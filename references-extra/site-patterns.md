# 站点形态模式库：成套解法

遇到下面某种**站点形态**时，直接套对应的解法模板。通用铁律见 [pitfalls.md](pitfalls.md)，流程与命令见 [workflow-detail.md](workflow-detail.md)。

---

## 墙的几种形态（反爬分类总览）

> 遇到被墙的站，先判清是哪一种墙再选手段。判据只有一条硬标准：**带 cookie 二访（HTTP 客户端即可）能不能直接拿到真内容？**
> - 能 → 壳页挑战，cookie 可复用 → 走 **普通 HTTP + loginCheckJs 重取**（首选，最快最稳）；
> - 不能，必须浏览器执行 JS 才算过 → 硬 JS 挑战 → 走 **webView**。

### 首访 403 壳页（cookie 可复用）—— 书迷楼 shumi99.com 实战（v8 修正结论）

> ⚠️ **v8 复盘修正（重要）**：本技能早期把 shumi99 误判为"JS 挑战每请求必现、cookie 不可复用、只能 webView"，
> 并据此写了 webView 解法（v3-v5）。真机实测推翻：shumi99 的 403 是**首访壳页 + Set-Cookie，二访带 cookie 直接 200**——
> 跳转不需要浏览器执行 JS，HTTP 层 cookie 复用即可过。正确解法是**普通 HTTP + loginCheckJs 重取**，webView 方案反而卡壳页。

**症状**：首访返回 403 + 一段极短 HTML（含 `<script>window.location.href="同一URL"</script>` 跳转脚本）+ `Set-Cookie` 验证 cookie。
**带 cookie 二访直接 200 真内容**——cookie 可跨请求复用，不需要真浏览器跑 JS。

**识别**（与"硬 JS 挑战"区分的唯一标准）：
- 首访 403 + `Set-Cookie` + 极短壳页；
- **带 cookie 二访（curl/HTTP 客户端即可）返回 200 真内容** → 壳页挑战，cookie 可复用 → 走 HTTP + loginCheckJs；
- 若带 cookie 二访仍 403、必须浏览器执行那段 JS 才算过 → 那是硬 JS 挑战（见下节），才走 webView。

**解法：普通 HTTP + loginCheckJs 重取**（v8 真机实证搜索正常，realcheck.py 搜索命中 100 条）：
```json
"searchUrl": "http://www.shumi99.com/search/?searchkey={{key}}",
"enabledCookieJar": true,
"loginCheckJs": "var b=result.body();if(b&&b.indexOf('window.location.href')>-1&&b.indexOf('bookbox')<0){result=java.connect(result.url());}result;"
```
要点：
1. **searchUrl 走普通 HTTP，不加 webView**：Jsoup 拿到壳页 HTML 文本；`loginCheckJs` 在每次请求后执行，检测到壳页（含 `window.location.href` 且无 `bookbox` 内容锚点）就 `java.connect(result.url())` 重取一次，重取带 CookieStore 里的验证 cookie → 直接 200 真内容。
2. **`enabledCookieJar: true` 必开**：否则 403 响应的 `Set-Cookie` 不进 CookieStore，二访不带 cookie → 永远 403。
3. **loginCheckJs 返回必须带 `result`**（修改后的响应对象），且不能带 `<js>` 标签（3.25 不剥标签，Rhino 在 `<` 处语法错）。
4. **判定用内容锚点 `bookbox`**：壳页无 `bookbox`、真内容页有。铁律 12：别用 `window.location.href` 做"挑战页黑名单"（正常页统计代码里也有这串），用内容锚点最稳。
5. **为什么不用 webView**：webView 在 Legado 里拿到的是壳页 HTML，真机不保证执行壳页里的 `window.location.href` 自动跳转 → webJs 只能对着壳页发呆 → 超时/空结果（v3-v5 全栽在这）。这类站用 HTTP 层重取比赌浏览器跳转可靠得多。
6. **搜索参数小写 `searchkey`**：`GET /search/?searchkey=xxx` 才返真结果；写成 `SearchKey`/`POST` 等返回默认推荐列表（与关键词无关，极易误判成"规则命中有问题"）。判据：搜出来的书名必须含关键词。
7. **导入前必过 JS 语法校验**（v8 复盘新增）：loginCheckJs 这类内嵌 JS 一旦缺括号/非法 token，导入即 Rhino `SyntaxError`；交付前跑 `validate_booksource.py`（已内置 `node --check` 全片段校验）拦在交付前。

### 硬 JS 挑战（每请求必现，webView 专用）

**症状**：403 + 极短挑战 HTML，需要浏览器执行 JS（算题/渲染/跑一段挑战脚本）才能完成验证。
**带 cookie 二访（HTTP 客户端）仍 403**——cookie 不通用，每次请求都得真浏览器把 JS 跑一遍。

**识别**：关键判据 **带 cookie 二访仍 403，必须 WebView 执行 JS** → 走 webView。

**解法**：每个会被墙的入口（searchUrl / bookUrl / chapterUrl）URL 末尾都内联 webView 选项：
```json
"searchUrl": "http://站/search/?q={{key}},{\"webView\":true,\"webWait\":3000,\"charset\":\"utf-8\",\"webJs\":\"...\"}"
```
要点：每条 URL 都带 webView；等待字段用 `webWait`（3.25 只认这个，写 `webViewDelayTime` 被静默丢弃）；webJs 未就绪必须 `return null`（铁律 13）。

**与另外几种墙的对比**：

| 墙类型 | 判据 | 过墙手段 | cookie 复用 |
|---|---|---|---|
| Cloudflare | 403 + "Just a moment" 挑战页 | WebView / bypass_cf 拿 cf_clearance | 一套 clearance 跨路径复用 |
| 明文 cookie 自建验证页 | 含 `encryptedCookieValue` | `<js>` 提取真值带 `is_human` 重取（首选 loginCheckJs） | 取一次值复用 |
| **首访 403 壳页**（shumi99） | 403 + 极短壳页 + Set-Cookie；**带 cookie 二访即 200** | **普通 HTTP + loginCheckJs 重取** | **可复用，二访带 cookie 就过** |
| **硬 JS 挑战**（每请求必现） | 403 + 极短挑战页；**带 cookie 二访仍 403，必须浏览器执行 JS** | **每条 URL 内联 webView** | 不可复用，每次都要过 |
| **Cookie 频率限流**（常叠加） | 同一 URL 第二次返回几十字节空页 + `alert("搜索间隔…")` + `history.go(-1)` | webJs 每次成功后清掉限流 cookie | cookie 存在即限流，删掉才放行 |

---

## 目录双页站（详情页 ≠ 目录页）+ webView 内联选项过 CF

#### 目录双页站（详情页 ≠ 目录页）+ `webView` 内联选项过 CF（yndonie v8 实战模式）

**症状**：搜索/详情全部正常（书名作者封面都有值），一到目录就
`获取目录列表 → 列表大小:0 → io.legado.app.exception.TocEmptyException: 目录列表为空`。

**识别**：在详情页 HTML 里搜"完整目录 / 全部章节 / more"之类按钮——很多 CMS（杰奇 17mb 模板等）
详情页只放**最近章节**（`ul.qustime` 之类）+ 一个跳转按钮 `<a href="/{ID}/index.html">完整目录</a>`，
完整目录是独立页面。**没有 tocUrl 规则时 Legado 的 tocUrl=bookUrl（详情页）**，chapterList 在详情页上
永远 0 条——而且**所有书都一样**，不是个别书模板差异。

**解法**：
```json
"ruleBookInfo": {
  "tocUrl": "//a[contains(@class,'more-btn')]/@href##^(.+)$##$1,{\"webView\":true,\"webWait\":5000}"
},
"ruleToc": {
  "chapterList": "//div[@id='allchapter']/ul/li || //div[@class='catalog']/ul/li",
  "chapterName": "//a/text()",
  "chapterUrl": "//a/@href"
}
```

> 🚨 **`tocUrl` 属于 `ruleBookInfo`，不属于 `ruleToc`！**
> 反编译实体类：
> - `io.legado.app.data.entities.rule.TocRule` 字段 = `chapterList` / `chapterName` / `chapterUrl` /
>   `nextTocUrl` / `preUpdateJs` / `formatJs` / `isVolume` / `isVip` / `isPay` / `updateTime` —— **没有 `tocUrl`**。
> - `io.legado.app.data.entities.rule.BookInfoRule` 字段里**有** `tocUrl`。
>
> 写进 `ruleToc` 的 `tocUrl` 会被 Gson **静默丢弃**（不报错、不警告），App 里看 ruleToc 也确实少一个键，
> 于是 `tocUrl` 回退成 `bookUrl`（详情页）→ 目录永远 0 条 → `TocEmptyException`。
> **判据**：调试日志里「获取目录链接」那一行的 URL —— 如果它等于详情页 URL，就是 tocUrl 没生效。
三个关键点：
1. **tocUrl 规则提取按钮链接** + `##^(.+)$##$1,{...}` 在取值后**拼接 URL 内联选项**。
   ⚠️ 正则**必须有捕获组**：写 `^.*` 引用 `$1` 会 `No group 1` 异常（取值直接失败）；要用 `^(.+)$`。
2. **`,{"webView":true,"webWait":5000}` 内联选项**：Legado 的 AnalyzeUrl 用 `\s*,\s*(?=\{)` 切出选项串
   （Gson 严格解析，**必须双引号**），`webView:true` 让 App 用系统 WebView 加载——**能执行 CF 的 JS 挑战**
   （OkHttp 指纹会被挑战，WebView 是真 Chromium；前提是挑战无需人工交互，判据：curl 收到的是
   403+"Just a moment" 挑战页而非纯封锁页）。`webWait` 毫秒为挑战执行留时间，不够就调大。
   WebView 过挑战后 clearance 进 CookieJar（书源需开 CookieJar），**后续章节页 OkHttp 直连即可**。
3. **chapterList 备选 `||`**：`A || B` 在 Legado 里是 XPath 引擎（JsoupXpath）的**节点集并集**——两路都求、
   合并去重（不是"第一路命中就停"的回退）。用来同时兼容新旧模板容器（两容器通常互斥，故并集与回退等价）。
   ⚠️ 本地 lxml 不原生支持 `||`，`test_parse.py` 已用"分别求值再合并去重"模拟，使本地结论与真机对齐。

**验证陷阱**：本地抓样本工具如果"聪明地"抓到了 index.html 来验证目录，
就会得出"目录规则 OK"的假阳性——而 Legado 实际把目录页解析在**详情页 URL** 上。**本地验证必须模拟
Legado 的 URL 决策**（tocUrl 规则 → 空 = bookUrl；有值 = 按钮指向的页面），不能想当然替它选页面。

---

## 正文 JS 解密/防采集站（chapterUrl 内联 webView）

**症状**：搜索/详情/目录全通，正文页「获取成功」但 `解析正文内容 → 空 → ContentEmptyException`；
而 App 调试界面查看正文源码**能看到明文正文**（或用浏览器打开该章节页有正文）。

**根因**：正文不在静态 HTML 的正文容器里——由页面 JS（如 crypto-js AES 解密 + document.write、
异步接口注入）渲染进 DOM。Legado 的 OkHttp 直连拿到的响应里正文容器是空的，XPath 取 0 节点。
源码查看器/浏览器看到的明文是 JS 执行后的结果，**不代表静态响应里有正文**。

**解法**：给 `ruleToc.chapterUrl` 内联 webView 选项——Legado 的 webView 模式在 `onPageFinished`
后执行 `document.documentElement.outerHTML`，**返回 JS 执行后的渲染 DOM**，正文必然在里面：

```json
"ruleToc": {
  "chapterList": "//div[@id='allchapter']/ul/li || //div[@class='catalog']/ul/li",
  "chapterName": "//a/text()",
  "chapterUrl": "//a/@href##^(.+)$##$1,{\"webView\":true,\"webWait\":8000}"
}
```

要点：
1. `##^(.+)$##$1` 捕获组拼接选项的语法与 tocUrl 相同（正则**必须有捕获组**）。
2. **🔴 `webWait` 铁律（实战实锤）**：客户端 AES/crypto-js 解密脚本需要时间，正文页 `div#article` 在解密完成前是**空的**。`webWait` 必须 ≥ 解密耗时，否则无论 XPath 还是 `src` 拿到的都是解密前的空 DOM。**AES 解密站一律给 8000ms 起步**（3000ms 实测拿空）；tocUrl 与 chapterUrl 两个 webView 选项**必须一致给够**，只给一个给够没用。
3. 代价是每章都开一次 WebView（AES 解密站含解密约 8s，非解密的 JS 渲染站约 2~4 秒）——只在 OkHttp 直连确认取不到正文时才用；
   CookieJar 通用（webView 过 CF 后 OkHttp 也能直连），但正文渲染本身绕不开 WebView。
4. 判别"该不该用"：详情页/目录页 OkHttp 能拿到完整数据 + 独独正文空 → 正文是 JS 渲染的 → 用本方案。

---

## 正文规则 JS 兜底管道：xpath<js>...</js>

#### 正文规则 JS 兜底管道：`xpath<js>...</js>`

**症状**：chapterUrl 已加 webView（日志确认 WebView 跑了、获取成功），调试界面查看正文源码
**明明有 `<div id="article">` 和完整明文正文**，但按 `//div[@id='article']//text()` 解析仍是 0 节点。
（真机实测：WebView 3.5s 获取成功 → 解析正文内容 → 空 → `ContentEmptyException`，
而打印出的响应字符串里正文完好。）

**根因**：解析输入的字符串没问题，问题出在 **Jsoup 构建 DOM → XPath 求值**这一层——
页面里存在畸形标签（未闭合 script、非法嵌套 p、select 塞游离文本等），Jsoup 容错修正后
正文容器可能被吞进 script 文本或移位；也可能与 APK 内置 JsoupXpath 的定制行为有关
（反编译证实 APK 内的 JsoupXpath 与 Maven 同版本号**代码不同**，无法本地 1:1 复现）。
**"字符串里有正文"≠"DOM 里有正文"**。

**解法**：利用 Legado 规则的 `<js>` 管道语义——`splitSourceRule` 会把 `<js>...</js>`
切成独立规则，与前面的规则**链式执行**（前一条输出 = JS 里的 `result`），
且 JS 环境里 **`src` 变量 = webView 渲染后的 `document.documentElement.outerHTML`**（`evalJS` 绑定：`scriptBindings.set("src", this.content)`）——它**不是**静态原始 HTTP 响应，而是 JS 执行后的 DOM。
所以 `src` 同样受 `webWait` 钳制：等待不足时，解密前的空 `article` 也会被 `src` 拿到，纯 JS 兜底照样取空。**先保证 webWait 够长，`src` 才有货可提。**
JS 对**渲染后 outerHTML** 做字符串级正则提取，绕过 APK 内置 JsoupXpath 的 DOM 行为差异：

```
//div[@id='article']//text()<js>
var r = result == null ? '' : String(result);
if (r.replace(/\s/g, '').length > 200) {
  r;
} else {
  var h = String(src == null ? '' : src);
  var out = [];
  var re = /<p[^>]*>([\s\S]*?)<\/p>/g;
  var m;
  while ((m = re.exec(h)) !== null) {
    var t = m[1].replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
    if (t.length < 8) continue;
    if (/[<>]|www\.|http|Powered|Copyright|笔趣|转载|最新章节/.test(t)) continue;
    out.push(t);
  }
  out.join('\n');
}
</js>
```

要点：
1. **两段式语义**：XPath 命中（替换后长度 > 200）→ 直接用 XPath 结果，零开销；
   XPath 空 → JS 从 `src` 原始字符串正则提取。两种病因（DOM 被破坏 / 引擎差异）都覆盖。
2. **JS 内禁止出现 `</js>`**（会被提前截断）；`{{` 连写也要避免（splitSourceRule 的
   匹配 pattern 含 `{{...}}` 语法）；正则里的 `\/`、`\s` 合法。
3. **JS 提取必须配合 chapterUrl 的 webView + 足够 webWait**——OkHttp 直连的原始响应里正文本来就是空的，
   只有 WebView 渲染后的 outerHTML 里才有正文；而 outerHTML 何时算"渲染完"由 webWait 决定（见上节铁律）。
4. **🔴 `<a>` 内推荐文本剔除（实锤）**：站点把"类似：xxx 推荐"作为 `div#article` **最后一个含 `<a>` 的 `<p>`**，
   `//div[@id='article']//text()` 会把推荐书名也带出来。首选 XPath `//div[@id='article']//p[not(a)]//text()`
   直接排除整段推荐（JsoupXpath 2.5.3 的 `not(a)` 子轴可用；真机即便内置引擎语法差异导致取空，JS 分支 B 也会兜底）。
   或在 JS 里按行过滤 `类似[:：]`/`www.`/`http`/`沉默的鹦鹉` 等噪声词。
5. 段落过滤黑名单按站点调整：`<p>` 里混推荐链接/版权行（含 `<a>`、域名、Powered 等）要排除。
6. 本地验证方法：**优先用 Rhino 真引擎**（Legado 内置就是 Rhino，阿里云镜像 `org.mozilla:rhino:1.7.14`），
   `Context.evaluateString(scope, js, ...)` 把 JS 原样跑一遍——比"用别的引擎模拟逻辑"可信得多。
7. **兜底也失效时的终审**：若 `xpath<js>` 链式版真机仍取空且**日志无任何 JS 报错**、
   与上一版日志一字不差——首先怀疑**新源没生效**（导入未替换旧源/调试会话未重开/多版本共存），
   其次怀疑链式传递问题。此时改成**纯 `<js>` 单段规则**（前面不挂 XPath，`result` 直接 = 原始 HTML），
   并让 JS **自带诊断**：提取段数 < 3 时返回一行 `【调试】...输入长度=xx 段数=xx` 而非空串。
   三种结局一眼可判：出正文=通；出调试行=JS 在跑但输入不对（长度值会说话）；仍空白=新源没导进去。
   同时提醒用户：**导入新版本前先删干净旧版本**（多版本共名共存时调试可能一直跑旧规则）。

## 同名容器在页面出现多次（真列表藏在后面）

#### 现象

目录页 `//div[@class='catalog']` 命中 **3 个** div：前两个是"同作者推荐"（4 条 + 1 条，URL 形如 `/数字/`），
第三个才是真目录（3085 条，URL 形如 `/数字/数字.html`）。
按第一个容器去取 → 只拿到 4 条推荐书，表现为"目录只有几条"或"目录全是别的书"。

#### 判据

- 容器命中数远小于页面实际条目数
- 命中样例里出现与本目录无关的**其他书名**
- 同 class 的 div 用 `//div[@class='x']` 数出来是 **>1**

#### 解法：按条目特征过滤，不要按容器索引

```json
"chapterList": "//div[@class='catalog']//li/a[contains(@href,'.html')]"
```

- 真目录条目 URL 带 `.html`，推荐位不带 → `contains(@href,'.html')` 一次性滤掉
- **别写 `[3]` 下标**：推荐位数量随书变化（这本 2 个、那本 3 个），下标会错位；特征过滤与位置无关，稳定

#### 通用排查步骤

1. 先数 `//div[@class='x']` 命中几个（>1 就进了这个坑）
2. 逐个打印 `direct a 数 / 含 .html 的 a 数`，找准真容器
3. 同时看章节 `a` 的父级：`li` 就直接写 `//li/a[...]`，别用 `//a[...]`（后者会把容器里的其它链接一并收进来）

## 只有部分入口被墙（精准降级，别全套 webView）

#### 现象

同一站点：**搜索页**返回"访问验证"，而首页 / 详情页 / 目录页 / 正文页直连全部 200 明文。

#### 判据（先逐入口取证，再决定方案）

对每个入口各抓一次（详见 workflow-detail 取证步骤），登记"直连明文 / 验证页 / 空壳"：

| 入口 | 直连结果 | 结论 |
|---|---|---|
| 首页 / 详情 / 目录 / 正文 | 明文 | 保持直连 |
| 搜索 | 验证页 | 只给 searchUrl 上手段 |

#### 解法：只给被墙的那个入口加手段

- 明文 cookie 自建验证页 → `searchUrl` 用 `<js>` 提取 `encryptedCookieValue` 再带 `is_human` 重取
  （写法见 booksource-schema 第十节；比 webView 快一个数量级，且不拖慢其它入口）
- 真 CF / 需渲染 → 只对 `searchUrl` 内联 `,{"webView":true,...}`
  - 实证样例：**黄金屋 huangjinwu.org** 全站只有 `/search` 被 CF 五秒盾拦截，首页/分类/详情/目录/正文均 200 明文 ⇒ 仅 `searchUrl` 内联 `,{"webView":true,"webWait":12000}`，其它入口保持直连（详见文末「站点样本：黄金屋」+ pitfalls 铁律 21）。

#### 为什么不能"全套 webView"

`webView` 每章多等数秒（AES 站 ≥8000ms）。一本书 3000 章、只有搜索被墙，
把 webView 加在 `chapterUrl` 上等于为 1% 的请求付 100% 的代价。**按入口取证，按需上手段。**


## GoEdge WAF 人工图形验证码（loginCheckJs 弹码 + POST 提交）—— boluomao1.com 实战

#### GoEdge WAF 人工图形验证码

**症状**：全站**所有**路径（含 `robots.txt`、`favicon.ico`）都 307 → `/WAF/VERIFY/CAPTCHA?info=...&from=...`，
页面标题 `Verify Yourself`，表单含 `GOEDGE_WAF_CAPTCHA_ID`（hidden）+ `GOEDGE_WAF_CAPTCHA_CODE`（6 位图形码）。

**关键取证（决定能不能做）**：
1. **curl 和 Playwright 真实浏览器都过不去** ⇒ 这不是自动化指纹问题，是真·人工码，别在 header/UA 上反复试错（铁律：硬防护补全 header 无效）。
2. **过一次码后 cookie 可复用**：拿到 `ge_wc_XX=...` 后，**普通 HTTP 带该 cookie 直连就是 200 真内容**，
   且 WAF 按 IP 记忆——同 IP 会放行一段时间（实测沙盒 IP 过一次后不带 cookie 也能直连）。
   ⇒ **结论：这类站走「普通 HTTP + `enabledCookieJar:true` + `loginCheckJs`」即可，不需要 webView。**

**解法模板**（`loginCheckJs`，3.25 每次请求后都执行）：

```javascript
var b=result.body();
if(b&&b.indexOf('GOEDGE_WAF_CAPTCHA_ID')>-1){
  var i=b.indexOf('id="ui-captcha-image"');
  var j=b.indexOf('src="',i);
  var k=b.indexOf('"',j+5);
  var img=b.substring(j+5,k);
  if(img.indexOf('http')!==0){img='https://站点域名'+img;}
  var code=java.getVerificationCode(img);          // 弹窗让用户输入，返回输入的码
  var i2=b.indexOf('name="GOEDGE_WAF_CAPTCHA_ID"');
  var j2=b.indexOf('value="',i2);
  var k2=b.indexOf('"',j2+7);
  var cid=b.substring(j2+7,k2);
  if(code&&cid){
    var body='GOEDGE_WAF_CAPTCHA_ID='+cid+'&GOEDGE_WAF_CAPTCHA_CODE='+code;
    java.post(result.url(),body,{'Content-Type':'application/x-www-form-urlencoded'});
    result=java.connect(result.url());              // 带新 cookie 重取真实内容
  }
}
result;
```

要点：
1. `java.getVerificationCode(imageUrl)` 是官方 API（3.25 `jsHelp.md`），弹窗取用户输入；**图片 URL 必须是绝对地址**（相对路径要补域名）。
2. POST 提交到**验证码页当前 URL**（表单无 action，即提交给自己），body 就两个字段；`java.post(url, body, headerMap)` 是**三参**（`get/head` 才是两参）。
3. `enabledCookieJar:true` 必须开，否则 WAF cookie 不落库、下次又弹码。
4. **UA 必须桌面 Chrome**：实测手机 UA 与 Firefox UA 会被 WAF 直接 403，连验证码页都不给。
5. **兜底**：若真机弹码窗口没正常触发，让用户在手机浏览器打开站点手动过一次码，回 App 即可用一段时间。
6. 判别："是否值得做"取决于**过码后 cookie 能否让普通 HTTP 复用**——能复用就做，纯靠浏览器才能渲染的硬 JS 挑战站才上 webView（见上文"硬 JS 挑战"）。

---

## 宝塔防火墙 BTWAF 人工图形验证码（loginCheckJs 弹码，验证码以 data URI 传入）—— taozitxt.net 实战

#### 宝塔防火墙 BTWAF 人工图形验证码

**症状**：全站路径统一返回约 6KB 的「宝塔防火墙」页（`<title>宝塔防火墙</title>`），页内含
`get_btwaf_captcha_base64` 与 `Verification_auth_btwaf` 两个接口、一个 `<img id="yzm">` 与数英混合图形码（实测 4 位）。

**与 GoEdge 的形态差异（决定写法）**：
- 取码接口 `GET /get_btwaf_captcha_base64?captcha=<毫秒时间戳>` 返回 **JSON `{"msg":"<base64 图片>","status":true}`**，
  **不是图片 URL**；提交接口 `GET /Verification_auth_btwaf?captcha=<码>` 返回 `{"msg":"验证成功","status":true}`。
- 没有"能直接渲染成图片的 URL" ⇒ 必须把 base64 拼成 **data URI** 交给弹码框。
- ⚠️ **MIME 别信站方自己的代码**：WAF 页内联 JS 里写的是 `yzm.src="data:image/png;base64,"+data.msg`，
  但实际返回的 base64 魔数是 **`/9j/`（JPEG）**。站方自己把 MIME 标错了 —— **照它抄 `png` 也不会出错**
  （Glide 的 `DataUrlLoader` 只校验 `startsWith("data:image")` 与 `endsWith(";base64")`，中间 MIME 不敏感，
  它把字节流交给解码器由图片头自行判定），但**写 `jpg` 更贴合实际数据**，排查时也不容易被误导。

**✅ 关键实锤：`java.getVerificationCode` 接受 data URI（3.25 dex 反编译）**
弹码框 `VerificationCodeDialog.i()` 用 **Glide** 加载 `imageUrl`（`com.bumptech.glide.c.F(ctx, imageUrl)`），
而 Glide 内置 `DataUrlLoader`（混淆名 `Lj0/c`），其 `d()` 字节码为：
`startsWith("data:image")` → `indexOf(',')` → `endsWith(";base64")` → `Base64.decode()` → `ByteArrayInputStream`。
⇒ **`java.getVerificationCode("data:image/png;base64,<...>")` 可行**，不必先落地成文件或找图片直链。

**🔴 血泪教训：取码/提交必须用 `java.ajax`，绝不能用 `java.get(url)`（taozitxt 真机实证）**

初版模板误用了 `java.get('.../get_btwaf_captcha_base64?...')`，结果**真机搜索不弹窗、日志 `书籍总数:0`**。
3.25 dex 反编译根因：
```
AnalyzeUrl.get(String)->String 的实现体里只有如下分支：
  "bookName" -> book.getName()
  "title"    -> chapter.getTitle()
  其它        -> chapter.getVariable(key) / ruleData.getVariable(key) / ""
⇒ java.get(单参) 是「取当前书籍/章节变量」，根本不是 HTTP 请求方法！
```
该错误极其隐蔽：**不报错、不抛异常，只是静默返回空串** ⇒ `img` 恒为空 ⇒ 弹码分支永不进入 ⇒ 表现为"没弹窗"。
（技术文档里写的 `java.get(url, headerMap)` 是**两参** JSoup 方法，单参形态被 3.25 重定义成了取变量。）

正确写法：**取码、提交都用 `java.ajax(url)`**（返回响应体字符串）；**重取内容用 `java.connect(result.url())`**（返回 `StrResponse`，`loginCheckJs` 必须回传该类型）。

**解法模板**（`loginCheckJs`，3.25 每次 HTTP 请求返回后都执行）：

```javascript
var b=result.body();
if(b&&b.indexOf('Verification_auth_btwaf')>-1){        // 命中 WAF 拦截页
  var img='';
  try{var o=JSON.parse(java.ajax('http://站点域名/get_btwaf_captcha_base64?captcha='+new Date().getTime()));
      if(o&&o.msg){img='data:image/jpg;base64,'+o.msg;}}catch(e){img='';}
  if(img){
    var code=java.getVerificationCode(img);            // 弹窗取用户输入（传 data URI）
    if(code){
      var cr=java.ajax('http://站点域名/Verification_auth_btwaf?captcha='+encodeURIComponent(code));
      if(cr&&cr.indexOf('"status":true')>-1){
        result=java.connect(result.url());             // 带新 cookie 重取真实内容
      }
    }
  }
}
result;
```

> 图片 MIME 用 `jpg`（该站取码接口返回 JPEG，`/9j/` 头）；如站方返回 PNG 就换 `png`。
> Glide 的 `DataUrlLoader` 只校验 `startsWith("data:image")` 与 `endsWith(";base64")`，中间 MIME 不敏感，但保持一致更稳。


要点（taozitxt 实测 + 反编译）：
1. **弹码框传 data URI**，不是图片 URL（见上方 Glide 实锤）；这是本形态与 GoEdge 最大的写法差异。
2. **取码/提交用 `java.ajax`，不要用单参 `java.get`**（3.25 里单参 `get` 是取变量、不是请求，见上方血泪教训）。
3. **提交码必须匹配"服务端当前记录的那张图"**：Playwright 实测中，若提交前又调了一次取码接口，码会被顶掉 ⇒ `{"验证码错误"}`。
   故模板里**只取一次码、立即提交**，中间不重复请求。
4. **重取内容用 GET 也有效（已实测）**：WAF 页与过码 cookie 走同一会话时，直接 `GET` 搜索/分类 URL 即可拿到真实页面
   （taozitxt 实测：过码后 `GET /search/?searchkey=系统` 返回 60526B、100 个 `bookbox` 卡片）。
   故即使原请求是 POST，`result=java.connect(result.url())` 的 GET 重放也能救回来 —— **无需重放 POST body**。
5. ⚠️ **`java.connect(url, x)` 的第二参是请求头、不是 POST body**：3.25 dex 实证——
   `connect(urlStr)` → `p0.x` → `AnalyzeUrl.getStrResponseAwait`（仅 URL）；
   `connect(urlStr, header)` → `p0.y` → `u0.invokeSuspend`，其中对 `$header` 做 `gson.l(header, Map)` 再传给 AnalyzeUrl 构造。
   ⇒ 传 body 进去会被当 JSON 解析、多半直接抛异常；**要 POST 用三参 `java.post(url, body, headerMap)`**。
   > 同名不同义提醒：`java.get` 也是单参/两参语义完全不同（单参取变量、两参才是 JSoup GET），
   > 别从"connect 第二参是 header"类推到 get 上。完整重载真值表见 `apk-method-inventory.md` 的 `AnalyzeUrl` 节。
6. `enabledCookieJar:true` 必须开；过码后下发**会话级 cookie**（无 Expires）。
7. **⚠️ cookie 可能不能跨客户端复用**：taozitxt 实测把过码 cookie 拿去 curl 仍拿到 WAF 页（认浏览器特征）⇒ 这类站**只能靠 webView 或 loginCheckJs 弹码**，别指望"curl 带 cookie 直连"。
   （与 GoEdge 的差别：GoEdge 那次 cookie 可让普通 HTTP 复用、且 WAF 按 IP 记忆放行；BTWAF 这次不行——**每站都要单独取证**。）
8. **UA 用桌面 Chrome**；手机 UA / 爬虫 UA 同样吃 WAF 页。
9. **验码接口是「两阶段」的（易踩坑）**：WAF 页里 `<img id="yzm">` **初始没有 src**，
   靠页面内联脚本 `showCaptcha()` **异步再请求一次** `/get_btwaf_captcha_base64` 才填充。
   ⇒ 用外部工具（curl/Playwright）取证时，若不等待该异步填充完成，读到的会是**上一次的旧图**，
   与服务器当前记录的码不匹配，无论怎么填都判 `验证码错误`。**等待 `#yzm` 的 src 变成 `data:image...` 后再读**。
10. **兜底**：真机弹码窗口没正常触发时，让用户在手机浏览器打开站点手动过一次码。
11. 判别"是否值得做"：看**过码后能否让书源的后续请求继续走通**——本模板用 `loginCheckJs` 在**每次**被拦时弹码重取，故只要用户肯过一次码即可长期用。

---

## 客户端加密正文/简介（base64+XOR 等纯计算加密，规则 <js> 复现解码，不用 webView）

#### 客户端加密正文/简介：纯 JS 复现站点解码

**症状**：正文页静态 HTML 里正文容器存在但内容为空/是密文串，页面里另有脚本把密文解出来塞回 DOM
（菠萝猫：`p.obf-text[data-obf]` / `span.obf-html[data-obf-html]` 挂 base64 密文，
站内 JS 用 `atob` + 逐字节 `XOR (i%127+1)` + `TextDecoder('utf-8')` 解码）。

**🔴 与「正文 JS 解密站（webView）」的分界（别一律上 webView）**：
- **密文就在静态 HTML 里（挂在某属性/变量上）、解码是纯计算** → **不需要 webView**，在规则的 `<js>` 里复现解码即可，快得多（无每章 8s WebView 开销）。
- 密文要靠 JS 调接口/渲染后才进 DOM → 才走 webView（见上文"正文 JS 解密/防采集站"）。

**取证步骤**：在正文页源码里搜 `decode`/`atob`/`TextDecoder`/`obf` 等关键字，定位 ①解码算法 ②密文挂载属性。

**可复用模板（纯 JS base64+XOR+UTF8，单行、Rhino 兼容）**——
刻意**不用** `java.base64DecodeToByteArray` 等 Java API：其在 Rhino 里的返回类型/自动转换不确定，
纯 JS 实现既可控、又能在本地 node 里原样验证：

```javascript
// 贴进 ruleContent.content 的 <js> 内（B64 表 + 三个函数，ES5，零正则字面量）
var B="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function bd(s){var o=[],b=0,n=0;for(var i=0;i<s.length;i++){var c=B.indexOf(s.charAt(i));
if(c<0)continue;b=(b<<6)|c;n+=6;if(n>=8){n-=8;o.push((b>>n)&255);}}return o;}
function u8(a){var s="",i=0;while(i<a.length){var c=a[i++];
if(c<128)s+=String.fromCharCode(c);
else if(c<224)s+=String.fromCharCode(((c&31)<<6)|(a[i++]&63));
else if(c<240){var d=a[i++],e=a[i++];s+=String.fromCharCode(((c&15)<<12)|((d&63)<<6)|(e&63));}}return s;}
function dec(s){var r=bd(s),o=[];for(var i=0;i<r.length;i++)o.push(r[i]^((i%127)+1));return u8(o);}
```

**用法**：
1. **正文**：XPath 取全部密文属性 → Legado 多结果**自动按换行拼接** → `<js>` 里逐行解码：
   ```
   "//div[contains(@class,\"content\")]//p[contains(@class,\"obf-text\")]/@data-obf<js>…dec函数…
   var NL=String.fromCharCode(10),L=String(result).split(NL),t="",st=0;
   if(L.length>0&&L[0].length>0){var d0=dec(L[0]);if(d0.length<=25)st=1;}   // 首段是章节标题则跳过
   for(var i=st;i<L.length;i++){if(L[i].length>0)t+=dec(L[i])+NL;}
   t;</js>"
   ```
   > 用 `String.fromCharCode(10)` 而**不写 `"\n"`**：避免 JSON 转义在复制/转存中被破坏（零转义铁律）。
   > 首段跳过判据用"解码后长度 ≤ 25"——多数站把章节标题也当作第一段密文（仅第 1 页如此，分页后续页首段是正文，务必按长度判断而不是无脑跳第一段）。
2. **简介**：单个密文直接 `dec(String(result))`。
3. **验证方法（必做）**：把书源 JSON 里该字段的 `<js>` 内容**原样抽出**，在 node 里 `eval` 跑**真实密文**，
   确认解出的是正常中文——不要靠肉眼审代码。

---

## 站内搜索被废弃（搜索框跳外站）——只做发现

**症状**：页面有搜索框，但 `<input readonly onclick="window.open('外部站')">`，
或搜索请求根本不落在站内 ⇒ 抓任何搜索 URL 都拿不到结果。

**处置**：**不要硬编一个假的 `searchUrl`**（会永远"搜索无结果"，用户还以为是规则写错）。
只配 `exploreUrl`（发现频道）+ `ruleExplore`，并在 `bookSourceComment` 里写明"本站无站内搜索，请在发现里找书"。
`validate_booksource.py` 会对缺 `ruleSearch` 报 WARN，属**预期项**，不必消除。

---

## 目录/正文分页翻页（纯 JS 判页码，避免回环）

#### 目录/正文分页翻页

**症状**：`nextTocUrl` / `nextContentUrl` 取不到下一页，或**翻到最后一页后又翻回第 1 页无限循环**
（Legado 会一直追加请求，目录重复、正文重复拼接）。

**为什么不用 XPath**：两个原因叠加——
1. "下一个兄弟节点"要用 `following-sibling::` 轴，**JsoupXpath 不支持**（真机 `XPathSyntaxErrorException`，见 pitfalls「XPath 语法兼容性铁律」）。
2. 退而求其次用 `//a[contains(@href,"?p=")][1]` 取第一个匹配是**错的**：最后一页没有"下一页"按钮时，
   第一个含 `?p=` 的链接往往是**"上一页"** ⇒ Legado 往回抓 ⇒ 回环。

**解法：纯 JS 判页码（且"没有下一页就返回空串"让 Legado 自然停止）。**

**模板 A —— 目录翻页（页码递增型，`?cp=N`）**：从页面里"当前页"标记之后的第一个页码链接里，
取**页码大于当前页**的那个（当前页码从 `baseUrl` 解析）：

```javascript
// nextTocUrl（单行；把 'cp=' 换成站点真实分页参数，'class="cur"' 换成当前页标记）
<js>var h=String(result),u=String(baseUrl),ci=u.indexOf('cp='),cur=1,amp,vs;
if(ci>-1){amp=u.indexOf('&',ci);vs=(amp>-1)?u.substring(ci+3,amp):u.substring(ci+3);cur=parseInt(vs)||1;}
var pos=h.indexOf('class="cur"'),best="",bn=-1;
if(pos>-1){var p2=pos,hi,he,hr,k,v;while(true){hi=h.indexOf('href="',p2);if(hi<0)break;
he=h.indexOf('"',hi+6);hr=h.substring(hi+6,he);
if(hr.indexOf('cp=')>-1){k=hr.indexOf('cp=');amp=hr.indexOf('&',k);
v=parseInt((amp>-1)?hr.substring(k+3,amp):hr.substring(k+3));
if(v>cur&&(bn<0||v<bn)){bn=v;best=hr;}break;}p2=he;}}best;</js>
```

**模板 B —— 正文翻页（页面脚本里已有下一页变量）**：很多站把下一页 URL 直接写在内联脚本里
（菠萝猫：`var nextUrl = "\/read\/112\/7994.html?p=2"`，最后一页为空串 `""`）。直接读变量最稳，
注意 JSON 转义的 `\/` 要还原成 `/`：

```javascript
// nextContentUrl（单行；把 'nextUrl' 换成站点实际变量名）
<js>var h=String(result),i=h.indexOf('nextUrl'),out="";
if(i>-1){var q=h.indexOf('"',i),j=h.indexOf('"',q+1);
if(q>-1&&j>q){out=h.substring(q+1,j);}}
var BS=String.fromCharCode(92),SL=String.fromCharCode(47);
out=out.split(BS+SL).join(SL);out;</js>
```

## 站点侧 JS 签名 / 动态参数（sign、_ts、nonce）—— rrssk 中继搜索实战

#### 站点侧 JS 签名 / 动态参数

**形态识别**：请求 URL 或 POST body 里带 `sign` / `_ts` / `nonce` / `token`，值**不是服务端下发**
（页面静态 HTML 里搜不到该值），而是**页内联 JS 现算**的；常伴随 `__snc`（一次性串）、`_ts`（秒级时间戳）。
典型：搜索框 does not post to itself，而是跳到第三方中继站（本次 74xswz 站内搜索 = 直接 `location.href` 到
`rrssk.com/003Q.html`，由中继站的 JS 算签名后再 POST）。

**❌ 最常见的错误解法：抽取当前密钥常量然后写死。**
本次实证：先按 10-06 当天页面抽出了 4 个常量 `(60825, 27443, 38543, 2166136261)` 并把整套算式抄进搜索 JS，
本地算出的签名与页面一致、真请求 200。**但第二天再看：轮换的不是常量，是整套算法内核**
（累加式 `f=(f*K1+c+K2)>>>0` 被换成了 `FNV-1a + xorshift` 混合式，常量还留着，算式全变）。
⇒ **抽常量 = 必定过期**，用户每天都得找你改。**写之前先问自己一句：这个源三个月后还能用吗？**

**三级路线（按顺序评估，不要直接跳到最累的第 3 级）**：

| 级别 | 做法 | 适用 | 代价 |
|---|---|---|---|
| **L0 先证伪** | 直接发一个签名乱填的请求 | 很多站前端有校验、服务端不校验 | 5 分钟 |
| **L1 eval 官方 JS（首选）** | 拉取页面上的 signJs，**在 Rhino 里 `eval` 它**，调用它自己的签名函数 | 签名逻辑在同一段可取到的 JS 里 | 中 |
| **L2 让浏览器自己算** | `ajax` 选项 `webView:true` + `webJs`，或 `java.startBrowserAwait(url, title)`（**只有两个参数**，dex 实锤） | 依赖 DOM/真实交互才能算出签名 | 高（慢、易半截） |
| **L3 本地复刻算法**（最后手段） | 逆向成纯算式写进 `<js>` | 算法稳定 + 一年半载不变（罕见） | 必然被轮换干掉 |

**L0 —— 先确认服务端到底校不校验。** 本次两大发现：
- 页面 JS 里的 `_ad52ca !== 33`（DOM 指纹，14 项三元累加）与 `_b13bf3 !== 1`（`isTrusted` 真实交互）
  两道闸**只在页面自己算签名时生效，服务端根本不校验**。纯算式算出的签名直接 POST 照样 **200**。
  ⇒ **不要因为看见 `isTrusted` / 指纹检查就断言"Legado 不可能"**（本次第一版就下过这个错误结论，被实测推翻）。
- **`__snc` 是一次性的，`_ts` 必须与签名所用的 `ts` 完全一致**（跨秒即 403）。
  曾把签名时间戳和 POST 时间戳分两次 `Date.now()` 取，导致偶发 403——**同一个变量传给两处**即可。

**L1 —— eval 官方 JS 的写法要点**（这是唯一能扛住"换内核"的写法，因为算法是它自己提供的）：

```javascript
// ① 取回官方 signJs（一次 HTTP）
// ② 剥掉它自己加的两道"只在浏览器成立"的闸，避免 eval 后走不到签名函数
var src = raw
  .replace(/(\w+)\+=([\s\S]*?)\?(\d+):0;/g, function(a,b,c,d){ return b+'+='+d+';'; })
  .replace(/if\s*\(\s*typeof\s+_ad52ca[^)]*\)[^{]*\{[^}]*\}/g, '')
  .replace(/if\s*\(\s*_b13bf3\s*!==\s*1\s*\)[^{]*\{[^}]*\}/g, '');
// ③ 伪造最小 window/document，收集 addEventListener 注册的 handler
var handlers = [];
var window = { addEventListener: function(n,h,o){ handlers.push(h); } };
var document = {};
eval(src);
for (var i=0;i<handlers.length;i++){ try { handlers[i]({isTrusted:true}); } catch(x){} }
// ④ 从 window 上捡回签名函数（不要写死函数名的下标，按形取）
var f = window['__SIGN'] && typeof window['__SIGN'].f === 'function' ? window['__SIGN'].f : null;
// ⑤ ts 只取一次，签名和 POST 共用
var ts = Math.floor(Date.now()/1000);
var sg = String(f(encodeURIComponent(key), t, ts));
```

> 关键取舍：**eval 第三方脚本有风险**（它能在 Rhino 里调 `java.*`）。若介意，退到 L2。
> 其次：定位签名函数**不要写死数组下标**（`handlers[3]`），按"有 `f` 属性且是函数"去捡，站方改脚本顺序也不炸。

**L2 —— 让目标站自己的浏览器去算**（本次**未真机验证**，但从 3.25 API 看可行，遇到每天换内核的站优先试这条）：
`ajax` 选项支持 `webView` `webJs` `webWait`，`JsExtensions` 另有 `startBrowserAwait(url, title)`（dex 描述符
`(Ljava/lang/String;Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;` —— **两参，别照旧文档写第三个 `false`**）。
思路是让内置 WebView 加载中继页 `003Q.html`，页面自己算出并提交签名，`webJs` 只负责**把结果页 HTML 捞回来**
（务必 `return null` 表达未就绪，见铁律 13）。好处：算法每天换也无所谓，换的是它自己的浏览器。
代价：每搜一次开一次浏览器（慢）、半截页面风险、`about:blank` 死局（见 SKILL.md 的 webView 节）。

**本地怎么验证这类源（不受真站限流干扰）**：
1. **真 Rhino 跑一遍**：`js_layer_check.py` 用的是 Node V8，**不是 Rhino**，验证签名类 JS 不够看。
   下载 `rhino-1.7.14.jar`，用 `java -cp rhino-1.7.14.jar org.mozilla.javascript.tools.shell.Main x.js` 跑。
   两个 Rhino 独有的坑：① **全局 `java` 是 JavaPackage，`var java = {...}` 覆盖不了**，要写成
   `new Function('java','cache','key','page', src)` 参数注入；② `new Function` 不自动返回末条表达式，
   得写成 `'return (' + src + ');'`。另外本机 `/usr/bin/js` 多半被 Node 抢占，别指望系统 rhino 命令。
2. **mock 回放**：把一次真实抓到的 `relay.html` / `signjs.js` / `post_out.html` 存成 fixture，
   harness 里按 URL 回放。真站高频请求会被 IP 限流（本次表现为"同一组值 requests 200 / curl 403"，
   根因其实是 `__snc` 被前一次请求消耗了，不是 curl 参数问题）——**别用反复打真站来验证逻辑**。
   mock 路由注意：先按 `,{` 剥掉 ajax 的第二个参数再判断 URL，否则 Referer 里恰好含目标文件名会误命中。

要点：
1. **最后一页返回空串**是停止信号（Legado 见空即停）——模板 B 天然满足（变量为空），模板 A 靠 `v>cur` 判据返回空。
2. 用 `String.fromCharCode(92/47)` 处理反斜杠，**不要在 JS 里写字面 `\/`**（JSON 转存易被破坏，见"零转义铁律"）。
3. **验证方法**：把 `<js>` 内容原样抽出，在 node 里喂**真实页面 HTML** 跑 4 组——
   第 1 页 / 中间页 / **最后一页**（必须返回空）/ 不同书籍，确认既不漏页也不回环。
   菠萝猫实测：目录 `cp=1→2`、`cp=2→3`；正文 `p=1→2`、第 5 页（末页）→ 空。

---

## 站点样本：3Q中文网 (sk.3qdus.com) —— 手机 UA + 分页目录 + GBK

> 适用：制作该站书源时直接套用。无搜索（站长已关搜索功能），靠发现页 9 频道 + 详情页取书。整套规律由 sk.3qdus.com 真机实测固化。

**关键形态（全部真机实证）**：

1. **仅手机 UA 返回正文**：网站按 UA 区分，只给 **手机 UA** 发正文，桌面 UA 一律回占位符「本章未完 点击下一页继续阅读」/「本章已完」。`header` 必须带手机 UA（见下）。
2. **`header` 必须 JSON 格式**：`{"User-Agent":"<手机UA>","Referer":"https://sk.3qdus.com/"}`。行格式 `User-Agent: xxx` 会被 App 整段丢弃并回落默认桌面 UA（反编译 `BookSource.getHeaderMap` 实锤只认 JSON）。
3. **字符集 GBK**：通过 HTTP 头 `charset=gbk` 下发，本地 curl 按 GBK 解码即可；书源顶层无 charset 字段（写了也被 Gson 静默丢弃）。
4. **目录是分页目录**：每页约 50 章、全书可达 19 页，靠 `nextTocUrl` 翻页。**务必并发抓取**——别加 `concurrentRate`（全局串行限速会把 19 页拖成 ~19 秒）。
5. **同名 class 容器要限定范围**：目录页有两个 `ul.p2`——`div.info_chapters`（真章节，href 是 `.html` 章节页）与 `div.info_tj`（推荐阅读，href 是书籍详情页）。`chapterList` 必须写 `//div[@class='info_chapters']//ul/li`，否则推荐书名会混进目录。
6. **正文分页尾要清洗**：正文页 `div#novelcontent` 末尾带「本章未完…」/「本章已完」分页尾标识，`content` 规则用 `##(本章未完[^<]{0,60}|本章已完)##` 清掉；正文分页靠 `nextContentUrl`（`//a[@class='p4' and contains(.,'下一页')]/@href`）拼接。
7. **详情页简介位置**：`div.jj` 内、`<p class="p2">书名简介：</p>` 之后的**内层 `<p>`（无 class）** 才是正文，`ruleBookInfo.intro` 用纯 XPath `//div[@class='jj']/p[2]/text()`。**不要用 `<js>` 写 intro**（App 解析规则 `<js>` 不支持顶层 return，会 `invalid return`）。

**疑似 App 版本边界**：3.25 反编译版实测 `following-sibling::` 轴会抛 `XPathSyntaxErrorException`，故全程用纯 XPath / `//div[...]` 自顶向下定位，不碰兄弟轴。

## 站点样本：黄金屋 (huangjinwu.org) —— Cloudflare 按「端点」盾 + 目录 ?page=N 分页（越界钳末页）

> 适用：制作该站书源时直接套用。整套规律由 huangjinwu.org 真机实测固化：搜索被 CF 五秒盾按端点拦截、目录 `?page=N` 分页每页 100 章且越界页被钳到末页。

**关键形态（全部真机实证）**：

1. **仅 `/search` 被 Cloudflare 五秒盾拦截**：`/search?keyword=X` 直连返回"正在检查您的浏览器"空壳（列表 0 条）；首页 / 分类 `/list/N/{{page}}.html` / 标签 `/tag/N/{{page}}.html` / 排行 `/rank/N/{{page}}.html` / 详情 / 目录 / 正文 / `robots.txt` 全部 200 明文。**这是"按端点触发"的典型**——只对 `searchUrl` 内联过盾，别株连其它入口：
   `/search?keyword={{key}},{"charset":"utf-8","webView":true,"webWait":12000}`（`webWait` 必须够 CF 放行，默认 ~1000ms 会取空）。
2. **`checkKeyWord` 只是调试关键字，不过滤结果（纠偏）**：`ruleSearch.checkKeyWord` 是「校验书源用的测试关键字（调试用）」，3.25 反编译实锤其**不参与真实搜索结果过滤**。本站搜索恒 0 条的真凶是 `/search` 的 CF 盾，删 `checkKeyWord` 仅清理调试残留、与 0 条无因果。**别把"checkKeyWord 会过滤结果"写进铁律**。
3. **目录 `?page=N` 分页，每页 100 章**：本书 998 章 = 10 页。注意**越界页（如 `?page=6` 超出实际 5 页）被服务端钳到末页**而非 404 ⇒ 翻页"是否越界"不能作为终止判据，必须以"页面上是否还存在下一页链接"为准。
4. **`nextTocUrl` 反模式：取「分页条最后一个链接（尾页）」**：原 `nextTocUrl: ".page-link:last-child@href"` 取到的是分页条里最后一个链接（尾页），翻 1~2 页后直接跳尾页、中间章节全丢（998 章书只拿到 ~298 章，读者目录 `(1/298)`）。正解纯 JS 按页码确定性递增——「下一页」链接优先，否则 `page+1`，末页返回空串自然停止防回环：
   ```javascript
   // nextTocUrl（@js:；把 'page=' 换成站点真实分页参数）
   @js:(function(){
     var h=''+result, u=''+baseUrl, out='';
     var mm=h.match(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(?:(?!<\/a>)[\s\S]){0,80}?下一页/);
     if(mm&&mm[1]){ out=mm[1]; }
     else {
       var cur=1,max=0,has=false,pm=u.match(/[?&]page=(\d+)/);
       if(pm){ cur=parseInt(pm[1],10)||1; has=true; }
       var nr=/[?&]page=(\d+)/g,v;
       while((v=nr.exec(h))){ var n=parseInt(v[1],10); if(n>max){max=n;} }
       var nx=cur+1;
       if(max>=nx){ out=has ? u.replace(/([?&]page=)\d+/,'$1'+nx)
                             : (u+(u.indexOf('?')>-1?'&':'?')+'page='+nx); }
     }
     return out;
   })()
   ```
5. **详情走 `og:` meta**：`og:novel:book_name` / `og:novel:author` / `og:image` / `og:description` / `og:novel:category` + `og:novel:status` + `og:novel:tags`（kind 多行拼接）/ `og:novel:latest_chapter_name`。
6. **搜索/发现卡片走 `.book-card` 系列**：`bookList=.book-card`；`name=.book-title@text`；`author=.book-author@text##^[\w ]{2}：`；`coverUrl=img@src`；`intro=.book-desc@text`；`kind=.book-badge@text`。
7. **正文 `#readerContent@text` 单页正文，跨页靠 `nextContentUrl: a:matches(下一页)@href` 拼接**；本站对桌面/手机 UA 未做区分（不像 3Q中文网只给手机 UA），桌面 UA 即正常。
8. **`header` 必须 JSON 格式**：`{"User-Agent":"<桌面Chrome>","Referer":"https://www.huangjinwu.org/"}`；行格式会被 App 整段丢弃回落默认 UA。

**铁证对照**：修复前读者目录 `(1/298)`、详情 `共998章`；修复后真机目录 `(1/998)` 全加载；`validate_booksource.py` 对该源 ERROR=0。
