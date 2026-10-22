#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验开源阅读(Legado)3.0 书源 JSON 的字段完整性。

用法:
    python3 validate_booksource.py <书源.json> [--strict]
    cat 书源.json | python3 validate_booksource.py -

说明:
    输出分级报告:
      [ERROR] 缺必备字段，书源可能无法工作或解析失败
      [WARN ]  健壮性建议项（header / charset / replaceRegex 等）

    退出码: 0 = 通过；1 = 有 ERROR 或 --strict 下有 WARN；2 = 参数/解析错误。
    支持单个书源对象，也支持书源组（JSON 数组）。
"""
import sys
import json
import re
import os
import shutil
import subprocess
import tempfile

REQUIRED_TOP = ["bookSourceName", "bookSourceUrl"]

# 旧键名 → Legado 真实键名归一化(真实 schema: 解析规则在顶层独立对象, 键无 rule 前缀)
KEY_ALIAS = {
    "ruleBookList": "bookList", "ruleName": "name", "ruleAuthor": "author",
    "ruleKind": "kind", "ruleWordCount": "wordCount", "ruleLastChapter": "lastChapter",
    "ruleIntroduce": "intro", "ruleIntro": "intro", "ruleCoverUrl": "coverUrl",
    "ruleBookUrl": "bookUrl", "ruleChapterList": "chapterList",
    "ruleChapterName": "chapterName", "ruleChapterUrl": "chapterUrl",
    "ruleContent": "content", "ruleTocUrl": "tocUrl", "ruleCanReName": "canReName",
    "ruleNextTocUrl": "nextTocUrl", "ruleNextContentUrl": "nextContentUrl",
}


def _norm_keys(region):
    if isinstance(region, dict):
        return {KEY_ALIAS.get(k, k): v for k, v in region.items()}
    return region


def _parse_rule_region(val):
    """规则区可能是对象或字符串化 JSON，统一解析为对象并归一化键名；无法解析则原样返回。"""
    if isinstance(val, str) and not val.strip().startswith("<js"):
        try:
            val = json.loads(val)
        except Exception:
            return val
    return _norm_keys(val)


def _get_search_region(s):
    """搜索解析区域: 新 schema 在顶层 ruleSearch 对象; 旧写法内嵌 searchUrl 对象。"""
    rs = _parse_rule_region(s.get("ruleSearch"))
    if isinstance(rs, dict) and rs:
        return rs
    r = _parse_rule_region(s.get("searchUrl"))
    if isinstance(r, dict) and any(k in r for k in ("bookList", "name", "author", "bookUrl")):
        return r
    return None


# 解析区域: (key, 取值函数, 必填子字段, 展示名)
# 真实 schema (与 App 编辑界面/官方文档一致):
#   searchUrl/exploreUrl 只放 URL(或<js>); 解析规则在顶层 ruleSearch/ruleExplore/
#   ruleBookInfo/ruleToc/ruleContent 对象, 键名 bookList/name/author/chapterList/content 等。
SUB_FIELDS = [
    ("ruleSearch", _get_search_region,
     ["bookList", "name", "bookUrl"], "搜索解析(ruleSearch)"),
    ("ruleBookInfo", lambda s: _parse_rule_region(s.get("ruleBookInfo")),
     ["name"], "详情解析(ruleBookInfo)"),
    ("ruleToc", lambda s: _parse_rule_region(s.get("ruleToc")),
     ["chapterList", "chapterName", "chapterUrl"], "目录解析(ruleToc)"),
    ("ruleContent", lambda s: _parse_rule_region(s.get("ruleContent")),
     ["content"], "正文解析(ruleContent)"),
]


def get_explore_regions(src):
    """exploreUrl 可能是 字符串化JSON数组 / 列表(每条含 ruleExplore 或共用顶层 ruleExplore) / 对象, 返回 ruleExplore 区域列表。

    Legado 两种合法结构:
      (a) exploreUrl 每条含自己的 ruleExplore;
      (b) exploreUrl 每条仅 {'title','url'}, 所有入口共用顶层 ruleExplore 字段。
    本函数兼容两者: 某项缺 ruleExplore 时回退到顶层 ruleExplore。
    """
    ev_raw = src.get("exploreUrl")
    ev = _parse_rule_region(ev_raw)
    top_re = _parse_rule_region(src.get("ruleExplore"))  # 顶层 ruleExplore(所有入口共用)
    # 未配置 / 纯文本(单URL 或 Legado 标准 "标题::URL" 多行) -> 规则共用顶层 ruleExplore
    if ev is None:
        return None  # 未配置 exploreUrl → 调用方跳过发现频道校验(此前落到这里会返回 []，被误判成"配了但无规则")
    if isinstance(ev, str):
        if isinstance(ev_raw, str) and not ev_raw.strip():
            return None  # 空串也算未配置
        return [top_re] if isinstance(top_re, dict) else []
    entries = []
    if isinstance(ev, list):
        for e in ev:
            if isinstance(e, dict):
                re_ = _parse_rule_region(e.get("ruleExplore"))
                if not isinstance(re_, dict):
                    re_ = top_re  # 回退顶层 ruleExplore(结构 b)
                if isinstance(re_, dict):
                    entries.append(re_)
    elif isinstance(ev, dict):
        re_ = _parse_rule_region(ev.get("ruleExplore")) or top_re
        if isinstance(re_, dict):
            entries.append(re_)
        elif ev:  # 扁平对象直接含 rule*（少见但兼容）
            entries.append(ev)
    return entries


def load_source(path):
    """加载书源。兼容三种交付形态：数组（App 导入要求）、单对象、每行一个对象的 JSONL。

    ⚠️ 实测坑（开源阅读 3.25 本地导入）：App 的导入入口用 Gson 解析并**要求数组**，
    交单对象 `{...}` 会报 ImportError: Expected BEGIN_ARRAY but was BEGIN_OBJECT。
    单对象请包装成 `[{...}]` 再给用户导入，否则用户那边"改了没生效"——他会以为
    是规则问题，其实新文件从未导入成功。这里仍会自动兼容并继续校验，但会以
    **[ERROR] 交付形态** 报出（退出码 1），避免这条真翻车点被当成可忽略的提示。
    """
    if path == "-":
        data = json.load(sys.stdin)
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    try:
        data = json.loads(text)
    except ValueError:
        # JSONL: 每行一个对象(json.load 对多行必抛 Extra data, 原实现直接崩到 main)
        out = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        data = out
    if isinstance(data, dict):
        print("提示: 文件是单对象格式。App 的本地导入要求数组, 交付时应包装为 [{...}] "
              "(本工具已自动兼容, 不影响校验)。", file=sys.stderr)
        return [data]
    if isinstance(data, list):
        return data
    # JSONL：每行一个对象
    out = []
    for line in str(data).splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# 字段归属：键 → 允许出现的规则组。放错组会被 Gson 静默丢弃(不报错，App 界面也看不到该键)。
# 依据: 反编译 io.legado.app.data.entities.rule.{SearchRule,BookInfoRule,TocRule,ContentRule} (3.25 实测)
#   TocRule 字段 = chapterList/chapterName/chapterUrl/nextTocUrl/preUpdateJs/formatJs/
#                  isVolume/isVip/isPay/updateTime   —— 没有 tocUrl
#   BookInfoRule 字段含 name/author/kind/lastChapter/coverUrl/intro/wordCount/updateTime/
#                  status/canReName/downloadUrls/init/tocUrl
FIELD_OWNER = {
    "tocUrl": ("ruleBookInfo",),
    "bookList": ("ruleSearch", "ruleExplore"),
    "bookUrl": ("ruleSearch", "ruleExplore"),
    "chapterList": ("ruleToc",),
    "chapterName": ("ruleToc",),
    "chapterUrl": ("ruleToc",),
    "nextTocUrl": ("ruleToc",),
    "content": ("ruleContent",),
    "nextContentUrl": ("ruleContent",),
}

# 各规则组已知合法键(用于识别"完全不认识的键"); 不含上面 FIELD_OWNER 已列的键
GROUP_KNOWN_KEYS = {
    "ruleSearch": {"name", "author", "kind", "wordCount", "lastChapter", "intro",
                   "coverUrl", "checkKeyWord", "updateTime"},
    "ruleExplore": {"name", "author", "kind", "wordCount", "lastChapter", "intro",
                    "coverUrl", "checkKeyWord", "updateTime"},
    "ruleBookInfo": {"name", "author", "kind", "wordCount", "lastChapter", "intro",
                     "coverUrl", "status", "updateTime", "canReName", "bookInfoInit",
                     "init", "downloadUrls"},
    "ruleToc": {"preUpdateJs", "formatJs", "isVolume", "isVip", "isPay", "updateTime"},
    "ruleContent": {"webJs", "sourceRegex", "imageStyle", "replaceRegex", "payAction",
                    "subContent", "title", "imageDecode", "callBackJs"},
}


def check_field_ownership(src, label, errors, warns):
    """检测字段是否放错规则组(会被 Gson 静默丢弃)或键名根本不存在。"""
    for group in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
        region = src.get(group)
        if not isinstance(region, dict):
            continue
        for k in region:
            owner = FIELD_OWNER.get(k)
            if owner and group not in owner:
                errors.append(
                    "[%s] %s.%s 放错规则组: 它属于 %s，写在 %s 会被导入时静默丢弃(不报错、App 里也看不到)"
                    % (label, group, k, "/".join(owner), group))
            elif not owner and k not in GROUP_KNOWN_KEYS.get(group, set()):
                warns.append(
                    "[%s] %s.%s 不是该规则组的已知键，可能被 Gson 静默丢弃，请核对 App 编辑界面"
                    % (label, group, k))


# ---- JS 语法校验（v8 复盘新增：之前 validate 只查字段静态正确性, 不查 JS 语法,
#      导致 shumi99 v6 的"缺一个 }"漏过 → 导入后 Rhino 报 missing ) after argument list）----
# JS 片段散落各处：顶层 loginCheckJs / URL 行内选项的 js·webJs / 规则字段里的 <js>...</js> 管道 /
# ruleContent.webJs / 纯 <js> 钩子(init·bookInfoInit·preUpdateJs·formatJs)。全收上来做语法校验。
_NODE_BIN = None


def _node_bin():
    global _NODE_BIN
    if _NODE_BIN is None:
        _NODE_BIN = shutil.which("node") or False
    return _NODE_BIN


def _opt_of_inline(s):
    """从 URL 行内选项串(末尾 ,{JSON}) 取出 options 对象; 非内联返回 None。"""
    if not isinstance(s, str) or not re.search(r",\s*\{", s):
        return None
    i = s.rfind(",")
    j = s.find("{", i)
    try:
        return json.loads(s[i + 1:])
    except Exception:
        return None


def _collect_js_fragments(src):
    """收集书源内所有 JS 片段 -> [(位置, 代码)]。位置仅用于报错定位。"""
    frags = []
    name = src.get("bookSourceName", "源")
    seen = set()

    def add(where, code):
        if isinstance(code, str) and code.strip() and code not in seen:
            seen.add(code)
            frags.append((where, code))

    # 1) 顶层纯 JS 钩子
    for key in ("loginCheckJs",):
        add(name + "/" + key, src.get(key))

    # 2) URL 行内选项里的 js / webJs
    targets = [src.get("searchUrl")]
    ev = src.get("exploreUrl")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:
            ev = None
    if isinstance(ev, list):
        for it in ev:
            if isinstance(it, dict):
                targets.append(it.get("url"))
    for grp in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
        g = src.get(grp)
        if isinstance(g, dict):
            for k in ("bookUrl", "chapterUrl", "tocUrl", "nextContentUrl", "content", "webJs"):
                v = g.get(k)
                if not isinstance(v, str):
                    continue
                # webJs 是裸 JS(不带 <js> 标签, 也不是 URL+options 串): 上面的 inline 解析收不到,
                # 第 3 步的 walk 只收 <js>...</js>, 都不覆盖它 —— 曾整段 JS 无语法校验(shumi99 类)。
                # content 留给第 3 步收其中的 <js>, 不整体 add(否则整条规则当 JS 校验必误报)。
                if k == "webJs":
                    add(name + "/" + grp + ".webJs", v)
                else:
                    targets.append(v)
    for raw in targets:
        if not isinstance(raw, str):
            continue
        opt = _opt_of_inline(raw)
        if opt:
            if "webJs" in opt:
                add(name + "/webJs(inline)", opt["webJs"])
            if "js" in opt:
                add(name + "/js(inline)", opt["js"])

    # 3) 规则字段里的 <js>...</js> 管道 + 纯 <js> 钩子 + 顶层 searchUrl/exploreUrl 整串。
    #    覆盖范围: 顶层 searchUrl/exploreUrl + 所有 rule* 规则组内的所有字符串字段。
    #    旧版只认 5 个钩子键(init/bookInfoInit/preUpdateJs/formatJs/content), 解析字段
    #    (ruleBookInfo.intro、ruleSearch.bookList、ruleToc.nextTocUrl 等)与纯 <js> searchUrl
    #    里的语法错全部漏扫 —— 铁律 17 声称「所有 JS 片段」, 实现必须兑现(sk.3qdus intro
    #    惨案正是漏扫区)。
    js_scope_keys = ("searchUrl", "exploreUrl")

    def _in_js_scope(k, path):
        segs = [s.split("[")[0] for s in path.split(".") if s]
        if not segs:
            return k in js_scope_keys
        return segs[0].startswith("rule") or segs[0] in js_scope_keys

    def walk(o, path, k=""):
        if isinstance(o, dict):
            for kk, v in o.items():
                walk(v, path + "." + str(kk), kk)
        elif isinstance(o, list):
            for idx, v in enumerate(o):
                walk(v, path + "[%d]" % idx, k)
        elif isinstance(o, str) and _in_js_scope(k, path):
            for m in re.finditer(r"<js>(.*?)</js>", o, re.S):
                add(name + "/%s<js>" % (k or "?"), m.group(1))
    walk(src, "")
    return frags


def _braces_balanced(code):
    """兜底：仅判 () {} 是否平衡。字符串内的括号不区分, 但对"缺整个 }"这类硬错足够灵敏。"""
    depth = 0
    quote = None
    i = 0
    while i < len(code):
        ch = code[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _check_js_syntax(src, label, errors, warns, notes):
    """校验书源内全部 JS 片段语法。优先 node --check(真语法, 能抓缺括号/非法 token);
    无 node 时退化为括号平衡检查。语法错误报 ERROR（导入即崩, 必须拦在交付前）。"""
    frags = _collect_js_fragments(src)
    if not frags:
        return
    node = _node_bin()
    engine = "node --check" if node else "括号平衡(无 node, 仅兜底)"
    notes.append("[%s] JS 语法校验覆盖 %d 个片段(引擎: %s)" % (label, len(frags), engine))
    for where, code in frags:
        ok, msg = (True, "")
        if node:
            d = tempfile.mkdtemp(prefix="jsck_")
            try:
                p = os.path.join(d, "u.js")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(code)
                proc = subprocess.run([node, "--check", p], capture_output=True, text=True, timeout=15)
                if proc.returncode != 0:
                    lines = (proc.stderr or "").strip().splitlines()
                    # node --check 的 stderr 末行是版本号(Node.js vXX)，真正错误在 "SyntaxError/Error" 行
                    err_lines = [l for l in lines if "Error" in l]
                    ok, msg = False, (err_lines[-1] if err_lines else (lines[0] if lines else "未知语法错误"))[:220]
            except Exception:
                ok, msg = _braces_balanced(code), "" if _braces_balanced(code) else "node 执行异常且括号不平衡"
            finally:
                shutil.rmtree(d, ignore_errors=True)
        else:
            ok = _braces_balanced(code)
            if not ok:
                msg = "括号不平衡(疑似缺括号)"
        if not ok:
            errors.append(
                "[%s] %s 的 JS 语法错误: %s —— 导入后 Rhino 会报 SyntaxError(行号常恒为1)。"
                "务必先过本校验再交付" % (label, where, msg))


def _iter_rules(src):
    """遍历书源内所有规则字符串, 产出 (位置, 键, 规则串)"""
    for group in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent", "ruleReview"):
        region = src.get(group)
        if isinstance(region, str):
            try:
                region = json.loads(region)
            except Exception:
                continue
        if isinstance(region, dict):
            for k, v in region.items():
                if isinstance(v, str):
                    yield ("%s.%s" % (group, k), k, v)
    for k in ("searchUrl", "tocUrl", "chapterUrl"):
        v = src.get(k)
        if isinstance(v, str):
            yield (k, k, v)


def check_rule_pitfalls(src, label, errors, warns, notes):
    """把 SKILL.md 里的铁律落成自动检测：XPath 前导点、## 替换正则缺捕获组、loginCheckJs 带 <js> 标签、enabledCookieJar 缺失、webView 等待不足等"""
    rules = list(_iter_rules(src))

    # 1) XPath 前导点: .// 或 ./ 开头 → Legado 判模式的唯一入口是 startsWith('/'), 前导点被判 CSS → 静默 0 条
    for pos, k, v in rules:
        s = v.strip()
        # 带 XPath 特征才算误写(避开 "./search.php?q=" 这类相对 URL); 单斜杠的 './a/@href' 同样会落 CSS 模式
        xpath_like = ("//" in s or "@" in s or "text()" in s or "[" in s)
        if (s.startswith(".//") or s.startswith("./")) and xpath_like:
            errors.append(
                "[%s] %s 的 XPath 带前导点('.//'/'./'): 会被判为 CSS 模式 → 静默 0 条(不报错)。"
                "去掉前导点写成 '//...'" % (label, pos))

    # 1b) JsoupXpath 不兼容语法(boluomao v1 真机翻车): 这些写法在 lxml/浏览器里正常,
    #     但 Legado 内置 JsoupXpath(seimicrawler) 只实现 XPath 子集 → 真机直接抛
    #     XPathSyntaxErrorException(... NullPointerException ... getElementsByTag on a null object)
    #   - PROVEN: 有真机实证(boluomao v1 真机抛异常) → ERROR
    #   - INFERRED: 从"JsoupXpath 只实现 XPath 子集"推断, 未获真机实证 → 只 WARN。
    #     证据不足时护栏应当"提示"而不是"命令": 万一某条其实被支持, 报 ERROR 会逼用户改掉
    #     本来能用的书源 —— 那比漏报更糟, 是护栏主动制造 bug。
    _XPATH_UNSUPPORTED = [
        ("text()[", "伪函数 text() 带谓词", "改用 allText() 取元素及后代全部文本", 1),
        ("following-sibling::", "不支持兄弟轴", "改用父容器 //div[...] 自顶向下定位，或纯 JS 从标记后 indexOf 查找", 1),
        ("preceding-sibling::", "不支持兄弟轴", "同上", 0),
        ("parent::", "不支持轴", "改用 //父容器[...] 自顶向下定位", 0),
        ("ancestor::", "不支持轴", "改用 //父容器[...] 自顶向下定位", 0),
        ("child::", "不支持轴", "直接写 //子标签", 0),
        ("descendant::", "不支持轴", "用 // 代替", 0),
    ]
    for pos, k, v in rules:
        xp = v.split("<js>")[0]   # 只检查 XPath 部分, <js> 里的 JS 不算
        for bad, why, fix, proven in _XPATH_UNSUPPORTED:
            if bad not in xp:
                continue
            if proven:
                errors.append(
                    "[%s] %s 用了 JsoupXpath 不支持的语法 '%s'（%s，真机实证）→ 抛 XPathSyntaxErrorException。"
                    "注意它在 lxml/浏览器控制台里是正常的，极易漏。%s" % (label, pos, bad, why, fix))
            else:
                warns.append(
                    "[%s] %s 用了 '%s'（%s）：据 JsoupXpath 只实现 XPath 子集**推断**不支持，"
                    "但**未获真机实证**。若该书源在本 App 上实测可用则忽略本条；"
                    "一旦真机抛 XPathSyntaxErrorException，改法：%s" % (label, pos, bad, why, fix))

    # 2) ## 替换正则必须有捕获组(引用 $1 但正则里没有 '(')
    for pos, k, v in rules:
        if "##" not in v:
            continue
        if not ("$1" in v or "$2" in v or "$3" in v):
            continue
        parts = v.split("##")
        rx = parts[1] if len(parts) > 1 else ""
        if True:
            if rx and "(" not in rx:
                errors.append(
                    "[%s] %s 的替换正则 '%s' 无捕获组却引用 $1 → 替换为空。"
                    "应写 '^(.+)$' 而非 '^.*'" % (label, pos, rx[:40]))

    # 3) loginCheckJs: 带 <js> 标签必语法错(3.25 不剥标签); 本 App(3.25 反编译版)实测生效
    lc = src.get("loginCheckJs")
    if isinstance(lc, str) and lc.strip():
        if lc.strip().startswith("<js"):
            errors.append(
                "[%s] loginCheckJs 带 <js> 标签: 3.25 不剥标签, Rhino 在第1行 '<' 处语法错(行号恒为1)。"
                "去掉标签只留纯 JS" % label)
        else:
            # 本 App(legado 3.25 反编译版)经 putLoginHeader 实锤: 每次请求后执行, 落 cookie 到 CookieJar,
            # getLoginHeader 自动带到下次请求 → 过"明文 cookie"验证墙首选。已用真机(V14 过爪机书屋搜索墙)证实。
            # 其他构建不一定生效, 换 App 请用探针/调试桥实测确认。
            notes.append(
                "[%s] loginCheckJs 在本 App(3.25 反编译版)生效: 每次请求后执行, 返回 JSON 取 Cookie 落库, "
                "下次请求自动带上 → 过验证墙可用(首选)。注意返回值必须带 result、且不能带 <js> 标签。" % label)

    # 4) enabledCookieJar: 缺省 false → CF/验证 cookie 不落库
    #    仅在"疑似依赖 cookie"时提示, 避免对纯静态站刷噪音
    header_str = src.get("header") if isinstance(src.get("header"), str) else ""
    needs_cookie = bool(src.get("loginCheckJs")) or ("ookie" in header_str) or any(
        "webView" in v for _, _, v in rules)
    if "enabledCookieJar" not in src:
        if needs_cookie:
            warns.append(
                "[%s] 未显式设置 enabledCookieJar: 该字段缺省 false → OkHttp 不带 CookieJar 头、"
                "CF/验证 cookie 不落库复用(本源疑似依赖 cookie)。CF 站/验证墙站务必显式设 true" % label)
    elif src.get("enabledCookieJar") is not True and needs_cookie:
        warns.append(
            "[%s] enabledCookieJar 非 true: 本源疑似依赖 cookie(有 loginCheckJs/Cookie/webView), "
            "建议设为 true 让 cookie 跨请求复用" % label)

    # 5) webView 等待不足 → JS 挑战/客户端解密未完成就被截取
    webview_active = False
    for pos, k, v in rules:
        if '"webView"' not in v and "webView" not in v:
            continue
        if not re.search(r'"webView"\s*:\s*true', v):
            continue
        webview_active = True
        m = re.search(r'"webWait"\s*:\s*[\"\']?(\d+)', v)
        has_webjs = re.search(r'"webJs"\s*:', v) is not None
        if not m:
            if has_webjs:
                # 填了 webJs 会让默认等待失效，只剩约 100ms 基础延迟
                warns.append(
                    "[%s] %s 同时指定了 webJs 却没给 webWait: "
                    "一旦有 webJs，默认等待失效、只剩约 100ms 基础延迟，页面未渲染完就取 DOM。"
                    "必须显式写 webWait(JS挑战>=3000, 客户端解密>=8000)"
                    % (label, pos))
            else:
                warns.append(
                    "[%s] %s 启用 webView 但未指定 webWait: 3.25 默认等待约 1000ms 可能不足 → "
                    "JS 挑战/解密未完成就被截取, 建议 >=3000(JS挑战)/8000(客户端解密)"
                    % (label, pos))
        elif int(m.group(1)) < 3000:
            warns.append(
                "[%s] %s 的 webWait=%s 偏小: 启用 webView 后 JS 挑战/客户端解密需要足够时间完成, "
                "JS 挑战建议 >=3000, 客户端解密 >=8000, 否则正文容器仍空 → 取空"
                % (label, pos, m.group(1)))
    # 6) webView 站点: 本地脚本(curl/lxml)跑不了 JS 挑战与客户端解密, 必须真机确认
    if webview_active:
        notes.append(
            "[%s] 本源启用 webView: 本地验证(curl/lxml)跑不了 JS 挑战与客户端解密, 只能验静态 XPath 命中; "
            "实际抓取(过墙/解密)必须真机确认" % label)

    # 7) 同一段 JS 里多次取"秒级时间戳"(rrssk 中继搜索实证): 签名用一个 ts、发请求用另一个 ts,
    #     两者跨秒时服务端一致性校验不过 → 偶发 403; 表现是"时好时坏", 极易误判成限流/IP 问题。
    #     只 WARN: 确有场景需要两个不同时间戳(如缓存 TTL), 别用护栏逼人改错。
    frags = [c for _, c in _collect_js_fragments(src)]

    def _walk_strings(o):
        """补齐 <js> 片段: _collect_js_fragments 只认几个钩子字段, URL 字段(searchUrl 等)里的 <js> 抓不到"""
        if isinstance(o, dict):
            for v in o.values():
                _walk_strings(v)
        elif isinstance(o, list):
            for v in o:
                _walk_strings(v)
        elif isinstance(o, str):
            for m in re.finditer(r"<js>(.*?)</js>", o, re.S):
                frags.append(m.group(1))
    _walk_strings(src)

    # 两段来源会重叠：钩子字段(content 等)里的 <js> 既被 _collect_js_fragments 收到、
    # 又被 _walk_strings 追加 → 不按内容去重会对同一段 JS 刷出两条相同告警(1.13.14 自检抓到)。
    seen_code = set()
    for code in frags:
        if code in seen_code:
            continue
        seen_code.add(code)
        hits = len(re.findall(r"Date\.now\(\)\s*/\s*1000|getTime\(\)\s*/\s*1000", code))
        if hits >= 2:
            warns.append(
                "[%s] 同一段 JS 里出现 %d 次「秒级时间戳」(Date.now()/1000): 若签名与发请求各取了一次, "
                "跨秒会让签名里的 ts 与参数里的 ts 不一致 → 服务端偶发 403(实证: rrssk 中继搜索, "
                "曾表现为'同一组值 requests 200 / curl 403', 一度误判为限流)。"
                "改法: var ts=Math.floor(Date.now()/1000); 签名与拼接 URL 共用这一个变量。"
                "若本源确实需要多个不同时间戳则忽略本条" % (label, hits))

    # 8) L0 先证伪关卡(rrssk 中继搜索实证, 1.13.16 新增):
    #    搜索含签名特征(sign/token/_sig/signature/nonce/hmac/md5/encrypt/_snc/snc/vcode/captcha/verification)
    #    但书源 comment 无"已证伪/L0"标记 → WARN: 先发一次乱填签名看服务端是否校验,
    #    未证伪前勿轻信"无解"。只 WARN 不 ERROR: agent 测过但没留痕不应被卡死(happy path 保护)。
    #    注: 故意排除裸 auth/ts(太常见: author 含 auth、时间戳几乎必有), 否则会误伤普通源。
    _l0_blob = ""
    _su = src.get("searchUrl")
    if isinstance(_su, str):
        _l0_blob += _su + " "
    _rs = _get_search_region(src)
    if isinstance(_rs, dict):
        _l0_blob += json.dumps(_rs, ensure_ascii=False) + " "
    _SIGN_PATTERNS = (
        r"\bsign\b", r"signature", r"_sig\b", r"\btoken\b", r"\bnonce\b",
        r"\bhmac\b", r"\bmd5\b", r"encrypt", r"_snc\b", r"\bsnc\b",
        r"vcode", r"captcha", r"verification",
    )
    _L0_MARKERS = ("证伪", "l0", "l0_probe", "probe", "先测", "已测", "先证", "证伪过", "已L0", "l0:")
    if any(re.search(p, _l0_blob, re.I) for p in _SIGN_PATTERNS):
        _cmt = " ".join(str(src.get(k, "")) for k in ("comment", "bookSourceComment"))
        # 裸子串匹配会误命中("l0" 是 "html0"/"model0" 的子串), 把没证伪的源误判已证伪、
        # 静默抑制本 WARN; 故英文标记要求前后为非字母数字, 中文标记按整词保留
        _cmt_l = _cmt.lower()
        _l0_done = any(
            (re.search(r"(?<![a-z0-9])l0(?![a-z0-9])", _cmt_l) if mk.lower() in ("l0", "l0_probe", "probe")
             else mk.lower() in _cmt_l)
            for mk in _L0_MARKERS)
        if not _l0_done:
            warns.append(
                "[%s] 搜索含签名特征(sign/token/_sig/signature 等)但未发现 L0 证伪记录"
                "(comment 无 '证伪/L0' 标记): 先用 scripts/l0_probe.py 发一次乱填签名的请求, "
                "确认服务端是否真的校验——多数前端闸(DOM 指纹/_ad52ca、isTrusted/_b13bf3)服务端不校验, "
                "纯算式即过; 未证伪前不要轻信'无解'(1.13.15 之前曾因此误判 Legado 不可能)。"
                % label)

    # 9) 解析规则 <js> 管道的"顶层 return"在 App Rhino 上下文会 invalid return(真机实证)
    #    sk.3qdus.com 的 ruleBookInfo.intro 用 <js> 写 'return ...' → 真机报 invalid return → 该字段解析失败/取空。
    #    App 解析规则不在函数体内执行 <js>, 顶层 return 非法。node --check 抓不到(脚本模式顶层 return 合法),
    #    故单独检测。只 WARN 不 ERROR: 部分钩子字段可能允许, 但解析字段实测不允许, 给提示换纯 XPath。
    PARSE_JS_FIELDS = ("bookList", "name", "author", "bookUrl", "coverUrl", "intro", "kind",
                       "wordCount", "lastChapter", "status", "chapterList", "chapterName",
                       "chapterUrl", "tocUrl", "nextTocUrl", "nextContentUrl")
    for grp in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
        region = _parse_rule_region(src.get(grp))
        if not isinstance(region, dict):
            continue
        for f in PARSE_JS_FIELDS:
            v = region.get(f)
            if not isinstance(v, str):
                continue
            for m in re.finditer(r"<js>(.*?)</js>", v, re.S):
                code = m.group(1)
                # 去注释 + 去字符串字面量, 避免 return/function 出现在串内或注释里误判
                s = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "''", code)
                s = re.sub(r"//[^\n]*|/\*.*?\*/", "", s, flags=re.S)
                if re.search(r"\bfunction\b|\b=>\s*[\(\{]|\(function\b", s):
                    continue  # 有函数/IIFE 上下文 → return 合法, 跳过
                if re.search(r"\breturn\b", s):
                    warns.append(
                        "[%s] %s.%s 的 <js> 含**顶层 return**: App 解析规则不在函数体内执行 <js>, 顶层 return 会 "
                        "invalid return(真机实测该字段解析失败/取空)。建议改纯 XPath; 若必须用 JS, 把逻辑包进 "
                        "IIFE: (function(){ ... return result; })()" % (label, grp, f))

    # 10) concurrentRate 是全局串行限速: 两次请求至少间隔 N 毫秒, 跨整本书源全局生效。
    #     分页目录(ruleToc.nextTocUrl)/分页正文(nextContentUrl)/发现分页会因此从"并发抓取"退化成"串行",
    #     加载时间 ≈ 页数 × N 毫秒。sk.3qdus.com 19 页目录被拖到 ~19 秒(浏览器只加载 1 页故秒开)。
    #     除非为绕过搜索限流刻意设置(shumi99 30秒间隔), 否则分页站点不要设。
    cr = src.get("concurrentRate")
    if isinstance(cr, str) and cr.strip():
        m = re.match(r"\s*(\d+)", cr)
        if m and int(m.group(1)) > 0:
            has_paging = bool(src.get("exploreUrl"))
            toc = _parse_rule_region(src.get("ruleToc"))
            if isinstance(toc, dict) and toc.get("nextTocUrl"):
                has_paging = True
            con = _parse_rule_region(src.get("ruleContent"))
            if isinstance(con, dict) and con.get("nextContentUrl"):
                has_paging = True
            if has_paging:
                warns.append(
                    "[%s] concurrentRate=%s 是全局串行限速(两次请求至少间隔 N 毫秒, 跨全书源): "
                    "叠加分页(目录/正文/发现)会把并发抓取退化成串行, 加载时间≈页数×N毫秒(实测19页目录被拖到~19秒)。"
                    "除非为绕过搜索限流刻意设置, 否则分页站点不要设; 限流改用 enabledCookieJar+loginCheckJs 双清" % (label, cr))

    # 11) nextTocUrl/nextContentUrl 取"分页条最后一个链接(尾页)"而非"下一页" → 跳页丢章。
    #     反模式: 写成 .page-link:last-child@href / a:last-of-type@href / 含"尾页"字样的选择器,
    #     取到的是分页条里**最后一个链接(尾页)**; 分页条是一组(首页/上一页/1/2/.../下一页/尾页),
    #     last-child 取尾页 → 翻1~2页后直接跳尾页, 中间章节全丢(黄金屋998章书只拿到298章实证)。
    #     正解: 纯 JS 按页码确定性递增(下一页优先, 否则 page+1, 末页返回空串自然停止防回环), 见
    #     site-patterns.md「目录/正文分页翻页」+「站点样本：黄金屋」+ pitfalls 铁律20。
    #     仅当该字段无 JS 页码逻辑时才 WARN(已用 @js:/<js> 自己判 next 的不属此反模式)。
    for grp, fld in (("ruleToc", "nextTocUrl"), ("ruleContent", "nextContentUrl")):
        region = _parse_rule_region(src.get(grp))
        if not isinstance(region, dict):
            continue
        v = region.get(fld)
        if not isinstance(v, str) or not v.strip():
            continue
        has_js = ("@js:" in v) or ("<js>" in v)
        if has_js:
            continue  # 已用 JS 自己判下一页, 不属此反模式
        if re.search(r"(?<!nth-)(last-child|last-of-type)|(?<!nth-):last\b|尾页", v):
            warns.append(
                "[%s] %s.%s 取到的是分页条**最后一个链接(尾页)**而非「下一页」: 翻1~2页后直接跳到尾页, "
                "中间章节全部丢失(998章书只拿到298章实证)。正解: 纯 JS 按页码确定性递增(下一页优先、否则"
                "page+1, 末页返回空串自然停止防回环), 见 site-patterns.md「目录/正文分页翻页」+"
                "「站点样本：黄金屋」+ pitfalls 铁律20。" % (label, grp, fld))


# Legado 3.25 反编译版 AnalyzeUrl 的 UrlOption 字段（实证）。
# 写错字段名不会报错——Gson 不拒绝未知字段——会被静默忽略，必须显式拦截。
URL_OPTION_FIELDS = {
    "method", "charset", "headers", "body", "origin", "retry", "type",
    "webView", "webWait", "webJs", "js", "serverID",
}
# 3.25 不认识的等待字段（历史/官方版写法）：写了不报错也不生效，需明确报错/提醒。
URL_OPTION_DEAD_WAIT = "webViewDelayTime"

# 历史上被误传、实际不存在的字段 → 正确字段名（3.25）
URL_OPTION_TYPOS = {
    "webviewDelayTime": "webWait",
    "webDelay": "webWait",
    "delayTime": "webWait",
    "webViewDelay": "webWait",
    "webViewWait": "webWait",
    "webViewCache": "(不存在)",
    "source": "origin",
    "userAgent": "headers 里的 User-Agent",
}


def check_url_options(src, label, errors, warns, notes=None):
    """校验 URL 行内选项的字段名，拦截静默失效的拼写错误"""
    targets = [("searchUrl", src.get("searchUrl"))]
    for i, item in enumerate(src.get("exploreUrl") or []):
        if isinstance(item, dict):
            targets.append(("exploreUrl[%d].url" % i, item.get("url")))
    # 详情页/目录/正文的规则里同样可以挂行内选项，必须一并校验
    for grp in ("ruleSearch", "ruleExplore", "ruleToc", "ruleBookInfo", "ruleContent"):
        g = src.get(grp)
        if isinstance(g, dict):
            for k in ("bookUrl", "chapterUrl", "content", "tocUrl"):
                if isinstance(g.get(k), str):
                    targets.append(("%s.%s" % (grp, k), g[k]))

    # 行内选项的定位必须用正则 `,\s*{`：Legado 按 `,\s*(?=\{)` 切分，
    # 逗号与花括号之间**允许有空格**。旧实现写成 `",\\s*{" not in raw and ",{" not in raw`
    # ——前半段把正则当字面量做 in 判断、恒为真，后半段只认无空格 `,{`，
    # 于是 `url, {"webView":true}` 这类写法会整段跳过字段校验（拼错字段漏报）。
    _inline_opt_re = re.compile(r",\s*\{")
    for pos, raw in targets:
        if not isinstance(raw, str):
            continue
        matches = list(_inline_opt_re.finditer(raw))
        if not matches:
            continue
        # 取出行内选项 JSON：最后一个 `,{` / `, {` 之后的部分（从 `{` 起）
        idx = matches[-1].end() - 1
        opt_str = raw[idx:]
        try:
            opt = json.loads(opt_str)
        except Exception:
            continue
        if not isinstance(opt, dict):
            continue
        # 3.25 不认识的等待字段：webViewDelayTime 在该版被 Gson 静默丢弃
        if URL_OPTION_DEAD_WAIT in opt:
            if "webWait" in opt:
                notes.append(
                    "[%s] %s 写了 webViewDelayTime=%s（3.25 不认识，会被静默丢弃），"
                    "同时写了 webWait=%s（3.25 实际生效的等待字段）。webViewDelayTime 多余，建议删掉只留 webWait"
                    % (label, pos, opt[URL_OPTION_DEAD_WAIT], opt["webWait"]))
            else:
                errors.append(
                    "[%s] %s 只写了 webViewDelayTime=%s：3.25 反编译版不认识这个字段，"
                    "会被 Gson 静默丢弃、等待退回默认约 1000ms。3.25 的等待字段是 webWait，请改成 webWait"
                    % (label, pos, opt[URL_OPTION_DEAD_WAIT]))

        for key in list(opt.keys()):
            if key == URL_OPTION_DEAD_WAIT:
                continue
            if key in URL_OPTION_FIELDS:
                continue
            if key in URL_OPTION_TYPOS:
                errors.append(
                    "[%s] %s 使用了不存在的选项字段 '%s': Legado 会静默忽略它(不报错也不生效)。"
                    "正确写法: %s" % (label, pos, key, URL_OPTION_TYPOS[key]))
            else:
                warns.append(
                    "[%s] %s 的选项字段 '%s' 不在 UrlOption 合法字段内, 很可能被静默忽略。"
                    "合法字段: %s" % (label, pos, key, ", ".join(sorted(URL_OPTION_FIELDS))))
        # webJs + webWait 联动
        if opt.get("webJs") and "webWait" not in opt:
            warns.append(
                "[%s] %s 有 webJs 但无 webWait: webJs 会使默认等待失效(只剩约 100ms), "
                "需显式补 webWait" % (label, pos))
        if opt.get("bodyJs") and opt.get("webView"):
            warns.append(
                "[%s] %s 的 bodyJs 在 webView 模式下不生效(仅 OkHttp 分支执行), 写了等于没写"
                % (label, pos))
        if "webJs" in opt and re.search(
                r"\b(async|await)\b|Promise|\.then\s*\(", str(opt["webJs"])):
            errors.append(
                "[%s] %s 的 webJs 含 async/await/Promise: evaluateJavascript 拿到的是 JSON 序列化的 "
                "'{}'，非空且非 null → Legado 判定成功并静默返回 '{}'，不报错不重试。"
                "webJs 必须是同步表达式" % (label, pos))


def check_source(src, idx, errors, warns, notes):
    label = src.get("bookSourceName") or ("#index-%d" % idx)

    if not isinstance(src, dict):
        errors.append("[%s] 书源应为 JSON 对象" % label)
        return

    # Legado 导出的规则区域(searchUrl/ruleBookInfo/ruleToc/ruleContent)是字符串化 JSON，
    # 先解析为对象以便校验内部子字段；解析失败则保持原样，后续会报“不是对象”。
    for _k in ("searchUrl", "ruleSearch", "exploreUrl", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
        _v = src.get(_k)
        if isinstance(_v, str) and not _v.strip().startswith("<js"):
            try:
                src[_k] = json.loads(_v)
            except Exception:
                pass

    for k in REQUIRED_TOP:
        if not src.get(k):
            errors.append("[%s] 缺必备顶层字段: %s" % (label, k))

    header = src.get("header")
    if not header:
        warns.append("[%s] 建议配置全局请求头 header(UA/Referer)，否则易遇 403/防爬" % label)
    elif isinstance(header, str) and not header.strip().startswith(("<js", "@js:")):
        # 🔴 3.25 反编译实锤(BookSource.getHeaderMap): header 非 @js:/<js> 开头时一律 GSON.fromJsonObject;
        #    行格式 'Key: Value' 解析失败 → 整段 header 被丢弃 → 回落默认桌面 UA(正文/反爬可能失败)。
        try:
            json.loads(header)
        except Exception:
            # 不是合法 JSON: 再判是否长得像 'Key: Value' 行格式(反爬头最容易踩)
            if re.search(r"(?im)^\s*\S[^:\n]*:\s*\S", header) and re.search(r"User-Agent|Referer|Cookie|Accept|Host", header):
                errors.append(
                    "[%s] header 不是合法 JSON 对象字符串: 3.25 反编译(BookSource.getHeaderMap)实锤 "
                    "header 非 @js:/<js> 开头时一律 GSON.fromJsonObject, 行格式 'Key: Value' 解析失败→整段丢弃→"
                    "回落默认桌面 UA(正文/反爬会失败, 且静默无报错)。应写成 "
                    r'{"User-Agent":"...","Referer":"..."}' % label)
            else:
                warns.append(
                    "[%s] header 不是合法 JSON(且非 <js>/@js: 动态生成): App 可能静默丢弃, 请确认是 JSON 对象字符串" % label)

    has_any_rule = False
    for key, getter, fields, disp in SUB_FIELDS:
        region = getter(src)
        if region is None:
            if key == "ruleSearch" and src.get("searchUrl"):
                # 配了搜索URL但没有搜索解析规则 → App 里搜索列表必为空
                errors.append("[%s] 配置了 searchUrl 但缺顶层 ruleSearch 解析对象(缺 bookList/name/bookUrl)" % label)
                continue
            warns.append("[%s] 未配置 %s" % (label, disp))
            continue
        has_any_rule = True
        if not isinstance(region, dict):
            errors.append("[%s] %s 不是对象" % (label, disp))
            continue
        for f in fields:
            if not region.get(f):
                errors.append("[%s] %s 缺字段: %s" % (label, disp, f))

    # 发现频道(exploreUrl)单独校验: 兼容列表/对象/纯URL形态, 校验每条 ruleExplore 的必备子字段
    explore_regions = get_explore_regions(src)
    if explore_regions is not None:
        if not explore_regions:
            warns.append("[%s] 配置了 exploreUrl 但无可用 ruleExplore" % label)
        else:
            for ei, reg in enumerate(explore_regions):
                if not isinstance(reg, dict):
                    errors.append("[%s] 发现解析(ruleExplore #%d) 不是对象" % (label, ei))
                    continue
                for f in ("bookList", "name", "bookUrl"):
                    if not reg.get(f):
                        errors.append("[%s] 发现解析(ruleExplore #%d) 缺字段: %s" % (label, ei, f))

    su = src.get("searchUrl")
    if isinstance(su, str) and su.strip().startswith("<js"):
        if not src.get("ruleSearch"):
            errors.append("[%s] searchUrl 为 <js> 动态URL, 必须配套顶层 ruleSearch 解析对象" % label)
        # 🚨 <js> 返回值契约(39书屋实战实证): 必须是「URL','{行内选项}」字符串。
        #    返回 JSON.stringify({'url':...}) 整体对象 → AnalyzeUrl.initUrl eval 后把返回值
        #    整体当 URL 字面量发请求(地址以 {"url" 开头) → 必然 404。
        #    本地 lint 只会报"请求失败", 真机翻日志才现形 —— 故在此静态拦下。
        #    合法写法 = URL + 英文逗号 + 行内选项JSON, options 里不会出现 url 键, 故零误报。
        _js_body = su[su.find("<js>"):su.rfind("</js>")] if "</js>" in su else su[su.find("<js>"):]
        _js_ns = re.sub(r"\s+", "", _js_body)
        if (re.search(r"JSON\.stringify\(\{['\"]?url['\"]?\s*[:=]", _js_ns)
                or re.search(r"return\{['\"]?url['\"]?\s*[:=]", _js_ns)):
            errors.append(
                "[%s] searchUrl 的 <js> 返回了整体 JSON 对象(如 JSON.stringify({'url':...})): "
                "3.25 真机(AnalyzeUrl.initUrl)把返回值整体当 URL 字面量发请求, 地址以"
                " {\"url\" 开头 → 必然 404。正确形态: return 'https://.../api/search?q='+key+','"
                "+JSON.stringify({charset:'UTF-8'}) —— URL + 英文逗号 + 行内选项JSON"
                "(详见 references/parse-paths.md「JS 注入」)" % label)
        # POST body 预编码坑(同为 39 书屋实证): App 发送环节会对 body 再做一次 form 编码,
        # JS 里预先 encodeURIComponent = 双重编码 → 服务端查无此书(code=0 但 search 数组空)。
        # URL query 里的编码是合法的, 故只盯 options 对象键 body: 的取值, 不误伤 URL, 也不误伤
        # 同名 JS 变量赋值(body=body+'&'+...)——后者是逐参数拼接, 与发送层编码无关。
        # 只 WARN: 3.25 实证如此, 但个别接口确有吃预编码的先例, 提示而不阻断。
        if re.search(r"body['\"]?\s*:[^,}]*encodeURIComponent", _js_ns):
            warns.append(
                "[%s] searchUrl 的 <js> 给 POST body 预编码了关键词(encodeURIComponent): "
                "App 发送请求体时会再做一次 form 编码, 双重编码会让服务端查无此书"
                " —— 表现为接口返回 code=0 但结果数组为空(39 书屋实战实证)。"
                "body 里放原值即可; 需要编码的只有 URL query 里的 {{key}}(App 自动编码)"
                % label)
    elif isinstance(su, dict) and not su.get("url"):
        errors.append("[%s] searchUrl 缺 url" % label)

    # charset 的落点: ① URL 行内选项 {"charset":"..."}(UrlOption.charset) ② header。
    # 🔴 3.25 反编译实锤(BookSource.java 顶层字段表): 书源顶层【没有】 charset 字段,
    #    写在顶层的 charset 会被 Gson 静默丢弃 —— 不要再建议用户往顶层写。
    # 旧检测只看序列化文本里有没有 "charset" 字样, 于是顶层死字段也能蒙混过关(整套回归曾靠它骗过检查)。
    # 改为显式区分: 顶层键 → 警告丢弃; 仅当 header / URL 行内选项 任一含 charset 才算"有效声明"。
    top_charset = src.get("charset")
    has_valid_charset = False
    if isinstance(header, str) and re.search(r'"charset"\s*:', header):
        has_valid_charset = True
    for _uk in ("searchUrl", "exploreUrl", "bookUrl", "tocUrl"):
        _uv = src.get(_uk)
        _cands = []
        if isinstance(_uv, str):
            _cands.append(_uv)
        elif isinstance(_uv, list):  # 这些键在 720-726 行已被 json.loads 成 list, 需展开检查每项 url 里的行内选项
            for _it in _uv:
                if isinstance(_it, dict):
                    _cands.append(str(_it.get("url", "")))
                elif isinstance(_it, str):
                    _cands.append(_it)
        for _cand in _cands:
            if '"charset"' in _cand:
                has_valid_charset = True
                break
    if top_charset:
        warns.append("[%s] 顶层 charset 会被静默丢弃: 3.25 反编译(BookSource.java 顶层字段表)实锤书源顶层"
                     "【没有】charset 字段, 写在顶层的 charset 会被 Gson 静默丢弃。请改写成 URL 行内选项"
                     r' {"charset":"utf-8"} 或写进 header' % label)
    elif not has_valid_charset:
        warns.append("[%s] 未见有效 charset 声明(GBK/UTF-8): 只能写在 URL 行内选项 "
                     r'{"charset":"utf-8"} 或 header 里, 写在书源顶层会被静默丢弃' % label)

    # 净化规则: 顶层 replaceRegex, 或 ruleContent.replaceRegex(Legado 3.x), 或 content 内嵌 ##
    # 🔴 3.25 反编译实锤: 部分定制版 APK 对 ruleContent.replaceRegex 零消费(死字段),
    #    且 <js> 管道正文中 "##" 会被 Rhino 当字符串, 故最可靠的净化是写在 content 的 JS 内。
    rr = src.get("replaceRegex")
    rc = _parse_rule_region(src.get("ruleContent"))
    rc = rc if isinstance(rc, dict) else {}
    content_rule = rc.get("content", "")
    if not rr:
        rr = rc.get("replaceRegex")  # Legado 3.x 支持 ruleContent.replaceRegex
    js_sanitized = isinstance(content_rule, str) and ("<js>" in content_rule and ("continue" in content_rule or "break" in content_rule or ".test(" in content_rule))
    if not rr:
        if not (isinstance(content_rule, str) and "##" in content_rule) and not js_sanitized:
            warns.append("[%s] 未配置 replaceRegex / content 内嵌 ## / JS 内净化过滤, 正文可能夹带广告(注意: 部分定制版App不执行ruleContent.replaceRegex, 净化请写进content的JS)" % label)

    check_field_ownership(src, label, errors, warns)
    check_url_options(src, label, errors, warns, notes)
    check_rule_pitfalls(src, label, errors, warns, notes)
    _check_js_syntax(src, label, errors, warns, notes)

    if not has_any_rule:
        errors.append("[%s] 没有任何解析区域(ruleSearch/ruleBookInfo/ruleToc/ruleContent)，书源不可用" % label)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: python3 validate_booksource.py <书源.json|-> [--strict]")
        print("  --strict   把 WARN 也计入失败(交付终审用; 默认只 ERROR 算失败)")
        print("  - 作为路径时从 stdin 读 JSON")
        sys.exit(0 if len(sys.argv) >= 2 else 2)

    path = sys.argv[1]
    strict = "--strict" in sys.argv

    try:
        data = load_source(path)
    except Exception as e:
        print("无法读取/解析 JSON: %s" % e)
        sys.exit(2)

    errors, warns, notes = [], [], []

    # 交付形态检查: App 本地导入(Gson)要求 BEGIN_ARRAY, 单对象会 ImportError(用户表现为"改了没生效")
    if path != "-":
        try:
            with open(path, "r", encoding="utf-8") as _f:
                _raw = json.load(_f)
            if not isinstance(_raw, list):
                errors.append(
                    "[交付形态] 文件顶层不是 JSON 数组: 开源阅读本地导入用 Gson 解析并要求 BEGIN_ARRAY, "
                    "单对象会 ImportError: Expected BEGIN_ARRAY but was BEGIN_OBJECT —— 新书源从未导入成功, "
                    "用户会以为'规则没生效'。交付前请包成 [{...}]")
        except Exception:
            pass

    if isinstance(data, list):
        for i, s in enumerate(data):
            check_source(s, i, errors, warns, notes)
    else:
        check_source(data, 0, errors, warns, notes)

    print("=" * 50)
    print("校验结果: ERROR=%d  WARN=%d  NOTE=%d" % (len(errors), len(warns), len(notes)))
    print("=" * 50)
    for e in errors:
        print("[ERROR] %s" % e)
    for w in warns:
        print("[WARN ] %s" % w)
    for n in notes:
        print("[NOTE ] %s" % n)
    if not errors and not warns and not notes:
        print("书源字段完整，符合规范。")
    print("=" * 50)

    sys.exit(1 if (errors or (strict and warns)) else 0)


if __name__ == "__main__":
    main()
