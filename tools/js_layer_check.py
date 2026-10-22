#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
js_layer_check.py —— 在 Node 里执行书源的 webJs / URL 选项 `js` 字段, 注入绑定桩,
捕获「静态校验 + Playwright 时序模拟都碰不到」的 JS 层 bug。

为什么需要它(技能复盘清单 P3.9):
    validate_booksource.py 只查字段静态正确性, realcheck.py 只模拟 webView 时序, 两者都**不执行**
    书源真正跑的 JS(webJs / `js` 字段, 运行在 Legado 的 Rhino, 绑定 document/location/cookie/java/source)。
    这类 bug(语法错、运行时抛异常、return null 死循环、把 about:blank 当完成返回)正是 shumi99 当年
    60s 卡死(about:blank 死局)的根 —— 当时静态/时序全绿, 真机才暴露。本脚本在离线、确定性地提前发现。

注意边界(Node V8 ≠ Rhino Java 后端, 是近似执行):
    - 能抓: 语法错误、运行时异常、return null/about:blank 反模式、cookie 桩行为。
    - 抓不了: 某个 java.* 方法在 3.25 是否真实存在(那部分靠 legend-js-api.md 对照 APK jsHelp.md 解决)。
    - 替代不了真机/真站网络验证。

用法:
    python3 scripts/js_layer_check.py --source <书源.json> [--html 夹具.html] [--url URL] [--cookie "k=v"]
    python3 scripts/js_layer_check.py --js "(function(){...})()" [--html ...] [--url ...]
    python3 scripts/js_layer_check.py --self-test        # 内置回归, 全过则 exit 0

    --code <验证码>: 注入 java.getVerificationCode() 桩的返回值(模拟用户在弹窗里输入的码)。
        用于验证 loginCheckJs 的人工弹码路径(java.getVerificationCode)真的被走到, 而不是静默跳过。
        命中时输出会带 "弹码=True(java.getVerificationCode)"。
    --ajax-body <字符串>: 注入 java.ajax() 桩的兜底返回体(非取码/提交接口时返回), 默认空串。
    --captcha-b64 <base64>: 注入取码接口(get_btwaf_captcha_base64)返回的图片 base64,
        默认占位 'data:image/jpg;base64,AAAA'。用于验证"取码接口返回内容不同"时的分支。
"""
import os
import sys
import json
import tempfile
import shutil
import subprocess
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)


def find_node():
    return shutil.which("node")


# ---- Node 执行器: 读取 config.json + user.js, 注入桩后运行, 输出 JSON ----
HARNESS = r"""
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function main() {
  const dir = process.argv[2];
  const cfg = JSON.parse(fs.readFileSync(path.join(dir, 'config.json'), 'utf8'));
  const code = fs.readFileSync(path.join(dir, 'user.js'), 'utf8');

  // ---- 注入桩 (近似 Legado webJs/`js`/loginCheckJs 字段的 Rhino 绑定) ----
  const cookieStore = {};
  if (cfg.initialCookie) cookieStore[cfg.url || ''] = cfg.initialCookie;
  let _connectCalled = false;
  let _verificationAsked = false;
  const cookie = {
    getCookie: (u) => (cookieStore[u] != null ? cookieStore[u] : ''),
    getKey: (u, k) => {
      const c = cookieStore[u] || '';
      const m = c.split(';').map(s => s.trim()).find(s => s.startsWith(k + '='));
      return m ? m.slice(k.length + 1) : '';
    },
    setCookie: (u, v) => { cookieStore[u] = v; },
    replaceCookie: (u, v) => { cookieStore[u] = v; },
    removeCookie: (u) => { delete cookieStore[u]; },
  };
  const java = {
    getWebViewUA: () => 'Mozilla/5.0 (Linux; Android) AppleWebKit/537.36',
    // ajax：必须能返回"取码/提交"接口的 JSON, 否则 loginCheckJs 的弹码分支永远进不去,
    //       会把"正确写法"误判成"没弹码"(BTWAF 类书源踩过)。见 site-patterns.md BTWAF 章节。
    ajax: (u) => {
      const s = String(u == null ? '' : u);
      if (s.indexOf('get_btwaf_captcha_base64') > -1) {
        return JSON.stringify({ msg: cfg.captchaB64 || 'data:image/jpg;base64,AAAA', status: true });
      }
      if (s.indexOf('Verification_auth_btwaf') > -1) {
        return JSON.stringify({ msg: '验证成功', status: true });
      }
      return (cfg.ajaxBody != null ? cfg.ajaxBody : '');
    },
    // connect 记录调用并可在重取时返回"重取后的内容"(fixtureHtml2), 用于验证 loginCheckJs 重取逻辑
    connect: (u) => { _connectCalled = true; return {
      body: () => (cfg.fixtureHtml2 != null ? cfg.fixtureHtml2 : (cfg.fixtureHtml || '')),
      code: () => 200, url: () => u || cfg.url || '', headers: () => ({}) }; },
    post: () => ({}), head: () => ({}), webView: () => '',
    // 验证码弹窗(GoEdge/CF 等人工码): 3.25 官方 API java.getVerificationCode(imageUrl)
    // 桩返回可注入的码(cfg.verificationCode), 并标记被调用过, 便于验证 loginCheckJs 的弹码路径
    getVerificationCode: (u) => { _verificationAsked = true; return (cfg.verificationCode || '123456'); },
    startBrowser: () => '', startBrowserAwait: () => ({ body: () => '', toString: () => '' }),
    log: () => {}, toast: () => {}, longToast: () => {},
    get: () => '', put: () => '', getString: () => '', getStringList: () => [],
    getElement: () => null, getElements: () => [],
  };
  const source = { getKey: () => cfg.url || '', getVariable: () => '', setVariable: () => {} };

  const document = {
    documentElement: { outerHTML: cfg.fixtureHtml != null ? cfg.fixtureHtml : '' },
    cookie: '',
  };
  const location = { href: cfg.url || '', replaced: null, replace: (u) => { location.replaced = u; } };

  // ---- loginCheckJs 桩: result 是每次请求后的响应对象(StrResponse) ----
  const result = {
    body: () => (cfg.fixtureHtml != null ? cfg.fixtureHtml : ''),
    url: () => cfg.url || '',
    code: () => cfg.code || 200,
    headers: () => ({ entrySet: () => ({ iterator: () => ({ hasNext: () => false, next: () => null }) }) }),
  };

  // vm.runInNewContext 与 Rhino 脚本求值等价: 取"完成值"
  const ctx = { document, location, cookie, java, source, result, console };
  let r;
  try {
    r = vm.runInNewContext(code, ctx);
  } catch (e) {
    const stage = (e instanceof SyntaxError) ? 'compile' : 'run';
    process.stdout.write(JSON.stringify({
      ok: false, error: (stage === 'compile' ? 'SyntaxError: ' : 'RuntimeError: ') + e.message, stage,
    }));
    return;
  }
  const isLogin = (cfg.kind === 'loginCheckJs');
  if (!isLogin) {
    // webJs / `js` 字段：返回字符串(HTML)或 null；用 about:blank 判据识别"把未就绪当完成"
    const returnedNull = (r === null || r === undefined);
    const s = returnedNull ? '' : String(r);
    const isAboutBlank = !returnedNull && (
      s.indexOf('about:blank') >= 0 || s.length <= 39 || /<html><head><\/head><body><\/body><\/html>/.test(s)
    );
    process.stdout.write(JSON.stringify({
      ok: true, error: null, returnedNull, returnedLen: s.length, returned: s.slice(0, 2000),
      replaced: location.replaced, isAboutBlank, cookieAfter: cookieStore[cfg.url || ''] || '',
      connectCalled: _connectCalled, verificationAsked: _verificationAsked,
    }));
  } else {
    // loginCheckJs：返回 result 响应对象或 null；result 不是 HTML, 不应用 about:blank 判据。
    // 返回字符串时如实回传(便于断言"弹码拿到的码"等), 返回 result 对象则用占位符。
    const returnedNull = (r === null || r === undefined);
    const shown = (typeof r === 'string') ? r.slice(0, 2000) : '[loginCheckJs result]';
    process.stdout.write(JSON.stringify({
      ok: true, error: null, returnedNull, returned: shown,
      replaced: location.replaced, isAboutBlank: false,
      cookieAfter: cookieStore[cfg.url || ''] || '', connectCalled: _connectCalled,
      verificationAsked: _verificationAsked,
    }));
  }
}
main();
"""


def run_one(node, code, fixture_html, url, initial_cookie, fixture_html2="", kind="",
            verification_code="", ajax_body=None, captcha_b64=None):
    """在 Node 里跑一段书源 JS, 返回解析后的结果 dict; 失败返回 {ok:False, error}。
    fixture_html2: loginCheckJs 重取(java.connect)后返回的"真实内容"夹具。
    kind: webJs / js / loginCheckJs, 影响 HARNESS 的判据分支。
    verification_code: 注入 java.getVerificationCode() 桩的返回值(模拟用户输入的验证码);
        不传则桩返回默认 '123456'。用它验证 loginCheckJs 走的是弹码路径而不是静默跳过。
    ajax_body: 注入 java.ajax() 桩的兜底返回体(非取码/提交接口时返回); 不传则空串。
    captcha_b64: 注入取码接口返回的 base64 图片内容; 不传则用内置占位 'data:image/jpg;base64,AAAA'。
        ⚠️ 这两个必须有 CLI 入口(--ajax-body/--captcha-b64), 否则就是"桩读了却永远取默认值"的死配置。
    """
    d = tempfile.mkdtemp(prefix="js_layer_")
    try:
        with open(os.path.join(d, "user.js"), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            cfg = {"fixtureHtml": fixture_html, "url": url,
                   "initialCookie": initial_cookie or "", "fixtureHtml2": fixture_html2,
                   "kind": kind, "verificationCode": verification_code or ""}
            if ajax_body is not None:
                cfg["ajaxBody"] = ajax_body
            if captcha_b64 is not None:
                cfg["captchaB64"] = captcha_b64
            json.dump(cfg, f)
        with open(os.path.join(d, "harness.js"), "w", encoding="utf-8") as f:
            f.write(HARNESS)
        proc = subprocess.run([node, os.path.join(d, "harness.js"), d],
                              capture_output=True, text=True, timeout=30)
        out = (proc.stdout or "").strip()
        if not out:
            return {"ok": False, "error": "node 无输出: " + (proc.stderr or "").strip()[:200]}
        try:
            return json.loads(out)
        except Exception:
            return {"ok": False, "error": "node 输出非 JSON: " + out[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "node 执行超时(30s)"}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def extract_js_from_source(payload):
    """从书源 JSON 抽出所有 JS 片段, 返回 [(where, kind, code)]。
    kind ∈ {webJs, js, loginCheckJs, pipe}。覆盖点与 validate_booksource._collect_js_fragments 对齐：
    顶层 loginCheckJs / 顶层 URL 字段行内选项 webJs·js / 规则组(ruleSearch…ruleContent)内
    bookUrl·chapterUrl·tocUrl·nextContentUrl·content 的行内选项 webJs·js / 规则组 webJs 字段 /
    顶层 searchUrl·exploreUrl 整串 + 所有 rule* 规则组内字符串里的 <js> 管道(含纯 <js> 钩子)。
    v8 复盘新增 loginCheckJs 覆盖后, 又补上「规则组内的 webView webJs」——此前只扫顶层 URL 字段,
    漏掉写在 ruleBookInfo.bookUrl / ruleToc.chapterUrl 等规则组里的 webView webJs, 而 shumi99 v8
    详情/目录/正文的 webView webJs 正是写在那儿(与搜索的 loginCheckJs 分工), 漏扫会让这类 webJs 的
    语法/逻辑错误在本地测不出来(同 v6 翻车一类问题)。
    """
    found = []
    seen = set()
    if isinstance(payload, dict):
        payload = [payload]

    def opt_of(s):
        """按真机 AnalyzeUrl 切分语义(3.25 smali: paramPattern=`\\s*,\\s*(?=\\{)`,
        matcher.find() 取**第一个**「逗号后(可带空白)跟 {」处切开)提取行内选项 JSON。

        旧实现 `s.rfind(",{")` 有两个坑:
          1) 只认无空格的 `,{` —— `url, {"charset":"utf-8"}` 带空格就漏抓(真机允许);
          2) rfind 取**最后**一个 `,{` —— webJs/bodyJs 的 JS 代码里只要含 `,{`(如
             `cookie.setCookie(u,"a=1,{b:2}")`), 抓到的逗号在字符串内部, json.loads
             直接失败 → 该 webJs 静默漏扫。而漏扫正是本工具要防的头号事故
             (webJs 语法错在本地测不出来)。
        改为从左找第一个「逗号后跟 {」再 json.loads 尾部: json.loads 原生支持嵌套
        花括号, 尾部有垃圾会自己抛错, 语义与真机一致且不再误切。
        """
        if not isinstance(s, str):
            return None
        for i, ch in enumerate(s):
            if ch != ",":
                continue
            j = i + 1
            while j < len(s) and s[j].isspace():
                j += 1
            if j < len(s) and s[j] == "{":
                try:
                    return json.loads(s[i + 1:])
                except Exception:
                    return None
        return None

    def add(where, kind, code):
        if isinstance(code, str) and code.strip() and code not in seen:
            seen.add(code)
            found.append((where, kind, code))

    for idx, src in enumerate(payload):
        if not isinstance(src, dict):
            continue
        tag = src.get("bookSourceName", "src%d" % idx)

        def scan_region(region, prefix):
            """扫一个规则组内: bookUrl/chapterUrl/tocUrl/nextContentUrl/content 行内选项的
            webJs·js + 规则组 webJs 字段。"""
            for k in ("bookUrl", "chapterUrl", "tocUrl", "nextContentUrl", "content"):
                v = region.get(k)
                if isinstance(v, str):
                    opt = opt_of(v)
                    if opt:
                        if "webJs" in opt:
                            add(prefix + "." + k + ".webJs", "webJs", opt["webJs"])
                        if "js" in opt:
                            add(prefix + "." + k + ".js", "js", opt["js"])
            if isinstance(region.get("webJs"), str):
                add(prefix + ".webJs", "webJs", region["webJs"])

        def as_region(v):
            """规则组可能是 JSON 字符串(旧 schema), 统一转 dict; 失败返回 None。"""
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    return None
            return v if isinstance(v, dict) else None

        # 顶层 loginCheckJs（每次请求后执行, 绑定 result/cookie/baseUrl/java；返回修改后的 result）
        lc = src.get("loginCheckJs")
        if isinstance(lc, str) and lc.strip():
            add(tag + "/loginCheckJs", "loginCheckJs", lc)
        # 顶层 URL 字段行内选项。searchUrl/exploreUrl 可能是**数组**(Legado 多引擎/多入口
        # 合法结构), 每条 URL 各自可带行内选项 —— 旧实现只按字符串处理, 数组整体漏扫。
        for key in ("searchUrl", "exploreUrl", "bookUrl", "tocUrl", "chapterUrl", "nextContentUrl"):
            raw = src.get(key, "")
            for s in (raw if isinstance(raw, list) else [raw]):
                opt = opt_of(s)
                if opt:
                    if "webJs" in opt:
                        add(tag + "/" + key + ".webJs", "webJs", opt["webJs"])
                    if "js" in opt:
                        add(tag + "/" + key + ".js", "js", opt["js"])
        # 规则组: 行内选项 webJs/js + 规则组 webJs 字段 + <js> 管道
        for grp in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
            region = as_region(src.get(grp))
            if region is not None:
                scan_region(region, tag + "/" + grp)
            # exploreUrl 为数组/对象时, 每个入口可带自己的 ruleExplore(结构 a/b),
            # 旧写法则是对象直接含规则 —— 两者里的 webJs 选项都不能漏。
            if grp == "ruleExplore":
                ev = src.get("exploreUrl")
                entries = ev if isinstance(ev, list) else ([ev] if isinstance(ev, dict) else [])
                for ei, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    re_ = as_region(entry.get("ruleExplore"))
                    if re_ is None and any(k in entry for k in ("bookList", "name", "bookUrl")):
                        re_ = entry  # 旧写法: 对象直接含规则
                    if re_ is not None:
                        scan_region(re_, tag + "/exploreUrl[%d].ruleExplore" % ei)
        # 规则字段里的 <js> 管道: 覆盖顶层 searchUrl/exploreUrl 整串 + 所有 rule* 规则组内字符串。
        # 旧版只认 5 个钩子键(init/bookInfoInit/preUpdateJs/formatJs/content), 解析字段与纯
        # <js> searchUrl 漏扫(与 validate_booksource 同一覆盖范围, 见其 _collect_js_fragments)。
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
                    add(tag + "/%s<js>" % (k or "?"), "pipe", m.group(1))
        walk(src, "")
    return found


ABOUT_BLANK = "<html><head></head><body></body></html>"  # Legado about:blank outerHTML 约 39 字节


def check_source_file(node, source_path, fixture_html, url, initial_cookie, verification_code="",
                      ajax_body=None, captcha_b64=None):
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        # 坏 JSON/BOM/编码问题: 明确报错以输入错误(2)退出, 不把栈抛给用户。
        # 与 main() 里「找不到书源文件」的 exit 2 语义一致(用法/输入错误)。
        print("[FAIL] 书源文件无法解析为 JSON: %s (%s)" % (source_path, e))
        sys.exit(2)
    items = extract_js_from_source(payload)
    if not items:
        print("[NOTE] 该书源未检出 webJs / `js` 字段, 无 JS 层可执行")
        return True
    ok_all = True
    for where, kind, code in items:
        res = run_one(node, code, fixture_html, url, initial_cookie, kind=kind,
                      verification_code=verification_code,
                      ajax_body=ajax_body, captcha_b64=captcha_b64)
        if not res.get("ok"):
            ok_all = False
            print("[FAIL] %s -> %s" % (where, res.get("error")))
        else:
            flag = ""
            if res.get("isAboutBlank"):
                flag = "  ⚠ 返回了 about:blank/空内容, 疑似把未就绪当完成"
                ok_all = False
            extra = ""
            if res.get("connectCalled"):
                extra += " connectCalled=True"
            if res.get("verificationAsked"):
                extra += " 弹码=True(java.getVerificationCode)"
            print("[PASS] %s -> kind=%s returnedNull=%s replaced=%s%s%s" %
                  (where, kind, res.get("returnedNull"), res.get("replaced"), extra, flag))
    return ok_all


def self_test(node):
    """内置回归: 覆盖 about:blank 死局 / 正常页 / 毒 cookie / 语法错 / 运行时异常，
    以及 loginCheckJs 取码「正确 vs 错误写法」配对标本（铁律 22/23: 验证器自身要有能区分正误的自我证伪标本）。"""
    shumi_webjs = (
        "(function(){try{document.cookie='ss_search_delay=1;expires=Thu, 01 Jan 1970 00:00:00 GMT;"
        "path=/';}catch(e){}var h=document.documentElement.outerHTML;var u=location.href;"
        "if(h.indexOf('bookbox')>=0)return h;"
        "if(u.indexOf('shumi99')>=0&&u.indexOf('/search/')>=0&&h.indexOf('history.go')<0){"
        "try{location.replace(u)}catch(e){}return null}return h})()"
    )
    shumi_js = (
        "(function(){var c=cookie.getCookie('http://www.shumi99.com');"
        "if(c.indexOf('ss_search_delay')>=0){var a=c.split(';'),b=[];"
        "for(var i=0;i<a.length;i++){if(a[i].indexOf('ss_search_delay')<0)b.push(a[i]);}"
        "cookie.setCookie('http://www.shumi99.com',b.join(';'));}return null;})()"
    )
    normal_html = '<html><body><div class="bookbox"><a href="/b/1">书名</a></div></body></html>'
    # 403 壳页: 极短 HTML + 一行 window.location.href 跳转脚本(无 bookbox)
    shell_html = '<html><head></head><body></body></html><script> window.location.href ="/search/?searchkey=x"; </script>'
    # loginCheckJs 过 403 壳页: result.body() 是壳页 → 调 java.connect 重取真内容(v8 实战模板)
    logincheck_js = "var b=result.body();if(b&&b.indexOf('window.location.href')>-1&&b.indexOf('bookbox')<0){result=java.connect(result.url());}result;"
    # GoEdge WAF 人工图形验证码页(标题 Verify Yourself, 全站 307 到 /WAF/VERIFY/CAPTCHA)
    waf_html = ('<html><head><title>Verify Yourself</title></head><body><form method="post">'
                '<input type="hidden" name="GOEDGE_WAF_CAPTCHA_ID" value="cid-abc123xyz"/>'
                '<img id="ui-captcha-image" src="/WAF/VERIFY/CAPTCHA/IMAGE?sid=cid-abc123xyz"/>'
                '<input type="text" name="GOEDGE_WAF_CAPTCHA_CODE"/></form></body></html>')
    # 过码模板: 取验证码图绝对地址 → 弹窗要码 → POST 提交 → java.connect 重取真内容
    goed_logincheck_js = (
        "var b=result.body();var code='';"
        "if(b&&b.indexOf('GOEDGE_WAF_CAPTCHA_ID')>-1){"
        "var i=b.indexOf('id=\"ui-captcha-image\"');var j=b.indexOf('src=\"',i);var k=b.indexOf('\"',j+5);"
        "var img=b.substring(j+5,k);"
        "if(img.indexOf('http')!==0){img='https://www.boluomao1.com'+img;}"
        "code=java.getVerificationCode(img);"
        "var i2=b.indexOf('name=\"GOEDGE_WAF_CAPTCHA_ID\"');var j2=b.indexOf('value=\"',i2);var k2=b.indexOf('\"',j2+7);"
        "var cid=b.substring(j2+7,k2);"
        "if(code&&cid){java.post(result.url(),'GOEDGE_WAF_CAPTCHA_ID='+cid+'&GOEDGE_WAF_CAPTCHA_CODE='+code,"
        "{'Content-Type':'application/x-www-form-urlencoded'});result=java.connect(result.url());}}"
        "'cid='+cid+'&code='+code;"
    )
    # BTWAF 壳页(宝塔防火墙): result.body() 含 Verification_auth_btwaf 字样 -> 进 loginCheckJs 弹码分支
    btwaf_html = '<html><head><title>安全验证</title></head><body>Verification_auth_btwaf 请完成验证</body></html>'
    # 正确写法(taozitxt 修复版): 用 java.ajax 取码 base64 -> java.getVerificationCode 弹码 -> 提交 -> connect 重取
    taozi_ajax_logincheck = (
        "var b=result.body();if(b&&b.indexOf('Verification_auth_btwaf')>-1){"
        "var img='';"
        "try{var o=JSON.parse(java.ajax('http://www.taozitxt.net/get_btwaf_captcha_base64?captcha='+new Date().getTime()));"
        "if(o&&o.msg){img='data:image/jpg;base64,'+o.msg;}}catch(e){img='';}"
        "if(img){var code=java.getVerificationCode(img);"
        "if(code){var cr=java.ajax('http://www.taozitxt.net/Verification_auth_btwaf?captcha='+encodeURIComponent(code));"
        "if(cr&&cr.indexOf('\"status\":true')>-1){result=java.connect(result.url());}}}}result;"
    )
    # 错误写法(taozitxt 旧 bug): 用单参 java.get(url) 取码 -> 3.25 里单参 get 是变量存取, 静默返回空串,
    #   弹码分支永不进入. 此用例是"反向验证标本": 桩返回空串时该写法必须 verificationAsked=False(不误判为通过).
    taozi_get_logincheck = (
        "var b=result.body();if(b&&b.indexOf('Verification_auth_btwaf')>-1){"
        "var img='';try{img=java.get('http://www.taozitxt.net/get_btwaf_captcha_base64?captcha='+new Date().getTime());}catch(e){img='';}"
        "if(img){var code=java.getVerificationCode(img);"
        "if(code){result=java.connect(result.url());}}}result;"
    )
    cases = [
        # 1) about:blank 死局: about:blank 夹具 + shumi99 搜索 URL -> webJs 应 return null(重试而非返回空内容)
        ("shumi99 webJs @ about:blank死局", shumi_webjs, ABOUT_BLANK, "http://www.shumi99.com/search/?searchkey=x", None,
         lambda r: r.get("ok") and r.get("returnedNull") is True, "about:blank+shumi99搜索URL 应 return null(重试)"),
        # 2) 正常搜索结果页: webJs 应返回含 bookbox 的 HTML
        ("shumi99 webJs @ 正常结果页", shumi_webjs, normal_html, "http://www.shumi99.com/search/?searchkey=x", None,
         lambda r: r.get("ok") and not r.get("returnedNull") and "bookbox" in _ret(r), "应返回含 bookbox 的 HTML"),
        # 3) 毒 cookie: `js` 字段应 return null 且清空 ss_search_delay
        ("shumi99 js @ 毒cookie", shumi_js, "", "http://www.shumi99.com", "a=1; ss_search_delay=1",
         lambda r: r.get("ok") and r.get("returnedNull") is True and "ss_search_delay" not in r.get("cookieAfter", ""),
         "应 return null 且清掉 ss_search_delay"),
        # 4) 语法错误必须被捕获
        ("语法错误 webJs", "(function(){ return }))", normal_html, "http://x.com", None,
         lambda r: r.get("ok") is False, "应捕获 SyntaxError"),
        # 5) 运行时抛异常必须被捕获
        ("运行时异常 webJs", "(function(){ throw new Error('boom'); })()", normal_html, "http://x.com", None,
         lambda r: r.get("ok") is False, "应捕获 RuntimeError"),
        # 6) loginCheckJs 过 403 壳页: result.body() 是壳页(含 window.location.href 无 bookbox) → 应调 java.connect 重取
        ("loginCheckJs 过 403 壳页", logincheck_js, shell_html, "http://www.shumi99.com/search/?searchkey=x", None,
         lambda r: r.get("ok") and r.get("connectCalled") is True, "壳页应触发 java.connect 重取"),
        # 7) loginCheckJs 误写 result.body(属性而非方法) → TypeError 必须被捕获(pitfalls 铁律: 必须 result.body())
        ("loginCheckJs 误写 result.body", "(function(){var b=result.body;if(b&&b.indexOf('x')>=0){result=java.connect(result.url());}result;})()", normal_html, "http://x.com", None,
         lambda r: r.get("ok") is False, "result.body 属性误写应报 RuntimeError(TypeError)"),
        # 8) loginCheckJs 人工弹码(GoEdge WAF 模板): 命中验证码页 → 必须走到 java.getVerificationCode,
        #    且拿到的是"用户输入的码"(桩注入值)。若静默跳过(verificationAsked=False)说明取图/取
        #    captcha-id 的 indexOf 定位写错 —— 这类 bug 静态校验和时序模拟都抓不到。
        ("loginCheckJs 弹码 GoEdge", goed_logincheck_js, waf_html, "https://www.boluomao1.com/book/1/", None,
         lambda r: r.get("ok") and r.get("verificationAsked") is True
                   and "code=8899" in _ret(r) and r.get("connectCalled") is True,
         "验证码页应触发 java.getVerificationCode 并注入码后重取", "8899"),
        # 9) 正确取码写法(taozitxt 修复版): java.ajax 取码 -> 应走到 getVerificationCode 并 connect 重取
        #    铁律 22/23 的"正向标本": 桩返回非空 base64 时正确写法必须通过(不误判为没弹码).
        ("loginCheckJs 取码 java.ajax(正确写法)", taozi_ajax_logincheck, btwaf_html, "http://www.taozitxt.net/book/1/", None,
         lambda r: r.get("ok") and r.get("verificationAsked") is True and r.get("connectCalled") is True,
         "java.ajax 取码应触发弹码并 connect 重取"),
        # 10) 错误取码写法(taozitxt 旧 bug): 单参 java.get(url) 取码 -> 静默空串 -> 不弹码.
        #     铁律 22/23 的"反向标本": 若桩回归成恒返非空/有人把 get 改成发请求, 此用例会 FAIL 报警.
        ("loginCheckJs 取码 java.get单参(旧bug)", taozi_get_logincheck, btwaf_html, "http://www.taozitxt.net/book/1/", None,
         lambda r: r.get("ok") and r.get("verificationAsked") is not True,
         "单参 java.get 取码应静默空串、不进入弹码分支"),
    ]
    passed = total = 0
    pos_pass = pos_total = neg_pass = neg_total = 0
    NEG_NAMES = {"语法错误 webJs", "运行时异常 webJs", "loginCheckJs 取码 java.get单参(旧bug)"}
    for item in cases:
        name, code, html, url, cookie, pred, desc = item[:7]
        vcode = item[7] if len(item) > 7 else ""
        total += 1
        is_lc = "loginCheckJs" in name
        is_neg = name in NEG_NAMES
        if is_neg: neg_total += 1
        else: pos_total += 1
        html2 = normal_html if is_lc else ""
        res = run_one(node, code, html, url, cookie, fixture_html2=html2,
                      kind=("loginCheckJs" if is_lc else ""), verification_code=vcode)
        ok = bool(pred(res))
        passed += 1 if ok else 0
        if ok:
            if is_neg: neg_pass += 1
            else: pos_pass += 1
        print("[%s] %-34s %s" % ("PASS" if ok else "FAIL", name, "" if ok else ("预期: " + desc + " | 实得 " + json.dumps(res, ensure_ascii=False))))
    print("=" * 54)
    print("js_layer 回归: %d/%d 通过  (正例 %d/%d, 反例 %d/%d)" % (passed, total, pos_pass, pos_total, neg_pass, neg_total))
    return passed == total


def _ret(r):
    return r.get("returned", "") or ""


def main():
    args = sys.argv[1:]
    node = find_node()
    if not node:
        print("未找到 node(Node.js), 无法执行 JS 层检查。请先安装 Node.js(>=16)。")
        print("本检查是离线安全带, 缺失时不影响其他验证; 仅跳过 JS 层模拟。")
        sys.exit(2)
    if "--self-test" in args:
        ok = self_test(node)
        sys.exit(0 if ok else 1)
    # 解析 --source / --js / --html / --url / --cookie
    def get_opt(name):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return None
    source_path = get_opt("--source")
    inline_js = get_opt("--js")
    html_path = get_opt("--html")
    url = get_opt("--url")
    cookie = get_opt("--cookie")
    vcode = get_opt("--code")   # 注入 java.getVerificationCode() 桩的返回码(模拟用户输入的验证码)
    ajax_body = get_opt("--ajax-body")   # 注入 java.ajax() 桩的兜底返回体
    captcha_b64 = get_opt("--captcha-b64")   # 注入取码接口返回的 base64 图片内容
    fixture = ABOUT_BLANK
    if html_path and os.path.isfile(html_path):
        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            fixture = f.read()
    if source_path:
        if not os.path.isfile(source_path):
            print("找不到书源文件: %s" % source_path)
            sys.exit(2)
        ok = check_source_file(node, source_path, fixture, url, cookie, verification_code=vcode or "",
                               ajax_body=ajax_body, captcha_b64=captcha_b64)
        sys.exit(0 if ok else 1)
    if inline_js is not None:
        res = run_one(node, inline_js, fixture, url, cookie, verification_code=vcode or "",
                      ajax_body=ajax_body, captcha_b64=captcha_b64)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("ok") else 1)
    print(__doc__.strip().splitlines()[0])
    print("用法见文件头注释。")
    sys.exit(2)


if __name__ == "__main__":
    main()
