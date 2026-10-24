#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
booksource_lint.py —— AI 书源调试工具（独立工具，不依赖任何 Skill）

来源: 以 legado_app_3.25.apk(真机同版本)反编译产物为**唯一证据源**:
      /workspace/forensics/smali/smali_classes3/io/legado/app/model/analyzeRule/*.smali
      (字节码级实证: SourceRule 前缀链 / ## 拆分 / JS_PATTERN / getResultLast 取值)
      + /workspace/forensics/jadx_src(同 APK 的 jadx 反编译, 不完整仅作交叉参考);
      一律不采用网络下载的其他版本源码 —— 用户使用的就是这个版本, 版本不对齐
      则调试行为可能不一致, 版本漂移风险不可接受。
      实证铁律: webWait 唯一 / replaceRegex 死字段 / tocUrl 归属 /
      concurrentRate 全局串行 / nextTocUrl 取尾页丢章 / java.get 单参非 HTTP /
      &&||%% 同根并行选择后合并(非链式!) / :regex 是唯一顺序链式模式。

目的: AI 每做一份书源后, 先跑它自检 → 读报告 → 修复 → 再跑, 直到 0 ERROR,
      争取你导入 App 一次成功, 不再来回返工。

它复刻了 App「书源调试」页的核心动作: 逐条规则判定成败并给样例, 只是搬到离线、确定性地提前做。

检查分两类:
  [静态·必跑] 结构 / 必备字段 / 字段归属铁律 / 正则语法 / JS 语法 / URL / 解析路径括号 /
              webWait 唯一 / replaceRegex 死字段 / concurrentRate+分页 / nextTocUrl 取尾页 /
              enabledCookieJar / java.get 单参 等。纯标准库, 任何环境都能跑。
  [动态·按需] 拿到真实页面样本后, 实跑每条规则, 判定"语法引擎认不认"与"到底取没取到东西"。
              XPath 用真机引擎(org.seimicrawler.xpath == JsoupXpath 2.5.5, 与 APK 同包名,
              对齐表格包裹预处理 + <?xml 切 xmlParser); Jsoup 用真 jar; JSONPath 用 jayway 同构;
              lxml 仅在缺真机引擎时作 XPath 近似兜底。这是静态查不到的盲区。

用法:
  python3 booksource_lint.py <书源.json>                  # 仅静态
  python3 booksource_lint.py <书源.json> --dynamic \\       # 动态(无样本时只做语法编译校验)
      --html sample.html \\                                # 通用页面样本(用于搜索/详情/目录/正文)
      --search-html s.html --bookinfo-html i.html \\        # 或分别给
      --json api.json                                     # 给 JSONPath 规则用的 JSON 样本
  python3 booksource_lint.py -                            # 从 stdin 读
  python3 booksource_lint.py <书源.json> --strict          # WARN 也判失败(exit 1)
  python3 booksource_lint.py --self-test                   # 内置正/反例标本, 全过 exit 0

报告分级:
  [ERROR] 会导致解析失败/取空/静默丢弃的真实问题(必须修)
  [WARN ] 健壮性/性能隐患(强烈建议修)
  [INFO ] 提示

退出码: 0 = 通过(无 ERROR, --strict 下也无 WARN); 1 = 有 ERROR/WARN(strict); 2 = 参数/解析错误
"""

import sys
import os
import re
import json
import argparse
import subprocess
import tempfile
import shutil
import base64
import random
import atexit
from urllib.parse import quote, urljoin

import requests  # 真实抓取层（按书源配置真连真抓）

# jayway JsonPath 兼容引擎（APK 反编译同构，对齐真机 jayway 2.9.x 行为）。
# 纯 Python、无外部依赖，始终可用；jsonpath_ng 仅作最终兜底。
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "booksource_lint_assets")
if _ASSETS_DIR not in sys.path:
    sys.path.insert(0, _ASSETS_DIR)
try:
    from jayway_compat import (
        JsonPath as _JaywayPath,
        legado_get_string_list as _jp_get_string_list,
        legado_get_string as _jp_get_string,
        legado_get_list as _jp_get_list,
        InvalidPath as _JPInvalidPath,
        PathNotFound as _JPPathNotFound,
        _split_rule as _jp_split_rule,
        _chomp_code_balanced as _jp_chomp_balanced,
    )
    _HAVE_JAYWAY = True
except Exception:  # noqa
    _HAVE_JAYWAY = False

# 统一临时目录：live_debug 会为每章/每页生成临时 HTML，退出时统一清理，避免 /tmp 堆积
_TMP_DIR = tempfile.mkdtemp(prefix="ai_booksource_debug_")
atexit.register(lambda: shutil.rmtree(_TMP_DIR, ignore_errors=True))

# ----------------------------------------------------------------------------
# 1. 真实 SCHEMA（来自 APK 解析引擎 + 反编译实证，非臆测）
# ----------------------------------------------------------------------------
REQUIRED_TOP = ["bookSourceName", "bookSourceUrl"]

# 解析区域 → 该区域必备子字段（新 schema: 规则在顶层 ruleXxx 对象内）
# 注: bookList/chapterList 是「分组容器」规则, 真机里可省略(规则直接作用于整页),
#     故只作 WARN, 不列为必填 ERROR。
REGION_REQUIRED = {
    "ruleSearch": ["name", "bookUrl"],
    "ruleExplore": ["name", "bookUrl"],
    "ruleBookInfo": ["name"],
    "ruleToc": ["chapterName", "chapterUrl"],
    "ruleContent": ["content"],
}

# 字段归属铁律: field → 允许出现它的区域集合（出现在别处 = 静默丢弃/无效）
FIELD_OWNERSHIP = {
    "tocUrl": {"ruleBookInfo"},                 # 3.25 反编译: tocUrl 只属 ruleBookInfo
    "nextTocUrl": {"ruleToc"},
    "nextContentUrl": {"ruleContent"},
    "content": {"ruleContent"},
    "chapterUrl": {"ruleToc"},
    "chapterList": {"ruleToc"},
    "bookList": {"ruleSearch", "ruleExplore"},
    "bookUrl": {"ruleSearch", "ruleExplore"},
}

# 死字段: (区域, 字段) 写了不执行（3.25 反编译零消费点）
DEAD_FIELDS = [
    ("ruleContent", "replaceRegex"),            # 铁律 5/10: 正文净化写不进去
]

# 等待字段: 正确名 vs 会被 Gson 静默丢弃的错名（铁律 7/183）
WAIT_FIELD_RIGHT = "webWait"
WAIT_FIELD_WRONG = ["webViewDelayTime", "webviewDelayTime", "webDelay", "webviewdelaytime"]

# 合法行内选项白名单（URL 行内选项; 错名会被 Gson 静默忽略）
KNOWN_INLINE_OPTS = {
    "webView", "webWait", "webJs", "js", "serverID", "charset", "headers",
    "enabledCookieJar", "userAgent", "method", "body", "retry", "httpHeaders",
}

# 解析规则里"取属性/文本"的末尾关键字（来自 AnalyzeByJSoup.getResultLast）
JSOUP_TAIL_KEYWORDS = {"text", "textNodes", "ownText", "html", "all"}

# 翻页模拟护栏：真机对 nextTocUrl/nextContentUrl 无步数上限（仅 next 返回空才停），
# 工具设上限仅为防本地 hang（真机死循环会卡死/oom，护栏对齐该风险）。死循环检测仍为 ERROR。
MAX_TOC_PAGES = 100
MAX_CONTENT_PAGES = 200


# ----------------------------------------------------------------------------
# 2. 报告收集器
# ----------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.items = []  # (severity, code, msg, fix)

    def add(self, severity, code, msg, fix=""):
        self.items.append((severity, code, msg, fix))

    def error(self, code, msg, fix=""):
        self.add("ERROR", code, msg, fix)

    def warn(self, code, msg, fix=""):
        self.add("WARN", code, msg, fix)

    def info(self, code, msg, fix=""):
        self.add("INFO", code, msg, fix)

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    @property
    def warns(self):
        return [i for i in self.items if i[0] == "WARN"]

    def summary(self):
        return "ERROR=%d  WARN=%d  INFO=%d" % (
            len(self.errors), len(self.warns),
            len([i for i in self.items if i[0] == "INFO"]),
        )


# ----------------------------------------------------------------------------
# 3. 行号定位（把 JSON 字段名映射回原始文本行，方便回去改）
# ----------------------------------------------------------------------------
def locate_line(raw_text, key, value_snippet=None):
    """在原始文本里找 `"key"` 或 `key":` 出现处，返回行号（从 1 开始），找不到返回 0。"""
    if not raw_text:
        return 0
    lines = raw_text.splitlines()
    # 先按 "key": 精确匹配（最贴近字段定义处）
    pat = re.compile(r'"%s"\s*:' % re.escape(key))
    for i, ln in enumerate(lines, 1):
        if pat.search(ln):
            if value_snippet is None or value_snippet in ln:
                return i
    # 退而求其次：出现 key 字样的行
    for i, ln in enumerate(lines, 1):
        if '"%s"' % key in ln:
            return i
    return 0


# ----------------------------------------------------------------------------
# 4. 书源解析辅助
# ----------------------------------------------------------------------------
def _region(src, name):
    """取解析区域对象（新 schema 顶层 ruleXxx 对象）。"""
    v = src.get(name)
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        # 旧写法兼容：区域以字符串内联（少见），尝试当整体
        return {"_raw": v}
    return None


def _iter_region_rules(src):
    """产出 (region_name, field_name, value_string) 供逐条检查。"""
    for region in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
        r = _region(src, region)
        if not isinstance(r, dict):
            continue
        for fld, val in r.items():
            if isinstance(val, str):
                yield region, fld, val


def _collect_js(src):
    """收集所有需语法校验的 JS 片段: webJs / loginCheckJs / <js>...</js> / preUpdateJs / formatJs。"""
    frags = []
    # 顶层
    if isinstance(src.get("loginCheckJs"), str) and src["loginCheckJs"].strip():
        frags.append(("loginCheckJs", src["loginCheckJs"]))
    # 各区域
    for region, fld, val in _iter_region_rules(src):
        if fld in ("webJs", "preUpdateJs", "formatJs") and val.strip():
            frags.append(("%s.%s" % (region, fld), val))
        # 内嵌 <js>...</js>
        for m in re.finditer(r"<js>([\s\S]*?)</js>", val):
            frags.append(("%s.%s<js>" % (region, fld), m.group(1)))
    # URL 行内选项里的 js 字段（形如 ,"js":"..." 或 @js:）
    for region, fld, val in _iter_region_rules(src):
        for m in re.finditer(r'"js"\s*:\s*"((?:[^"\\]|\\.)*)"', val):
            frags.append(("%s.%s@js" % (region, fld), m.group(1)))
    return frags


def _collect_regex(src):
    """收集所有需编译校验的正则: 各区域 replaceRegex(格式 find##replace) / sourceRegex。"""
    regs = []
    for region, fld, val in _iter_region_rules(src):
        if fld == "replaceRegex" and val:
            # 多组以 \n 分隔，每组 find##replace
            for grp in val.split("\n"):
                if "##" in grp:
                    regs.append(("%s.replaceRegex" % region, grp.split("##", 1)[0]))
                else:
                    regs.append(("%s.replaceRegex" % region, grp))
        elif fld == "sourceRegex" and val:
            regs.append(("%s.sourceRegex" % region, val))
    return regs


# ----------------------------------------------------------------------------
# 5. 静态检查（纯标准库）
# ----------------------------------------------------------------------------
def check_structure(src, raw, rep):
    if not isinstance(src, dict):
        rep.error("STRUCT", "书源根必须是 JSON 对象（当前是 %s）" % type(src).__name__,
                  "确认导出的是单条书源对象，而非数组/字符串")
        return
    for f in REQUIRED_TOP:
        if not src.get(f):
            rep.error("REQ-TOP", "缺必备顶层字段 `%s`" % f,
                      "书源必须有 bookSourceName 与 bookSourceUrl 才能被导入")


def check_region_completeness(src, raw, rep):
    # 搜索/探索区域互替：纯发现源(有 exploreUrl)允许缺 ruleSearch；纯搜索源允许缺 ruleExplore
    has_explore = bool(src.get("exploreUrl")) and str(src.get("exploreUrl", "")).strip()
    has_search = bool(str(src.get("searchUrl") or "").strip())
    for region, req in REGION_REQUIRED.items():
        r = _region(src, region)
        # 无对应入口的源: 整个区域缺失/留空均属有意设计(如无搜索站 ruleSearch 全空串)
        if region == "ruleSearch" and not has_search:
            continue
        if region == "ruleExplore" and not has_explore:
            continue
        # 空 dict({}) 视同缺失: ruleExplore 为空时 App 回退用 ruleSearch（LIVE 链路同款行为），不报错
        if not r and ((region == "ruleSearch" and has_explore) or
                      (region == "ruleExplore" and has_search)):
            continue
        if not r:
            rep.warn("REGION-MISS", "缺解析区域 `%s`（该源可能不支持此功能）" % region,
                     "若此源确实用不到该区域可忽略；否则补齐 %s" % "/".join(req))
            continue
        if isinstance(r, dict):
            missing = [f for f in req if not r.get(f)]
            if missing:
                line = locate_line(raw, region)
                rep.error("REGION-REQ",
                          "`%s` 缺必备子字段 %s" % (region, "/".join(missing)),
                          "在 %s 内补上 %s（行 ~%d）" % (region, "/".join(missing), line))


def check_field_ownership(src, raw, rep):
    for fld, allowed in FIELD_OWNERSHIP.items():
        for region in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
            r = _region(src, region)
            if isinstance(r, dict) and r.get(fld) is not None:
                if region not in allowed:
                    line = locate_line(raw, fld)
                    rep.error("OWNERSHIP",
                              "`%s` 出现在 `%s`，但 3.25 只认它属于 %s → 写错位置会被静默丢弃"
                              % (fld, region, "/".join(sorted(allowed))),
                              "把 `%s` 移到 %s（行 ~%d）" % (fld, "/".join(sorted(allowed)), line))


def check_dead_fields(src, raw, rep):
    for region, fld in DEAD_FIELDS:
        r = _region(src, region)
        if isinstance(r, dict) and r.get(fld) is not None:
            line = locate_line(raw, fld)
            rep.warn("DEAD-FIELD",
                     "`%s.%s` 在 3.25 是死字段（反编译零消费点，写了不执行）" % (region, fld),
                     "正文净化改用 content 的 `<js>` 或 `##` 管道（行 ~%d）" % line)


def check_wait_field(src, raw, rep):
    # 区域行内选项 + 顶层键，都查错名等待字段
    scanned = []
    for region, fld, val in _iter_region_rules(src):
        scanned.append((region, fld, val))
    for k, v in src.items() if isinstance(src, dict) else []:
        scanned.append(("top", k, str(v)))
    for region, fld, val in scanned:
        # 顶层: 查键名; 区域行内: 查值文本（含 "webViewDelayTime": 之类内联）
        hay = (fld if region == "top" else str(val)).lower()
        for wrong in WAIT_FIELD_WRONG:
            if wrong in hay:
                line = locate_line(raw, wrong if region == "top" else fld, str(val)[:40])
                rep.error("WAIT-FIELD",
                          "`%s.%s` 里用了 `%s` —— 3.25 只认 `webWait`，错名会被 Gson 静默丢弃（本地全绿、真机取空）"
                          % (region, fld, wrong),
                          "改成 `webWait`（行 ~%d）" % line)
    # 启用 webView 却没给 webWait
    for region, fld, val in _iter_region_rules(src):
        if '"webview":true' in str(val).lower() or '"webview": true' in str(val).lower():
            if WAIT_FIELD_RIGHT not in str(val):
                line = locate_line(raw, "webView", str(val)[:40])
                rep.warn("WAIT-MISS",
                         "`%s.%s` 启用了 webView 却没显式写 webWait（3.25 默认约 1000ms，JS 挑战/解密需更长）"
                         % (region, fld),
                         "显式写 `webWait`，JS 挑战≥3000、客户端 AES 解密≥8000（行 ~%d）" % line)


def check_regex_syntax(src, raw, rep):
    for where, pattern in _collect_regex(src):
        try:
            re.compile(pattern)
        except re.error as e:
            line = locate_line(raw, "replaceRegex", pattern[:40]) or locate_line(raw, "sourceRegex", pattern[:40])
            rep.error("REGEX",
                      "`%s` 正则无法编译: %s" % (where, e),
                      "修正正则语法（行 ~%d）" % line)


def check_book_url_pattern(src, raw, rep):
    pat = src.get("bookUrlPattern")
    if not isinstance(pat, str) or not pat.strip():
        return
    try:
        re.compile(pat)
    except re.error as e:
        line = locate_line(raw, "bookUrlPattern")
        rep.error("BOOKURL-PATTERN",
                  "`bookUrlPattern` 不是合法正则: %s（真机用 kotlin.text.Regex 构造，非法会抛 "
                  "IllegalArgumentException 导致书源加载即崩溃）" % e,
                  "修正正则；该字段对搜索结果 bookUrl 做全匹配(Regex.matches)，命中即视为详情页直链"
                  "（行 ~%d）" % line)


def check_search_explore(src, raw, rep):
    """搜索/探索入口与解析区域的一致性（真机行为：缺解析区域则入口无效）。"""
    def _has_rules(region):
        r = _region(src, region)
        return isinstance(r, dict) and any(str(v).strip() for v in r.values())

    # searchUrl ↔ ruleSearch
    has_search_url = bool(str(src.get("searchUrl") or "").strip())
    has_search_rule = _has_rules("ruleSearch")

    # exploreUrl ↔ ruleExplore
    # 注意: exploreUrl 常为分类 tab 的 JSON 数组, 条目 url 为空者真机当作分组标题跳过,
    #       不算真实发现入口; 仅当存在非空 url 条目时才算"有 exploreUrl"。
    eu = str(src.get("exploreUrl") or "").strip()
    has_explore_url = False
    if eu:
        if eu.startswith("["):
            try:
                for it in json.loads(eu):
                    if isinstance(it, dict) and str(it.get("url") or "").strip():
                        has_explore_url = True
                        break
            except (ValueError, TypeError):
                has_explore_url = True  # 非 JSON 但非空, 视为有
        else:
            has_explore_url = True
    has_explore_rule = _has_rules("ruleExplore")
    # 真机语义(与 check_region_completeness 的区域互替一致): ruleSearch/ruleExplore 任一非空
    # 即可解析书目, 缺一方真机回退另一方的规则 —— 不算错。
    # 只有"两者都空却仍声明了入口", 才是真正的入口失效。
    if not has_search_rule and not has_explore_rule:
        if has_search_url:
            line = locate_line(raw, "searchUrl")
            rep.error("SEARCH-NO-RULE",
                      "配置了 searchUrl 但 ruleSearch 与 ruleExplore 均为空 —— 无任何书目解析规则，"
                      "搜到的响应无法解析，搜索等于失效",
                      "补全 ruleSearch（至少 name + bookUrl）（行 ~%d）" % line)
        elif has_explore_url:
            line = locate_line(raw, "exploreUrl")
            rep.error("EXPLORE-NO-RULE",
                      "配置了 exploreUrl 但 ruleExplore 与 ruleSearch 均为空 —— 无任何书目解析规则，"
                      "发现页响应无法解析",
                      "补全 ruleExplore（至少 name + bookUrl）（行 ~%d）" % line)
    else:
        # 单侧缺一: 真机可回退, 只提示"该入口规则无法被触发"
        if has_explore_rule and not has_explore_url:
            line = locate_line(raw, "ruleExplore") or locate_line(raw, "name")
            rep.warn("EXPLORE-NO-URL",
                     "配置了 ruleExplore 但无 exploreUrl —— 发现规则无法被触发（搜索仍可用）",
                     "若确需发现页，提供 exploreUrl（行 ~%d）" % line)
        if has_search_rule and not has_search_url and not str(src.get("bookSourceUrl") or "").strip():
            line = locate_line(raw, "ruleSearch") or locate_line(raw, "name")
            rep.error("SEARCH-NO-URL",
                      "配置了 ruleSearch 但无 searchUrl 也无 bookSourceUrl —— 无法触发搜索请求",
                      "提供 searchUrl（或 bookSourceUrl 兼作搜索入口）（行 ~%d）" % line)

    # bookSourceUrl 必须是 http(s) 绝对地址（真机以此判定站点根域）
    bsu = str(src.get("bookSourceUrl") or "").strip()
    if bsu and not re.match(r'^https?://', bsu):
        line = locate_line(raw, "bookSourceUrl")
        rep.error("BOOKSOURCE-URL",
                  "`bookSourceUrl` 必须是 http(s) 绝对地址（真机以此作站点根域与 baseUrl），"
                  "当前: %s" % bsu[:40],
                  "改成 https:// 开头的完整地址（行 ~%d）" % line)


def check_js_syntax(src, raw, rep):
    frags = _collect_js(src)
    if not frags:
        return
    node = shutil.which("node")
    if not node:
        rep.info("JS-SKIP", "未找到 node，跳过 JS 语法校验（装 node 后可查 webJs/loginCheckJs/<js> 语法）")
        return
    for where, code in frags:
        if not code.strip():
            continue
        # java.get(url) 单参不是 HTTP（铁律: 静默返回空串）
        if re.search(r'java\.get\(\s*["\'][^"\']+["\']\s*\)', code):
            line = locate_line(raw, "loginCheckJs") or locate_line(raw, "webJs")
            rep.error("JAVA-GET",
                      "`%s` 里出现单参 `java.get(url)` —— 这不是 HTTP 请求，3.25 会静默返回空串"
                      % where,
                      "改成双参 `java.get(url, header)` 或用 `java.connect`（行 ~%d）" % line)
        # 注: 真机 StrResponse 同时提供 body()(:193) 与 getBody()(:234), 二者同义 —— 均合法, 不告警
        # 工具无法真机模拟的 java API（GUI/TTF 反爬/非对称签名/7z-rar 解压/繁简未打包）
        _UNEMU = [
            ("webView", "GUI 渲染，工具无头环境不执行（动态检查会原样跳过）"),
            ("webViewGetSource", "GUI 渲染，工具无头环境不执行"),
            ("webViewGetOverrideUrl", "GUI 渲染，工具无头环境不执行"),
            ("startBrowser", "GUI 跳转，工具无头环境不执行"),
            ("startBrowserAwait", "GUI 跳转并等待，工具无头环境不执行"),
            ("getVerificationCode", "验证码 GUI，工具无法处理（动态检查返回空）"),
            ("queryTTF", "TTF 字体反爬，工具未实现（动态检查返回空）"),
            ("queryBase64TTF", "TTF 字体反爬，工具未实现"),
            ("replaceFont", "TTF 字体替换，工具无 TTF 数据（动态检查原样返回）"),
            ("createSign", "非对称签名，工具未对齐（签名算法未实证）"),
            ("createAsymmetricCrypto", "非对称签名，工具未对齐（签名算法未实证）"),
            ("get7zStringContent", "7z 解压，环境无 7z CLI，工具返回空"),
            ("get7zByteArrayContent", "7z 解压，环境无 7z CLI，工具返回空"),
            ("getRarStringContent", "rar 解压，环境无 rar 解压，工具返回空"),
            ("getRarByteArrayContent", "rar 解压，环境无 rar 解压，工具返回空"),
            ("un7zFile", "7z 解压，环境无 7z CLI，工具返回空"),
            ("unrarFile", "rar 解压，环境无 rar 解压，工具返回空"),
        ]
        for _name, _why in _UNEMU:
            if re.search(r'java\.%s\(' % re.escape(_name), code):
                rep.warn("JAVA-UNEMU",
                         "`%s` 用到 `java.%s` —— %s" % (where, _name, _why),
                         "动态检查结果对该 API 不可信；真机可正常运行（行 ~%d）"
                         % (locate_line(raw, "loginCheckJs") or locate_line(raw, "webJs")))
        # Legado 模板 {{...}} 真机先求值替换再执行 JS —— 语法检查须先替换为占位符，
        # 否则把合法模板误报为语法错误（话本小说 ruleToc.updateTime 实证误报）
        check_code = re.sub(r'\{\{[\s\S]*?\}\}', '0', code)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
            tf.write(check_code)
            tmp = tf.name
        try:
            r = subprocess.run([node, "--check", tmp], capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                line = locate_line(raw, "loginCheckJs") or locate_line(raw, "webJs")
                msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "语法错误"
                rep.error("JS-SYNTAX", "`%s` JS 语法错误: %s" % (where, msg),
                          "抽该片段单独 `node --check` 定位（行 ~%d）" % line)
        except subprocess.TimeoutExpired:
            rep.warn("JS-TIMEOUT", "`%s` node --check 超时（疑似巨型片段）" % where)
        finally:
            os.unlink(tmp)


def check_urls(src, raw, rep):
    # 只校验真正的 URL 字段; 区域里的 bookUrl/chapterUrl 是「提取规则」不是 URL, 不查
    url_fields = ["bookSourceUrl", "searchUrl", "ruleFindUrl"]
    cand = {}
    for f in url_fields:
        if isinstance(src.get(f), str):
            cand[f] = src[f]
    # ruleBookInfo.tocUrl 是目录 URL 模板(常含 {{bookUrl}}), 属于 URL
    bi = _region(src, "ruleBookInfo")
    if isinstance(bi, dict) and isinstance(bi.get("tocUrl"), str):
        cand["ruleBookInfo.tocUrl"] = bi["tocUrl"]
    # 区域里的 searchUrl(搜索 URL 模板)
    for region, fld, val in _iter_region_rules(src):
        if fld == "searchUrl":
            cand["%s.searchUrl" % region] = val
    for where, u in cand.items():
        u = str(u).strip()
        if not u:
            continue
        # data: URI（真机 AnalyzeUrl.getByteArrayIfDataUri 内联 base64 解码, 不发网络请求）
        if u.startswith("data:"):
            if re.match(r'^data:.*?;base64,', u, re.I):
                rep.info("URL-DATA",
                         "`%s` 是 data: URI —— 真机 base64 内联解码、不发网络请求，"
                         "LIVE 校验将跳过 HTTP 直接解码" % where)
            else:
                rep.warn("URL-DATA",
                         "`%s` 是 data: URI 但非 `;base64,` 形态，真机 getByteArrayIfDataUri 可能不识别"
                         % where,
                         "确认是否为标准 data: URI（行 ~%d）" % locate_line(raw, where.split(".")[-1], u[:40]))
            continue
        # URL 字段内联 ,{...} 选项含 useWebView/webJs → 真机走 WebView 渲染(JS 执行后取 DOM)
        _mopt = re.search(r',\s*(\{.*)', u, re.S)
        if _mopt:
            try:
                _o = json.loads(_mopt.group(1))
                if _o.get("useWebView") or _o.get("webJs"):
                    line = locate_line(raw, where.split(".")[-1], u[:40])
                    rep.warn("URL-WEBVIEW",
                             "`%s` 的 URL 选项含 useWebView/webJs —— 真机用 WebView 渲染"
                             "（执行 JS 后取 DOM），工具 LIVE 默认走 requests 拿不到渲染结果"
                             % where,
                             "用 --browser 走 headless Chromium 校验（行 ~%d）" % line)
            except Exception:
                pass
        # 跳过明显是「解析规则」而非字面 URL 的取值:
        # {{变量}} / <js> / @XPath / 以 // 或 / 开头的 XPath /
        # 含 @ (Jsoup 属性或层级操作符) / 含 ( (正则或函数) / 以 : 开头(:regex) / 以 $ 开头(JSONPath)
        if ("{{" in u or "<js>" in u or u.startswith("@XPath")
                or u.startswith("//") or "@" in u or "(" in u
                or u.startswith(":") or u.startswith("$")):
            continue
        if re.match(r'^(https?://|/)', u):
            continue
        if re.match(r'^[\w.-]+://', u):  # 其它非常见 scheme（thunder/magnet 等书源偶尔用）
            continue
        line = locate_line(raw, where.split(".")[-1], u[:40])
        rep.warn("URL", "`%s` 看起来不像合法 URL（应以 http(s):// 或 / 开头）: %s"
                 % (where, u[:60]),
                 "确认链接格式（行 ~%d）" % line)


def check_parse_path_sanity(src, raw, rep):
    """解析路径基础语法: 括号配平（XPath）、JSONPath 以 $ 开头。Jsoup 扩展语法太灵活，不在此判。"""
    for region, fld, val in _iter_region_rules(src):
        v = str(val)
        # XML/XPath 括号配平
        if v.lstrip().startswith("/") or v.startswith("@XPath"):
            if v.count("(") != v.count(")"):
                line = locate_line(raw, fld, v[:40])
                rep.warn("XPATH-BRACE", "`%s.%s` XPath 圆括号不配平（%d 开 %d 闭）"
                         % (region, fld, v.count("("), v.count(")")),
                         "检查 XPath 括号（行 ~%d）" % line)
        # JSONPath 以 $ 开头
        if v.lstrip().startswith("$"):
            if not re.match(r'^\$\.?', v):
                rep.warn("JSONPATH", "`%s.%s` 以 $ 开头但格式异常: %s" % (region, fld, v[:40]))


def check_concurrent_rate(src, raw, rep):
    cr = src.get("concurrentRate")
    if cr in (None, "", 0, "0"):
        return
    has_paging = False
    for region, fld, val in _iter_region_rules(src):
        if fld in ("nextTocUrl", "nextContentUrl", "nextExploreUrl") and str(val).strip():
            has_paging = True
    if has_paging:
        line = locate_line(raw, "concurrentRate")
        rep.warn("CONCURRENT",
                 "`concurrentRate=%s` 是全局串行限速（两次请求至少间隔 N 毫秒，跨全书源）"
                 "，与分页(目录/正文/发现)并发抓取冲突 → 加载被拖成十几秒" % cr,
                 "分页站点不要设 concurrentRate；限流优先 enabledCookieJar+loginCheckJs（行 ~%d）" % line)


def check_next_toc(src, raw, rep):
    for region, fld, val in _iter_region_rules(src):
        if not fld.endswith("nextTocUrl") and not fld.endswith("nextContentUrl") \
                and not fld.endswith("nextExploreUrl"):
            continue
        v = str(val)
        if not v:
            continue
        # 取"尾页"特征 + 无 JS 页码逻辑 → 跳页丢章
        tail_markers = ["last-child", "last-of-type", "尾页", "末页", "最后一页"]
        has_tail = any(m in v for m in tail_markers)
        has_js_page = bool(re.search(r'<js>|page\s*\+|\?page=|\bpage\b', v))
        if has_tail and not has_js_page:
            line = locate_line(raw, fld, v[:40])
            rep.warn("NEXT-TAIL",
                     "`%s.%s` 用「尾页」类选择器(%s)但无 JS 页码逻辑 → 可能跳到尾页丢中间章节"
                     % (region, fld, "/".join(m for m in tail_markers if m in v)),
                     "改用「下一页」链接或按 ?page=N 做 page+1，末页返回空串停（行 ~%d）" % line)


def check_cookie_jar(src, raw, rep):
    """启用 webView 的站点，强烈建议 enabledCookieJar:true（CF/明文 cookie 站点）。"""
    uses_webview = False
    for region, fld, val in _iter_region_rules(src):
        if '"webview":true' in str(val).lower():
            uses_webview = True
    if uses_webview and not src.get("enabledCookieJar"):
        line = locate_line(raw, "enabledCookieJar") or locate_line(raw, "bookSourceUrl")
        rep.warn("COOKIE-JAR",
                 "书源用了 webView 但没写 `enabledCookieJar:true` —— CF/明文 cookie 验证站必须显式开启",
                 "加 `\"enabledCookieJar\": true`（行 ~%d）" % line)


# ----------------------------------------------------------------------------
# 6. 动态检查（XPath 真机 JsoupXpath / Jsoup 真 jar / JSONPath jayway 同构，按需）
# ----------------------------------------------------------------------------
def _find_jsoup_jar(script_dir):
    candidates = [
        os.path.join(script_dir, "booksource_lint_assets", "jsoup-1.17.2.jar"),
        os.path.join(script_dir, "booksource_lint_assets", "JsoupRuleEval.class"),
    ]
    jar = candidates[0]
    klass = candidates[1]
    if os.path.isfile(jar) and os.path.isfile(klass):
        return jar, os.path.dirname(klass)
    # 退化: 找 skill 目录
    for base in (os.path.expanduser("~/.workbuddy/skills/legado-booksource-debug/scripts/jsoup_eval"),
                 "/workspace/legado-booksource-debug/scripts/jsoup_eval"):
        j = os.path.join(base, "jsoup-1.17.2.jar")
        k = os.path.join(base, "JsoupRuleEval.class")
        if os.path.isfile(j) and os.path.isfile(k):
            return j, base
    return None, None


def _rule_kind(rule):
    """按 APK AnalyzeRule$SourceRule.init 实证派发（前缀均 ignoreCase 且必须带冒号）:
    <js>/@js: -> JS | @XPath: -> XPath | @Json: -> JSONPath | @CSS:/@@ -> Jsoup |
    ':' 前缀 -> Regex | '$.'/'$[' 开头 -> JSONPath | '/' 开头 -> XPath |
    含 {{}} 或 @get:{} 或主段含 $N(分组引用) -> 真机 Mode.Regex 组装分支(字面量) |
    其余 -> jsoup（真机 Default 模式即 Jsoup select，无字面量捷径！）。

    实证: AnalyzeByRegex$SourceRule.init 前缀链 @CSS:/@@/@XPath:/@Json: startsWith(ignoreCase=true)
    (本地 smali AnalyzeRule$SourceRule.smali 逐指令核对);
    getString 的 Mode.Default -> getAnalyzeByJSoup(...).getString() —— 纯选择器必须过 Jsoup，
    只有 evalPattern(@get:{}/{{}}) 命中或 splitRegex 的 \\$\\d{1,2} 命中才进 Regex 组装分支。
    注意: '@' 无前缀时是元素相对简写(如 a@href)，仍属 Jsoup; '&&' 是组合分隔符
    (见 _split_combination); '##' 是段内替换(makeUpRule 先组装再拆 ##)。"""
    s = str(rule).strip()
    if not s:
        return "literal"
    low = s.lower()
    if low.startswith("<js>") or low.startswith("@js:"):
        return "js"
    if low.startswith("@xpath:"):
        return "xpath"
    if low.startswith("@json:"):
        return "jsonpath"
    if s.startswith("@css:") or s.startswith("@@"):
        return "jsoup"
    if s.startswith("$.") or s.startswith("$["):
        return "jsonpath"
    if s.startswith("/"):
        return "xpath"
    if s.startswith(":"):
        return "regex"
    # 真机 evalPattern: @get:{...}|{{...}}(CASE_INSENSITIVE) 命中 -> Regex 组装分支，
    # 返回组装后的字面量; makeUpRule 里 $N 从上一阶段结果列表取值，同样按字面量处理。
    if "{{" in s or "@get:" in low:
        return "literal"
    main = s.split("##")[0]
    if re.search(r"\$\d{1,2}", main):
        return "literal"
    return "jsoup"


# ----------------------------------------------------------------------------
# 组合规则切分（对齐 RuleAnalyzer.splitRule("&&","||","%%")）
#   - 括号 [ ] / ( ) 平衡组内（且引号/转义感知）的分隔符受保护，不当切分点
#   - 首个出现的分隔符即为 elementsType; 之后只按它切
#   - 括号不平衡时真机抛 Error("后未平衡"); 这里返回 None 交给引擎自行报语法错
#   - 真机语义（JSoup/XPath/JSONPath 三引擎源码一致）: 各段从同一根元素**并行**选择后合并:
#       &&  -> 各段结果 concat      || -> 第一个非空段      %% -> 列优先交错(ragged zip)
#     (Regex 模式例外: AnalyzeByRegex 按 splitNotBlank("&&") 顺序链式, 见 _regex_engine)
# ----------------------------------------------------------------------------
_COMB_SEPS = ("&&", "||", "%%")


def _split_combination(rule):
    """括号/引号感知切分。返回 (elementsType, segments);
    elementsType=None 表示无组合分隔符或括号不平衡（调用方按单段处理）。"""
    s = str(rule)
    n = len(s)
    etype = None
    # 第一遍: 找 depth==0 且引号外最早出现的分隔符
    in_s = in_d = False
    depth = 0
    i = 0
    while i < n:
        c = s[i]
        if c == "'" and not in_d:
            in_s = not in_s
            i += 1
            continue
        if c == '"' and not in_s:
            in_d = not in_d
            i += 1
            continue
        if in_s or in_d:
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c in "[(":
            depth += 1
            i += 1
            continue
        if c in "])":
            depth -= 1
            if depth < 0:
                return None, [s]  # 不平衡, 不切
            i += 1
            continue
        if depth == 0:
            for sp in _COMB_SEPS:
                if s.startswith(sp, i):
                    etype = sp
                    break
            if etype is not None:
                break
        i += 1
    if etype is None or depth != 0:
        return None, [s]
    # 第二遍: 只按该分隔符切
    segs = []
    cur = []
    in_s = in_d = False
    depth = 0
    i = 0
    while i < n:
        c = s[i]
        if c == "'" and not in_d:
            in_s = not in_s
        elif c == '"' and not in_s:
            in_d = not in_d
        elif not in_s and not in_d:
            if c == "\\":
                cur.append(s[i:i + 2])
                i += 2
                continue
            if c in "[(":
                depth += 1
            elif c in "])":
                depth -= 1
            elif depth == 0 and s.startswith(etype, i):
                segs.append("".join(cur))
                cur = []
                i += len(etype)
                continue
        cur.append(c)
        i += 1
    segs.append("".join(cur))
    return etype, segs


def _strip_xpath_prefix(s):
    """剥离 @XPath: 前缀(ignoreCase, 必须带冒号); 无冒号的 @XPath 不是 XPath(真机当 CSS 选)。"""
    return re.sub(r"(?i)^@xpath:", "", str(s), count=1)


def _strip_inline_options(rule):
    """剥掉规则尾部行内选项, 对齐 AnalyzeUrl UrlOption 层:
    a@href,{"webView":true} -> a@href。仅当 ',{' 之后整体是合法 JSON 对象才剥,
    避免误伤 CSS 里极少见的 ',{' 字面量。"""
    s = str(rule)
    idx = 0
    while True:
        i = s.find(",{", idx)
        if i < 0:
            return s
        try:
            v = json.loads(s[i + 1:])
            if isinstance(v, dict):
                return s[:i]
        except Exception:
            pass
        idx = i + 1


def _strip_js_blocks(rule):
    """剥掉规则中的 <js>...</js> 与 @js:... 段(JS 由 check_js_syntax 静态覆盖),
    返回剩余的选择器部分。动态引擎只应看到非 JS 部分。"""
    return _JS_MARKER_RE.sub("", str(rule)).strip()


def _run_jsoup(jar_dir, html_file, rule, mode="text"):
    """调真 Jsoup 桥接。返回 (ok, results_or_error)。ok=False 表示语法异常。
    mode="text": 提取文本/属性(默认); mode="elem": 返回每个匹配元素的 outerHtml(列表迭代)。
    JsoupRuleEval 输出 base64 编码结果（每行一条），这里解码回真实文本。"""
    try:
        r = subprocess.run(
            ["java", "-cp", "%s:%s" % (os.path.join(jar_dir, "jsoup-1.17.2.jar"), jar_dir),
             "JsoupRuleEval", html_file, rule, mode],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "Jsoup 执行异常")
        out = []
        for l in r.stdout.splitlines():
            l = l.strip()
            if not l:
                continue
            try:
                out.append(base64.b64decode(l).decode("utf-8", "replace"))
            except Exception:
                out.append(l)
        return True, out
    except Exception as e:  # noqa
        return False, str(e)


# ---------------------------------------------------------------------------
# 真机 XPath 引擎桥接（org.seimicrawler.xpath == JsoupXpath 2.5.5，与 APK 同包名）
#   对齐 AnalyzeByXPath.strToJXDocument: 表格包裹预处理 + <?xml 切 xmlParser
#   单段 selN + JXNode.asString 序列化(元素 outerHTML / 文本 / 属性值)
#   组合符 &&/||/%% 由 Python 侧 _eval_combo 已对齐 splitRule, 本桥接只处理单段
# ---------------------------------------------------------------------------
_XPATH_DEPS = ["JsoupXpath-2.5.5.jar", "jsoup-1.15.3.jar", "commons-lang3-3.12.0.jar",
               "antlr4-runtime-4.7.2.jar", "slf4j-api-2.0.6.jar", "slf4j-nop-2.0.6.jar"]


def _find_xpath_jar(script_dir):
    """定位真机 XPath 引擎(XPathBench.jar + 依赖)。返回目录路径或 None。"""
    base = os.path.join(script_dir, "booksource_lint_assets", "jxpath")
    if os.path.isfile(os.path.join(base, "XPathBench.jar")):
        return base
    for alt in (os.path.expanduser("~/.workbuddy/skills/legado-booksource-debug/scripts/xpath_eval"),
                "/workspace/legado-booksource-debug/scripts/xpath_eval"):
        if os.path.isfile(os.path.join(alt, "XPathBench.jar")):
            return alt
    return None


def _run_xpath(html_file, rule, jar_dir=None):
    """真机 XPath 引擎单段求值。返回 (ok, results)。
    ok=False 时 results 为错误信息字符串。无 jar/Java 时退回 lxml 近似。
    rule 为已剥离 @XPath: 前缀的单段; html_file 为页面文件路径。"""
    if jar_dir is None:
        jar_dir = _find_xpath_jar(os.path.dirname(os.path.abspath(__file__)))
    if not jar_dir:
        return _run_xpath_lxml(html_file, rule)
    try:
        cp = ":".join([os.path.join(jar_dir, "XPathBench.jar")] +
                      [os.path.join(jar_dir, d) for d in _XPATH_DEPS])
        r = subprocess.run(["java", "-cp", cp, "XPathBench", "list", html_file, rule],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "XPath 引擎异常")
        lines = r.stdout.splitlines()
        if not lines:
            return True, []
        n = int(lines[0])
        out = []
        for i in range(n):
            b = lines[1 + i] if 1 + i < len(lines) else ""
            try:
                out.append(base64.b64decode(b).decode("utf-8", "replace"))
            except Exception:
                out.append(b)
        return True, out
    except Exception as e:  # noqa
        return False, str(e)


def _run_xpath_compile(rule, jar_dir=None):
    """XPath 语法预校验: 调真机引擎编译(最小文档), 语法错返回 (False, error)。
    无 jar 时退回 lxml 近似编译。"""
    if jar_dir is None:
        jar_dir = _find_xpath_jar(os.path.dirname(os.path.abspath(__file__)))
    if not jar_dir:
        return _run_xpath_lxml_compile(rule)
    try:
        cp = ":".join([os.path.join(jar_dir, "XPathBench.jar")] +
                      [os.path.join(jar_dir, d) for d in _XPATH_DEPS])
        r = subprocess.run(["java", "-cp", cp, "XPathBench", "compile", rule],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "XPath 编译异常")
        ok = r.stdout.strip() == "OK"
        return ok, (None if ok else r.stdout.strip())
    except Exception as e:  # noqa
        return False, str(e)


def _run_xpath_lxml(html_file, rule):
    """无真机引擎时的 lxml 近似(标准 XPath 1.0, 非 seimicrawler 语法, 不做表格包裹)。"""
    try:
        import lxml.etree
        tree = lxml.etree.parse(html_file, lxml.etree.HTMLParser(encoding="utf-8"))
        res = tree.xpath(rule)
        if not res:
            return True, []
        return True, [r if isinstance(r, str) else lxml.etree.tostring(
            r, encoding="unicode", method="html") for r in res]
    except Exception as e:  # noqa
        return False, str(e)


def _run_xpath_lxml_compile(rule):
    """lxml 近似语法校验(无真机引擎时)。lxml 不可用则跳过(不误报)。"""
    try:
        import lxml.etree
    except Exception:
        return True, None
    try:
        lxml.etree.XPath(rule)
        return True, None
    except Exception as e:  # noqa
        return False, str(e)


def _eval_list(html_file, rule, jar_dir):
    """对齐 Legado getElements(bookList/chapterList 列表规则): 组合规则(&&/||/%%)
    括号/引号感知切分 -> 每段从同一根**并行**选择元素 -> 合并(&& concat /
    || 首个非空 / %% 列优先交错) -> 返回每个匹配元素的 outerHtml 列表
    (供逐条套用 name/bookUrl/chapterName 等子规则)。
    rule 为空或 '##' 表示整页即一条; ':' 前缀纯正则在 AnalyzeByRegex 顺序链式。"""
    if not jar_dir:
        return []
    rule = _strip_inline_options(str(rule)).strip()
    if not rule or rule == "##":
        try:
            with open(html_file, encoding="utf-8") as f:
                return [f.read()]
        except Exception:
            return []
    rev = rule.startswith("-")   # '-' 前缀: 真机在列表层对最终结果倒序
    if rev:
        rule = rule[1:]
    # 源码同构(AnalyzeRule.getElements:627-665): splitSourceRule -> 每段 makeUpRule
    # -> 元素级引擎(引擎内再拆 &&/||/%%) -> 合并
    out = []
    for seg, _mode in _split_source_rule(rule):
        sr = _SRule(seg, _mode)
        sr.make_up_rule([], {})
        etype, segs = _split_combination(sr.rule)
        if etype is None:
            items = _eval_list_seg(html_file, sr.rule, jar_dir, mode=_mode)
        else:
            results = []
            for s2 in segs:
                s2 = s2.strip()
                if not s2:
                    continue
                it = _eval_list_seg(html_file, s2, jar_dir, mode=_mode)
                if it:
                    results.append(it)
                    if etype == "||":
                        break
            items = _merge_combo(results, etype)
        out.extend(items)
    if rev:
        out.reverse()
    return out


def _jp_strip_braces(rule):
    """剥离 Legado 内联默认块 {…}（含配对括号，字符串感知），用于语法预校验。"""
    out = []
    i = 0
    n = len(rule)
    while i < n:
        c = rule[i]
        if c == "{":
            end = _jp_chomp_balanced(rule, i)
            if end != -1:
                i = end + 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _jp_find(rule, data):
    """对齐真机 AnalyzeByJSonPath.getStringList：返回字符串列表。
    优先 jayway 同构引擎（真机对齐），兜底 jsonpath_ng。"""
    if not rule:
        return []
    if _HAVE_JAYWAY:
        try:
            return _jp_get_string_list(rule, data)
        except Exception:  # noqa
            return []
    try:
        import jsonpath_ng
        return [str(r.value) for r in jsonpath_ng.parse(rule).find(data)]
    except Exception:  # noqa
        return []


def _jp_compile(rule):
    """JSONPath 语法预校验：剥离 {…} 内联块与 &&/||/%% 组合符后逐段编译。
    优先 jayway（真机对齐），兜底 jsonpath_ng 整体编译。语法错误抛 InvalidPath。"""
    if _HAVE_JAYWAY:
        stripped = _jp_strip_braces(rule)
        for seg in _jp_split_rule(stripped, ("&&", "||", "%%")):
            seg = seg.strip()
            if seg:
                _JaywayPath(seg)  # 语法错误 → InvalidPath
        return
    import jsonpath_ng
    jsonpath_ng.parse(rule)


def _eval_list_seg(html_file, seg, jar_dir, mode=None):
    """列表规则的单个组合段(元素级)。对齐 getElements 的 when(mode) 分发:
    Regex(':'前缀/组装) -> AnalyzeByRegex.getElements 顺序链式; XPath -> getElements
    组合并行; Json -> getList; Default -> Jsoup getElements 组合并行。
    mode 优先: 真机 splitSourceRule 在剥 @js: 前缀**前**已定 mode, 剥后规则体
    不再含前缀, 不能靠 _rule_kind 重判(否则 js 段被误判成 jsoup)。"""
    main = str(seg).split("##")[0].strip()
    kind = mode if mode is not None else _rule_kind(main)
    if kind == "js":
        # 列表 JS 段: 真机 getElements 对 evalJS 结果 —— NativeArray/List → 逐元素;
        # 字符串 → 按 \n 拆行。node 侧 list_mode 以 JSON 数组整体回传数组结果。
        m = _JS_MARKER_RE.search(str(seg))
        code = (m.group(1) if m.group(1) is not None else m.group(2)) if m else main
        try:
            with open(html_file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            return []
        out = _eval_js(code, text, None, list_mode=True)
        if out.startswith("<<JS_ERROR:"):
            return []
        try:
            parsed = json.loads(out)
            if isinstance(parsed, list):
                return [x for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [x for x in out.splitlines() if x.strip()]
    if kind == "literal":
        # 真机 Regex 模式: 对整页文本按该规则做正则链式; 组装配字面量通常无命中
        return []
    if kind == "jsonpath":
        try:
            with open(html_file, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            return _jp_find(main, data)
        except Exception:
            return []
    if kind == "xpath":
        # 注意: 不可传入 Jsoup 的 jar_dir —— 那是 Jsoup jar 目录, 没有 XPathBench.jar;
        # 传 None 让 _run_xpath 自己定位 jxpath 目录(_find_xpath_jar), 否则误判引擎不可用→0 条
        ok, out = _run_xpath(html_file, _strip_xpath_prefix(main))
        return out if ok else []
    if kind == "regex":
        try:
            with open(html_file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            return []
        return _regex_engine(text, str(seg))
    # jsoup(Default): 取匹配元素 outerHtml
    ok, out = _run_jsoup(jar_dir, html_file, str(seg), mode="elem")
    return out if ok else []


# ----------------------------------------------------------------------------
# 规则组合语义（本地 APK 反编译 smali 逐指令实证）
#   <js>...</js> | @js:    -> JS_PATTERN 切段, evalJS 注入 (splitSourceRule,
#                            AnalyzeRule.smali 调 t6/i.a, 模式串见 t6/i.smali)
#   {{var}}                -> 变量替换 / makeUpRule 组装 (evalPattern)
#   ##                     -> 段内替换: makeUpRule 先组装再拆, 引擎取值后应用
#   && / || / %%           -> 组合分隔符, 括号引号感知, 各段同根并行选择后合并
#                            (getStringList 循环体内 iget-object v11, p0, element 为同一根,
#                             AnalyzeByJSoup.smali / AnalyzeRule.smali 三处一致)
#   :regex(a) && :regex(b) -> Regex 模式例外: AnalyzeByRegex 顺序链式
# 以上均来自本地 legado_app_3.25.apk 字节码实证, 非推测。
# ----------------------------------------------------------------------------
_JS_MARKER_RE = re.compile(r"<js>([\w\W]*?)</js>|@js:([\w\W]*)", re.IGNORECASE)
_VAR_RE = re.compile(r"\{\{([\w\W]*?)\}\}")
_REPLACE_SEP = "##"


_SR_PUT_RE = re.compile(r"@put:(\{[^}]+?\})", re.IGNORECASE)          # :86
_SR_EVAL_RE = re.compile(r"@get:\{[^}]+?\}|\{\{[\w\W]*?\}\}", re.IGNORECASE)  # :87
_SR_DOLLAR_RE = re.compile(r"\$\d{1,2}")                              # :88

_SR_DEFAULT_TYPE = 0     # 普通片段
_SR_JS_TYPE = -1         # {{...}}  (jsRuleType)
_SR_GET_TYPE = -2        # @get:{}  (getRuleType)


def _sr_starts(s, prefix, ignore_case=False):
    return s.lower().startswith(prefix.lower()) if ignore_case else s.startswith(prefix)


class _SRule(object):
    """对齐 AnalyzeRule$SourceRule（源码 1609-1900）: 前缀判 mode + evalPattern 分片 + makeUpRule。"""

    def __init__(self, rule_str, mode=None):
        self.mode = mode or "default"
        self.replace_regex = ""
        self.replacement = ""
        self.replace_first = False
        self.put_map = {}
        self.rule_param = []
        self.rule_type = []
        self.rule = str(rule_str or "")
        rs = self.rule
        if self.mode not in ("js", "regex"):
            # 源码 1636-1658: 前缀判定（@CSS: 是 ignoreCase 且不剥前缀，交给 Jsoup 层剥）
            if _sr_starts(rs, "@CSS:", True):
                self.mode = "default"
            elif _sr_starts(rs, "@@", False):
                self.mode = "default"
                rs = rs[2:]
            elif _sr_starts(rs, "@XPath:", True):
                self.mode = "xpath"
                rs = rs[7:]
            elif _sr_starts(rs, "@Json:", True):
                self.mode = "jsonpath"
                rs = rs[6:]
            elif _sr_starts(rs, "$.", False) or _sr_starts(rs, "$[", False):
                self.mode = "jsonpath"
            elif _sr_starts(rs, "/", False):
                self.mode = "xpath"
        self.rule = self._split_put_rule(rs)
        # 源码 1660-1707: evalPattern 分片
        m = _SR_EVAL_RE.search(self.rule)
        if m:
            prefix = self.rule[:m.start()]
            if self.mode not in ("js", "regex") and (
                    m.start() == 0 or not prefix.endswith("##")):
                self.mode = "regex"          # 含 {{}}/@get:{} 且前缀不以 ## 结尾 -> Regex 组装分支
            pos = 0
            while m:
                if m.start() > pos:
                    self._split_regex(self.rule[pos:m.start()])
                g = m.group()
                if _sr_starts(g, "@get:", True):
                    self.rule_type.append(_SR_GET_TYPE)
                    self.rule_param.append(g[6:-1])
                elif _sr_starts(g, "{{", False):
                    self.rule_type.append(_SR_JS_TYPE)
                    self.rule_param.append(g[2:-2])
                else:
                    self._split_regex(g)
                pos = m.end()
                m = _SR_EVAL_RE.search(self.rule, pos)
            if len(self.rule) > pos:
                self._split_regex(self.rule[pos:])

    def _split_put_rule(self, rule_str):
        """源码 288-320: 剥掉 @put:{...} 片段并解析进 putMap。"""
        out = rule_str
        for m in _SR_PUT_RE.finditer(rule_str):
            out = out.replace(m.group(0), "")
            try:
                self.put_map.update(json.loads(m.group(1)))
            except Exception:
                pass
        return out

    def _split_regex(self, rule_str):
        """源码 1717-1745: 只对第一个 ## 段扫 $N，切出 param/type 列表。"""
        main = rule_str.split("##")[0]
        m = _SR_DOLLAR_RE.search(main)
        pos = 0
        if m:
            if self.mode not in ("js", "regex"):
                self.mode = "regex"
            while m:
                if m.start() > pos:
                    self.rule_type.append(_SR_DEFAULT_TYPE)
                    self.rule_param.append(rule_str[pos:m.start()])
                g = m.group()
                try:
                    self.rule_type.append(int(g[1:]))
                except Exception:
                    self.rule_type.append(_SR_DEFAULT_TYPE)
                self.rule_param.append(g)
                pos = m.end()
                m = _SR_DOLLAR_RE.search(main, pos)
        if len(rule_str) > pos:
            self.rule_type.append(_SR_DEFAULT_TYPE)
            self.rule_param.append(rule_str[pos:])

    @staticmethod
    def _is_rule(s):
        """源码 1709-1715: 含 '@' 或以 $./$[// 开头 → 视为"规则"（递归求值），否则当 JS。"""
        return ("@" in s or s.startswith("$.") or s.startswith("$[")
                or s.startswith("//"))

    def make_up_rule(self, result, ctx):
        """源码 1782-1840: 倒序组装 param（$N/JS/@get/字面）→ 拆 ## → 取 replaceRegex 等。"""
        if self.rule_param:
            sb = []
            for i in range(len(self.rule_param) - 1, -1, -1):
                t = self.rule_type[i]
                p = self.rule_param[i]
                if t > _SR_DEFAULT_TYPE:            # $N: 从 result 列表取第 N 项
                    if isinstance(result, (list, tuple)) and len(result) > t:
                        v = result[t]
                        if v is not None:
                            sb.insert(0, str(v))
                    else:
                        sb.insert(0, p)
                elif t == _SR_JS_TYPE:              # {{...}}
                    if self._is_rule(p):
                        sb.insert(0, _sr_get_string(p, ctx, result))
                    else:
                        v = _eval_js(p, result, ctx.get("vars"))
                        sb.insert(0, "" if v is None else str(v))
                elif t == _SR_GET_TYPE:             # @get:{key}
                    sb.insert(0, str((ctx.get("vars") or {}).get(p, "")))
                else:
                    sb.insert(0, p)
            self.rule = "".join(sb)
        parts = self.rule.split(_REPLACE_SEP)
        self.rule = parts[0].strip()
        if len(parts) > 1:
            self.replace_regex = parts[1]
        if len(parts) > 2:
            self.replacement = parts[2]
        if len(parts) > 3:
            self.replace_first = True


def _sr_apply_replace(value, sr):
    """源码 245-274: replaceFirst 只替换首个匹配且未命中返回空串；否则全部替换（异常退化字面替换）。"""
    if not sr.replace_regex:
        return value
    if sr.replace_first:
        try:
            m = re.search(sr.replace_regex, value)
            if not m:
                return ""
            return re.sub(sr.replace_regex,
                          _sr_repl_escape(sr.replacement), m.group(0), count=1)
        except Exception:
            return sr.replacement
    try:
        return re.sub(sr.replace_regex, _sr_repl_escape(sr.replacement), value)
    except Exception:
        return value.replace(sr.replace_regex, sr.replacement)


def _sr_repl_escape(repl):
    """真机 replacement 走 Java 正则分组引用 $N；Python 侧需转成 \\N。"""
    return re.sub(r"\$(\d{1,2})", r"\\\1", repl)


def _split_source_rule(rule):
    """对齐 splitSourceRule(源码 965-1065): 按 JS_PATTERN 切段，每段 trim，JS 段标 mode=js。"""
    s = str(rule or "")
    segs = []
    pos = 0
    for m in _JS_MARKER_RE.finditer(s):
        if m.start() > pos:
            seg = s[pos:m.start()].strip()
            if seg:
                segs.append((seg, None))
        code = m.group(1) if m.group(1) is not None else m.group(2)
        segs.append((code, "js"))
        pos = m.end()
    tail = s[pos:].strip()
    if tail:
        segs.append((tail, None))
    return segs


def _sr_to_text(v):
    # 源码 AnalyzeByJSoup.java:471-484 getString: 单值直接返回, 多值用 "\n"(StrPool.LF) 拼接
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(_sr_to_text(x) for x in v)
    return str(v)


def _sr_eval_seg(sr, cur, ctx):
    """按 mode 把一段交给对应引擎（mode 由 SourceRule 按源码 1625-1708 判定，不靠猜）。"""
    if sr.mode == "js":
        if not sr.rule:
            # 空 JS 段(e.g. `...href@js:##正则##替换###` 拆 ## 后代码为空):
            # 真机保留上一段结果(事实依据: 笔迷读 coverUrl 实测与详情页 og:image 完全相同)
            return cur
        # 真机 result = 上一段结果且已按 "\n" 拼接成字符串(AnalyzeByJSoup:471-484);
        # 直接传 list 会让 JS 的 String(result) 变成逗号连接的一整行, split('\n') 失效 → 取空
        return _eval_js(sr.rule, _sr_to_text(cur), ctx.get("vars"),
                        src=ctx.get("raw_text", ""))
    if sr.mode == "regex":
        # makeUpRule 的"组装分支"(存在 $N/{{}}/@get 类型的 param) 产出的就是最终字面量:
        # 源码 1782-1807 组装后 rule 已是拼接结果; 真机调试面板(用户实测截图)显示 intro/模板类
        # 规则返回的就是该文本。非组装型正则(如 `:` 前缀纯正则)才交给正则引擎。
        if any(t != _SR_DEFAULT_TYPE for t in sr.rule_type):
            return sr.rule
        if not sr.rule:
            return ""
        return _eval_seg(sr.rule, ctx, mode="regex")
    if sr.mode in ("default", "jsoup", "xpath", "jsonpath"):
        # 组合规则(&&/||/%%)在引擎内部拆分: 三引擎 getStringList/getElements 语义一致
        # (各段同根并行 -> && concat / || 首个非空 / %% 列优先交错)
        return _eval_combo(sr.rule, ctx)
    return _eval_seg(sr.rule, ctx, mode=sr.mode)


def _sr_get_string(rule, ctx, obj=None):
    """对齐 AnalyzeRule.getString(源码 590-625) 的段级循环，返回字符串。"""
    cur = obj if obj is not None else ctx.get("raw_text", "")
    for seg, mode in _split_source_rule(rule):
        sr = _SRule(seg, mode)
        sr.make_up_rule(cur, ctx)
        if cur is None:
            break
        cur = _sr_eval_seg(sr, cur, ctx)
        if sr.replace_regex:
            cur = _sr_apply_replace(_sr_to_text(cur), sr)
    return _sr_to_text(cur)


_INLINE_RULE_RE = re.compile(r"\{\{@@([\w\W]*?)\}\}")


def _expand_pattern(rule, ctx, depth=0):
    """真机 evalPattern: 展开 {{@@规则}}(先求值) 再 {{变量}} 替换。"""
    def _repl(m):
        try:
            res = _eval_combined(m.group(1), ctx, depth + 1)
        except Exception:  # noqa
            res = []
        return res[0] if res else ""
    s = _INLINE_RULE_RE.sub(_repl, str(rule))
    return _substitute_vars(s, ctx.get("vars"))


def _expand_inline_rules(text, ctx):
    """把字面量里的 {{@@规则}} 展开为对该规则的求值结果(对齐真机: 模板内嵌规则会先求值再拼接)。
    内嵌规则自身可含 ## 替换(e.g. {{@@[property="update_time"]@content##\\s##🔸}})。"""
    s = str(text)
    if "{{@@" not in s:
        return s

    def _repl(m):
        inner = m.group(1)
        try:
            res = _eval_combined(inner, ctx)
        except Exception:  # noqa
            res = []
        return res[0] if res else ""

    return _INLINE_RULE_RE.sub(_repl, s)


def _substitute_vars(rule, vars_map):
    """替换 {{var}}。vars_map 提供 bookUrl/baseUrl/key/page/ruleFindUrl/@put 等。"""
    if not vars_map:
        return rule
    def _repl(m):
        name = m.group(1).strip()
        if name in vars_map and vars_map[name] is not None:
            return str(vars_map[name])
        return m.group(0)
    return _VAR_RE.sub(_repl, rule)


def _js_eval_script_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "booksource_lint_assets", "js_eval.js")


def _eval_js(code, result, vars_map, src=None, list_mode=False):
    """用 node 执行 <js> 片段, 对齐 App 的 Rhino evalJS。
    真机绑定(AnalyzeRule.smali:2427/2502 实证): result=上一段结果(多值 "\\n" 拼接的字符串),
    src=AnalyzeRule.content(整页源码), 另有 java/source/baseUrl/book/cookie/cache 等。
    注入绑定: java(桩) / result / src / baseUrl / bookUrl / 变量 / Packages.org.jsoup(Rhino Java桥)。
    返回字符串(异常则以 <<JS_ERROR:..>> 标记)。
    list_mode=True: JS 返回数组时以 JSON 数组整体回传(真机 getElements 对 NativeArray
    按 List 逐元素取, 不按行拆)。"""
    try:
        script = _js_eval_script_path()
        payload = json.dumps({"code": code, "result": result or "",
                              "src": src or "", "vars": vars_map or {},
                              "list_mode": bool(list_mode)},
                             ensure_ascii=False)
        r = subprocess.run(["node", "--openssl-legacy-provider", script], input=payload,
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            tail = [l for l in r.stderr.strip().splitlines() if l.strip()][-1:]
            return "<<JS_ERROR:%s>>" % (tail[0] if tail else "node 异常")
        out = r.stdout.strip()
        return out if out != "" else ""
    except Exception as e:  # noqa
        return "<<JS_ERROR:%s>>" % e


def _regex_engine(content, rule):
    """正则引擎 + && 顺序链式, 对齐 AnalyzeByRegex.getElements。
    ':regex(...)' 前缀(APK 真机写法)剥离; 每段按 find() 顺序链式, 取分组结果。"""
    parts = rule.split("&&")
    res = content
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 剥离 :regex(...) 前缀; 也兼容裸 : 前缀
        if p.startswith(":regex(") and p.endswith(")"):
            p = p[len(":regex("):-1]
        elif p.startswith(":"):
            p = p[1:]
        try:
            mm = re.search(p, res, re.S)
        except Exception:
            return []
        if not mm:
            return []
        if mm.groups():
            res = mm.group(1) if mm.group(1) is not None else mm.group(0)
        else:
            res = mm.group(0)
    return [res]


def _apply_replace(items, parts):
    """parts[1:] 为 (replaceRegex, replacement) 成对。对每个 item 做替换(全替换)。
    Java Matcher 的 $1 反引用转成 Python 的 \\1。"""
    if len(parts) < 3:
        return items
    out = list(items)
    i = 1
    while i + 1 < len(parts):
        regex = parts[i]
        # Java Matcher 的 $1 组引用转成 Python \1；字面 $ 保留(不做全量转换)
        repl = re.sub(r"\$(\d)", r"\\\1", parts[i + 1])
        new = []
        for it in out:
            try:
                new.append(re.sub(regex, repl, it, flags=re.S))
            except Exception:
                new.append(it)
        out = new
        i += 2
    return out


def _resolve_next_urls(results, base_url):
    """对齐真机 AnalyzeRule.getStringList 收尾语义（AnalyzeRule.smali cond_e/cond_f）:
      1) 结果若是字符串 → 按 \\n 拆成多行(cond_e)
      2) 每行做绝对 URL 解析（utils/n1.smali n1.b: 首尾去空白; javascript:* → 丢弃;
         new URL(base, spec) 失败 → 保留原串），非空且未重复才收（保序去重）
    nextTocUrl/nextContentUrl 均走此语义，真机会把得到的**全部** URL 并发抓取。"""
    out = []
    for item in results or []:
        for line in str(item).split("\n"):
            s = line.strip()
            if not s:
                continue
            if s.lower().startswith("javascript"):
                continue
            try:
                r = urljoin(base_url, s)
            except Exception:
                r = s
            if r and r not in out:
                out.append(r)
    return out


def _make_ctx(page_file, json_file, jar_dir, charset, raw_text=None,
              vars_map=None, mode="text"):
    if raw_text is None:
        try:
            with open(page_file, encoding=charset, errors="replace") as f:
                raw_text = f.read()
        except Exception:
            raw_text = ""
    return {"page_file": page_file, "json_file": json_file, "jar_dir": jar_dir,
            "charset": charset, "raw_text": raw_text, "vars": vars_map or {},
            "mode": mode}


def _eval_combined(rule, ctx, _depth=0):
    """对齐 AnalyzeRule.getString 的真机顺序:
      1) evalPattern: 先展开 {{...}}(变量 + {{@@规则}} 内嵌求值) 与 @get:{} 组装
      2) makeUpRule: 再拆 ##(确定 main / replaceRegex / replacement)
      3) splitSourceRule: 对 main 切 <js>/@js:
      4) 引擎取值, **之后**才应用替换
    顺序很关键:
      - 若先切 @js:, `...href@js:##正则##替换###` 会把 `##正则...` 误当 JS 代码(语法错)
      - 若先拆 ##, intro 模板里 `{{@@规则##a##b}}` 的内层 ## 会被外层误拆(真机内层已先求值)
    变量 {{var}} 的判定与替换在 evalPattern 内按原始规则操作符进行,
    避免把 URL 等含 ':' 的字面量误判为正则。返回结果字符串列表。"""
    rule = str(rule)
    # 真机 SourceRule.init 判定 mode 在 evalPattern 之前 -> kind 必须基于**原始规则**
    # (否则 `🔔 更新时间：{{@@...}}` 展开后变纯文本, 会被误判成 CSS 选择器走 Jsoup)
    kind0 = _rule_kind(rule)
    if "{{" in rule and _depth < 3:
        rule = _expand_pattern(rule, ctx, _depth)   # 1) evalPattern(变量 + {{@@规则}})
    parts = rule.split(_REPLACE_SEP)                # 2) makeUpRule 拆 ##
    main = parts[0]
    results = []
    if not main.strip():
        # 对齐真机 AnalyzeRule.smali cond_a: 空规则体跳过引擎提取、保留当前内容
        # (整页源码)。`##regex##$1` 这类纯正则替换规则由此拿到整页再替换。
        results = _eval_plain(main, ctx, kind0)
    pos = 0
    for m in _JS_MARKER_RE.finditer(main):
        plain = main[pos:m.start()]
        if plain:
            results.extend(_eval_plain(plain, ctx, kind0))
        code = m.group(1) if m.group(1) is not None else m.group(2)
        code = _substitute_vars(code, ctx.get("vars"))
        if not str(code).strip():
            # 空 JS 段(e.g. `...href@js:##正则##替换`): 真机不产生新结果, 保留已累积值
            pos = m.end()
            continue
        cur = "".join(results) if results else ctx.get("raw_text", "")
        results = [_eval_js(code, cur, ctx.get("vars"))]
        pos = m.end()
    tail = main[pos:]
    if tail:
        results.extend(_eval_plain(tail, ctx, kind0))
    results = [r for r in results if r is not None]
    if len(parts) >= 2:
        # 真机 makeUpRule: size()>1 即设 replaceRegex=parts[1], replacement 缺省为空串(删除模式)
        rep_parts = [main] + [_substitute_vars(p, ctx.get("vars")) for p in parts[1:]]
        if len(rep_parts) < 3:
            rep_parts = rep_parts + [""] * (3 - len(rep_parts))
        results = _apply_replace(results, rep_parts)
    return results


def _eval_plain(seg, ctx, kind=None):
    """一段规则(不含 <js>/@js:)。kind 为整条原始规则的 Mode(由调用方按原始规则判定)。
    注: ## 的拆分已上移到 _eval_combined —— 对齐真机 makeUpRule 的**顺序**:
    先对整条规则拆 ##(确定 main/replaceRegex/replacement), 再对 main 做
    splitSourceRule(切 <js>/@js:)。顺序颠倒会把 `...href@js:##正则##替换###`
    里的 `##正则...` 误当 JS 代码执行(真机此处是空 JS 段 + 正则替换)。"""
    seg = str(seg)
    main = seg.strip()
    if not main:
        # 真机对空 rule 跳过引擎提取、返回当前内容本身(AnalyzeRule.smali cond_a)
        base = ctx.get("raw_text", "")
        return [_substitute_vars(base, ctx.get("vars"))] if base else []
    if kind == "literal":
        # 真机 Regex 组装分支: 组装后的字面量直接返回(不再当选择器)
        return [main]
    return _eval_combo(main, ctx)


def _eval_combo(main, ctx):
    """组合规则求值(对齐三引擎同名逻辑, 非链式!):
    splitRule("&&","||","%%") 括号/引号感知切分 -> 每段从**同一根元素**求值 ->
    &&: 各非空段结果 concat; ||: 首个非空段即停; %%: 列优先交错(ragged zip)。
    括号不平衡(真机抛 Error)时按单段交给引擎自行报语法错。"""
    etype, segs = _split_combination(main)
    if etype is None:
        return _eval_seg(main, ctx)
    results = []
    for seg in segs:
        seg = seg.strip()
        if not seg:
            continue
        items = _eval_seg(seg, ctx)
        if items:
            results.append(items)
            if etype == "||":
                break
    return _merge_combo(results, etype)


def _merge_combo(results, etype):
    """组合结果合并(对齐三引擎一致语义): && concat / || 单结果 / %% 列优先交错。"""
    if not results:
        return []
    if etype == "%%":
        out = []
        for i in range(len(results[0])):
            for lst in results:
                if i < len(lst):
                    out.append(lst[i])
        return out
    out = []
    for lst in results:
        out.extend(lst)
    return out


def _eval_seg(seg, ctx, mode=None):
    """单个规则段(不含 ##/JS): 按 mode 派发引擎, 均从 ctx 指定的同一根求值。
    mode 由调用方(_SRule)按源码 1625-1708 的前缀规则判定; Default 模式交由
    _rule_kind 继续判(真机 Jsoup 引擎内部还有一层 SourceRule)。"""
    seg = str(seg).strip()
    vars_map = ctx.get("vars")
    if not seg:
        base = ctx.get("raw_text", "")
        return [_substitute_vars(base, vars_map)] if base else []
    kind = mode if (mode and mode != "default") else _rule_kind(seg)
    main_sub = _substitute_vars(seg, vars_map)
    if kind == "js":
        return [_eval_js(main_sub, ctx.get("raw_text", ""), vars_map)]
    if kind == "literal":
        # 真机 Mode.Regex 组装分支: 返回组装后的字面量, 不做选择;
        # 其中 {{@@规则}} 是内嵌规则求值(真机调试面板显示的是求值后的结果, 非模板原文)
        return [_expand_inline_rules(main_sub, ctx)]
    if kind == "jsonpath":
        # 真机 Json 引擎对传入内容直接 parse；元素级(item 为 JSON 字符串)时
        # page_file 即 item 全文，同样可解析 —— 不能只认 json_file。
        src_file = ctx.get("json_file") or ctx.get("page_file")
        if not src_file or not os.path.isfile(src_file):
            return []
        try:
            with open(src_file, encoding=ctx["charset"], errors="replace") as f:
                data = json.load(f)
            return _jp_find(main_sub, data)
        except Exception:
            return []
    if kind == "xpath":
        pf = ctx.get("page_file")
        if not pf or not os.path.isfile(pf):
            return []
        ok, out = _run_xpath(pf, _strip_xpath_prefix(main_sub))
        return out if ok else []
    if kind == "regex":
        return _regex_engine(ctx.get("raw_text", ""), main_sub)
    # jsoup(真机 Default 模式)
    if not ctx.get("jar_dir"):
        return []
    ok, out = _run_jsoup(ctx["jar_dir"], ctx["page_file"], main_sub,
                         mode=ctx.get("mode", "text"))
    return out if ok else []


def dynamic_check(src, raw, rep, samples):
    html = samples.get("html")
    s_html = samples.get("search_html")
    bi_html = samples.get("bookinfo_html")
    toc_html = samples.get("toc_html")
    con_html = samples.get("content_html")
    js_json = samples.get("json")

    jar, jar_dir = _find_jsoup_jar(os.path.dirname(os.path.abspath(__file__)))

    region_html = {
        "ruleSearch": s_html or html,
        "ruleExplore": s_html or html,
        "ruleBookInfo": bi_html or html,
        "ruleToc": toc_html or html,
        "ruleContent": con_html or html,
    }

    lxml_ok = True
    try:
        import lxml.etree  # noqa
    except Exception:
        lxml_ok = False

    jsonpath_ok = _HAVE_JAYWAY  # jayway 同构引擎纯 Python 无外部依赖，始终可用
    xpath_ok = _find_xpath_jar(os.path.dirname(os.path.abspath(__file__))) is not None

    if not (html or s_html or bi_html or toc_html or con_html or js_json):
        # 无样本: 仅做语法编译校验
        rep.info("DYN-SKIP", "无页面/JSON 样本，动态模式只做规则语法编译校验（给 --html/--json 可做实跑）")
        _dynamic_syntax_only(src, raw, rep, lxml_ok, jsonpath_ok, jar, jar_dir)
        return

    # 非解析规则字段(URL 模板/JS 代码): 真机不经过 AnalyzeRule, 动态检查跳过
    SKIP_FIELDS = {"tocUrl", "nextTocUrl", "nextContentUrl", "searchUrl",
                   "exploreUrl", "ruleFindUrl", "webJs", "preUpdateJs",
                   "formatJs", "loginCheckJs"}

    for region, fld, val in _iter_region_rules(src):
        rule = str(val)
        if not rule or rule.strip() in ("", "##"):
            continue
        if fld in SKIP_FIELDS:
            continue
        rule = _strip_inline_options(rule)      # a@href,{"webView":true} -> a@href
        rule = _strip_js_blocks(rule)           # <js>/@js: 段由静态语法检查覆盖
        if not rule.strip():
            continue
        page = region_html.get(region)
        parts = rule.split("##")          # 真机 makeUpRule: 主段交引擎, 替换在取值后应用
        main = parts[0].strip()
        if not main:
            continue
        etype0, _s0 = _split_combination(main)
        if etype0 is not None:
            if not page:
                continue
            _dyn_combined(page, js_json, jar_dir, main, region, fld, raw, rep, parts, charset=src.get("charset") or "utf-8")
            continue
        kind0 = _rule_kind(main)
        if kind0 in ("literal", "js"):
            # 字面量模板(URL/纯文本/{{var}}) 或纯 JS 段: 非选择器, 真机返回字面量本身
            continue
        if kind0 == "jsonpath":
            if not js_json:
                continue
            if not jsonpath_ok:
                rep.info("DYN-JP-SKIP", "`%s.%s` 是 JSONPath 但 jayway 兼容引擎不可用，跳过动态" % (region, fld))
                continue
            _dyn_jsonpath(js_json, main, region, fld, raw, rep, parts)
        else:
            if not page:
                continue
            if kind0 == "xpath":
                if not xpath_ok and not lxml_ok:
                    rep.info("DYN-XP-SKIP", "`%s.%s` 是 XPath 但缺真机引擎且缺 lxml，跳过" % (region, fld))
                    continue
                _dyn_xpath(page, main, region, fld, raw, rep, parts)
            elif kind0 == "regex":
                _dyn_regex(page, main, region, fld, raw, rep, parts, charset=src.get("charset") or "utf-8")
            else:  # jsoup
                if not jar:
                    rep.info("DYN-JSOP-SKIP",
                             "`%s.%s` 是 Jsoup 规则但找不到 jsoup jar，跳过实跑（仅静态已查）" % (region, fld))
                    continue
                _dyn_jsoup(jar_dir, page, main, region, fld, raw, rep, parts)


def _dynamic_syntax_only(src, raw, rep, lxml_ok, jsonpath_ok, jar, jar_dir):
    """无样本时, 仅编译校验规则语法能否被引擎接受。"""
    SKIP_FIELDS = {"tocUrl", "nextTocUrl", "nextContentUrl", "searchUrl",
                   "exploreUrl", "ruleFindUrl", "webJs", "preUpdateJs",
                   "formatJs", "loginCheckJs"}
    for region, fld, val in _iter_region_rules(src):
        rule = str(val).strip()
        if not rule or rule in ("##",):
            continue
        if fld in SKIP_FIELDS:
            continue
        rule = _strip_inline_options(rule)
        rule = _strip_js_blocks(rule)
        if not rule:
            continue
        _et, segs0 = _split_combination(rule)
        segs = [p.strip() for p in segs0 if p.strip()] if _et else [rule]
        for seg in segs:
            seg_main = seg.split("##")[0].strip()
            if not seg_main:
                continue
            skind = _rule_kind(seg_main)
            if skind in ("literal", "js", "regex"):
                if skind == "regex":
                    # 正则段: 仅编译校验(剥离 :/:regex( 前缀)
                    pat = seg_main[1:] if seg_main.startswith(":") else seg_main
                    if pat.startswith("regex(") and pat.endswith(")"):
                        pat = pat[6:-1]
                    try:
                        re.compile(pat)
                    except re.error as e:
                        line = locate_line(raw, fld, seg_main[:40])
                        rep.error("DYN-REGEX-SYN", "`%s.%s` 正则无法编译: %s" % (region, fld, e),
                                  "修正正则语法（行 ~%d）" % line)
                continue
            if skind == "xpath":
                ok, err = _run_xpath_compile(_strip_xpath_prefix(seg_main))
                if not ok:
                    line = locate_line(raw, fld, seg_main[:40])
                    rep.error("DYN-XPATH-SYN", "`%s.%s` XPath 语法引擎不接受: %s" % (region, fld, err),
                              "修正 XPath 语法（行 ~%d）" % line)
            elif skind == "jsonpath" and jsonpath_ok:
                try:
                    _jp_compile(seg_main)
                except Exception as e:  # noqa
                    line = locate_line(raw, fld, seg_main[:40])
                    rep.error("DYN-JP-SYN", "`%s.%s` JSONPath 语法引擎不接受: %s" % (region, fld, e),
                              "修正 JSONPath 语法（行 ~%d）" % line)
            elif skind == "jsoup" and jar:
                # 用极小文档探语法是否抛异常
                with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
                    tf.write("<html><body><div class='x'>a</div></body></html>")
                    tmp = tf.name
                try:
                    ok, err = _run_jsoup(jar_dir, tmp, seg_main)
                finally:
                    os.unlink(tmp)
                if not ok:
                    line = locate_line(raw, fld, seg_main[:40])
                    rep.error("DYN-JSOP-SYN", "`%s.%s` Jsoup 规则语法引擎不接受: %s" % (region, fld, err),
                              "修正 Jsoup 规则语法（行 ~%d）" % line)


def _dyn_xpath(page, rule, region, fld, raw, rep, parts=None):
    ok, res = _run_xpath(page, _strip_xpath_prefix(rule))
    if not ok:
        line = locate_line(raw, fld, rule[:40])
        rep.error("DYN-XPATH-SYN", "`%s.%s` XPath 语法引擎不接受: %s" % (region, fld, res),
                  "修正 XPath 语法（行 ~%d）" % line)
        return
    res = _dyn_apply(res, parts) if parts else res
    if not res:
        line = locate_line(raw, fld, rule[:40])
        rep.warn("DYN-XPATH-EMPTY", "`%s.%s` 在样本页 XPath 命中 0 条%s（可能语法合法但无匹配）"
                 % (region, fld, "(替换后)" if parts and len(parts) > 1 and parts[1] else ""),
                 "核对样本页结构与 ## 替换段（行 ~%d）" % line)
    else:
        _dyn_hit(region, fld, raw, rep, res, elem=(fld in ("bookList", "chapterList")))


def _dyn_regex(page, rule, region, fld, raw, rep, parts=None, charset="utf-8"):
    """纯正则规则(以 ':' 前缀, 真机 splitSourceRule 判 Regex 模式)。"""
    text = ""
    try:
        with open(page, encoding=charset, errors="replace") as f:
            text = f.read()
    except Exception:
        pass
    pat = rule.split("##")[0].strip()
    inner = pat[1:] if pat.startswith(":") else pat
    if inner.startswith("regex(") and inner.endswith(")"):
        inner = inner[6:-1]
    try:
        re.compile(inner)
    except re.error as e:
        line = locate_line(raw, fld, rule[:40])
        rep.error("DYN-REGEX-SYN", "`%s.%s` 正则无法编译: %s" % (region, fld, e),
                  "修正正则语法（行 ~%d）" % line)
        return
    res = _regex_engine(text, rule)
    res = _dyn_apply(res, parts) if parts else res
    if not res:
        line = locate_line(raw, fld, rule[:40])
        rep.warn("DYN-REGEX-EMPTY", "`%s.%s` 在样本页正则命中 0 条%s（可能语法合法但无匹配）"
                 % (region, fld, "(替换后)" if parts and len(parts) > 1 and parts[1] else ""),
                 "核对样本页结构与 ## 替换段（行 ~%d）" % line)
    else:
        _dyn_hit(region, fld, raw, rep, res, elem=(fld in ("bookList", "chapterList")))


def _dyn_combined(page, js_json, jar_dir, rule, region, fld, raw, rep, parts=None, charset="utf-8"):
    """组合规则(&&/||/%%)动态检查, 对齐真机三引擎同根并行语义:
    括号/引号感知切分 -> 每段从同一根求值 -> 按 elementsType 合并
    (&& concat / || 首个非空 / %% 列优先交错) -> 仅合并结果为空才告警
    (|| 语义下首段空、后段命中属正常)。bookList/chapterList 按元素级
    (mode=elem, 真机 getElements)评估, 其余字段按字符串级。
    rule 已去掉 ## 后缀(替换在合并后经 _dyn_apply 应用, 对齐 makeUpRule)。"""
    main = rule
    rev = main.startswith("-")
    if rev:
        main = main[1:]
    etype, segs = _split_combination(main)
    if etype is None:
        segs = [main]
    elem = fld in ("bookList", "chapterList")
    results = []
    for seg in segs:
        seg = seg.strip()
        if not seg:
            continue
        seg_main = seg.split("##")[0].strip()
        kind = _rule_kind(seg_main)
        if kind == "literal":
            continue  # 组装配字面量段: 真机返回字面量本身, 无命中判定
        res, err, code = _dyn_seg_eval(page, js_json, jar_dir, seg, kind, elem, charset=charset)
        if err:
            line = locate_line(raw, fld, seg_main[:40])
            rep.error(code, "`%s.%s` %s" % (region, fld, err),
                      "修正规则语法（行 ~%d）" % line)
            return
        if res:
            results.append(res)
            if etype == "||":
                break
    merged = _merge_combo(results, etype) if etype else (results[0] if results else [])
    if rev:
        merged = list(reversed(merged))
    if parts:
        merged = _dyn_apply(merged, parts)
    if not merged:
        _dyn_empty(region, fld, raw, rep,
                   "DYN-COMBO-EMPTY", "组合规则(%s)%s" % (
                       etype or "单段",
                       "(替换后)" if parts and len(parts) > 1 and parts[1] else ""))
    else:
        _dyn_hit(region, fld, raw, rep, merged, elem=elem)


def _dyn_seg_eval(page, js_json, jar_dir, seg, kind, elem, charset="utf-8"):
    """组合规则单段求值。返回 (results, error_msg, error_code)。"""
    try:
        if kind == "jsonpath":
            if not js_json:
                return [], None, None
            with open(js_json, encoding="utf-8") as f:
                data = json.load(f)
            return (_jp_find(seg, data), None, None)
        if kind == "xpath":
            import lxml.etree
            tree = lxml.etree.parse(page, lxml.etree.HTMLParser(encoding="utf-8"))
            res = tree.xpath(_strip_xpath_prefix(seg))
            if elem:
                out = [r if isinstance(r, str) else lxml.etree.tostring(
                    r, encoding="unicode", method="html") for r in res]
            else:
                out = []
                for r in res:
                    if isinstance(r, str):
                        out.append(r)
                    elif hasattr(r, "itertext"):
                        out.append("".join(r.itertext()).strip())
                    else:
                        out.append(str(r))
            return out, None, None
        if kind == "regex":
            with open(page, encoding=charset, errors="replace") as f:
                text = f.read()
            return _regex_engine(text, seg), None, None
        # jsoup
        if not jar_dir:
            return [], None, None
        ok, out = _run_jsoup(jar_dir, page, seg, mode=("elem" if elem else "text"))
        if not ok:
            return [], str(out), "DYN-JSOP-SYN"
        return out, None, None
    except Exception as e:  # noqa
        code = {"jsonpath": "DYN-JP-SYN", "xpath": "DYN-XPATH-SYN"}.get(kind, "DYN-REGEX-SYN")
        return [], str(e), code


def _dyn_apply(items, parts):
    """应用 ## 替换段(对齐真机 makeUpRule: 引擎取值之后对结果逐项应用 replaceRegex)。"""
    if not items or len(parts) < 2 or not parts[1]:
        return items
    return _apply_replace(items, [parts[0], parts[1], parts[2] if len(parts) > 2 else ""])


def _dyn_hit(region, fld, raw, rep, items, elem=False):
    """命中上报(对齐 App 调试面板: 每字段显示取到的条数与样例)。"""
    line = locate_line(raw, fld, "")
    sample = " | ".join(x[:60].replace("\n", " ") for x in items[:3]) if items else "（空）"
    rep.info("DYN-HIT", "`%s.%s` 命中 %d 条%s, 样例: %s"
             % (region, fld, len(items), "（元素）" if elem else "", sample),
             "规则在样本页验证通过（行 ~%d）" % line)


def _dyn_empty(region, fld, raw, rep, code, engine):
    line = locate_line(raw, fld, "")
    rep.warn(code, "`%s.%s` 在样本页 %s 命中 0 条（可能语法合法但无匹配）"
             % (region, fld, engine), "核对样本页结构与该规则各段（行 ~%d）" % line)


def _dyn_jsoup(jar_dir, page, rule, region, fld, raw, rep, parts=None):
    elem = fld in ("bookList", "chapterList")
    ok, out = _run_jsoup(jar_dir, page, rule, mode=("elem" if elem else "text"))
    if not ok:
        line = locate_line(raw, fld, rule[:40])
        rep.error("DYN-JSOP-SYN", "`%s.%s` Jsoup 规则语法引擎不接受: %s" % (region, fld, out),
                  "修正 Jsoup 规则语法（行 ~%d）" % line)
        return
    # out 是 base64 行, 空 = 无命中
    if parts and len(parts) > 1 and parts[1]:
        out = _dyn_apply(out, parts)
    if not out:
        line = locate_line(raw, fld, rule[:40])
        rep.warn("DYN-JSOP-EMPTY", "`%s.%s` 在样本页 Jsoup 命中 0 条%s（可能语法合法但无匹配）"
                 % (region, fld, "(替换后)" if parts and len(parts) > 1 and parts[1] else ""),
                 "核对样本页结构与 ## 替换段（行 ~%d）" % line)
    else:
        _dyn_hit(region, fld, raw, rep, out, elem=(fld in ("bookList", "chapterList")))


def _dyn_jsonpath(js_json, rule, region, fld, raw, rep, parts=None):
    try:
        with open(js_json, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa
        line = locate_line(raw, fld, rule[:40])
        rep.error("DYN-JP-SYN", "`%s.%s` 样本 JSON 读取失败: %s" % (region, fld, e),
                  "检查样本 JSON 文件（行 ~%d）" % line)
        return
    # 语法预校验（对齐真机：jayway 不接受的语法真机亦不接受）；组合符/内联块属 Legado 语法，已剥离
    try:
        _jp_compile(rule)
    except Exception as e:  # noqa
        line = locate_line(raw, fld, rule[:40])
        rep.error("DYN-JP-SYN", "`%s.%s` JSONPath 语法引擎不接受: %s" % (region, fld, e),
                  "修正 JSONPath 语法（行 ~%d）" % line)
        return
    res = _jp_find(rule, data)
    if parts:
        res = _dyn_apply(res, parts)
    if not res:
        line = locate_line(raw, fld, rule[:40])
        rep.warn("DYN-JP-EMPTY", "`%s.%s` 在样本 JSON 命中 0 条%s"
                 % (region, fld, "(替换后)" if parts and len(parts) > 1 and parts[1] else ""),
                 "核对 JSON 结构与 ## 替换段（行 ~%d）" % line)
    else:
        _dyn_hit(region, fld, raw, rep, res, elem=(fld in ("bookList", "chapterList")))


# ----------------------------------------------------------------------------
# 6.5 真实抓取层 + 全链路 Live 调试（对齐 App「书源调试」逐页验证）
# ----------------------------------------------------------------------------
_SESSION = requests.Session()  # 持有 cookie（enabledCookieJar 时跨请求保持）


def _source_headers(src):
    h = {"User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"}
    # 对象形式 headers
    hd = src.get("headers")
    if isinstance(hd, dict):
        for k, v in hd.items():
            h[str(k)] = str(v)
    # 字符串形式 header (Legado 标准字段): ① JSON 对象(真机 Gson 解析成 Map, 标准形态)
    # ② 回退每行 Key=Value。必须先试 JSON —— 否则单行 JSON 里 "q=0.9" 的 `=` 会把
    #    整行拆成非法 header 名(requests 抛 Invalid ... in header name)。
    hs = src.get("header")
    if isinstance(hs, str) and hs.strip():
        s = hs.strip()
        parsed = False
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        h[str(k)] = str(v)
                    parsed = True
            except (ValueError, TypeError):
                pass
        if not parsed:
            for line in s.splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                h[k.strip()] = v.strip()
    return h


_CHARSET_ALIAS = {
    "gbk": "gb18030", "gb2312": "gb18030", "gb18030": "gb18030",
    "big5": "big5", "utf-8": "utf-8", "utf8": "utf-8",
}


def _detect_html_charset(raw, maxlen=8192):
    """对齐真机 okhttp/jsoup: 从 HTML 的 <meta charset> / Content-Type 自动识别编码。
    国内小说站大量 GBK 页面不声明 HTTP charset，靠 meta 识别（否则整页乱码）。
    返回 Python codec 名，识别不出返回 None。"""
    try:
        head = raw[:maxlen]
        m = re.search(rb'<meta[^>]+charset\s*=\s*["\']?\s*([\w-]+)', head, re.I)
        if not m:
            m = re.search(rb'charset=["\']?\s*([\w-]+)', head, re.I)
        if m:
            name = m.group(1).decode("ascii", "ignore").lower()
            return _CHARSET_ALIAS.get(name, name)
    except Exception:
        pass
    return None


def fetch(url, src, method="GET", body=None, referer=None, timeout=25, charset=None):
    """按书源配置真实发请求，返回 (text, final_url, error)。"""
    headers = _source_headers(src)
    if referer:
        headers["Referer"] = referer
    # charset: options.charset 优先(GBK 源等)，其次书源级；无则按 HTML meta 自动检测(对齐真机 okhttp)
    if not charset:
        charset = src.get("charset") or "utf-8"
    # 真机 AnalyzeUrl.getByteArrayIfDataUri: data: URI 内联 base64 解码, 不发 HTTP 请求。
    # 正则 t6/i:123 = "data:.*?;base64,(.*)" 匹配 urlNoQuery(去 query), Base64.decode(flags=0)。
    _dm = re.match(r'data:.*?;base64,(.*)', str(url).split('?')[0], re.I)
    if _dm:
        try:
            _dbody = base64.b64decode(_dm.group(1), validate=False)
            _denc = _CHARSET_ALIAS.get((charset or "utf-8").lower(),
                                       charset or "utf-8")
            return _dbody.decode(_denc, "replace"), url, None
        except Exception as e:  # noqa
            return None, url, "data: URI 解码失败: %s" % e
    try:
        if str(method).upper() == "POST":
            if body is not None and not any(k.lower() == "content-type" for k in headers):
                # 对齐 App：Legado 对 body 默认按表单提交，requests 传 str 不会自动带该头
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = _SESSION.post(url, data=body, headers=headers, timeout=timeout)
        else:
            r = _SESSION.get(url, headers=headers, timeout=timeout)
        # 真机 okhttp 对无 charset 声明的响应按 HTML meta 检测编码(否则 GBK 站会乱码)
        enc = _detect_html_charset(r.content) or charset
        try:
            r.encoding = enc
        except Exception:
            r.encoding = charset
        return r.text, r.url, None
    except Exception as e:  # noqa
        return None, url, str(e)


# ---- loginCheckJs 模拟执行（对齐 AnalyzeUrl.evalJS + okhttp cookieJar） ----
def _js_asset(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "booksource_lint_assets", name)


def _session_cookie_str(base_url):
    """从 requests.Session 取出匹配域名(host)的 cookie 字符串，传给 node 侧。
    base_url 可为完整 URL 或域名；内部用 urlparse 取 hostname 匹配。"""
    from urllib.parse import urlparse
    domain = (urlparse(base_url).hostname or "") if base_url else ""
    out = []
    for c in _SESSION.cookies:
        d = (c.domain or "").lstrip(".")
        if not domain or d == domain or d.endswith(domain) or domain.endswith(d):
            out.append("%s=%s" % (c.name, c.value))
    return "; ".join(out)


def _merge_cookie_to_session(cookie_str, base_url):
    """把 loginCheckJs 经 node 拿到的新 cookie 合并进 requests.Session，供后续请求自动带。"""
    from urllib.parse import urlparse
    host = (urlparse(base_url).hostname or "") if base_url else ""
    for part in (cookie_str or "").split(";"):
        kv = part.strip()
        if not kv or "=" not in kv:
            continue
        name, _, val = kv.partition("=")
        try:
            _SESSION.cookies.set(name.strip(), val.strip(),
                                 domain=host if host else None)
        except Exception:
            pass


def _run_login_check(src, final_url, html, charset, rep, step_label):
    """对齐 App：每步响应后执行 loginCheckJs。
    - node 侧用 java.ajax 真发登录请求，cookie 自动进 node 内存 jar
    - 执行后把 cookie 合并进 _SESSION，后续请求自动带（覆盖大部分登录型源）
    - 返回 loginCheckJs 可能修改后的 body（无变化则 None）"""
    js = (src.get("loginCheckJs") or "").strip()
    if not js:
        return None
    base_url = src.get("bookSourceUrl") or ""
    payload = {
        "js": js,
        "response": {"url": final_url or "", "body": html or "", "header": ""},
        "baseUrl": base_url,
        "cookie": _session_cookie_str(base_url),
        "headers": _source_headers(src),
    }
    try:
        r = subprocess.run(["node", "--openssl-legacy-provider", _js_asset("login_check.js")],
                           input=json.dumps(payload, ensure_ascii=False),
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            tail = [l for l in r.stderr.strip().splitlines() if l.strip()][-1:]
            rep.warn("LIVE-LOGINCHECK", "[%s] loginCheckJs 执行异常: %s"
                     % (step_label, tail[0] if tail else "node 进程异常"))
            return None
        out = json.loads(r.stdout.strip() or "{}")
    except Exception as e:  # noqa
        rep.warn("LIVE-LOGINCHECK", "[%s] loginCheckJs 执行失败: %s" % (step_label, e))
        return None
    if out.get("error"):
        rep.warn("LIVE-LOGINCHECK", "[%s] loginCheckJs 报错: %s" % (step_label, out["error"]))
    cookie_str = out.get("cookie") or ""
    if cookie_str:
        _merge_cookie_to_session(cookie_str, base_url)
        rep.info("LIVE-LOGINCHECK", "[%s] 已执行 loginCheckJs 并写入 cookie（%d 字节）"
                 % (step_label, len(cookie_str)))
    else:
        rep.info("LIVE-LOGINCHECK", "[%s] 已执行 loginCheckJs（无新增 cookie）" % step_label)
    new_body = out.get("body")
    if isinstance(new_body, str) and new_body != (html or ""):
        return new_body
    return None


_URL_EXPR_RE = re.compile(r"\{\{(.+?)\}\}")


def _eval_url_template(text, keyword="", page=1, base_url="", charset="utf-8"):
    """对齐 AnalyzeUrl：URL/Body 里的 {{...}} 表达式求值。
    快路径覆盖常见写法（key/page/Math.random/java.encodeURI），其余走 node JS 桥
    （绑定 key/page/java/(baseUrl)）。求值失败保留原文，让后续阶段按字面量报错。
    charset: options.charset 决定 key 的 URL 编码（GBK 源按 GBK %xx，对齐真机）。"""
    def _eval_expr(expr):
        expr = expr.strip()
        if expr == "key":
            try:
                return quote(str(keyword).encode(charset, "replace"), safe="")
            except Exception:
                return quote(keyword, safe="")
        if expr in ("page", "searchPage"):
            return str(page)
        if expr == "Math.random()":
            return repr(random.random())
        m = re.fullmatch(r"java\.encodeURI\((key|page)\)", expr)
        if m:
            v = keyword if m.group(1) == "key" else str(page)
            try:
                return quote(str(v).encode(charset, "replace"), safe="")
            except Exception:
                return quote(v, safe="")
        m = re.fullmatch(r"java\.encodeURI\((.+)\)", expr)
        if m:
            inner = _eval_expr(m.group(1))
            if inner is None:
                return None
            return quote(inner, safe="")
        vars_map = {"key": keyword, "page": str(page), "searchPage": str(page),
                    "baseUrl": base_url}
        out = _eval_js(expr, "", vars_map)
        if out.startswith("<<JS_ERROR"):
            return None
        return out

    def _repl(m):
        r = _eval_expr(m.group(1))
        return m.group(0) if r is None else r

    return _URL_EXPR_RE.sub(_repl, text)


_SEARCH_JS_CACHE = {}


def build_search(src, keyword, page=1):
    """从 searchUrl 构造真实请求 (url, method, body, charset)，无搜索则回退 bookSourceUrl。
    searchUrl 支持两种 JS 写法, 均经 node 桥接执行 (java.ajax 同步 curl 带书源 headers/cookie,
    绑定 key/page/java.encodeURI), 返回 'url,{options}' 再拆出请求参数:
      - @js: 前缀
      - <js>...</js> 包裹 (App 标准写法, 如 39书屋搜索 POST API)"""
    su = src.get("searchUrl")
    if not su and isinstance(src.get("ruleSearch"), dict):
        su = src.get("ruleSearch", {}).get("searchUrl")
    if not su:
        bsu = src.get("bookSourceUrl")
        if bsu:
            return bsu, "GET", None, "utf-8"
        return None
    su = str(su).strip()
    base = src.get("bookSourceUrl", "")
    # <js>...</js> 包裹与 @js: 前缀等价: 都需经 node 桥接执行 JS (java.ajax 真实发请求),
    # 再按 "url,{行内选项}" 拆出真实 URL 与 options (对齐 App AnalyzeUrl.evalJS 对 <js> searchUrl 的处理)。
    # 否则整段 <js> 会被当 URL 字面量请求, live 搜索关验证必然失败。
    js_code = None
    m_js = re.search(r"<js>([\s\S]*?)</js>", su, re.I)
    if m_js:
        js_code = m_js.group(1)
    elif su.startswith("@js:"):
        js_code = su[4:]
    if js_code is not None:
        orig_su = str(src.get("searchUrl") or "").strip()
        ck = (orig_su, keyword, page, base)
        if ck in _SEARCH_JS_CACHE:
            return _SEARCH_JS_CACHE[ck]
        payload = {
            "js": js_code,
            "response": {"url": "", "body": "", "header": ""},
            "baseUrl": base,
            "cookie": _session_cookie_str(base) if base else "",
            "headers": _source_headers(src),
            "key": keyword, "page": page,
        }
        try:
            r = subprocess.run(["node", "--openssl-legacy-provider", _js_asset("login_check.js")],
                               input=json.dumps(payload, ensure_ascii=False),
                               capture_output=True, text=True, timeout=60)
            out = json.loads(r.stdout or "{}")
        except Exception:  # noqa
            return None
        if out.get("error"):
            return None
        ret = out.get("body") or ""
        _merge_cookie_to_session(out.get("cookie"), base)  # java.ajax 种的 cookie 并回 Session
        su = ret.strip()
        if not su:
            return None
    opts = {}
    m = re.search(r",\s*(\{.*)", su, re.S)  # options 可为 ",{" 或 ",\n{"（逗号后允许空白/换行）
    if m:
        try:
            opts = json.loads(m.group(1))
        except Exception:
            opts = {}
        su = su[:m.start()]
    q_charset = str(opts.get("charset") or src.get("charset") or "utf-8")
    try:
        # 对齐 AnalyzeUrl: options.charset 决定 URL 参数编码（GBK 源 searchkey 需 GBK %xx）
        q = quote(str(keyword).encode(q_charset, "replace"), safe="")
    except Exception:
        q = quote(keyword, safe="")
    url = _eval_url_template(su, keyword=keyword, page=page, base_url=base, charset=q_charset)
    if "{{" in url:
        # 求值失败残留的 {{...}}：退化旧快路径，保证至少 {{key}}/{{page}} 可用
        url = url.replace("{{key}}", q).replace("{{page}}", str(page))
    # searchUrl 可能为相对路径(带/或不带/)，一律以 bookSourceUrl 为基址拼绝对 URL(对齐 AnalyzeUrl)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        url = urljoin(base, url)
    method = opts.get("method", "GET")
    body = opts.get("body")
    if body:
        body = _eval_url_template(str(body), keyword=keyword, page=page, base_url=base, charset=q_charset)
        if "{{" in body:
            body = body.replace("{{key}}", q).replace("{{page}}", str(page))
    if su != str(src.get("searchUrl") or "").strip():  # @js: 求值结果进缓存（含拆好的 options）
        _SEARCH_JS_CACHE[(str(src.get("searchUrl")).strip(), keyword, page, base)] = (
            url, method, body, q_charset)
    return url, method, body, q_charset


def browser_fetch(url, src, method="GET", body=None, wait_ms=8000,
                  cookie_file=None, ua=None):
    """headless Chromium 渲染页面。可执行 JS、跟随重定向、带 UA。
    覆盖 WebView / 客户端解密 / 反爬类源（普通 requests 拿不到的）。
    返回 (html, final_url, error)。"""
    if str(method).upper() == "POST":
        return None, url, "headless 渲染暂不支持 POST 请求（反爬源若是 POST 需真机）"
    ua = ua or _source_headers(src).get("User-Agent")
    # 注意: --user-agent 必须用等号形式, 空格形式在 headless 下会被误判为多个导航 target
    cmd = ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
           "--disable-dev-shm-usage", "--virtual-time-budget=%d" % wait_ms,
           "--user-agent=%s" % ua]
    if cookie_file:
        cmd.append("--cookie-file=%s" % cookie_file)
    cmd += ["--dump-dom", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            tail = [l for l in r.stderr.strip().splitlines() if l.strip()][-1:]
            return None, url, tail[0] if tail else "chromium 异常退出"
        return r.stdout, url, None
    except Exception as e:  # noqa
        return None, url, str(e)


def _browser_warmup(src, rep):
    """对需浏览器验证的源：先访问首页让 JS 跑、写 cookie，返回 cookie 文件路径。"""
    bsu = src.get("bookSourceUrl")
    if not bsu:
        return None
    cf = tempfile.NamedTemporaryFile("w", suffix=".cookies", delete=False,
                                    dir=_TMP_DIR).name
    html, _, err = browser_fetch(bsu, src, cookie_file=cf, wait_ms=10000)
    if html is None:
        rep.info("LIVE-BROWSER", "首页预热失败: %s（继续，可能无需 cookie）" % err)
        return None
    rep.info("LIVE-BROWSER", "已用 headless Chromium 访问首页并保存 cookie（%s，%d 字节）"
             % (bsu, len(html)))
    return cf


def _eval_rule_results(rule, page_file, jar_dir, json_file=None, charset="utf-8",
                       vars_map=None):
    """对单条规则求值（含组合语义: {{}} / <js> / ## / :regex &&），
    返回 (results_list, error)。results 为空列表=无命中。"""
    rule = str(rule).strip()
    if not rule or rule == "##":
        return [], None
    ctx = _make_ctx(page_file, json_file, jar_dir, charset, vars_map=vars_map)
    try:
        # 源码同构引擎(AnalyzeRule.getString:590-625)
        val = _sr_get_string(rule, ctx)
        res = [val] if val != "" else []
    except Exception as e:  # noqa
        return None, "求值异常: %s" % e
    return res, None


def _write_tmp(html, suffix=".html"):
    # 落在统一临时目录，进程退出时统一清理(_TMP_DIR 见文件末尾 atexit)
    tf = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                     encoding="utf-8", dir=_TMP_DIR)
    tf.write(html)
    tf.close()
    return tf.name


def _live_stage(rep, stage, rule, page_file, jar_dir, json_file=None, charset="utf-8",
               limit=3, vars_map=None):
    """对单条规则求值并报告命中数与样例，返回 (results, error)。"""
    if not str(rule).strip():
        rep.warn("LIVE-SKIP", "[%s] 规则为空，跳过" % stage)
        return [], None
    res, err = _eval_rule_results(rule, page_file, jar_dir, json_file, charset, vars_map)
    if err:
        rep.error("LIVE-%s" % stage, "[%s] %s" % (stage, err))
        return None, err
    sample = " | ".join(x[:50] for x in res[:limit]) if res else "（空）"
    rep.info("LIVE-%s" % stage, "[%s] 命中 %d 条，样例: %s"
             % (stage, len(res), sample))
    return res, None


def _check_anti_bot(html, final_url, req_url, src, rep):
    """检测反爬/浏览器验证，让工具报错接近 App 的"challenge/重定向"诊断。
    返回 bool：是否建议切换到浏览器渲染模式。"""
    from urllib.parse import urlparse
    need_browser = False
    final = urlparse(final_url)
    req = urlparse(req_url)
    if final.netloc and req.netloc and final.netloc != req.netloc:
        rep.warn("LIVE-ANTI-BOT",
                 "请求被重定向到不同域名 `%s` → `%s`，疑似站点反爬/地区跳转"
                 % (req.netloc, final.netloc),
                 "该源可能需要浏览器验证或登录，工具无法替代真机")
        need_browser = True
    if html:
        low = html.lower()
        if "challenge" in low:
            rep.warn("LIVE-CHALLENGE",
                     "响应内容出现 `challenge`，站点可能要求浏览器验证",
                     "对应 loginCheckJs 里的浏览器验证路径；工具无法自动过验证")
            need_browser = True
        if "> window" in html or "script> window" in html.replace(" ", ""):
            rep.warn("LIVE-JS-CHALLENGE",
                     "响应含 JS 挑战脚本（`script> window`），站点在检测 bot",
                     "需要真机 WebView 通过验证")
            need_browser = True
        if "搜索间隔" in html or "30 秒" in html:
            rep.warn("LIVE-RATE-LIMIT",
                     "响应出现\"搜索间隔/30 秒\"，站点已限流或要求验证",
                     "降低请求频率或按 loginCheckJs 用浏览器过验证")
    lcjs = src.get("loginCheckJs") or ""
    if "startBrowser" in lcjs or "java.connect" in lcjs:
        rep.info("LIVE-BROWSER-REQ",
                 "该书源 loginCheckJs 含 startBrowser/java.connect（需真机开浏览器人工验证）",
                 "工具无法自动化这部分；但会在每步先模拟执行 loginCheckJs，"
                 "仅当仍被挡时才需你真机手动过验证")
        need_browser = True
    elif lcjs.strip():
        rep.info("LIVE-LOGINCHECK-INFO",
                 "该书源配置了 loginCheckJs —— 工具会在搜索/详情/目录/正文每步响应后自动模拟执行"
                 "（node 实现 java.ajax 真实发登录请求 + 自动种 cookie，覆盖大部分登录型源）",
                 "若 loginCheckJs 依赖人机验证（滑块/CF challenge）则无法自动化，需真机确认")
    return need_browser


def _diag_empty_response(html, rep, prefix):
    """列表 0 命中时的响应体诊断: 区分「接口 JSON 拒绝(展示 code/msg)」/
    「疑似风控或错误页(超短响应)」/「正常页面(规则选择器问题)」三类。"""
    h = (html or "").strip()
    if not h:
        return
    s = h.lstrip()
    if s.startswith("{") or s.startswith("["):
        code, msg = "", ""
        try:
            j = json.loads(h)
            code = j.get("code", "") if isinstance(j, dict) else ""
            msg = (j.get("msg") or j.get("message") or "") if isinstance(j, dict) else ""
        except Exception:
            pass
        rep.info(prefix + "-RESP",
                 "接口返回 JSON%s%s，原文前150字: %s —— 服务器拒绝/无数据（非选择器问题，"
                 "检查参数/风控/接口变更）" % (" code=%s" % code if code != "" else "",
                                              " msg=%s" % msg if msg else "", h[:150]))
    elif len(h) < 2000:
        rep.info(prefix + "-RESP",
                 "响应体仅 %d 字节（疑似错误/风控页），前200字: %s" % (len(h), h[:200]))


def _norm_url(u):
    """归一化 URL 用于翻页 loop 检测：去 fragment、末尾斜杠、小写 host。"""
    from urllib.parse import urlparse, urlunparse
    try:
        p = urlparse(u)
        path = p.path.rstrip("/")
        return urlunparse((p.scheme, p.netloc.lower(), path, "", p.query, ""))
    except Exception:
        return u


def _parse_book_list(html_file, rule, jar_dir, charset, vars_map):
    """对齐 App BookListRule 解析（搜索/探索共用）：
    bookList 取容器 → 逐 item 同时套 name/bookUrl（同源，避免各字段独立跳空导致首条错配）。
    字段名兼容 SearchRule(bookName/bookAuthor/bookIntro) 与 ExploreRule(name/author/intro)。
    返回 dict: items, names, bookurls, authors, covers, intros, kinds, count。
    无 bookUrl 的 item 按真机行为丢弃(不加书)。"""
    rule = rule or {}
    items = _eval_list(html_file, rule.get("bookList"), jar_dir) if jar_dir else []

    def _pick(*keys):
        for k in keys:
            v = rule.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    name_rule = _pick("name", "bookName")
    url_rule = _pick("bookUrl")
    author_rule = _pick("author", "bookAuthor")
    cover_rule = _pick("coverUrl")
    intro_rule = _pick("intro", "bookIntro")
    kind_rule = _pick("kind")

    def _one(item_html, rule_str):
        if not rule_str:
            return ""
        ifile = _write_tmp(item_html)
        ctx = _make_ctx(ifile, None, jar_dir, charset, raw_text=item_html,
                        vars_map=vars_map, mode="elemrule")
        res = _eval_combined(rule_str, ctx)
        return res[0] if res and res[0] else ""

    names, bookurls = [], []
    authors, covers, intros, kinds = [], [], [], []
    for ih in items:
        u = _one(ih, url_rule)
        if not u:                      # 无 bookUrl 的 item：对齐真机不加书
            continue
        names.append(_one(ih, name_rule))
        bookurls.append(u)
        authors.append(_one(ih, author_rule))
        covers.append(_one(ih, cover_rule))
        intros.append(_one(ih, intro_rule))
        kinds.append(_one(ih, kind_rule))

    return {
        "items": items,
        "names": names,
        "bookurls": bookurls,
        "authors": authors,
        "covers": covers,
        "intros": intros,
        "kinds": kinds,
        "count": len(bookurls),
    }


def _live_crawl_toc(toc_url, toc_html, src, jar_dir, charset, vars_map, rep, _f, rt,
                    parallel=False):
    """模拟 Legado 目录翻页（对齐真机 getStringList URL 列表语义）。
    返回 (names, urls, pages, loop, terminated, distinct)。
      - names/urls: 累积的章节名/章节URL(按URL去重)
      - pages: 访问过的页 URL 序列
      - loop: 某页 nextTocUrl 解析出已访问页(自引用/回链) → 真机按去重停止但章节可能不全
      - terminated: 是否因无新页而正常停止(否则达护栏上限)
      - distinct: 去重后的实际页数
    真机流程（webBook/k.smali + AnalyzeRule.smali 实证）:
      nextTocUrl 经 getStringList 求值 → 按\\n拆行→逐行绝对化→去重 → **并发抓取全部新页**
      → 每个新页再求 nextTocUrl（BFS），只抓没访问过的页，直到无新页。
    """
    names, urls = [], []
    seen_url = set()
    visited = {_norm_url(toc_url)}
    pages = [toc_url]
    loop = False
    terminated = True
    distinct = 1

    pname_rule = str(rt.get("chapterName", "")).strip()
    purl_rule = str(rt.get("chapterUrl", "")).strip()
    nxt_rule = str(rt.get("nextTocUrl", "")).strip()

    def _ch_one(ch, rule):
        rule = str(rule).strip()
        if not rule:
            return ""
        cf = _write_tmp(ch)
        ctx = _make_ctx(cf, None, jar_dir, charset, raw_text=ch,
                        vars_map=vars_map, mode="elemrule")
        r = _eval_combined(rule, ctx)
        return r[0] if r and r[0] else ""

    def _parse_chapters(cur_url, cur_html):
        tfile = _write_tmp(cur_html)
        chs = _eval_list(tfile, rt.get("chapterList"), jar_dir) if jar_dir else []
        for ch in chs:
            pu = _ch_one(ch, purl_rule)
            if not pu:                 # 无 chapterUrl 的容器：不计为章（同源提取 name/url）
                continue
            u = urljoin(cur_url, pu)
            if u not in seen_url:
                seen_url.add(u)
                names.append(_ch_one(ch, pname_rule))
                urls.append(u)

    def _fetch_pages(url_list, referer):
        """并发（或串行）抓取一批新页；单个失败仅丢页（真机该请求失败即丢弃）。"""
        got, first_err = {}, None
        if not url_list:
            return got, first_err

        def _one(u):
            html, _, err = _f(u, "GET", None, referer=referer)
            return u, html, err

        if parallel and len(url_list) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as ex:
                for u, html, err in ex.map(_one, url_list):
                    if html is None and first_err is None:
                        first_err = err
                    if html is not None:
                        got[u] = html
        else:
            for u in url_list:
                u2, html, err = _one(u)
                if html is None and first_err is None:
                    first_err = err
                if html is not None:
                    got[u2] = html
        return got, first_err

    queue = [(toc_url, toc_html)]
    _parse_chapters(toc_url, toc_html)
    while queue:
        if distinct >= MAX_TOC_PAGES:
            terminated = False   # 达到 MAX_TOC_PAGES 仍未停
            break
        cur_url, cur_html = queue.pop(0)
        _parse_chapters(cur_url, cur_html)
        if not nxt_rule:
            continue             # 无 nextTocUrl: 单页源，队列自然排空
        ctx = _make_ctx(_write_tmp(cur_html), None, jar_dir, charset,
                        raw_text=cur_html, vars_map=vars_map)
        res = _eval_combined(nxt_rule, ctx)
        nxt_urls = _resolve_next_urls(res, cur_url)
        if cur_url == toc_url and len(nxt_urls) > 8:
            rep.warn("LIVE-PAGINATE-BULK",
                     "nextTocUrl 一次解析出 %d 个下一页 URL，真机会**全部并发请求**"
                     "（『并发解析目录,总页数:%d』）。正常源的下一页每页只该有 1~2 个；"
                     "这通常是 `##正则##替换` 类规则把整页源码都拆成了 URL 列表"
                     " → 大量无效请求、目录解析慢（真机实测 6.5s）且可能被站点封禁"
                     % (len(nxt_urls), len(nxt_urls)),
                     "nextTocUrl 应精确指向『下一页』链接，"
                     "如 `a:contains(下一页)@href` 或 option 的 selected 逻辑")
        new_pages = []
        for u in nxt_urls:
            nu = _norm_url(u)
            if nu == _norm_url(cur_url):
                loop = True      # 自引用（真机去重后停止；链式语义即死循环）
                continue
            if nu in visited:
                loop = True      # 回链已访问页
                continue
            visited.add(nu)
            new_pages.append(u)
        quota = MAX_TOC_PAGES - distinct
        if len(new_pages) > quota:
            new_pages = new_pages[:quota]
        got, first_err = _fetch_pages(new_pages, referer=cur_url)
        if new_pages and not got:
            rep.warn("LIVE-PAGINATE-FETCH", "目录下一页抓取全部失败(%s): %s → 跳过该批次（真机行为一致）"
                     % (new_pages[0], first_err))
        if new_pages and len(got) < len(new_pages):
            rep.info("LIVE-PAGINATE", "%d 个下一页中 %d 个抓取失败已丢弃（真机行为一致）"
                     % (len(new_pages), len(new_pages) - len(got)))
        for u in new_pages:
            if u in got:
                pages.append(u)
                distinct += 1
                queue.append((u, got[u]))
    return names, urls, pages, loop, terminated, distinct


def _live_follow_paging(initial_url, initial_html, next_rule, rep, _f, label,
                        jar_dir, charset, vars_map, max_pages, parallel=False):
    """通用翻页跟随(nextContentUrl 等)，对齐真机 getStringList URL 列表语义:
    求值结果按 \\n 拆行→逐行绝对化→去重 → **并发抓取全部新页** → 每页再求 next（BFS）。
    返回 (pages, loop, terminated, fetched)，fetched=[(url, html)] 抓取顺序。"""
    from urllib.parse import urljoin as _uj
    pages = [initial_url]
    visited = {_norm_url(initial_url)}
    loop = False
    terminated = True
    fetched = []

    def _fetch_pages(url_list, referer):
        got, first_err = {}, None
        if not url_list:
            return got, first_err

        def _one(u):
            html, _, err = _f(u, "GET", None, referer=referer)
            return u, html, err

        if parallel and len(url_list) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as ex:
                for u, html, err in ex.map(_one, url_list):
                    if html is None and first_err is None:
                        first_err = err
                    if html is not None:
                        got[u] = html
        else:
            for u in url_list:
                u2, html, err = _one(u)
                if html is None and first_err is None:
                    first_err = err
                if html is not None:
                    got[u2] = html
        return got, first_err

    queue = [(initial_url, initial_html)]
    while queue:
        if len(pages) >= max_pages:
            terminated = False
            break
        cur_url, cur_html = queue.pop(0)
        if not str(next_rule).strip():
            continue
        tfile = _write_tmp(cur_html)
        ctx = _make_ctx(tfile, None, jar_dir, charset, raw_text=cur_html, vars_map=vars_map)
        nxt = _eval_combined(str(next_rule), ctx)
        nxt_urls = _resolve_next_urls(nxt, cur_url)
        new_pages = []
        for u in nxt_urls:
            nu = _norm_url(u)
            if nu == _norm_url(cur_url):
                loop = True
                continue
            if nu in visited:
                loop = True
                continue
            visited.add(nu)
            new_pages.append(u)
        quota = max_pages - len(pages)
        if len(new_pages) > quota:
            new_pages = new_pages[:quota]
        got, first_err = _fetch_pages(new_pages, referer=cur_url)
        if new_pages and not got:
            rep.warn("LIVE-%s-FETCH" % label, "翻页抓取全部失败(%s): %s → 跳过该批次（真机行为一致）"
                     % (new_pages[0], first_err))
        for u in new_pages:
            if u in got:
                pages.append(u)
                fetched.append((u, got[u]))
                queue.append((u, got[u]))
    return pages, loop, terminated, fetched


def live_debug(src, raw, rep, keyword, browser=False, no_browser=False, explore=False):
    """对齐 App「书源调试」：搜索/探索→详情→目录→正文 真实链路。
    explore=True 走『发现』入口(exploreUrl + ruleExplore)；否则搜索(searchUrl + ruleSearch)。
    browser=True 全程用 headless Chromium；否则先 requests，检测到反爬/验证自动升级浏览器。"""
    if not isinstance(src, dict):
        rep.error("LIVE", "书源根必须是对象")
        return
    jar, jar_dir = _find_jsoup_jar(os.path.dirname(os.path.abspath(__file__)))
    charset = src.get("charset") or "utf-8"
    use_browser = bool(browser)
    cookie_file = None  # 浏览器会话共享 cookie
    # 变量表: 供 {{key}} {{page}} {{bookUrl}} {{baseUrl}} 等替换 (对齐 App 的变量解析)
    vars_map = {
        "key": keyword,
        "page": 1,
        "baseUrl": src.get("bookSourceUrl", ""),
        "ruleFindUrl": src.get("ruleFindUrl", ""),
    }

    def _f(url, method="GET", body=None, referer=None):
        """按当前模式抓取：浏览器 or requests；抓取后执行 loginCheckJs 注入 cookie。"""
        if use_browser:
            html, final, err = browser_fetch(url, src, method, body, cookie_file=cookie_file)
        else:
            html, final, err = fetch(url, src, method, body, referer, charset=charset)
        if html is None:
            return html, final, err
        # 对齐 App(WebBook/x0)：每步响应后执行 loginCheckJs 拿登录态（cookie 汇入 _SESSION）
        nbody = _run_login_check(src, final, html, charset, rep, tag)
        if nbody is not None:
            html = nbody
        return html, final, err

    rep.info("LIVE", "开始真实链路调试（关键词=%s，charset=%s，浏览器=%s）"
             % (keyword, charset, "强制" if browser else "自动"))

    # ---- 1. 入口决策：搜索 or 探索（发现） ----
    # 对齐 App：有 searchUrl 走搜索；纯发现源(bookSourceUrl+exploreUrl)走探索。
    ex_url = src.get("exploreUrl")
    has_explore = bool(ex_url) and str(ex_url).strip()
    can_search = bool(build_search(src, keyword)[0]) if (keyword and not explore) else bool(src.get("searchUrl") or src.get("bookSourceUrl"))
    # 探索触发：显式 --explore，或（有探索入口 且 (无关键词 或 无搜索入口)）
    use_explore = explore or (has_explore and (not keyword or not can_search))
    tag = "探索" if use_explore else "搜索"
    if use_explore:
        if not has_explore:
            rep.error("LIVE-NOENTRY", "未配置 exploreUrl，无法执行探索（发现）调试（可加 --keyword 走搜索）")
            return
        prefix = "LIVE-EXPLORE"
        eu_raw = str(ex_url).strip()
        base = (src.get("bookSourceUrl") or "").strip()
        # 对齐真机 ExploreUrl 解析: 行 -> "&&" 拆 tab -> "::" 拆(标题, url);
        # url 非绝对时以 bookSourceUrl 为基拼接; {{page}} 等模板按 tab 求值
        tabs = []
        eu_trim = eu_raw.strip()
        if eu_trim.startswith("["):
            # ExploreUrl 的 JSON 数组形态: [{title,url,style}...]，跳过 url 为空的分组标题
            try:
                for it in json.loads(eu_trim):
                    if not isinstance(it, dict):
                        continue
                    t = str(it.get("title") or "")
                    u = str(it.get("url") or "").strip()
                    if u:
                        tabs.append((t, u))
            except Exception:
                tabs = []
        if not tabs:
            for _line in eu_raw.splitlines():
                _line = _line.strip()
                if not _line:
                    continue
                for _tab in _line.split("&&"):
                    _tab = _tab.strip()
                    if not _tab:
                        continue
                    if "::" in _tab:
                        _title, _sep, _tu = _tab.partition("::")
                        tabs.append((_title.strip(), _tu.strip()))
                    else:
                        tabs.append(("", _tab))
        if not tabs:
            rep.error("LIVE-NOENTRY", "exploreUrl 解析不到任何分类 tab（格式: 标题::URL&&标题::URL）")
            return
        _tab_title, _tab_url = tabs[0]
        url = _eval_url_template(_tab_url, keyword=keyword or "", page=1, base_url=base)
        if base:
            url = urljoin(base, url)   # 对齐 App：bookSourceUrl + exploreUrl 拼接
        if len(tabs) > 1:
            rep.info("LIVE-EXPLORE",
                     "exploreUrl 共 %d 个分类 tab，工具逐 tab 调试第 1 个『%s』: %s"
                     % (len(tabs), _tab_title or "未命名", url))
        else:
            rep.info("LIVE-EXPLORE", "以『发现』入口调试：%s" % url)
        method, body = "GET", None
        rg = _region(src, "ruleExplore") or {}
    else:
        prefix = "LIVE-SEARCH"
        bs = build_search(src, keyword)
        if bs is None:
            rep.error("LIVE-NOENTRY",
                      "无 searchUrl（需 --keyword）且无 exploreUrl；纯发现源请加 --explore")
            return
        url, method, body, bs_charset = bs
        if keyword and bs_charset and bs_charset != "utf-8":
            charset = bs_charset  # 对齐 AnalyzeUrl: options.charset 同管响应解码
        rg = _region(src, "ruleSearch") or {}

    # 先用 requests（_f 内含 loginCheckJs）；若检测到反爬/验证信号且允许，预热首页 + 浏览器重试
    if not use_browser and not no_browser:
        html, final, err = _f(url, method, body)
        if html is None:
            rep.error("LIVE-FETCH", "%s页抓取失败: %s" % (tag, err))
            return
        need_b = _check_anti_bot(html, final, url, src, rep)
        if need_b:
            rep.info("LIVE-BROWSER", "检测到反爬/验证信号，自动切换到 headless Chromium 重试")
            cookie_file = _browser_warmup(src, rep)
            use_browser = True
            html, final, err = _f(url, method, body)  # 浏览器重试（_f 内含 loginCheckJs）
            if html is None:
                rep.error("LIVE-BROWSER", "浏览器重试抓取失败: %s" % err)
                return
            rep.info("LIVE-BROWSER", "浏览器重试成功，后续关卡沿用 headless Chromium")
    else:
        html, final, err = _f(url, method, body)
        if html is None:
            rep.error("LIVE-FETCH", "%s页抓取失败: %s" % (tag, err))
            return
        _check_anti_bot(html, final, url, src, rep)

    sfile = _write_tmp(html)
    rep.info(prefix, "已抓取 %s （%d 字节，引擎=%s）"
             % (final, len(html), "Chromium" if use_browser else "requests"))

    # ---- 1.5 书籍列表（搜索/探索共用 BookListRule 解析） ----
    # 对齐 App(webBook/z)：ruleExplore.bookList 为空 → 直接用 ruleSearch.bookList（不套整页）
    if use_explore and not (rg.get("bookList") or "").strip():
        rs2 = _region(src, "ruleSearch") or {}
        if (rs2.get("bookList") or "").strip():
            rep.warn("LIVE-EXPLORE", "ruleExplore.bookList 为空，已按 App 行为回退用 ruleSearch.bookList")
            rg = rs2
    r = _parse_book_list(sfile, rg, jar_dir, charset, vars_map)
    if not r["items"]:
        rep.error(prefix, "%s列表(bookList)未取到任何容器 → %s规则失效" % (tag, tag))
        _diag_empty_response(html, rep, prefix)
        return
    names, bookurls = r["names"], r["bookurls"]
    rep.info(prefix, "列表命中 %d 条书" % r["count"])
    if not bookurls:
        rep.error(prefix, "%s未取到任何 bookUrl → %s规则失效（浏览器模式仍被挡？见上诊断）" % (tag, tag))
        _diag_empty_response(html, rep, prefix)
        return
    first_name = (names[0] if names else "?")
    first_book = urljoin(final, bookurls[0])
    vars_map["bookUrl"] = first_book
    rep.info(prefix, "取首条: 《%s》 → %s" % (first_name, first_book))
    # 对齐 App 调试面板: 首条各字段逐条验证(不止 name/bookUrl)
    if r["items"]:
        ifile = _write_tmp(r["items"][0])
        for _fld in ("author", "kind", "lastChapter", "coverUrl", "intro"):
            _rule = (rg.get(_fld) or "").strip()
            if _rule:
                _live_stage(rep, "%s-%s" % (prefix.replace("LIVE-", ""), _fld.upper()),
                            _rule, ifile, jar_dir, charset=charset,
                            vars_map=vars_map, limit=1)

    # ---- 2. 书籍详情 ----
    bi_html, bi_final, bi_err = _f(first_book, "GET", None, referer=final)
    if bi_html is None:
        rep.error("LIVE-BOOKINFO", "详情页抓取失败: %s" % bi_err)
        return
    bfile = _write_tmp(bi_html)
    bi = _region(src, "ruleBookInfo") or {}
    _live_stage(rep, "BOOKINFO-NAME", bi.get("name", ""), bfile, jar_dir, charset=charset, vars_map=vars_map)
    _live_stage(rep, "BOOKINFO-AUTHOR", bi.get("author", ""), bfile, jar_dir, charset=charset, vars_map=vars_map)
    # 对齐 App 调试面板: 详情各字段逐条验证(不止 name/author/tocUrl)
    for fld in ("kind", "lastChapter", "coverUrl", "intro"):
        if (bi.get(fld) or "").strip():
            _live_stage(rep, "BOOKINFO-%s" % fld.upper(), bi[fld], bfile, jar_dir,
                        charset=charset, vars_map=vars_map, limit=1)
    toc_rule = (bi.get("tocUrl") or "").strip()
    if toc_rule:
        tocurls, _ = _live_stage(rep, "BOOKINFO-TOC", toc_rule, bfile, jar_dir, charset=charset, vars_map=vars_map)
        toc_url = urljoin(bi_final, tocurls[0]) if tocurls else None
        if not toc_url:
            # 对齐 App(WebBook)：tocUrl 规则非空但未取到 → 也按「留在当前页」处理并提示
            rep.warn("LIVE-BOOKINFO", "tocUrl 规则未取到结果 → 按对齐 App 行为留在当前页（详情即目录）")
            toc_url = bi_final
    else:
        # 对齐 App(WebBook)：tocUrl 规则为空 → 详情页即目录页
        toc_url = bi_final
        rep.info("LIVE-BOOKINFO", "tocUrl 规则为空 → 详情页即目录页（对齐 App 行为）")
    vars_map["baseUrl"] = toc_url
    rep.info("LIVE-BOOKINFO", "目录地址: %s" % toc_url)

    # ---- 3. 目录（含翻页模拟） ----
    toc_html, toc_final, toc_err = _f(toc_url, "GET", None, referer=bi_final)
    if toc_html is None:
        rep.error("LIVE-TOC", "目录页抓取失败: %s" % toc_err)
        return
    rt = _region(src, "ruleToc") or {}
    nxt_rule = str(rt.get("nextTocUrl", "")).strip()

    if nxt_rule:
        ch_names, ch_urls, pages, loop, terminated, distinct = _live_crawl_toc(
            toc_url, toc_html, src, jar_dir, charset, vars_map, rep, _f, rt,
            parallel=not use_browser)
        rep.info("LIVE-PAGINATE",
                 "目录翻页模拟: 跟随 nextTocUrl 共访问 %d 个去重页(序列 %d 步), 累积 %d 章%s"
                 % (distinct, len(pages), len(ch_urls),
                    " → 存在自引用/回链(死循环特征)!" if loop and terminated
                    else (" → 未正常终止(触达护栏)!" if not terminated else "")))
        if loop and terminated:
            rep.error("LIVE-PAGINATE-LOOP",
                       "nextTocUrl 存在自引用/回链（某页的 next 指向已访问过的页）。"
                       "真机按 URL 去重后会停止、不会无限循环，但说明 next 指向了错误的"
                       "『下一页』——典型症状是跳尾页丢中间章",
                       "nextTocUrl 必须指向『下一页』链接；不要用 last-child/尾页选择器，"
                       "末页 next 应返回空串")
        elif not terminated:
            rep.warn("LIVE-PAGINATE-NONTERM",
                     "nextTocUrl 抓取 %d 页仍未收敛，已触达工具防 hang 护栏上限"
                     "（真机无步数上限，会一直翻到无新页为止）。若源确为长目录属正常；"
                     "若伴随 BULK 告警则多为规则把整页拆成了 URL 列表" % len(pages),
                     "确认目录是否真的长；否则检查 nextTocUrl 是否真指向『下一页』")
        elif distinct < 2 and ("last-child" in nxt_rule or "末页" in nxt_rule or "尾页" in nxt_rule):
            rep.warn("LIVE-PAGINATE-TAIL",
                     "nextTocUrl 含『尾页/last-child』特征但只抓到 1 页 → 可能跳尾页丢中间章",
                     "改用『下一页』链接或 ?page=N 做 page+1")
        rep.info("LIVE-PAGINATE-PATH", "翻页路径: " + " → ".join(pages[:12])
                 + (" …" if len(pages) > 12 else ""))
        if not ch_urls:
            rep.error("LIVE-TOC", "翻页后仍取不到任何 chapterUrl → 目录规则失效")
            return
    else:
        tfile = _write_tmp(toc_html)
        chapters = _eval_list(tfile, rt.get("chapterList"), jar_dir) if jar_dir else []
        if not chapters:
            rep.error("LIVE-TOC", "目录列表(chapterList)未取到任何容器 → 目录规则失效")
            return

        def _ch_one(ch, rule):
            rule = str(rule).strip()
            if not rule:
                return ""
            cf = _write_tmp(ch)
            ctx = _make_ctx(cf, None, jar_dir, charset, raw_text=ch,
                            vars_map=vars_map, mode="elemrule")
            res = _eval_combined(rule, ctx)
            return res[0] if res and res[0] else ""

        ch_name_rule = str(rt.get("chapterName", "")).strip()
        ch_url_rule = str(rt.get("chapterUrl", "")).strip()
        ch_names, ch_urls = [], []
        for ch in chapters:
            cu = _ch_one(ch, ch_url_rule)
            if not cu:                 # 无 chapterUrl 的容器：对齐真机不计为章
                continue
            ch_names.append(_ch_one(ch, ch_name_rule))
            ch_urls.append(cu)
        if not ch_urls:
            rep.error("LIVE-TOC", "目录未取到任何 chapterUrl → 目录规则失效")
            return
        rep.info("LIVE-PAGINATE", "目录无 nextTocUrl，单页取章（共 %d 章）" % len(ch_urls))

    first_ch = urljoin(toc_final, ch_urls[0])
    rep.info("LIVE-TOC", "共 %d 章，取首章: %s" % (len(ch_urls), first_ch))

    # ---- 4. 正文（含 nextContentUrl 翻页跟随） ----
    con_html, con_final, con_err = _f(first_ch, "GET", None, referer=toc_final)
    if con_html is None:
        rep.error("LIVE-CONTENT", "正文页抓取失败: %s" % con_err)
        return
    cfile = _write_tmp(con_html)
    rc = _region(src, "ruleContent") or {}
    content, _ = _live_stage(rep, "CONTENT", rc.get("content", ""), cfile, jar_dir, charset=charset, vars_map=vars_map)
    if content:
        rep.info("LIVE-CONTENT", "正文首段 %d 字: %s"
                 % (len(content[0]), content[0][:80].replace("\n", " ")))
    else:
        rep.error("LIVE-CONTENT", "正文取空 → 正文规则失效")
        return

    nxt_c_rule = str(rc.get("nextContentUrl", "")).strip()
    if nxt_c_rule:
        cpages, cloop, cterm, cfetched = _live_follow_paging(
            first_ch, con_html, nxt_c_rule, rep, _f, "CONTENT-PAGE",
            jar_dir, charset, vars_map, MAX_CONTENT_PAGES, parallel=not use_browser)
        rep.info("LIVE-CONTENT-PAGE",
                 "nextContentUrl 翻页: 共访问 %d 步%s"
                 % (len(cpages), " → 存在自引用/回链(死循环特征)!" if cloop and cterm
                    else (" → 未正常终止(触达护栏)!" if not cterm else "")))
        if cloop and cterm:
            rep.error("LIVE-CONTENT-LOOP",
                       "nextContentUrl 存在自引用/回链（某页 next 指向已访问页）。"
                       "真机按 URL 去重后停止，但说明 next 指向了错误的『下一页』→ 正文重复/丢段",
                       "nextContentUrl 应指向『下一页』且末页返回空串停止")
        elif not cterm:
            rep.warn("LIVE-CONTENT-NONTERM",
                     "nextContentUrl 跟随 %d 步仍未返回空串，已触达工具防 hang 护栏上限"
                     "（真机无步数上限，会一直翻直到 next 返回空）。若源确为长分页（每章一页）属正常；"
                     "否则检查 nextContentUrl 是否真指向『下一页』，末页应返回空串" % len(cpages))
        if cfetched:
            # 对齐真机: 各翻页正文按序拼接；检测翻页正文取空（下一页指错会整段丢字）
            merged = 0
            empty_pages = []
            for cu, chtml in cfetched:
                cfx = _write_tmp(chtml)
                seg, _ = _eval_rule_results(rc.get("content", ""), cfx, jar_dir,
                                            None, charset, vars_map)
                if seg and seg[0]:
                    merged += len(seg[0])
                else:
                    empty_pages.append(cu)
            rep.info("LIVE-CONTENT-PAGE", "翻页正文合并: %d 页共 %d 字%s"
                     % (len(cfetched), merged,
                        ("；以下页取空: %s" % "; ".join(empty_pages[:3])) if empty_pages else ""))

    rep.info("LIVE", "链路完成：搜索→详情→目录→正文 四关均已真实跑通（引擎=%s）"
             % ("Chromium" if use_browser else "requests")
             if not rep.errors else "链路存在 ERROR，见上")


# ----------------------------------------------------------------------------
# 7. 主流程
# ----------------------------------------------------------------------------
def run_checks(src, raw, rep, dynamic, samples):
    check_structure(src, raw, rep)
    if not isinstance(src, dict):
        return
    check_region_completeness(src, raw, rep)
    check_field_ownership(src, raw, rep)
    check_dead_fields(src, raw, rep)
    check_wait_field(src, raw, rep)
    check_regex_syntax(src, raw, rep)
    check_book_url_pattern(src, raw, rep)
    check_js_syntax(src, raw, rep)
    check_urls(src, raw, rep)
    check_search_explore(src, raw, rep)
    check_parse_path_sanity(src, raw, rep)
    check_concurrent_rate(src, raw, rep)
    check_next_toc(src, raw, rep)
    check_cookie_jar(src, raw, rep)
    if dynamic:
        dynamic_check(src, raw, rep, samples)


def print_report(rep, src_name):
    print("=" * 70)
    print("AI 书源调试报告: %s" % src_name)
    print("=" * 70)
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    items = sorted(rep.items, key=lambda x: order.get(x[0], 9))
    cur = None
    for sev, code, msg, fix in items:
        if sev != cur:
            cur = sev
            print("\n[%s]" % sev)
        loc = ""
        line = None
        # 提取行号（fix 里可能含 行 ~N）
        m = re.search(r"行\s*~?(\d+)", fix)
        if m:
            line = m.group(1)
        if line:
            loc = " (L%s)" % line
        print("  • [%s]%s %s" % (code, loc, msg))
        if fix:
            print("       ↳ 修: %s" % fix)
    print("\n" + "-" * 70)
    print("结论: %s" % rep.summary())


def load_source(path):
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    src = json.loads(raw)
    # 支持书源组（数组）→ 逐个检查，但报告聚焦第一个合规对象
    if isinstance(src, list):
        if not src:
            raise ValueError("书源数组为空")
        return src, raw
    return src, raw


# ----------------------------------------------------------------------------
# 8. 自测（正/反例标本，铁律 22/23：护栏自身也要能区分正误）
# ----------------------------------------------------------------------------
GOOD_SRC = {
    "bookSourceName": "测试源-好", "bookSourceUrl": "https://example.com",
    "ruleSearch": {"bookList": "##", "name": "//h3", "bookUrl": "//h3/a/@href"},
    "ruleBookInfo": {"name": "//h1", "tocUrl": "//a[@class='toc']/@href"},
    "ruleToc": {"chapterList": "##", "chapterName": "//li", "chapterUrl": "//li/a/@href",
                "nextTocUrl": "<js>return '';</js>"},
    "ruleContent": {"content": "//div[@id='content']"},
}

BAD_SRC = {
    "bookSourceName": "测试源-坏", "bookSourceUrl": "not-a-url",
    "ruleSearch": {"bookList": "##", "name": "//h3"},   # 缺 bookUrl
    "ruleBookInfo": {"name": "//h1"},
    "ruleToc": {"chapterList": "##", "chapterName": "//li"},  # 缺 chapterUrl
    "ruleContent": {
        "content": "//div",
        "replaceRegex": "([未闭合(",                  # 正则语法错
    },
    "concurrentRate": "1000",
    "ruleExplore": {"bookList": "##", "name": "//a", "bookUrl": "//a@href",
                    "nextTocUrl": "//ul/li[last-child]"},  # 取尾页无 JS
    "loginCheckJs": "java.get('https://x.com')",       # 单参 java.get
    "webViewDelayTime": "8000",                         # 错等待字段
}


def self_test():
    rep = Report()
    run_checks(GOOD_SRC, json.dumps(GOOD_SRC), rep, False, {})
    good_err = len(rep.errors)
    rep2 = Report()
    run_checks(BAD_SRC, json.dumps(BAD_SRC), rep2, False, {})
    codes = {i[1] for i in rep2.items}
    need = {"REGION-REQ", "REGION-REQ", "REGEX", "CONCURRENT", "NEXT-TAIL",
            "JAVA-GET", "WAIT-FIELD", "URL"}
    caught = need & codes
    ok = (good_err == 0) and len(caught) >= 6
    print("自检: 好源 ERROR=%d (应=0)" % good_err)
    print("自检: 坏源 抓到 %d/%d 类关键问题" % (len(caught), len(need)))
    print("  命中: %s" % ", ".join(sorted(caught)))
    print("  未命中: %s" % ", ".join(sorted(need - caught)) or "无")
    print("结果: %s" % ("通过" if ok else "失败"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 书源调试工具（反编译 Legado 3.25 实证）")
    ap.add_argument("path", nargs="?", help="书源 JSON 路径，- 表示 stdin")
    ap.add_argument("--dynamic", action="store_true", help="开启动态实跑（需样本）")
    ap.add_argument("--html", help="通用页面样本（搜索/详情/目录/正文共用）")
    ap.add_argument("--search-html", help="搜索页样本")
    ap.add_argument("--bookinfo-html", help="详情页样本")
    ap.add_argument("--toc-html", help="目录页样本")
    ap.add_argument("--content-html", help="正文页样本")
    ap.add_argument("--json", help="JSON 样本（给 JSONPath 规则）")
    ap.add_argument("--strict", action="store_true", help="WARN 也判失败")
    ap.add_argument("--keyword", help="真实链路调试关键词（走搜索：搜索→详情→目录→正文）")
    ap.add_argument("--explore", action="store_true",
                    help="以『发现』入口调试（exploreUrl + ruleExplore）；纯发现源无需关键词")
    ap.add_argument("--browser", action="store_true",
                    help="强制全程用 headless Chromium 渲染（覆盖 WebView/反爬/客户端解密类源）")
    ap.add_argument("--no-browser", action="store_true",
                    help="禁止浏览器自动升级，仅用普通请求")
    ap.add_argument("--self-test", action="store_true", help="内置正/反例自检")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.path:
        ap.print_help()
        return 2

    samples = {
        "html": args.html, "search_html": args.search_html,
        "bookinfo_html": args.bookinfo_html, "toc_html": args.toc_html,
        "content_html": args.content_html, "json": args.json,
    }
    try:
        src, raw = load_source(args.path)
    except Exception as e:  # noqa
        print("[ERROR] 书源解析失败: %s" % e, file=sys.stderr)
        return 2

    rep = Report()
    print("🔧 AI 书源调试工具  v1.0  (反编译 Legado 3.25 实证)")
    if isinstance(src, list):
        print("[INFO] 检测到书源组（%d 条），逐条检查前 3 条" % len(src))
        for i, s in enumerate(src[:3]):
            r2 = Report()
            run_checks(s, json.dumps(s), r2, args.dynamic, samples)
            print("\n--- 书源 #%d (%s) ---" % (i + 1, s.get("bookSourceName", "?")))
            print_report(r2, args.path)
        return 0

    run_checks(src, raw, rep, args.dynamic, samples)

    # 真实链路调试：搜索(--keyword) 或 探索(--explore / 纯发现源自动)
    src_explore = bool(src.get("exploreUrl")) and str(src.get("exploreUrl", "")).strip()
    do_live = bool(args.keyword) or args.explore or (src_explore and not args.keyword)
    if do_live:
        print("\n" + "=" * 70)
        if args.explore:
            mode = "发现/探索入口（--explore）"
        elif args.keyword:
            mode = "关键词: %s" % args.keyword
        else:
            mode = "纯发现源自动探索"
        print("真实链路调试（%s）" % mode)
        print("=" * 70)
        live_debug(src, raw, rep, args.keyword or "",
                   browser=args.browser, no_browser=args.no_browser, explore=args.explore)

    # 报告只打印一次（合并静态 + 链路结果）
    print_report(rep, args.path)
    if rep.errors:
        return 1
    if args.strict and rep.warns:
        return 1
    print("\n✅ 通过（无 ERROR）" if not rep.warns else "\n⚠️ 通过但有 WARN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
