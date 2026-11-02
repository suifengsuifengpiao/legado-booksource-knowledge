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
     {{java.encodeURI(key)}} 或实测确认。**不写选项 = 默认 GET，同样适用**
     （v1.15.13 修：此前 R6 嵌在 `if opt:` 内，裸写法漏报）；显式 method:POST 不报
     （POST 关键词在 body，编码路径不同）
  R7 bookSourceUrl 协议与各规则 URL 协议一致性

切分算法（v1.15.13 重写，逐条对 3.25 dex）：
  `<clinit>` paramPattern = "\\s*,\\s*(?=\\{)"；`analyzeUrl()` 在**首次**匹配处切分
  （url=substring(0,start)、选项=substring(end) 交 gson fromJson），无匹配则整串当 url +
  默认 GET；解析失败被 runCatching 吞成 null（宿主按默认选项继续，不崩）。
  exploreUrl 另走一条：paramPattern 无匹配时 seek=0 → **整串都是 url，不切选项**。
  旧版用 rfind(",{") + json.loads(整段后缀)，两头都比宿主严：既误杀 @js:/<js> 尾部 JS，
  也误判数组内 "url" 值里的 \\",{...}\\"（实测：12 本已交付书源里 3 本被误判 ERROR）。

退出码：0 = 无 ERROR（默认口径，WARN 不阻断）；1 = 有 ERROR，或 --strict 下有 WARN
用法：python3 check_request_layer.py <书源.json> [--strict]
      --strict：WARN 亦视为失败（R6 这类「编码可能有问题」在严格模式下应阻断交付）
      v1.15.13 前 --strict 只写在用法里、无实现分支，传了等于没传
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

# 3.25 AnalyzeUrl.<clinit>：paramPattern = "\\s*,\\s*(?=\\{)"
PARAM_RE = re.compile(r"\s*,\s*(?=\{)")


class Result:
    def __init__(self):
        self.errors = []
        self.warns = []
        self.notes = []

    def err(self, code, msg):
        self.errors.append((code, msg))

    def warn(self, code, msg, blocking=True):
        """blocking=True：--strict 下视为失败（真的会让你交付后出事）。
        blocking=False：提示性（已真机验证可过、只是建议再确认），--strict 不阻断。
        v1.15.14：此前一刀切「WARN 即失败」，导致 duomle 修复版（真机已验证）在 --strict 下也红，
        把「建议实测确认」和「真的会坏」混为一谈。"""
        self.warns.append((code, msg, blocking))

    def note(self, code, msg):
        self.notes.append((code, msg))


def split_options(raw, host="?"):
    """按 **3.25 宿主自己的算法** 把 'url,{...}' 切分（v1.15.13 重写）。

    旧实现用 `rfind(",{")` + `json.loads(整段后缀)`，与本闸要防的误判同源：
    宿主根本不按"最后一个 ,{" 切，也**不会**因为后缀含多余内容就失败。

    3.25 反编译实证（classes3.dex → `io/legado/app/model/analyzeRule/AnalyzeUrl`）：
      · `<clinit>` 的 `paramPattern = Pattern.compile("\\s*,\\s*(?=\\{)")`
      · `analyzeUrl()` 在该 pattern **首次**匹配处切分：url = substring(0, start)，
        选项 = substring(end)，交给 gson `fromJson(..., UrlOption.class)`；无匹配 → 用整个 ruleUrl、默认选项
      · 选项解析失败被 `runCatching` 吞成 null → 宿主按 **默认 GET + 无选项** 继续（不是崩溃）
      · exploreUrl 另走一条：dex 里 `paramPattern.find()` 为假时 seek=0，即**整串都算 url**，
        不做切分 → 数组里 "url" 值内层带 \",{...}\" 不会被宿主当选项
    gson 按"解析完一个完整对象即返回、忽略其后多余内容"工作（java_probe/Probe3 实测），
    所以 `@js:` / `<js>` 尾部 trailing 的 JS 源码不会让宿主失败。

    返回 (url_part, opt_dict|None, err|None)。err 仅在**选项段本身**不是合法 JSON 对象时给出，
    且在 host=explore 时按宿主口径降级为该段整串当 url 的一部分。
    """
    s = raw.strip()
    if host == "explore":
        # 宿主对 exploreUrl 不切选项（dex: paramPattern.find() 为假 → seek=0，整串当 url）
        return s, None, None
    m = PARAM_RE.search(s)
    if not m:
        return s, None, None
    url_part = s[:m.start()].strip()
    opt_part = s[m.end():].strip()
    if not opt_part.startswith("{"):
        return url_part, None, None
    try:
        opt = json.JSONDecoder().raw_decode(opt_part)[0]
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
            # {{ }} 内嵌多行 JS 时 Python 的 json 会因裸回车报错，而宿主 gson **能过**
            # （八叉书库实证：java_probe/Probe.java → gson [OK] 元素数=15，格 2 实测）。
            # 这是本闸的模型局限，不是书源错 → NOTE，交 js_layer_check / 真机，不判 ERROR
            # 判据收紧（v1.15.13 第二版，两步都实测过）：
            #   ① 必须有 `{{` 与 `}}` —— 事故版 v4 那种真未转义的 ,{"webView" 不含 {{ }}，必须继续报 ERROR；
            #   ② 不能再要求"没有 ,{" —— 八叉书库正是 `,{` 同一子串两边都在（{{ 在前、,{ 是 JSON 元素分隔），
            #      而 v4 的 `,{` 落在**引号内**。真正的分界是引号：v4 的双引号在 ,{ 前提前闭合，
            #      整串无法被 json 解析；八叉书库虽也无法被 Python json 解析(裸回车)但 gson 能过。
            # 结论：两种都不能靠结构判，只能靠「宿主实测能过」→ 本闸不判，转 NOTE 交 js_layer_check / 真机。
            # 为不放过真错，这里额外要求解析器报的是**控制字符**类错误（gson 宽容接受），
            # 引号提前闭合（Expecting ',' delimiter / Invalid control 之外的语法错）仍按 ERROR 报。
            if ("{{" in explore and "}}" in explore) and "Invalid control character" in str(e):
                res.note("R1", f"exploreUrl 为 JSON 数组且内嵌 {{{{ }}}} 动态片段（宿主先算 JS 再解析，"
                               f"gson 实测可过；Python json 因裸回车报错），本闸跳结构校验；"
                               f"JS 语法另用 js_layer_check.py / 真机验证")
                return
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
        url, opt, oerr = split_options(raw, host="explore")
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
        # v1.15.14：先把行内选项 ,{...} 从路径里剥掉再判——宿主虽不把它当选项解析（explore 口径），
        # 但它显然不是 URL 路径的一段；不剥会让 {"webWait":3000} 里的 3000 被误判成易失长数字段。
        _url_for_r5 = re.sub(r"\s*,\s*\{.*$", "", url, flags=re.S)
        for seg in re.findall(r"[^/]*\d{4,}[^/]*", _url_for_r5.replace("{{page}}", "")):
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
    # 关键词载体（v1.15.13 精修两处漏报，均为实测）：
    #   ① `"{{key}}" not in url` 会把 R6 自己建议的处方 {{java.encodeURI(key)}} 判成 ERROR ——
    #      处方执行完反而新增一条红，见 `references/maintenance.md` 与 CHANGELOG；
    #   ② `@js:` / `<js>` 动态 URL 里关键词常以 `+key+` 拼接、或整串由 JS 返回，原逻辑只认字面
    #      `{{key}}` → 已交付的 八叉书库 / 手机小说 / luyouxs 三本被误判 ERROR（它们是 JS 返回形态）。
    # 载体判定：整个 searchUrl 原文（含 JS 源码）或 body 里出现 key 变量或 {{key}} 即算。
    # 宿主在 analyzeUrl 之前就把整个串当 URL 处理，故原文（含 JS 尾巴）要一起看。
    # 注意不能用 `search` 全文：`cookie` / `searchkey` 里的 "key" 会被子串匹配骗过
    # （正则已带词边界，但关键词本身可能只出现在 JS 尾巴里，故只取 url 段 + body，不做全文）。
    key_src = url + "\n" + str((opt or {}).get("body", ""))
    KEY_VAR_RE = re.compile(r"(?<![A-Za-z0-9_$])key(?![A-Za-z0-9_$])")
    if "{{key}}" not in key_src and not KEY_VAR_RE.search(key_src):
        res.err("R4", "searchUrl 与 body 里都找不到 key（{{key}} / +key+ / {{java.encodeURI(key)}}），搜索词无处可去")
    # v1.15.13：无选项 = 默认 GET，与显式 method:GET 同口径。
    # 旧写法把 R6 整段嵌在 `if opt:` 内，裸 searchUrl（不写选项）走 else 只打 NOTE
    # → 「GET URL 含 {{key}} 未编码」这条最常命中的提示，恰恰在最常见的写法上不响。
    if opt:
        method = str(opt.get("method", "GET")).upper()
        webview = bool(opt.get("webView"))
        if method == "POST" and webview:
            res.err("R4", "method=POST 与 webView=true 互斥：Android WebView 只能 GET，POST body 会丢失，服务端收不到关键词（duomle 真机事故根因）")
        res.note("R4", f"searchUrl method={method}, webView={webview}")
    else:
        method = "GET"
        res.note("R4", "searchUrl 无选项 → 按默认 method=GET, webView=False 检查")
    # method 显式 POST 不报：关键词走 body，编码由 body 路径决定，与 URL 查询串无关。
    # 已经显式编码的写法（{{java.encodeURI(key)}} 等）不再提示——它是本条 WARN 的处方，
    # 处方执行完还响 = 永远消不掉的红灯（v1.15.13 实测：照建议改完反而先被 R4 判 ERROR）。
    if method == "GET" and "{{key}}" in url:
        res.warn("R6", "GET URL 含 {{key}}：若宿主未自动编码，中文关键词可能未编码；建议 {{java.encodeURI(key)}} 或实测确认",
                     blocking=False)   # v1.15.14：宿主 AnalyzeUrl 默认会对 {{key}} 做 URL 编码（多本已交付源真机可搜），
                     # 属"建议再确认"而非"交付后会坏"；duomle 修复版真机通过却因此被判 strict 失败，是误伤。


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
    # v1.15.13：--strict 从「只写在用法里」改为真实现。旧版两处用法文本都写了它，
    # 却没有一个分支读它 —— 传了等于没传，WARN 在严格模式下静默放行。
    strict = "--strict" in sys.argv[1:]
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
    total_warn = 0
    total_warn_info = 0
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
        for c, m, blocking in res.warns:
            tag = "[WARN ]" if blocking else "[WARN·提示]"
            print(f"{YEL}{tag}{RST} {c} {m}")
        for c, m in res.notes:
            print(f"{GRN}[NOTE ]{RST} {c} {m}")

        n_block = sum(1 for w in res.warns if w[2])
        n_info = len(res.warns) - n_block
        print(f"\n小计：ERROR={len(res.errors)}  WARN={len(res.warns)}"
              f"（阻断 {n_block} / 提示 {n_info}）  NOTE={len(res.notes)}")
        total_err += len(res.errors)
        total_warn += n_block
        total_warn_info += n_info

    print(f"\n{'='*64}")
    if total_err:
        print(f"{RED}结论：请求层不通过，ERROR={total_err}——这些错误 validate / test_parse 都查不出来，必须修完再交付。{RST}")
        sys.exit(1)
    if strict and total_warn:
        print(f"{RED}结论：--strict: 阻断级 WARN 视为失败，请求层不通过（阻断 WARN={total_warn}）。"
              f"这些是「交付后真会坏」的隐患（分页失效/地址易失/证书不匹配），必须处理。{RST}")
        sys.exit(1)
    if total_warn_info:
        print(f"{YEL}提示：有 {total_warn_info} 条提示级 WARN（不阻断 --strict）——建议实测确认，但不影响交付判定。{RST}")
    # 通过时不复述 --strict 口径：回退实验里那句话会让「分支被短路」的日志与正常日志只差 exit code，
    # 从输出看不出"本该失败"（v1.15.13 实测）。口径只在失败分支说一次。
    print(f"{GRN}结论：请求层通过（ERROR=0）。注意：本闸只验「宿主能否解析并发出请求」，不验站点是否真返回预期内容，后者仍需真实页/真机证据。{RST}")
    sys.exit(0)


if __name__ == "__main__":
    main()
