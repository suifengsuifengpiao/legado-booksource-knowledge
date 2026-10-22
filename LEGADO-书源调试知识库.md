# Legado 3.25 书源开发与调试知识库（单文件版）

> 用途：AI 跨会话知识库。做 Legado 书源制作/调试/APK 核对任务时，读本文件即可，
> 无需重新反编译 APK 或重新盘点。
> 来源：legado_app_3.25.apk（jadx 1.5.0 反编译 99.4% + apktool 完整 smali + assets 内置官方帮助文档）
> 生成时间：2026-10-22
> 原始明细：/workspace/legado_knowledge/（分文件版） 与 /workspace/forensics/PARSING_STATUS.md

## 目录

1. APK 解析状态与书源调试类索引（反编译完整度、类路径索引、官方文档索引、重跑命令）
2. 源规则总说明：规则标志(@@/@XPath:/@Json:/:regex)、jsLib、并发率、书源类型
3. JS 与 java.* API：写 `<js>` 的权威依据（java.ajax/createSign/connect/get/encodeJS…）
4. 书源调试说明：调试页输入格式（搜索=关键词、发现=名称::URL、目录=++URL、正文=--URL）
5. 书源管理与批量校验：校验判定口径（何为"校验成功"/失效识别范围）
6. （同仓库另附）`解析要点-核心引擎行为与实战坑点.md`：AnalyzeUrl/AnalyzeRule 行为实证、7 大语法陷阱、亿软小说实战案例


---

## 一、APK 解析状态与书源调试类索引

### Legado 3.25 APK 反编译状态

源: /workspace/legado_app_3.25.apk (18.8MB, 11802 类, jadx 1.5.0)

#### 目录
- smali/            apktool 完整输出, 21973 个 .smali (io/legado 4318 类全) —— 基准
- jadx_full2/       jadx 完整输出, 15685 个 .java (11730/11802 = 99.4%) —— **权威 Java 视角**
- _deprecated/      历史中断的部分输出, 勿用

#### 完整度核查 (jadx_full2 vs smali)
- io/legado 业务类: java 3802 vs smali 4318
- 书源解析链路: analyzeRule 34/34, webBook 50/50, AnalyzeUrl/AnalyzeRule/RhinoScriptEngine 全 ✓
- 真实差集 25 类 (均无关): AppConst/ImageProvider/R/NetworkChangedListener,
  book.import UI 系列, 阅读菜单 UI, *ExtensionsKt —— 需要时查 smali
- 另 215 个为 R8 混淆单字母类 (a/b/e5...), 无分析价值

#### 重跑命令 (内存注意!)
cgroup 限额 8GB, 必须显式限堆, 否则被 OOM killer SIGKILL (exit 137):
cd /workspace && JAVA_OPTS='-Xms256M -Xmx4G -XX:MaxRAMPercentage=0' \
  ./jadx_dist/bin/jadx -d forensics/jadx_full2 -j 2 legado_app_3.25.apk

#### 书源开发/调试相关类索引 (jadx_full2/sources 下)

| 类别 | 路径 | 类 |
|---|---|---|
| 解析引擎 | io/legado/app/model/analyzeRule/ | AnalyzeRule, AnalyzeUrl, AnalyzeByXPath/Regex/JSoup/JSonPath, RuleAnalyzer, RuleData, QueryTTF, CustomUrl |
| 规则模型 | io/legado/app/data/entities/ 与 entities/rule/ | BookSource, BookChapter, SearchBook, BookInfoRule, ContentRule, TocRule, SearchRule, ExploreRule, ExploreKind |
| JS 宿主 | io/legado/app/help/JsExtensions + com/script/rhino/ | JsExtensions(java.ajax/webView/createSign 总入口), RhinoScriptEngine |
| 网络 | io/legado/app/help/http/ | CookieStore, StrResponse, ObsoleteUrlFactory |
| 调试 UI | io/legado/app/ui/book/source/debug/ + web/socket/ | BookSourceDebugActivity/Adapter/Model/WebSocket |
| 发现调试 | io/legado/app/ui/book/explore/ | ExploreShowActivity |
| 登录调试 | io/legado/app/ui/login/ | SourceLoginActivity/ViewModel/Dialog |
| 编辑器 | io/legado/app/ui/book/source/edit/ | BookSourceEditActivity/ViewModel/Adapter |

注意: model/webBook 包 50 文件全为 R8 混淆单字母(lambda/协程), 按调用链分析;
      RhinoScriptEngine 在 com.script.rhino, BookChapter/SearchBook/BookSource 在 data/entities。

#### 内置官方帮助文档 (assets/web/help/md/, 均在 smali/assets 下)

写书源直接相关:
- ruleHelp.md       源规则总帮助(规则标志/jsLib/并发率/书源类型)
- jsHelp.md         java.* API 全清单 + book/chapter/cookie/cache 对象(写 <js> 的权威依据)
- regexHelp.md      正则专题 | xpathHelp.md XPath 专题 | txtTocRuleHelp.txt TXT目录规则(67KB)
- debugHelp.md      书源调试官方说明: 搜索=关键词, 发现=名称::URL, 目录=++URL, 正文=--URL
- SourceMBookHelp.md 书源管理界面说明(含批量校验判定口径)

其他: replaceRuleHelp / dictRuleHelp / httpTTSHelp / readMenuHelp / webDavHelp /
      webDavBookHelp / ExtensionContentType / appHelp / LICENSE / privacyPolicy /
      disclaimer / storageHelp / updateLog

路径: forensics/smali/assets/web/help/md/


---

## 二、官方帮助：源规则总说明（ruleHelp）

### 源规则帮助

* [阅读3.0(Legado)规则说明](https://mgz0227.github.io/The-tutorial-of-Legado/)
* [书源帮助文档](https://mgz0227.github.io/The-tutorial-of-Legado/Rule/source.html)
* [订阅源帮助文档](https://mgz0227.github.io/The-tutorial-of-Legado/Rule/rss.html)
* 辅助键盘❓中可插入URL参数模板,打开帮助,js教程,正则教程,选择文件
* 规则标志, {{......}}内使用规则必须有明显的规则标志,没有规则标志当作js执行
```
@@ 默认规则,直接写时可以省略@@
@XPath: xpath规则,直接写时以//开头可省略@XPath
@Json: json规则,直接写时以$.开头可省略@Json
: regex规则,不可省略,只可以用在书籍列表和目录列表
```
* jsLib
> 注入JavaScript到RhinoJs引擎中，支持两种格式，可实现[函数共用](https://github.com/gedoor/legado/wiki/JavaScript%E5%87%BD%E6%95%B0%E5%85%B1%E7%94%A8)

> `JavaScript Code` 直接填写JavaScript片段  
> `{"example":"https://www.example.com/js/example.js", ...}` 自动复用已经下载的js文件

* 并发率
> 并发限制，单位ms，可填写两种格式

> `1000` 访问间隔1s  
> `20/60000` 60s内访问次数20  

* 书源类型: 文件
> 对于类似知轩藏书提供文件整合下载的网站，可以在书源详情的下载URL规则获取文件链接

> 通过截取下载链接或文件响应头头获取文件信息，获取失败会自动拼接`书名` `作者`和下载链接的`UrlOption`的`type`字段

> 压缩文件解压缓存会在下次启动后自动清理，不会占用额外空间  

* CookieJar
> 启用后会自动保存每次返回头中的Set-Cookie中的值，适用于验证码图片一类需要session的网站

* 登录UI
> 不使用内置webView登录网站，需要使用`登录URL`规则实现登录逻辑，可使用`登录检查JS`检查登录结果  
> 版本20221113重要更改：按钮支持调用`登录URL`规则里面的函数，必须实现`login`函数
```
规则填写示范
[
    {
        name: "telephone",
        type: "text"
    },
    {
        name: "password",
        type: "password"
    },
    {
        name: "注册",
        type: "button",
        action: "http://www.yooike.com/xiaoshuo/#/register?title=%E6%B3%A8%E5%86%8C"
    },
    {
        name: "获取验证码",
        type: "button",
        action: "getVerificationCode()"
    }
]
```
* 登录URL
> 可填写登录链接或者实现登录UI的登录逻辑的JavaScript
```
示范填写
function login() {
    java.log("模拟登录请求");
    java.log(source.getLoginInfoMap());
}
function getVerificationCode() {
    java.log("登录UI按钮：获取到手机号码"+result.get("telephone"))
}

登录按钮函数获取登录信息
result.get("telephone")
login函数获取登录信息
source.getLoginInfo()
source.getLoginInfoMap().get("telephone")
source登录相关方法,可在js内通过source.调用,可以参考阿里云语音登录
login()
getHeaderMap(hasLoginHeader: Boolean = false)
getLoginHeader(): String?
getLoginHeaderMap(): Map<String, String>?
putLoginHeader(header: String)
removeLoginHeader()
setVariable(variable: String?)
getVariable(): String?
AnalyzeUrl相关函数,js中通过java.调用
initUrl() //重新解析url,可以用于登录检测js登录后重新解析url重新访问
getHeaderMap().putAll(source.getHeaderMap(true)) //重新设置登录头
getStrResponse( jsStr: String? = null, sourceRegex: String? = null) //返回访问结果,文本类型,书源内部重新登录后可调用此方法重新返回结果
getResponse(): Response //返回访问结果,网络朗读引擎采用的是这个,调用登录后在调用这方法可以重新访问,参考阿里云登录检测
```

* 发现url格式
```json
[
  {
    "title": "xxx",
    "url": "",
    "style": {
      "layout_flexGrow": 0,
      "layout_flexShrink": 1,
      "layout_alignSelf": "auto",
      "layout_flexBasisPercent": -1,
      "layout_wrapBefore": false
    }
  }
]
```

* 请求头,支持http代理,socks4 socks5代理设置
```
socks5代理
{
  "proxy":"socks5://127.0.0.1:1080"
}
http代理
{
  "proxy":"http://127.0.0.1:1080"
}
支持http代理服务器验证
{
  "proxy":"http://127.0.0.1:1080@用户名@密码"
}
注意:这些请求头是无意义的,会被忽略掉
```

* url添加js参数,解析url时执行,可在访问url时处理url,例
```
https://www.baidu.com,{"js":"java.headerMap.put('xxx', 'yyy')"}
https://www.baidu.com,{"js":"java.url=java.url+'yyyy'"}
```

* 增加js方法，用于重定向拦截
  * `java.get(urlStr: String, headers: Map<String, String>)`
  * `java.post(urlStr: String, body: String, headers: Map<String, String>)`
* 对于搜索重定向的源，可以使用此方法获得重定向后的url
```
(()=>{
  if(page==1){
    let url='https://www.yooread.net/e/search/index.php,'+JSON.stringify({
    "method":"POST",
    "body":"show=title&tempid=1&keyboard="+key
    });
    return source.put('surl',String(java.connect(url).raw().request().url()));
  } else {
    return source.get('surl')+'&page='+(page-1)
  }
})()
或者
(()=>{
  let base='https://www.yooread.net/e/search/';
  if(page==1){
    let url=base+'index.php';
    let body='show=title&tempid=1&keyboard='+key;
    return base+source.put('surl',java.post(url,body,{}).header("Location"));
  } else {
    return base+source.get('surl')+'&page='+(page-1);
  }
})()
```

* 图片链接支持修改headers
```
let options = {
"headers": {"User-Agent": "xxxx","Referrer":baseUrl,"Cookie":"aaa=vbbb;"}
};
'<img src="'+src+","+JSON.stringify(options)+'">'
```

* 字体解析使用
> 使用方法,在正文替换规则中使用,原理根据f1字体的字形数据到f2中查找字形对应的编码
```
<js>
(function(){
  var b64=String(src).match(/ttf;base64,([^\)]+)/);
  if(b64){
    var f1 = java.queryBase64TTF(b64[1]);
    var f2 = java.queryTTF("https://alanskycn.gitee.io/teachme/assets/font/Source Han Sans CN Regular.ttf");
    // return java.replaceFont(result, f1, f2);
    return java.replaceFont(result, f1, f2, true); // 过滤掉f1中不存在的字形
  }
  return result;
})()
</js>
```

* 购买操作
> 可直接填写链接或者JavaScript，如果执行结果是网络链接将会自动打开浏览器,js返回true自动刷新目录和当前章节

* 图片解密
> 适用于图片需要二次解密的情况，直接填写JavaScript，返回解密后的`ByteArray`  
> 部分变量说明：java（仅支持[js扩展类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/help/JsExtensions.kt)），result为待解密图片的`ByteArray`，src为图片链接

* 封面解密
> 同图片解密 其中result为待解密封面的`inputStream`


---

## 三、官方帮助：JS 与 java.* API（jsHelp）

### js变量和函数
> 阅读使用[Rhino](https://github.com/mozilla/rhino)作为JavaScript引擎以便于[调用Java类和方法](https://m.jb51.net/article/92138.htm)，查看[ECMAScript兼容性表格](https://mozilla.github.io/rhino/compat/engines.html)

> [Rhino运行时](https://github.com/mozilla/rhino/blob/master/src/org/mozilla/javascript/ScriptRuntime.java#L299)懒加载导入的Java类和方法

|构造函数|函数|对象|调用类|简要说明|
|------|-----|------|----|------|
|JavaImporter|importClass importPackage| |[ImporterTopLevel](https://github.com/mozilla/rhino/blob/master/src/org/mozilla/javascript/ImporterTopLevel.java#L147-L190)|导入Java类到JavaScript|
||getClass|Packages java javax ...|[NativeJavaTopPackage](https://github.com/mozilla/rhino/blob/master/src/org/mozilla/javascript/NativeJavaTopPackage.java#L66-L104)|默认导入JavaScript中的Java类|
|JavaAdapter|||[JavaAdapter](https://github.com/mozilla/rhino/blob/master/src/org/mozilla/javascript/JavaAdapter.java)|继承Java类|

> 注意`java`变量指向已经被阅读修改，如果想要调用`java.*`下的包，请使用`Packages.java.*`

> 在书源规则中使用`@js` `<js>` `{{}}`可使用JavaScript调用阅读部分内置的类和方法

> 注意为了安全，阅读会屏蔽部分java类调用，见[RhinoClassShutter](https://github.com/gedoor/legado/blob/master/modules/rhino/src/main/java/com/script/rhino/RhinoClassShutter.kt)

> 不同的书源规则中支持的调用的Java类和方法可能有所不同

|变量名|调用类|
|------|-----|
|java|当前类|
|baseUrl|当前url,String  |
|result|上一步的结果|
|book|[书籍类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/data/entities/Book.kt)|
|chapter|[章节类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/data/entities/BookChapter.kt)|
|source|[基础书源类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/data/entities/BaseSource.kt)|
|cookie|[cookie操作类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/help/http/CookieStore.kt)| 
|cache|[缓存操作类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/help/CacheManager.kt)|
|title|章节当前标题 String|
|src| 请求返回的源码|
|nextChapterUrl|下一章节url|

#### 当前类对象的可使用的部分方法

##### [RssJsExtensions](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/ui/rss/read/RssJsExtensions.kt)
> 只能在订阅源`shouldOverrideUrlLoading`规则中使用  
> 订阅添加跳转url拦截, js, 返回true拦截,js变量url,可以通过js打开url  
> 例子https://github.com/gedoor/legado/discussions/3259

* 调用阅读搜索

```js
java.searchBook(bookName: string)
```

* 添加书架

```js
java.addBook(bookUrl: String)
```

##### [AnalyzeUrl](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt) 部分函数
> js中通过java.调用,只在`登录检查JS`规则中有效
```js
initUrl() //重新解析url,可以用于登录检测js登录后重新解析url重新访问
getHeaderMap().putAll(source.getHeaderMap(true)) //重新设置登录头
getStrResponse( jsStr: String? = null, sourceRegex: String? = null) //返回访问结果,文本类型,书源内部重新登录后可调用此方法重新返回结果
getResponse(): Response //返回访问结果,网络朗读引擎采用的是这个,调用登录后在调用这方法可以重新访问,参考阿里云登录检测
```

##### [AnalyzeRule](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt) 部分函数
* 获取文本/文本列表
> `mContent` 待解析源代码，默认为当前页面  
> `isUrl` 链接标识，默认为`false`
```js
java.getString(ruleStr: String?, mContent: Any? = null, isUrl: Boolean = false)
java.getStringList(ruleStr: String?, mContent: Any? = null, isUrl: Boolean = false)
```
* 设置解析内容

```js
java.setContent(content: Any?, baseUrl: String? = null):
```

* 获取Element/Element列表

> 如果要改变解析源代码，请先使用`java.setContent`

```js
java.getElement(ruleStr: String)
java.getElements(ruleStr: String)
```

* 重新搜索书籍/重新获取目录url

> 可以在刷新目录之前使用,有些书源书籍地址和目录url会变

```js
java.reGetBook()
java.refreshTocUrl()
```
* 变量存取

```js
java.get(key)
java.put(key, value)
```

##### [js扩展类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/help/JsExtensions.kt) 部分函数

* 链接解析[JsURL](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/utils/JsURL.kt)
```js
java.toURL(url): JsURL
java.toURL(url, baseUrl): JsURL
```
* 获取SystemWebView User-Agent
```js
java.getWebViewUA(): String
```
* 网络请求
```js
java.ajax(urlStr): String
java.ajaxAll(urlList: Array<String>): Array<StrResponse?>
//返回Response 方法body() code() message() header() raw() toString() 
java.connect(urlStr): StrResponse

java.post(url: String, body: String, headerMap: Map<String, String>): Connection.Response

java.get(url: String, headerMap: Map<String, String>): Connection.Response

java.head(url: String, headerMap: Map<String, String>): Connection.Response

* 使用webView访问网络
* @param html 直接用webView载入的html, 如果html为空直接访问url
* @param url html内如果有相对路径的资源不传入url访问不了
* @param js 用来取返回值的js语句, 没有就返回整个源代码
* @return 返回js获取的内容
java.webView(html: String?, url: String?, js: String?): String?

* 使用webView获取跳转url
java.webViewGetOverrideUrl(html: String?, url: String?, js: String?, overrideUrlRegex: String): String?

* 使用webView获取资源url
java.webViewGetSource(html: String?, url: String?, js: String?, sourceRegex: String): String?

* 使用内置浏览器打开链接，可用于获取验证码 手动验证网站防爬
* @param url 要打开的链接
* @param title 浏览器的标题
java.startBrowser(url: String, title: String)

* 使用内置浏览器打开链接，并等待网页结果 .body()获取网页内容
java.startBrowserAwait(url: String, title: String): StrResponse
```
* 调试
```js
java.log(msg)
java.logType(var)
```
* 获取用户输入的验证码
```js
java.getVerificationCode(imageUrl)
```
* 弹窗提示
```js
java.longToast(msg: Any?)
java.toast(msg: Any?)
```
* 从网络(由java.cacheFile实现)、本地读取JavaScript文件，导入上下文请手动`eval(String(...))`
```js
java.importScript(url)
//相对路径支持android/data/{package}/cache
java.importScript(relativePath)
java.importScript(absolutePath)
```
* 缓存网络文件
```js
获取
java.cacheFile(url)
java.cacheFile(url,saveTime)
执行内容
eval(String(java.cacheFile(url)))
删除缓存文件
cache.delete(java.md5Encode16(url))
```
* 获取网络压缩文件里面指定路径的数据 *可替换Zip Rar 7Z
```js
java.get*StringContent(url: String, path: String): String

java.get*StringContent(url: String, path: String, charsetName: String): String

java.get*ByteArrayContent(url: String, path: String): ByteArray?

```
* URI编码
```js
java.encodeURI(str: String) //默认enc="UTF-8"
java.encodeURI(str: String, enc: String)
```
* base64
> flags参数可省略，默认Base64.NO_WRAP，查看[flags参数说明](https://blog.csdn.net/zcmain/article/details/97051870)
```js
java.base64Decode(str: String)
java.base64Decode(str: String, charset: String)
java.base64DecodeToByteArray(str: String, flags: Int)
java.base64Encode(str: String, flags: Int)
```
* ByteArray
```js
Str转Bytes
java.strToBytes(str: String)
java.strToBytes(str: String, charset: String)
Bytes转Str
java.bytesToStr(bytes: ByteArray)
java.bytesToStr(bytes: ByteArray, charset: String)
```
* Hex
```js
HexString 解码为字节数组
java.hexDecodeToByteArray(hex: String)
hexString 解码为utf8String
java.hexDecodeToString(hex: String)
utf8 编码为hexString
java.hexEncodeToString(utf8: String)
```
* 标识id
```js
java.randomUUID()
java.androidId()
```
* 繁简转换
```js
将文本转换为简体
java.t2s(text: String): String
将文本转换为繁体
java.s2t(text: String): String
```
* 时间格式化
```js
java.timeFormatUTC(time: Long, format: String, sh: Int): String?
```
* 文件
>  所有对于文件的读写删操作都是相对路径,只能操作阅读缓存/android/data/{package}/cache/内的文件
```js
//文件下载 url用于生成文件名，返回文件路径
downloadFile(url: String): String
//文件解压,zipPath为压缩文件路径，返回解压路径
unArchiveFile(zipPath: String): String
unzipFile(zipPath: String): String
unrarFile(zipPath: String): String
un7zFile(zipPath: String): String
//文件夹内所有文件读取
getTxtInFolder(unzipPath: String): String
//读取文本文件
readTxtFile(path: String): String
//删除文件
deleteFile(path: String) 
```

##### [js加解密类](https://github.com/gedoor/legado/blob/master/app/src/main/java/io/legado/app/help/JsEncodeUtils.kt) 部分函数

> 提供在JavaScript环境中快捷调用crypto算法的函数，由[hutool-crypto](https://www.hutool.cn/docs/#/crypto/概述)实现  
> 由于兼容性问题，hutool-crypto当前版本为5.8.22  

> 注意：如果输入的参数不是Utf8String 可先调用`java.hexDecodeToByteArray java.base64DecodeToByteArray`转成ByteArray
* 对称加密
> 输入参数key iv 支持ByteArray|**Utf8String**
```js
// 创建Cipher
java.createSymmetricCrypto(transformation, key, iv)
```
>解密加密参数 data支持ByteArray|Base64String|HexString|InputStream
```js
//解密为ByteArray String
cipher.decrypt(data)
cipher.decryptStr(data)
//加密为ByteArray Base64字符 HEX字符
cipher.encrypt(data)
cipher.encryptBase64(data)
cipher.encryptHex(data)
```
* 非对称加密
> 输入参数 key支持ByteArray|**Utf8String**
```js
//创建cipher
java.createAsymmetricCrypto(transformation)
//设置密钥
.setPublicKey(key)
.setPrivateKey(key)

```
> 解密加密参数 data支持ByteArray|Base64String|HexString|InputStream  
```js
//解密为ByteArray String
cipher.decrypt(data,  usePublicKey: Boolean? = true
)
cipher.decryptStr(data, usePublicKey: Boolean? = true
)
//加密为ByteArray Base64字符 HEX字符
cipher.encrypt(data,  usePublicKey: Boolean? = true
)
cipher.encryptBase64(data,  usePublicKey: Boolean? = true
)
cipher.encryptHex(data,  usePublicKey: Boolean? = true
)
```
* 签名
> 输入参数 key 支持ByteArray|**Utf8String**
```js
//创建Sign
java.createSign(algorithm)
//设置密钥
.setPublicKey(key)
.setPrivateKey(key)
```
> 签名参数 data支持ByteArray|inputStream|String
```js
//签名输出 ByteArray HexString
sign.sign(data)
sign.signHex(data)
```
* 摘要
```js
java.digestHex(data: String, algorithm: String,): String?

java.digestBase64Str(data: String, algorithm: String,): String?
```
* md5
```js
java.md5Encode(str)
java.md5Encode16(str)
```
* HMac
```js
java.HMacHex(data: String, algorithm: String, key: String): String

java.HMacBase64(data: String, algorithm: String, key: String): String
```

#### book对象的可用属性
##### 属性
> 使用方法: 在js中或{{}}中使用book.属性的方式即可获取.如在正文内容后加上 ##{{book.name+"正文卷"+title}} 可以净化 书名+正文卷+章节名称（如 我是大明星正文卷第二章我爸是豪门总裁） 这一类的字符.
```js
bookUrl // 详情页Url(本地书源存储完整文件路径)
tocUrl // 目录页Url (toc=table of Contents)
origin // 书源URL(默认BookType.local)
originName //书源名称 or 本地书籍文件名
name // 书籍名称(书源获取)
author // 作者名称(书源获取)
kind // 分类信息(书源获取)
customTag // 分类信息(用户修改)
coverUrl // 封面Url(书源获取)
customCoverUrl // 封面Url(用户修改)
intro // 简介内容(书源获取)
customIntro // 简介内容(用户修改)
charset // 自定义字符集名称(仅适用于本地书籍)
type // 0:text 1:audio
group // 自定义分组索引号
latestChapterTitle // 最新章节标题
latestChapterTime // 最新章节标题更新时间
lastCheckTime // 最近一次更新书籍信息的时间
lastCheckCount // 最近一次发现新章节的数量
totalChapterNum // 书籍目录总数
durChapterTitle // 当前章节名称
durChapterIndex // 当前章节索引
durChapterPos // 当前阅读的进度(首行字符的索引位置)
durChapterTime // 最近一次阅读书籍的时间(打开正文的时间)
canUpdate // 刷新书架时更新书籍信息
order // 手动排序
originOrder //书源排序
variable // 自定义书籍变量信息(用于书源规则检索书籍信息)
 ```

#### chapter对象的部分可用属性
> 使用方法: 在js中或{{}}中使用chapter.属性的方式即可获取.如在正文内容后加上 ##{{chapter.title+chapter.index}} 可以净化 章节标题+序号(如 第二章 天仙下凡2) 这一类的字符.
 ```js
 url // 章节地址
 title // 章节标题
 baseUrl //用来拼接相对url
 bookUrl // 书籍地址
 index // 章节序号
 resourceUrl // 音频真实URL
 tag //
 start // 章节起始位置
 end // 章节终止位置
 variable //变量
 ```
 
#### source对象的部分可用函数
* 获取书源url
```js
source.getKey()
```
* 书源变量存取
```js
source.setVariable(variable: String?)
source.getVariable()
```

* 登录头操作
```js
获取登录头
source.getLoginHeader()
获取登录头某一键值
source.getLoginHeaderMap().get(key: String)
保存登录头
source.putLoginHeader(header: String)
清除登录头
source.removeLoginHeader()
```
* 用户登录信息操作
> 使用`登录UI`规则，并成功登录，阅读自动加密保存登录UI规则中除type为button的信息
```js
login函数获取登录信息
source.getLoginInfo()
login函数获取登录信息键值
source.getLoginInfoMap().get(key: String)
清除登录信息
source.removeLoginInfo()
```
#### cookie对象的部分可用函数
```js
获取全部cookie
cookie.getCookie(url)
获取cookie某一键值
cookie.getKey(url,key)
设置cookie
cookie.setCookie(url,cookie)
替换cookie
cookie.replaceCookie(url,cookie)
删除cookie
cookie.removeCookie(url)
```

#### cache对象的部分可用函数
> saveTime单位:秒，可省略  
> 保存至数据库和缓存文件(50M)，保存的内容较大时请使用`getFile putFile`
```js
保存
cache.put(key: String, value: Any , saveTime: Int)
读取数据库
cache.get(key: String): String?
删除
cache.delete(key: String)
缓存文件内容
cache.putFile(key: String, value: String, saveTime: Int)
读取文件内容
cache.getFile(key: String): String?
保存到内存
cache.deleteMemory(key: String)
cache.getFromMemory(key: String): Any?
cache.putMemory(key: String, value: Any)

```


---

## 四、官方帮助：书源调试说明（debugHelp）

### 书源调试

* 调试搜索>>输入关键字，如：
```
系统
```
* 调试发现>>输入发现URL，如：
```
月票榜::https://www.qidian.com/rank/yuepiao?page={{page}}
```
* 调试详情页>>输入详情页URL，如：
```
https://m.qidian.com/book/1015609210
```
* 调试目录页>>输入目录页URL，如：
```
++https://www.zhaishuyuan.com/read/30394
```
* 调试正文页>>输入正文页URL，如：
```
--https://www.zhaishuyuan.com/chapter/30394/20940996
```


---

## 五、官方帮助：书源管理与批量校验（SourceMBookHelp）

### 书源管理界面帮助

* 书源右上角标志
  * 绿点表示书源有发现,且启用了发现
  * 红点表示书源有发现,但是未启用
  * 没有标志表示此书源没有发现
* 右上角有分组菜单,可以按分组筛选书源
* 右上角更多菜单里包含
  * 新建书源
  * 本地导入
  * 网络导入
  * 二维码导入
  * 分享选中源
* 选择源的更多操作在右下角的菜单里面,操作都是针对选择的书源
  * 启用所选
  * 禁用所选
  * 添加分组
  * 移除分组
  * 启用发现
  * 禁用发现
  * 置顶所选
  * 置底所选
  * 导出所选
  * 校验所选
* 校验书源可批量校验书源，由于网络等原因结果仅限参考
  * "校验成功"是指所选的校验项目全部通过
  * 可正常识别搜索为空、发现为空、搜索(发现)目录为空、搜索(发现)正文为空、校验超时、js执行错误导致的失效，其余的原因视为网站失效
  * 校验搜索优先使用书源填写的校验关键词，不存在时使用用户输入的关键词
  * 校验结束后会自动筛选"失效"书源
