#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用真实浏览器指纹伪装抓取页面, 突破 Cloudflare 等对普通自动化工具的拦截。

原理: 普通 curl/requests 的指纹(尤其是 JA3 TLS 指纹、HTTP2 设置)会被 CF 识别为
非浏览器而拦截。curl_cffi 的 `impersonate` 能模拟 Chrome 的 TLS/HTTP2 指纹, 对
"数据中心 IP + 真实浏览器指纹" 的普通页面(首页/详情/目录/正文)常常能拿到真实 HTML。
注意: 这只能过"被动指纹"检测; Turnstile 交互挑战、受保护的 ajax 接口依然过不了。

依赖:
    sudo pip3 install curl_cffi
    无 curl_cffi 时自动回退到 requests(过不了 CF, 但普通站可用)。

用法:
    python3 fetch_page.py <URL> [-o out.html] [--referer URL] [--impersonate chrome124]
    python3 fetch_page.py -i urls.txt        # 逐行读 URL, 各自存为 <序号>.html

取证用法(先取证铁律: 判别"cookie 判别型防爬"):
    # 不带 cookie 抓一次
    python3 fetch_page.py <正文页URL> -o no_cookie.html
    # 带 cookie 再抓一次(值来自 App 过 CF 后的 CookieJar, 或 bypass_cf.py 提取的 clearance)
    python3 fetch_page.py <正文页URL> -o with_cookie.html --cookie "is_human=xxx; cf_clearance=yyy"
    # 对比两次结果: 不带即被挖空、带了就有明文 => cookie 判别型, 不是 JS 渲染
"""
import sys
import argparse


def build_session(impersonate):
    """优先 curl_cffi 指纹伪装, 失败回退 requests。"""
    try:
        from curl_cffi import requests as cffi_requests
        sess = cffi_requests.Session(impersonate=impersonate)
        return sess, "curl_cffi(%s)" % impersonate
    except Exception as e:
        try:
            import requests
            return requests.Session(), "requests(无指纹伪装: %s)" % e
        except Exception as e2:
            print("两种 HTTP 库都不可用: %s / %s" % (e, e2))
            sys.exit(2)


def fetch(sess, url, referer, timeout=20, cookie=None, ua=None):
    headers = {
        "User-Agent": ua or ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    resp = sess.get(url, headers=headers, timeout=timeout, verify=False)
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="目标 URL; 或传 - 从标准输入逐行读")
    ap.add_argument("-o", "--output", help="保存 HTML 的文件路径")
    ap.add_argument("-i", "--input-file", help="从文件逐行读 URL")
    ap.add_argument("--referer", help="Referer 头")
    ap.add_argument("--cookie", help="Cookie 头(取证: 与不带 cookie 的抓取对比, 判别 cookie 判别型防爬)")
    ap.add_argument("--ua", help="自定义 User-Agent(默认安卓 Chrome)")
    ap.add_argument("--impersonate", default="chrome124", help="curl_cffi 指纹(默认 chrome124)")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    sess, backend = build_session(args.impersonate)
    print("[backend] %s" % backend, file=sys.stderr)

    urls = []
    if args.input_file:
        try:
            with open(args.input_file, encoding="utf-8-sig") as f:
                urls = [l.strip() for l in f if l.strip()]
        except (OSError, UnicodeDecodeError) as e:
            print("读取 URL 清单失败(%s): %s" % (args.input_file, e), file=sys.stderr)
            sys.exit(2)
    elif args.url and args.url != "-":
        urls = [args.url]
    elif not sys.stdin.isatty():
        urls = [l.strip() for l in sys.stdin if l.strip()]

    if not urls:
        print("未提供 URL。用法见 --help。")
        sys.exit(2)

    failed = []
    for idx, u in enumerate(urls):
        try:
            resp = fetch(sess, u, args.referer, args.timeout,
                         cookie=args.cookie, ua=args.ua)
            body = resp.text
            print("[%d] %s -> HTTP %s, %d 字节" % (idx, u, resp.status_code, len(body)), file=sys.stderr)
        except Exception as e:
            print("[%d] %s -> 失败: %s" % (idx, u, e), file=sys.stderr)
            failed.append(u)
            continue

        if args.input_file or (args.url == "-" and len(urls) > 1):
            out = "%d.html" % idx
        elif args.output:
            out = args.output
        else:
            out = None

        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(body)
            print("    已保存 %s" % out, file=sys.stderr)
        else:
            sys.stdout.write(body)

    if failed:
        # 有 URL 抓取失败必须非零退出: 管道/脚本调用方靠退出码判断是否真抓到内容。
        # 旧实现失败只打 stderr 后继续, 循环结束 exit 0 —— 调用方把"没抓到"当"抓到了"
        # 继续跑下一步(假绿), 是职责性缺陷。
        sys.exit(1)


if __name__ == "__main__":
    main()
