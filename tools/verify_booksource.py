#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书源本地实测闭环驱动: 自动抓真实页面 → 跑 test_parse → 汇总 PASS/FAIL。

把"生成书源 → 抓样本 → 验证命中 → 失败则修正重跑"合成一步, 实现真正的本地实测。
这是 validate_booksource.py(字段完整性) 与 test_parse.py(规则命中) 的总装驱动。

用法:
    python3 verify_booksource.py <书源.json> [--keyword 剑来] \
        [--workdir <临时工作目录>] [--impersonate chrome124] [--timeout 20]

自动流程:
    1. 字段完整性校验(validate_booksource.py)
    2. 用 curl_cffi 指纹伪装, 按书源规则自动抓取真实页面:
       搜索页(用 --keyword) → 取首本书 URL → 详情页 → 目录页 → 首章正文页
       发现频道首条入口 URL → 发现列表页
       (搜索抓不到时, 自动回退用发现频道取首本书, 尽量补全详情/目录/正文样本)
    3. 抓到的 HTML 存到 workdir, 调用 test_parse.py 验证各区域命中
    4. 汇总 PASS/FAIL; 任一核心区域 FAIL 即整体 FAIL, 供 agent 据此修正后重跑

说明:
    - 抓不到的页面(硬防护/Turnstile/受保护 ajax)标注 SKIP, 不计入 FAIL。
    - CSS/JS 规则仍由 App 实测, 本驱动只验 XPath/JSONPath。
    - 本驱动负责"测", 不负责"改"; 改规则由 agent 读 FAIL 报告后执行(见 SKILL.md 闭环指令)。
"""
import sys
import os
import json
import subprocess
import tempfile
from urllib.parse import urljoin, quote

try:
    from lxml import html as lxml_html
except Exception as e:
    print("缺少 lxml, 请先安装: sudo pip3 install lxml (%s)" % e)
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 可选能力: 真实浏览器过 Cloudflare(bypass_cf.py)。playwright 为 lazy import, 此处 import 安全。
try:
    sys.path.insert(0, SCRIPT_DIR)
    import bypass_cf  # noqa
    HAVE_BYPASS = True
except Exception:
    HAVE_BYPASS = False

# 强挑战特征: 标题/正文明确是 CF 验证页(与 bypass_cf 保持一致)
CF_STRONG = [
    "just a moment", "attention required", "verify you are human",
    "enable javascript and cookies to continue", "checking your browser",
    "ddos-guard", "performance & security by cloudflare",
    "访问验证", "正在检查您的浏览器", "请稍候", "检查您的浏览器",
]
# 弱特征: 仅说明页面嵌了 CF 防御 JS; 真实内容页也常含这些, 只有当内容很短(挑战页壳)才算挑战
CF_WEAK = ["cf-chl", "challenge-platform", "cf_captcha"]


def looks_like_cf(html):
    """粗判是否为 Cloudflare 挑战页(与 bypass_cf 同源, 本地化以便无 playwright 也能检测)。

    区分"主体是挑战页"与"仅嵌了 CF 防御 JS 的真实内容页": 弱特征(cf-chl 等)只有在
    内容极短(<5KB, 挑战页壳)时才算挑战; 内容较长的真实页面即使含 cf-chl 也判非挑战。
    """
    if not html:
        return False
    low = html.lower()
    if any(m in low for m in CF_STRONG):
        return True
    if any(m in low for m in CF_WEAK):
        return len(html) < 5000
    return False


# CF 过后的会话缓存: 一旦拿到 clearance, 后续抓取全部复用, 避免重复过 CF / 反复重试
_cf = {"sess": None, "tried": False}


def build_session(impersonate):
    sys.path.insert(0, SCRIPT_DIR)
    import fetch_page
    return fetch_page.build_session(impersonate)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# 全局附加 Cookie(--cookie 传入): 对"已种好 cookie 才能取到内容"的站点,
# 用它把手工/浏览器取得的 cookie 带进闭环验证, 否则每一步都会被验证页挡住。
EXTRA_COOKIE = None

# 书源 header 里声明的 User-Agent: 抓取必须复用它(真机上 App 发起 OkHttp 请求时
# 用的就是书源的 UA)。旧实现全程用上面 HEADERS 写死的移动 UA —— UA 敏感站会按 UA
# 分野不同内容, 用错 UA 本地验证会假 MISS, 结论与真机相反。
SOURCE_UA = None


def apply_source_header(src):
    """从书源 header(JSON 字符串或对象)提取 User-Agent 存入 SOURCE_UA。"""
    global SOURCE_UA
    hdr = src.get("header") if isinstance(src, dict) else None
    if isinstance(hdr, str):
        try:
            hdr = json.loads(hdr)
        except Exception:
            hdr = None
    if isinstance(hdr, dict):
        ua = hdr.get("User-Agent") or hdr.get("user-agent")
        if isinstance(ua, str) and ua.strip():
            SOURCE_UA = ua.strip()


def do_fetch(sess, url, method="GET", data=None, referer=None, timeout=20, charset=None):
    h = dict(HEADERS)
    if SOURCE_UA:
        h["User-Agent"] = SOURCE_UA  # 书源声明的 UA 优先(UA 敏感站按 UA 分野内容)
    if referer:
        h["Referer"] = referer
    if EXTRA_COOKIE:
        h["Cookie"] = EXTRA_COOKIE
    try:
        if method.upper() == "POST":
            resp = sess.post(url, headers=h, data=data, timeout=timeout, verify=False)
        else:
            resp = sess.get(url, headers=h, timeout=timeout, verify=False)
        if charset:
            try:
                resp.encoding = charset
            except Exception:
                pass
        return resp, None
    except Exception as e:
        return None, str(e)


def _find_options_span(s):
    """找 Legado URL 行内选项 `,{...}` 的 (start, end): 末尾必须是完整且平衡的 `{...}`。

    从右往左扫, 取「匹配右花括号正好落在字符串末尾」的那个 `{` 作为选项起始——
    这样 `{{key}}` 占位符的内部花括号、JSON 内部逗号都不会干扰; 真实选项对象始终延伸到末尾。

    前置条件(真机 AnalyzeUrl paramPattern=`\\s*,\\s*(?=\\{)` 实证): 选项必须由**逗号**引出。
    没有这个条件时, 以 `{{key}}` 结尾且无行内选项的串(如 `/s?q={{key}}`)会被
    误判成"选项就是 {{key}} 本身"整段剥掉, URL 退化成 `/s?q=` —— 抓取直接歪。
    找不到则返回 None。
    """
    n = len(s)
    for start in range(n - 1, -1, -1):
        if s[start] != '{':
            continue
        pre = s[:start].rstrip()
        if not pre.endswith(','):
            continue  # 选项必须由逗号引出; {{key}} 等占位符不是选项
        depth = 0
        end = -1
        for j in range(start, n):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end == n - 1:
            return start, end
    return None


def _strip_brace_options(s):
    """从字符串末尾剥掉 Legado 的 URL 行内选项 `,{...}`(如 `,{"webView":true}`)。

    选项 JSON 永远在末尾; 用 `_find_options_span` 稳健切出, 兼容 `{{key}}` 占位符、
    JSON 内部逗号与偶见字面量花括号。无选项返回原串。
    """
    s = (s or "").strip()
    span = _find_options_span(s)
    if span is None:
        return s
    start, _ = span
    pre = s[:start].rstrip()
    if pre.endswith(','):
        pre = pre[:-1].strip()
    return pre


def strip_url_options(expr):
    """剥离规则字符串末尾的 URL 行内选项(,{"webView"...}); 兼容 {{key}} 占位符与字面量花括号。"""
    return _strip_brace_options(expr)


def split_url_options(s):
    """把 Legado 的 `url,{"k":"v"}` 行内选项语法拆成 (clean_url, options_dict)。

    搜索/发现/正文 URL 常内联 `{method,body,webView,webWait,charset}` 等选项。
    本地闭环只能跑纯 HTTP(GET/POST), webView 类选项跑不了 JS 挑战 → 由调用方决定 SKIP。
    无选项时返回 (s, None)。用 `_find_options_span` 稳健兼容 `{{key}}` 占位符。
    """
    s = (s or "").strip()
    span = _find_options_span(s)
    if span is None:
        return s, None
    start, end = span
    pre = s[:start].rstrip()
    if pre.endswith(','):
        pre = pre[:-1].strip()
    try:
        opts = json.loads(s[start:end + 1])
    except Exception:
        opts = None
    return pre, (opts if isinstance(opts, dict) else None)


def strip_locator(xpath):
    """取 && / ## 前的定位部分, 并剥掉末尾 URL 行内选项(,{"webView"...}), 用于 URL 提取。"""
    if not xpath:
        return ""
    s = xpath.split("##")[0].split("&&")[0].strip()
    return strip_url_options(s)


def _apply_clean_ops(val, expr):
    """对提取值应用 Legado ##正则##替换 清洗(支持 $N 组引用)。

    ruleBookUrl 常见写法: ...@href##.*'([^']+)'.*##$1 —— 必须应用清洗,
    否则 javascript:sovote(...,'/123/'); 原样进入 urljoin 生成坏 URL。
    注意: Legado 按 split('##', limit=6) 切分, **不存在 '###' 这种分隔符**;
    写 ##正则###$1 会被切成"替换成 #$1", 结果前面多一个 #(bookUrl 直接废掉),
    正确写法始终是 ##正则##$1 或 ##待删文本 两段式。
    """
    if not expr or val is None or not isinstance(val, str):
        return val
    if "##" not in expr:
        return val
    # Legado 是纯 split(rule, "##", limit=6): parts[1]=正则, parts[2]=替换串(缺省 "" → 删除匹配)。
    # 必须按 "##" 切——若去找 "###", 标准写法 ##正则##$1 会退化成单段, 正则里带着字面
    # '##$1' 永远匹配不上, 于是值原样返回(bookUrl 拿到 javascript: 伪协议 → 坏 URL)。
    parts = expr.split("##", 5)
    pattern = parts[1] if len(parts) > 1 else ""
    if not pattern:
        return val
    replacement = parts[2] if len(parts) > 2 else ""
    try:
        rep = _re.sub(r"\$(\d+)", lambda m: "\\g<%d>" % int(m.group(1)), replacement)
        val = _re.sub(pattern, rep, val, count=1) if len(parts) > 3 else _re.sub(pattern, rep, val)
    except Exception:
        pass
    return val


def first_match(html_text, xpath):
    """在 HTML 上取首个匹配(属性或文本), 应用 ## 正则清洗, 用于推导下一跳 URL。

    若定位表达式是裸属性(如 '@href'), 退化为取文档中首个含该属性的元素的属性值。
    """
    loc = strip_locator(xpath)
    if not loc:
        return None
    try:
        tree = lxml_html.fromstring(html_text)
        m = _ATTR_RE.match(loc.strip())
        if m:
            attr = m.group(1)
            v = None
            for el in tree.iter():
                if hasattr(el, "get") and el.get(attr):
                    v = el.get(attr)
                    break
        else:
            r = tree.xpath(loc)
            if not r:
                return None
            v = r[0]
            if isinstance(v, str):
                v = v.strip() or None
            elif hasattr(v, "text_content"):
                v = v.text_content().strip() or None
            else:
                v = str(v).strip() or None
    except Exception:
        return None
    return _apply_clean_ops(v, xpath)


import re as _re

_ATTR_RE = _re.compile(r"^@([\w\-]+)$")


def _js_url_template(js_text, keyword):
    """从 <js> 搜索URL里提取请求 URL。

    兼容两种写法: java.ajax('https://...') 字面量, 或先把 URL 拼进变量再
    java.ajax(u) —— 取 js 里首个 'https://...' 字符串段, 并把后续
    '+变量+' 拼接段接上(变量值视为关键词, 如 java.urlEncode(key))。
    """
    m = _re.search(r"'(https?://[^']*)'", js_text)
    if not m:
        return None
    url = m.group(1)
    pos = m.end()
    while True:
        # 拼接段形如 '+expr+'剩余'。expr 可能是裸 key, 也可能是 java.encodeURI(key)
        # / encodeURIComponent(key) 等带点分与调用的写法——只认 [A-Za-z_]\w* 会把
        # java.encodeURI(key) 整段漏掉, 导致关键词位为空、请求被判成挑战页。
        m2 = _re.match(r"\s*\+\s*([A-Za-z_$][\w$.]*(?:\([^()]*\))?)\s*\+\s*'([^']*)'",
                       js_text[pos:])
        if not m2:
            break
        expr, tail = m2.group(1), m2.group(2)
        if _re.search(r"\bkey\b", expr):
            enc = _re.search(r"encod|URI", expr, _re.I)
            url += (quote(keyword, safe="") if enc else keyword) + tail
        else:
            url += tail
        pos += m2.end()
    return url


def _extract_cookie_name_from_js(js_text):
    """提取书源 js 里 'Cookie':'NAME='+c 中的 cookie 名(自建验证页模式)。"""
    m = _re.search(r"'Cookie'\s*:\s*'([^'=:]{1,64}?)\s*='?\s*\+", js_text)
    if m:
        return m.group(1)
    return None


def handle_verification_page(sess, url, body, raw_search=""):
    """站点自建"访问验证"页(明文cookie模式): 提取 encryptedCookieValue 并带 cookie 重抓。

    须在 CF 判断之前执行——此类页面标题也叫"访问验证"会被 looks_like_cf 误判；
    encryptedCookieValue 在页面中后部(CSS 占大头)，必须全文本查找。返回重试后的 body 或 None。
    这模拟了书源 loginCheckJs 在真实设备上的行为，便于本地验证搜索是否真能过验证页。
    """
    if not body or 'encryptedCookieValue' not in body:
        return body
    m = _re.search(r'encryptedCookieValue\s*=\s*"([^"]+)"', body)
    if not m:
        print("      [验证页] 未找到 cookie 值, SKIP"); return None
    cname = _extract_cookie_name_from_js(raw_search) or "is_human"
    print("      [验证页] 自建验证页(明文cookie), 自动提取 %s 并重试" % cname)
    h2 = dict(HEADERS)
    if SOURCE_UA:
        h2["User-Agent"] = SOURCE_UA
    h2["Cookie"] = "%s=%s" % (cname, m.group(1))
    try:
        r2 = sess.get(url, headers=h2, timeout=20, verify=False)
        body2 = r2.text
    except Exception as e:  # noqa
        print("      FAIL 重试: %s" % e); return None
    if body2 and 'encryptedCookieValue' in body2:
        print("      [验证页] 重试仍被拦, SKIP"); return None
    print("      OK 重试 HTTP %s, %d 字节" % (r2.status_code, len(body2)))
    return body2


def first_link_from_list(html_text, list_loc, url_loc):
    """从列表页(目录页)提取首个条目的链接 URL。

    正确处理 Legado 语义: ruleChapterUrl 通常是裸属性 '@href'/'@src',
    必须挂在 ruleChapterList 的首个节点上才有意义(不能直接对整个文档跑
    tree.xpath('@href'))。若 url_loc 是裸属性, 取首个列表节点的该属性;
    否则当作相对/绝对 xpath 应用到首个列表节点。
    """
    list_loc = strip_locator(list_loc)
    url_loc = strip_locator(url_loc)
    if not list_loc or not url_loc:
        return None
    try:
        tree = lxml_html.fromstring(html_text)
        nodes = tree.xpath(list_loc)
    except Exception:
        return None
    if not nodes:
        return None
    first = nodes[0]
    m = _ATTR_RE.match(url_loc.strip())
    if m:
        attr = m.group(1)
        if hasattr(first, "get"):
            return first.get(attr)
        return None
    try:
        r = first.xpath(url_loc)
    except Exception:
        return None
    if not r:
        return None
    v = r[0]
    if isinstance(v, str):
        return v.strip() or None
    return None


# 旧键名 → Legado 真实键名归一化(真实 schema: 顶层规则对象, 键无 rule 前缀)
KEY_ALIAS = {
    "ruleBookList": "bookList", "ruleName": "name", "ruleAuthor": "author",
    "ruleKind": "kind", "ruleWordCount": "wordCount", "ruleLastChapter": "lastChapter",
    "ruleIntroduce": "intro", "ruleIntro": "intro", "ruleCoverUrl": "coverUrl",
    "ruleBookUrl": "bookUrl", "ruleChapterList": "chapterList",
    "ruleChapterName": "chapterName", "ruleChapterUrl": "chapterUrl",
    "ruleContent": "content", "ruleTocUrl": "tocUrl", "ruleCanReName": "canReName",
    "ruleNextTocUrl": "nextTocUrl", "ruleNextContentUrl": "nextContentUrl",
}


def norm_region(val):
    if isinstance(val, str) and not val.strip().startswith("<js"):
        try:
            val = json.loads(val)
        except Exception:
            return None
    if isinstance(val, dict):
        return {KEY_ALIAS.get(k, k): v for k, v in val.items()}
    return val


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("booksource")
    ap.add_argument("--keyword", default="剑来", help="搜索实测用的关键词(默认 剑来)")
    ap.add_argument("--workdir", help="工作目录, 存抓到的 HTML(默认自动建临时目录)")
    ap.add_argument("--impersonate", default="chrome124")
    ap.add_argument("--cookie", help="附加 Cookie 头, 如 'is_human=xxx; cf_clearance=yyy'"
                                     " (已种好 cookie 才能取内容的站点用它跑完整闭环)")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    try:
        with open(args.booksource, encoding="utf-8-sig") as _f:
            src = json.load(_f)
        if isinstance(src, list):
            # App 导入格式是数组; 取第一个书源实测(多书源文件请拆开或逐个传)
            if not src:
                print("书源文件是空数组"); sys.exit(2)
            if len(src) > 1:
                print("提示: 文件含 %d 个书源, 实测第 1 个" % len(src))
            src = src[0]
    except Exception as e:
        print("无法读取书源: %s" % e); sys.exit(2)

    workdir = args.workdir or tempfile.mkdtemp(prefix="legado_verify_")
    os.makedirs(workdir, exist_ok=True)
    print("工作目录(抓到的真实页面在此): %s" % workdir)

    global EXTRA_COOKIE
    EXTRA_COOKIE = args.cookie or None
    if EXTRA_COOKIE:
        print("[cookie] 已附加: %s" % (EXTRA_COOKIE[:60] + ("..." if len(EXTRA_COOKIE) > 60 else "")))
    apply_source_header(src)
    if SOURCE_UA:
        print("[UA] 使用书源声明的 User-Agent: %s" % (SOURCE_UA[:80] + ("..." if len(SOURCE_UA) > 80 else "")))
    sess, backend = build_session(args.impersonate)
    print("[backend] %s" % backend)

    base = str(src.get("bookSourceUrl") or "").rstrip("/")
    timeout = args.timeout

    samples = {}  # name -> html path

    def fetch_and_save(name, url, referer=None, method="GET", data=None, charset=None):
        if not url:
            print("[%s] 无 URL, SKIP" % name); return None
        s = _cf["sess"] or sess
        print("[%s] 抓取 %s" % (name, url))
        resp, err = do_fetch(s, url, method=method, data=data, referer=referer, timeout=timeout, charset=charset)
        if err or resp is None:
            print("      FAIL 抓取: %s" % (err or "无响应")); return None
        try:
            body = resp.text
        except Exception:
            body = resp.content.decode("utf-8", errors="ignore")
        # —— 先查"自建验证页(明文cookie)"，再查 CF：此类页面标题也含"访问验证"会被 CF 误判 ——
        if 'encryptedCookieValue' in body:
            body2 = handle_verification_page(s, url, body)
            if not body2:
                print("      [验证页] 过验证失败, 本页 SKIP"); return None
            body = body2
        # —— 反爬增强: 检测到 CF 挑战页, 尝试真实浏览器绕过(自动) ——
        if HAVE_BYPASS and resp is not None and not _cf["tried"] and looks_like_cf(body):
            print("      [CF] 检测到 Cloudflare 挑战页, 启动真实浏览器绕过...")
            cf_s, cf_ua, ok = bypass_cf.get_cf_session(url)
            _cf["tried"] = True
            if ok and cf_s is not None:
                _cf["sess"] = cf_s
                print("      [CF] 已拿到 cf_clearance(仅本地验证用, 不写死进书源), 用新会话重抓本页")
                resp, err = do_fetch(cf_s, url, method=method, data=data, referer=referer, timeout=timeout, charset=charset)
                if err or resp is None:
                    # 重抓也可能失败(CF 会话秒过期/网络抖动): 必须判空再用。
                    # 旧代码直接 resp.text, resp 为 None 时 AttributeError 整个脚本崩栈。
                    print("      [CF] 新会话重抓失败: %s, 本页 SKIP" % (err or "无响应"))
                    return None
                try:
                    body = resp.text
                except Exception:
                    body = resp.content.decode("utf-8", errors="ignore")
                if 'encryptedCookieValue' in body:
                    body2 = handle_verification_page(cf_s, url, body)
                    if body2: body = body2
            else:
                print("      [CF] 真实浏览器未能过 CF(数据中心 IP 可能被标记), 本页 SKIP")
                return None
        if looks_like_cf(body):
            print("      [CF] 仍是挑战页, 本页 SKIP(架构性拦截, 请改用发现频道/Webview)"); return None
        print("      OK HTTP %s, %d 字节" % (resp.status_code, len(body)))
        p = os.path.join(workdir, name + ".html")
        with open(p, "w", encoding="utf-8") as _f:
            _f.write(body)
        samples[name] = p
        return body

    # ---- 1) 字段校验 ----
    print("\n" + "=" * 50)
    print("步骤1: 字段完整性校验")
    print("=" * 50)
    try:
        vproc = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "validate_booksource.py"), args.booksource],
                               capture_output=True, text=True, timeout=120)
        print(vproc.stdout)
        field_ok = (vproc.returncode == 0)
    except subprocess.TimeoutExpired:
        print("字段校验超时(120s): validate_booksource.py 无响应, 按 FAIL 继续")
        field_ok = False

    # ---- 2) 搜索页 ----
    su = norm_region(src.get("searchUrl"))
    search_html = None
    search_url = None
    raw_search = src.get("searchUrl")
    if isinstance(raw_search, str) and raw_search.strip().startswith("<js"):
        # <js> 动态搜索URL: 模拟"验证页取明文cookie → 带cookie请求"两步流程
        url = _js_url_template(raw_search, args.keyword)
        if not url:
            print("[search] <js> searchUrl 未能解析出请求URL, SKIP")
        else:
            search_url = url
            print("[search] 抓取(js两步) %s" % url)
            s0 = _cf["sess"] or sess
            resp, err = do_fetch(s0, url, referer=base, timeout=timeout)
            body = None if (err or resp is None) else resp.text
            if err or resp is None:
                print("      FAIL 抓取: %s" % (err or "无响应"))
            elif 'encryptedCookieValue' in (body or ""):
                # 顺序关键: 自建验证页的标题也叫"访问验证", 先判 CF 会被误杀,
                # 于是永远走不到"提取明文 cookie 再重抓"这一步。
                body = handle_verification_page(s0, url, body, raw_search)
                if body and looks_like_cf(body):
                    print("      [CF] 过验证后仍是挑战页, SKIP"); body = None
            elif looks_like_cf(body or ""):
                print("      [CF] 挑战页, SKIP"); body = None
            # 统一落盘: 原流程把保存写在 else 分支里, 过验证成功那条路径不会保存,
            # 于是后续详情/目录/正文全部拿不到样本而 SKIP。
            if body:
                print("      OK HTTP %s, %d 字节" % (resp.status_code, len(body)))
                p = os.path.join(workdir, "search.html")
                with open(p, "w", encoding="utf-8") as _f:
                    _f.write(body)
                samples["search"] = p
                search_html = body
    else:
        # 纯字符串 URL(支持 {{key}} 占位符, Legado 自动编码) 或 对象化 {url,method,body}
        search_charset = None
        search_webview = False
        if isinstance(raw_search, str):
            tpl = raw_search.replace("{{key}}", args.keyword)
            search_url, opts = split_url_options(tpl)
            search_url = urljoin(base + "/", search_url) if not search_url.startswith("http") else search_url
            method = "POST" if (isinstance(opts, dict) and str(opts.get("method", "")).upper() == "POST") else "GET"
            data = None
            if method == "POST" and isinstance(opts, dict):
                data = (opts.get("body") or "").replace("{{key}}", args.keyword)
            search_charset = opts.get("charset") if isinstance(opts, dict) else None
            search_webview = bool(isinstance(opts, dict) and opts.get("webView"))
        elif isinstance(su, dict) and su.get("url"):
            tpl = su["url"].replace("{{key}}", args.keyword)
            search_url, opts = split_url_options(tpl)
            search_url = urljoin(base + "/", search_url) if not search_url.startswith("http") else search_url
            method = su.get("method", "GET")
            data = None
            if method.upper() == "POST":
                data = (su.get("body") or "").replace("{{key}}", args.keyword)
            search_charset = su.get("charset")
            search_webview = bool(su.get("webView"))
        else:
            search_url = None
        if search_url:
            if search_webview:
                # webView 站(JS 挑战/客户端解密每请求必现): 本地 curl 跑不了 JS, 无法真验, 标注 SKIP 交真机
                print("[search] 检测到 webView 选项(JS 挑战/解密站): 本地 curl 无法跑 JS, 本页 SKIP(请真机验证)")
                search_html = None
            else:
                # fetch_and_save 内部已自行处理"自建验证页(明文cookie)"与 Cloudflare,
                # 返回时 body 必不含 encryptedCookieValue(否则已在内部 SKIP/重试),
                # 原 598-607 的重试分支为不可达死代码, 已删除。
                search_html = fetch_and_save("search", search_url, referer=base, method=method, data=data, charset=search_charset)

    # ---- 3) 发现频道首条入口(用于回退取书) ----
    explore_html = None
    explore_entry_url = None
    explore_rule_bookurl = None
    explore_rule_booklist = None
    ev = norm_region(src.get("exploreUrl"))  # 解析字符串化 JSON(如 "[{...},{...}]")
    top_re = norm_region(src.get("ruleExplore"))  # 顶层 ruleExplore(所有入口共用)
    if isinstance(ev, list) and ev:
        e0 = ev[0]
        if isinstance(e0, dict):
            e0_url, e0_opts = split_url_options(str(e0.get("url", "")).replace("{{page}}", "1"))  # 验证取第一页
            explore_entry_url = urljoin(base + "/", e0_url) if not e0_url.startswith("http") else e0_url
            re_ = norm_region(e0.get("ruleExplore")) or top_re  # 某项缺则回退顶层
            if isinstance(re_, dict):
                explore_rule_bookurl = re_.get("bookUrl")
                explore_rule_booklist = re_.get("bookList", "")
            if e0_opts and e0_opts.get("webView"):
                print("[explore] 检测到 webView 选项(JS 挑战/解密站): 本地 curl 无法跑 JS, SKIP(请真机验证)")
            else:
                explore_html = fetch_and_save("explore", explore_entry_url, referer=base)
    elif isinstance(ev, dict):
        ev_url, ev_opts = split_url_options(str(ev.get("url", "")).replace("{{page}}", "1"))
        explore_entry_url = urljoin(base + "/", ev_url) if not ev_url.startswith("http") else ev_url
        re_ = norm_region(ev.get("ruleExplore")) or top_re
        explore_rule_bookurl = re_.get("bookUrl") if isinstance(re_, dict) else None
        if isinstance(re_, dict):
            explore_rule_booklist = re_.get("bookList", "")
        if ev_opts and ev_opts.get("webView"):
            print("[explore] 检测到 webView 选项(JS 挑战/解密站): 本地 curl 无法跑 JS, SKIP(请真机验证)")
        else:
            explore_html = fetch_and_save("explore", explore_entry_url, referer=base)

    # ---- 4) 推导首本书 URL(优先搜索, 回退发现) ----
    book_url = None
    if search_html:
        # 规则位置: 优先顶层 ruleSearch(真实 schema); 旧写法内嵌 searchUrl 对象
        rs = norm_region(src.get("ruleSearch"))
        if isinstance(rs, dict) and rs.get("bookUrl"):
            rule_bookurl = rs.get("bookUrl", "")
            rule_booklist = rs.get("bookList", "")
        elif isinstance(su, dict):
            rule_bookurl = su.get("bookUrl", "")
            rule_booklist = su.get("bookList", "")
        else:
            rule_bookurl = ""
            rule_booklist = ""
        href = None
        if rule_bookurl:
            # Legado 语义: bookUrl 相对 bookList 的**首个节点**求值。裸 '@href' 以前用
            # first_match 对全文档取"第一个含 href 的元素" —— 那往往是页面顶部导航/logo 链,
            # 推出的书 URL 是错的(后续详情/目录/正文全部歪)。有容器一律走 first_link_from_list。
            if rule_booklist:
                href = first_link_from_list(search_html, rule_booklist, rule_bookurl)
            else:
                href = first_match(search_html, rule_bookurl)
            if href:
                href = _apply_clean_ops(href, rule_bookurl)
        if href:
            book_url = urljoin(search_url or base + "/", href)
    if not book_url and explore_html and explore_rule_bookurl:
        if explore_rule_booklist:
            href = first_link_from_list(explore_html, explore_rule_booklist, explore_rule_bookurl)
        else:
            href = first_match(explore_html, explore_rule_bookurl)
        if href:
            href = _apply_clean_ops(href, explore_rule_bookurl)
        if href:
            book_url = urljoin(explore_entry_url or base + "/", href)

    # ---- 5) 详情页 ----
    bookinfo_html = None
    if book_url:
        bookinfo_html = fetch_and_save("bookinfo", book_url, referer=base)
    bi = norm_region(src.get("ruleBookInfo"))
    toc_url = None
    if bookinfo_html and isinstance(bi, dict):
        # 目录页链接: 真实 schema 键为 tocUrl(旧写法叫 ruleChapterUrl)
        href = first_match(bookinfo_html, bi.get("tocUrl") or bi.get("ruleChapterUrl") or "")
        if href:
            toc_url = urljoin(book_url or base + "/", href)

    # ---- 6) 目录页 ----
    toc_html = None
    if toc_url:
        toc_html = fetch_and_save("toc", toc_url, referer=base)
    tc = norm_region(src.get("ruleToc"))
    content_url = None
    if toc_html and isinstance(tc, dict):
        # 首章 URL 必须相对 chapterList 首个节点取(裸 @href 不能直接对文档跑)
        href = first_link_from_list(toc_html, tc.get("chapterList", ""), tc.get("chapterUrl", ""))
        if href:
            href = _apply_clean_ops(href, tc.get("chapterUrl", ""))
        if href:
            content_url = urljoin(toc_url or base + "/", href)

    # ---- 7) 正文页 ----
    if content_url:
        fetch_and_save("content", content_url, referer=base)

    # ---- 8) 跑 test_parse ----
    print("\n" + "=" * 50)
    print("步骤2: 解析命中验证(test_parse, 基于上述真实页面)")
    print("=" * 50)
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "test_parse.py"), args.booksource]
    if "search" in samples:
        cmd += ["--search", samples["search"]]
    if "explore" in samples:
        cmd += ["--explore", samples["explore"]]
    if "bookinfo" in samples:
        cmd += ["--bookinfo", samples["bookinfo"]]
    if "toc" in samples:
        cmd += ["--toc", samples["toc"]]
    if "content" in samples:
        cmd += ["--content", samples["content"]]
    try:
        tproc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(tproc.stdout)
    except subprocess.TimeoutExpired:
        print("解析超时(300s): test_parse.py 无响应, 跳过解析结果")

    # ---- 9) 汇总 ----
    print("=" * 50)
    print("汇总")
    print("=" * 50)
    print("字段完整性 : %s" % ("PASS" if field_ok else "FAIL(见上)"))
    got = [k for k in ("search", "explore", "bookinfo", "toc", "content") if k in samples]
    skip = [k for k in ("search", "explore", "bookinfo", "toc", "content") if k not in samples]
    print("已抓样本   : %s" % (", ".join(got) if got else "无"))
    if skip:
        print("未抓样本   : %s (SKIP, 多为硬防护/Turnstile/受保护接口)" % ", ".join(skip))
    if not got:
        print("解析命中   : 未判定(本地零样本 —— 全部入口被硬防护/WebView 挡住, 无法真实抓取)")
        print("            本源疑似需真机 WebView 过 JS 挑战, 请用户在 App 内实测搜索/目录/正文后再判定")
        overall = "UNKNOWN"
    else:
        # 判定以 test_parse 退出码为准: 0=核心字段全命中(JS 规则中性跳过也算 0);
        # 1=有核心字段 MISS/ERR; 其它=用法错误/崩溃 → 未判定。
        # 旧实现 Match stdout 文案("核心字段全部命中 OK"), 而带 JS 规则的书源输出的是
        # "核心字段本地命中 OK; 另有 N 项 JS 规则需 App 真机验证" —— 不含那句文案,
        # 于是凡有 JS 规则的书源都被误判成 UNKNOWN(明明本地全绿)。
        rc = tproc.returncode
        if rc == 0:
            print("解析命中   : PASS")
            overall = "PASS"
        elif rc == 1:
            print("解析命中   : FAIL —— 请读上方 [MISS]/[ERR] 报告, 回看 %s 里的真实 HTML 修正规则后重跑本脚本" % workdir)
            overall = "FAIL"
        else:
            print("解析命中   : 未判定(test_parse 退出码 %s: 用法/解析错误或崩溃)" % rc)
            overall = "UNKNOWN"
    print("-" * 50)
    print("总体结果   : %s" % overall)
    print("工作目录   : %s" % workdir)
    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
