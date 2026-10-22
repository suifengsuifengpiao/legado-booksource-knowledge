# Legado `java` 对象与内置变量速查（Rhino v1.8.1 引擎）

> 阅读使用 [Rhino](https://github.com/mozilla/rhino) 作 JS 引擎，可调用 Java 类与方法。
> `java` 变量是阅读**修改过的当前类**，不是 `java.*` 包——要调 `java.*` 下的包请用 `Packages.java.*`。
> 阅读出于安全屏蔽了部分 Java 类（见 `RhinoClassShutter`）。
> 不同规则里支持调用的 `java.*` 方法可能不同；`const` 声明不支持块级作用域，循环里请用 `var`。

## 内置变量（书源规则可直接用）

| 变量 | 说明 |
|---|---|
| `java` | 当前类（源操作入口） |
| `baseUrl` | 当前 url（String） |
| `result` | 上一步结果；在 `loginCheckJs` 里是响应对象（含 `.url()/.code()/.body()`） |
| `book` / `chapter` / `source` | 书籍 / 章节 / 书源对象 |
| `cookie` | Cookie 操作类（`getCookie`/`getKey`/`setCookie`/`replaceCookie`/`removeCookie`）——3.25 反编译可见这 5 个方法（**未穷举全部 dex**；若某构建另有 `setWebCookie` 之类写入 WebView cookie 的方法，请反馈以补全） |
| `cache` | 缓存操作类（`put`/`get`/`delete`/`putFile`/`getFile`/`putMemory`/`getFromMemory`/`deleteMemory`） |
| `title` | 当前章节标题 |
| `src` | 请求返回的源码 |
| `nextChapterUrl` | 下一章节 url（与 `chapter` 对象同源，规则里可直接用） |
| `isFromBookInfo` | 是否为详情页刷新 |

## `java` 对象常用方法（签名以源码为准）

> ⚠️ **`java` 没有 `urlEncode`**（实测报 `Cannot find function urlEncode in object AnalyzeUrl`）。编码用下面任意一个。

### 编码 / 网络请求（最常用，写 `<js>` 必看）

| 方法 | 签名 | 说明 |
|---|---|---|
| **URI 编码** | `java.encodeURI(str, enc)` | **关键词编码首选**（dex 实证只有两参重载，enc 必传，如 `"UTF-8"`）；或 Rhino 原生 `encodeURIComponent(key)` |
| 普通请求 | `java.ajax(urlStr): String` | **直接返回响应体字符串**（不是包装对象） |
| 并发请求 | `java.ajaxAll(urlList): Array<StrResponse?>` | 批量访问（元素可空） |
| 连接请求 | `java.connect(urlStr): StrResponse` | 3.25 可用（部分参考资料标注"已废弃"）。`loginCheckJs` 里 `result` 必须保留响应对象（带 `.body()/.url()/.code()`），此时只能用 `java.connect` 重取 |
| 连接请求（带请求头） | `java.connect(urlStr, headerJson): StrResponse` | ⚠️ **第二参是请求头 JSON 字符串，不是 body**（3.25 dex 实证：`p0.y` 里 `gson.l(header, Map)`）。**不支持 POST**；要 POST 用 `source.header`/`AnalyzeUrl` 或 `<js>` 里另想办法 |
| **🔴 单参 `java.get` 不是请求** | `java.get(key): String` | **3.25 里单参 `get(String)` 是「取当前书籍/章节变量」**（`bookName`/`title`/`getVariable(key)`），传 URL 只会**静默返回空串**。要发 GET 请求一律用 `java.ajax`。真机踩坑记录见 `site-patterns.md` BTWAF 章节 |
| GET | `java.get(url, headerMap): Connection.Response` | **两参，JSoup 风格响应**（dex: `get(Ljava/lang/String;Ljava/util/Map;)Lorg/jsoup/Connection$Response;`）。⚠️ 与下面的单参形态**同名不同义**，别混用 |
| POST | `java.post(url, body, headerMap): Connection.Response` | **三参**（dex: `post(Ljava/lang/String;Ljava/lang/String;Ljava/util/Map;)...`）；漏 `body` 会让请求体被当成请求头，POST 直接废 |
| HEAD | `java.head(url, headerMap): Connection.Response` | **两参**（dex 实证） |
| WebView 访问 | `java.webView(html, url, js): String?` | 用内置 WebView 取渲染后内容 |
| 浏览器等待 | `java.startBrowserAwait(url, title): StrResponse` | 弹内置浏览器等用户过验证，返回响应 |

### 🔬 dex 真值表：`AnalyzeUrl`（即 JS 里的 `java`）HTTP 方法**全部重载**（1.13.20 androguard 提取，写 `java.xxx()` 前先在此 grep）

```
ajax(Ljava/lang/Object;)Ljava/lang/String;
ajaxAll([Ljava/lang/String;)[Lio/legado/app/help/http/StrResponse;
connect(Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;
connect(Ljava/lang/String;Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;   ← 第2参是 header JSON，非 body
get(Ljava/lang/String;)Ljava/lang/String;                                            ← 取变量！不是请求
get(Ljava/lang/String;Ljava/util/Map;)Lorg/jsoup/Connection$Response;
head(Ljava/lang/String;Ljava/util/Map;)Lorg/jsoup/Connection$Response;
post(Ljava/lang/String;Ljava/lang/String;Ljava/util/Map;)Lorg/jsoup/Connection$Response;
startBrowserAwait(Ljava/lang/String;Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;
webView(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
```

> ⚠️ **只看方法名会翻车**：`get` 有**两个重载且语义完全不同**——单参是取变量、两参才是 GET。
> **教训**：判定"某方法是否存在"必须枚举全部重载（按描述符核对），不能凭一次 grep 的部分输出下结论。

> ⚠️ **签名以 APK 内置 `jsHelp.md`(3.25) 为准**：上面的 `ajax`/`ajaxAll`/`connect`/`get/post/head`/`webView`/`startBrowserAwait` 在 3.25 文档里**只有上述参数**。
> **dex 复验**：`JsExtensions.startBrowserAwait` 的方法描述符确为
> `(Ljava/lang/String;Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;` —— **两参，无第三个布尔参**。
> 部分较新版本源码里这些函数多了 `callTimeout`/`skipRateLimit`/`cacheFirst`/`refetchAfterSuccess`/`html` 等参数——
> **3.25 不一定支持，用到前请用探针/调试桥实测**，别照新版文档硬写。

### 搜索重定向拦截（`raw().request().url()` / `.header("Location")`）

> 来源：3.25 内置 `ruleHelp.md`「url 添加 js 参数 / 增加 js 方法用于重定向拦截」。**已并入技能（此前缺失）**。
> 部分站的搜索会**先 302 跳转到真实搜索页 URL**（URL 里带 token / 分类）。这类源不能把 `searchUrl` 写成死链，
> 要用 `<js>` 在 `page==1` 时发起请求、从响应里取**最终跳转 URL**，存进 `source` 变量复用，后续分页只追加 `&page=`。

```javascript
// 方式一：java.connect 拿最终 URL（StrResponse.raw().request().url()）
(()=>{
  if(page==1){
    let url='https://www.yooread.net/e/search/index.php,'+JSON.stringify({
      "method":"POST","body":"show=title&tempid=1&keyboard="+key
    });
    return source.put('surl',String(java.connect(url).raw().request().url()));
  }
  return source.get('surl')+'&page='+(page-1);
})()

// 方式二：java.post 后从 Location 头取（Connection.Response.header("Location")）
(()=>{
  let base='https://www.yooread.net/e/search/';
  if(page==1){
    return base+source.put('surl',java.post(base+'index.php','show=title&tempid=1&keyboard='+key,{}).header("Location"));
  }
  return base+source.get('surl')+'&page='+(page-1);
})()
```

要点：`source.put/get` 是**源级变量**（跨规则/分页持久）；持久化变量存取另见下方「变量存取」节的 `java.get`/`java.put`；`java.connect`/`java.post` 复用同一 CookieStore，跳转带 cookie 也不会丢。

### 解析 / 变量

| 方法 | 签名 | 说明 |
|---|---|---|
| 取文本 | `java.getString(ruleStr, mContent=null, isUrl=false)` | 按规则解析文本 |
| 取文本列表 | `java.getStringList(ruleStr, mContent=null, isUrl=false)` | 按规则解析文本列表 |
| 设解析内容 | `java.setContent(content, baseUrl=null)` | 改解析源后再取元素 |
| 取元素 | `java.getElement/Elements(ruleStr)` | 取 Element / 列表 |
| 变量存取 | `java.get(key)` / `java.put(key, value)` | 源级变量（跨规则）。⚠️ 但 **`java` 实际绑定的是 `AnalyzeUrl`**，其单参 `get(String)` 经 dex 实证**只读当前书籍/章节**（`bookName`→书名、`title`→章节名、其余→`chapter/ruleData.getVariable(key)`），命中不了就**静默返回空串**——**不能当 HTTP GET 用**，详见上文"编码/网络请求"表的红条 |
| 重取 | `java.reGetBook()` / `java.refreshTocUrl()` | 刷新前重取书籍/目录 url |

### 调试 / 提示 / 用户输入

| 方法 | 签名 | 说明 |
|---|---|---|
| **日志** | `java.log(msg)` / `java.logType(var)` | **调试首选**，把值打到 App 日志 |
| 弹窗 | `java.toast(msg)` / `java.longToast(msg)` | 短/长提示 |
| 验证码 | `java.getVerificationCode(imageUrl)` | 取用户输入的验证码；**可传 data URI**（3.25 用 Glide 加载，内含 `DataUrlLoader`，dex 实锤），故 WAF 返回 base64 码时直接拼 `data:image/png;base64,` 传入即可，无需图片直链 |

> 其余加解密（`createSymmetricCrypto`/`createSign`/`digestHex`/`md5Encode`）、文件操作（`downloadFile`/`readTxtFile`）、`base64`/`hex`、字体（`queryTTF`/`replaceFont`）、`t2s`/`s2t` 等见用户提供的 3.25 反编译（按 dex 描述符 grep 方法名核对签名），不再罗列。

## `{{key}}` 占位符（搜索 URL 免 `<js>` 编码）

搜索 URL 直接写纯字符串 + `{{key}}`，**Legado 会自动 URL 编码**：

```
"searchUrl": "https://站/search.php?searchkey={{key}}&searchtype=articlename"
```

绝大多数搜索不需要 `<js>`。仅当要动态拼 URL、做签名、过动态验证时才用 `<js>`。

## URL 行内选项（追加在 URL 末尾 `,{JSON}`）

格式：`https://example.com/page,{"webView":true}`。常用：

| 选项 | 类型 | 说明 |
|---|---|---|
| `webView` | bool | `true` 时用内置 WebView 加载（SPA/JS 渲染/需执行脚本的页） |
| `webJs` | string | WebView 加载完成后执行的 JS（**需 `webView:true` 才生效**） |
| `webWait` | number | WebView 加载后等待毫秒（**3.25 的字段名是 `webWait`**，写成 `webViewDelayTime` 会被 Gson 静默丢弃） |
| `method` | string | `GET`/`POST`/`HEAD` |
| `charset` | string | 编码 `utf-8`/`gbk` |
| `retry` | number | 重试次数 |
| `headers` | object/array | 自定义请求头（dex 实证字段名只有 `headers`，没有 `header`，写错被静默丢弃） |
| `body` | string | POST 请求体 |
| `js` | string | 访问前执行 JS，结果替换 URL |
| `serverID` | number | 指定服务端/代理 |
| `origin` | string | 原始 URL（内部用） |

> **版本差异（开源阅读 3.25 实测，`model/analyzeRule/AnalyzeUrl$UrlOption`）**：字段只有
> `method / charset / headers / body / origin / retry / type / webView / webWait / webJs / js / serverID`。
> **`dnsIp`、`bodyJs` 在该版本不存在**（新版本文档里才有），写了会被忽略——别拿它们当救命稻草。

## 补充 API（APK `jsHelp.md` 3.25 实测收录，此前技能遗漏）

> 以下均来自 APK 内置 `jsHelp.md`，3.25 真实可用。签名以该文档为准。

### WebView / 浏览器扩展

| 方法 | 签名 | 说明 |
|---|---|---|
| 用 webView 取**跳转 url** | `java.webViewGetOverrideUrl(html, url, js, overrideUrlRegex): String?` | 拦截重定向，返回命中正则的 url |
| 用 webView 取**资源 url** | `java.webViewGetSource(html, url, js, sourceRegex): String?` | 返回命中 `sourceRegex` 的资源地址 |
| 弹内置浏览器（不等待） | `java.startBrowser(url, title)` | 打开链接用于手动过验证码 |
| 取 SystemWebView UA | `java.getWebViewUA(): String` | 拿内置 WebView 的 User-Agent |
| 链接解析（JsURL） | `java.toURL(url, baseUrl): JsURL` | 生成可链式处理的 URL 对象（dex 实证只有两参重载） |

### 脚本 / 缓存文件

| 方法 | 签名 | 说明 |
|---|---|---|
| 导入外部 JS | `java.importScript(url)` / `java.importScript(relativePath)` / `java.importScript(absolutePath)` | 从网络/缓存/本地读 JS 注入上下文（相对路径限 `android/data/{包}/cache`） |
| 缓存网络文件 | `java.cacheFile(url, saveTime)` | 下载并缓存（dex 实证两参重载，saveTime 为秒）；执行用 `eval(String(java.cacheFile(url, 0)))`；删缓存 `cache.delete(java.md5Encode16(url))` |
| 压缩包内取数据（zip/rar/7z） | `java.getZip/get7z/getRarStringContent(url, path, charset)` / `...ByteArrayContent(url, path, charset)` | 取压缩包内指定路径的数据（dex 实证全部三参，charset 必传） |

### 编码 / 字节 / 标识 / 时间

| 方法 | 签名 | 说明 |
|---|---|---|
| String↔ByteArray | `java.strToBytes(str, charset)` / `java.bytesToStr(bytes, charset)` | 与 `base64DecodeToByteArray` 配合处理非 UTF8（dex 实证均为两参，charset 必传） |
| 随机标识 | `java.randomUUID()` / `java.androidId()` | 生成请求唯一标识 |
| 时间格式化 | `java.timeFormatUTC(time: Long, format: String, sh: Int): String?` | UTC 时间格式化 |

> 加解密（`createSymmetricCrypto`/`createAsymmetricCrypto`/`createSign`/`digestHex`/`md5Encode`/`HMac*`）、
> 字体（`queryBase64TTF`/`queryTTF`/`replaceFont`）、`t2s`/`s2t` 等见上表"其余加解密"说明，3.25 一致。

---

## `loginCheckJs` —— 验证墙标准处理（每请求后执行）

Legado 在**每次 HTTP 请求网站后**都执行 `loginCheckJs`，`result` 为响应对象。这是过"自建验证页 / Cloudflare / 验证码"的标准入口，**优先于此而非在 `searchUrl` 里硬写 `<js>`**。边界：只在普通 HTTP 书源链路（含搜索）生效；走 webView 的站（WebBook/webView 内部导航）不触发，过墙靠 webJs，别照搬（铁律 16 v8 修正）。

**过"明文 cookie 自建验证页"（站点 JS 内嵌 `encryptedCookieValue`，自动 setCookie）**：

> 实战教训：**用 `indexOf` 切片，别用正则字面量**。含 `\s`、`\"` 的正则经过复制/转存/剪贴板导入，转义一环被破坏就是 `SyntaxError`。防御版零反斜杠，任何 Rhino 版本都不会挂。

```javascript
var b = result.body();
if (b && b.indexOf('encryptedCookieValue') > -1 && !cookie.getKey(baseUrl, 'is_human')) {
  var i = b.indexOf('encryptedCookieValue');
  var j = b.indexOf('"', i);
  var k = b.indexOf('"', j + 1);
  if (j > -1 && k > j) {
    cookie.setCookie(baseUrl, 'is_human=' + b.substring(j + 1, k));   // 写入域名 cookie
    result = java.connect(result.url());                              // 带 cookie 重取真实内容
  }
}
result;   // 末尾必须返回 result
```

要点：`cookie.getKey` 已设过则不再重连是**防御性检查**（`java.connect` 的返回值不会再过 `loginCheckJs`，不加也不会死循环，该检查也可以省，见 `pitfalls.md`「loginCheckJs 写法细则」）；一次配置、普通 HTTP 链路全局生效（搜索/详情/目录/正文的 HTTP 请求都过验证）；**走 webView 的站不触发**（见本节开头边界）；正则字面量版（`/encryptedCookieValue\s*=\s*"([^"]+)"/`）功能相同，但只在书源不经人工转存时才安全。

**过 Cloudflare 盾（需用户手动点验证）**：

```javascript
var u = result.url(), c = result.code(), b = result.body();
if (/_cf_|ge_ua|verify.php/gi.test(b) && c >= 403) {
  cookie.removeCookie(baseUrl);
  result = java.startBrowserAwait(u, "验证");   // 弹浏览器等用户过 CF（只有两个参数）
}
result;
```

> 注意：`loginCheckJs` 末尾**必须返回 `result`**（修改后的响应对象）。
