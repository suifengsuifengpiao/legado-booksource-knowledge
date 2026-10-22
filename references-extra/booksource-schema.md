# 开源阅读(Legado)3.0 书源 JSON 字段规范

> **本文 schema 已按 Legado 3.25 反编译版(BookSource.java 及各 Rule 实体)与 App 编辑界面逐字段核对**(2026-10 实测修正)。
> 历史教训: 曾把解析规则塞进 searchUrl 字符串化 JSON 里并使用 `ruleBookList` 这类带前缀键名,
> 导入 App 后所有规则字段显示为空——**App 静默丢弃不认识的键**, 不报任何错。
> 字段名的唯一权威是 App「编辑书源」界面的括号内英文名(如 书籍列表规则 bookList)。

## 一、总体结构(最重要!)

```json
{
  "bookSourceName": "书源名",
  "bookSourceUrl": "https://example.com",
  "bookSourceType": 0,
  "bookSourceGroup": "分组",
  "bookSourceComment": "注释",
  "enabled": true,
  "enabledExplore": true,
  "header": "{\"User-Agent\": \"...\", \"Referer\": \"...\"}",
  "searchUrl":  "URL 或 <js>...</js>",        // 只有请求, 没有解析规则!
  "exploreUrl": "[{\"title\":\"...\",\"url\":\"...\"}]",  // 只有入口, 没有解析规则!
  "ruleSearch":   { "bookList": "...", "name": "...", "bookUrl": "..." },
  "ruleExplore":  { "bookList": "...", "name": "...", "bookUrl": "..." },
  "ruleBookInfo": { "name": "...", "author": "...", "tocUrl": "..." },
  "ruleToc":      { "chapterList": "...", "chapterName": "...", "chapterUrl": "..." },
  "ruleContent":  { "content": "..." }
}
```

**三条铁律:**
1. `searchUrl` / `exploreUrl` **只放请求**; 解析规则在**顶层独立对象** `ruleSearch` / `ruleExplore`。
2. 规则对象的键名**没有 rule 前缀**: 是 `bookList`/`name`/`author`, 不是 `ruleBookList`/`ruleName`。
3. 规则对象写**原生 JSON 对象**, 不要字符串化(字符串化在部分版本也能解析, 但原生对象最稳)。
4. **字段必须放对规则组**: 导入用 Gson 反序列化到实体类, **放错组的键被静默丢弃**(无任何报错, App 编辑界面也看不到该键)。
   最高频的坑是 `tocUrl` —— 它是 `ruleBookInfo` 的键, 不是 `ruleToc` 的(详见第五、六节)。

## 二、顶层字段

| 字段 | 类型 | 说明 | 是否必备 |
|---|---|---|---|
| `bookSourceName` | string | 书源显示名称 | **是** |
| `bookSourceUrl` | string | 书源主页地址，相对链接拼接基准；调试桥 `tag` 即此值 | **是** |
| `bookSourceType` | int | 0 文本 / 1 音频 / 2 图片 / 3 文件 | 否 |
| `bookSourceGroup` | string | 分组 | 否 |
| `bookSourceComment` | string | 注释(显示在编辑界面) | 建议 |
| `header` | string | 全局请求头, **必须是 JSON 对象字符串**（如 `{"User-Agent":"...","Referer":"..."}`） | 建议 |
| `enabled` / `enabledExplore` | bool | 启用 / 启用发现 | 否 |
| `loginUrl` | string | 登录地址 | 否 |
| `bookUrlPattern` | string | 详情页 URL 正则 | 否 |
| `lastUpdateTime` | long | 最后更新时间戳 | 否 |
| **`concurrentRate`** | **string** | **并发限速**（见下方专节） | 否 |
| `enabledCookieJar` | bool | **自动存 Set-Cookie**（UI 标「CookieJar」）；缺省 false，写了 = true | 否 |
| `loginCheckJs` | string | **登录检查 JS**，普通 HTTP 链路每次请求后执行（3.25 实测生效，webView 站不触发；见 field-availability.md 矩阵与 pitfalls 铁律 16 v8 修正） | 否 |
| `loginUi` | string | 登录 UI 布局 JSON（按钮/输入框，可调用 `登录URL` 函数） | 否 |
| `coverDecodeJs` | string | 封面解密 JS（返回解密后输入流） | 否 |
| `jsLib` | string | 共用 JS 库（函数共用），可填片段或 `{"key":"url"}` 复用远程 JS | 否 |
| `customOrder` | int | 自定义排序 | 否 |
| `weight` | int | 书源权重（搜索结果排序） | 否 |
| `variableComment` | string | 变量注释 | 否 |
| `respondTime` | long | 响应耗时（自动填） | 否 |
| `exploreScreen` | string | 发现页自定义界面 | 否 |
| `ruleReview` | object | 书评规则（与 ruleSearch 同级的对象） | 否 |

> 字段名的唯一权威是 App「编辑书源」界面的括号内英文名；上面全部取自 3.25 `BookSource.java` 反编译实体字段表，
> **未在此列出的键一律被 Gson 静默丢弃**（`ruleReview` 是本文档列出的合法键，除此之外的自定义键写了一样不留痕）。

### 🚨 请求头 `header`：只认 JSON，写成 `Key: Value` 会被静默丢弃

> 反编译 `BaseSource$DefaultImpls.getHeaderMap()` 实证（legado 3.25）：`header` 字符串**非 `@js:`/`<js>` 开头时，一律走 `GSON.fromJsonObject<Map<String,String>>(header)`**。
> 因此 `"User-Agent: xxx\nReferer: xxx"`（多行文本格式）**不是合法 JSON → 解析失败 → 整段 header 被丢弃**；
> 随后源码显式兜底：map 里若**没有 `User-Agent`（忽略大小写）就塞入默认 UA `help/config/a→d`（Windows 桌面 Chrome）**。
> 症状：书源看似导入成功，但请求全都用桌面 UA——对“只给手机 UA 发正文/内容”的站，表现为**列表正常、正文空**。
>
> ✅ 正确写法（JSON 对象字符串，注意转义）：`"header": "{\"User-Agent\": \"<手机UA>\", \"Referer\": \"https://site.com/\"}"`
> 也可用 `<js>`/`@js:` 动态生成（返回 JSON 字符串）。
> 排查口诀：**正文空但目录/发现正常 ⇒ 先怀疑 header 没生效（UA 回落默认）**，抓包或改 JSON 复验。

### 并发限速 `concurrentRate`（高价值：可替代"双清"限流 workaround）

> 实测语义来自 `AnalyzeUrl.java:881` 的 `fetchStart()`：按 `bookSourceUrl`（= `source.getKey()`）做**全局限速**，在每次请求发起前施加。

| 写法 | 语义 | 示例 |
|---|---|---|
| 纯数字（无 `/`） | 固定间隔毫秒：两次请求之间至少间隔 N 毫秒 | `"1000"` = 1 秒 1 次 |
| `N/M` | M 毫秒时间窗内最多 N 次请求 | `"20/60000"` = 60 秒内最多 20 次 |

- 类型为 **String**（数字和 `N/M` 都当字符串存），值为 `"0"` 或空 = 不限速。
- 限流是**跨整本书源**的（不是单页面），搜索/详情/目录/正文共用一个配额 → 直接掐断"短时间高频触发站点 30s 限流"的可能。
- **实战意义**：像 shumi99 这种"30 秒搜索间隔"的站，顶层写 `"concurrentRate":"30000"` 或 `"20/60000"`，
  让 App 自己限速即可从源头避开限流挑战，**比在 `searchUrl` 里硬写双清闭环更稳、更干净**。
  （「对付搜索间隔型限流」它是从源头避开的首选；通用限流处置首选仍是 `enabledCookieJar:true` + `loginCheckJs`，
  双清闭环是 webView 卡死时的兜底，见 `pitfalls.md` 铁律 16/18。）

> 🚨 **翻车警示（sk.3qdus.com 真机实测）**：`concurrentRate` 的语义是「**两次请求之间至少间隔 N 毫秒**」，且**跨整本书源全局生效**——它不是「每秒并发 N 个」。有分页目录（`nextTocUrl`）/ 分页正文（`nextContentUrl`）/ 发现的站点，本应**并发**抓取多页（19 页目录约 1 秒），一旦设了 `"1000"`，19 页被**强制串行、每页等 1 秒 ≈ 19 秒**（真机日志 `0:00:324 → 0:19:320`）。**除非为绕过搜索限流刻意设置（如 shumi99 30 秒间隔），否则分页站点不要设这个值**；限流优先用 `enabledCookieJar:true` + `loginCheckJs`（铁律 16 双清闭环）。`validate_booksource.py` 已新增「`concurrentRate>0` 且存在分页」→ WARN。

## 三、搜索: searchUrl + ruleSearch

`searchUrl` 形态:
- 普通: `"https://example.com/search?q={{key}}&page={{page}}"`
- 带请求选项: `"url,{\"method\":\"POST\",\"body\":\"...\",\"charset\":\"gbk\"}"`
- 动态: `"<js> ... return 'url' + ',' + JSON.stringify({method:'POST', body:'...'}) ... </js>"` —— 🚨 返回值必须是「URL`,`{行内选项}`，不能是 `JSON.stringify({'url':...})` 整体对象（真机会整体当 URL 请求 → 404）；POST body 里的关键词**不要预编码**（App 发送时会再编码一次，双重编码 = 查无此书）

`ruleSearch` 字段(与 App「搜索」页签一致):

| 键 | 说明 |
|---|---|
| `bookList` | **必备**, 书籍列表容器(结果为多节点的规则) |
| `name` / `author` / `kind` / `wordCount` | 书名/作者/分类/字数, 相对 bookList 节点 |
| `lastChapter` / `intro` / `coverUrl` | 最新章节/简介/封面 |
| `bookUrl` | **必备**, 详情页链接; 常配 `##正则##$1` 从 `javascript:` 链接中提取真链（注意是 `##...##$1`, 不是 `###$1`） |
| `checkKeyWord` | 校验关键字(调试用) |

```json
"ruleSearch": {
  "bookList": "//ul[@id='list']/li[a[@class='imgbox']]",
  "name": "//h3/a/text()",
  "bookUrl": "//h3/a/@href##.*'([^']+)'.*##$1"
}
```

## 四、发现: exploreUrl + ruleExplore

`exploreUrl` 是**入口数组**的字符串化 JSON(或用换行/&&分隔的多行 URL), `{{page}}` 为页码占位:
`"[{\"title\":\"玄幻\",\"url\":\"/sort_1_{{page}}.html\"}]"`。支持相对路径。

`ruleExplore` 字段与 `ruleSearch` 完全一致(所有入口**共用**顶层一个 `ruleExplore`;
仅当不同入口结构不同时, 才考虑旧式每条入口内嵌自己的规则——新版以顶层为准)。

## 五、详情: ruleBookInfo

| 键 | 说明 |
|---|---|
| `name` / `author` / `kind` / `wordCount` | 书名/作者/分类/字数 |
| `lastChapter` / `intro` / `coverUrl` | 最新章节/简介/封面 |
| `tocUrl` | **目录页链接**(关键!); 留空则视为详情页即目录页。🚨 **它属于 `ruleBookInfo`, 不属于 `ruleToc`**——写进 `ruleToc` 会被导入时静默丢弃(实体类 `TocRule` 无此字段), 于是目录页 URL 退回详情页 |
| `canReName` / `init` | 可选；`init` 是详情页 JS 预取钩子（旧书源兼容键 `bookInfoInit` 校验器也认，新写书源用 `init`） |

## 六、目录: ruleToc

> 🚨 **`ruleToc` 里没有 `tocUrl`**。目录页 URL 规则写在 `ruleBookInfo.tocUrl`。
> 写在这里会被 Gson 静默丢弃(不报错), 目录页退回 `bookUrl`(详情页), 双页站表现为目录永远 0 条。

| 键 | 说明 |
|---|---|
| `chapterList` | **必备**, 章节列表容器 |
| `chapterName` | 章节名, 相对 chapterList 节点求值；**必须以 `/` 开头**写 `//a/text()`（写 `.//a/text()` 会被当 CSS 静默取空） |
| `chapterUrl` | 章节 URL, 相对 chapterList 节点(如 `@href`) |
| `nextTocUrl` | 目录下一页(分页目录必配) |
| `preUpdateJs` / `formatJs` / `isVolume` / `isVip` / `isPay` | 可选 |

## 七、正文: ruleContent

| 键 | 说明 |
|---|---|
| `content` | **必备**, 正文规则; 末尾可接 `##正则##替换` 做净化(循环替换) |
| `nextContentUrl` | 正文下一页 |
| `webJs` / `sourceRegex` / `imageStyle` | 可选 |

```json
"ruleContent": { "content": "//div[@id='article']##章节内容正在更新中！|本章未完.{0,20}" }
```

## 八、净化 replaceRegex(注意格式)

- 🚨 **3.25 反编译版里 `ruleContent.replaceRegex` 是死字段**：全代码库零消费，写了不报错也不执行。
  （书源级 `replaceRegex` 字段同样不存在；各版本对象格式的传闻只在旧版 App 流传，不要写。）
- **唯一可用方案**: 直接在 `ruleContent.content` 规则末尾用 `##正则##替换`(官方"正则之净化", 循环匹配替换), 零额外字段、最稳。

## 九、完整最小可用示例(真实 schema)

```json
{
  "bookSourceName": "示例书源",
  "bookSourceUrl": "https://example.com",
  "bookSourceType": 0,
  "header": "{\"User-Agent\": \"Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36\", \"Referer\": \"https://example.com/\"}",
  "searchUrl": "https://example.com/search?q={{key}}",
  "ruleSearch": {
    "bookList": "//div[@class='book']",
    "name": "//a[@class='name']/text()",
    "bookUrl": "//a[@class='name']/@href"
  },
  "ruleBookInfo": {
    "name": "//h1/text()",
    "tocUrl": "//a[@class='catalog']/@href"
  },
  "ruleToc": {
    "chapterList": "//ul[@class='list']/li",
    "chapterName": "//a/text()",
    "chapterUrl": "//a/@href"
  },
  "ruleContent": { "content": "//div[@id='content']" }
}
```

> 生成书源前务必先走"分析站点"一步；生成后用 `scripts/validate_booksource.py` 校验、
> `scripts/verify_booksource.py` 本地实测(会抓真实页面并跑规则命中)。

## 十、常见 CMS 与参数坑（踩坑沉淀）

- **杰奇 CMS（Jieqi）小说站**：路径特征 `/modules/article/`，书籍详情页多为 `/{数字ID}/`；搜索接口常见 `search.php?searchkey={{key}}&searchtype=articlename`。注意 `searchtype` 取值有讲究——多数站只认 `articlename`（按书名），传 `all` 常被后端拒绝返回空/404，不是规则错。
- **自建"访问验证"页(明文 cookie 模式)**：部分站对搜索等入口弹"访问验证"页, 但验证逻辑是纯前端——页面 JS 里明文写着 `encryptedCookieValue="xxx"`, 点按钮只是 `setCookie('is_human', 值)` 后重定向, **无服务端交互**。破解: searchUrl 用 `<js>` 两步——先请求验证页提取该值, 再带 `Cookie: is_human=xxx` 请求真实页。cookie 值每次请求都变, 不能写死, 但 `<js>` 每次现取所以无感。
- **搜索结果"JS 动态填充"先别急着判死刑**：先确认搜索页 HTML 里是否真无书名(服务端直出=能解析); 再去站点 JS(如 index.js/newmain.js)里挖 `ajax_*` 端点——若端点可直连, searchUrl 直接指向端点即可。真正无解的只有"端点被 CF 等硬防护护住"这一种。
- **`enabledExplore` 与 `exploreUrl` 配套**：想让"发现"频道可用，顶层需 `enabledExplore: true`，且 `exploreUrl` 是**入口数组**字符串(每条含 `title`/`url`)。
