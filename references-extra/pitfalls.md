# Legado 书源：实战铁律与排错（反编译/真机实证）

> 由 SKILL.md 下沉的详细内容，按需查阅。

## 🔴 方法论第一原则：先取证真实响应，再改规则

> **最惨痛的一课**：把"App 源码查看器里能看到明文正文、但 XPath 取空"直接诊断为"正文是 JS 渲染注入的，必须上 WebView"，于是死磕 WebView 方案（8 秒/章）多版。真相是 **cookie 判别**（无有效 cookie 时服务器返回挖空容器+解密脚本，有 cookie 时静态 HTML 直接给明文正文），直连 2 秒即通。
> **根因不是规则写错，是"真实响应长什么样"没确认就动手了。**

### 铁律 0：改任何"解析失败"规则前，先取证真实响应（带 / 不带 cookie 各抓一次对比）

- **不要**上来就套"JS 渲染 → WebView""列表空 → 分两页"等模板。先回答：**你的请求在真实环境里到底拿到了什么？**
- **抓取对比动作**（沙盒可做）：用 `scripts/fetch_page.py`（curl_cffi 指纹伪装）或 `scripts/bypass_cf.py` 分别以**带 cookie / 不带 cookie / 带 CF clearance** 三种状态各抓一次正文页，对比 HTML 差异：
  - 不带 cookie 就被挖空 / 跳挑战页 → **cookie 问题**，解法 = `enabledCookieJar:true` + 先过一次 CF（WebView 或 bypass_cf 提取 clearance 落库），**不是** WebView 解析；
  - 三种状态都能拿到明文正文 → 纯静态解析，**别上 WebView**；
  - 只有浏览器渲染后 DOM 里才有正文、三种直连都挖空 → **真 JS 渲染**（这时才上 `chapterUrl` 内联 `webView` + 足够 `webWait`）。
- **关键边界（必须刻进脑海）**：本技能的 `test_parse.py` / JsoupXpath / Rhino 本地验证**只验证静态 HTML 的解析语法**，**覆盖不了"CF / cookie 判别"这类动态响应分支**。本地验证通过 ≠ 真机能拿正文。

### 正文空（ContentEmptyException）根因判别决策树

> 触发：目录正常、正文页"获取成功"但解析后空。**按以下顺序排查，不要跳步**：

| 顺序 | 检查项 | 判别方法 | 若是 → 解法 |
|---|---|---|---|
| ① | 真实响应是不是被 CF / cookie 拦截的挖空页？ | 带 / 不带 cookie 各抓一次正文页对比 | 不带 cookie 即挖空 → `enabledCookieJar:true` + 先过一次 CF 落 cookie（WebView 或 bypass_cf）；**非 WebView 解析** |
| ② | 是不是静态 HTML 里就有正文、只是规则 XPath 没命？ | 把真实响应（带 cookie）存成样本，用 `test_parse.py` 验 XPath | 命中失败 → 修 XPath / CSS / Regex；**别上 WebView** |
| ③ | 是不是真 JS 渲染（无 JS 执行 DOM 就空）？ | 直连 HTML 正文容器空、浏览器渲染后才有 | 上 `chapterUrl` 内联 `webView:true` + `webWait` ≥ 8000（AES 解密站） |
| ④ | 是不是 `content` 规则本身把正文滤掉了？ | 检查 content 的 JS 过滤黑名单 / `replaceRegex` | 放宽过滤；注意本 App `ruleContent.replaceRegex` 是死字段（见铁律 5），净化写进 content 的 JS |

> **优先级铁律**：①（cookie / CF）永远先于 ③（JS 渲染）。绝大多数"源码有明文但取空"其实是 ①，不是 ③。本技能过去的"JS 渲染站"章节把 ③ 当默认路径，是这次误判的根源，已改为以 ① 为优先。

### 本地验证的边界（别被它误导）

- **能证**：某条 XPath / CSS / Regex / JSONPath 在**给定 HTML 样本**上是否命中、命中数、样例值；JS 语法在 Rhino 下能否跑、分支逻辑对不对。
- **不能证**：真实网络分支（CF 挑战、cookie 判别、签名时效）、App 内置引擎的偶发差异、设备侧（网络出口 / WebView 实现）差异。
- 任何涉及"请求拿没拿到真内容"的问题，**用真实响应取证**，不要用本地静态验证替代。

## 🔴 实战铁律补遗（反编译实锤）

> 以下四条是把"正文取空"彻底修通后固化的硬结论，全部有 APK 源码 / Rhino 复现支撑，非经验猜测。

- **铁律 1：`enabledCookieJar` 不写 = false（AnalyzeUrl.java:643 三元判空）**
  - 缺省 false 时，OkHttp 请求**不**带 `CookieJar:1` 头，响应 `Set-Cookie` 不进 CookieStore 跨请求复用；CF 过后的 `cf_clearance` / `is_human` 落不了库，后续 OkHttp 直连仍被挡。
  - **CF 站 / 明文 cookie 验证站必须显式写 `"enabledCookieJar": true`**。它与 webWait 是此类站点最常见的两处真实差异。
- **铁律 2：webView `webWait` 必须覆盖客户端解密脚本耗时**
  - 正文由 crypto-js AES 解密注入时，脚本耗时数秒；webWait 不足 → `div#article` 仍空 → XPath 与 `src` 都拿空（实测：chapterUrl 给 3000、tocUrl 给 8000 都偏短）。
  - **AES 解密站一律 8000ms 起步**；`tocUrl` 与 `chapterUrl` 两个 webView 选项**都要给够**。
- **铁律 3：`loginCheckJs` 在本 App（legado 3.25 反编译版）是生效字段 —— 之前判"死代码"是错的，已用 APK 反编译 + 真机双证实推翻**
  - 反编译 `BaseSource$DefaultImpls.putLoginHeader`：每次请求后执行 loginCheckJs，把返回值当 JSON，取 `"Cookie"`/`"cookie"` → `CookieStore.replaceCookie(key, value)` 落库；`getLoginHeader` 在后续请求自动把该 cookie 带上。完整链路存在，**不是死代码**。
  - 真机实证：用户 V14 书源用它（`java.connect` 重取 + `cookie.setCookie` 写 `is_human`）过爪机书屋搜索墙，**真机搜索正常**；V15 弃用它改用 `searchUrl` 内联 `<js>` 反而搜不到。
  - **过验证墙/取明文 cookie 优先用 `loginCheckJs`**（本 App 实测最稳）；它返回的对象必须带 `result`（修改后的响应）。注意 3.25 的 `loginCheckJs` **不能带 `<js>` 标签**（不剥标签，Rhino 在 `<` 处语法错）。
- **铁律 4：webView 模式下 `src` = 渲染后 `outerHTML`，不是静态响应**
  - `evalJS` 绑定 `scriptBindings.set("src", this.content)`，webView 模式 content 就是 `document.documentElement.outerHTML`（JS 执行后 DOM）。
  - 因此纯 JS 正则兜底**同样依赖 webWait 足够**；先保证 webWait，再谈 `src` 提取。
- **铁律 5：`ruleContent.replaceRegex` 在 3.25 定制版 APK 是死字段（反编译实锤）**：写在 `ruleContent` 里的 `replaceRegex` 全代码库零消费点，正文净化写不进去，必须写进 content 的 `<js>`。
  - 3.25 定制版：全代码库检索，`ContentRule.getReplaceRegex` 除实体定义/编辑界面/相等比较外**零消费点**——写在这里的净化正则**不执行**。
    净化的可靠位置是 **content 规则的 JS 内**或规则内联 `##`。
  - **口径**：别的 Legado 版本里 `replaceRegex` 可能生效（执行点排在格式化之后、作用对象是纯文本），
    但本技能**只以用户提供的 3.25 反编译为准、不引用官方仓库**（见 SKILL.md「绝不下载官方源码」）。
    在 3.25 上它就是死的 —— 别把净化写进去赌别的版本。
  - **结论**：删 HTML 节点一律写 `content` 的行内 `##`；**要删纯文字也写行内 `##`**（对已抽取的文本同样生效），
    不要依赖 `replaceRegex`。
- **铁律 6：正文"JS 渲染"很可能是"cookie 判别"的表象**
  - 爪机书屋实测：`enabledCookieJar:true` + webView 过过一次 CF 后，cookie 落库，**纯 OkHttp 直连 2 秒即得明文正文**（无需 webView、无需等解密）。
  - 机制：无有效 cookie → 服务器返回挖空容器 + 解密脚本（防爬）；有有效 cookie → 静态 HTML 直接给明文正文。之前判"必须 JS 渲染"是被挖空页误导。
  - **代价/风险**：直连版依赖 cookie 有效期（is_human 约 1 小时）——过期后直连重新拿空。自救：换 webView 版刷任意一章（重新种 cookie）再切回直连版；或稳定场景直接用 webView 版（慢但自愈）。
  - **诊断启示**：正文空 + 源码有解密脚本 ≠ 必须上 webView。先检查 `enabledCookieJar` 是否开启、cookie 是否落库，**先试直连**，不行再上 webView（8 秒/章的成本差异巨大）。

- **铁律 7：3.25 的等待字段只有 `webWait`，`webViewDelayTime` 会被静默丢弃（实证）**
  - **legado 3.25 反编译版** `UrlOption` 元数据实证为 `method, charset, headers, body, origin, retry,
    type, webView, webWait, webJs, js, serverID`，**等待字段叫 `webWait`**，**没有 `webViewDelayTime`**，
    也没有 `bodyJs` / `dnsIp`。
  - **Gson 不拒绝未知字段**：写成 `webViewDelayTime` = 不报错、不警告、不生效。**这是"本地验证全绿、真机全空"的头号成因**。
  - **3.25 正确写法：只写 `webWait`**，不要写 `webViewDelayTime`（写了也不生效，纯属误导）。
  - 排查动作：用户说"真机失败但你说验证过了"，**第一件事是查书源里所有行内选项是否用了 `webWait`**，
    而不是误写成 `webViewDelayTime`。
  - **两个易踩点**：① 不填 `webJs` 时 `webWait` 缺省约 1000ms（3.25 节奏）；② **一旦填了 `webJs`，默认等待失效**，
    只剩约 100ms 基础延迟——此时必须显式写 `webWait`，否则页面还没渲染完就开始取 DOM。
  - **`webJs` 重试节奏（3.25 实证，判定标准：结果非空且非 `"null"`）**：
    **失败后固定 1000ms 重试，最多 31 次**（不是递增；`help/http/c.java` 实证）。
    - 3.25 是**只重跑 JS、不重新发起请求**——所以"重试"救不了请求本身失败的情况，只救"页面还在渲染"。
- **铁律 8：URL 选项的 `webJs` 没有 JSBridge，`java.ajaxAwait` 只在规则 JS 里可用**
  - `BackstageWebView` 构造参数 `isRule` 决定是否注入 `getInjectionString`（含 `java.ajaxAwait` / `cache` / `source` 等桥）。
  - **URL 行内选项的 `webJs` 走 `isRule=false` → 无任何桥**，`java.*` 不存在；只有**规则里的 webJs**（`AnalyzeRule.getWebJsResult` 传 `isRule=true`）才有桥。
  - `webJs` 返回 **Promise 是最坏的失败模式**：`evaluateJavascript` 拿到的是 JSON 序列化的 `"{}"`，非空且 ≠ `"null"` → 判定成功 → **静默返回 `{}`，不报错、不重试**。写 `async` 函数等于静默失败。
  - `bodyJs` 只在非 webView 的 OkHttp 分支生效，**webView 模式下写了无效**。webView 返回的 HTML 不经过任何后处理，直接成为 body。
- **铁律 9：WebView 的 Cookie 与 `enabledCookieJar` 完全隔离，书源配置无法在请求前清 Cookie**
  - `enabledCookieJar` / `CookieStore` / `AnalyzeUrl.setCookie()` 只作用于 **OkHttp 侧**的 headerMap；WebView 用 Android 全局单例 `android.webkit.CookieManager`，**跨书源、跨请求共享**。把 `enabledCookieJar` 设成 false 对 WebView 无效。
  - `webView.loadUrl(url, headerMap)` 会把书源 header 下发，但 CookieManager 的 cookie 会与之**合并**——在 header 里写空值 Cookie 压不掉旧值。
  - `onPageFinished` 还会 `setCookie(url)` 把 WebView cookie **回写 CookieStore**，且**不看 `enabledCookieJar`**——双向污染。
  - **推论：靠 cookie 做限流的站点（如 `ss_search_delay`），第一次搜索后必然污染后续请求**；
    `webJs` 只能**事后**清理（页面已加载完才执行，请求发出时的 cookie 已带上）——但**不是唯一手段**：
    URL 行内选项的 **`js` 字段在发请求之前执行**，可事前清 CookieStore（见**铁律 16** 双清闭环）。
    ⚠️ 本行曾写"唯一可用手段是 webJs、无法在请求发出前干预"，与铁律 16 直接矛盾，已订正。
- **铁律 10：正文净化只有行内 `##` 可靠 —— `replaceRegex` 在 3.25 是死字段（与铁律 5 同一结论）**
  - `content` 规则的**行内 `##正则##替换##`**：在 `AnalyzeRule.getString()` 内部、`HtmlFormatter` **之前**执行，
    作用对象是 **HTML 字符串**（XPath 抽取结果的 outerHTML）。要删 DOM 里的广告节点用这里，写法须匹配标签：
    `//div[@id='rtext']##<a[^>]*>[^<]*返回顶部[^<]*</a>##`
  - `ruleContent.replaceRegex` 字段：在 3.25 定制版全代码库**零消费点**（铁律 5 实证）→ **写了不执行**。
    别照抄"它在格式化之后对纯文本生效"的说法 —— 那是别的版本的行为，本 App 不适用；按它写净化会静默失效。
  - 两者都不是 DOTALL（Kotlin `String.replace(Regex)`）；跨行匹配用 `[^<]*` / `[\s\S]*` 显式表达，不要依赖 `.`。
  - **避坑**：行内替换里优先用**不含反斜杠**的正则（如 `[^>]*` `[^<]*`）。`\s` 在 JSON 里要写成 `\\s`，
    一旦转义层数搞错就静默失效，而且本地验证时如果直接从文件原文取字符串、不做 JSON 反转义，
    会把 `\\s` 当真，测出来"通过"而真机失效。
- **铁律 11：URL 行内 `webJs` 必须自带「内容够不够」判定，否则会把半截页面当成结果返回**
  - `BackstageWebView` 的判定只有 `result.isNotEmpty() && result != "null"`：**半截页面也算成功**。
    然后重试是有内容的——按 **固定 1000ms**（3.25 实证，不是递增）最多 31 次重跑同一个 JS，**不会重新发起请求**。
    ⚠️ 曾在本文件写成"按 200/400/600/800/1000ms 递增"，那是**旧版本**残留，与 3.25 反编译及
    `realcheck.py` 的 `RETRY_INTERVALS = {"325": [1000]}` 冲突，已订正。
  - 所以无条件 `return outerHTML` 的 webJs **等于放弃了整个重试机制**：首次 evaluate 时页面往往只渲染到
    `<head>`（实测 854B），立刻返回 → 列表 0 条。这是"第一次搜索正常、之后全空"类故障的头号成因。
  - **清理 cookie 必须放在判定之前**：若写成「先判 bookbox 再清 cookie」，被限流那次走不到清理分支，
    脏 cookie 会一直带到后续请求；写成「先清后判」，即使本次失败，下一次请求也是干净的。
  - 实测对照（同一站点、连续 3 次搜索、均在 30s 窗口内）：无 webJs → 1 成 2 败；无条件 webJs → 1 成 2 次返回半截；
    **先清后判 + 判定特征 → 3 次全部第 1 次尝试即成功**（当时那轮实验用的是长度判定，纯属该站页面长度分布稳定；
    判定特征选型见铁律 12——正确做法是用内容锚点，不是长度）。
  - **判定特征必须用「内容锚点」，不能用「挑战页特征」或「长度」**（踩过坑，见铁律 12）：
    正确写法是判**该页面独有的内容标记**，例如搜索/发现页判 `h.indexOf('bookbox')<0`、详情页判 `booktitle`、
    正文页判 `'id="rtext"'`。这类标记在半截页和挑战页里都是 0，能精确触发重试。
- **铁律 12：`webJs` 判定禁用「可疑特征黑名单」，且 HTTP 状态码不代表内容成败（踩坑实录）**
  - 曾经用"页面像不像挑战页"做判定：`if(h.indexOf('window.location.href')>=0) return '';`
    ——结果**正常正文页里也有这串**（CNZZ/百度统计的 `trackPageview(window.location.href, '书名', '章节名', ...)`），
    于是每一页都被判成挑战页 → 31 次重试全空 → 真机"js执行超时"。
    **教训：黑名单里的字符串要先在真实正常页里数一遍出现次数，非 0 就不能用。**
  - 同理，长度判定（`h.length<2000`）也不可靠：有的反爬页有 9KB 骨架，有的真页面只有 8KB。
    判"内容对不对"永远比判"像不像坏页面"可靠。
  - **`HTTP 403 ≠ 内容失败**：本站所有页面都可能返回 403，但 body 是完全正常的 HTML。
    webView 模式不检查状态码，只看 `webJs` 返回；所以不要拿 403 当失败依据，也不要为它加额外处理。
  - **锚点要在半截页上验一遍**：用 `page.goto(..., wait_until="domcontentloaded")` 后立刻 evaluate 一次、
    等 3s 再 evaluate 一次，对比锚点计数。若半截状态下锚点已 >0，说明该锚点出现在 `<head>`/CSS 里
    （例如 `rtext` 先出现在 `<style>#rtext p{...}`），必须收紧成带属性的写法 `id="rtext"`。

- **铁律 13：webJs 的「未就绪」信号必须 `return null`，绝不能 `return ''`（真机事故实锤，3.25 c.java 字节码级实证）**
  - Legado 对 `evaluateJavascript` 结果的判定用的是 **Android 回传的原始字符串（JSON 编码后的）**：
    `if (原始值.length <= 0 || 原始值 == "null") 重试 else 成功`。
  - 换算成 JS 侧返回值：`return null`/不返回（undefined）→ 原始值 `"null"` → **触发重试**；
    **`return ''` → 原始值 `'""'`（两个引号，长度 2，非 null）→ 直接判「获取成功」，body 为空字符串**。
  - 真机表现：日志「获取成功」耗时 ≈ 加载+等待，html 查看为空，列表 0 条——**全程无报错**。
    这正是「webJs 明明写了判定、真机却静默空结果」的成因。
  - **为什么本地模拟测不出来**：自写模拟器常把「返回空 → 重试」写成测试逻辑，等于替 Legado 补了它没有的行为，
    模拟器比被测对象更聪明，测试就失效了。**模拟重试判定必须照抄反编译源码的原始值语义**。
  - 正确模板（未就绪 return null → Legado 每 1000ms 重试、最多 31 次；就绪 return h）：
    `(function(){try{var h=document.documentElement.outerHTML;if(h.indexOf('<锚点>')<0)return null;return h;}catch(e){return null;}})()`
  - 顺带纠正：3.25 同样按原始值判定，`return ''` 不安全；`return null` 触发重试。

- **铁律 14（v2 修正）：cookie 限流要分清「预防」与「自救」两件事；自愈用 `location.replace()`，不要用 XHR，也不要用 `reload()`**
  - 注入链（3.25 反编译 `AnalyzeUrl.setCookie()`）：
    ① `CookieStore.getCookie(domain)` 非空 → 与书源 `header` 里的 Cookie **合并**后 `headerMap.put("Cookie", …)`，**不看 `enabledCookieJar`**（`enabledCookieJar` 只额外加 `CookieJar:1` 头）；
    ② `webView.loadUrl(url, headerMap)`——**headerMap 只作用于这一次 `loadUrl`**，页面内的后续导航不再携带。
  - **回写实锤（v3 终版结论，勿再反复）**：webView 路径**每页加载完成都会把 WebView cookie 回写 CookieStore**。证据：官方版 `BackstageWebView.kt:183-188`（`onPageFinished → setCookie(url) → CookieManager.getCookie(url) → CookieStore.setCookie`）；3.25 反编译版同名逻辑被混淆为 `help/http/e.java`（`extends WebViewClient`，26 行）与 `f.java`（WebChromeClient，75 行）。**1.8.0 版曾写"不回写"是因为在反编译源里按 BackstageWebView 类名 grep 没对上混淆名（l.java+e.java+f.java）——教训：混淆代码要按行为特征（继承 WebViewClient）搜，不能按官方类名搜。**
  - **完整污染闭环（六步，全部实锤）**：① 搜索成功，服务端 `Set-Cookie: <限流cookie>=1; expires=<now+30s>`（浏览器 30 秒后自动删）；② webView `onPageFinished` 回写进 CookieStore（数据库+内存）；③ `CookieStore.cookieToMap` 只按 `name=value` 解析、**不解析过期时间** → 该条目在 CookieStore 里**永久存活**；④ 下次搜索 `AnalyzeUrl.setCookie()` 无条件注入 → 限流；⑤ 限流页 `alert()+history.go(-1)` → about:blank 死局；⑥ 31 次重试全 null → 40.5s「js执行超时」，或吃满请求层协程预算 → 60s `TimeoutCancellationException: Timed out waiting for 60000 ms`。
  - **为什么 `reload()` 救不了**：`reload()` 复用首次 `loadUrl` 的额外请求头（含被注入的 Cookie），删掉的 cookie 原地复活 → 限流循环。
  - **为什么 XHR 兜底不可靠**：XHR 不是文档导航，遇到「403 + JS 自跳转」型挑战时拿回的仍是挑战壳页；一旦页面已被踢到 `about:blank`，XHR 直接抛 `NetworkError: about:blank`。
  - **正确自愈 = `location.replace(location.href)`**：`replace` 是**全新导航**，只带 CookieManager 的 cookie，不含首次 `loadUrl` 的注入头。先删限流 cookie 再 replace，并加**节流**（两次 replace 间隔 > 2.5s）避免打断正在进行的导航。
  - **预防优先于自救**：命中锚点后立即删除限流 cookie，让下一次请求天然干净。实测：连续 3 次搜索全部命中，cookie 全程为空。
  - 工具：`realcheck.py --poison [--poison-cookie name=value]`（主框架请求前回种 cookie，XHR 不回种）。**注意**：Playwright 无法模拟 `loadUrl` 的 headerMap 注入，也无法模拟真机 webView 的历史累积，因此模拟器对 `replace` 方案偏保守（真机通常更好），对 `reload` 方案偏乐观（真机更差）——判读结果时要带上这层偏差。

- **铁律 15：「403 + JS 自跳转」挑战站，以及 `history.go(-1)` 造成的 about:blank 死局（真机 31 次全 null 实锤）**
  - > ⚠️ **v8 修正（先读这段，避免误判站型）**：下面"只能用 webView"的结论只对**硬 JS 挑战**（带 cookie 二访 HTTP 仍 403、必须浏览器执行 JS 才算过）成立。shumi99 实测是**另一类「首访 403 壳页、cookie 可复用」**：首访 403 + Set-Cookie，二访（带 cookie 的普通 HTTP 请求即可）直接 200 真内容——那段 `window.location.href` 跳转纯粹是让浏览器带着 cookie 再请求一次，HTTP 层 cookie 复用就能完成，**不需要浏览器真执行 JS**。对这类站，**普通 HTTP + `enabledCookieJar:true` + `loginCheckJs`（检测到壳页就 `java.connect(result.url())` 重取一次）即可过**（v8 真机实证搜索正常），用 webView 反而卡壳页。判据：**带 cookie 二访返回 200 真内容 → 壳页型走 HTTP+loginCheckJs；带 cookie 二访仍 403 → 硬挑战型走 webView**。详见 site-patterns.md「首访 403 壳页」一节。
  - 挑战形态：首次请求返回 `403` + `Set-Cookie: <随机名>=<随机值>; expires=+2h`，body 只有一行
    `<script> window.location.href ="/同一URL"; </script>`
    浏览器自动跳转并带上 cookie → 第二次 200 正常页。**curl 永远过不了**——即使把 Chromium 的全部请求头逐字照抄也仍 403，说明挑战认的是连接复用/导航语义而非请求头字面值 ⇒ **这条只适用于硬 JS 挑战型**；壳页型（shumi99）cookie 可复用，走 HTTP+loginCheckJs 即可。
  - 限流形态：命中的**不是**"提示页"，而是
    `<script>alert("搜索间隔: 30 秒");window.history.go(-1);</script>`
    执行后 `history.go(-1)`；当 webView 历史里前一条是初始空白页时，页面停在 **`about:blank`**。
  - **about:blank 是真死局，页面内部无法自救**（实测）：`document.cookie` 抛 `SecurityError`、`document.referrer` 为空、XHR 抛 `NetworkError`、`history.forward()` 连续 12 次无效、页面恒为 39 字节。**这一组现象可作为"页面被踢到 about:blank"的判据**。
  - webJs 的 webView 内自救写法已被 **v2.0.0 极简方案**（见铁律 16 末条）取代：旧「三层自救 + `sessionStorage` 节流」方案曾把 about:blank 分支写成 `return null`，导致 31 次重试全 null ≈ 40s「js执行超时」；现行方案对 about:blank / 限流页 / 首页一律 **直接 `return outerHTML` 秒回**（最坏只是解析 0 条，不卡 60s），`sessionStorage`/`setTimeout` 节流全部删除。本铁律的 about:blank 判据描述仍有效，处方以铁律 16 v2.0.0 为准。
  - **② 的判定条件必须写 `location.href.indexOf('<域名>')>=0`，绝不要用限流文案关键词**（如「搜索间隔」）做判断：那段文案在 `alert()` 里，页面被踢走后压根读不到——旧版本正是死在这一条上。
  - 取证提醒：动手前先确认**书源真实使用的 URL**（从 JSON 的 `searchUrl` 里取，别凭印象拼）。在错误 URL 上做对照实验会得到完全相反的结论。

- **铁律 16：破解 CookieStore 永久注入的正解 = 「双清闭环」——事前用 URL 选项 `js` 字段清 CookieStore，事后用 webJs 清 CookieManager（3.25 全字段反编译实锤）**
  - **`js` 字段（3.25 UrlOption 官方字段）**：`AnalyzeUrl.analyzeUrl()` 解析行内选项时执行 `evalJS(js, this.url)`，**返回值非 null 则替换请求 URL，返回 null 则 URL 原样**；其绑定环境（`evalJS` 通用绑定）含 `java`/`baseUrl`/`cookie`(=CookieStore 实例)/`cache`/`key`/`source`/`result`。**执行时机在发请求之前** → 天然的"请求前钩子"。
  - 事前清（searchUrl 的 `js` 字段）：`cookie.getCookie('http://站点/')` 取串 → 按分号拆分剔除限流键 → `cookie.setCookie(url, 新串)` 回写。实测六种污染形态（限流在前/后/带空格/仅有/干净/空）6/6 通过。**存量污染自动自愈，用户无需手动清 Cookie**。
  - 事后清（webJs 命中锚点时删 `document.cookie`）：保证 **WebView CookieManager**（App 级共享，30 秒内仍有效）不积累；且 onPageFinished 回写进 CookieStore 的内容也不再含限流键 → 不产生新的永久条目。
  - **双清缺一不可**：只做事前清，CookieManager 里 30 秒内的旧 cookie 仍会被浏览器自动带上；只做事后清，CookieStore 的永久条目每次都抢先注入。两层都做，任一时刻任一存储都是干净的。
  - **`loginCheckJs` 的版本适用性（v8 修正，推翻旧结论）**：旧版曾写"3.25 反编译版 `WebBook` 链路不执行书源 `loginCheckJs`（仅 RSS 用）"——**这是错的，已被 v8 真机实证推翻**。本 App（3.25 反编译版）`loginCheckJs` 在**每次 HTTP 请求返回后都执行**（铁律 3 的 APK 反编译 + line 296 的真机证实已坐实）；v8 正是靠它在 shumi99 的**搜索（WebBook）链路**上检测 403 壳页并 `java.connect` 重取一次过墙。正确结论：走 webView 的站点 `loginCheckJs` 对 webView 内部导航不生效（过墙靠 webJs），但**普通 HTTP 书源链路（含搜索）`loginCheckJs` 每次请求后都执行、过"验证墙/壳页/限流页"首选此钩子**。照抄他人结论前先以本 App 真机/APK 实锤为准。
  - **超时报错甄别**：`kotlinx.coroutines.TimeoutCancellationException: Timed out waiting for 60000 ms` = 请求层协程 60s 硬超时（webView 反复导航吃满预算）；OkHttp 层还有 `callTimeout(60s)`（`help/http/w.java`）但抛的是 `SocketTimeoutException`。看到 60s 协程超时优先怀疑 webView 死循环/死局，而不是网络慢。
  - **403 挑战：分类型处理（v8 修正，推翻"一律不要 HTTP 直连"的旧结论）**。旧结论"HTTP 直连成功率极低、只能走 webView"**只对硬 JS 挑战型成立**（带 cookie 二访 HTTP 仍 403、必须浏览器执行 JS 才算过）。但 shumi99 实测是**另一类「首访 403 壳页、cookie 可复用」**：首访 403+Set-Cookie，二访带 cookie 的**普通 HTTP** 即 200 真内容（那段 `window.location.href` 只是让浏览器带 cookie 再请求一次，HTTP 层 cookie 复用就能完成，不需要浏览器真跑 JS）。对壳页型，**普通 HTTP + `enabledCookieJar:true` + `loginCheckJs`（检测到壳页就 `java.connect(result.url())` 重取一次）即可过**（v8 真机实证搜索正常），用 webView 反而卡壳页。**判据：带 cookie 二访返回 200 真内容 → 壳页型走 HTTP+loginCheckJs；带 cookie 二访仍 403 → 硬挑战型走 webView**。详见 site-patterns.md「首访 403 壳页」一节与铁律 15 顶部的 v8 修正框。
  - **60s 死局已完整复现（Playwright 污染场景）**：提前种入限流 cookie 后再访问搜索页，页面稳定呈现 `location.href = about:blank` / `document.cookie` 抛 `SecurityError` / `outerHTML` 恒 39 字节 / webJs 连续 5 次（乃至 31 次）返回 null —— 与真机 `TimeoutCancellationException: Timed out waiting for 60000 ms` 是同一件事。**这组四联征就是死局的判据**，出现即说明请求头带上了限流 cookie，回头查 CookieStore（铁律 16 事前清）而不是继续调 webJs。
  - **人工种 cookie 的污染测试比真机更严苛**：真机上 webJs 会在搜索成功后立刻删掉浏览器侧 cookie，CookieManager 通常本来就是干净的；真机真正的污染源是 webJs 管不到的 CookieStore。所以"`add_cookies` 种入后 webJs 救不回来"属于预期结果（悲观场景），不代表真机会失败——判读复现结果时要分清这一层。
  - **3.25 反编译版只认 `webWait`、不认 `webViewDelayTime`（实测坐实，极易踩坑）**：3.25 反编译混淆版 `UrlOption` 的等待字段名是 `webWait`，而 `webViewDelayTime` 是该版**不存在**的字段，Gson 静默丢弃未知字段 ⇒ 若只在行内选项写 `webViewDelayTime`，用户 3.25 上**该等待不生效**，webView 在默认约 100ms 时就取 DOM → 拿不到结果/取空。**3.25 书源只写 `webWait` 即可**（不要写 `webViewDelayTime`）；复刻他人书源时要先确认目标 App 用哪个字段名。
  - **极简 webJs 设计原则（v2.0.0 重写结论，推翻此前"三层自救+节流"方案）**：webJs 越长、分支越多，越容易在真机上某分支行为不符预期而整体锁死，且 60s 超时日志无法定位坏在哪一层。正确做法是**每个分支必须有确定出口、绝不允许无限重试**：① `try{document.cookie='ss_search_delay=...;expires=<过去>;path=/'}` 清浏览器侧限流 cookie（顺便让回写 CookieStore 的内容也干净）；② 含结果锚点 → `return outerHTML`；③ 仅当 `location.href` 仍是本站 `/search/` 路径**且非限流页**（无 `history.go` 字样）→ `location.replace(u)` 重载一次（兜底过挑战）→ `return null`；④ 其余（限流页/about:blank/首页/其他）→ **直接 `return outerHTML`**。这样最坏情况只是"解析得 0 条 = 显示无结果并秒回"，**绝不卡 60 秒**。`sessionStorage` 节流、`setTimeout`、对 `java.`/`cookie.getCookie` 的调用等统统删掉。
  - **③ 的 replace 在重试周期里会重复触发（没有"只换一次"的开关），这是被允许的**：每次 evaluate 要么命中锚点走②返回，要么 replace 一次后 return null 等下一个 1000ms 周期；Legado 的重试循环本身有 31 次上限，最坏 31 个周期内必然结束，不会死锁。旧方案用 `sessionStorage` 记时间戳保证"一次"，代价是每次重试都读Storage、分支更长，v2.0.0 起删除。

- **铁律 17：所有内嵌 JS 片段必须经语法校验再交付（v6 翻车教训）**
  - **惨案**：v6 在 `searchUrl` 的 `js` 字段里写了带 `java.connect` 的重取代码，末尾**少一个 `}`**，Legado 内置 Rhino 报 `missing ) after argument list` 直接整段失效——而且 `validate_booksource.py` 当时**不校验 JS 语法**，本地全绿、真机全挂，定位花了好几轮。
  - **现技能已补**：`validate_booksource.py` 新增 `check_js_syntax()`——扫描书源里**所有** JS 片段（`loginCheckJs`、URL 行内选项 `js`/`webJs`、顶层 `searchUrl`/`exploreUrl` 整串、`rule*` 各组内所有字符串字段里的 `<js>` 管道），用 `node --check` 做语法校验（无 node 时退化为括号平衡检查），语法错直接报 **ERROR** 并给出错误类型。交付任何改动前先跑一遍：
    `python3 scripts/validate_booksource.py <你的书源.json>`
  - **易错点**：JS 写在 JSON 字符串值里时，括号/引号一旦不匹配，`node --check` 的报错行号指向的是**展开后的 JS**，不是原 JSON 行——定位时把该字段抽出来单独 `node --check` 最快（见 `js_layer_check.py` 的抽取逻辑）。    `java.connect`/`java.ajax` 这类 Java 互操作代码**务必不要在 `searchUrl` 行内 `js` 字段里硬塞**（v6/v7 连续翻车），改放顶层 `loginCheckJs`（铁律 15/16 已证稳定）。

- **铁律 18：`concurrentRate` 是全局串行限速，分页站点误加会把加载拖成十几秒（真机实测）**
  - **语义**（3.25 反编译 `AnalyzeUrl` 实证）：`concurrentRate` 的值是「**两次请求之间至少间隔 N 毫秒**」，且**跨整本书源全局生效**，不是「每秒并发 N 个」。
  - **坑**：分页目录 / 分页正文 / 发现分页本应**并发**抓取（19 页目录约 1 秒抓完）；但设了 `concurrentRate:"1000"` 后，19 页被**强制串行、每页等 1 秒 ≈ 19 秒**（sk.3qdus.com 真机日志 `0:00:324 → 0:19:320` 坐实）。浏览器秒开是因为它只加载当前 1 页，根本不存在「抓 19 页」。
  - **误用溯源**：把它当「限速防封」随手加在每本书源上 → 所有分页站点都变慢。它**只适合为绕过搜索限流刻意设置**（shumi99 30 秒间隔，填 `"30000"` 或 `"20/60000"`）。
  - **正确姿势**：分页站点（有 `nextTocUrl` / `nextContentUrl` / 发现分页）**不要设** `concurrentRate`，除非明确要限流；限流优先用 `enabledCookieJar:true` + `loginCheckJs`（铁律 16 双清闭环）。`validate_booksource.py` 已新增「`concurrentRate>0` 且存在分页」→ WARN。

- **铁律 19：解析规则 `<js>` 管道的「顶层 return」在 App 上 `invalid return`（真机实证）**
  - **惨案**：sk.3qdus.com 的 `ruleBookInfo.intro` 写成 `<js>\nvar i=src.indexOf('简介：'); ... return src.substring(i);\n</js>`，真机日志 `获取简介 → invalid return`，该字段解析失败/取空。
  - **根因**：App 把解析规则里的 `<js>` 当**顶层脚本**执行（**不在函数体内**），顶层 `return` 非法 → `invalid return`。注意 **`node --check` 抓不到这个错**（Node 脚本模式顶层 return 合法，exit=0），必须靠专门静态检测。
  - **正确姿势**：解析字段（name/intro/content/bookList/chapterList 等）的 `<js>` **优先用纯 XPath**，多数清洗用 `##正则##` 行内替换即可；若必须用 JS，把逻辑包进 **IIFE**：`(function(){ ... return result; })()`（return 在函数体内即合法）。`validate_booksource.py` 已新增：解析规则 `<js>` 出现**非 IIFE 包裹的顶层 return** → WARN（去注释/去字符串后片段里出现 `function`/箭头即视为已有函数上下文跳过——宁松勿紧，个别"函数没包住 return"的写法可能漏报，交付前人工过一眼）。

- **铁律 20：`nextTocUrl` / `nextContentUrl` 取「分页条最后一个链接（尾页）」而非「下一页」→ 跳页丢章（黄金屋 huangjinwu.org 实证）**
  - **现象**：目录翻 1~2 页后，章节数停在某中间值，后面全丢。读者端目录 `(1/298)`，但详情页写 `共998章`——中间章节整段消失。
  - **根因**：翻页规则写成 `.page-link:last-child@href` / `a:last-of-type@href` / 含"尾页"字样的选择器。分页条 `.page-link` 是一组链接：**首页 / 上一页 / 1 / 2 / … / 下一页 / 尾页**；`last-child` 取到的是**整条分页里最后一个链接（尾页）**，不是"下一页"。于是第 1 页→直接跳尾页（如第 10 页）→再翻仍尾页，中间 2~9 页全部跳过。
  - **正确姿势**：纯 JS 按页码确定性递增——先找「下一页」链接（分页条里紧邻"下一页"文字的 href），否则按 `baseUrl` 的 `?page=N` 做 `page+1`；**末页返回空串 `''` 让 Legado 自然停止，防回环**。注意**终止判据必须用"是否还存在下一页"**：部分站越界页（`?page=N` 超出实际页数）被服务端**钳到末页**而非 404，"越界判定"会失效。模板见 `site-patterns.md`「目录/正文分页翻页」+「站点样本：黄金屋」。`validate_booksource.py` 已新增：`nextTocUrl`/`nextContentUrl` 含 `last-child`/`last-of-type`/`尾页` 且无 JS 页码逻辑 → WARN。
  - **铁证**：黄金屋 998 章书修复前只加载 ~298 章（`(1/298)`）、修复后真机目录 `(1/998)` 全加载。

- **铁律 21：Cloudflare 五秒盾可按「端点」触发——只给被墙的入口上 `webView`，别全套 webView（黄金屋实证）**
  - **现象**：同一站点，只有**某一个入口**被 CF 挑战（黄金屋是 `/search` 被拦，直连返回"正在检查您的浏览器"空壳），而首页 / 分类 / 详情 / 目录 / 正文 / `robots.txt` 全部 200 明文直连。
  - **正确姿势**：**逐入口取证**（每个入口各抓一次，登记"明文 / 验证页 / 空壳"），只对 `searchUrl` 内联过盾：`/search?keyword={{key}},{"charset":"utf-8","webView":true,"webWait":12000}`（`webWait` 必须够 CF 放行，默认 ~1000ms 会取空）。**不要**把 `webView` 加进 `chapterUrl` / `bookUrl` / `bookUrlPattern`——每章多等数秒，一本书 3000 章、只有搜索被墙，却是为 1% 的请求付 100% 的代价。详见 `site-patterns.md`「只有部分入口被墙」一节 + 「站点样本：黄金屋」。
  - **纠偏**：搜索恒 0 条时先取证是 CF 盾还是别的；本例早期误判"残留 `checkKeyWord` 会过滤结果→0 条"，但 `checkKeyWord` 仅是「校验书源用的调试关键字」，**不参与真实搜索结果过滤**（3.25 反编译实锤）。0 条的真凶是 `/search` 的 CF 盾，删 `checkKeyWord` 只是清理调试残留、与 0 条无因果——**别把"checkKeyWord 过滤结果"写进任何铁律**。

- **铁律 22：改验证器/桩后必须跑「正向用例 + 反向用例」双跑（回应"每次改技能都有 bug"）**
  - **现象**：写完一个检测/桩，只用"能跑通"的正向样本验证，于是"死条件"（`,\s*{ not in raw` 恒为真）、"桩恒返空串误判正确写法为没弹码"这类 bug 直到真机撞车才暴露。
  - **纪律**：每加一个检测逻辑，立刻写两条用例——"会触发它"的正向用例 + "绕开它"的反向用例（植入故障→确认 FAIL→还原→确认 PASS），两条都过才算数。`run_evals.py` 改完必跑；改 `validate_booksource.py`/`realcheck.py`/`js_layer_check.py` 桩后，`js_layer_check.py --self-test` 也必跑，并保留反向验证记录。
  - **落地**：本轮给 `js_layer_check.py` self-test 增「正确取码写法(java.ajax)」(正例) 与「错误写法(java.get 单参)」(反例) 配对标本（见铁律 23）。

- **铁律 23：校验器自身要有「能区分正误」的自我证伪标本**
  - **现象**：抓 bug 的工具自己有 bug 是最隐蔽的——桩恒返空串会把"正确取码写法"判成"没弹码"，绿灯是假的，真机出事先还以为护栏过了。
  - **纪律**：验证器/桩必须能被证伪。桩要能返回真实的取码/提交 JSON（非恒返空串），且 self-test 同时覆盖"正确写法应通过"与"错误写法应被拦"两组；报告显式分「正例/反例」计数，使"桩能否区分正误"一眼可见。
  - **落地**：`js_layer_check.py` 桩已能按 URL 返回真实 BTWAF 取码/提交 JSON；self-test 现状 10/10（正例 7/7、反例 3/3），其中"错误写法(java.get 单参)"是反向标本——若桩回归成恒返非空或有人把 `java.get` 改成发请求，该例必 FAIL 报警。

- **铁律 24：事实性「是否」断言强制枚举全部重载**
  - **现象**：只看单参 `java.get` 就断言 `get/post/head` 多参"3.25 查无此定义"——证据不全就下了全称否定结论，照写书源会调用一个不存在的方法。
  - **纪律**：判断是否存在的全称命题（"支持/不支持""存在/不存在"）必须枚举**全部重载**并附 dex 描述符，不得凭单次 grep 的部分输出下结论。
  - **落地**：`apk-method-inventory.md` / `legend-js-api.md` 已固化 `AnalyzeUrl` 的 HTTP 方法全量重载真值表（含描述符）；写 `java.xxx()` 前先 grep 真值表，而不是凭印象。

- **铁律 25：改跨文件陈述后必须做「一致性扫描」**
  - **现象**：`pitfalls.md` 同一结论两处打架——"重试 200/400/600/800/1000ms 递增" vs "固定 1000ms"、"cookie 只能事后清理" vs 铁律 16「`js` 字段事前可清」，因分多次补写、没回头统一。
  - **纪律**：改了涉及「节奏/顺序/可否」的陈述（重试节奏、cookie 清理时机、XPath 引擎支持度等），必须用 Grep 扫一遍同类关键词（递增/固定、只能事后/事前可清、变量存取/HTTP 请求），确认无旧主张残留再收工。
  - **落地**：本条目即实例——`pitfalls.md` 的"重试递增 vs 固定 1000ms"矛盾已在上一轮订正，本法固化"改完必扫"；references/maintenance.md「语义部分（脚本抓不到，必须人工过）」清单已显式列入此项。

### 运行时 try/catch 把 JS 异常直接吐到结果栏（App 内调试补刀）

铁律 17 的 `validate_booksource.py` 是**交付前静态拦截**；但真机运行时万一仍抛异常，靠 60s 超时日志很难定位。补一个**运行时**技巧（源自《书源规则：从入门到入土》）——把规则包进 try/catch，异常文本直接 `return "" + e`，会原样出现在解析结果/结果栏里，不用翻日志：

```javascript
(function(result){
  try{
    // 你的处理逻辑
    return result;
  }catch(e){
    return "" + e;   // 异常文本（含行号/类型）直接显示在结果处
  }
})(result);
```

> 适用：`loginCheckJs`、`webJs`、`rule*` 里的 `<js>` 管道都可用。注意 `webJs` 一旦 return 非空 Legado 就当"成功"不再重试——**调试期用、定稿时去掉或改回正确的确定出口**（见铁律 16 极简 webJs 原则）。`java.log(msg)` 打日志也行，但 try/catch 能在结果处直接看到完整异常文本，定位最快。

---

## 🔴 靠 Cookie 限流的站点：用 webJs 事后清理（实战验证）

> 典型站点：搜索成功后下发 `Set-Cookie: <delay_cookie>=1; max-age=30`，30 秒内**只要请求头带这个 cookie** 就返回极短空页。
> 空页常配 `alert("搜索间隔: 30 秒"); window.history.go(-1)`，真机表现是「获取成功但书籍总数 0」+ 弹窗 + 内容为空。

### 判定方法

1. 同一 URL 连续抓两次：**第一次有结果、第二次内容骤降到几十字节** → 就是 cookie 限流。
2. 看响应 `Set-Cookie`：出现一个短 `max-age` 的计时刻 cookie（名字各站不同，如 `ss_search_delay`）。
3. Playwright 对照实验最干净：保留 cookie 连搜 vs 每次 `clear_cookies()` 连搜，若后者稳定 100% 命中即坐实。

### 处置写法（URL 行内选项）

> ⚠️ **v2.0.0 修正（本节 webJs 模板是三层自救版的历史存档，不要照抄）**：现行 webJs 一律用铁律 16 末条的
> **极简四分支**（清 cookie → 锚点命中 return outerHTML → 仍在本站路径才 replace+return null →
> 其余直接 return outerHTML 秒回）。下面的历史模板保留是为了对照理解「节流 replace 曾怎么写」，
> 其 `sessionStorage` 节流分支已删；新书源请直接套极简四分支。

```
"webJs": "(function(){try{var h=document.documentElement?document.documentElement.outerHTML:'';if(h.indexOf('<内容锚点>')>=0){try{document.cookie='<限流cookie名>=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';}catch(e){}return h;}if(location.href.indexOf('<域名>')>=0){try{document.cookie='<限流cookie名>=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';}catch(e){}var n=Date.now(),l=0;try{l=+(sessionStorage.getItem('_lr')||0);}catch(e){}if(n-l>2500){try{sessionStorage.setItem('_lr',''+n);}catch(e){}location.replace(location.href);}}return null;}catch(e){return null;}})()"
```

**事前清（配套，关键）：URL 行内选项再加 `js` 字段**（铁律 16，请求前执行，清 CookieStore 永久条目）：

```
"js": "(function(){try{var u='http://<域名>/';var c=String(cookie.getCookie(u)||'');if(c.indexOf('<限流cookie名>=')>=0){var ps=c.split(';');var kp=[];for(var i=0;i<ps.length;i++){var p=ps[i].replace(/^\\s+|\\s+$/g,'');if(p.length>0&&p.indexOf('<限流cookie名>=')!==0)kp.push(p);}cookie.setCookie(u,kp.join('; '));}}catch(e){}return null;})()"
```

`return null` 表示"不改 URL"（Legado 只在返回非 null 时替换 URL），因此可安全用作纯钩子。Rhino 是 ES5，**不要用 `filter`/`trim`/箭头函数**。

要点：
- **命中锚点就顺手清限流 cookie**（事后清 CookieManager），再配 `js` 字段**事前清 CookieStore**——两层合起来才是完整方案，缺一层都会留下漏洞（见铁律 16）。
- **未命中时的自愈用 `location.replace(location.href)`，不要用 XHR，也不要用 `reload()`**（铁律 14 v2）：`replace` 是全新导航、不带首次 `loadUrl` 的注入头；`reload` 会复用注入头；XHR 撞「403 + JS 自跳转」挑战时拿回的是壳页。
- **判定"是否还在本站"用 `location.href`，不要用限流文案关键词**（铁律 15）。
- ~~`sessionStorage` 节流（2.5s）是必需的~~：**v2.0.0 起已删除**。旧方案用它保证「replace 一次」，代价是每次重试都读写 Storage；现行方案接受 replace 在重试周期里重复触发（上限 31 个周期内必结束，见铁律 16 v2.0.0）。
- 一旦写 `webJs`，**必须显式给等待毫秒**（否则只剩 100ms，见铁律 7）。
- 清 cookie 的 JS 一定要包 `try/catch`：限流页若执行了 `history.go(-1)`，文档可能已失效，`document.cookie` 会抛 `SecurityError`。
- **"未就绪"必须 `return null`，绝不能 `return ''`**——原因见铁律 13，这是本段示例曾真实踩过的雷。
- XHR 重取返回的是字符串，直接 `return t` 即可（Legado 用返回串作响应体），无需 `document.write` 回写 DOM。

### 诚实的边界（别过度承诺）

- 此法是**维持干净状态**为主、**事后补救**为辅。补救只在「页面仍是本站 URL」时有效；**一旦被 `history.go(-1)` 踢到 `about:blank` 就是死局**（铁律 15），本次搜索必然失败，只能等限流窗口过期或用户在 Legado 里清该站 Cookie。
- 交付时**必须如实告诉用户**：首次导入若搜索失败，在书源详情里点一次「清除 Cookie」即可恢复；之后每次搜索成功会自动清理，可连续搜索。
- **不要向用户承诺"完全免疫限流"**。正确表述是「常态连搜稳定，极端污染场景需清一次 Cookie」。
- 站点若把限流 cookie 与挑战混用（删除后触发 403 挑战），`replace` 自愈会让浏览器自动跑完挑战再落地；因此**不需要在 webJs 里手写挑战逻辑**，交给浏览器即可。

---

## 实战铁律（按坑归类，从流程文档剥离）

### 交付形态与转义：用户「改了没生效」的头号真凶

> 🚨 **交付格式铁律（真实翻车：用户"改了没生效"折腾三轮的真凶）**：给用户导入的文件**必须是 JSON 数组** `[{...}]`。
> 开源阅读 3.25 本地导入用 Gson 解析并**要求数组**，交单对象 `{...}` 会弹
> `ImportError: Expected BEGIN_ARRAY but was BEGIN_OBJECT`——但用户经常只顾调试报错、没注意导入弹窗，
> 结果 App 里一直是旧书源，怎么改规则都"不行"。**交付前用 `validate_booksource.py` 过一遍（它会对单对象文件报 ERROR「交付形态」），
> 并提醒用户导入后核对一个字段值（如 searchUrl 是否为新值）确认导入成功**。
> 另外：书源 JSON 里含 `\"` 转义的 JS（正则里的引号）经复制/转存可能被破坏成 `SyntaxError`，
> **loginCheckJs 之类内嵌 JS 要写成零双引号零反斜杠的防御版**（引号用 `String.fromCharCode(34)` 生成，切片用 indexOf）。

### 内嵌 JS 零转义铁律（真机 SyntaxError #N 的根因）

> 🚨 **内嵌 JS「零转义」铁律（真机 `SyntaxError #N` 的根因，翻车两次）**
> 报错形如 `<js>搜索:SyntaxError (Unknown source)#4`，`#4` 是**出错行号**。定位方法：数一下书源里那段 JS 的第 4 行，
> 实战中就是含 `\s` / `\"` 的正则行——JSON 里的 `\\s`、`\\\"` 经过"复制粘贴 / 网盘转存 / 剪贴板导入 / 微信传输"
> 任意一环被还原成 `\s`、`"`，正则字面量提前闭合，Rhino 直接语法错误。**这不是规则写错，是文本在传输中被破坏。**
>
> 因此所有内嵌 JS 必须满足：**单行（无 `\n`）、零双引号（用 `String.fromCharCode(34)`）、零反斜杠（不用正则字面量，用 indexOf/split 切片）、
> 零 `&` 和裸 `>`（避免被 HTML 转义成 `&amp;`/`&gt;`）**。交付前用这条自检：
> `python3 -c "import json;d=json.load(open(f));js=d[0]['loginCheckJs'];print('引号',js.count(chr(34)),'反斜杠',js.count(chr(92)),'换行',js.count(chr(10)))"` → 必须全 0。
>
> 🚨🚨 **根因修正（v5，3.25 反编译实锤）——loginCheckJs 绝对不能带 `<js>` 标签**
> `webBook/x0` 的搜索流程（p 方法，`--show-bad-code` 反编译确认）：
> `analyzeUrl.evalJS(bookSource.getLoginCheckJs(), strResponse)` —— **原串直接进 Rhino，无任何 `<js>`/`@js:` 前缀剥离**；
> `AnalyzeUrl.evalJS` 实现里也没有剥离逻辑。所以 loginCheckJs 以 `<js>` 开头时，Rhino 在第 1 行 `<` 处就报
> `⇒开始解析搜索页 : SyntaxError:<Unknown source>#1`——这正是 v3/v4 内容完整仍报错的根因！
> （早期 `<js>搜索:SyntaxError#4` 则是另一条路：searchUrl 的 `<js>` 前缀由 AnalyzeUrl.initUrl 剥离后才 eval，行号才有意义。）
>
> ⚠️ **body 访问方式（真机 TypeError 实证，v6 定论）**：`result.body` 返回的是 **`body()` 方法对象**（Rhino 中方法名优先于 bean getter，jadx 反编译会漏显这个方法——反编译输出不可全信，真机报错才是铁证），对其调 indexOf 会报
> `TypeError: Cannot find function indexOf in object function body()`。
> **必须写方法调用 `result.body()`**。`result.url()` 同理是方法调用。`cookie.setCookie(url,cookie)`/`java.connect(url)→StrResponse` 均已核实存在。
>
> 参考写法（yndonie 验证页绕过 v6，219 字符，无标签/无双引号/无反斜杠/无换行/无`&`/无`!`）：
> ```
> var b=result.body();var i=b?b.indexOf('encryptedCookieValue'):-1;if(i+1){var p=b.substring(i).split(String.fromCharCode(34));if(p[1]){cookie.setCookie(baseUrl,'is_human='+p[1]);result=java.connect(result.url())}}result;
> ```
> 要点：① **无 `<js>` 标签**；② **`result.body()` 方法调用**（不是属性）；③ `if(i+1)` 代替 `if(i>-1)`、`split(引号)[1]` 代替正则配对；
> ④ 末尾 `result;` 返回新 StrResponse（x0.p 会强转回 StrResponse 当作新响应）；⑤ body 为 null 时安全退出。
>
> 同理，**非 JS 的规则字段也尽量消除 `\s`**：`##^作者[:：]\s*##` 不如直接写 `##作者：`（删除匹配文本），
> 既零转义又更直观。全文件反斜杠数用 `"文件里反斜杠总数"` 自检，理想值 0（header 的字符串化 JSON 除外）。

> 🚨 **交付通道铁律（真机两次翻车：吃转义 → 吃整段代码）**
> 用户手机上拿到书源的路径几乎都是"从聊天窗口复制"。聊天客户端的 Markdown 渲染会**静默吃掉纯文本里的内容**：
> 第一轮吃掉 JSON 转义（`\s`、`\"` 还原成 SyntaxError），第二轮（v3）更狠——把
> `cookie.getKey(baseUrl,'is_human')){` **一整段函数调用直接吞掉**，App 里存的是
> `if(!(cookie.setCookie(...)` 这种坏代码，报 `⇒开始解析搜索页 : SyntaxError:<Unknown source>#1`。
> 因此：**给用户的书源 JSON 必须包在 ``` 代码块里交付**（代码块内不做 Markdown 渲染，文本原样保留），
> 哪怕用户偏好"纯 JSON"。代码块里复制一样方便，纯文本反而会坏。
> 同时让用户导入后在编辑页核对 loginCheckJs 是否与原文一致（数括号/找关键词）。

### 报错阶段速查（3.25 真机实证）

**报错阶段速查（3.25 真机实证）**：

| 报错形态 | 根因 |
|---|---|
| `⇒开始解析搜索页 : SyntaxError:<Unknown source>#1` | **loginCheckJs 带 `<js>` 标签**（3.25 不剥标签，`<` 即语法错，行号恒为 1）——先去掉标签再查其他 |
| `<js>搜索:SyntaxError (Unknown source)#N` | 同上（旧版日志前缀），`#N` 为 JS 内行号，数第 N 行找坏点 |
| `missing ) after argument list` / `Unexpected token 'catch'` | JS **括号不匹配**（v6 在 `searchUrl` 行内 `js` 字段末尾少一个 `}` 导致）——交付前先跑 `validate_booksource.py` 的 JS 语法校验（`_check_js_syntax`）即可拦下；定位时把该字段抽出来单独 `node --check` |
| `TypeError: Cannot find function indexOf in object function body()` | loginCheckJs 里写了 **`result.body`（属性形式）**——必须 `result.body()` 方法调用（Rhino 里方法名优先于 getter） |
| `ImportError: Expected BEGIN_ARRAY...` | 文件是单对象 `{...}`，App 本地导入要求数组 `[{...}]` |
| **无任何报错**，日志显示"列表大小：N"但结果 0 条/全部被丢弃 | **子规则带了前导点**（`.//xxx` / `./xxx`）→ Legado 判为 CSS 模式而非 XPath，静默命中 0 条。去掉点改 `//xxx`（详见上文"XPath 模式判定铁律"） |
| `TocEmptyException: 目录列表为空`（详情/搜索正常） | **目录页 URL 不对**：很多站目录与详情**分两页**——详情页只有最近章节 + "完整目录"按钮，完整目录在 `/{ID}/index.html`。无 tocUrl 规则时 tocUrl=bookUrl(详情页) → 容器永远不存在。用 tocUrl 规则提取按钮链接；CF 站再内联 `,{"webView":true}`（见 `site-patterns.md`「目录双页站」） |
| `ContentEmptyException: 内容为空`（目录正常，正文页获取成功） | ⚠️ **别直接跳到"JS 渲染"结论**——先按**铁律 0**取证：带 cookie / 不带 cookie 各抓一次对比。不带 cookie 就被挖空 ⇒ cookie 问题（`enabledCookieJar` + 先过一次墙），**不是** JS 渲染；直连有明文只是规则没命中 ⇒ 改规则。确认**只有浏览器渲染后 DOM 里才有正文**，才给 `chapterUrl` 内联 `,{"webView":true,"webWait":8000}`（AES/客户端解密站一律 8000ms 起步，3000ms 实测拿空，见 `site-patterns.md`「正文 JS 解密/防采集站」）。判据：源码查看器有明文正文但 XPath 取空 |

### loginCheckJs 写法细则

**loginCheckJs 写法细则（实战沉淀）**：

> ⚠️ **版本指纹提示（与「铁律 3」一致）**：本实战 App（legado 3.25 反编译版）里 `loginCheckJs` **是生效字段**——反编译 `BaseSource$DefaultImpls.putLoginHeader` 证实每次请求后执行、返回值取 `Cookie` 落库、下次请求自动带上（真机 V14 过爪机书屋搜索墙已证）。**本段写法细则对「本 App」有效**。唯需注意：其他 App 构建不一定有这条链路（标准 Legado 仅在「登录检查」对话框手动触发时执行），换 App 请用探针/调试桥实测确认；若该版本不执行它，则过墙真实手段是 `enabledCookieJar:true` + WebView 过墙落库复用，或 `searchUrl` 内联 `<js>` 两步。**先确认自己的 App 版本是否真跑 loginCheckJs，再决定是否依赖它。**

- **能短则短**：`cookie.getKey(baseUrl,'xx')` 的"已有 cookie 就跳过"检查**可以省**——`java.connect` 的返回值不会再过 loginCheckJs，无死循环风险；省掉后 JS 少 40+ 字符、少一个易丢段（v3 就坏在被吃掉的就是这段）。
- 假 cookie 绕不过：yndonie 的验证页实测服务器校验 `is_human` 真伪（`is_human=1` 依然弹验证页），JS 提取真值这条路省不掉。
- 极简参考版（v6，219 字符，**无 `<js>` 标签**、**`result.body()` 方法调用**、零双引号/反斜杠/换行/`&`/`!`）：
  `var b=result.body();var i=b?b.indexOf('encryptedCookieValue'):-1;if(i+1){var p=b.substring(i).split(String.fromCharCode(34));if(p[1]){cookie.setCookie(baseUrl,'is_human='+p[1]);result=java.connect(result.url())}}result;`

### XPath 模式判定铁律

> 🚨🚨 **XPath 模式判定铁律——前导点会让规则静默失效（yndonie v6 真机翻车，必须背下来）**
>
> **症状**：App 调试日志显示"列表大小：49"（bookList 命中了），但**所有书都取不到名字、整列表被丢弃**，
> 且**没有任何报错**。这类"不报错但全空"的坑比 SyntaxError 难查十倍，因为它不会告诉你哪条规则坏了。
>
> **根因（Legado 3.25 反编译，`AnalyzeRule$SourceRule` 构造函数）**：判定规则走哪种解析模式的代码是
> ```java
> if      startsWith(ruleStr, "@CSS:")   -> Mode.Default
> else if startsWith(ruleStr, "@@")      -> Mode.Default
> else if startsWith(ruleStr, "@XPath:") -> Mode.XPath
> else if startsWith(ruleStr, "@Json:")  -> Mode.Json
> else if isJSON || startsWith("$.") || startsWith("$[") -> Mode.Json
> else if startsWith(ruleStr, "/")       -> Mode.XPath     // <== 成为 XPath 的唯一入口
> // 以上都不匹配 -> Mode.Default，按 Jsoup CSS 选择器解析
> ```
> **`startsWith("/")` 是唯一的 XPath 入口**。写 `.//div[...]` 或 `./a/@href`（W3C 标准的相对路径写法）时，
> 开头是 `.` 不是 `/` → 落到 **Default/CSS 模式** → CSS 解析失败 → **命中 0 条，静默丢弃**。
>
> **铁律：列表内的相对 XPath 就写 `//xxx`，不要加点。** 这不是权宜之计：
> Legado 走 `AnalyzeByXPath.getResult()` → `JXNode.sel(xpath)`，而 JsoupXpath 的 `JXNode.sel("//x")`
> **本身就是相对当前节点求值的**——实测同一条 `//div[@class='newnav']/h3/a/text()` 在 49 个 li 节点上
> 各自返回自己那条书名（不是全文档第一个）。那个点纯粹是**画蛇添足**。
>
> 自查清单：全部被 Silent 坑死的三类写法
> | 错误写法 | 后果 | 正确写法 |
> |---|---|---|
> | `.//div[@class='newnav']/h3/a/text()` | CSS 模式 → 空 | `//div[@class='newnav']/h3/a/text()` |
> | `./a/@href`（式如 ruleToc） | CSS 模式 → 空 | `//a/@href` |
> | `/html/body/div/...` 绝对路径 | 列表节点下必然 0 条 | `//div[...]` 相对写法 |
>
> `scripts/test_parse.py` 已内置这条检查（原 `warn_abs_xpath` 的建议**曾经是反的**，教人写 `.//`，已修正为 `warn_xpath_mode`），任何 `.//`/`./` 开头的规则会被标 ❌ 并给出改正后的写法——**生成书源后必跑**。
>
> **单值字段务必显式写 `/text()`**：这是**双安全写法**——
> - Maven `JsoupXpath:2.5.3` 实测：命中**元素节点**时 `JXNode.toString()` 返回的是 **outerHTML**（`<a href="..">书名</a>`），
>   只有 `asString()` 才是纯文本。不写 `/text()` 时，`name` 会带一整串标签脏数据。
> - APK 内置版 `toString()` 字节码为 `return asString();`（纯文本），此时写 `/text()` 结果完全等价。
>
> 即**无论目标 App 是哪种实现，写 `/text()` 都不会更差**，而不写则依赖版本行为。
> 同理，**文本节点**才可能出现 `<JX_TEXT el_depth=..>` 包裹；命中元素节点出现标签串时，补 `/text()` 即可解决。
> `allText()` 也可用（返回节点及其后代全部文本）。

### XPath 语法兼容性铁律（JsoupXpath 引擎短板，真机 XPathSyntaxError）

> 🚨 **症状**：真机弹 `org.seimicrawler.xpath.exception.XPathSyntaxErrorException:
> Please check the syntax of your xpath expr ... NullPointerException:
> Attempt to invoke virtual method 'org.jsoup.select.Elements org.jsoup.nodes.Element.getElementsByTag(java.lang.String)' on a null object`
>
> 而**同一条 XPath 在 Python lxml / 浏览器控制台里是好的**——因为 Legado 用的是 **JsoupXpath（seimicrawler）**，
> 它只实现了 XPath 的一个子集，不支持的语法会直接抛异常（不是静默 0 条，会中止解析并弹错）。

**证据分级（重要：护栏的严厉程度必须匹配证据强度）**：只有真机实证过的才值得当 ERROR 拦；
纯推断的若也报 ERROR，万一条款其实被支持，就会逼用户改掉本来能用的书源——**护栏反而制造 bug**。
`validate_booksource.py` 已按此分级：实证组报 ERROR，推断组只报 WARN（措辞写明"未获真机实证，实测可用可忽略"）。

| 写法 | 后果 | 替代 | 证据 |
|---|---|---|---|
| `//a/text()[last()]` | **XPathSyntaxError**（伪函数 `text()` 带谓词） | 用 `//a/allText()` | **真机实证**（boluomao v1）→ ERROR |
| `//span/following-sibling::a[1]` | **XPathSyntaxError**（不支持兄弟轴） | 纯 JS：从当前标记（如 `class="cur"`）之后用 `indexOf` 找第一个目标链接 | **真机实证**（boluomao v1）→ ERROR |
| `preceding-sibling::` | 疑不支持 | 同上 | 推断 → WARN |
| `parent::` / `ancestor::` | 疑不支持 | 改用父容器 `//div[...]` 自顶向下定位 | 推断 → WARN |
| `child::` / `descendant::` | 疑不支持 | 直接写 `//子标签` / 用 `//` | 推断 → WARN |

> 上面"推断"的三条是从"JsoupXpath 只实现 XPath 子集"推出来的，**没在真机上炸过**。
> 你的书源若用了它们且实测正常，忽略 WARN 即可；哪天真机弹 `XPathSyntaxErrorException`，再按替代方案改，
> 并回来把这一格升级成"真机实证"（顺手把 `validate_booksource.py` 里对应的 `proven` 标记改成 1）。

**实测兼容（可放心用）**：`contains()`、`starts-with()`、`not(contains(...))`、`[1]` 位置谓词、
`//` 相对写法（列表内相对求值）、`//text()`、`allText()`、`@attr`、谓词里的 `.//a[...]`。

**两个衍生坑**：
1. **想绕 `<svg>` 隔断文本别用谓词**：作者名这种 `<a><svg/>周行文</a>` 结构，`text()` 会先取到 svg 前的空白节点。
   正确解是 **`allText()`**（取元素及后代全部文本），不是 `text()[last()]`。
2. **翻页别用 `[1]` 硬取第一个匹配**：`//a[contains(@href,"?p=")][1]` 在**最后一页**会取到"上一页"链接 →
   Legado 往回抓 → **目录/正文重复回环**。改用纯 JS 判"页码必须大于当前页"，或直接读页面脚本里的下一页变量
   （如 `var nextUrl = "..."`；最后一页该变量为空串 → 返回空 → 自然停止）。
   参考实现见 `site-patterns.md`「目录/正文分页翻页」章节的翻页模板 A。

3. **写列表/章节选择器前，先确认页面没有「同名 class 的多个容器」（sk.3qdus.com 真机混入推荐书）**
   - 目录页同时有两个 `class='p2'` 的 `<ul>`——第一个 `div.info_chapters` 是**真章节**（href 指向 `.html` 章节页），第二个 `div.info_tj` 是**推荐阅读**（href 指向书籍详情页）。若用宽泛的 `//ul[@class='p2']/li`，推荐区的书名会被**当成章节**混进目录（每页 20 条、19 页累加 = 大量非本书内容）。
   - **正确姿势**：先用 `//ul[@class='p2']` 这类选择器在**真实 HTML** 上数一数命中了几组、每组是什么，再用更具体的**祖先容器**限定范围（如 `//div[@class='info_chapters']//ul/li`）。`validate_booksource.py` 虽不能直接判断语义，但「章节名不是预期形态（如不以『第X章』开头）」可作为人工复核信号。

### 可选：用 Legado 同款引擎本地复现

#### 可选：用 Legado 同款引擎本地复现（"脚本 OK / 真机不行"时的终审手段）

`test_parse.py` 用 lxml，它的 XPath 语义与 Legado 的 JsoupXpath **不等价**（lxml 里 `.//` 是相对路径的正解，
Legado 里却是致命 bug）。当出现"脚本说 OK、真机却取不到"时，用真引擎复现是唯一靠谱的判据。

**依赖坐标（版本和包名都不能错）**：

| 组件 | 坐标 | 坑 |
|---|---|---|
| JsoupXpath | `cn.wanghaomiao:JsoupXpath:2.5.3` | ⚠️ **仓库 2.5.3 ≠ Legado APK 内置版**：Maven 2.5.3 的 `JXNode.toString()` 会输出 `<JX_TEXT el_depth=..>` 包裹，而 **Legado APK 内置版（反编译实锤）`toString()` = `return asString()` 纯文本**。本地复现时**只信 sel() 命中数，不信 toString 输出**；要精确复现 getString 结果，需从 APK dex 反编译对应类核对 |
| jsoup | `org.jsoup:jsoup:1.17.x` | — |
| antlr4-runtime | `org.antlr:antlr4-runtime:4.7.2` | 4.8 会打版本警告 |
| 其他 | slf4j-api、commons-lang3 | 缺一即 `NoClassDefFoundError` |

Maven 中央仓拉不动时走阿里云镜像：`https://maven.aliyun.com/repository/public/<group/path>/<artifact>/<ver>/<artifact>-<ver>.jar`

**调用方式要与 Legado 源码保持一致**（`AnalyzeByXPath.getResult/getString/getStringList`）：
`JXDocument.create(doc).selN(xpath)` 取列表 → 对每个 JXNode 调 `node.sel(xpath)` 取子字段 →
用 `String.valueOf(node)` 得到 Legado `getString` 的结果（因为 `JXNode.toString()` 字节码就是 `return asString()`）；
列表类字段走 `getStringList`，对应 `node.asString()`。

> ⚠️ **jadx 反编译输出不可全信**（曾漏显 `body()` 方法导致误判 TypeError 根因）。
> **定性 API 行为请以 `javap -c -p <class>` 字节码为准**，反编译只用来定位调用点。
