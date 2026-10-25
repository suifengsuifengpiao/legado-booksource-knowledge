#!/usr/bin/env python3
"""bypass_cf.py — 用真实浏览器(playwright + 系统 chromium)突破 Cloudflare 挑战, 提取 clearance Cookie。

======================= 合规与使用边界(务必先读) =======================
本工具仅用于「自有书源的本地调试验证」。

- 沙盒是数据中心 IP, Cloudflare 对这类 IP 的强 Turnstile 未必放行; 本工具「尽力而为」,
  过不了会如实返回 cf_passed=False, 不要反复重试。
- 提取的 cf_clearance 与「请求所用 IP + UA」强绑定: 数据中心 IP 拿到的 clearance,
  在手机 Legado App(家庭/移动 IP)上通常无效。
- 因此【不把 Cookie 写死进书源】, 它仅用于:
    (1) 本地 verify 验证 CF 站点页面能否解析;
    (2) 诊断「这个站到底能不能用普通书源做」(能过=可尝试, 过不了=需 WebView 或放弃)。
======================================================================

用法(命令行):
  python3 bypass_cf.py <URL>                         # 打印 HTML 长度 / 是否 CF / 是否拿到 clearance
  python3 bypass_cf.py <URL> --out page.html         # 保存过 CF 后的页面 HTML
  python3 bypass_cf.py <URL> --cookies-out cf.json   # 保存 cookie 字典(供人工查看)
  python3 bypass_cf.py <URL> --wait-text "正文"       # 等待某文本出现再判定通过(更稳)

作为库调用(供 verify_booksource.py 注入):
  from bypass_cf import get_cf_session
  session, ua, ok = get_cf_session("https://site.com/")
  if ok:
      html = session.get("https://site.com/book/1").text   # 已带 clearance, 可抓子页
"""
import argparse
import json
import os
import shutil
import sys
import time

# 系统 chromium 优先(UA 指纹更接近用户真机); 找不到再回退 playwright 自带浏览器。
# 旧实现硬编码 /usr/bin/chromium: 用户机没这个路径时 launch 直接抛异常, 连降级都没有。
CHROME_CANDIDATES = ("/usr/bin/chromium", "/usr/bin/chromium-browser",
                     "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None  # None -> playwright 用自带 chromium
# 强挑战特征: 标题/正文明确是 CF 验证页(无论字节多少都判为挑战页)
CF_STRONG = [
    "just a moment", "attention required", "verify you are human",
    "enable javascript and cookies to continue", "checking your browser",
    "ddos-guard", "performance & security by cloudflare",
    "访问验证", "正在检查您的浏览器", "请稍候", "检查您的浏览器",
]
# 弱特征: 仅说明页面嵌了 CF 防御 JS; 真实内容页也常含这些, 只有当内容很短(挑战页壳)才算挑战
CF_WEAK = ["cf-chl", "challenge-platform", "cf_captcha"]
# goto 单次最长等待(挑战页本身 domcontentloaded 很快, 真正等待放在循环里)
GOTO_TIMEOUT = 20000


def _looks_like_browser_error(html):
    """Chromium 网络错误页(DNS/连接失败/超时都会渲染它)。

    特征与字节数无关: 错误页内嵌大量样式脚本, 可达 100KB+, 用长度判会漏。
    goto 抛异常后拿到的就是这个 —— 它不是站点响应, 绝不能当"非 CF 挑战页"成功返回。
    """
    if not html:
        return True
    return ('id="main-frame-error"' in html
            or "net::ERR_" in html
            or "ERR_NAME_NOT_RESOLVED" in html
            or "ERR_CONNECTION_REFUSED" in html
            or "ERR_CONNECTION_TIMED_OUT" in html
            or "ERR_ADDRESS_UNREACHABLE" in html)


def looks_like_cf(html):
    """粗判当前 HTML 是否仍是 CF 挑战页(主体), 而非仅嵌了 CF 防御 JS 的真实内容页。

    判断标准:
      - 命中强特征(标题/正文是验证页, 含中英文 CF 文案) → 直接判挑战页
      - 仅命中弱特征(cf-chl 等防御 JS)时, 只有内容极短(挑战页壳, <5KB)才判挑战;
        内容较长的真实页面即使嵌了 cf-chl 也判非挑战
    """
    if not html:
        return False
    low = html.lower()
    if any(m in low for m in CF_STRONG):
        return True
    if any(m in low for m in CF_WEAK):
        return len(html) < 5000  # 真实内容页通常很长, 挑战页壳很短
    return False


def _click_turnstile(page):
    """尽力点击 Turnstile 复选框(在子 frame 内)。可能失败/无效, 不保证。"""
    try:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                box = frame.locator("input[type=checkbox]").first
                if box.count() and box.is_visible():
                    box.click(timeout=4000)
                    return True
            except Exception:
                pass
        cb = page.locator("input[type=checkbox]").first
        if cb.count() and cb.is_visible():
            cb.click(timeout=4000)
            return True
    except Exception:
        pass
    return False


def bypass(url, wait_text=None, click_turnstile=True, timeout_ms=45000):
    """真实渲染访问 url, 尝试过 CF。返回 (html, cookies_list, ua, cf_passed)。

    cookies_list 为 playwright 的 ctx.cookies() 结构(list of dict: name/value/domain/path/expires)。
    cf_passed = 是否成功拿到 cf_clearance(或页面本就不是 CF 挑战页)。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        sys.stderr.write(
            "[bypass_cf] 未安装 playwright 或浏览器内核, 无法突破 CF 挑战: %s\n"
            "  安装: pip install playwright && playwright install chromium\n" % e)
        return "", [], "", False

    start = time.time()
    limit = timeout_ms / 1000.0
    launch_kwargs = {"headless": True,
                     "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
    chrome = find_chrome()
    if chrome:
        launch_kwargs["executable_path"] = chrome
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT)
                goto_ok = True
            except Exception:
                # 即便 goto 超时, 也可能已经拿到挑战页/部分内容 —— 但浏览器网络错误页
                # 也是这个路径产出的, 下面用 goto_ok + 长度把两者区分开。
                goto_ok = False

            try:
                ua = page.evaluate("navigator.userAgent")
            except Exception:
                ua = ""

            clicked = False
            while time.time() - start < limit:
                try:
                    cookies = ctx.cookies()
                except Exception:
                    cookies = []
                clearance = any(c.get("name") == "cf_clearance" for c in cookies)
                try:
                    html = page.content()
                except Exception:
                    html = ""

                if clearance:
                    # 拿到 clearance 后再重载一次, 确保取到真实内容(而非挑战页残留)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT)
                        html = page.content()
                    except Exception:
                        pass
                    return html, cookies, ua, True
                if wait_text and wait_text in html:
                    return html, cookies, ua, True
                if not html or (not goto_ok and (len(html) < 5000 or _looks_like_browser_error(html))):
                    # 空内容或「goto 报错 + 短页面」不可当"非挑战页成功":
                    # 站点没加载/浏览器网络错误页也是这个形态, 旧逻辑会返回
                    # cf_passed=True —— 站点根本没打开却报成功, 是文件头承诺
                    # "过不了如实返回 False"要堵的假绿。继续等, 超时后如实报 False。
                    time.sleep(1)
                    continue
                if looks_like_cf(html):
                    if click_turnstile and not clicked:
                        if _click_turnstile(page):
                            clicked = True
                    time.sleep(3)
                else:
                    # 页面本就不是 CF 挑战页 → 视为成功
                    return html, cookies, ua, True

            # 超时: 返回当前状态, cf_passed 取决于是否拿到 clearance
            try:
                html = page.content()
                cookies = ctx.cookies()
            except Exception:
                html, cookies = "", []
            return html, cookies, ua, any(c.get("name") == "cf_clearance" for c in cookies)
        finally:
            # 循环中途异常也必须收掉浏览器, 否则崩一次漏一个 chromium 进程
            try:
                browser.close()
            except Exception:
                pass


def get_cf_session(url, timeout_ms=45000):
    """返回 (curl_cffi.Session 或 None, ua, ok)。Session 已注入 clearance cookie 与对应 UA。

    供 verify_booksource.py 在检测到 CF 挑战页时调用: 过 CF 后继续用该 session 抓子页。
    """
    try:
        from curl_cffi import requests as cffi_req
    except Exception:
        return None, "", False

    html, cookies, ua, ok = bypass(url, timeout_ms=timeout_ms)
    if not ok:
        return None, ua, False
    s = cffi_req.Session(impersonate="chrome124")
    if ua:
        s.headers["User-Agent"] = ua
    for c in cookies:
        try:
            s.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"))
        except Exception:
            pass
    return s, ua, True


def main():
    ap = argparse.ArgumentParser(description="用真实浏览器突破 Cloudflare 挑战, 提取 clearance Cookie")
    ap.add_argument("url", help="目标 URL")
    ap.add_argument("--out", help="保存过 CF 后的 HTML 到此文件")
    ap.add_argument("--cookies-out", help="保存 cookie 字典(JSON)到此文件")
    ap.add_argument("--wait-text", help="等待该文本出现再判定通过(更稳)")
    ap.add_argument("--timeout", type=int, default=45000, help="总超时毫秒, 默认 45000")
    args = ap.parse_args()

    html, cookies, ua, ok = bypass(args.url, wait_text=args.wait_text, timeout_ms=args.timeout)
    print("UA: %s" % ua)
    got_cf = any(c.get("name") == "cf_clearance" for c in cookies)
    print("HTML长度: %d" % len(html))
    print("是否Cloudflare挑战页: %s" % looks_like_cf(html))
    print("是否成功获取可用页面: %s" % ok)
    print("是否拿到cf_clearance: %s" % got_cf)
    print("Cookie清单: %s" % ", ".join(c.get("name", "") for c in cookies))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as _f:
            _f.write(html)
        print("已保存 HTML -> %s" % args.out)
    if args.cookies_out:
        with open(args.cookies_out, "w", encoding="utf-8") as _f:
            json.dump(cookies, _f, ensure_ascii=False, indent=2)
        print("已保存 Cookie -> %s" % args.cookies_out)


if __name__ == "__main__":
    main()
