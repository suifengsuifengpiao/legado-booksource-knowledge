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
    - 能抓: 语法错误、运行时异常、return null/about:blank 反模式(仅 webJs 语义)、cookie 桩行为、
      列表规则(bookList/chapterList)末段纯 <js> 返回类型(非数组=真机强转 List 崩溃, mowan v1 实证)。
    - 抓不了: 某个 java.* 方法在 3.25 是否真实存在(那部分靠 legend-js-api.md 对照 APK jsHelp.md 解决)。
    - 替代不了真机/真站网络验证。

<js> 求值作用域(3.25 dex 实证, 2026-10-25 P2-1 坐实, 证据链见 references/apk-method-inventory.md):
    真机每个 <js> 片段都是**独立顶层作用域**——AnalyzeRule.evalJS / AnalyzeUrl.evalJS 每次调用
    都新建 com.script.ScriptBindings 并经 RhinoScriptEngine.getRuntimeScope 求值, 一个片段里的
    顶层 var/function 声明**不会**被后续片段看到。唯一跨片段共享通道是书源的 jsLib 字段
    (BaseSource.getShareScope: jsLib 顶层声明经 setPrototype 注入每个 <js> 的作用域)。
    ⇒ 文档写法「bookList 的 <js> 里定义 helper, 子规则 <js>helper(result).xxx 引用」在真机
      必然 ReferenceError(取名空); 正确形态只有两种: helper 放进 jsLib 共享, 或每个子规则内联自含。
    本 harness 与真机同构: 逐片段独立求值; --source 模式自动把书源 jsLib 作为 prelude 注入
    该源所有片段(模型 shareScope), jsLib 形态为 {"key":"url"} 时远程 URL 离线取不到会显式
    注记跳过(不静默——漏注入会让该源 <js> 假 FAIL)。
    result 桩语义(--source 模式): bookList/chapterList/searchUrl/exploreUrl 的 <js> 用响应
    对象桩(result.body()=--html 夹具); 其余规则字段的 <js>(name/author/bookUrl/content 等
    子规则)用**元素字符串桩**(result=--html 夹具本身) —— 与真机"子规则 result 是上一步传来
    的列表元素/正文字符串"一致。测 JSON API 站的子规则时, --html 传该接口的 JSON 响应即可。

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
  // resultMode=raw(子规则 <js> 专用): 真机子规则的 result 是上一步传来的**列表元素字符串**
  // (bookList <js> 返回的 JSON.stringify(item)), 不是响应对象 —— 该语义此前从未建模,
  // 补上后才能钉住"子规则引用跨片段 helper"这类 bug(2026-10-25 P2-1, dex 坐实见
  // 文件头「<js> 求值作用域」节)。webJs/js/loginCheckJs/bookList 仍用响应对象桩。
  const result = (cfg.resultMode === 'raw')
    ? (cfg.fixtureHtml != null ? cfg.fixtureHtml : '')
    : {
        body: () => (cfg.fixtureHtml != null ? cfg.fixtureHtml : ''),
        url: () => cfg.url || '',
        code: () => cfg.code || 200,
        headers: () => ({ entrySet: () => ({ iterator: () => ({ hasNext: () => false, next: () => null }) }) }),
      };

  // ---- jsLib 共享作用域(真机 shareScope, dex 实证): 书源 jsLib 字段的顶层声明经
  //      setPrototype 注入每个 <js> 的求值作用域 —— 先在同一上下文执行 prelude 再跑片段,
  //      顶层 var/function 即对片段可见(模型原型链查找)。jsLib 自身语法错也会在此暴露,
  //      与真机一致: shareScope 在首个 <js> 求值时才惰性创建, 失败即该次 JS 执行失败。
  //      (从宽点: prelude 在带完整绑件的 ctx 里执行, 真机 shareScope 是裸作用域, jsLib
  //      顶层引用 java/cookie 等绑定在真机反而会失败——harness 不建模这一层。)
  const ctx = { document, location, cookie, java, source, result, console };
  let r;
  try {
    if (cfg.prelude) vm.runInNewContext(cfg.prelude, ctx);
    r = vm.runInNewContext(code, ctx);
  } catch (e) {
    const stage = (e instanceof SyntaxError) ? 'compile' : 'run';
    process.stdout.write(JSON.stringify({
      ok: false, error: (stage === 'compile' ? 'SyntaxError: ' : 'RuntimeError: ') + e.message, stage,
    }));
    return;
  }
  // 列表规则(bookList/chapterList)的 <js>: 真机 AnalyzeRule.getElements 对返回值强转 List,
  // 非数组直接 ClassCastException(String cannot be cast to List)崩溃(mowan v1 实证)。
  if (cfg.kind === 'list-js') {
    if (!Array.isArray(r)) {
      process.stdout.write(JSON.stringify({
        ok: false, stage: 'run',
        error: '列表规则 <js> 必须返回数组: 真机 AnalyzeRule.getElements 将返回值强转 List, '
             + '字符串/对象会 ClassCastException(String cannot be cast to List)直接崩溃(mowan v1 实证); '
             + '返回 null 不崩但真机静默得到空列表(书名全空, 同样是事故)。'
             + '应返回 JSON.stringify(item) 组成的数组; 子规则用 <js> 内联解析该 JSON 字符串'
             + '(如 <js>JSON.parse(result).name</js>), 或把共用 helper(如 _p)放进书源 jsLib '
             + '字段共享(真机 shareScope, dex 实证) —— 注意 helper 定义在 bookList 的 <js> 里'
             + '对子规则不可见(每个 <js> 独立作用域), 那样写真机 ReferenceError 取名空',
      }));
      return;
    }
    process.stdout.write(JSON.stringify({
      ok: true, error: null, returnedIsArray: true, returnedLen: r.length,
      returned: JSON.stringify(r).slice(0, 2000),
    }));
    return;
  }
  const isLogin = (cfg.kind === 'loginCheckJs');
  // about:blank 判据只对 webJs 语义适用: webJs/URL 选项 js 返回的是整页 HTML,
  // 空页/未就绪页才有 about:blank 反模式; 解析字段(pipe: name/intro 等)短返回是正常
  // 形态 —— mowan 17 块中 15 个 pipe 块曾因空夹具返回 "" 被误亮(2026-10-25 验证师反馈)。
  const isWebJsLike = (cfg.kind === 'webJs' || !cfg.kind);
  if (!isLogin) {
    // webJs / `js` 字段：返回字符串(HTML)或 null；用 about:blank 判据识别"把未就绪当完成"
    const returnedNull = (r === null || r === undefined);
    const s = returnedNull ? '' : String(r);
    const isAboutBlank = isWebJsLike && !returnedNull && (
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
            verification_code="", ajax_body=None, captcha_b64=None,
            prelude="", result_raw=False):
    """在 Node 里跑一段书源 JS, 返回解析后的结果 dict; 失败返回 {ok:False, error}。
    fixture_html2: loginCheckJs 重取(java.connect)后返回的"真实内容"夹具。
    kind: webJs / js / loginCheckJs / list-js, 影响 HARNESS 的判据分支。
    verification_code: 注入 java.getVerificationCode() 桩的返回值(模拟用户输入的验证码);
        不传则桩返回默认 '123456'。用它验证 loginCheckJs 走的是弹码路径而不是静默跳过。
    ajax_body: 注入 java.ajax() 桩的兜底返回体(非取码/提交接口时返回); 不传则空串。
    captcha_b64: 注入取码接口返回的 base64 图片内容; 不传则用内置占位 'data:image/jpg;base64,AAAA'。
        ⚠️ 这两个必须有 CLI 入口(--ajax-body/--captcha-b64), 否则就是"桩读了却永远取默认值"的死配置。
    prelude: 书源 jsLib(共享作用域)代码, 先于片段在同一上下文执行 —— 模型真机
        source.getShareScope() 的 setPrototype 注入(3.25 dex 实证, 见文件头「<js> 求值
        作用域」节)。jsLib 语法错会在此暴露, 与真机"首个 <js> 求值时惰性创建 shareScope
        失败即当次 JS 执行失败"一致。
    result_raw: True 时 result 桩直接是 fixture_html 字符串(子规则 <js> 语义: 真机子规则的
        result 是上一步传来的列表元素字符串); 默认 False 为响应对象桩(webJs/js/loginCheckJs/
        bookList 语义)。2026-10-25 P2-1 补: 此前子规则 result 语义从未建模。
    """
    d = tempfile.mkdtemp(prefix="js_layer_")
    try:
        with open(os.path.join(d, "user.js"), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            cfg = {"fixtureHtml": fixture_html, "url": url,
                   "initialCookie": initial_cookie or "", "fixtureHtml2": fixture_html2,
                   "kind": kind, "verificationCode": verification_code or "",
                   "prelude": prelude or "",
                   "resultMode": "raw" if result_raw else "response"}
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
    kind ∈ {webJs, js, loginCheckJs, pipe, list-js}。list-js = bookList/chapterList 的**末段是纯
    <js>**(真机要求返回数组, 见 HARNESS list-js 分支; mowan v1 曾因返回拼接字符串真机
    ClassCastException 崩溃)。链式形态(<js>...</js>选择器)不标 list-js —— JS 返回值是后段
    输入而非最终列表元素(3.25 反编译实证, 见 _is_pure_js_terminal)。覆盖点与
    validate_booksource._collect_js_fragments 对齐：
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
                # 旧 schema: 规则组可能是字符串化 JSON(如 exploreUrl[i].ruleExplore 结构 a),
                # 其中的 <js> 键名在串内不可见 —— 先解析再递归, 让 bookList/chapterList 的
                # <js> 能被识别(否则 explore 条目结构 a 整体绕过 list-js 闸门; 2026-10-25
                # 验证师 Major-3 实证的漏报通道)。
                if o.strip().startswith("{"):
                    try:
                        _parsed = json.loads(o)
                    except Exception:
                        _parsed = None
                    if isinstance(_parsed, dict):
                        walk(_parsed, path)
                for m in re.finditer(r"<js>(.*?)</js>", o, re.S):
                    # bookList/chapterList 的末段是纯 <js> 时, 其返回值就是列表元素:
                    # 真机 AnalyzeRule.getElements 对返回值强转 List, 非数组直接
                    # ClassCastException(String→List)崩溃(mowan v1 实证) → 标 list-js
                    # 走 HARNESS 的类型闸门。
                    # ⚠ 仅"末段纯 <js>"适用: 链式形态(<js>...</js>选择器)下 JS 返回值是
                    # 后段输入, 由 AnalyzeByJSoup.parse 当 HTML 解析后求值, 最终 result 是
                    # Elements(List), 数组契约不适用(2026-10-25 验证师证伪初版过严后补)。
                    _kind = ("list-js"
                             if k in ("bookList", "chapterList") and _is_pure_js_terminal(o)
                             else "pipe")
                    add(tag + "/%s<js>" % (k or "?"), _kind, m.group(1))
        walk(src, "")
    return found


ABOUT_BLANK = "<html><head></head><body></body></html>"  # Legado about:blank outerHTML 约 39 字节


def _is_pure_js_terminal(rule_val):
    """规则串是否以 <js>...</js> 收尾(末段是纯 JS, 无尾部选择器/正则段)。

    3.25 反编译实证(AnalyzeRule.getElements + splitSourceRule + AnalyzeByJSoup.parse):
    规则按段顺序执行, 前段输出是后段输入 ——
      - 链式形态 <js>...</js>div.x: JS 返回的 HTML 字符串经 Jsoup.parse 解析成 DOM,
        再供尾部选择器求值, 最终 result 是 Elements(List), 强转成功(58书屋在售源实证);
      - 末段纯 <js>: JS 返回值直接作为最终列表元素被强转 List, 非数组即
        ClassCastException(String→List)崩溃(mowan v1 实证)。
    两类形态契约不同, 数组闸门只适用于后者。
    """
    if not isinstance(rule_val, str) or "<js>" not in rule_val:
        return False
    last_end = None
    for m in re.finditer(r"<js>(.*?)</js>", rule_val, re.S):
        last_end = m.end()
    if last_end is None:
        return False
    return rule_val[last_end:].strip() == ""


def extract_js_lib(src):
    """抽取书源 jsLib 字段的**本地可执行**代码块, 返回 (chunks, skipped_urls)。

    真机语义(3.25 dex 实证, BaseSource$DefaultImpls.getShareScope): jsLib 是唯一跨 <js>
    共享的作用域 —— 其顶层函数/变量声明经 setPrototype 注入每个 <js> 的求值作用域:
      - 字符串形态: 整段 eval;
      - JSON map 形态({"key":"code_or_url"}): 逐值 eval, 值是 URL 的先下载缓存再 eval。
    离线 harness 取不到远程 URL: 值以 http(s):// 开头的记入 skipped_urls 并注记跳过
    (不静默 —— 漏注入会让该源的 <js> 假 FAIL, 必须让用户知道这是环境限制)。
    """
    lib = src.get("jsLib")
    if not isinstance(lib, str) or not lib.strip():
        return [], []
    chunks, skipped = [], []
    parsed = None
    if lib.lstrip().startswith("{"):
        try:
            parsed = json.loads(lib)
        except Exception:
            parsed = None
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, str) and v.strip():
                if re.match(r"^https?://", v.strip()):
                    skipped.append(v.strip())
                else:
                    chunks.append(v)
    else:
        chunks.append(lib)
    return chunks, skipped


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
    # jsLib 共享作用域(真机 shareScope, dex 实证): 每个书源的 jsLib 顶层声明要注入它
    # 自己的所有 <js> 片段 —— 否则按官方推荐形态(helper 放 jsLib)写的书源会被假 FAIL
    # (与 P2-1 同类的"按正确写法跑校验器即 FAIL")。map 形态里的远程 URL 离线取不到,
    # 显式注记跳过, 不静默。
    srcs = payload if isinstance(payload, list) else [payload]
    prelude_by_tag = {}
    for idx, src in enumerate(srcs):
        if not isinstance(src, dict):
            continue
        tag = src.get("bookSourceName", "src%d" % idx)
        chunks, skipped = extract_js_lib(src)
        for u in skipped:
            print("[NOTE] %s: jsLib 远程 %s 离线取不到, 未注入共享作用域"
                  "(该源 <js> 若依赖它会 FAIL, 属环境限制非书源 bug)" % (tag, u))
        if chunks:
            prelude_by_tag[tag] = "\n;\n".join(chunks)

    def _tag_of(where):
        # where = <bookSourceName>/<字段>; 书名含 "/" 时按已知 tag 精确匹配前缀
        for t in prelude_by_tag:
            if where.startswith(t + "/"):
                return t
        return None

    # 子规则 <js> 的 result 语义(3.25 dex 坐实, 2026-10-25 P2-1): 真机子规则的 result 是
    # 上一步传来的**列表元素字符串**(bookList <js> 返回的 JSON.stringify(item) / content
    # 的正文串), 不是响应对象。bookList/chapterList 的 <js>(含链式形态)与 searchUrl/
    # exploreUrl 整串 <js> 才是响应语义。用错桩会让真机正确形态假 FAIL —— 例如子规则
    # <js>JSON.parse(result).name</js> 用响应对象桩必 SyntaxError, 而它在真机是对的。
    _RESPONSE_KEYS = ("bookList", "chapterList", "searchUrl", "exploreUrl")

    def _sub_key(where):
        head = where.rsplit("<js>", 1)[0]
        return head.rsplit("/", 1)[-1] if "/" in head else ""

    ok_all = True
    for where, kind, code in items:
        prelude = prelude_by_tag.get(_tag_of(where) or "", "")
        result_raw = (kind == "pipe" and _sub_key(where) not in _RESPONSE_KEYS)
        res = run_one(node, code, fixture_html, url, initial_cookie, kind=kind,
                      verification_code=verification_code,
                      ajax_body=ajax_body, captcha_b64=captcha_b64,
                      prelude=prelude, result_raw=result_raw)
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
    # mowan.lol 混合聚合站 API 夹具(搜索响应: novel×2 + video×1; v4 写法按 type 过滤后应得 2 条)
    mowan_api_json = json.dumps({
        "code": 0,
        "data": {"items": [
            {"name": "斗破苍穹", "author": "天蚕土豆", "type": "novel"},
            {"name": "短剧甲", "type": "video"},
            {"name": "凡人修仙传", "author": "忘语", "type": "novel"}]}},
        ensure_ascii=False)
    # v1 病态写法(反例标本): 列表 <js> 返回拼接 HTML 字符串 → 真机 String→List 强转
    # ClassCastException 崩溃(mowan v1 真机日志实证), 本地必须 FAIL。
    mowan_v1_list_js = (
        "(function(){var d=JSON.parse(result.body());var items=d.data.items||[];"
        "var s='';for(var i=0;i<items.length;i++){s+='<div class=\"book-name\">'+items[i].name+'</div>';}"
        "return s;})()"
    )
    # v4 正确写法(正例标本): _p 兼容层 + JSON.stringify(item) 数组 + type=novel 过滤。
    # 与 v1 标本同一站点同一接口; 差异为「解析方式(_p/直接取)+type 过滤+返回类型」三项,
    # 其中返回类型是闸门判据(2026-10-25 验证师 Minor: 原注释"只差返回类型"言过其实, 已修正)。
    mowan_v4_list_js = (
        "(function(){function _p(r){if(r==null)return null;var raw;"
        "if(typeof r==='string'){raw=r;}else if(typeof r.body==='function'){raw=r.body();}"
        "else{raw=String(r);}if(raw==null)return null;"
        "try{return JSON.parse(raw);}catch(e){}"
        "if(typeof r==='object'&&typeof r.body!=='function'){return r;}return null;}"
        "var d=_p(result);var items=(d&&d.data&&d.data.items)||[];var out=[];"
        "for(var i=0;i<items.length;i++){if(items[i].type!=='novel')continue;"
        "out.push(JSON.stringify(items[i]));}return out;})()"
    )
    # 链式形态(正例标本, 2026-10-25 验证师 Major-1 反馈新增): JS 段返回拼接 HTML 字符串,
    # 管道尾部 div.book-item 选择器在真机 Jsoup.parse 出的 DOM 上求值, 最终 result 是
    # Elements(List) —— 强转成功, 数组契约不适用于该形态(58书屋在售源实证)。
    # 此标本验证的是: 链式 JS 作为 pipe 执行时行为正常(返回长 HTML 串, 不误触 about:blank)。
    mowan_chained_pipe_js = (
        "(function(){var d=JSON.parse(result.body());var items=d.data.items||[];"
        "var s='';for(var i=0;i<items.length;i++){s+='<div class=\"book-item\"><a class=\"book-link\" href=\"#\">'+items[i].name+'</a></div>';}"
        "return s;})()"
    )
    # mowan v4 的 JSON 兼容层 helper(既吃字符串也吃 StrResponse.body()/普通对象)。
    # 🔴 跨片段共用它只有两条合法通道(3.25 dex 实证, 见文件头「<js> 求值作用域」节):
    #   ① 书源 jsLib 字段(真机 shareScope 原型链注入); ② 每个子规则内联自含。
    #   定义在 bookList 的 <js> 里(含 IIFE 内)对子规则**不可见** —— 真机每个 <js> 独立
    #   作用域, 那样写真机 ReferenceError 取名空。标本 14/15/16 三连钉住这三种行为。
    mowan_p_helper = (
        "function _p(r){if(r==null)return null;var raw;"
        "if(typeof r==='string'){raw=r;}else if(typeof r.body==='function'){raw=r.body();}"
        "else{raw=String(r);}if(raw==null)return null;"
        "try{return JSON.parse(raw);}catch(e){}"
        "if(typeof r==='object'&&typeof r.body!=='function'){return r;}return null;}"
    )
    # 子规则 <js> 的 result 语义: 真机是上一步传来的**列表元素字符串**(bookList <js> 返回的
    # JSON.stringify(item)), 不是响应对象 —— result_raw=True 精确建模(2026-10-25 P2-1 补,
    # 此前该语义从未建模, "按文档写法跑校验器即 FAIL"一半原因是它)。
    mowan_item_json = json.dumps({"name": "斗破苍穹", "author": "天蚕土豆",
                                  "type": "novel", "id": 12345}, ensure_ascii=False)
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
        # 11) mowan v1 病态写法(反例标本): 列表 <js> 返回拼接 HTML 字符串 → 真机强转 List 崩溃,
        #     必须 FAIL 且错误信息点名"数组"。铁律 22/23: 若有人把 list-js 闸门改松/改坏,
        #     此用例立刻报警(护栏的护栏)。
        ("mowan v1 列表拼接字符串(旧bug)", mowan_v1_list_js, mowan_api_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") is False and "数组" in (r.get("error") or ""),
         "列表 <js> 返回字符串必须 FAIL(真机 String→List 强转崩溃)", "", "list-js"),
        # 12) mowan v4 正确写法(正例标本): 返回 JSON.stringify(item) 数组(type=novel 过滤)
        #     → 必须 PASS 且 returnedIsArray=True、returnedLen=2。与 11 配对防"把数组写法
        #     误判成非法"的反向事故。
        ("mowan v4 列表 JSON 数组(正确写法)", mowan_v4_list_js, mowan_api_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") is True and r.get("returnedIsArray") is True
                   and r.get("returnedLen") == 2,
         "列表 <js> 返回 JSON 字符串数组必须 PASS 且 isArray(len=2, 已过滤 video)", "", "list-js"),
        # 13) 链式形态管道 JS(正例标本, 58书屋实证): pipe 语义下返回长 HTML 串 → 必须 PASS,
        #     且不误触 about:blank(2026-10-25 判据语义细分: 空/短返回只对 webJs 语义告警)。
        ("链式 <js>返串+选择器(pipe 形态)", mowan_chained_pipe_js, mowan_api_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") is True and not r.get("returnedNull")
                   and r.get("isAboutBlank") is False and "book-item" in _ret(r),
         "链式形态 JS 返回 HTML 串应 PASS 且不误触 about:blank", "", "pipe"),
        # 14) v4 完整形态·子规则引用 bookList IIFE 内 _p(反例标本, 2026-10-25 P2-1 dex 坐实):
        #     文档旧写法把 "_p 定义在 bookList IIFE + 子规则 <js>_p(result).xxx" 定为正确形态,
        #     但 dex 实证真机每个 <js> 独立作用域(AnalyzeRule.evalJS 每次新建 ScriptBindings),
        #     IIFE 内的 _p 到不了子规则 → 真机 ReferenceError → 取名空(与铁律 26 坑②同症)。
        #     harness 逐片段独立求值与真机同构, 必须 FAIL 且错误点名 _p。若有人把 harness 改成
        #     跨片段共享作用域, 此用例立刻报警(护栏的护栏)。
        ("mowan v4 完整形态·子规则引用 IIFE _p(旧bug)", "_p(result).name", mowan_item_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") is False and "_p is not defined" in (r.get("error") or ""),
         "子规则引用 bookList IIFE 内 _p 必须 FAIL(真机独立作用域, ReferenceError 同构)",
         "", "pipe", "", True),
        # 15) 同书源走 jsLib 共享(正例标本): _p 放进 jsLib(真机 shareScope 原型链注入)后,
        #     子规则必须 PASS 且取到书名。与 14 配对防两种反向事故: 把 jsLib 注入改坏(假
        #     FAIL)或把 harness 改成无脑跨片段共享(14 失守)。
        ("mowan v4 jsLib 共享 _p(正确写法)", "_p(result).name", mowan_item_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") and "斗破苍穹" in _ret(r),
         "jsLib 共享作用域注入 _p 后子规则应 PASS 且取到书名",
         "", "pipe", mowan_p_helper, True),
        # 16) 子规则自含形态(正例标本): 不依赖任何跨片段共享, <js> 内联 JSON.parse(result)。
        #     零依赖正确形态, 必须 PASS。与 14/15 一起把"三种写法只有两种对"钉死。
        ("mowan v4 子规则自含 JSON.parse(正确写法)",
         "(function(){var d=JSON.parse(result);return (d&&d.name)||'';})()", mowan_item_json,
         "https://www.mowan.lol/api/search?keyword=x", None,
         lambda r: r.get("ok") and "斗破苍穹" in _ret(r),
         "子规则自含 JSON.parse(result) 应 PASS 且取到书名", "", "pipe", "", True),
    ]
    passed = total = 0
    pos_pass = pos_total = neg_pass = neg_total = 0
    NEG_NAMES = {"语法错误 webJs", "运行时异常 webJs", "loginCheckJs 取码 java.get单参(旧bug)",
                 "mowan v1 列表拼接字符串(旧bug)",
                 "mowan v4 完整形态·子规则引用 IIFE _p(旧bug)"}
    for item in cases:
        name, code, html, url, cookie, pred, desc = item[:7]
        vcode = item[7] if len(item) > 7 else ""
        kind_over = item[8] if len(item) > 8 else ""   # 第 9 元: 显式 kind(如 list-js)
        prelude = item[9] if len(item) > 9 else ""     # 第 10 元: jsLib prelude(shareScope 模型)
        raw = item[10] if len(item) > 10 else False    # 第 11 元: result 桩用元素字符串(子规则语义)
        total += 1
        is_lc = "loginCheckJs" in name
        is_neg = name in NEG_NAMES
        if is_neg: neg_total += 1
        else: pos_total += 1
        html2 = normal_html if is_lc else ""
        kind = kind_over or ("loginCheckJs" if is_lc else "")
        res = run_one(node, code, html, url, cookie, fixture_html2=html2,
                      kind=kind, verification_code=vcode, prelude=prelude, result_raw=raw)
        ok = bool(pred(res))
        passed += 1 if ok else 0
        if ok:
            if is_neg: neg_pass += 1
            else: pos_pass += 1
        print("[%s] %-34s %s" % ("PASS" if ok else "FAIL", name, "" if ok else ("预期: " + desc + " | 实得 " + json.dumps(res, ensure_ascii=False))))
    # 提取覆盖回归(2026-10-25 验证师 Major-1/Major-3 反馈新增, 不执行 JS 只断言标注):
    # extract_js_from_source 对三种列表 <js> 形态的 kind 标注 —— 纯 <js> 末段=list-js(数组闸门) /
    # 链式 <js>+选择器=pipe(数组契约不适用) / 旧 schema 字符串化 ruleExplore(exploreUrl 结构 a)
    # 内的也要识别为 list-js。carve-out 或二级解析被改坏时此处立刻报警(护栏的护栏)。
    # 三处 JS 代码刻意不同: add() 按 code 去重, 相同代码会被 seen 吞掉后两处。
    _probe_src = [{
        "bookSourceName": "probe",
        "ruleSearch": {"bookList": "<js>(function(){return [];})()</js>", "name": ".n@text"},
        "ruleToc": {"chapterList": "<js>(function(){return [2];})()</js>div.c"},
        "exploreUrl": [{"title": "t", "url": "https://x.com",
                        "ruleExplore": json.dumps({"bookList": "<js>(function(){return [1];})()</js>",
                                                   "name": ".n@text"})}],
    }]
    _marked = [(w, k) for w, k, c in extract_js_from_source(_probe_src)]
    _n_list = sum(1 for w, k in _marked if k == "list-js")
    _pipe_where = [w for w, k in _marked if k == "pipe"]
    total += 1
    pos_total += 1
    # 期望 2 个 list-js(ruleSearch 纯末段 + explore 结构 a 字符串化区域); 若结构 a 被绕过
    # (键名在串内不可见)则只有 1 个; 期望唯一 pipe 是 ruleToc 的链式 chapterList。
    extract_ok = (_n_list == 2 and _pipe_where == ["probe/chapterList<js>"])
    if extract_ok:
        pos_pass += 1
        passed += 1
    print("[%s] %-34s %s" % ("PASS" if extract_ok else "FAIL", "extract 覆盖: 三形态 kind 标注",
                             "" if extract_ok else ("标注=%s" % _marked)))
    # jsLib 共享作用域抽取覆盖(2026-10-25 P2-1 新增, 不执行 JS 只断言抽取):
    # 字符串形态整段注入 / JSON map 形态逐值注入 / map 里 http(s):// 值离线取不到必须显式
    # 跳过(不静默 —— 漏注入会让按官方推荐形态(helper 放 jsLib)写的书源假 FAIL)。
    # 抽错规则(如把 URL 也当代码注入)会让 harness 与真机 shareScope 语义漂移。
    _lib_str = {"bookSourceName": "libprobe", "jsLib": "function _p(r){return r;}",
                "ruleSearch": {"bookList": "<js>(function(){return [];})()</js>"}}
    _lib_map = {"bookSourceName": "libprobe2",
                "jsLib": json.dumps({"a": "function fa(){return 1;}",
                                     "b": "https://cdn.example.com/lib.js"}),
                "ruleSearch": {"bookList": "<js>(function(){return [];})()</js>"}}
    _lib_none = {"bookSourceName": "libprobe3",
                 "ruleSearch": {"bookList": "<js>(function(){return [];})()</js>"}}
    _c1, _s1 = extract_js_lib(_lib_str)
    _c2, _s2 = extract_js_lib(_lib_map)
    _c3, _s3 = extract_js_lib(_lib_none)
    total += 1
    pos_total += 1
    lib_ok = (_c1 == ["function _p(r){return r;}"] and _s1 == []
              and _c2 == ["function fa(){return 1;}"]
              and _s2 == ["https://cdn.example.com/lib.js"]
              and _c3 == [] and _s3 == [])
    if lib_ok:
        pos_pass += 1
        passed += 1
    print("[%s] %-34s %s" % ("PASS" if lib_ok else "FAIL", "extract jsLib: 字符串/map 注入, URL 跳过",
                             "" if lib_ok else ("chunks=%s skipped=%s / %s %s / %s %s"
                                                % (_c1, _s1, _c2, _s2, _c3, _s3))))
    print("=" * 54)
    print("js_layer 回归: %d/%d 通过  (正例 %d/%d, 反例 %d/%d)" % (passed, total, pos_pass, pos_total, neg_pass, neg_total))
    return passed == total


def _ret(r):
    return r.get("returned", "") or ""


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__.strip())
        sys.exit(0)
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
