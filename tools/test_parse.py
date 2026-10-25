#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开源阅读(Legado)3.0 书源解析命中本地验证工具。

用途:
    拿到真实页面 HTML 样本后, 在本地"对齐 3.25 真机引擎"地跑书源里的解析规则,
    报告每个区域/字段是否命中、命中数量与前几个样例, 把"推测版"变成"可验证版"。
    这是 validate_booksource.py(只查字段完整性) 的必要补充——它查"规则对不对"。
    引擎对齐: XPath(以 / 或 @XPath: 开头)用 lxml 跑; JSOUP 默认规则(@ 层级分隔,
    形如 .类@标签@属性, 是 3.25 真机默认引擎)用 BeautifulSoup 对齐 Jsoup 的 select;
    其中扩展属性选择器走内置真 Jsoup 通道(scripts/jsoup_eval/, jar + JsoupRuleEval)
    忠实复刻真机行为: ~= 是 Jsoup 正则匹配操作符, bs4 无法等价建模; 问号形态则并非操作符——
    Jsoup 将 ? 解析进属性名, [attr?=val] 恒不命中, 真机同结果; 通道不可用时降级为「需真机验证」;
    JSONPath 用 jsonpath_ng; JS(<js>)标注需真机, 不假通过。

用法:
    python3 test_parse.py <书源.json> \
        [--search  search.html] \
        [--explore explore.html] \
        [--bookinfo info.html] \
        [--toc toc.html] \
        [--content content.html] \
        [--json api.json]   # 给 JSONPath 规则用的 JSON 样本

说明:
    - Legado 3.0 真实 schema: 解析规则在顶层独立对象 ruleSearch/ruleExplore/ruleBookInfo/
      ruleToc/ruleContent, 键名为 bookList/name/author/chapterList/chapterUrl/content 等
      (与 App 编辑界面一致); 旧写法(规则内嵌 searchUrl、键带 rule 前缀)已做归一化兼容。
    - 支持 XPath / JSOUP 默认规则(@ 层级分隔, 对齐 3.25 真机) / JSONPath / JS:
      XPath(以 / 或 @XPath: 开头)走 lxml; JSOUP(默认模式, 形如 .类名@标签@属性 /
      #id / tag / 前缀 - 列表倒置)走 BeautifulSoup 对齐 Jsoup 的 select; JS(<js>)
      与部分 @CSS: 标注需真机或按说明处理, 不假通过。.类名@标签 是合法 JSOUP 规则,
      不再误判为 XPath 的 Invalid expression。
    - 支持 Legado 扩展语法: && 备选链、|| (JsoupXpath 节点并集, 本地合并去重模拟)、
      ## 正则清洗(尽力模拟)。JS(<js>)规则不本地执行, 明确标注「需真机验证」而非假通过。
    - 只验证解析字段(rule*), 跳过 url/method/charset/headers/body 等配置字段; 可选展示字段缺失不计入失败。
    - HTML 样本按书源 charset 读取(缺省回退 gb18030→utf-8), 兼容 GBK 老站。
    - 退出码: 0 核心字段全部命中; 1 有核心字段 MISS/ERR; 2 参数/解析错误。
"""
import sys
import os
import json
import re
import argparse
import shutil
import subprocess
import base64
import tempfile
from collections import Counter

try:
    from lxml import html as lxml_html
except Exception as e:
    print("缺少 lxml, 请先安装: sudo pip3 install lxml (%s)" % e)
    sys.exit(2)

try:
    import jsonpath_ng.ext as jsonpath_mod
    HAVE_JSONPATH = True
except Exception:
    HAVE_JSONPATH = False

# JSOUP 默认规则引擎对齐: 用 BeautifulSoup 的 select 替代 Jsoup 的 select()
try:
    from bs4 import BeautifulSoup, Tag
    HAVE_BS4 = True
except Exception:
    BeautifulSoup = None
    Tag = None
    HAVE_BS4 = False


# Legado 3.0 真实 schema (与 App 编辑界面/官方文档一致):
#   searchUrl/exploreUrl 只放 URL(或<js>), 解析规则在顶层独立对象 ruleSearch/ruleExplore/
#   ruleBookInfo/ruleToc/ruleContent, 键名无 rule 前缀(bookList/name/author/chapterList/...)。
# 旧写法(规则内嵌 searchUrl 对象、键带 rule 前缀)也见过, 这里统一归一化兼容两种。
KEY_ALIAS = {
    "ruleBookList": "bookList", "ruleName": "name", "ruleAuthor": "author",
    "ruleKind": "kind", "ruleWordCount": "wordCount", "ruleLastChapter": "lastChapter",
    "ruleIntroduce": "intro", "ruleIntro": "intro", "ruleCoverUrl": "coverUrl",
    "ruleBookUrl": "bookUrl", "ruleChapterList": "chapterList",
    "ruleChapterName": "chapterName", "ruleChapterUrl": "chapterUrl",
    "ruleContent": "content", "ruleTocUrl": "tocUrl", "ruleCanReName": "canReName",
    "ruleNextTocUrl": "nextTocUrl", "ruleNextContentUrl": "nextContentUrl",
    "ruleBookInfoInit": "bookInfoInit", "rulePreUpdateJs": "preUpdateJs",
    "ruleFormatJs": "formatJs", "ruleChapterInfo": "updateTimes",
}

# 区域配置类键(非解析规则, 不验证)
CONFIG_KEYS = {"url", "method", "charset", "headers", "body", "webView", "type", "checkKeyWord"}

# 各区域的"容器字段"与"相对子字段"
CONTAINER = {
    "searchUrl": ("bookList", ["name", "author", "bookUrl", "coverUrl", "intro", "kind", "lastChapter"]),
    "ruleToc": ("chapterList", ["chapterName", "chapterUrl"]),
    "ruleExplore": ("bookList", ["name", "author", "bookUrl", "coverUrl", "intro", "kind", "lastChapter"]),
}

# 各区域真正需要验证的"解析字段"白名单(排除 url/method/charset/headers/body 等配置)
PARSER_BY_REGION = {
    "searchUrl": ["bookList", "name", "author", "bookUrl", "coverUrl", "intro", "kind", "lastChapter"],
    "ruleBookInfo": ["name", "author", "coverUrl", "intro", "kind", "lastChapter", "wordCount", "tocUrl"],
    "ruleToc": ["chapterList", "chapterName", "chapterUrl"],
    "ruleContent": ["content"],
    "ruleExplore": ["bookList", "name", "author", "bookUrl", "coverUrl", "intro", "kind", "lastChapter"],
}

# 可选展示字段: 缺失/为空不计入失败(仅提示)
OPTIONAL = {"author", "coverUrl", "intro", "kind", "lastChapter", "wordCount"}


def norm_keys(region):
    """把旧键名(ruleXxx)归一化为 Legado 真实键名(驼峰无前缀), 并解析字符串化 JSON。"""
    if not isinstance(region, dict):
        return region
    out = {}
    for k, v in region.items():
        out[KEY_ALIAS.get(k, k)] = v
    return out


def norm_region(val):
    """规则区可能是对象, 也可能是字符串化 JSON; 统一解析并归一化键名。"""
    if isinstance(val, str) and not val.strip().startswith("<js"):
        try:
            val = json.loads(val)
        except Exception:
            return None
    return norm_keys(val)


def is_jsonpath(expr):
    return isinstance(expr, str) and expr.lstrip().startswith("$.")


def split_chains(expr):
    """按 Legado 规则分隔符 && 拆成备选/链式规则段(前一段取空才试下一段)。

    非字符串(JSON 里 rule* 误配成数字/对象/数组): 真机 AnalyzeUrl 链同样不成立,
    本地中性返回空段(调用方按"无结果"继续), 不把类型错误升级成 AttributeError 崩栈。
    """
    if not isinstance(expr, str):
        return []
    return [s.strip() for s in expr.split("&&") if s.strip()]


def split_union(locator):
    """按 || 拆成并集分支。

    ⚠️ 关键事实(3.25 反编译+真机证实): Legado 规则分析层只认 && 一个分隔符,
    || 不是规则分隔符——它整串被丢给 XPath 引擎(JsoupXpath), 由引擎按「节点集并集」
    求值(等价于 XPath 的 |, 但 JsoupXpath 额外支持 || 写法)。lxml 不原生支持 ||,
    直接求值会抛 XPath 异常 → 把本来正确的规则误判成 ERR。这里用「分别求值再合并去重」
    模拟 JsoupXpath 的并集语义, 让本地验证与真机对齐。
    非字符串误配: 同 split_chains, 中性返回空, 不崩栈。
    """
    if not isinstance(locator, str):
        return []
    return [s.strip() for s in locator.split("||") if s.strip()]


def _dedup_nodes(nodes):
    seen, out = set(), []
    for n in nodes:
        key = id(n)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _has_inline_js(expr):
    """规则是否含内联 <js> 管道(如 xpath<js>...</js>), 即 <js 不在开头。"""
    if not isinstance(expr, str):
        return False
    s = expr.strip()
    return ("<js" in s) and (not s.startswith("<js"))


def split_inline_js(expr):
    """去掉内联 <js>...</js> 管道, 返回前面的 XPath/规则部分(本地可验证部分)。

    无内联 <js> 时返回 (原串剥离, False) 而非截断 —— 否则 idx=-1 会让 expr[:-1]
    吞掉末字符, 导致前导点告警的"改写为 '%s'"建议值残缺(如 .//a@text 建议成 //a@tex),
    用户照抄写出坏规则。
    """
    if not isinstance(expr, str):
        return "", False
    idx = expr.find("<js")
    if idx < 0:
        return expr.strip(), False
    return expr[:idx].strip(), True


def _is_template(expr):
    """Legado 模板占位字面量(如 {{page}} / {{"https://..."}}): 运行时由 App 填充,
    不是 XPath/CSS/正则, 不应作为规则本地验证(否则会 MISS/ERR 误报)。"""
    if not isinstance(expr, str):
        return False
    s = expr.strip()
    return ("{{" in s) and ("}}" in s)


def strip_url_options(expr):
    """剥离 Legado 规则字符串末尾的 URL 行内选项 `,{...}`（如 `,{"webView":true,"webWait":3000}`）。

    这些选项是 App 层网络配置（WebView / 等待 / 请求方法），不是 XPath / 正则，
    本地解析前必须剥掉，否则会污染 XPath（如 `//a/@href,{"webView":true}` 被当非法 XPath）。

    切分语义按 3.25 真机实证（AnalyzeUrl.smali: paramPattern = `\\s*,\\s*(?=\\{)`,
    matcher.find() 取**第一个**「逗号后(可带空白)跟 {」的位置从此切开）。
    旧实现是末尾锚定正则 `,\\s*\\{[^}]*\\}$`, 两个真机不符点:
      1) `[^}]*` 到第一个 `}` 就停 → webJs/bodyJs 里写 JS 对象(嵌套花括号)时剥不干净,
         残留片段污染规则; 改为括号配对扫描(跳过字符串字面量与转义), 兼容任意嵌套。
      2) 末尾锚定与真机「第一个逗号即切」语义不同。
    保守兜底: 切点后若不是配平到串尾的 JSON 对象(尾随垃圾/花括号不闭合),
    视为 URL 内容里的假阳性, 原样返回不剥。
    """
    s = (expr or "").strip()
    for i, ch in enumerate(s):
        if ch != ",":
            continue
        j = i + 1
        while j < len(s) and s[j].isspace():
            j += 1
        if j >= len(s) or s[j] != "{":
            continue  # 该逗号后不是 { → 不是行内选项分隔点, 看下一个逗号
        # 括号配对(跳过字符串/转义)到串尾才算完整选项对象
        depth, k, in_str, esc = 0, j, None, False
        while k < len(s):
            c = s[k]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == in_str:
                    in_str = None
            elif c in "\"'":
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth == 0 and k < len(s) and not s[k + 1:].strip():
            m = i  # 匹配起点回退到逗号前的空白(对齐 \s*,\s* 的匹配范围)
            while m > 0 and s[m - 1].isspace():
                m -= 1
            return s[:m] if m else s[:i]
        # 没配平或 } 后有尾随内容: 不是干净的行内选项, 继续找下一个逗号
    return s


def split_regex(locator):
    """按 Legado 3.25 源码语义拆分 ## 清洗规则（已核对 AnalyzeRule$SourceRule）：

    源码（AnalyzeRule.java 353-363）就是纯 split：
        List parts = split(rule, "##", limit=6)
        rule         = parts[0]
        replaceRegex = parts[1]   （若存在）
        replacement  = parts[2]   （若存在；字段默认值 "" → 只有两段时是「删除匹配」）
        replaceFirst = true        （若存在 parts[3]）

    ⚠️ 因此不存在 "###" 这种特殊分隔：写 `##正则###$1` 会被切成
    [正则, "#$1"]，替换结果前面多一个 '#'。正确写法是 `##正则##$1`。

    返回 (rule, [(pattern, replacement, replace_first), ...])
    """
    raw = (locator or "").strip()
    if "##" not in raw:
        return strip_url_options(raw), []
    parts = raw.split("##", 5)  # limit=6 → 最多 6 段
    parts[0] = strip_url_options(parts[0])  # URL 段剥离行内选项后再拆 ##
    rule = parts[0].strip()
    pattern = parts[1] if len(parts) > 1 else ""
    replacement = parts[2] if len(parts) > 2 else ""  # 无第三段 → 删除匹配
    replace_first = len(parts) > 3
    if not pattern:
        return rule, []
    return rule, [(pattern, replacement, replace_first)]


def _legado_repl_to_python(rep):
    """Legado 替换串的 $1/$0 组引用 → Python re.sub 的 \\g<N>。"""
    return re.sub(r"\$(\d+)", lambda m: "\\g<%d>" % int(m.group(1)), rep)


def apply_regex_ops(texts, ops):
    """对文本列表应用 Legado ## 正则清洗。

    op 形态: (pattern, replacement, replace_first)
      - replacement 为空 → 删除所有匹配（Legado 默认行为）
      - replacement 非空 → 替换（支持 $N 组引用，已转 \\g<N>）
      - replace_first 为真 → 只替换第一个匹配

    返回 (texts, err): 正则编译失败(漏右括号/非法转义等)时真机会抛 RegexException
    导致该字段解析失败/取空——本地必须如实报错。旧版 except 后原样返回文本,
    坏正则反而全绿通过(静默假绿), 是最危险的一类漏报。
    """
    if not ops:
        return texts, None
    out = texts
    try:
        for pattern, replacement, replace_first in ops:
            if pattern.strip() == "$":
                # Legado 惯用法 ##$##替换: 把整串替换为字面量(不是正则结尾锚点 $);
                # 例如 ruleBookInfo.tocUrl 的 `##$##desc.html` 意为整段置为 desc.html。
                out = [(replacement if replacement else "") for _ in out]
                continue
            rx = re.compile(pattern)
            count = 1 if replace_first else 0
            if replacement:
                rep = _legado_repl_to_python(replacement)
                out = [rx.sub(rep, t, count=count) for t in out]
            else:
                out = [rx.sub("", t, count=count) for t in out]
        return out, None
    except Exception as ex:
        return texts, "##正则错误(真机抛 RegexException 致该字段解析失败): %s" % ex


def to_text(v):
    if isinstance(v, str):
        return v.strip()
    if hasattr(v, "text_content"):
        return v.text_content().strip()
    if hasattr(v, "text"):
        return (v.text or "").strip()
    return str(v).strip()


def to_relative(locator):
    """把 Legado 子规则的 //... 转成 lxml 相对当前节点的写法。

    Legado(JsoupXpath) 里列表子规则是**相对列表节点**求值的: JXNode.sel("//text()")
    只取该节点下的文本。而 lxml 的 "//" 恒从文档根开始, 直接求值会把整页文本/属性
    都算进来(命中数虚高、样例混进别的区块), 让本来正确的规则被误判成有问题。
    """
    if not locator:
        return locator
    loc = locator.strip()
    if loc.startswith("//"):
        rest = loc[2:]
        if rest.startswith("@"):
            # 裸属性(如 //@href): Legado 取的是列表节点自身的属性, 故用 descendant-or-self
            return "descendant-or-self::*/" + rest
        return "descendant::" + rest
    if loc.startswith("/"):
        return "./" + loc[1:]
    return loc


JS_SKIP = "__JS_RULE__"
# ':' 正则模式(Legado 书籍列表/目录列表专用规则模式, 见 apk-3.25-verified-facts.md):
# 本地不建模, 如实降级为「需真机验证」, 绝不误当 CSS/XPath 跑出与真机语义不符的结果
REGEX_SKIP = "__RULE_REGEX__"
# 空规则(未配置/空白串): 真机视为字段未配置, 本地同样中性跳过, 不计失败
EMPTY_RULE = "__EMPTY_RULE__"


def _is_regex_rule(expr):
    """Legado ':' 正则规则模式判定(书籍/目录列表专用)。'::' 是合法 CSS 伪类写法, 不算。"""
    if not isinstance(expr, str):
        return False
    s = expr.lstrip()
    return s.startswith(":") and not s.startswith("::")


def eval_rule_nodes(node, expr, relative=False):
    """返回节点列表(用于容器/相对子字段定位), 不转文本、不应用 ## 文本清洗。
    relative=True 时按 Legado 语义相对当前节点求值(列表子规则)。
    语义对齐真机: && 备选链(前段取空试下一段); 每段内的 || 为 JsoupXpath 并集
    (各分支分别求值后合并去重)。出错返回 (None, 错误)。"""
    if not expr or not str(expr).strip():
        return [], EMPTY_RULE
    if _is_regex_rule(expr):
        # ':' 正则容器本地不建模(防 cmode 路由偏差落入 xpath 求值)
        return [], REGEX_SKIP
    if str(expr).strip().startswith("<js"):
        # 容器是纯 <js>: 真机上由 Rhino 返回节点列表, 本地无 Rhino → 中性跳过(需真机),
        # 不能把 <js> 当 XPath 丢给 lxml 求值(那会抛 XPathEvalError 造成假 ERR)。
        return [], JS_SKIP
    for seg in split_chains(expr):         # && 备选链
        locator, _ops = split_regex(seg)  # 容器层忽略 ##(文本级清洗)
        if not locator:
            continue
        collected, seg_err = [], None
        for branch in split_union(locator):  # || 并集分支
            try:
                r = node.xpath(to_relative(branch) if relative else branch)
            except Exception as e:
                seg_err = "XPath不支持(Legado扩展?):%s" % e
                continue
            if r is None:
                r = []
            if not isinstance(r, list):
                r = [r]
            collected.extend(r)
        if collected:
            return _dedup_nodes(collected), None
        if seg_err:
            return None, seg_err
    return [], None


# Legado 扩展属性选择器(~=)bs4/soupsieve 无法等价建模:
# 反编译 AnalyzeByJSoup.getElementsSingle 实证, Legado 对 [attr~=val] 不做任何自定义处理,
# 直接 temp.select(beforeRule) 委托给 Jsoup 原生引擎。因此唯一忠实做法是调用真 Jsoup 求值,
# 而非用 Python 硬猜复刻(Jsoup 的 ~= 是【正则匹配】, jsoup-1.17.2 实测: 无词边界——foobar
# 也中 ~=foo; | 为正则 OR——[a~=x|y] 双命中; . 为任意字符——[a~=f.o] 中 foo; 复刻必漏)。
# ⚠ ?= 不是操作符(2026-10-25 审计实证, jsoup-1.17.2 实测可复跑):
#    Jsoup 把 ? 解析进【属性名】, [attr?=val] 恒不命中、不报错; 反编译坐实 CSS 选择器透传
#    select(), 故真机同结果——写了等于静默取空。路由正则保留 \? 是让此类规则也走真通道,
#    拿到与真机一致的恒空, 而非假装它有语义。行为已固化为回归:
#    evals/jsoup_realdevice_equiv.py 的「幻影操作符?=恒不命中」用例。
# jar 缺失或 Java 不可用时, 仍优雅降级为 JSOUP_EXT(「需真机验证」), 不假通过、不误报非法。
JSOUP_EXT = "__JSOUP_EXT_ATTR__"
_LEGADO_EXT_ATTR = re.compile(r"\[[^\]]*(\~|\?)=\s*[^\]]*\]")

# ---- 真机等价求值通道: 用打包的 org.jsoup 复刻 Legado JSOUP 引擎, 忠实求值 ~= 等规则 ----
_JSOUP_JAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jsoup_eval", "jsoup-1.17.2.jar")
_JSOUP_HELPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jsoup_eval")
_JSOUP_READY = None  # None=未探测; True/False 缓存


def _find_java():
    """定位 java 可执行文件。"""
    cand = shutil.which("java")
    if cand:
        return cand
    # JAVA_HOME 可能指向 JDK 根目录(无 bin/ 拼不成可执行文件), 也可能直接指向 bin 目录;
    # 两种形态都要试, 否则设了 JAVA_HOME 反而找不到旁边的 java。
    for p in [os.environ.get("JAVA_HOME", ""),
              "/usr/lib/jvm/default-java", "/usr/lib/jvm/default-java/bin", "/usr/bin"]:
        for sub in ("", "bin"):
            if not p:
                continue
            exe = os.path.join(p, sub, "java") if sub else os.path.join(p, "java")
            if os.path.isfile(exe):
                return exe
    return ""


def _find_javac():
    """定位 javac(与 java 同目录优先, 再退回 PATH)。"""
    cand = shutil.which("javac")
    if cand:
        return cand
    java = _find_java()
    if java:
        exe = os.path.join(os.path.dirname(java), "javac")
        if os.path.isfile(exe):
            return exe
    return ""


def _jsoup_engine_available():
    """探测真 Jsoup 求值通道是否可用(java + jar + 编译好的助手类); 结果缓存。"""
    global _JSOUP_READY
    if _JSOUP_READY is not None:
        return _JSOUP_READY
    java = _find_java()
    if not java or not os.path.isfile(_JSOUP_JAR):
        _JSOUP_READY = False
        return False
    helper = os.path.join(_JSOUP_HELPER_DIR, "JsoupRuleEval.class")
    if not os.path.isfile(helper):  # 现场编译(需 javac)
        javac = _find_javac()
        src = os.path.join(_JSOUP_HELPER_DIR, "JsoupRuleEval.java")
        if javac and os.path.isfile(src):
            try:
                subprocess.run([javac, "-cp", _JSOUP_JAR, src], cwd=_JSOUP_HELPER_DIR,
                               capture_output=True, timeout=60)
            except Exception:
                pass
    _JSOUP_READY = os.path.isfile(os.path.join(_JSOUP_HELPER_DIR, "JsoupRuleEval.class"))
    return _JSOUP_READY


def _jsoup_real_eval(html, rule):
    """用真 Jsoup 求值单条 JSOUP 规则(整条 @ 链 + 末段取值), 返回 (文本列表, None)。
    html 可为 str 或 bs4 节点(取其 HTML 序列化); 通道不可用时返回 (None, JSOUP_EXT) 降级。"""
    if not _jsoup_engine_available():
        return None, JSOUP_EXT
    java = _find_java()
    if isinstance(html, str):
        html_str = html
    else:
        html_str = str(html)
    fd, path = tempfile.mkstemp(suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html_str)
        proc = subprocess.run(
            [java, "-cp", "%s:%s" % (_JSOUP_JAR, _JSOUP_HELPER_DIR),
             "JsoupRuleEval", path, rule],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return None, JSOUP_EXT
        out = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(base64.b64decode(line).decode("utf-8"))
            except Exception:
                pass
        return out, None
    except Exception:
        return None, JSOUP_EXT
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

# 收集需真机验证的 JS 字段与字段可用性提示(死字段/活字段), 供结论区汇总
JS_NOTE_FIELDS = []
FIELD_NOTES = []
# 书源是否配置了 loginCheckJs(过墙/取 cookie 用); 影响搜索本地验证的定性
HAS_LOGINCHECKJS = False


def eval_rule(node, expr, relative=False):
    """评估一条 Legado 规则(可能含 && / || / ##), 返回 (结果文本列表, 错误)。
    先取节点(支持 && 备选链、|| 并集), 再把命中节点转文本并应用 ## 正则清洗。
    <js> 规则本地无法执行, 返回 JS_SKIP, 由报告层标为「需真机验证」(不计入失败)。"""
    if not expr or not str(expr).strip():
        return [], EMPTY_RULE
    if _is_regex_rule(expr):
        # ':' 正则模式(书籍/目录列表专用)本地不建模; 旧版丢给 lxml/CSS 求值会得到与真机
        # 语义不符的假结果(本地绿、真机错), 如实降级
        return [], REGEX_SKIP
    if expr.strip().startswith("<js"):
        # JS 规则要 Rhino + java 对象才能跑, 本地没有; 不能因为跑不了就判规则错。
        return [], JS_SKIP
    for seg in split_chains(expr):         # && 备选链
        locator, ops = split_regex(seg)
        if not locator:
            continue
        texts, seg_err = [], None
        for branch in split_union(locator):  # || 并集分支
            nodes, err = eval_rule_nodes(node, branch, relative=relative)
            if err:
                seg_err = err
                continue
            texts.extend([to_text(x) for x in nodes if to_text(x) != ""])
        texts = [t for t in texts if t]
        if texts:
            _ops_out, _rx_err = apply_regex_ops(texts, ops)
            if _rx_err:
                return None, _rx_err
            return _ops_out, None
        if seg_err:
            return None, seg_err
    return [], None


# ===================== JSOUP 默认规则引擎对齐 =====================
# Legado 3.25 真实引擎(反编译 AnalyzeByJSoup / ElementsSingle 实证):
#   - 模式判定(SourceRule): 以 @CSS: 开头→纯 CSS; 否则默认 JSOUP(@ 是层级分隔符)。
#   - 规则按 @ 拆成层级段, 逐段在上一层结果上 getElementsSingle 收窄。
#   - getElementsSingle 对每段 beforeRule: 首段为 children/class/text/tag/id 走专用方法,
#     否则整段当 CSS select(beforeRule)。beforeRule 为空→返回 element.children()。
#     关键: 对 [attr~=val] 等扩展属性选择器**不做任何自定义处理**, 直接
#     temp.select(beforeRule) 委托 Jsoup 原生引擎 -> bs4/soupsieve 无法等价建模。
#     ([attr?=val] 同理透传, 但 ?= 并非操作符——Jsoup 把 ? 解析进属性名, 恒不命中, 见 L410。)
#   - 前缀 - 是"列表倒置"标记(官方文档明载), 仅反转结果顺序, 不影响命中数。
#   - 方括号 [n]/[-n]/[0:1] 是元素索引, 取第 n 个/范围(本地暂只取末段整体, 不逐索引)。
# 本地用 BeautifulSoup 对齐 Jsoup 的 select(基本选择器 .class/tag/#id/[attr]/后代/子代 一致);
# 扩展属性操作符(~=)走内置真 Jsoup 通道(_jsoup_real_eval)忠实求值, 通道不可用时降级 JSOUP_EXT;
# 含 ?= 的规则同样走该通道(得到与真机一致的恒空), 但 ?= 不是操作符, 见 L410 注释块。

def detect_mode(expr):
    """按 3.25 真机规则模式判定, 决定用哪套本地引擎。
    XPath(以 / 或 @XPath: 开头) → lxml; JSOUP(默认, 非上述前缀) → BeautifulSoup;
    @Json:/$./$[ → JSONPath; <js → JS(需真机); @CSS: → CSS(BeautifulSoup select)。"""
    if not isinstance(expr, str):
        return "xpath"
    e = expr.strip()
    if not e:
        return "xpath"
    if e.startswith("<js"):
        return "js"
    if e.startswith("@XPath:"):
        return "xpath"
    if _is_regex_rule(e):
        return "regex"   # ':' 正则模式本地不建模, 由报告层标「需真机验证」
    if e.startswith("@Json:") or e.startswith("$.") or e.startswith("$[") or is_jsonpath(e):
        return "json"
    if e.startswith("@CSS:"):
        return "css"
    if e.startswith("@@"):
        return "jsoup"
    if e.startswith("/"):
        return "xpath"
    return "jsoup"


_ATTR_RE = re.compile(r"\[([A-Za-z_][\w-]*)=([^\]'\"]+)\]")


def _quote_attr(sel):
    """对齐 Jsoup 的宽松度: 给未加引号的属性选择器值自动加引号(如 [property=og:title]
    → [property="og:title"]), 否则 bs4/soupsieve 会因值里的 ':' 等报 Malformed。
    已加引号的不会二次加引号; 仅影响默认 CSS 分支, 不改变选择语义。"""
    return _ATTR_RE.sub(r'[\1="\2"]', sel)


def _jsoup_single(bs, before):
    """对齐 ElementsSingle.getElementsSingle: before 为每段(已剥离 [] 索引)。
    before 为空→children; 首段 children/class/text/tag/id 走专用; 否则整段 select(before)。"""
    if before == "":
        return [c for c in bs.children if isinstance(c, Tag)]
    parts = before.split(".", 5)  # Kotlin split(limit=6)
    typ = parts[0]
    if typ == "children":
        return [c for c in bs.children if isinstance(c, Tag)]
    if typ == "class":
        return bs.select(".%s" % parts[1]) if len(parts) > 1 else []
    if typ == "tag":
        return bs.find_all(parts[1]) if len(parts) > 1 else []
    if typ == "id":
        el = bs.find(id=parts[1]) if len(parts) > 1 else None
        return [el] if el else []
    if typ == "text":
        return [t.parent for t in bs.find_all(string=lambda s: s and len(parts) > 1 and parts[1] in s)
                if isinstance(t.parent, Tag)]
    return bs.select(_quote_attr(before))  # default: 整段当 CSS(给属性值补引号以对齐 Jsoup)


def _strip_rule_prefix(rule):
    """剥离 JSOUP 规则前缀(@CSS: / @@) 与列表倒置标记(-), 返回 (core, reversed_flag)。"""
    core = rule.strip()
    rev = core.startswith("-")
    core = core.lstrip("-")
    if core.startswith("@CSS:"):
        core = core[len("@CSS:"):]
    elif core.startswith("@@"):
        core = core[2:]
    return core, rev


_IDX_RE = re.compile(r"\[(\d+)\]")


def _strip_index(seg):
    """把段拆成 (选择器, 数字索引或 None)。只识别末端 [数字] 索引(如 li[0] / div[2])，
    绝不误伤 [attr=val] 这类 CSS 属性选择器(无数字, 原样保留, 对齐 Legado findIndexSet 只解 [\\d+])。"""
    m = _IDX_RE.search(seg)
    if not m:
        return seg.strip(), None
    idx = int(m.group(1))
    selector = (seg[:m.start()] + seg[m.end():]).strip()
    return selector, idx


def _apply_index(elements, idx):
    """按数字索引保留单个元素; 越界返回空(对齐 Legado findIndexSet 的 indexList 行为)。"""
    if idx is None:
        return elements
    if 0 <= idx < len(elements):
        return [elements[idx]]
    return []


def _jsoup_select_elements(node, core):
    """纯元素选择(容器层): @ 层级逐段收窄, 忽略取值指示符(text/html/@attr),
    返回元素节点列表(bs4 Tag)。中间段命中 0 → 返回空。支持 [N] 数字索引。"""
    segs = core.split("@")
    res = [node]
    for i, seg in enumerate(segs):
        selector, idx = _strip_index(seg)
        if selector in ("text", "html") or selector.startswith("@"):
            if i == len(segs) - 1:
                break
            continue
        nxt = []
        for el in res:
            nxt.extend(_jsoup_single(el, selector))
        res = _apply_index(nxt, idx)
        if not res:
            break
    return res


def _jsoup_extract(res, last_seg):
    """对元素列表按最后一段取值: @attr 取属性; text 取文本; html 取 html;
    其余字符串(如 content/href, Legado 标准 og 取值写法)当作属性名取属性。"""
    if not res:
        return []
    ls = last_seg.strip()
    if ls.startswith("@"):
        attr = ls[1:]
        return [el.get(attr, "") for el in res if isinstance(el, Tag)]
    if ls == "text":
        return [el.get_text(strip=True) for el in res if isinstance(el, Tag)]
    if ls == "html":
        return [el.decode_contents() for el in res if isinstance(el, Tag)]
    # 其余当作属性名(attr); 元素无此属性时回退取文本, 避免误空
    out = []
    for el in res:
        if not isinstance(el, Tag):
            continue
        v = el.get(ls, None)
        out.append(v if v is not None else el.get_text(strip=True))
    return out


def _dedup_texts(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def eval_rule_nodes_jsoup(root, expr):
    """JSOUP 容器层: 返回 (bs4 元素列表, err)。支持 && 备选 / || 并集 / @ 层级 / 前缀 - (列表倒置)。"""
    if not expr or not str(expr).strip():
        return [], EMPTY_RULE
    if _is_regex_rule(expr):
        return [], REGEX_SKIP
    if expr.strip().startswith("<js"):
        return [], JS_SKIP
    if not HAVE_BS4:
        return [], "未安装 bs4, 无法验证 JSOUP 规则"
    rev = expr.lstrip().startswith("-")
    for seg in split_chains(expr):
        collected = []
        for branch in split_union(seg):
            core, _ = _strip_rule_prefix(branch)
            core = strip_url_options(core)
            try:
                nodes = _jsoup_select_elements(root, core)
            except Exception as _e:
                if _LEGADO_EXT_ATTR.search(core):
                    return None, JSOUP_EXT
                return None, "JSOUP选择器非法:%s" % _e
            if nodes:
                collected.extend(nodes)
        if collected:
            return (collected[::-1] if rev else collected), None
    return [], None


def eval_rule_jsoup(root, expr):
    """JSOUP 取值层: 返回 (文本列表, err)。最后段 text/html/@attr 决定取值;
    支持 && 备选 / || 并集 / ## 清洗 / 前缀 -。无取值指示符(纯元素)默认取文本。
    扩展属性选择器(~= 是 Jsoup 正则匹配操作符)走真 Jsoup 通道(_jsoup_real_eval)忠实求值;
    jar/Java 不可用时降级为 JSOUP_EXT(「需真机验证」), 不误报非法、不假通过。"""
    if not expr or not str(expr).strip():
        return [], EMPTY_RULE
    if _is_regex_rule(expr):
        return [], REGEX_SKIP
    e = expr.strip()
    if e.startswith("<js"):
        return [], JS_SKIP
    if not HAVE_BS4:
        return [], "未安装 bs4, 无法验证 JSOUP 规则"
    rev = e.startswith("-")
    err = None
    for seg in split_chains(e):
        collected = []
        for branch in split_union(seg):
            try:
                core, ops = split_regex(branch)
                core2, _rev = _strip_rule_prefix(core)
                # 扩展属性选择器(~= 正则匹配): bs4 无法等价建模, 走真 Jsoup 通道求值
                if _LEGADO_EXT_ATTR.search(core2) and _jsoup_engine_available():
                    jvals, jerr = _jsoup_real_eval(str(root), core2)
                    if jerr is None:
                        if ops:
                            jvals, _rx_err = apply_regex_ops(jvals, ops)
                            if _rx_err:
                                err = _rx_err
                                continue
                        if jvals:
                            collected.extend(jvals)
                        continue
                    err = JSOUP_EXT  # 真机通道不可用 -> 降级(保持「需真机验证」语义)
                    continue
                segs = core2.split("@")
                res = [root]
                branch_texts = []
                for i, s in enumerate(segs):
                    selector, idx = _strip_index(s)
                    is_last = (i == len(segs) - 1)
                    if is_last:
                        # 最后一段恒为取值指示符: @attr 取属性 / text 取文本 / html 取 html /
                        # 其余(如 content/href)当作属性名(Legado og 取值标准写法)
                        branch_texts.extend(_jsoup_extract(res, selector))
                        break
                    nxt = []
                    for el in res:
                        nxt.extend(_jsoup_single(el, selector))
                    res = _apply_index(nxt, idx)
                    if not res:
                        break
                # 每分支的 ## 清洗只作用于本分支结果, 再并入并集(避免后分支覆盖前分支)
                if branch_texts and ops:
                    branch_texts, _rx_err = apply_regex_ops(branch_texts, ops)
                    if _rx_err:
                        err = _rx_err
                        continue
                if branch_texts:
                    collected.extend(branch_texts)
            except Exception as _e:
                if _LEGADO_EXT_ATTR.search(core2):
                    err = JSOUP_EXT
                else:
                    err = "JSOUP选择器非法:%s" % _e
                continue
        if collected:
            return _dedup_texts(collected[::-1] if rev else collected), None
        if err:
            return None, err
    return [], None


def _eval_sub_field_jsoup(nodes, expr, limit=5000, label=None):
    """JSOUP 子字段相对求值: nodes 是 bs4 Tag(容器结果), 对每项按 JSOUP 语义相对求值。
    返回 (命中条数, 列表项总数, 样例列表, 错误)。"""
    if not isinstance(nodes, list):
        nodes = list(nodes)
    total = 0
    hits = []
    err = None
    for nd in nodes[:limit]:
        total += 1
        r, e = eval_rule_jsoup(nd, expr)
        if e:
            err = e
            break
        texts = [t for t in r if t]
        if texts:
            hits.extend(texts)
    return len(hits), total, hits[:3], err


def eval_sub_field(nodes, expr, limit=5000, label=None, mode=None):
    """对列表的每个节点按 Legado 相对语义逐项求值(非只看首节点)。
    返回 (命中条数, 列表项总数, 样例列表, 错误)。
    按规则模式分派: JSOUP/CSS 用 BeautifulSoup 相对求值; XPath 子字段若挂在 JSOUP 容器
    (bs4 节点)上, 则对每个容器元素重建 lxml 子树后按相对 XPath 求值,
    对齐真机 JXNode.sel(//x) 相对列表节点求值的语义。
    """
    if mode is None:
        mode = detect_mode(expr)
    if mode in ("jsoup", "css"):
        # 对称处理: 若容器来自 XPath(lxml 元素, 非 bs4 Tag), 逐节点转 bs4 后再做 JSOUP 相对求值,
        # 对齐反向(JSOUP 容器挂 XPath 子字段已在下方 lxml 重建子树)。
        if HAVE_BS4 and nodes and not isinstance(nodes[0], Tag):
            bs_nodes = []
            for nd in nodes[:limit]:
                try:
                    # 关键: lxml 元素的 str() 是调试 repr(<Element li at 0x...>), 非 HTML 标记;
                    # 必须用 lxml_html.tostring 序列化才能得到可解析的标记(否则 select 找不到子节点)。
                    bs_nodes.append(BeautifulSoup(lxml_html.tostring(nd, encoding="unicode"), "html.parser"))
                except Exception:
                    continue
            if bs_nodes:
                return _eval_sub_field_jsoup(bs_nodes, expr, limit=limit, label=label)
        return _eval_sub_field_jsoup(nodes, expr, limit=limit, label=label)
    if _has_inline_js(expr):
        base, _ = split_inline_js(expr)
        expr = base
        if label:
            JS_NOTE_FIELDS.append("%s(内联<js>管道,需真机)" % label)
    total = 0
    hits = []
    err = None
    # 混合场景: JSOUP 容器返回 bs4 Tag, 但子字段是 XPath → 逐节点重建 lxml 子树相对求值
    if HAVE_BS4 and nodes and isinstance(nodes[0], Tag):
        for nd in nodes[:limit]:
            total += 1
            try:
                sub_tree = lxml_html.fromstring(str(nd))
            except Exception:
                continue
            r, e = eval_rule(sub_tree, expr, relative=True)
            if e:
                err = e
                break
            texts = [to_text(x) for x in (r or []) if to_text(x) != ""]
            if texts:
                hits.extend(texts)
        return len(hits), total, hits[:3], err
    for nd in nodes[:limit]:
        total += 1
        r, e = eval_rule(nd, expr, relative=True)
        if e:
            err = e
            break
        texts = [to_text(x) for x in (r or []) if to_text(x) != ""]
        if texts:
            hits.extend(texts)
    return len(hits), total, hits[:3], err


def report_list_hit(label, hits, total, samples, err):
    """列表子字段的命中报告: 命中 N/总数。返回 True=不计入失败。"""
    if err:
        if err == JS_SKIP:
            print("    %-14s : [需真机验证] JS 规则, 本地不执行(必须 App 实机确认, 不代表失败)" % label)
            JS_NOTE_FIELDS.append(label)
            return True
        if err == REGEX_SKIP:
            print("    %-14s : [需真机验证] ':' 正则规则(书籍/目录列表专用), 本地不建模, 需 App 实机确认(不代表失败)" % label)
            JS_NOTE_FIELDS.append("%s(:正则规则,需真机)" % label)
            return True
        if err == JSOUP_EXT:
            print("    %-14s : [需真机验证] Legado 扩展属性选择器(~=)本地 bs4 无法建模, 需 App 实机确认(不代表失败)" % label)
            JS_NOTE_FIELDS.append("%s(扩展属性选择器,需真机)" % label)
            return True
        if err == EMPTY_RULE:
            # 空规则=真机视为未配置, 中性跳过(不计失败); 以前当 ERR 报, 空白串字段假失败
            print("    %-14s : [SKIP] 规则为空(视为未配置), 跳过(不计失败)" % label)
            return True
        print("    %-14s : [ERR] %s" % (label, err))
        return False
    if total and hits == 0:
        if label in OPTIONAL:
            print("    %-14s : [OPT·MISS] %d 个列表项均未命中(忽略)" % (label, total))
            return True
        print("    %-14s : [MISS] %d 个列表项均未命中" % (label, total))
        return False
    print("    %-14s : [OK] 命中 %d/%d 条" % (label, hits, total))
    for t in samples:
        show = t if len(t) <= 60 else (t[:60] + "...")
        print("        例: %s" % show)
    return True


def eval_jsonpath(data, expr):
    if not HAVE_JSONPATH:
        return None, "未安装 jsonpath_ng, 请: sudo pip3 install jsonpath-ng"
    try:
        matches = [m.value for m in jsonpath_mod.parse(expr).find(data)]
        return matches, None
    except Exception as e:
        return None, "JSONPath错误:%s" % e


# 「命中了但值不对」的特征：验证器不能只数命中数，否则假阳性会一路绿灯
_LABEL_ONLY_RE = re.compile(r"^\s*(作者|分类|状态|字数|更新|最近章节|简介|书名|标签)[:：]?\s*$")
_LABEL_PREFIX_RE = re.compile(r"^\s*(作者|分类|状态|字数|更新|最近章节|简介|书名|标签)\s*[:：]")
_LABEL_WORDS = r"作者|分类|状态|字数|更新|最近章节|简介|书名|标签"
_SUSPICIOUS_WARNINGS = []


def sanity_warn(label, value):
    """对命中值做合理性检查，可疑则返回问题说明（命中≠正确）。"""
    v = (value or "").strip()
    if not v:
        return "空值"
    if _LABEL_ONLY_RE.match(v):
        return "只取到标签文字「%s」，## 正则清洗多半写反了（Legado: ##正则=删除匹配，##正则##替换=替换）" % v
    if label in ("name", "author", "kind", "lastChapter", "intro") and _LABEL_PREFIX_RE.match(v):
        return "值带标签前缀（如「作者：」），建议规则末尾加 ##%s\\s*[:：]\\s* 清洗掉" % _LABEL_WORDS
    if v.startswith("#"):
        return "值以 # 开头，多半是 `##正则###$1` 写错了 —— 源码按 split('##') 切，正确写法是 `##正则##$1`"
    if label in ("name", "author", "kind", "lastChapter", "chapterName") and (
        v.startswith("http://") or v.startswith("https://")
    ):
        return "取成了 URL，选择器可能选错节点"
    if label == "bookUrl" or label == "chapterUrl" or label == "tocUrl":
        if not (v.startswith("/") or v.startswith("http")):
            return "不像链接（应为 / 或 http 开头），检查 @href 提取是否正确"
    if label == "lastChapter" and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return "取成了日期而非章节名，## 清洗可能没生效"
    return ""


def warn_xpath_mode(src):
    """规则模式判定检查——**前导点是 Legado 最隐蔽的静默杀手**。

    源码依据 (Legado 3.25, io.legado.app.model.analyzeRule.AnalyzeRule$SourceRule):
        if      startsWith(ruleStr, "@CSS:")  -> Mode.Default
        else if startsWith(ruleStr, "@@")     -> Mode.Default
        else if startsWith(ruleStr, "@XPath:")-> Mode.XPath
        else if startsWith(ruleStr, "@Json:") -> Mode.Json
        else if isJSON || startsWith("$.") || startsWith("$[") -> Mode.Json
        else if startsWith(ruleStr, "/")      -> Mode.XPath      <=== 唯一入口
        // 什么都不匹配 -> Mode.Default(Jsoup CSS)

    即: **只有以 `/` 开头才会被当 XPath**。写 `.//xxx` / `./xxx` 会以 CSS 选择器解析,
    不报错、不崩溃, 静默命中 0 条, 表现为"列表大小 49 但每条都被丢弃"。

    正确的列表内相对写法就是 `//xxx`(不带点): JsoupXpath 的 JXNode.sel() 本身是
    相对当前节点的, 实测同一规则在 49 个节点上各返回自己的值(见 SKILL.md)。
    """
    # (区域, 容器字段, 子字段列表)
    LIST_REGIONS = {
        "ruleSearch": ("bookList", ["name", "author", "kind", "coverUrl", "intro",
                                    "lastChapter", "bookUrl", "wordCount", "updateTime"]),
        "ruleExplore": ("bookList", ["name", "author", "kind", "coverUrl", "intro",
                                     "lastChapter", "bookUrl", "wordCount", "updateTime"]),
        "ruleToc": ("chapterList", ["chapterName", "chapterUrl", "isVip", "updateTime"]),
    }
    problems = []
    for region, (container, fields) in LIST_REGIONS.items():
        r = norm_region(src.get(region))
        if not isinstance(r, dict) or not r.get(container):
            continue
        for f in fields:
            v = r.get(f)
            if not isinstance(v, str) or not v.strip():
                continue
            head = split_inline_js(v.split("##")[0].strip())[0]
            if head.startswith("<js") or head.startswith("@Json:") or head.startswith("@CSS:"):
                continue
            if head.startswith("@XPath:"):
                head = head[7:].strip()
            fixed = head[1:] if head.startswith(".//") else "/" + head[1:]
            if head.startswith(".//") or head.startswith("./"):
                print("    [%s.%s] ❌ 前导点 '%s' 会让 Legado 判为 CSS 模式而非 XPath → "
                      "静默命中 0 条(列表有数但全部被丢弃)。改写为 '%s'"
                      % (region, f, head, fixed))
                problems.append((region, f))
            elif head.startswith("/html") or (head.startswith("/") and not head.startswith("//")):
                print("    [%s.%s] ⚠ 绝对路径 '%s' 在列表节点下通常命中 0 条, 建议改相对写法 '%s'"
                      % (region, f, head, head.split("/")[-2] if head.count("/") > 1 else head))
                problems.append((region, f))
    # 非列表区域同样受模式判定约束
    for region in ("ruleBookInfo", "ruleContent"):
        r = norm_region(src.get(region))
        if not isinstance(r, dict):
            continue
        for f, v in r.items():
            if not isinstance(v, str) or not v.strip():
                continue
            head = split_inline_js(v.split("##")[0].strip())[0]
            if head.startswith("<js") or head.startswith("@Json:") or head.startswith("@CSS:"):
                continue
            if head.startswith("@XPath:"):
                head = head[7:].strip()
            fixed = head[1:] if head.startswith(".//") else "/" + head[1:]
            if head.startswith(".//") or head.startswith("./"):
                print("    [%s.%s] ❌ 前导点 '%s' 会让 Legado 判为 CSS 模式 → 静默取空, "
                      "改写为 '%s'" % (region, f, head, fixed))
                problems.append((region, f))
    return problems


def report_hit(label, res, err):
    """返回 True=不计入失败(OK 或可选缺失); False=计入失败。"""
    if err:
        if err == JS_SKIP:
            print("    %-14s : [需真机验证] JS 规则, 本地不执行(必须 App 实机确认, 不代表失败)" % label)
            JS_NOTE_FIELDS.append(label)
            return True
        if err == REGEX_SKIP:
            print("    %-14s : [需真机验证] ':' 正则规则(书籍/目录列表专用), 本地不建模, 需 App 实机确认(不代表失败)" % label)
            JS_NOTE_FIELDS.append("%s(:正则规则,需真机)" % label)
            return True
        if err == JSOUP_EXT:
            print("    %-14s : [需真机验证] Legado 扩展属性选择器(~=)本地 bs4 无法建模, 需 App 实机确认(不代表失败)" % label)
            JS_NOTE_FIELDS.append("%s(扩展属性选择器,需真机)" % label)
            return True
        if err == EMPTY_RULE:
            # 空规则=真机视为未配置, 中性跳过(不计失败)
            print("    %-14s : [SKIP] 规则为空(视为未配置), 跳过(不计失败)" % label)
            return True
        print("    %-14s : [ERR] %s" % (label, err))
        return False
    if res is None:
        if label in OPTIONAL:
            print("    %-14s : [OPT·MISS] 可选字段无结果(忽略)" % label)
            return True
        print("    %-14s : [MISS] 无结果" % label)
        return False
    texts = [to_text(x) for x in res if to_text(x) != ""]
    if not texts:
        if label in OPTIONAL:
            print("    %-14s : [OPT·MISS] 命中但文本为空(忽略)" % label)
            return True
        print("    %-14s : [MISS] 命中 %d 个但文本为空" % (label, len(res)))
        return False
    print("    %-14s : [OK] 命中 %d 条" % (label, len(texts)))
    for t in texts[:3]:
        show = t if len(t) <= 60 else (t[:60] + "...")
        print("        例: %s" % show)
    # 合理性检查：命中了，但值是不是真能用？
    for t in texts[:1]:
        problem = sanity_warn(label, t)
        if problem:
            print("        [⚠ 可疑] %s" % problem)
            _SUSPICIOUS_WARNINGS.append("%s: %s" % (label, problem))
    return True


def _eval_field(k, expr, tree, json_data, soup=None, mode=None):
    if not isinstance(expr, str):
        # JSON 里 rule* 误配成数字/对象/数组: 真机 AnalyzeUrl 链同样不成立, 按中性
        # 跳过(不计失败), 绝不让类型错误升级成 AttributeError 崩栈。
        print("    %-14s : [配置错误] 规则值不是字符串(%s), App 端同样无法解析, 中性跳过(不计失败)"
              % (k, type(expr).__name__))
        return True
    if _is_template(expr):
        print("    %-14s : [模板] {{...}} 占位字面量, 非解析规则, 跳过" % k)
        return True
    if mode is None:
        mode = detect_mode(expr)
    if mode == "json":
        if json_data is not None:
            r, e = eval_jsonpath(json_data, expr)
            return report_hit(k, r, e)
        print("    %-14s : [JSONPath] 需 --json 样本验证" % k)
        return True
    if _has_inline_js(expr):
        if mode in ("jsoup", "css") and soup is not None:
            base, _ = split_inline_js(expr)
            r, e = eval_rule_jsoup(soup, base)
            JS_NOTE_FIELDS.append("%s(内联<js>管道,需真机)" % k)
            return report_hit(k, r, e)
        base, _ = split_inline_js(expr)
        r, e = eval_rule(tree, base)
        JS_NOTE_FIELDS.append("%s(内联<js>管道,需真机)" % k)
        return report_hit(k, r, e)
    if mode in ("jsoup", "css"):
        if soup is None:
            print("    %-14s : [JSOUP] 需 HTML 样本验证" % k); return True
        r, e = eval_rule_jsoup(soup, expr)
        return report_hit(k, r, e)
    r, e = eval_rule(tree, expr)
    return report_hit(k, r, e)


def check_region(name, region, html_text, json_data):
    print("\n[%s]" % name)
    if not isinstance(region, dict):
        print("  区域不是对象, 跳过")
        return False
    parser_fields = PARSER_BY_REGION.get(name)
    if not parser_fields:
        parser_fields = [k for k in region if k not in CONFIG_KEYS]

    ok = True
    if html_text and html_text.strip():
        try:
            tree = lxml_html.fromstring(html_text)
        except Exception as e:
            # 空白/非法文档(空文件、只有换行空白)会让 lxml 抛 ParserError: Document is empty,
            # 不接住就是整个脚本栈崩溃 —— 样例问题不是规则问题, 按中性跳过
            print("  HTML 样本无法解析(空白或非法文档): %s → 跳过(中性, 不计入失败)" % e)
            return True
        soup = BeautifulSoup(html_text, "html.parser") if HAVE_BS4 else None
        cont_key, sub_fields = CONTAINER.get(name, (None, []))
        if cont_key and region.get(cont_key):
            cmode = detect_mode(region[cont_key])
            if cmode == "js":
                # 纯 <js> 容器: 真机上由 Rhino 返回节点列表, 本地无 Rhino 无法执行。
                # 子字段挂在该容器返回的节点上, 无节点同样无法本地验证 → 一并标注需真机,
                # 全部中性(不计失败)。旧版把它丢给 lxml xpath 求值 → 假 ERR。
                print("    %-14s : [需真机验证] 容器为 JS 规则(<js>), 本地不执行(必须 App 实机确认, 不代表失败)" % cont_key)
                JS_NOTE_FIELDS.append("%s(纯JS容器,需真机)" % cont_key)
                for sf in sub_fields:
                    if sf in parser_fields and region.get(sf):
                        JS_NOTE_FIELDS.append("%s(容器为JS,依赖容器返回节点,需真机)" % sf)
            elif cmode == "regex":
                # ':' 正则容器: 书籍/目录列表专用的列表过滤模式, 本地不建模。
                # 子字段挂在该容器返回的节点上, 无节点同样无法本地验证 → 一并中性。
                print("    %-14s : [需真机验证] 容器为 ':' 正则规则(列表专用), 本地不建模, 需 App 实机确认(不代表失败)" % cont_key)
                JS_NOTE_FIELDS.append("%s(:正则容器,需真机)" % cont_key)
                for sf in sub_fields:
                    if sf in parser_fields and region.get(sf):
                        JS_NOTE_FIELDS.append("%s(容器为正则,依赖容器返回节点,需真机)" % sf)
            else:
                if cmode in ("jsoup", "css"):
                    nodes, err = eval_rule_nodes_jsoup(soup, region[cont_key])
                else:
                    nodes, err = eval_rule_nodes(tree, region[cont_key])
                if err:
                    if err == JSOUP_EXT:
                        print("    %-14s : [需真机验证] Legado 扩展属性选择器(~=)本地 bs4 无法建模, 需 App 实机确认" % cont_key)
                        JS_NOTE_FIELDS.append("%s(扩展属性选择器,需真机)" % cont_key)
                    elif err == JS_SKIP:
                        print("    %-14s : [需真机验证] JS 规则, 本地不执行(必须 App 实机确认, 不代表失败)" % cont_key)
                        JS_NOTE_FIELDS.append("%s(需真机)" % cont_key)
                    elif err == EMPTY_RULE:
                        print("    %-14s : [SKIP] 容器规则为空(视为未配置), 跳过(不计失败)" % cont_key)
                    else:
                        print("    %-14s : [ERR] %s" % (cont_key, err)); ok = False
                elif not nodes:
                    if name == "searchUrl" and HAS_LOGINCHECKJS:
                        # 搜索依赖 loginCheckJs 过墙, 本地样例通常未过墙(结果由 Ajax 填入),
                        # 容器为空是样例局限而非规则错 → 降级为「需真机验证」, 不计入失败
                        print("    %-14s : [需真机验证] 容器 0 个; 本源配了 loginCheckJs 过墙, "
                              "本地样例多未过墙(结果 Ajax 填入), 以真机搜索为准" % cont_key)
                    else:
                        print("    %-14s : [MISS] 容器命中 0 个" % cont_key); ok = False
                else:
                    print("    %-14s : [OK] 容器命中 %d 个" % (cont_key, len(nodes)))
                    if nodes:
                        for sf in sub_fields:
                            if sf in parser_fields and region.get(sf):
                                if _is_template(region[sf]):
                                    print("    %-14s : [模板] {{...}} 占位字面量, 非解析规则, 跳过" % sf)
                                    continue
                                hits, total, samples, e = eval_sub_field(
                                    nodes, region[sf], label=sf, mode=detect_mode(region[sf]))
                                ok = report_list_hit(sf, hits, total, samples, e) and ok
            for k in parser_fields:
                if k == cont_key or k in sub_fields or region.get(k) is None:
                    continue
                ok = _eval_field(k, region[k], tree, json_data, soup=soup,
                                mode=detect_mode(region[k])) and ok
        else:
            for k in parser_fields:
                if region.get(k) is None:
                    continue
                ok = _eval_field(k, region[k], tree, json_data, soup=soup,
                                mode=detect_mode(region[k])) and ok
    elif json_data is not None:
        for k in parser_fields:
            if region.get(k) is None:
                continue
            if is_jsonpath(region[k]):
                r, e = eval_jsonpath(json_data, region[k])
                ok = report_hit(k, r, e) and ok
            else:
                # 无 HTML 样本时, 非 JSONPath 字段本地无法验证; 按「无样本=中性」契约跳过,
                # 不计为解析失败(否则动态站只传 --json 时 XPath 字段会被误判失败, 假阴性)。
                print("    %-14s : [需HTML] 无 HTML 样本, 跳过(中性, 不计入失败)" % k)
    else:
        print("  未提供该区域的样本(HTML/JSON), 跳过(中性, 不计入失败)")
        return True  # 无样本=无法验证(中性), 不等于解析失败; 失败仅指样本在但 MISS/ERR
    return ok


def get_search_region(src):
    """搜索解析区域: 新 schema 在顶层 ruleSearch 对象; 旧写法内嵌 searchUrl 对象。"""
    rs = norm_region(src.get("ruleSearch"))
    if isinstance(rs, dict) and rs:
        return rs
    r = norm_region(src.get("searchUrl"))
    if isinstance(r, dict) and any(k in r for k in ("bookList", "name", "author", "bookUrl")):
        return r  # 旧写法: 规则内嵌 searchUrl
    return None


def get_explore_regions(src):
    """返回发现规则区域列表。

    Legado 三种合法结构:
      (a) exploreUrl 为数组, 每条含自己的 ruleExplore;
      (b) exploreUrl 为数组/字符串, 各入口共用顶层 ruleExplore;
      (c) 旧写法 exploreUrl 为对象直接含规则。
    """
    ev_raw = src.get("exploreUrl")
    ev = norm_region(ev_raw)
    top_re = norm_region(src.get("ruleExplore"))  # 顶层 ruleExplore(所有入口共用)
    if ev is None:
        # exploreUrl 为纯 URL 字符串(非JSON), 规则共用顶层 ruleExplore
        if isinstance(ev_raw, str) and ev_raw.strip() and isinstance(top_re, dict):
            return [top_re]
        return []
    regions = []
    if isinstance(ev, list):
        for entry in ev:
            if isinstance(entry, dict):
                re_ = norm_region(entry.get("ruleExplore"))
                if not isinstance(re_, dict):
                    re_ = top_re  # 回退到顶层 ruleExplore(结构 b)
                if isinstance(re_, dict):
                    regions.append(re_)
    elif isinstance(ev, dict):
        re_ = norm_region(ev.get("ruleExplore")) or top_re
        if isinstance(re_, dict):
            regions.append(re_)
        elif any(k in ev for k in ("bookList", "name", "bookUrl")):
            regions.append(ev)  # 旧写法: 对象直接含规则
    return regions


def check_field_availability(src):
    """基于 3.25 反编译+真机验证的字段生死表, 给书源做字段层提示。

    实测结论(已用 legado_app_3.25.apk 反编译 + 用户真机双证实):
      - loginCheckJs 在本 App 生效: 每次请求后执行, 结果 JSON 取 Cookie/cookie →
        CookieStore.replaceCookie 落库, getLoginHeader 自动带上下次请求。可用于过验证墙。
      - ruleContent.replaceRegex 在本 App 是死字段: 全代码库仅 ContentRule.toString 引用,
        无解析/执行逻辑; 正文净化必须写进 content 的 <js>。
    """
    print("\n[字段可用性核查 · 基准=legado 3.25 反编译+真机]")
    rc = src.get("ruleContent")
    rc = norm_region(rc) if isinstance(rc, (dict, str)) else None
    if isinstance(rc, dict) and rc.get("replaceRegex"):
        msg = ("⚠ ruleContent.replaceRegex 在本 App 是死字段(反编译+真机证实), "
               "写了不执行 → 正文净化请改用 content 的 <js>")
        print("  " + msg)
        FIELD_NOTES.append(msg)
    else:
        print("  ✓ 未见 ruleContent.replaceRegex(死字段), 正文净化约定走 content 的 <js> ✓")
    global HAS_LOGINCHECKJS
    if src.get("loginCheckJs"):
        HAS_LOGINCHECKJS = True
        msg = ("✓ loginCheckJs 在本 App 生效(每次请求后执行, JSON 取 Cookie 落库, "
               "下次请求自动带上) → 过验证墙可用, 别弃用它")
        print("  " + msg)
        FIELD_NOTES.append(msg)
    else:
        print("  · 未配置 loginCheckJs(如需过验证墙, 本 App 可用它)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("booksource")
    ap.add_argument("--search", help="搜索结果页 HTML")
    ap.add_argument("--explore", help="发现列表页 HTML(验证 ruleExplore)")
    ap.add_argument("--bookinfo", help="书籍详情页 HTML")
    ap.add_argument("--toc", help="目录页 HTML")
    ap.add_argument("--content", help="正文页 HTML")
    ap.add_argument("--json", help="JSON 样本(供 JSONPath 规则验证)")
    args = ap.parse_args()

    try:
        with open(args.booksource, encoding="utf-8-sig") as _f:
            src = json.load(_f)
        if isinstance(src, list):
            # App 导入格式是数组; 取第一个书源验证(多书源文件请拆开或逐个传)
            if not src:
                print("书源文件是空数组"); sys.exit(2)
            if len(src) > 1:
                print("提示: 文件含 %d 个书源, 验证第 1 个(其余请逐个传入)" % len(src))
            src = src[0]
    except Exception as e:
        print("无法读取书源: %s" % e); sys.exit(2)

    json_data = None
    if args.json:
        try:
            with open(args.json, encoding="utf-8-sig") as _f:
                json_data = json.load(_f)
        except Exception as e:
            print("无法读取 JSON 样本: %s" % e); sys.exit(2)

    warn_xpath_mode(src)
    check_field_availability(src)

    # 确定书源编码(用于读取 GBK 老站样本)
    charset = src.get("charset")
    if not charset:
        su = norm_region(src.get("searchUrl"))
        if isinstance(su, dict):
            charset = su.get("charset")

    def read_html(p):
        if not p:
            return None
        try:
            with open(p, "rb") as _f:
                raw = _f.read()
        except Exception as e:
            print("无法读取 %s: %s" % (p, e)); return None
        if charset:
            try:
                return raw.decode(charset, errors="ignore")
            except Exception:
                pass
        # UTF-8 优先：现代站点多为 UTF-8；GBK 文件按 UTF-8 **严格**解码会抛错，自然回退到 gb18030。
        # 注意这里不能带 errors="ignore"——任何字节流都能被"无错解码", 回退分支永远走不到,
        # GBK 页会被静默解成乱码。曾用 errors="ignore" 导致"回退 gb18030"的代码是死代码。
        # 若反过来先试 gb18030，UTF-8 字节会被 gb18030「无错解码」成乱码，永远不会走到 utf-8——
        # 这是之前样例页中文乱码(鏂楃牬鑻)的根因。
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore")

    samples = {
        "searchUrl": read_html(args.search),
        "exploreUrl": read_html(args.explore),
        "ruleBookInfo": read_html(args.bookinfo),
        "ruleToc": read_html(args.toc),
        "ruleContent": read_html(args.content),
    }

    print("=" * 50)
    print("解析命中验证: %s" % src.get("bookSourceName", args.booksource))
    if charset:
        print("书源编码: %s (GBK 老站已兼容)" % charset)
    print("=" * 50)

    all_ok = True
    for name in ("searchUrl", "ruleBookInfo", "ruleToc", "ruleContent"):
        if name == "searchUrl":
            region = get_search_region(src)
        else:
            region = norm_region(src.get(name))
        if region is None:
            print("\n[%s] 未配置, 跳过" % name)
            continue
        r_ok = check_region(name, region, samples.get(name), json_data)
        if not r_ok:
            all_ok = False

    # 发现频道: 可能多条 ruleExplore, 去重后逐条验证
    explore_regions = get_explore_regions(src)
    if explore_regions:
        html = samples.get("exploreUrl")
        # 去重(共用顶层 ruleExplore 时多条入口规则相同)
        seen, uniq = set(), []
        for reg in explore_regions:
            key = json.dumps(reg, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key); uniq.append(reg)
        if html is None:
            print("\n[exploreUrl] 配置了 %d 条发现入口(去重后 %d 种规则), 但未提供 --explore 样本, 跳过(中性, 不计入失败)"
                  % (len(explore_regions), len(uniq)))
        elif len(uniq) == 1:
            print("\n[exploreUrl] 配置了 %d 条入口, 共用相同规则, 验证 1 条:" % len(explore_regions))
            r_ok = check_region("ruleExplore", uniq[0], html, json_data)
            if not r_ok:
                all_ok = False
        else:
            for i, reg in enumerate(uniq):
                print("\n[exploreUrl #%d]" % i)
                r_ok = check_region("ruleExplore", reg, html, json_data)
                if not r_ok:
                    all_ok = False
    else:
        print("\n[exploreUrl] 未配置, 跳过")

    print("\n" + "=" * 50)
    if _SUSPICIOUS_WARNINGS:
        print("⚠ 命中但值可疑（命中≠正确，务必人工确认）: %d 项" % len(_SUSPICIOUS_WARNINGS))
        for w in _SUSPICIOUS_WARNINGS:
            print("   - %s" % w)
        print("-" * 50)
    # JS 规则与字段提示汇总: 严格区分「本地已验证」与「需真机验证」
    if JS_NOTE_FIELDS:
        print("⚠ 需 App 真机验证的 JS 规则(%d 项, 本地 Rhino 不执行, 不代表失败):"
              % len(JS_NOTE_FIELDS))
        for f in sorted(set(JS_NOTE_FIELDS)):
            print("   - %s" % f)
        print("-" * 50)
    if FIELD_NOTES:
        print("字段可用性提示:")
        for n in FIELD_NOTES:
            print("   - %s" % n)
        print("-" * 50)
    if all_ok and not JS_NOTE_FIELDS:
        verdict = "核心字段全部命中 OK" + ("（但有 %d 项值可疑，见上）" % len(_SUSPICIOUS_WARNINGS) if _SUSPICIOUS_WARNINGS else "")
    elif all_ok and JS_NOTE_FIELDS:
        verdict = ("核心字段本地命中 OK; 另有 %d 项 JS 规则需 App 真机验证(本地无法执行)"
                   % len(set(JS_NOTE_FIELDS)))
    else:
        verdict = "存在核心字段 MISS/ERR (请在 App 复验或微调规则)"
    print("结果: %s" % verdict)
    print("=" * 50)
    sys.exit(0 if all_ok else 1)


def jsoup_self_test(verbose=False):
    """JSOUP 引擎自我证伪标本(铁律 22/23): 正向证明能命中, 反向证明非法选择器具 ERR 不崩溃/不假绿。
    返回 (all_ok, lines)。通过 subprocess 由 run_evals.py 统一调度。"""
    if not HAVE_BS4:
        return False, ["[FAIL] bs4 未安装, JSOUP 自检无法进行(视为失败)"]
    blocks = "".join('<li><a href="/b%d">书%d</a></li>' % (i, i) for i in range(1, 51))
    chaps = "".join('<li><a href="/c%d">章%d</a></li>' % (i, i) for i in range(1, 21))
    html = ('<html><head><meta property="og:title" content="我的书名">'
            '<meta property="og:image" content="https://x/cover.jpg">'
            '<meta property="category" content="玄幻">'
            '<meta property="status" content="连载"></head><body>'
            '<div id="wrap" class="block"><ul>%s</ul></div>'
            '<div class="info_chapters"><ul>%s</ul></div></body></html>' % (blocks, chaps))
    root = BeautifulSoup(html, "html.parser")
    lines = []
    ok = True

    def check(rule, mode, expect, desc, exact=False):
        nonlocal ok
        fn = eval_rule_nodes_jsoup if mode == "nodes" else eval_rule_jsoup
        res, err = fn(root, rule)
        got = len(res) if res else 0
        passed = (err is None) and (got == expect if exact else got >= expect)
        ok = ok and passed
        lines.append("[%s] %-36s got=%d expect%s%d %s" % (
            "PASS" if passed else "FAIL", desc, got,
            ("=" if exact else ">="), expect, "" if passed else ("err=%s" % err)))

    # --- 正向: 证明 JSOUP 默认规则能正确命中(含此前被误判的点) ---
    check(".block@ul@li", "nodes", 50, "JSOUP 搜索容器 .block@ul@li")
    check("-.info_chapters@ul@li@a", "nodes", 20, "JSOUP 目录容器 -.info_chapters@ul@li@a")
    check(".block@ul@li[0]", "nodes", 1, "数字索引[0]")
    check(".block@ul@li[49]", "nodes", 1, "数字索引[49](末位)")
    check(".block@ul@li[99]", "nodes", 0, "越界索引[99]返回空(不崩溃)", exact=True)
    check("[property=og:title]@content", "vals", 1, "og 属性选择器取值(原误判点)")
    check("[property=og:image]@content", "vals", 1, "og:image 取值")
    check(".block@ul@li@a@href", "vals", 50, "容器+子字段 a@href")
    # 子字段相对求值(逐节点, 非只看首节点)
    nodes, _ = eval_rule_nodes_jsoup(root, ".block@ul@li")
    h, t, _, e = _eval_sub_field_jsoup(nodes, "a@href")
    sub_ok = (e is None) and h == 50 and t == 50
    ok = ok and sub_ok
    lines.append("[%s] %-36s 50/50" % ("PASS" if sub_ok else "FAIL", "子字段相对 a@href"))
    # --- 扩展引擎特性(此前自检未覆盖, 防止改坏不报警) ---
    check(".block@ul@li@a@href && .block@ul@nonexist@a@href", "vals", 50, "&& 备选链: 首段命中优先")
    check(".block@ul@li@a@href || .info_chapters@ul@li@a@href", "vals", 70, "|| 并集")
    check(".block@ul@li@a@text", "vals", 50, "text 指示符取值")
    check(".block@ul@li@a@html", "vals", 50, "html 指示符取值")
    check("class.block@ul@li", "nodes", 50, "class. 前缀")
    check("tag.a@href", "vals", 70, "tag. 前缀")
    check("id.wrap", "nodes", 1, "id. 前缀")
    check("text.书@href", "vals", 50, "text. 前缀")
    # ## 正则清洗
    v_re, e_re = eval_rule_jsoup(root, ".block@ul@li@a@href##/b(\\d+)##B$1")
    re_ok = (e_re is None) and len(v_re) == 50 and v_re[0] == "B1"
    ok = ok and re_ok
    lines.append("[%s] %-36s %s" % ("PASS" if re_ok else "FAIL", "## 正则清洗(B1..)",
                                     (v_re[:2] if v_re else [str(e_re)])))
    # ##$## 整串替换(非正则结尾锚点)
    v_d, e_d = eval_rule_jsoup(root, ".block@ul@li@a@href##$##DESC")
    dollar_ok = (e_d is None) and bool(v_d) and v_d[0] == "DESC"
    ok = ok and dollar_ok
    lines.append("[%s] %-36s %s" % ("PASS" if dollar_ok else "FAIL", "##$##整串替换",
                                     (v_d[:1] if v_d else [str(e_d)])))
    # Legado 扩展属性选择器 ~= : 真 Jsoup 通道可用时忠实求值(玄幻/连载);
    # 通道不可用(无 jar/Java)时优雅降级为「需真机验证」(JSOUP_EXT), 不误报非法、不假通过。
    v_ext, e_ext = eval_rule_jsoup(root, "[property~=category|status|update_time]@content")
    if _jsoup_engine_available():
        ext_ok = (e_ext is None) and sorted(v_ext) == ["玄幻", "连载"]
        ext_desc = "扩展属性~=真机求值"
    else:
        ext_ok = (e_ext == JSOUP_EXT)
        ext_desc = "扩展属性~=降级需真机"
    ok = ok and ext_ok
    lines.append("[%s] %-36s %s" % ("PASS" if ext_ok else "FAIL", ext_desc,
                                    (sorted(v_ext) if e_ext is None else e_ext)))
    # || 并集 + 每分支独立 ## 清洗: 后分支的 ##$## 不得覆盖前分支结果(修复: collected 跨分支累积导致 ops 重应用)
    _cu = Counter(eval_rule_jsoup(root, '.block@ul@li@a@href##$##X || .info_chapters@ul@li@a@href##$##Y')[0])
    union_ok = (len(_cu) == 2 and _cu.get('X') == 1 and _cu.get('Y') == 1)
    ok = ok and union_ok
    lines.append("[%s] %-36s X=%s Y=%s" % ("PASS" if union_ok else "FAIL",
                                           "||并集+每分支##$##不互覆盖", _cu.get('X'), _cu.get('Y')))
    # 混合引擎对称: JSOUP 子字段挂 XPath 容器(lxml 节点)应转 bs4 后命中(修复前返回 JSOUP选择器非法)
    try:
        _tree = lxml_html.fromstring(html)
        _xn, _xe = eval_rule_nodes(_tree, "//div[@class='block']//li")
        _h, _t, _s, _err = eval_sub_field(_xn, "a@href", label="js_on_xp", mode="jsoup")
        js_on_xp_ok = (_err is None) and _h == 50 and _t == 50
    except Exception as _ex:
        _h = _t = 0; _err = str(_ex); js_on_xp_ok = False
    ok = ok and js_on_xp_ok
    lines.append("[%s] %-36s hits=%d/%d err=%s" % ("PASS" if js_on_xp_ok else "FAIL",
                                                   "JSOUP子字段挂XPath容器(对称)", _h, _t, _err))
    # - 倒置真正生效: 前两位应为 章20,章19
    nodes2, _ = eval_rule_nodes_jsoup(root, "-.info_chapters@ul@li@a")
    txts = [nd.get_text(strip=True) for nd in (nodes2 or [])[:2]]
    rev_ok = txts == ["章20", "章19"]
    ok = ok and rev_ok
    lines.append("[%s] %-36s 前两位=%s" % ("PASS" if rev_ok else "FAIL", "- 倒置顺序生效", txts))
    # --- 反向: 非法选择器优雅 ERR, 不崩溃也不假绿 ---
    bad, bad_err = eval_rule_nodes_jsoup(root, "###@@@notxpath")
    bad_ok = (bad is None or bad == []) and bad_err is not None and "JSOUP选择器非法" in bad_err
    ok = ok and bad_ok
    lines.append("[%s] %-36s err=%s" % ("PASS" if bad_ok else "FAIL",
                                        "反向:非法选择器优雅ERR", (bad_err or "")[:36]))
    # --- 行内选项剥离: 对齐真机 AnalyzeUrl paramPattern(`\s*,\s*(?=\{)` 首个逗号即切),
    #     且兼容 webJs/bodyJs 里的嵌套花括号(旧 [^}]* 正剥不净 → 残留污染规则) ---
    _uo = [
        ('//a/@href,{"webView":true,"webJs":"var d={};java.log(d)"}', "//a/@href", "嵌套花括号选项剥净"),
        ('//a/@href,{"charset":"utf-8"}', "//a/@href", "普通选项剥净"),
        ('//a/@href, {"charset":"utf-8"}', "//a/@href", "逗号后带空格剥净"),
        ('//div[contains(text(),"a,b{}")]//a', '//div[contains(text(),"a,b{}")]//a', "URL串内逗号花括号不误剥"),
    ]
    for _src, _want, _desc in _uo:
        _got = strip_url_options(_src)
        _uok = _got == _want
        ok = ok and _uok
        lines.append("[%s] %-36s got=%r" % ("PASS" if _uok else "FAIL", "行内选项:" + _desc, _got))
    # --- 坏 ## 正则必须报错(真机抛 RegexException 致字段解析失败; 旧版静默返回原文=假绿) ---
    _br, _berr = eval_rule_jsoup(root, ".block@ul@li@a@href##(##B$1")
    _brok = _berr is not None and "正则错误" in _berr
    ok = ok and _brok
    lines.append("[%s] %-36s err=%s" % ("PASS" if _brok else "FAIL", "反向:坏##正则报ERR",
                                       (_berr or "")[:36]))
    # --- 空规则/空白规则=真机视为未配置 → EMPTY_RULE 中性(旧版当 ERR 假失败) ---
    _eo = ["", "   ", "\n\t"]
    _emok = all(eval_rule_jsoup(root, _e)[1] == EMPTY_RULE for _e in _eo) and \
        all(eval_rule(None, _e)[1] == EMPTY_RULE for _e in _eo)
    ok = ok and _emok
    lines.append("[%s] %-36s sentinel=%s" % ("PASS" if _emok else "FAIL",
                                             "空规则→中性EMPTY_RULE", EMPTY_RULE))
    # --- 纯 <js> 容器本地无 Rhino → JS_SKIP 中性(旧版丢给 lxml xpath 求值=假 ERR) ---
    _jso, _jse = eval_rule_nodes_jsoup(root, "<js>return [1,2,3]</js>")
    _jsok = _jse == JS_SKIP
    ok = ok and _jsok
    lines.append("[%s] %-36s err=%s" % ("PASS" if _jsok else "FAIL", "<js>容器→JS_SKIP中性", _jse))
    # --- ':' 正则模式(书籍/目录列表专用) → REGEX_SKIP 中性(旧版误当 CSS/XPath 跑出假结果) ---
    _rxo = [":li.bk", ":a", ": "]
    _rxok = all(eval_rule_jsoup(root, _r)[1] == REGEX_SKIP for _r in _rxo) and \
        all(eval_rule(None, _r)[1] == REGEX_SKIP for _r in _rxo) and \
        all(eval_rule_nodes_jsoup(root, _r)[1] == REGEX_SKIP for _r in _rxo)
    # '::' 是 CSS 伪类写法, 不是正则模式, 必须继续按 JSOUP 走(误降级会把能验的规则标需真机)
    _colok = eval_rule_jsoup(root, ":li.bk")[1] == REGEX_SKIP and \
        eval_rule_jsoup(root, "li:not(a)")[1] is None
    ok = ok and _rxok and _colok
    lines.append("[%s] %-36s err=%s" % ("PASS" if _rxok else "FAIL", "':'正则→REGEX_SKIP中性", REGEX_SKIP))
    lines.append("[%s] %-36s '::'不误判" % ("PASS" if _colok else "FAIL", "CSS'::'写法不被当正则"))
    return ok, lines


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        ok, lines = jsoup_self_test(verbose=True)
        for ln in lines:
            print(ln)
        print("结果: %s" % ("JSOUP 引擎自检通过" if ok else "JSOUP 引擎自检失败"))
        sys.exit(0 if ok else 1)
    main()
