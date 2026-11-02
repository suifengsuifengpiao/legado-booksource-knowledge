#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
请求层闸（第五道闸）· check_request_layer.py
=============================================
用途：在把书源交给宿主（Legado）之前，模拟宿主对 **URL / 请求参数** 的解析，
      抓出「解析层四道闸永远看不到」的错误。

由来（2026-11-02 duomle 真机事故）：
  - exploreUrl 用 JSON 数组格式，却把 ,{"webView":true} 直接塞进 url 字符串未转义
    → 宿主 gson 抛 MalformedJsonException: Unterminated object at line 1 column 74 path $[0].url
    → 发现页整段崩溃，而 validate / test_parse 全绿（它们不碰 URL 字符串）
  - searchUrl 同时写 method:POST 与 webView:true
    → Android WebView 只能 GET，POST body 丢失 → 服务端收不到关键词 → 列表为空
    → 真机日志「获取书籍列表 → 列表为空，按详情页解析」→ 0 本

检查项：
  R1 exploreUrl 语法：以 [ 开头必须为合法 JSON（逐项 title/url）
  R2 exploreUrl 文本行格式：每行 标题::URL（以 @js: / <js> 开头时为 JS 动态发现，
     本闸不解析 JS，转 NOTE 提示另验——手机小说真机已验证 @js: 形态合法）
  R3 exploreUrl 各项 URL：内嵌选项 ,{...} 二次解析；相对路径在 bookSourceUrl
     非空时由宿主拼接（合法），bookSourceUrl 为空才报 ERROR
  R4 searchUrl 结构 + method 与 webView 互斥（相对路径同 R3 口径）
  R5 易失地址启发式（路径含 4+ 位数字，需多会话复验）
  R6 GET searchUrl 里的 {{key}} 中文编码提示：GET 的查询串由宿主 AnalyzeUrl
     编码与否取决于写法，若未编码中文关键词可能取空——WARN 提示改
     {{java.encodeURI(key)}} 或实测确认
  R7 bookSourceUrl 协议与各规则 URL 协议一致性

退出码：0 = 无 ERROR；1 = 有 ERROR
用法：python3 check_request_layer.py <书源.json> [--strict]
"""
import json
import re
import sys
import os

RED = "\033[31m"
YEL = "\033[33m"
GRN = "\033[32m"
CYN = "\033[36m"
RST = "\033[0m"


class Result:
    def __init__(self):
        self.errors = []
        self.warns = []
        self.notes = []

    def err(self, code, msg):
        self.errors.append((code, msg))

    def warn(self, code, msg):
        self.warns.append((code, msg))

    def note(self, code, msg):
        self.notes.append((code, msg))


def split_options(raw):
    """把 'url,{"a":1}' 拆成 (url, options_dict|None, err)。
    从右往左找最后一个 ',{'，避免 body 里含 { 时误切。"""
    s = raw.strip()
    idx = s.rfind(",{")
    if idx == -1:
        return s, None, None
    url_part = s[:idx].strip()
    opt_part = s[idx + 1:].strip()  # 保留 { 开头
    try:
        opt = json.loads(opt_part)
        if not isinstance(opt, dict):
            return url_part, None, f"选项不是 JSON 对象：{opt_part[:80]}"
        return url_part, opt, None
    except Exception as e:
        return url_part, None, f"选项 JSON 非法（{e}）：{opt_part[:120]}"


def check_explore(explore, res, base=""):
    if not explore:
        res.note("R1", "exploreUrl 为空，跳过发现页检查")
        return

    # @js: / <js> 开头 = JS 动态发现，宿主先 evalJS 再用返回值；本闸不解析 JS，
    # 按文本行/JSON 逐行解析只会刷出成片误报（亲亲小说 15 条全是这类）。
    # 手机小说书源真机已验证 @js: exploreUrl 合法。
    if re.match(r"^\s*(@js:|<js>)", explore):
        res.note("R1", "exploreUrl 为 JS 动态生成（@js:/<js>），本闸不解析 JS；"
                       "JS 语法另用 js_layer_check.py / 真机验证")
        return

    is_json = explore.lstrip().startswith("[")
    items = []

    if is_json:
        try:
            arr = json.loads(explore)
        except Exception as e:
            # 尽量给出列号，对齐宿主 gson 的报错位置
            col = getattr(e, "colno", None)
            pos = f"，约第 {col} 列" if col else ""
            res.err("R1", f"exploreUrl 声明为 JSON 数组但解析失败{pos}：{e}")
            # 错误定位：找出第一个可疑的未转义内嵌选项
            m = re.search(r'"[^"]*?,\{"', explore)
            if m:
                res.err("R1", f"疑似未转义的内嵌选项（此处双引号提前闭合字符串）：…{explore[max(0,m.start()-40):m.end()+40]}…")
                res.err("R1", '修法一：内层引号转义为 \\" ；修法二（更稳）：改用文本行格式 标题::URL,{"webView":true}')
            return
        if not isinstance(arr, list) or not arr:
            res.err("R1", "exploreUrl JSON 不是非空数组")
            return
        for i, it in enumerate(arr):
            if not isinstance(it, dict):
                res.err("R1", f"第 {i} 项不是对象：{it!r}")
                continue
            if "title" not in it or "url" not in it:
                res.err("R1", f"第 {i} 项缺 title/url：{list(it.keys())}")
                continue
            items.append((it["title"], str(it["url"]), f"JSON[{i}]"))
    else:
        for ln, line in enumerate(explore.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if "::" not in line:
                res.err("R2", f"第 {ln} 行缺 '标题::URL' 分隔符：{line[:80]}")
                continue
            title, url = line.split("::", 1)
            items.append((title.strip(), url.strip(), f"行{ln}"))

    if not items:
        res.err("R1", "exploreUrl 未解析出任何分类项")
        return

    res.note("R1", f"exploreUrl 格式={'JSON数组' if is_json else '文本行'}，共 {len(items)} 项")

    for title, raw, where in items:
        url, opt, oerr = split_options(raw)
        if oerr:
            res.err("R3", f"[{where}]「{title}」内嵌选项非法：{oerr}")
            continue
        if not re.match(r"^https?://", url):
            # 相对路径：宿主 AnalyzeUrl 以 bookSourceUrl 为基拼接（workflow-detail.md 既有结论；
            # 来读读 2026-10-31 真机调通、读书斋已交付，均为相对 exploreUrl）。
            # bookSourceUrl 为空时无处可拼 → 才是 ERROR。
            if base:
                res.note("R3", f"[{where}]「{title}」为相对路径，宿主以 bookSourceUrl({base}) 拼接")
            else:
                res.err("R3", f"[{where}]「{title}」URL 不以 http(s):// 开头且 bookSourceUrl 为空，宿主无处拼接基址：{url[:80]}")
        if "{{page}}" not in url:
            res.warn("R3", f"[{where}]「{title}」URL 不含 {{{{page}}}}，多条分类可能永远只取第 1 页")
        # 易失地址启发式
        for seg in re.findall(r"[^/]*\d{4,}[^/]*", url.replace("{{page}}", "")):
            if re.search(r"\d{4,}", seg):
                res.warn("R5", f"[{where}]「{title}」路径含长数字段 '{seg}'，疑似易失地址；须用 3 个独立会话复验是否稳定")


def check_search(search, res, base=""):
    if not search:
        res.note("R4", "searchUrl 为空，跳过搜索检查")
        return
    url, opt, oerr = split_options(search)
    if oerr:
        res.err("R4", f"searchUrl 选项 JSON 非法：{oerr}")
        return
    if not re.match(r"^https?://", url):
        # 与 R3 同口径：相对路径 + bookSourceUrl 非空 = 宿主拼接（来读读真机调通同形态）
        if base:
            res.note("R4", f"searchUrl 为相对路径，宿主以 bookSourceUrl({base}) 拼接")
        else:
            res.err("R4", f"searchUrl 不以 http(s):// 开头且 bookSourceUrl 为空：{url[:80]}")
    if "{{key}}" not in url and not (opt and "{{key}}" in str(opt.get("body", ""))):
        res.err("R4", "searchUrl 与 body 都没有 {{key}}，搜索词无处可去")
    if opt:
        method = str(opt.get("method", "GET")).upper()
        webview = bool(opt.get("webView"))
        if method == "POST" and webview:
            res.err("R4", "method=POST 与 webView=true 互斥：Android WebView 只能 GET，POST body 会丢失，服务端收不到关键词（duomle 真机事故根因）")
        if method == "GET" and "{{key}}" in url:
            res.warn("R6", "GET URL 含 {{key}}：若宿主未自动编码，中文关键词可能未编码；建议 {{java.encodeURI(key)}} 或实测确认")
        res.note("R4", f"searchUrl method={method}, webView={webview}")
    else:
        res.note("R4", "searchUrl 无选项（默认 GET）")


def check_consistency(book, res):
    base = book.get("bookSourceUrl", "")
    if not base:
        res.err("R7", "bookSourceUrl 为空")
        return
    b_scheme = "https" if base.startswith("https://") else "http" if base.startswith("http://") else "?"
    if b_scheme == "?":
        res.err("R7", f"bookSourceUrl 协议异常：{base[:60]}")
    for field in ("searchUrl", "exploreUrl"):
        v = book.get(field) or ""
        schemes = set(re.findall(r"https?://", v))
        if schemes and b_scheme != "?":
            other = schemes - {b_scheme + "://"}
            if other:
                res.warn("R7", f"{field} 混用协议 {sorted(schemes)}，bookSourceUrl={b_scheme}；https 若证书不匹配会整段失败")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python3 check_request_layer.py <书源.json> [--strict]")
        sys.exit(2)
    path = args[0]
    if not os.path.exists(path):
        print(f"{RED}文件不存在：{path}{RST}")
        sys.exit(2)

    data = json.load(open(path, encoding="utf-8"))
    books = data if isinstance(data, list) else [data]

    total_err = 0
    for bi, book in enumerate(books):
        name = book.get("bookSourceName", f"#{bi}")
        print(f"\n{CYN}{'='*64}{RST}")
        print(f"{CYN}请求层闸 · {name}{RST}")
        print(f"{CYN}{'='*64}{RST}")
        res = Result()
        base = book.get("bookSourceUrl", "")
        check_explore(book.get("exploreUrl"), res, base)
        check_search(book.get("searchUrl"), res, base)
        check_consistency(book, res)

        for c, m in res.errors:
            print(f"{RED}[ERROR]{RST} {c} {m}")
        for c, m in res.warns:
            print(f"{YEL}[WARN ]{RST} {c} {m}")
        for c, m in res.notes:
            print(f"{GRN}[NOTE ]{RST} {c} {m}")

        print(f"\n小计：ERROR={len(res.errors)}  WARN={len(res.warns)}  NOTE={len(res.notes)}")
        total_err += len(res.errors)

    print(f"\n{'='*64}")
    if total_err:
        print(f"{RED}结论：请求层不通过，ERROR={total_err}——这些错误 validate / test_parse 都查不出来，必须修完再交付。{RST}")
        sys.exit(1)
    print(f"{GRN}结论：请求层通过（ERROR=0）。注意：本闸只验「宿主能否解析并发出请求」，不验站点是否真返回预期内容，后者仍需真实页/真机证据。{RST}")
    sys.exit(0)


if __name__ == "__main__":
    main()
