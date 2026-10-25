#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""realcheck —— 用 Playwright 忠实复现 Legado BackstageWebView 的真实抓取时序，实跑交付的书源。

为什么需要它:
  curl / lxml 抓不到 JS 挑战后的 DOM，而"用 lxml 验证 XPath"又掩盖了真实引擎的语义差异。
  本脚本直接从**交付的书源文件**里读取 rules 与 URL 行内选项，
  按 BackstageWebView.kt 的真实行为 按需执行 webJs:
     onPageFinished 后等待 webWait -> 固定 1000ms 重复 evaluateJavascript
     -> 最多 31 次 -> 判定标准是"结果非空且非 null"(半截页面也算通过!)
  因此 webJs 若不带长度/内容判定，脚本会如实暴露"第 1 次就把半截 HTML 当成结果"的缺陷，
  而不是假装通过。

用法:
  python3 realcheck.py <书源.json> [--times 3] [--gap 6000] [--key 搜索词] [--stop-on-fail]
  参数:
    --times N        连续搜索次数(默认3), 用来撞30秒限流窗口
    --gap MS         两次搜索之间的间隔毫秒(默认6000), 默认落在限流窗口内
    --key XXX        搜索关键词(默认"系统")
    --stop-on-fail   首次失败即停止后续步骤

输出:
  每次请求的成功尝试序号 / 字节数 / 列表命中数, cookie 中是否残留限流项,
  以及随后访问详情/发现/正文是否受连带影响。

退出码: 0=全部通过  1=存在失败  2=参数或依赖错误
"""
import argparse
import asyncio
import json
import sys
import time

MAX_RETRY = 31

# 等待字段名与重试节奏都随 App 版本指纹变化（详见 references/field-availability.md）
WAIT_FIELD = {"325": "webWait"}
# 3.25 反编译版：失败后固定 1000ms 重试
RETRY_INTERVALS = {"325": [1000]}
DEFAULT_WAIT = 1000
# _report 默认"出现至少 1 次"即判存在(不要求数量): 否则搜索首页不足 10 个结果标记的站点会被误判 FAIL。
# 调用方需更高门槛时传 (子串, N) 元组。
DEFAULT_MIN_HIT = 1
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")  # Legado 默认 UA(help/config/a.java Q)

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.stderr.write("[错误] 需要 playwright: pip install playwright && playwright install chromium\n")
    sys.exit(2)


def load_source(path):
    try:
        with open(path, encoding="utf-8-sig") as _f:
            data = json.load(_f)
    except Exception as e:
        sys.stderr.write("[错误] 无法解析书源 JSON: %s\n" % e)
        sys.exit(2)
    src = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    return src


def split_url_options(url):
    """拆 'URL,{json选项}' 返回 (url, dict选项)；无行内选项时返回 (url, {})。

    切分语义与真机 AnalyzeUrl.kt 对齐(3.25 smali 实证): paramPattern =
    `\\s*,\\s*(?=\\{})`, matcher.find() 取**第一个**「逗号后(可带空白)跟 {」的位置;
    选项 JSON 可含嵌套花括号(webJs/bodyJs 里的 JS 对象), 必须括号配对扫描到串尾。
    旧实现用 find(",{") 字面量, 漏掉 `URL, {...}`(逗号后带空格)的合法写法——
    选项串会整段留在 URL 里导致导航失败。选项 JSON 解析失败时真机保留整串为 URL, 与此一致。
    """
    if isinstance(url, dict):                       # Legado 也支持对象形式
        return url.get("url", ""), url
    if not isinstance(url, str):
        return "", {}
    for i, ch in enumerate(url):
        if ch != ",":
            continue
        j = i + 1
        while j < len(url) and url[j].isspace():
            j += 1
        if j >= len(url) or url[j] != "{":
            continue
        # 括号配对(跳过字符串与转义)到串尾才算完整选项对象
        depth = 0
        k = j
        in_str = None
        while k < len(url):
            c = url[k]
            if in_str:
                if c == "\\":
                    k += 2
                    continue
                if c == in_str:
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
        if depth == 0 and k < len(url) and not url[k + 1:].strip():
            m = i
            while m > 0 and url[m - 1].isspace():
                m -= 1
            head = url[:m] if m else url[:i]
            try:
                return head, json.loads(url[i + 1:])
            except Exception as e:
                # 结构像选项但 JSON 坏: 真机 Gson 解析同样失败。这里剥掉头部保证导航
                # 地址正确, 但必须显式告警 —— 否则丢失的 webJs/webWait 会被当成
                # 「无 webJs」上报, 又是一次假绿。
                print("  [严重] URL 行内选项 JSON 解析失败(%s): %r —— 该选项(webJs/webWait 等)已丢弃, "
                      "请修正书源" % (e, url[i + 1:][:80]))
                return head, {}
        # 没配平或 } 后有尾随内容: 不是选项, 继续找下一个逗号
    return url, {}


class Checker(object):
    def __init__(self, src, args):
        self.src = src
        self.args = args
        self.base = str(src.get("bookSourceUrl") or "").rstrip("/")
        self.fails = 0
        self.passes = 0
        self.app = "325"
        # 从 WAIT_FIELD 表取, 避免"表改了实现没改"的漂移（该表此前定义后从未被读取, 属死配置）
        self.wait_field = WAIT_FIELD.get("325", "webWait")
        self.field_errors = []

    def _interval(self, attempt):
        table = RETRY_INTERVALS["325"]
        return table[attempt] if attempt < len(table) else table[-1]

    def delay_of(self, opt, pos):
        """3.25 取等待毫秒，并检查是否写了 webWait（3.25 唯一生效的等待字段）。
        写成 webViewDelayTime 会被 Gson 静默丢弃 → 等待退回默认，是'本地绿/真机空'的头号成因。"""
        if "webWait" in opt:
            try:
                # webWait 写成字符串/带小数值也会让 wait_for_timeout 直接 TypeError 崩栈
                return max(0, int(float(opt["webWait"])))
            except (TypeError, ValueError):
                self.field_errors.append(
                    "%s: webWait 不是数字(%r) → 等待退回默认 %dms。"
                    % (pos, opt.get("webWait"), DEFAULT_WAIT))
        if "webViewDelayTime" in opt:
            self.field_errors.append(
                "%s: 只写了 webViewDelayTime，3.25 不认识它 → 会被静默忽略、等待退回默认 %dms。"
                "3.25 的等待字段是 webWait，请改成 webWait" % (pos, DEFAULT_WAIT))
        return DEFAULT_WAIT

    async def fetch(self, page, url, label, webjs, delay, expect_sub=None, strict=True):
        # ⚠️ 导航失败不能静默 pass：否则超时/断网的空白页会被当成"页面确实没内容"上报,
        # 与"站点 JS 渲染失败""被 WAF 拦截"完全无法区分 —— 正是本技能反复警告的虚假安全感。
        nav_err = None
        try:
            await page.goto(url, wait_until="load", timeout=15000)
        except Exception as e:
            nav_err = e
        if nav_err is not None:
            self.fails += 1
            print("    [失败] %s 导航失败(%s: %s) —— 结果是空白页, 不可当作站点真实响应"
                  % (label, type(nav_err).__name__, str(nav_err)[:120]))
            try:
                self.field_errors.append("%s 导航失败" % label)
            except Exception:
                pass
            return ""
        await page.wait_for_timeout(delay)
        if not webjs:
            html = await page.evaluate(
                "document.documentElement?document.documentElement.outerHTML:''")
            self._report(label, 0, html, expect_sub, strict)
            return html
        for attempt in range(MAX_RETRY):
            await page.wait_for_timeout(self._interval(attempt))
            try:
                result = await page.evaluate(webjs)
            except Exception as e:
                # 真机语义: evaluateJavascript 抛错 -> 原始值拿到 null -> 重试。
                # 这里曾直接崩栈(traceback 顶掉退出码), 违背"导航/求值失败不可静默 pass"
                # 的原则——如实按 null 重试, 并在最终超时里如实报告。
                result = None
                if attempt == 0:
                    print("  [%s] webJs 第1次执行即抛错(%s: %s) —— 按真机语义按 null 重试"
                          % (label, type(e).__name__, str(e)[:120]))
            # 忠实模拟 evaluateJavascript 原始值语义(3.25 c.java 实锤):
            # JS 返回 null/undefined -> 原始值 "null" -> 重试
            # JS 返回 ''              -> 原始值 '""'(长度2,非null) -> 判成功且 body=''
            #   → 即「真机获取成功但 html 为空、列表 0 条」的确切成因, 必须在 webJs 里禁止
            raw = json.dumps(result, ensure_ascii=False)
            if raw == "null":
                continue
            # 非字符串返回(数字/布尔/数组): 真机后续按字符串用, 这里同等 String 化,
            # 否则 _report 里 len()/count() 直接 TypeError 崩栈。
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            if result == "":
                print("  [%s] webJs 返回 '' → 目标版本判「获取成功」但 body 为空"
                      "(真机表现: 获取成功/html为空/0条)  失败" % label)
                self.fails += 1
                return ""
            self._report(label, attempt + 1, result, expect_sub, strict)
            return result
        print("  [%s] js执行超时(31次未取到合格内容)  失败" % label)
        if strict:
            self.fails += 1
        return ""

    def _report(self, label, attempt, html, expect_sub, strict=True):
        ok = True
        note = ""
        min_hit = DEFAULT_MIN_HIT
        key = expect_sub
        if isinstance(expect_sub, (tuple, list)):   # (子串, 最少命中数)
            key, min_hit = expect_sub[0], expect_sub[1]
        if key:
            hit = html.count(key)
            ok = hit >= min_hit
            note = " %s命中=%d条" % (key, hit)
        elif len(html) < 2000:
            ok = False
            note = " (只有 %dB，疑似半截页面)" % len(html)
        if expect_sub and len(html) < 2000:
            note += " (疑似半截)"
        if attempt:
            print("  [%s] 第%d次尝试成功 %dB%s %s"
                  % (label, attempt, len(html), note, "OK" if ok else "失败"))
        else:
            print("  [%s] %dB%s %s" % (label, len(html), note,
                  "OK" if ok else ("忽略(预热页)" if not strict else "失败")))
        if not strict:                      # 首页/引导页不参与成败判定
            return
        if ok:
            self.passes += 1
        else:
            self.fails += 1

    async def _cold_content(self, page):
        """冷启动直取正文：不带任何 cookie 直接打开一个章节页。
        站点若必须靠前序请求种 cookie 才有内容，这一步会当场暴露。"""
        import re
        src = self.src
        ch_opt = split_url_options((src.get("ruleToc") or {}).get("chapterUrl", ""))[1]
        # content 显式 null 时 .get("content","") 返回 None, re.search(pattern, None) 会 TypeError 崩栈
        rule_text = (src.get("ruleContent") or {}).get("content") or ""
        m = re.search(r"id=[\"']([a-zA-Z0-9_-]+)[\"']", rule_text)
        cid = m.group(1) if m else None
        if not getattr(self.args, "content_url", None):
            print("\n--- 冷启动检查: 跳过(需 --content-url 指定一个真实章节 URL) ---")
            return ""
        url = self.args.content_url
        if not url.startswith("http"):
            url = self.base + url
        print("\n--- 冷启动(无任何 cookie) 直取正文页: %s ---" % url)
        html = await self.fetch(page, url, "冷启正文", ch_opt.get("webJs"),
                                self.delay_of(ch_opt, "ruleToc.chapterUrl"),
                                ('id="%s"' % cid, 1) if cid else None)
        if cid and html and ('id="%s"' % cid) in html:
            print("       正文容器 id='%s' 存在 OK" % cid)
        return html

    async def _deep_check(self, page, ctx, search_html, delay):
        """从搜索结果里取出真实的书/章链接，验证详情→目录→正文整条链路。
        这里用正则直接探链接，不套用书源自身的规则，避免"用规则验规则"的循环论证。"""
        import re
        src = self.src
        print("\n--- 深度链路(详情 / 发现 / 正文) ---")

        ex_list = src.get("exploreUrl")
        if isinstance(ex_list, list) and ex_list:
            # exploreUrl 条目既可以是对象({"url":...}), 也可以是纯字符串(Legado 允许),
            # 旧实现直接 .get("url") 对字符串条目 AttributeError 崩栈
            ex0 = ex_list[0]
            ex_raw = ex0.get("url", "") if isinstance(ex0, dict) else (ex0 if isinstance(ex0, str) else "")
            ex_url, ex_opt = split_url_options(ex_raw)
            await self.fetch(page, ex_url.replace("{{page}}", "1"), "发现页",
                             ex_opt.get("webJs"),
                             self.delay_of(ex_opt, "exploreUrl[0].url"),
                             ("href=", 1))  # 通用链接标记: 不绑死 bookbox 模板, 任何渲染出书籍链接的站点都判通过

        if not search_html:
            print("  (跳过详情/正文: 未取到搜索结果)")
            return

        books = re.findall(r'href="(/\d+/)"', search_html)
        if not books:
            print("  (跳过详情/正文: 搜索结果里没提取到书籍链接)")
            return
        bu_opt = split_url_options(
            (src.get("ruleSearch") or {}).get("bookUrl", ""))[1]
        detail_url = self.base + books[0]
        detail_html = await self.fetch(
            page, detail_url, "详情页", bu_opt.get("webJs"),
            self.delay_of(bu_opt, "ruleSearch.bookUrl"), ("href=", 1))

        ch_opt = split_url_options((src.get("ruleToc") or {}).get("chapterUrl", ""))[1]
        chaps = re.findall(r'href="(/\d+/\d+\.html)"', detail_html)
        if chaps:
            content_html = await self.fetch(
                page, self.base + chaps[0], "正文页", ch_opt.get("webJs"),
                self.delay_of(ch_opt, "ruleToc.chapterUrl"), None)
            rule_text = (src.get("ruleContent") or {}).get("content") or ""
            if content_html:
                m = re.search(r"id=[\"']([a-zA-Z0-9_-]+)[\"']", rule_text)
                if m and m.group(1) in content_html:
                    print("       正文容器 id='%s' 存在 OK" % m.group(1))
                    self.passes += 1
                else:
                    print("       正文容器 %s 未命中 失败" % (m.group(1) if m else "?"))
                    self.fails += 1
        else:
            print("  (跳过正文: 详情页里没提取到章节链接)")

    async def run(self):
        src, args = self.src, self.args
        search_url, opt = split_url_options(src.get("searchUrl"))
        webjs = opt.get("webJs")
        delay = self.delay_of(opt, "searchUrl")
        print("书源: %s" % src.get("bookSourceName"))
        print("目标 App 版本指纹: 325 (legado 3.25 反编译版, 等待字段 webWait, 重试间隔 1000ms(单次))")
        print("searchUrl 行内选项: webView=%s %s=%s charset=%s webJs=%s\n"
              % (opt.get("webView"), self.wait_field, delay, opt.get("charset"),
                 "已配置" if webjs else "无"))

        async with async_playwright() as p:
            br = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await br.new_context(user_agent=DEFAULT_UA, locale="zh-CN")
            if getattr(self.args, "poison", False):
                # 复刻 3.25 CookieStore 永久注入: AnalyzeUrl.setCookie() 把
                # CookieStore(数据库, 不解析 max-age) 的 cookie 并入 headerMap,
                # 经 webView.loadUrl(url, headerMap) 注入主框架请求。
                # 用「每个主框架文档请求前把限流 cookie 回种进 jar」模拟——
                # webJs 删 document.cookie 也删不掉注入源, 与真机一致;
                # 页内 XHR 不回种(真机上 XHR 不带注入头)。
                pc_name, _, pc_val = getattr(
                    self.args, "poison_cookie", "ss_search_delay=1").partition("=")
                far = int(time.time()) + 86400 * 365
                host = self.base.split("//")[-1].split("/")[0]

                async def _seed():
                    await ctx.add_cookies([{
                        "name": pc_name, "value": pc_val, "domain": host,
                        "path": "/", "expires": far, "httpOnly": False}])

                async def _poison_route(route):
                    req = route.request
                    if req.resource_type == "document" and host in req.url:
                        await _seed()
                    await route.continue_()

                await ctx.route("**/*", _poison_route)
                await _seed()
                print("已启用 CookieStore 注入模拟: 主框架请求前回种 %s=%s"
                      % (pc_name, pc_val))
            page = await ctx.new_page()
            page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

            if args.cold:
                # 最严苛：无任何 cookie 时直接开正文页，暴露"必须预热才有内容"的站点
                await self._cold_content(page)

            # 引导页不参与成败判定：它没有列表，半截也只是预热的副产品
            if not args.cold:
                await self.fetch(page, self.base + "/", "首页(预热)", None, delay,
                                 strict=False)

            print("\n--- 连续 %d 次搜索「%s」(间隔 %dms) ---" % (args.times, args.key, args.gap))
            key = args.key
            try:
                from urllib.parse import quote
                key_enc = quote(key)
            except Exception:
                key_enc = key
            url = search_url.replace("{{key}}", key_enc)
            last_html = ""
            for n in range(1, args.times + 1):
                if n > 1:
                    await page.wait_for_timeout(args.gap)
                last_html = await self.fetch(page, url, "搜索#%d" % n, webjs, delay, ("href=", 1))
                if args.stop_on_fail and self.fails:
                    break

            names = [c["name"] for c in await ctx.cookies()]
            print("\n--- cookie ---")
            print("  %s" % names)
            delay_like = [n for n in names if "delay" in n.lower()]
            print("  限流类 cookie: %s" % (delay_like if delay_like else "无"))

            await self._deep_check(page, ctx, last_html, delay)
            await br.close()

        if self.field_errors:
            print("\n--- 字段名与目标版本不匹配(会被 Gson 静默丢弃) ---")
            for e in sorted(set(self.field_errors)):
                print("  [严重] %s" % e)
        print("\n========================================")
        print("结果: 通过 %d  失败 %d  字段问题 %d"
              % (self.passes, self.fails, len(set(self.field_errors))))
        print("========================================")
        return 1 if (self.fails or self.field_errors) else 0


def main():
    ap = argparse.ArgumentParser(description="忠实复现 Legado 抓取时序，实跑书源")
    ap.add_argument("source", help="书源 JSON 文件路径")
    ap.add_argument("--times", type=int, default=3, help="连续搜索次数(默认3)")
    ap.add_argument("--gap", type=int, default=6000, help="搜索间隔毫秒(默认6000)")
    ap.add_argument("--key", default="系统", help="搜索关键词(默认:系统)")
    ap.add_argument("--stop-on-fail", action="store_true", help="首次失败即停止")
    ap.add_argument("--cold", action="store_true",
                    help="冷启动模式: 不做首页预热, 先以无任何 cookie 的状态直取正文页")
    ap.add_argument("--content-url",
                    help="冷启动模式使用的真实章节 URL(绝对路径或相对站点根的 /数字/数字.html)")
    ap.add_argument("--poison", action="store_true",
                    help="模拟 3.25 CookieStore 永久注入: 主框架请求追加恒定限流 cookie "
                         "(配套 --gap 0 可复现窗口内极速二搜)")
    ap.add_argument("--poison-cookie", default="ss_search_delay=1",
                    help="注入的 cookie 键值对(默认 ss_search_delay=1)")
    args = ap.parse_args()

    src = load_source(args.source)
    rc = Checker(src, args)
    sys.exit(asyncio.run(rc.run()))


if __name__ == "__main__":
    main()
