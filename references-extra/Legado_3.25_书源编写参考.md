# Legado 3.25 书源编写参考（自官方 APK 逆向提取）

> 来源：`legado_app_3.25.apk`（18.8 MB，4 个 dex，包名 `io.legado.app`）
> 提取方式：androguard 解析 dex，读取类方法签名与字节码常量
> 提取时间：2026-10-06

**为什么这份比网上流传的教程可靠**：所有内容直接来自你真机安装的这个版本的字节码，不是文档传抄、也不是对 GitHub 源码的猜测。

**已证实/修正的既有认知**

| 既有认知 | APK 实际情况 |
|---|---|
| 发现页无法分组 | ✅ 证实。`ExploreKind` 只有 `title` / `url` / `style` 三个属性，没有 group 字段 |
| `java` 对象只有 `ajax`、`getCookie` | ❌ **严重低估**，实际 **107 个公开方法** |
| ajax 只支持 method/body/headers | ❌ 实际 **12 个选项** |
| Legado 用 rhino | ✅ 证实（APK 内含 `org/mozilla/javascript/*`，且封装为 `com.script.rhino.*`） |

---

## 1. `java.xxx` 全表（JsExtensions，107 个公开方法）

### 1.1 网络请求

| 方法 | 说明 |
|---|---|
| `ajax(url或url,{json})` | 常用。返回响应体字符串 |
| `ajaxAll(url数组)` | 并发请求多个，返回 `StrResponse[]` |
| `connect(url)` / `connect(url, method)` | 返回 `StrResponse` 对象（含头信息） |
| `get(url, Map)` | jsoup `Connection.Response` |
| `post(url, body, Map)` | 同上 |
| `head(url, Map)` | 同上 |
| `downloadFile(url[, 目标路径])` | 下载到本地并返回路径 |
| `cacheFile(url[, 秒数])` | 缓存远程文件到本地并返回路径 |
| `getCookie(url[, 名称])` | 取 Cookie |
| `toURL(url[, baseUrl])` | 返回 `JsURL` 对象，可做 URL 拆解 |

### 1.2 编码 / 加密 / 摘要

| 方法 | 说明 |
|---|---|
| `base64Encode(s[, flags])` / `base64Decode(s[, flags])` | 另有 `ToByteArray` 版本 |
| `md5Encode(s)` / `md5Encode16(s)` | 32 位 / 16 位 |
| `hexEncodeToString` / `hexDecodeToString` / `hexDecodeToByteArray` | 十六进制 |
| `aesEncodeToBase64String(data, key, transformation, iv)` | 本 74xswz 书源在用，`transformation` 填 `AES/CBC/PKCS5Padding` |
| `aesEncodeToString` / `aesDecodeToString` / `aesEncodeToByteArray` / `aesDecodeToByteArray` | 非 base64 版本 |
| `aesEncodeArgsBase64Str` / `aesDecodeArgsBase64Str` | 参数式重载 |
| `desEncodeToString` / `desEncodeToBase64String` / `desBase64DecodeToString` / `desDecodeToString` | DES |
| `tripleDESEncodeBase64Str` / `tripleDESEncodeArgsBase64Str` / `tripleDESDecodeStr` / `tripleDESDecodeArgsBase64Str` | 3DES |
| `HMacBase64(data, key, alg)` / `HMacHex(data, key, alg)` | HMAC |
| `digestHex(data, alg)` / `digestBase64Str(data, alg)` | 摘要，alg 如 MD5/SHA1/SHA256 |
| `createSymmetricCrypto(alg, key, iv)` | 返回 hutool `SymmetricCrypto` 对象，可反复加解密 |
| `createAsymmetricCrypto(alg)` | 非对称加密对象 |
| `createSign(alg)` | 签名对象 |
| `randomUUID()` / `androidId()` |  |

### 1.3 文件 / 压缩包

| 方法 | 说明 |
|---|---|
| `getFile(path)` → `File` | |
| `readFile(path)` → `byte[]` | |
| `readTxtFile(path[, charset])` | |
| `deleteFile(path)` → boolean | |
| `getTxtInFolder(path)` | 读取文件夹下所有 txt |
| `unzipFile` / `un7zFile` / `unrarFile` / `unArchiveFile(path)` | 解压到本地并返回路径 |
| `getZipStringContent(path, 内部文件名[, charset])` | **直接读压缩包内某文件内容**，不必先解压 |
| `getZipByteArrayContent` / `get7zStringContent` / `getRarStringContent` 等 | 同上，支持 zip / 7z / rar |
| `strToBytes(s[, charset])` / `bytesToStr(bytes[, charset])` | |
| `utf8ToGbk(s)` | 老站点乱码救星 |

### 1.4 浏览器渲染（反爬大杀器）

| 方法 | 说明 |
|---|---|
| `webView(url, ...)` → String | 用内置 WebView 真正渲染页面并返回源码 |
| `webViewGetSource(url, ...)` | 取渲染后源码 |
| `webViewGetOverrideUrl(...)` | 拦截跳转 URL |
| `startBrowser(url, title)` / `startBrowserAwait(url, title)` → `StrResponse` | 打开可见浏览器，等待用户操作后回收结果（适合过手动验证码 / 登录） |
| `getWebViewUA()` | 拿真实 WebView 的 UA，比手写 UA 真实 |

> 对付 JS 加密签名的站点，`webView` 让浏览器自己去算，天然省掉逆向。

### 1.5 字体反爬

| 方法 | 说明 |
|---|---|
| `queryTTF(obj[, boolean])` → `QueryTTF` | 从字体文件/URL 解析字形映射 |
| `queryBase64TTF(base64)` → `QueryTTF` | |
| `replaceFont(内容, QueryTTF, QueryTTF[, boolean])` | 把混淆字形替换回真字符 |

官方通道（3.25）：

```javascript
var f1 = java.queryBase64TTF(b64[1]);
var f2 = java.queryTTF("https://.../Source Han Sans CN Regular.ttf");
return java.replaceFont(result, f1, f2, true);
```

#### 1.5.1 能力边界（2026-11-13 勘误版 · 整篇替换 11-12 初版）

> **⚠️ 勘误说明**：11-12 初版据该站「会话级动态字形」推出「规则层无法还原正文 / 目录名仍不可救」，已于 2026-11-13 由**四条独立通道复算证伪**（见下「实站取证」）。根因是错归因：只验了字形轮廓**渲染层**、没验字符置换**关系层**，再把 `QueryTTF` 三条限制越界外推成业务结论。**「规则层无解」从来不是官方结论**——官方 §1.5 只定义 `queryTTF` / `queryBase64TTF` / `replaceFont` 三个字体 API（`official-help/ruleHelp.md:180-182`），无任何条文禁止规则层做字符串置换解码。勘误文档全文见 `cases/字体站型勘误留痕_20261113/字体反爬站型与3.25规则层能力边界.md`。
> **证据等级（如实）**：站型判据与 `QueryTTF` 实现边界为 **L1**（3.25 `classes*.dex` 反编译本体 + 抽取 `QueryTTF.java` + fontTools 独立复算）；「有限 16 套固定置换表可解码」为**书源侧本地实站夹具 L1**（四条独立通道互证），**字体样本与复算脚本未随包、真机 App 导入即用未验**，引擎侧**未独立复现**，不写「已修复」。`classify_font_obfuscation` 是启发式：只识别站型、不等于证明加密、更不等于判定规则层能力。合成 cmap 独立复算见 `cases/标本_字体恒等cmap站型判非加密字体_假阴性.md`。

**站型只描述字体文件长什么样，不决定规则层能否还原正文/目录**——两件事必须分开判：

| | 站型 A · 私有区码位重定向 | 站型 B · CJK 恒等 cmap + 字形轮廓替换 |
|---|---|---|
| cmap 特征 | 含 `U+E000~F8FF` 或 `≥U+F0000` 私有区码位 | **无私有区**；码位集中 CJK 基本区，字形名 `uniXXXX` 与码位恒等自洽 |
| 混淆发生在 | cmap 映射（码位 → 字形） | `glyf` 轮廓重绘 / 重排（码位本身没变） |
| 抓到的正文 | 私有区乱码字符 | 正常汉字字形，但字形与 Unicode 不对应 |
| 字体 API 通道 | 可反推 `replaceFont` / `replaceRegex` | **不适用**（见下三条限制） |
| 规则层能否还原 | 通常能 | **未判定，与站型无关**（见「实站取证」「操作顺序」） |
| `reverse_font.py` 判定 | `pua_codepoint_redirect` / `rule_layer_recoverable=True` | `glyph_shape_cjk_identity` / `rule_layer_recoverable=None`（v1.15.25 起） |

只认站型 A 的诊断会把站型 B 报成「可能非加密字体」（假阴性），这是 v1.15.24 工具侧修复的起因；而把站型 B 直接判成「规则层无法还原 / 目录名仍不可救」是**从字体形态越界推断业务结论**，已在 v1.15.25 更正。

**`QueryTTF` 的实现边界（3.25 反编译本体，三条互相独立）**：

1. **格式**：构造函数按手写 TTF 表目录解析（`sfntVersion` / `numTables` / `cmap` / `loca` / `maxp` / `glyf`），**没有 woff2 解码分支**。dex 字符串池里的 `font/woff2` / `woff2` 位于 MIME / 邻近字符串，不是 `QueryTTF` 的解码路径；站点只发 `wOF2` 时须先由外部转成标准 TTF（`\x00\x01\x00\x00`）才可能进这条通道。
2. **匹配口径**：`getGlyfById()` 把简单字形轮廓序列化成 `x,y|x,y` 坐标串；`glyphToUnicode` 是**精确 HashMap 匹配**（`glyphString → codepoint`），无容差、无相似度阈值。`replaceFont` 依赖「混淆字体的轮廓串」能在「正确字体」里找到**完全相等**的键；轮廓一旦重绘、重排或量化即失配。
3. **字形集合可随会话变**：字形集合可锚在会话级 guard cookie（如 `reader_guard_id`）上，每次会话下发不同字库；跨会话轮廓集合变化。

> **这三条只封闭 `java.queryTTF` + `java.replaceFont` 这条字体 API 通道，不封闭规则层的纯字符串置换解码通道**——后者只处理响应体里的字符串，不解析字体、不调用任何字体 API。三条成立时的结论是「别在这条通道上继续调 XPath / 换字体 API / 截正则」，**不是**「规则层无解」。本结论**只针对用户 3.25 反编译**，不外推其它构建；对照用的 `Noto Sans CJK` 为 CFF/OTTO（无 `glyf` 表），与 `QueryTTF` 口径不同源，相关对照标「未实测/受限」。

**实站取证（`www.aaawz.cc`）：有限 16 套固定字符置换表**。11-12 初版在此处下「规则层无解 / 目录名仍不可救」结论，已证伪。四份 woff2 的渲染层现象（6763 条 CJK 恒等 cmap、跨会话轮廓精确交集 1.18%、家族名随机）都是真的，但**字体文件的形态 ≠ 字符置换关系**：站点实际从**有限 16 套固定字符置换表**轮换下发，`font.url` 文件名前 12 位即表号，每表长 6763、`AA_CODES` 的完全双射、两两不同；规则层 `jsLib` 内置 `AA_CODES` 与 16 张 `AA_TABLES`，`aaDecode(font.url, 文本)` 逐字查表即可**同时还原正文与目录名**（`ruleContent.content` 与 `ruleToc.chapterList` 均调它），这条通道**完全不经过字体 API**。四条独立通道复算（书源侧本地实站夹具 L1、样本未随包）：A 换语言 Python 重写解码（16 表全双射、历史 5/5 字体 key 命中、1496 条目录全量解码失败 0、乱码正文解成《十日终焉》开篇）/ B Node 跑他方原始 `jsLib` 的 `aaDecode` 本体（与 A 一致）/ C1 Node 端到端跑 `ruleContent.content`（通顺正文）/ C2 Node 端到端跑 `ruleToc.chapterList`（1496 条全解出、`[0] 第1章 空屋`、`[1495] 陈俊南（终）`、残留乱码 0）。**16 套表覆盖性未证**（本地仅 5 个 key 全命中），`aaDecode` 对无表 key 原样返回乱码自带降级兜底。

**写书源时的操作顺序（勘误后）**：

1. 遇到「乱码 / 看不懂的汉字」→ 先取字体文件，跑 `reverse_font.py <字体文件>` 看 `obfuscation_type`；
2. `pua_codepoint_redirect`（站型 A）→ 走本节既有 `replaceFont` / `replaceRegex` 通道；
3. `glyph_shape_cjk_identity`（站型 B）→ **不要在字体 API 通道上继续调 XPath、换字体 API 或截正则**；但**不要据此写「规则层无法还原」或放弃目录**，转第 4 步；
4. **另查字符置换通道**（关键，11-12 初版缺的就是它），三条任一成立即可在规则层还原、**包含目录名**：① 正文/目录乱码是否来自有限套固定置换表；② 表是否随响应下发或可按 `font.url` 前若干位（实站 12 位）索引到表号；③ 是否能在 `jsLib` 内置表并由 `<js>` 规则对 `ruleContent` / `ruleToc.chapterList` 逐字查表解码；
5. 查不到置换表、也没有其它字符串映射线索时，才写「本规则层无法还原」并转浏览器阅读 / 换源——**且必须写明是「此站此通道取证后」的结论，不是站型推论**；
6. 单份字体只能判站型；要判「会话动态」须取多份同站字体按 `cases/标本_字体恒等cmap站型判非加密字体_假阴性.md` 的 fontTools 片段复算轮廓集合。
7. 凡书源含 `<js>`（尤其 `searchUrl`），须真机或 Rhino 直 eval 表达式复核，不能只信 `node --check` / `new Function`（表达式上下文里 `return` 会报 `invalid return`）。

### 1.6 UI / 调试 / 其他

| 方法 | 说明 |
|---|---|
| `log(obj)` / `logType(obj)` | 日志，`logType` 额外打印类型 |
| `toast(obj)` / `longToast(obj)` | 屏幕提示，调试时很直观 |
| `htmlFormat(html)` | HTML 格式化 |
| `encodeURI(s[, charset])` | |
| `s2t(s)` / `t2s(s)` | 简→繁 / 繁→简 |
| `timeFormat(毫秒)` / `timeFormatUTC(毫秒, 格式, 偏移)` | |
| `getSource()` → `BaseSource` | **拿到当前书源对象本身**，可读它自己的字段 |
| `importScript(url)` | **导入外部 JS 库**，之后各处可调用 |
| `getVerificationCode(url)` | 验证码识别 |
| `toNumChapter(name)` | 章节名转数字 |

> `getSource()` 值得一提：意味着书源 JS 里可以读自身的 `bookSourceUrl`、`header` 等属性，不必硬编码。

---

## 2. `cache.xxx` 全表（CacheManager，17 个方法）

| 方法 | 说明 |
|---|---|
| `putMemory(key, obj)` / `getFromMemory(key)` | 内存缓存，进程内跨规则共享 |
| `deleteMemory(key)` | |
| `get(key)` / `put(key, obj[, 秒数])` / `delete(key)` | 持久化缓存 |
| `getInt` / `getLong` / `getFloat` / `getDouble` | 带类型的读取 |
| `getByteArray(key)` | |
| `getFile(key)` / `putFile(key, path[, 秒数])` | 缓存文件 |
| `getQueryTTF(key)` | 缓存字体对象（配合 MMKV 省重复解析） |

> 74xswz 书源用 `putMemory/getFromMemory` 缓存翻页参数 `v`/`q`，属正确用法。

---

## 3. `ajax(url, {json})` 的 12 个选项

由 `AnalyzeUrl$UrlOption.toString()` 字段名还原，是目前见过最全的一份：

| 选项 | 作用 |
|---|---|
| `method` | 请求方法，如 `POST` |
| `body` | 请求体。**注意**：与 `Content-Type` 同时出现时按原样发送，需自行 urlencode |
| `headers` | 请求头对象 |
| `charset` | 指定响应编码，乱码站不用猜 |
| `retry` | 重试次数 |
| `js` | 对返回结果再执行一段 JS |
| `webJs` | 在 WebView 中注入并执行的 JS |
| `webView` | **用内置浏览器发起请求**，返回渲染后源码 |
| `origin` | 源相关标识 |
| `type` | 数据类型标记 |
| `serverID` | 指定使用的服务器 ID（订阅源场景） |
| `webWait` | WebView 等待毫秒数，等 JS 跑完再取源码 |

---

## 4. JS / URL 模板中可用的变量

从 `AnalyzeUrl` 字节码常量还原：

```
java      cache      source     book       bookName   result
key       page       title      text       baseUrl    mUrl
url       urlStr     cookie     headers    escape     hex
utf8      value      tag        zipPath    proxy      jsStr
speakText speakSpeed coroutineContext
```

- `java` → `JsExtensions` 实例
- `cache` → `CacheManager`
- `source` → 当前书源对象
- `result` → 上一步规则的结果
- `key` / `page` → 搜索关键词与页码（Legado 自动注入）
- `baseUrl` → 当前上下文 URL

另有内置模板替换：
- `{{...}}` → 先执行的 JS 片段（如 `{{page==1?'':'-'+page}}`）
- `<(.*?)>` → 可嵌套的 JS 片段，由 `replaceKeyPageJs` 求值后拼进 URL
- `%0` → 占位符

---

## 5. 书源 JSON 顶层字段（BookSource，31 个）

| 字段 | 类型 | 说明 |
|---|---|---|
| `bookSourceName` | String | 名称 |
| `bookSourceUrl` | String | 站点根 URL |
| `bookSourceGroup` | String | **分组**，用于书源管理页归类 |
| `bookSourceType` | int | 类型 |
| `bookSourceComment` | String | 备注 |
| `variableComment` | String | 变量说明，写给别人看的模板变量文档 |
| `enabled` / `enabledExplore` | boolean | 是否启用 / 是否启用发现 |
| `enabledCookieJar` | Boolean | **是否启用 Cookie jar**，登录态站点需要 |
| `exploreUrl` | String | 发现地址，多组换行 |
| `exploreScreen` | String | 发现页筛选 |
| `searchUrl` | String | 搜索地址 |
| `header` | String | **书源级全局请求头** |
| `concurrentRate` | String | **并发率**，防被封（如 `1/1000`） |
| `jsLib` | String | **自定义 JS 库**，定义后可被各规则 JS 调用 |
| `loginUrl` / `loginUi` / `loginCheckJs` | String | 登录三件套 |
| `coverDecodeJs` | String | 封面解码 JS |
| `bookUrlPattern` | String | URL 正则，用于识别本书属于该书源 |
| `ruleSearch` / `ruleExplore` / `ruleBookInfo` / `ruleToc` / `ruleContent` / `ruleReview` | Object | 各规则段 |
| `customOrder` / `weight` | int | 排序权重 |
| `lastUpdateTime` / `respondTime` | long | 更新时间 / 响应时间（自动维护） |
| `CREATOR` | | Parcelable，非书源字段 |

> **最容易被忽略的三个**：`header`（省掉每处重复写 UA）、`jsLib`（公共函数抽出来复用）、`concurrentRate`（防爆）。

---

## 6. 各规则段支持的字段

### search（11）
`bookList` `name` `author` `bookUrl` `coverUrl` `intro` `kind` `lastChapter` `updateTime` `wordCount` `checkKeyWord`

### explore（10）
同 search，**但没有 `checkKeyWord`**

### bookInfo（12）
`init` `name` `author` `intro` `kind` `coverUrl` `lastChapter` `updateTime` `wordCount` `tocUrl` `canReName` `downloadUrls`

### toc（10）
`chapterList` `chapterName` `chapterUrl` `nextTocUrl` `updateTime` `isVip` `isPay` `isVolume` `preUpdateJs` `formatJs`

### content（9）
`content` `title` `nextContentUrl` `webJs` `sourceRegex` `replaceRegex` `imageStyle` `imageDecode` `payAction`

### review（10）
`reviewUrl` `avatarRule` `contentRule` `postTimeRule` `postReviewUrl` `postQuoteUrl` `deleteUrl` `reviewQuoteUrl` `voteUpUrl` `voteDownUrl`

---

## 7. 发现页（ExploreKind）的硬限制

```kotlin
ExploreKind(title: String, url: String, style: Style)
```

**只有这三个属性**，因此 Legado 发现页**结构上不可能分组**，只能用 `男生·都市` 这种「前缀伪装」。

`Style` 支持 flexbox 布局微调（JSON 里嵌套 style 对象）：
`layout_flexBasisPercent` `layout_flexGrow` `layout_flexShrink` `layout_wrapBefore` `layout_alignSelf`

---

## 8. 对本仓库 74xswz 书源的可优化点

| 方向 | 现状 | 可改成 |
|---|---|---|
| UA 重复声明 | 每个 ajax 都手写 `curl/8.5.0` | 挪到书源顶层 `header`，一处维护 |
| 公共函数 | 无 | 抽出到 `jsLib` |
| 防限流 | 无 | 加 `concurrentRate` |
| 调试 | 只有 `java.log` | 失败分支改用 `java.toast` 直观看反馈 |
| 分组 | `bookSourceGroup` 空 | 填值便于归类管理 |

---

## 附：APK 逆向方法（便于日后复现）

```bash
pip3 install androguard
unzip -o legado_app_3.25.apk 'classes*.dex'
# 遍历 DEX(open(f,'rb').read()).get_classes()，按类名筛选后：
#   cls.get_fields()          → 字段（即 JSON key）
#   cls.get_methods()         → 方法名 + get_descriptor()
#   m.get_instructions()      → 字节码，正则抽 const-string 常量
```
