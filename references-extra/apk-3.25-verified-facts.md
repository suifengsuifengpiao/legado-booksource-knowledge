# Legado 3.25 APK 书源调试功能实证（来自 legado_app_3.25.apk）

> 证据来源：`legado_app_3.25.apk`（用户当前使用版本，18 MB，含 classes.dex×4 + `assets/web/help/md/` 16 篇未混淆 Markdown 文档）。
> 用途：写书源时以「本 APK 实锤」为准。本文件与 SKILL.md 互为印证，不重复展开已有论述。
> 取证方式：① 提取 `assets/web/help/md/*.md` 原文；② 对 4 个 dex 做 strings 关键词计数。

## 一、五个调试入口（debugHelp.md 原文）

- 调试搜索 >> 直接输入关键字（如 `系统`）
- 调试发现 >> 输入 `标题::发现URL`（如 `月票榜::https://www.qidian.com/rank/yuepiao?page={{page}}`）
- 调试详情页 >> 直接输入详情页 URL
- 调试目录页 >> `++URL`
- 调试正文页 >> `--URL`

> 与项目指令「调试输入约定」完全一致。发现调试带分类标题前缀；搜索/详情直接给值。

## 二、校验书源的真相（不可作为「能不能用」的依据）

- `SourceMBookHelp.md`：校验成功 = 所选校验项目全部通过；能识别「搜索为空 / 发现为空 / 目录为空 / 正文为空 / 超时 / JS 执行错误」；**结果仅限参考（网络原因）**；结束自动筛选失效源。
- `appHelp.md` 第 6 点原话：「**效验书源显示失效就说明书源不能用了吗？效验书源只是测试书源，可以做为参考，但失效了不代表书源不能用了。**」
- `appHelp.md` 第 3 点：「部分 **2.0 书源并不适用于 3.0**」→ 必须按 3.0/3.25 字段写，不要套旧源。
- `appHelp.md` 第 7 点：发现/正版书源只能找书看榜，不能看书。

> 结论：App 校验只巡检空值/异常，**「校验成功 ≠ 书源能用」**；真机五项调试才是交付门槛。

## 三、规则标志与关键字段（ruleHelp.md）

- 规则标志：`@@` 默认；`@XPath:` 以 `//` 开头可省；`@Json:` 以 `$.` 开头可省；`:` 正则，**只用于书籍列表和目录列表**（校验器 `test_parse.py` 本地不建模该模式，命中即标「需真机验证」，不误当 CSS/XPath 跑出假结果）。
- `CookieJar`：启用后自动保存每次返回头 `Set-Cookie`，适用验证码 session 类站点（dex 实证 `enabledCookieJar` 出现 58 次）。
- 并发率：`1000`（间隔 1s）或 `20/60000`（60s 内 20 次）。
- URL 行内 `js` 字段：`https://x.com,{"js":"java.headerMap.put('k','v')"}` —— 解析 url 前执行。
- 搜索重定向拦截：`java.get(url,headers)` / `java.post(url,body,headers)` / `java.connect(url).raw().request().url()` / `java.post(url,body,{}).header("Location")`。
- 字体反爬：正文替换里 `java.queryBase64TTF` / `java.queryTTF` / `java.replaceFont(result,f1,f2,true)`。
- 图片/封面解密：JS 返回 `ByteArray`，`result` 为待解密字节/流。

## 四、JS API 关键签名（jsHelp.md）

- 变量：`java`(当前类) `baseUrl` `result` `book` `chapter` `source` `cookie` `cache` `title` `src` `nextChapterUrl`。
- 网络请求（注意参数个数；**完整重载真值表见 `apk-method-inventory.md` 的 `AnalyzeUrl` 节**）：
  - `java.connect(urlStr): StrResponse` —— **单参**；另有两参 `connect(urlStr, headerJson)`，第二参是**请求头 JSON 不是 body**
  - `java.ajax(urlStr): String` —— **单参**（无 callTimeout/header 新版参数）
  - `java.post(url, body, headerMap): Connection.Response` —— **三参**（body 不是 headerMap）
  - `java.get(url, headerMap)` / `java.head(url, headerMap)` —— 两参
  - 🔴 **`java.get(urlStr)` 单参不是请求**：dex 实证其实现体只处理 `bookName`/`title`/`getVariable(key)`，
    传 URL 会**静默返回空串**（不报错）。要发 GET 用 `java.ajax`，别被"两参 get 是 GET"类推误导。
- webView：`java.webView(html,url,js)` / `java.webViewGetOverrideUrl(html,url,js,regex)` / `java.webViewGetSource(html,url,js,regex)`。
- 验证码：`java.getVerificationCode(imageUrl)`；调试：`java.log / java.logType`；弹窗：`java.toast / java.longToast`。
  - **data URI 可用（dex 实锤）**：弹码框 `VerificationCodeDialog.i()` 用 Glide 加载 `imageUrl`（`com.bumptech.glide.c.F`），Glide 内置 `DataUrlLoader`（混淆名 `Lj0/c`，`d()`：`startsWith("data:image")` → `indexOf(',')` → `endsWith(";base64")` → `Base64.decode`）⇒ 形如 `data:image/png;base64,...` 的字符串可直接传入显示。
  - ⚠️ **MIME 中间段不敏感**：`DataUrlLoader` 只校验 `data:image` 前缀与 `;base64` 后缀，中间的 `png`/`jpg` 写错也不影响解码（字节流交给解码器按文件头判定）。taozitxt 实测站方 JS 自己标 `png` 而实际数据是 JPEG（`/9j/`），照样能显示。
- 加解密：`createSymmetricCrypto / createAsymmetricCrypto / createSign / digest* / md5Encode / HMac* / base64Decode*`（`java.base64DecodeToByteArray` 返回类型不确定，纯 JS 复现更稳）。

## 五、dex 字符串取证（UrlOption / 反编译实证）

| 关键词 | dex 出现次数 | 含义 |
|---|---|---|
| `webWait` | 4 | ✅ 3.25 真实等待字段 |
| `webViewDelayTime` | **0** | ❌ 不存在 → 写它静默失效（铁律坐实） |
| `webView` | 155 | ✅ 字段与逻辑存在 |
| `webJs` | 4 | ✅ 存在 |
| `loginCheckJs` | 63 | ✅ 真实钩子，多处引用 |
| `enabledCookieJar` | 58 | ✅ 真实集成 |
| `UrlOption` | 10 | ✅ 类存在 |
| `charset`/`headers`/`retry`/`serverID` | 221/172/104/6 | ✅ UrlOption 字段表齐全 |
| `analyzeUrl` | 39 | ✅ 存在 |

> 注：`BackstageWebView` 在 dex 字符串计数为 0（类名已混淆），不影响结论——`webView` 逻辑存在（155 次），行内选项用 `webView/webWait/webJs` 即可。

## 六、searchUrl `<js>` 返回值契约（39 书屋 wap.39shuwu.com 真机实证）

- **执行链**：`AnalyzeUrl.initUrl` 剥离 `searchUrl` 的 `<js>` 前缀后整段 eval，**返回值整体作为新 URL 字符串**，再按「URL + 英文逗号 + `,{JSON}`」规则拆出 `UrlOption`。
- 🚨 **返回值必须是「URL`,`{行内选项}`字符串**（如 `return u + ',' + JSON.stringify({charset:'UTF-8'})`）。
  返回 `JSON.stringify({'url':u,...})` 整体对象 → 真机把返回值整体当 URL 字面量发请求，地址以 `{"url"` 开头 → **必然 404**（本地 lint 仅报"请求失败"，真机翻日志才现形）。
- **POST body 里的关键词不要预编码**：App 发送请求体时会**再做一次 form 编码**，JS 里预先 `encodeURIComponent` = 双重编码 → 服务端查无此书，表现为 `code=0` 但 `search` 数组为空。
- **配套检测**：`validate_booksource.py` 对这两类形态分别出 ERROR（整体对象）与 WARN（body 预编码），回归用例 `bad-searchurl-js-return-json-object` / `bad-searchurl-js-body-preencoded` / `good-searchurl-js-url-combo` 三对正反标本固化。

## 七、与本技能的对应关系

- ✅ 版本锁定 3.25（用户 APK 即此版本，基准一致）。
- ✅ 等待字段只认 `webWait`（`webViewDelayTime` 在 dex 中 0 次，**实证**为死字段）。
- ✅ `enabledCookieJar` / `loginCheckJs` 均真实存在且被高频引用。
- ✅ 净化走 `content` 行内 `##正则##替换##`；`ruleContent.replaceRegex` 为死字段（help 文档未给 replaceRegex 任何消费说明）。
- ✅ JS API 签名（`post` 三参、`connect`/`ajax` 单参、重定向 `java.connect/...header("Location")`）与 jsHelp.md 完全对齐。
- ✅ 校验不可靠的论断被 `SourceMBookHelp` + `appHelp` 双重证实。
