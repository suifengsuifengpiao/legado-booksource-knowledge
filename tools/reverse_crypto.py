#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_crypto.py — 站点加密参数(请求签名)诊断工具。

======================= 它能做什么 / 不能做什么 =======================
能:
  - 用真实浏览器(playwright+chromium)打开站点, 拦截所有 XHR/fetch 请求,
    识别出「带签名/令牌的神秘参数」(sign/_signature/token/x-csrf-token/nonce/ts...)。
  - 下载页面引用的 JS 文件, 在源码里定位这些参数的「生成点」(文件+代码段), 让你知道去哪读算法。
  - 在浏览器真实环境里探测 window 上常见的签名函数(sign/encrypt/getSign...), 并尝试调用复现。
  - 输出诊断结论: 该站是否启用请求签名、参数清单、能否用书源 @js 复现、给出落地建议。

不能(诚实边界):
  - 不会全自动写出混淆后的加密算法(那需要人工读 JS / 用 Node 复现)。本工具给「线索 + 骨架」。
  - 若签名依赖浏览器指纹(canvas/WebGL/WASM/设备信息), 书源(@js 无这些环境)基本无解, 会如实判定。
======================================================================

用法:
  python3 reverse_crypto.py <站点首页或搜索页URL> [--keyword 剑来] [--out report.json]
"""
import argparse
import json
import os
import re
import sys
import tempfile
from urllib.parse import urljoin, urlparse, parse_qs

# 强特征: 名称或子串命中即记(这些是签名/令牌的高置信信号)
STRONG = [
    "sign", "signature", "_signature", "token", "xsrf", "csrf", "nonce",
    "timestamp", "x-csrf-token", "x-sign", "x-token", "authorization",
    "appkey", "secret", "hmac", "salt", "w_rid", "wts", "buvid", "wbi",
    "vk", "smid", "traceparent",
]
# 弱特征: 仅精确相等才记(避免 t/ts/v/key 误伤 content-type/user-agent 等常见头)
WEAK = {"t", "ts", "v", "key"}
# 常见 window 级签名函数名(用于浏览器内探测)
WIN_SIGN_FUNCS = ["sign", "encrypt", "getSign", "makeSign", "signature",
                 "genSign", "createSign", "getToken", "makeToken", "calcSign"]

JS_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', re.I)


def _resolve_chrome():
    """系统 chromium 优先, 回退 playwright 自带浏览器(与 bypass_cf 同一套候选)。

    旧实现硬编码 /usr/bin/chromium: 用户机没这个路径时 launch 直接抛异常。
    """
    try:
        from bypass_cf import find_chrome
        return find_chrome()
    except Exception:
        pass
    for p in ("/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
        if os.path.isfile(p):
            return p
    return None


def _decode_js(raw):
    """JS 字节流解码: utf-8 严格优先, 失败退 gb18030。

    旧实现用 r.text(requests 无 charset 头时按 latin-1 兜底) —— 无 charset 声明的
    GBK JS 会整文件乱码, 下游 locate() 的代码段定位全部失效。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")


# 模块加载时解析一次: 系统 chromium 优先, 回退 playwright 自带浏览器(None)
CHROME_PATH = _resolve_chrome()


def _is_suspect(key):
    """判断参数/头名是否疑似签名相关。强特征子串命中; 弱特征仅精确命中。"""
    k = (key or "").lower()
    if k in WEAK:
        return True
    return any(s in k for s in STRONG)


def _collect_params(url, method, headers, post_data):
    """从 query / header / body 中提取可疑参数名。"""
    found = set()
    # query
    try:
        for k in parse_qs(urlparse(url).query).keys():
            if _is_suspect(k):
                found.add(k)
    except Exception:
        pass
    # headers
    for k in (headers or {}).keys():
        if _is_suspect(k):
            found.add(k)
    # body(form/json)
    if post_data:
        for m in re.findall(r'["\']?([A-Za-z0-9_]+)["\']?\s*[:=]', post_data[:2000]):
            if _is_suspect(m):
                found.add(m)
    return sorted(found)


def intercept(url, keyword=None, listen_ms=8000):
    """打开页面并监听请求, 返回请求列表(含可疑参数标注)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        # 未装 playwright 时友好降级: 旧实现裸抛堆栈, 用户看不出缺什么
        print("[错误] 需要 playwright: pip install playwright && playwright install chromium (%s)" % e,
              file=sys.stderr)
        return [], [], ""
    reqs = []
    launch_kwargs = {"headless": True,
                     "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
    if CHROME_PATH:
        launch_kwargs["executable_path"] = CHROME_PATH
    with sync_playwright() as p:
        b = p.chromium.launch(**launch_kwargs)
        try:
            ctx = b.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()

            def on_req(req):
                try:
                    hdrs = dict(req.headers)
                except Exception:
                    hdrs = {}
                suspects = _collect_params(req.url, req.method, hdrs, req.post_data or "")
                reqs.append({
                    "url": req.url,
                    "method": req.method,
                    "resource_type": req.resource_type,
                    "has_suspect": bool(suspects),
                    "suspects": suspects,
                    "headers_keys": sorted(hdrs.keys()),
                    "post_data": (req.post_data or "")[:500],
                })

            page.on("request", on_req)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            # 尝试触发搜索(尽力)
            if keyword:
                try:
                    sel = "input[type=search], input[name*=search i], input[placeholder*=搜索 i], input[placeholder*=search i]"
                    box = page.locator(sel).first
                    if box.count():
                        box.fill(keyword)
                        box.press("Enter")
                except Exception:
                    pass
            page.wait_for_timeout(listen_ms)
            # 探测 window 签名函数
            win_sign = []
            try:
                win_sign = page.evaluate(
                    """() => {
                        const names = %s;
                        const out = [];
                        for (const n of names) {
                            try { if (typeof window[n] === 'function') out.push(n); } catch(e){}
                        }
                        return out;
                    }""" % json.dumps(WIN_SIGN_FUNCS)
                )
            except Exception:
                win_sign = []
            # 提取页面 JS 引用
            try:
                html = page.content()
            except Exception:
                html = ""
        finally:
            # 监听/求值中途异常也必须收掉浏览器, 否则崩一次漏一个 chromium 进程
            try:
                b.close()
            except Exception:
                pass
    return reqs, win_sign, html


def download_js(html, base_url, out_dir, limit=25):
    """下载页面引用的 JS 到 out_dir, 返回 [(js_url, local_path)]。"""
    import requests
    urls = JS_SRC_RE.findall(html or "")
    results = []
    seen = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        if len(results) >= limit:
            break
        absu = urljoin(base_url, u)
        try:
            r = requests.get(absu, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) < 2_000_000:
                fn = "js_%d.js" % len(results)
                # r.content + 显式解码: 不用 r.text(无 charset 头时 latin-1 兜底 -> GBK 乱码)
                open(os.path.join(out_dir, fn), "w", encoding="utf-8").write(_decode_js(r.content))
                results.append((absu, os.path.join(out_dir, fn)))
        except Exception:
            pass
    return results


def locate(js_files, suspects):
    """在每个 JS 文件里 grep 可疑参数名, 返回 {param: [{file, snippet}]}。"""
    out = {}
    for param in suspects:
        hits = []
        for js_url, path in js_files:
            try:
                txt = open(path, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for m in re.finditer(re.escape(param), txt):
                s, e = max(0, m.start() - 80), min(len(txt), m.end() + 80)
                snippet = txt[s:e].replace("\n", " ")
                hits.append({"file": os.path.basename(path), "snippet": snippet[:200]})
                if len(hits) >= 3:
                    break
        if hits:
            out[param] = hits
    return out


def diagnose(url, keyword=None, out=None, listen_ms=8000):
    tmp = tempfile.mkdtemp(prefix="legado_crypto_")
    print("[1/4] 打开页面并监听请求(含触发搜索)...")
    reqs, win_sign, html = intercept(url, keyword=keyword, listen_ms=listen_ms)
    xhr = [r for r in reqs if r["resource_type"] in ("xhr", "fetch") or ".json" in r["url"]]
    suspect_reqs = [r for r in reqs if r["has_suspect"]]
    all_suspects = sorted({s for r in reqs for s in r["suspects"]})

    print("[2/4] 下载页面 JS 并定位签名生成点...")
    js_files = download_js(html, url, tmp)
    locations = locate(js_files, all_suspects) if all_suspects else {}

    print("[3/4] 生成诊断结论...")
    enabled = bool(all_suspects)
    # 判定落地可行性: 若签名依赖指纹类关键字, 倾向无解
    fingerprint_kw = ["canvas", "webgl", "fingerprint", "navigator", "deviceid", "touch", "ua.substr", "getParameter"]
    needs_fp = any(any(k in h["snippet"].lower() for h in hits) for hits in locations.values() for k in fingerprint_kw) if locations else False

    if not enabled:
        verdict = "无明显请求签名(普通参数即可, 书源直接写 URL/header)"
        advice = "无需加密逆向。直接用 searchUrl + header(UA/Referer/Cookie) 即可, 重点在 XPath/JSONPath 命中。"
    elif needs_fp:
        verdict = "强校验: 签名依赖浏览器指纹, 书源 @js 大概率无法复现"
        advice = ("签名算法引用了 canvas/webgl/navigator 等浏览器指纹, Legado 的 @js 运行环境无这些 API, "
                  "纯书源无法实现。建议: 改用 App WebView 模式, 或放弃该站。"
                  "若坚持, 可把签名函数抽出来用 Node 预计算(服务器方案), 但无法塞进普通书源。")
    else:
        verdict = "可尝试用 @js 在书源中复现签名"
        advice = ("签名参数多为 timestamp/nonce + 固定 key 的哈希(md5/sha1/hmac)。"
                  "请在下方『生成点』代码段中读出算法, 用 Legado 规则里的 @js: 段生成该参数, 挂到 searchUrl。"
                  "示例骨架:\n"
                  "  searchUrl.url: /search?q={{key}}&t={{...}}&sign={{js}}\n"
                  "  (在规则区用 @js: 计算 sign, 参考 parse-paths.md 的 JS 注入写法)")

    report = {
        "url": url,
        "keyword": keyword,
        "enabled_signature": enabled,
        "suspect_params": all_suspects,
        "suspect_requests": [
            {"url": r["url"], "method": r["method"], "suspects": r["suspects"]}
            for r in suspect_reqs
        ],
        "xhr_count": len(xhr),
        "total_requests": len(reqs),
        "window_sign_functions": win_sign,
        "locations": locations,
        "verdict": verdict,
        "booksource_advice": advice,
        "js_dir": tmp,
    }
    if out:
        json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return report


def _print_report(r):
    print("\n" + "=" * 56)
    print("加密参数诊断报告")
    print("=" * 56)
    print("目标: %s" % r["url"])
    print("是否启用请求签名 : %s" % r["enabled_signature"])
    print("可疑参数         : %s" % (", ".join(r["suspect_params"]) if r["suspect_params"] else "无"))
    print("window签名函数   : %s" % (", ".join(r["window_sign_functions"]) if r["window_sign_functions"] else "未探测到"))
    print("监听请求数/带签名: %d / %d" % (r["total_requests"], len(r["suspect_requests"])))
    if r["suspect_requests"]:
        print("\n-- 带签名的请求(节选) --")
        for sr in r["suspect_requests"][:5]:
            print("  [%s] %s" % (sr["method"], sr["url"][:90]))
            print("        参数: %s" % ", ".join(sr["suspects"]))
    if r["locations"]:
        print("\n-- 签名生成点(JS代码段, 去这里读算法) --")
        for param, hits in r["locations"].items():
            print("  ◇ %s" % param)
            for h in hits[:2]:
                print("      %s: …%s…" % (h["file"], h["snippet"]))
    print("\n结论: %s" % r["verdict"])
    print("\n书源落地建议:\n  %s" % r["booksource_advice"])
    print("\n(JS 源码已下载到: %s )" % r["js_dir"])


def main():
    ap = argparse.ArgumentParser(description="站点加密参数(请求签名)诊断")
    ap.add_argument("url")
    ap.add_argument("--keyword", help="触发搜索用的关键词")
    ap.add_argument("--out", help="诊断报告保存为 JSON")
    ap.add_argument("--listen", type=int, default=8000, help="监听毫秒数, 默认 8000")
    args = ap.parse_args()
    r = diagnose(args.url, keyword=args.keyword, out=args.out, listen_ms=args.listen)
    _print_report(r)
    if args.out:
        print("\n报告已保存 -> %s" % args.out)


if __name__ == "__main__":
    main()
