# -*- coding: utf-8 -*-
"""
真机等价回归 (real-device equivalence): 校验器(test_parse.eval_rule_jsoup) 的输出
必须与真机 Jsoup 引擎的行为逐值一致, 否则就是「校验绿了但真机跑不出来」的漏报。

golden 值的来源 (铁律: 真机验证优先):
    用 Java 20 + 真 org.jsoup (jsoup-1.17.2.jar) 复刻 Legado 3.25 默认 JSOUP 引擎的
    `@` 层级语义, 对用户书源「吾看书」的真实规则做实测锁为 golden。
    关键结论(反编译 AnalyzeByJSoup 实证): Legado 对 [attr~=val] 等扩展属性选择器**不做
    任何自定义处理**, 直接委托 Jsoup 原生引擎 -> 这类规则 bs4 无法等价建模。因此校验器已
    内置「真 Jsoup 通道」(_jsoup_real_eval): 检测到 ~= 等操作符的规则路由于此(问号形态亦走此通道,
    得到真机一致的恒空——Jsoup 把 ? 解析进属性名, [attr?=val] 恒不命中, 真机同结果);
    本地有 jar/Java 时直接用真 Jsoup 求值, 实现与真机逐值一致; jar 缺失时优雅降级为 JSOUP_EXT(需真机验证)。

    为什么用 jsoup-1.17.2 而非 APK 内嵌版本: Legado 3.25 捆绑的 Jsoup 版本号已被内联,
    1.17.2 是同一主版本区间的代理; 该回归锁定的「值级行为」在此版本下已确认, 未来若要从
    APK 抽取真 Jsoup 做精确对齐, 只需替换 jar 并复跑 JsoupPilot 重新生成 golden。

运行: python3 evals/jsoup_realdevice_equiv.py [-v]
    也可由 run_evals.py 统一调度(见其 main 中的 realdevice_equiv_test 调用)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import test_parse as T  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

# ---- 内联夹具（取自站点真实响应片段）----
BOOKINFO = """<html><head>
<meta property="og:novel:author" content="佚名">
<meta property="og:image" content="https://x/cover.jpg">
<meta property="og:description" content="这是简介">
<meta property="og:novel:book_name" content="测试书">
<meta property="category" content="玄幻">
<meta property="status" content="连载">
</head><body><a class="查看更多章节" href="/desc.html">查看更多章节</a></body></html>"""

TOC = """<html><body><div class="info_chapters"><ul>
<li><a href="/c/1.html">第一章</a></li>
<li><a href="/c/2.html">第二章</a></li>
<li><a href="/c/3.html">第三章</a></li>
</ul><select class="page"><option value="/toc1.html">1</option><option value="/toc2.html">2</option></select></div></body></html>"""

CONTENT = """<html><body><div id="novelcontent"><p>第一段正文。</p><p>第二段正文。</p></div></body></html>"""

# 「正文以 <script> 为载体」的站点形态(百草露 m.baicaolu.com 2026-10-31 实证):
# 真机 @html 会先删 script 再取 outerHtml -> 拿到只剩提示语的空容器(长度 127);
# 要拿到脚本内容必须用 @all。这对 golden 钉住该差异, 防后人把 @html 改回 innerHTML。
SCRIPT_CONTENT = """<html><body><div id="txt"><p><b>提示</b></p><script>document.writeln(obf.mg('PHA+5q2j5paH44CCPC9wPg=='))</script></div></body></html>"""

SEARCH = """<html><body><div class="block"><ul>
<li><span>作者甲</span><a href="/b/1.html">书名一</a></li>
<li><span>作者乙</span><a href="/b/2.html">书名二</a></li>
<li><span>作者丙</span><a href="/b/3.html">书名三</a></li>
</ul></div></body></html>"""

# (region, rule, note, mode, expect)
#   mode="vals"  -> 精确值级断言: eval_rule_jsoup 返回的列表 == expect (顺序+去重后)
#   mode="ext"   -> 扩展属性专属: 必须降级为 JSOUP_EXT(真机支持但 bs4 无等价语义, 硬求值会假阴性)
# expect 对 "vals" 为 golden 列表; 对 "ext" 为 None
CASES = [
    ("bookinfo", '[property="og:novel:author"]@content', "带引号og:author", "vals", ["佚名"]),
    ("bookinfo", '[property="og:image"]@content',        "带引号og:image",  "vals", ["https://x/cover.jpg"]),
    ("bookinfo", '[property="og:description"]@content',  "带引号og:description", "vals", ["这是简介"]),
    ("bookinfo", '[property="og:novel:book_name"]@content', "带引号og:book_name", "vals", ["测试书"]),
    # ~= 扩展属性: 校验器走真 Jsoup 通道, 必须逐值等于真机(玄幻/连载); 通道不可用时退化为 "ext" 判定
    ("bookinfo", '[property~=category|status|update_time]@content', "扩展属性~=真机求值", "vals", ["玄幻", "连载"]),
    ("bookinfo", '[property~=las?test_chapter_name]@content',      "扩展属性~=真机求值(空)", "vals", []),
    # ?= 幻影固化(2026-10-25 审计实证): ?= 不是 Jsoup 操作符, ? 被解析进属性名,
    # [attr?=val] 恒不命中、不报错 —— 反编译坐实选择器透传 select(), 真机同结果(静默取空)。
    # 本用例把"写了不报错但恒空"这一真机行为钉成回归, 防止后人再把 ?= 当操作符"修复"。
    ("bookinfo", '[property?=og:novel:author]@content',            "幻影操作符?=恒不命中(真机同结果)", "vals", []),
    ("bookinfo", 'text.查看更多章节@href##$##desc.html', "tocUrl整串替换", "vals", ["desc.html"]),
    ("bookinfo", '[property=og:novel:author]@content',  "[UNQUOTED] 未引号og:author", "vals", ["佚名"]),
    ("toc",      '-.info_chapters@ul@li@a@text', "目录章节名(-倒置)", "vals", ["第三章", "第二章", "第一章"]),
    ("toc",      '-.info_chapters@ul@li@a@href', "目录章节URL(-倒置)", "vals", ["/c/3.html", "/c/2.html", "/c/1.html"]),
    ("toc",      'option@value',                 "nextTocUrl", "vals", ["/toc1.html", "/toc2.html"]),
    # 3.25 真机 "html": elements.select("script").remove() 后取 elements.outerHtml(),
    # 是 **单条** 拼接结果(不是逐元素各一条)。旧 golden 按逐元素 innerHTML 写, 与真机不符。
    ("content",  '#novelcontent@p@html',         "正文html(单条outerHtml)", "vals", ["<p>第一段正文。</p>\n<p>第二段正文。</p>"]),
    ("content",  '#novelcontent@all',            "正文all(outerHtml)", "vals", ["<div id=\"novelcontent\">\n <p>第一段正文。</p>\n <p>第二段正文。</p>\n</div>"]),
    ("scriptc",  '#txt@html',                    "html删script(真机空壳)", "vals", ["<div id=\"txt\">\n <p><b>提示</b></p>\n</div>"]),
    ("scriptc",  '#txt@all',                     "all保留script(正文载体)", "vals", ["<div id=\"txt\">\n <p><b>提示</b></p>\n <script>document.writeln(obf.mg('PHA+5q2j5paH44CCPC9wPg=='))</script>\n</div>"]),
    ("search",   '.block@ul@li@a@text',          "搜索书名(JSOUP式)", "vals", ["书名一", "书名二", "书名三"]),
    ("search",   '.block@ul@li@a@href',          "搜索bookUrl(JSOUP式)", "vals", ["/b/1.html", "/b/2.html", "/b/3.html"]),
    ("search",   '.block@ul@li@span@text',       "搜索作者(JSOUP式)", "vals", ["作者甲", "作者乙", "作者丙"]),
]


def realdevice_equiv_test(verbose=False):
    """返回 (all_ok, lines)。逐条断言校验器输出 == 真机 Jsoup golden。"""
    if not T.HAVE_BS4:
        return False, ["[FAIL] bs4 未安装, 真机等价回归无法进行"]
    docs = {
        "bookinfo": BeautifulSoup(BOOKINFO, "html.parser"),
        "toc": BeautifulSoup(TOC, "html.parser"),
        "content": BeautifulSoup(CONTENT, "html.parser"),
        "scriptc": BeautifulSoup(SCRIPT_CONTENT, "html.parser"),
        "search": BeautifulSoup(SEARCH, "html.parser"),
    }
    ok = True
    lines = []
    # 真 Jsoup 求值通道(jar + Java)是否可用。文档承诺: 通道不可用时 ~= 用例不是规则错误,
    # 必须降级为 JSOUP_EXT 判定(需真机验证), 否则无 jar 环境会把「环境缺失」误报成「假 FAIL」,
    # 拖垮 run_evals 的整包回归。
    ch_ok = T._jsoup_engine_available()
    degraded = 0
    for region, rule, note, mode, expect in CASES:
        vals, err = T.eval_rule_jsoup(docs[region], rule)
        degrade = bool(T._LEGADO_EXT_ATTR.search(rule)) and not ch_ok
        if degrade:
            # 通道不可用: 判定「优雅降级为 JSOUP_EXT」本身正确(不假通过、不误报非法)
            degraded += 1
            passed = (err == T.JSOUP_EXT)
            got = "JSOUP_EXT(降级:通道不可用,需真机验证)" if passed else "ERR:%s" % err
        elif mode == "ext":
            passed = (err == T.JSOUP_EXT)
            got = "JSOUP_EXT" if err == T.JSOUP_EXT else ("err=%s" % err if err else "vals=%s" % vals)
        else:
            passed = (err is None) and (vals == expect)
            got = vals if err is None else "ERR:%s" % err
        ok = ok and passed
        lines.append("[%s] %-46s got=%s" % ("PASS" if passed else "FAIL", note, got))
    if degraded:
        lines.append("[INFO] %d 条 ~= 用例因通道不可用降级为 JSOUP_EXT 判定(需真机验证)" % degraded)
    return ok, lines


if __name__ == "__main__":
    ok, lines = realdevice_equiv_test(verbose="-v" in sys.argv)
    print("===== 真机等价回归 (校验器 vs 真机 Jsoup golden) =====")
    for ln in lines:
        print("  " + ln)
    n_pass = sum(1 for l in lines if l.startswith("[PASS]"))
    n_total = n_pass + sum(1 for l in lines if l.startswith("[FAIL]"))
    print("RESULT: %s (%d/%d)" % ("ALL PASS" if ok else "FAIL", n_pass, n_total))
    sys.exit(0 if ok else 1)
