# Legado 书源：App 版本指纹与字段可用性矩阵

> 由 SKILL.md 下沉的详细内容，按需查阅。

## App 版本指纹与字段可用性矩阵

> 同一字段（`loginCheckJs` / `ruleContent.replaceRegex`）在不同 Legado 构建里语义不同。`ruleContent.replaceRegex` 在 3.25 **生效但必须以 `##` 开头**；其它构建可能不执行。**默认一律按 3.25 反编译版处理**（见 SKILL.md 版本锁定）：不主动询问用户版本、不假设、不引入"兼容写法/双写"。

### 版本默认与切换时机（不要每次问）

- **默认就是 3.25 反编译版**，直接按本矩阵干活，**不要**在开工前追问"你用的哪个版本/从哪下的"。
- **只有当用户主动说换了版本**时，才重新确认并重建本矩阵；在此之前不假设任何其他构建的行为。
- 若确实需要在真机上确认版本，可用诊断探针书源（第七步方案 A）在 `java` 层探测（`java.log` 打印设备侧结论）
  作为按需手段——探针当前覆盖 java 方法可用性/验证墙/cookie/编码/数据特征，版本号采集需要时再扩，**不是开工前置步骤**。

### 字段可用性矩阵（以本实战 App = 3.25 反编译版为基准）

> 基准判定来自 jadx 全代码库检索；**其他构建请用探针/调试桥实测确认**，不要直接套。

| 字段 / 能力 | 本 App 状态 | 反编译证据 | 备注 |
|---|---|---|---|
| `enabledCookieJar` | ✅ **生效**（缺省 false） | AnalyzeUrl.java:643 三元判空 | 不写 = false，CF 后 cookie 不落库 |
| `ruleToc.tocUrl` / `chapterUrl` 内联 `{webView:true}` | ✅ 生效 | splitSourceRule 切选项串 | webView 解析路径可用 |
| `<js>` 管道（`xpath<js>...</js>`） | ✅ 生效 | AnalyzeRule.evalJS | 正文/规则内 JS 可用 |
| 规则内联 `##正则##替换` | ✅ 生效 | splitSourceRule 解析 | 章节名净化等可用 |
| **`loginCheckJs`** | ✅ **生效**（每次 HTTP 请求后执行） | `BaseSource$DefaultImpls.putLoginHeader`：返回值当 JSON 取 `Cookie`/`cookie` → `CookieStore.replaceCookie` 落库；`getLoginHeader` 后续请求自动带上 | 过"明文 cookie"验证墙首选；**返回值必须带 `result`**；**不能带 `<js>` 标签**（3.25 不剥标签）；**边界：只在普通 HTTP 书源链路生效，走 webView 的站（WebBook/webView 内部导航）不触发**（铁律 16 的 v8 修正），别把"驯兽师"写法照搬到 webView 站 |
| **`ruleContent.replaceRegex`** | ✅ **生效** | `webBook.w.b` 内 `ContentRule->getReplaceRegex()` → `AnalyzeRule.getString$(…,mask=4)`；`SourceRule.makeUpRule` 按 `##` 切段 | **必须以 `##` 开头**（`##正则##替换`）；裸正则=被当规则求值→正文取空→抛「内容为空」。作用对象=多页合并并逐行 trim 后的正文，落库前执行（切段机制完整反编译见 `references/evidence/AnalyzeRule-SourceRule.java`） |

> ⚠️ 锁定说明：本矩阵以你提供的 `legado_app_3.25.apk` 反编译版为基准，且该构建被真机实测证实 `loginCheckJs` 过墙有效。本技能不引用其他任何 Legado 构建；你换版本会主动告知，届时重新核验。

### URL 行内选项：3.25 的等待字段只有 `webWait`

| 3.25 反编译版 | `UrlOption` 等待字段真名 | 被静默忽略的写法 |
|---|---|---|
| legado 3.25 反编译版 | **`webWait`**（唯一生效的等待字段） | `webViewDelayTime`（该版无此字段，Gson 静默丢弃） |

- Gson **静默丢弃未知字段**，所以写成 `webViewDelayTime` = 不报错、不生效、等待退回默认。
- 3.25 反编译版 `UrlOption` 全字段实证：`method` `charset` `headers` `body` `origin` `retry` `type`
  `webView` `webWait` `webJs` `js` `serverID`（**无** `webViewDelayTime` / `bodyJs` / `dnsIp`）。
- **结论：3.25 书源只写 `webWait` 即可，不要写 `webViewDelayTime`**（写了也不生效，纯属误导）。

### 规则组合法键清单（3.25 反编译实证）

> Gson **不拒绝未知键**，写错的字段会被**静默丢弃**：不报错、不警告、不生效。所以必须白名单核对，不要凭记忆。

| 规则组 | 合法键（data class 字段） |
|---|---|
| `ruleSearch` | `checkKeyWord` `bookList` `name` `author` `intro` `kind` `lastChapter` `updateTime` `bookUrl` `coverUrl` `wordCount` |
| `ruleExplore` | `checkKeyWord` `bookList` `name` `author` `intro` `kind` `lastChapter` `updateTime` `bookUrl` `coverUrl` `wordCount` |
| `ruleBookInfo` | `init` `name` `author` `intro` `kind` `lastChapter` `status` `updateTime` `coverUrl` `tocUrl` `wordCount` `canReName` `downloadUrls` |
| `ruleToc` | `preUpdateJs` `chapterList` `chapterName` `chapterUrl` `formatJs` `isVolume` `isVip` `isPay` `updateTime` `nextTocUrl` |
| `ruleContent` | `content` `title` `nextContentUrl` `webJs` `sourceRegex` `replaceRegex` `imageStyle` `imageDecode` `payAction` |

**已踩过的非法键**：`beTime`（详情页更新时间，**不存在**，正确名是 `updateTime`）。书源顶层也没有 `charset` 字段，
charset 只能写在 URL 行内选项 `{"charset":"utf-8"}` 或 `header` 里——写在顶层同样被丢弃。

### 「更新时间」字段的现实：写了不代表会生效

- `SearchRule` / `ExploreRule` / `BookInfoRule` 虽有 `updateTime` 键，但 `BookList.kt` 与 `BookInfo.kt`
  **均无任何消费点**（全代码库检索确认）——解析出来就没人用。
- **只有 `TocRule.updateTime` 真正生效**：`BookChapterList.kt` 取它写入每章的 `tag` / `wordCount`，
  进而影响 `latestChapterTime`。站点目录页若不提供章节时间，这条就没有可用的源。
- 所以详情页那句"更新时间：xxx"在当前版本写进书源也**不会显示**；要在交付说明里如实讲清楚，别让用户拿 App 界面找不到。
- `Book` 实体对应字段是 `latestChapterTitle`（不是 `lastChapter`）、`latestChapterTime`（Long），规则层用 `lastChapter` 是对的。

### 实战启示

- **净化正文**：净化首选 `content` 的 `<js>` 或行内 `##`；**要用 `ruleContent.replaceRegex` 必须 `##` 开头**，且注意它会连带触发逐行 trim + 全角缩进；
- **过"明文 cookie"验证墙（如爪机书屋搜索墙）**：**优先用 `loginCheckJs`**（本 App 实测最稳，自动落 cookie 复用）；CF 盾站用 `enabledCookieJar:true` + WebView 过一次落库；
- **清单化版本敏感字段**：每次新换 App 构建，先用探针/调试桥核验"矩阵"里**版本敏感字段**（如 `ruleContent.replaceRegex`）在该构建是否仍生效，再决定用法。