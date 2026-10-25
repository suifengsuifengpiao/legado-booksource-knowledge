#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webView 书源的本地实测器：用 Playwright 忠实模拟 Legado BackstageWebView 的行为。

解决什么问题
------------
书源 URL 带 `webView:true` 时（JS 挑战站、客户端解密站、Cookie 限流站），
纯 curl/requests **永远抓不到真实页面**。以前只能一律 SKIP 交真机，
于是「站点按 Cookie 限流」「等待字段名与目标 App 版本不匹配而静默失效」这类问题**本地一律测不出来**，
全靠用户真机才发现——这正是调试闭环最大的盲区。

本模块能测出来的三件事
----------------------
1. 页面到底能不能渲染出正文（真跑 JS，不猜）。
2. **连续请求会不会被限流**（同一 WebView 连搜多个关键词，对比命中数）。
   这是纯 HTTP 测不出来的：Tengine/阿里云盾这类多后端会话轮换，纯 HTTP 时通时不通。
3. **URL 行内选项的字段名是否真实存在**——写错字段 Gson 静默忽略，
   等待时间会退回 900ms，表现为「明明给了 8000 还是取空」。这里按源码合法字段校验。

模拟 Legado 的关键时序（对照 BackstageWebView.kt）
-------------------------------------------------
- 每次请求用**全新 Page**（等同全新 WebView，无历史栈），
  避免上一条记录的 `history.go(-1)` 污染下一次导航；
- 导航完成后等 `100ms + webWait`；
- 执行 `webJs`，返回**非空且非 "null"** 才算成功，否则按固定 1000ms 重试（上限 31 次）；
- 弹窗一律 dismiss（限流页的 `alert` 会阻塞后续脚本，与真机一致）。

用法
----
    from webview_probe import probe_webview
    r = probe_webview("https://x.com/search/?searchkey={{key}}",
                      opts={"webView": True, "webWait": 3000,
                            "webJs": "..."},
                      keywords=["系统", "逆袭"], sample_dir="./samples")
"""
import os
import re
import time
import json

# Legado 3.25 反编译版 AnalyzeUrl 的 UrlOption 字段（实证）。
# 写错名字不会被报错——Gson 不拒绝未知字段——只会静默忽略。
URL_OPTION_FIELDS = {
    "method", "charset", "headers", "body", "origin", "retry", "type",
    "webView", "webWait", "webJs", "js", "serverID",
}

# 3.25 不认识的等待字段（历史/官方版写法）：会被 Gson 静默丢弃
URL_OPTION_DEAD_WAIT = "webViewDelayTime"

# 常见误传字段 → 正确写法（3.25）
# ⚠️ 必须与 validate_booksource.py 的 URL_OPTION_TYPOS 保持一致,
# 否则同一字段一处报 error 给正解、另一处只降为"可能被忽略"的 warn —— 判定口径打架。
OPTION_TYPOS = {
    "webviewDelayTime": "webWait",
    "webDelay": "webWait",
    "delayTime": "webWait",
    "webViewDelay": "webWait",
    "webViewWait": "webWait",
    "webViewCache": "(不存在)",
    "source": "origin",
    "userAgent": "headers 里的 User-Agent",
}

DEFAULT_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")


def check_option_fields(opts):
    """校验 URL 行内选项字段名，返回 (errors, warns)"""
    errors, warns = [], []
    if not isinstance(opts, dict):
        return errors, warns
    if URL_OPTION_DEAD_WAIT in opts:
        if "webWait" in opts:
            warns.append("写了 webViewDelayTime=%s（3.25 不认识，会被静默丢弃），"
                         "同时有 webWait=%s（3.25 实际生效）。webViewDelayTime 多余，建议删掉"
                         % (opts[URL_OPTION_DEAD_WAIT], opts["webWait"]))
        else:
            errors.append("只写了 webViewDelayTime=%s：3.25 不认识它，会被静默丢弃、等待退回默认。"
                          "3.25 的等待字段是 webWait，请改成 webWait" % opts[URL_OPTION_DEAD_WAIT])
    for k in opts:
        if k == URL_OPTION_DEAD_WAIT:
            continue
        if k in URL_OPTION_FIELDS:
            continue
        if k in OPTION_TYPOS:
            errors.append("选项字段 '%s' 不存在，Legado 会静默忽略；正确写法: %s"
                          % (k, OPTION_TYPOS[k]))
        else:
            warns.append("选项字段 '%s' 不在 UrlOption 合法字段内，可能被静默忽略" % k)
    if opts.get("webJs") and "webWait" not in opts:
        warns.append("有 webJs 但没给 webWait：webJs 会让默认等待失效（只剩约 100ms），必须显式补上")
    if opts.get("bodyJs") and opts.get("webView"):
        warns.append("bodyJs 在 webView 模式下不生效（仅 OkHttp 分支执行）")
    if "webWait" in opts:
        ww = opts["webWait"]
        # 真机 Gson 把 webWait 解析成 Long, 非数字(字符串/带单位)直接抛 JsonSyntaxException,
        # AnalyzeUrl 失败 → 整个搜索请求报错。字段名检查抓不到这类值类型错误, 必须显式查。
        if isinstance(ww, bool) or not isinstance(ww, (int, float)):
            try:
                float(str(ww))
            except (TypeError, ValueError):
                errors.append("webWait 的值 %r 不是数字：真机 Gson 解析 Long 会抛异常，"
                              "整个搜索请求失败，请改成毫秒数字(如 3000)" % (ww,))
    js = str(opts.get("webJs") or "")
    if re.search(r"\b(async|await)\b|Promise|\.then\s*\(", js):
        errors.append("webJs 含 async/await/Promise：evaluateJavascript 拿到的是 "
                      "JSON 序列化的 '{}'，非空且非 null → Legado 判定成功并静默返回空内容")
    return errors, warns


def detect_ratelimit(html, url=""):
    """识别「按 Cookie 限流」的返回页。返回 (是否限流, 说明)"""
    if not html:
        return False, ""
    low = html[:2000]
    if len(html) < 500 and re.search(r"alert\s*\(\s*['\"]", low):
        return True, ("返回极短页面(%d字节)且含 alert → 典型的「搜索间隔」限流页"
                      % len(html))
    if re.search(r"(搜索间隔|访问过于频繁|请求过于频繁|操作太快)", html[:2000]):
        return True, "页面文案含频率限制提示"
    return False, ""


def _count_result_links(out):
    """结果链接数: 通用退化判据(非 bookbox 类站点用)——统计页面里 `<a ` 出现次数。"""
    return out.count("<a ") if isinstance(out, str) else 0


def _looks_like_result_list(out):
    """兜底: 未命中标记但有若干结果链接, 也视作取到了列表(避免非 bookbox 站点永远判 0 命中)。"""
    return isinstance(out, str) and _count_result_links(out) >= 3


def probe_webview(url_template, opts=None, keywords=None, sample_dir=None,
                  user_agent=DEFAULT_UA, per_keyword_gap=0.8, verbose=True):
    """用 Playwright 模拟 Legado WebView 请求。

    参数
    ----
    url_template : 含 `{{key}}` 占位符的 URL
    opts         : URL 行内选项 dict（webView / webWait / webJs / charset）
    keywords     : 要依次搜索的关键词列表，用于测限流
    sample_dir   : 样本保存目录

    返回 dict：
        ok            是否有任一关键词取到内容
        rate_limited  是否命中限流
        results       每个关键词的命中书名数
        option_errors / option_warns  选项字段问题
        sample        保存下来的搜索页 HTML 路径
        reason        失败原因
    """
    res = {
        "ok": False, "rate_limited": False, "results": {}, "sample": None,
        "option_errors": [], "option_warns": [], "reason": "", "available": False,
    }
    opts = opts or {}
    # marker 是 probe 侧配置, 不是书源 URL 字段, 排除后再校验, 否则会误报"未知字段"
    res["option_errors"], res["option_warns"] = check_option_fields(
        {k: v for k, v in opts.items() if k != "marker"})

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        res["reason"] = "playwright 未安装，无法实测 webView: %s" % e
        return res

    keywords = keywords or ["天官赐福", "斗破苍穹"]
    try:
        delay_ms = int(float(opts.get("webWait") or 1000))
    except (TypeError, ValueError):
        delay_ms = 1000
    webjs = opts.get("webJs") or "document.documentElement.outerHTML"
    intervals = [1000]
    # 结果判定标记: 默认 bookbox(主流模板类), 可通过 opts["marker"] / --marker / env RESULT_MARKER 覆盖,
    # 让非 bookbox 类站点也能被正确判定(避免永远判失败/0 命中)。
    marker = opts.get("marker") or os.environ.get("RESULT_MARKER") or "bookbox"

    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                ctx = b.new_context(user_agent=user_agent,
                                    viewport={"width": 412, "height": 869})
                hit_any = False
                for i, k in enumerate(keywords):
                    from urllib.parse import quote
                    u = (url_template.replace("{{key}}", quote(k))
                         .replace("{{page}}", "1"))
                    # 关键：每次用全新 Page，等同 Legado 每次新建 WebView（无历史栈）
                    page = ctx.new_page()
                    try:
                        page.on("dialog", lambda d: d.dismiss())
                        try:
                            page.goto(u, wait_until="load", timeout=25000)
                        except Exception as e:
                            # 导航失败不能静默吞掉: 否则超时/断网的空白页会被当成"页面确实没内容",
                            # 与"站点 JS 渲染失败""被 WAF 拦截"完全无法区分(虚假安全感)。
                            print("  [webView] 导航失败(%s): %s —— 跳过本关键词, 当作未取到内容"
                                  % (type(e).__name__, str(e)[:120]))
                            time.sleep(1.0)
                            continue
                        time.sleep(delay_ms / 1000.0 + 0.5)
                        out = ""
                        for attempt in range(31):
                            try:
                                out = page.evaluate("() => " + webjs)
                            except Exception:
                                out = ""
                            # 对齐 Android evaluateJavascript: null/undefined -> JSON 字符串 "null",
                            # 数字/对象 -> JSON 序列化字符串。不转换的话 None/数字会让下一行
                            # `marker in out` TypeError, 整个探测中断(浏览器句柄也漏掉)。
                            if out is None:
                                out = "null"
                            elif not isinstance(out, str):
                                out = json.dumps(out, ensure_ascii=False)
                            if out and out != "null" and (marker in out or _looks_like_result_list(out)):
                                break
                            time.sleep(intervals[0] / 1000.0)
                    finally:
                        # 收集本次请求后的 cookie 名, 用于判断限流 cookie 是否被清掉。
                        # 必须 try 包裹: finally 里再抛异常会吞掉 try 块的真实错误, 调试时最怕丢原异常。
                        try:
                            cookies = [c["name"] for c in ctx.cookies()]
                        except Exception:
                            cookies = []
                        if verbose and cookies:
                            print("    [cookie] 请求后 jar: %s" % ",".join(cookies))
                        page.close()

                    n = 0
                    if out and (marker in out or _looks_like_result_list(out)):
                        n = out.count('class="%s"' % marker) if ('class="%s"' % marker in out) else _count_result_links(out)
                        hit_any = True
                        if sample_dir and not res["sample"]:
                            os.makedirs(sample_dir, exist_ok=True)
                            p = os.path.join(sample_dir, "search.html")
                            with open(p, "w", encoding="utf-8") as _f:
                                _f.write(out)
                            res["sample"] = p
                    else:
                        limited, why = detect_ratelimit(out or page_html_fallback(ctx, u))
                        if limited:
                            res["rate_limited"] = True
                            res["reason"] = why
                    res["results"][k] = n
                    if verbose:
                        print("    [webView] 搜[%s] 命中=%d%s"
                              % (k, n, "  <- 疑似限流" if n == 0 and res["rate_limited"] else ""))
                    time.sleep(per_keyword_gap)
            finally:
                # 循环中途异常也必须收掉浏览器, 否则探测一崩就漏一个 chromium 进程
                try:
                    b.close()
                except Exception:
                    pass

        res["available"] = True
        res["ok"] = hit_any
        if not hit_any and not res["reason"]:
            res["reason"] = ("webView 渲染后仍未取到内容：JS 挑战可能没通过，"
                             "或 webWait=%d 不足（客户端解密站要 8000+）" % delay_ms)
        return res
    except Exception as e:
        res["reason"] = "Playwright 实测异常: %s" % str(e)[:200]
        return res


def page_html_fallback(ctx, url, wait=2.5):
    """webJs 没产出内容时，退回读页面源码，用于判断限流特征"""
    try:
        page = ctx.new_page()
        page.on("dialog", lambda d: d.dismiss())
        try:
            page.goto(url, wait_until="load", timeout=20000)
        except Exception:
            pass
        time.sleep(wait)
        h = page.content()
        page.close()
        return h
    except Exception:
        return ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 webview_probe.py <书源.json> [--keyword K] [--marker M] [--workdir D]")
        sys.exit(2)
    src_path = sys.argv[1]
    if src_path in ("-h", "--help"):
        print("用法: python3 webview_probe.py <书源.json> [--keyword K] [--marker M] [--workdir D]")
        print("  --keyword K  搜索关键词(默认取书源自带/内置测试词)")
        print("  --marker M   命中判据(默认 bookbox; 非 bookbox 类站点请换, 见 1.13.22 F6)")
        print("  --workdir D  工作目录(默认临时目录)")
        sys.exit(0)
    # 裸 open 会让任何手滑(--help / 拼错路径)直接甩 Python 堆栈, 用户看不懂、也看不出是自己打错了。
    # 同类脚本的对照: realcheck.py 走 argparse 天然友好; validate_booksource.py 有 try/except。
    # 本文件 1.13.24 审查前是唯一裸 open 的, 冒烟(逐个脚本跑 --help)才抓出来。
    if src_path.startswith("-") or not os.path.isfile(src_path):
        print("用法: python3 webview_probe.py <书源.json> [--keyword K] [--marker M] [--workdir D]")
        if not src_path.startswith("-"):
            print("书源文件不存在: %s" % src_path)
        sys.exit(2)
    try:
        with open(src_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("无法读取/解析 JSON: %s" % e)
        sys.exit(2)
    # 空数组/非对象书源: data[0] 会 IndexError 裸崩; 与 realcheck.load_source 同样防护
    src = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    su = src.get("searchUrl") or ""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from verify_booksource import split_url_options
    url, opts = split_url_options(su)
    kw = []
    for i, a in enumerate(sys.argv):
        if a == "--keyword" and i + 1 < len(sys.argv):
            kw = [sys.argv[i + 1]]
    marker = None
    for i, a in enumerate(sys.argv):
        if a == "--marker" and i + 1 < len(sys.argv):
            marker = sys.argv[i + 1]
    if marker:
        opts = dict(opts or {})
        opts["marker"] = marker
    wd = None
    for i, a in enumerate(sys.argv):
        if a == "--workdir" and i + 1 < len(sys.argv):
            wd = sys.argv[i + 1]
    print("URL:", url)
    print("选项:", json.dumps(opts, ensure_ascii=False) if opts else "无")
    r = probe_webview(url, opts, keywords=kw or None, sample_dir=wd)
    print(json.dumps({k: v for k, v in r.items() if k != "results"},
                     ensure_ascii=False, indent=2))
    print("各关键词命中:", r["results"])
    sys.exit(0 if r["ok"] else 1)
