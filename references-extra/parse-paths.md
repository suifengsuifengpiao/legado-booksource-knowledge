# 解析路径与引擎：语法与书源示例

开源阅读（Legado）3.0 的解析规则背后有**多个引擎**，由规则串里的**前缀 / 首字符**决定走哪一个。搞清楚"这条规则到底被哪个引擎吃"，比背语法更重要——很多书源报错，根因是引擎选错了，而不是规则写错了。

引擎判定（来自 3.25 反编译 `SourceRule`，校验器 `test_parse.py` 的 `detect_mode` 已严格对齐）：

| 规则开头 | 走的引擎 | 备注 |
|---|---|---|
| `/` 或 `@XPath:` | XPath（lxml / JsoupXpath） | 静态 HTML 主力 |
| `@Json:` 或 `$.` / `$[` | JSONPath | 动态站 JSON 接口 |
| `@CSS:` | CSS（Jsoup `select`） | 显式 CSS |
| `@@` | **JSOUP 默认（Jsoup `select`）** | 见下方一节 |
| 无上述标志（如 `.block@ul@li`） | **JSOUP 默认（Jsoup `select`）** | `(@@` 可省略，写不写都一样） |
| `:`（`::` 除外） | **':' 正则模式** | **只用于书籍列表和目录列表**（apk-3.25-verified-facts.md 实锤）；校验器 `test_parse.py` 本地不建模，如实标「需真机验证」 |
| `<js` | JS 注入 | 需真机，校验器不跑 |

> 🚨 **`{{...}}` 内使用规则必须有明显规则标志，没有规则标志会被当作 JS 执行**。
> 例如 `name` 规则写 `{{book.name}}` 没问题（那是变量），但若在 `{{}}` 里写 `//a/text()` 这类**解析规则**，
> 必须带 `@XPath:` 之类的标志，否则 Legado 会把它当 JS 去 `eval`，通常直接报错或取空。
> 凡是"规则在 `{{}}` 里、且不是纯变量运算"的情况，先确认有没有挂规则标志。

## 一、JSOUP 默认规则（`@@`，`@` 链式层级）— 最常被误判的方式

> 这是 Legado **最被低估、也最常被误判**的解析方式。很多书源的搜索 / 目录 / 正文规则其实都是 JSOUP 默认规则，而非 XPath。`.类@标签@属性` 是**完全合法**的 JSOUP 规则。

当规则**没有显式引擎标志**（`@@` 可省略，写不写都是 JSOUP 默认），或以 `@@` 开头时，Legado 走 **Jsoup 引擎**。这类规则用 `@` 作为**层级分隔符**，把整串切成多段，逐段用 Jsoup 收窄到目标节点（对齐反编译 `AnalyzeByJSoup.getElements` + `ElementsSingle.getElementsSingle`）。

**核心语法：`.类@标签@属性` 完全合法**

```
.block@ul@li                   → 先 select(".block")，再在其中 select("ul")，再 select("li")
.info_chapters@ul@li@a        → 逐级收窄到 <a>
[property=og:title]@content   → 选中 og:title 这个 meta，取 content 属性
```

注意：上面的 `.block`、`.info_chapters` **不是 XPath**，`@` **不是 XPath 的轴**，而是 JSOUP 的层级分隔符。把 `.类@标签` 当 XPath 去跑 `//` 会报 `Invalid expression`——那是错误的校验方向，**规则本身没问题**。

**首段前缀（首段按 `.` 拆，首词决定收窄方式）**：

| 首段写法 | 含义（对齐 `ElementsSingle` 的 sparse-switch） |
|---|---|
| `.class` 或 `div.x` 这类 CSS 串 | 整段当 CSS `select`（`.block` → `select(".block")` 合法命中） |
| `class.xxx` | 按类名取（`getElementsByClass`） |
| `tag.li` | 按标签名取（`getElementsByTag`） |
| `id.xxx` | 按 id 取（`Evaluator.Id`） |
| `text.关键字` | 取包含该文本的元素（`getElementsContainingOwnText`） |
| `children` | 直接取子元素 |

**列表倒置前缀 `-`**：`-.info_chapters@ul@li@a` 与 `.info_chapters@ul@li@a` **命中数量相同**（实机均为 20），只是把列表顺序反转。`-` 只影响顺序，不影响命中结果——校验时不要因为加了 `-` 就误判为非法。

**取值指示符（最后一段）**：

| 末段 | 取值 |
|---|---|
| `text` | 元素文本 |
| `html` | 元素内部 HTML |
| `@href` / `@src` / `@content` | 取对应属性 |
| `href` / `src` / `content` 这类裸属性名 | 视为属性名取属性（Legado og 取值标准写法；元素无此属性时回退取文本，避免误空） |
| 不写末段 | 取元素本身（容器规则常用，如 `bookList: .block@ul@li`） |

**`[]` 索引**：某段后可加 `[]` 取第 N 个，如 `ul[0]`。无 `[]` 时整段即选择器。

> ✅ 校验器 `test_parse.py` 已对齐上述 3.25 真机引擎，实机验证：`.block@ul@li` 容器命中 50、`-.info_chapters@ul@li@a` 容器命中 20、`[property=og:title]@content` 命中 1，均为合法 JSOUP 规则，不再报 `Invalid expression`。

> ⚠️ **本地校验器对 JSOUP 规则的已知局限（知悉以免被误导）**：
> 1. **扩展属性选择器 `~=` / `?=` 走真 Jsoup 通道求值**：反编译 `AnalyzeByJSoup.getElementsSingle` 实证，Legado 对 `[attr~=val]` / `[attr?=val]` **不做任何自定义处理**，直接委托 Jsoup 原生引擎（Jsoup 的 `~=` 是正则 OR 构造，如 `[a~=x|y]` ⇒ `\bx|y\b`）。bs4/soupsieve 无法等价建模，故校验器内置**真 Jsoup 求值通道**（`scripts/jsoup_eval/`，jar + `JsoupRuleEval`）忠实复刻真机行为——`[property~=category|status|update_time]@content` 实测返回 `[玄幻, 连载]`，与真机一致。**前提是本机有 Java 且 `jsoup_eval/jsoup-1.17.2.jar` 在位**；若通道不可用，校验器会优雅降级为 **`[需真机验证]`** 而不误报非法。
> 2. **`##$##` 是整串替换（非正则锚点）**：`##$##值` 是把整段结果替换为字面量的 Legado 惯用法（如 `tocUrl` 的 `##$##desc.html`）。校验器已正确实现为整串替换，不会把 `$` 当正则结尾锚点而追加出 `xxxdesc.html` 之类的异常拼接。
> 3. **混合引擎（双向已支持）**：JSOUP 容器挂 XPath 子字段、XPath 容器挂 JSOUP 子字段真机都支持，本地也已**对称**支持两个方向（容器是 XPath/lxml 节点时逐节点转 bs4 再求 JSOUP，反之重建 lxml 子树求 XPath），不会误报 ERR。

## 二、XPath（静态 HTML 主力）

适用于页面源码里直接能看到数据的静态站。

- 列表容器：整文档定位，如 `//div[@class='book-list']/li`
- 列表内子规则（name/author/bookUrl/...）：**必须以 `/` 开头**，写成 `//...`（不带点），
  例如 `//a[@class='name']/text()`、`//img/@src`。
  > 🚨 **想要 XPath 时，绝不要写 `.//...` 或 `./...`**！Legado 只对 `startsWith("/")` 的规则走 XPath 模式，
  > 前导点会被当成 JSOUP / CSS（见上一节），**不报错、静默命中 0 条**。JsoupXpath 的 `JXNode.sel("//x")`
  > 本身就是相对当前列表节点求值的，那个点是多余且有害的。
  >
  > ⚠️ 但注意反例：`.block@ul@li` 这种**本来就是 JSOUP 默认规则**，它**带前导点但完全合法**——
  > 只要你的意图是 JSOUP（用 `@` 分隔层级），前导 `.` 是对的；只有"意图写 XPath 却写成 `.//...`"才是错的。
  > 判定的关键不是"有没有点"，而是"有没有以 `/` 开头 / 是否想用 XPath"。
- 顶层（详情页）规则同样是 `//...`，如 `//div[@class='booknav2']/h1/text()`
- 清洗：规则末尾 `##正则##$1`（替换）或 `##文本`（删除），详见 schema 文档第八节
- 注意：多段文本会返回多条并自动按换行拼接；`text()`/`allText()` 都返回纯文本。

## 三、CSS（静态 HTML 的简洁替代）

写法比 XPath 短，适合简单结构。与 JSOUP 默认模式共享 Jsoup 引擎。

- 取文本：`a.name` 配合 `text()` 语义由 App 处理
- 取属性：`img > @src`
- 列表容器：`div.book-list > li`
- 适用位置同 XPath，可作其替代；复杂嵌套仍推荐 XPath。

## 四、Regex（清洗与提取）

两个用途：

1. **rule 内提取**：在 XPath/CSS 取出的整块文本上二次用正则裁出目标（`##正则##替换`，净化为循环替换）。
2. **ruleContent.content 末尾净化（行内 `##正则##替换##` 或 content 的 `<js>`）**：全局或区域清洗。⚠️ **`ruleContent.replaceRegex` 字段在 3.25 是死字段**（反编译实锤全代码库零消费：写了不执行、静默丢弃，pitfalls.md 铁律 5）——不要依赖它；格式见 `booksource-schema.md` 第八节。这里的 Regex 指 `##` 行内清洗语法（由 `splitSourceRule` 切段解析，四段语义与「不存在 `###`」见 `workflow-detail.md`「## 清洗规则的真实语义」），不是替换规则对象。

示例：`ruleContent` 取出正文块后，在规则末尾用 `##` 把广告语清掉：

```json
"ruleContent": { "content": "//div[@id='article']##<script[\\s\\S]*?</script>|推荐语.*?$" }
```

> 正则中要转义：`\` 在 JSON 字符串里写成 `\\`，`.*?` 非贪婪常用。

## 五、JSONPath（动态站 JSON 接口）

适用于 Vue/React 等动态站：页面源无数据，数据由 XHR 返回 JSON。

- 取数组：`$.data.list[*]`
- 取字段：`$.data.list[*].bookName`
- 取链接：`$.data.list[*].bookUrl`
- 列表容器用 `$.data.list[*]`，子字段相对取值，如 `$.bookName`

示例（动态搜索——注意解析规则在顶层 `ruleSearch` 对象，searchUrl 只放请求）：

```json
"searchUrl": "https://api.example.com/search?q={{key}}",
"ruleSearch": {
  "bookList": "$.data.books[*]",
  "name": "$.bookName",
  "author": "$.author",
  "bookUrl": "$.bookUrl"
}
```

> 动态站关键是先用浏览器自动化抓到真实 API 与返回结构，再写 JSONPath。

## 六、JS 注入（进阶：加密、签名、动态 URL、解密）

当站点对请求参数做了签名、或正文需解密时，用 JS 注入处理。

- 位置：规则的 `js` 段、变量运算（如 `{% ... %}` 或在 `ruleContent`/`ruleWebJs` 中）。
- 典型用途：
  - 生成带 `sign` / `token` 的请求 URL
  - 解密返回的正文（AES/Base64 等）
  - 拼接/重写分片章节链接

示例（在搜索 URL 上注入 JS 生成签名/取验证 cookie——searchUrl 用 `<js>` 包裹）：

```json
"searchUrl": "<js>\nvar kw = String(key);\nvar sign = java.md5Encode(kw + 'secret');\nreturn 'https://api.example.com/search?q=' + encodeURIComponent(kw) + '&sign=' + sign + ',' + JSON.stringify({charset:'UTF-8'});\n</js>",
"ruleSearch": { "bookList": "$.data.books[*]", "name": "$.bookName", "author": "$.author", "bookUrl": "$.bookUrl" }
```

> 🚨 **`<js>` 的返回值必须是「URL`,`{行内选项}`（一个字符串：URL + 英文逗号 + JSON）**，绝不能返回 `JSON.stringify({'url':...})` 整体 JSON 对象——
> 3.25 真机把返回值整体当 URL 字面量去请求，拼出的地址以 `{"url"...` 开头，必然 404（39 书屋实战踩实：本地 lint 只报"请求失败"，真机日志才现形）。
> 行内选项字段表见 `legend-js-api.md`「URL 行内选项」。

> **POST body 里的 `q` 不要预编码**：App 发送请求体时会再做一次 form 编码，JS 里预先 `encodeURIComponent` 会双重编码，服务端查无此书（表现为 `code=0` 但结果数组为空）。URL query 里的 `{{key}}` 由 App 自动编码——用占位符时不要在 JS 里手动编；但 JS 自拼 URL 的另一段 query（如上面的 `'&sign='+sign`）不受此限，按需编。

> 🚨 **Rhino 里没有全局 `md5()`**：签名要用 `java.md5Encode(str)`（3.25 `jsHelp.md` 实证）。写裸 `md5(...)` 直接 `ReferenceError`。

> JS 注入难度最高，但遇到加密/防爬站是唯一突破口；写之前先确认确实是算法在 JS 端完成。

## 选型速查

| 站点特征 | 首选路径 |
|---|---|
| 源码含数据（静态）+ 结构规则 | JSOUP 默认（`.类@标签@属性`）/ XPath / CSS |
| 想要 XPath 但结构里带层级点 | 用 `@` 分隔的 JSOUP，或写 `//` 开头的纯 XPath |
| 数据走 XHR 返回 JSON（动态） | JSONPath |
| 请求需签名 / 正文需解密 | JS 注入 + 上面之一 |
| 正文有广告 / 冗余标签 | content 内联 `##正则##替换##` 或 content 的 `<js>` 过滤（**不要用 `ruleContent.replaceRegex` 字段，3.25 死字段**） |
