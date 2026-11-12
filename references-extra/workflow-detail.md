# Legado 书源：完整工作流与工具用法

> 由 SKILL.md 下沉的详细内容，按需查阅。

## 何时使用（触发场景）

- 为小说站 / 漫画站 / 听书站编写或重写书源
- 校验已有书源 JSON 的字段完整性（用 `scripts/validate_booksource.py`）
- 验证解析规则是否真的命中（用 `scripts/test_parse.py` + 真实页面样本）
- 调试书源：搜索 / 发现(探索) / 列表 / 详情 / 目录 / 正文某条规则解析失败
- 配置请求头（UA、Referer、Cookie）、字符编码、广告过滤规则
- 判断目标站是静态 HTML 还是动态 JSON 加载，以决定解析方式
- 站点被 Cloudflare / 验证码等防护拦截，自动化工具拿不到页面

### 第零步：先问清用户环境（决定后面走哪条调试路线，别一上来就推荐用不了的）

> **血泪教训**：默认"用户有电脑"会直接把方案做成废方案。大量书源作者**只用手机**、没有电脑，
> 而本技能运行在**云端沙箱**，**连不到用户手机的局域网 IP**。所以动手前必须先确认：

| 用户环境 | 设备侧诊断路线 | 说明 |
|---|---|---|
| **只有手机（最常见）** | **诊断探针书源**（见第七步方案 A） | 我生成探针书源 → 用户导入 App → 搜任意词 → 列表即诊断报告 → 截图发我 |
| 只有手机、且不愿导入额外书源 | App 自带调试界面（方案 B） | 用户在 App 里跑调试，把输出**复制/截图**发我，我解读 |
| 有电脑，且与手机同局域网 | Web 服务调试桥（方案 C） | 电脑运行 `legado_debug_bridge.py` 连手机 1122/1123 |

**默认假设：用户只有手机**（不要开场就问——这是固定答案，反复问只会添乱，同"先问 App 版本"那条的处理）。
- 直接按方案 A/B（探针 / App 内调试界面）准备；
- **只有用户主动说"有电脑"**时，才确认是否同局域网，然后走方案 C；
- 用户明确说没电脑 → 全程不提 Web 服务调试桥。

> 别忘了：**取证用的真实浏览器跑在 Agent 沙盒**（`realcheck.py` / `webview_probe.py`），不需要用户的电脑；
> 用户没电脑只意味着方案 C 不可用，**不意味着取证能力下降**。

### 第一步：分析目标站点（静态 vs 动态 + 防护识别）

> 这是最重要的一步，决定了后续所有规则怎么写，务必先做。

1. 用浏览器自动化（agent-browser / playwright-cli）打开目标站首页与一本书的详情页、目录页、正文页。
2. 判断加载类型：
   - **静态 HTML**：页面源里能直接看到书籍列表、章节、正文文本 → 用 **XPath / CSS** 解析。
   - **动态加载（SPA，如 Vue/React）**：页面源里没有数据，数据走 XHR 接口返回 JSON → 用 **JSONPath** 解析，必要时配合 JS 注入。
3. 抓包看真实请求：真实 API 地址、`method`、`User-Agent`、`Referer`、`Cookie`、请求体（`body`）。
4. 记录编码：老站点多为 **GBK**，现代站多为 **UTF-8**。

#### 防护识别与降级（关键补充）

分析站点时先判断站点防护强度，避免在无谓的"突破"上浪费时间：

- **软防护**（UA / Referer / Cookie 缺失导致 403）→ 补全 `header` 即可，正常走流程。
   - **🔴 cookie 判别型防爬（最易被误诊）**：服务器**按 cookie 决定返回内容**——无有效 cookie（如 `is_human` / `cf_clearance`）时返回**挖空容器 + 解密脚本**（防爬假象），有有效 cookie 时静态 HTML **直接给明文正文**。**判别动作**：带 / 不带 cookie 各抓一次对比；不带即挖空 = 此型。解法 = `enabledCookieJar:true`（让过 CF 后的 cookie 落库复用）+ 先过一次 CF（App 用 WebView 打开任意一页；`bypass_cf.py` 提取的 clearance 与沙盒 IP 绑定、仅供本地 verify 复现，不能落库到手机）。**千万别误判成"JS 渲染必须上 WebView 解析"**——那是绕远路（每章 8 秒 vs 直连 2 秒）。

      **取证命令**（同一个正文页抓两次对比，这是判定此型的唯一依据）：
      ```bash
      python3 scripts/fetch_page.py <正文页URL> -o no_cookie.html
      python3 scripts/fetch_page.py <正文页URL> -o with_cookie.html --cookie "is_human=xxx; cf_clearance=yyy"
      # 判据: 不带 cookie 的样本正文容器为空 + 带 cookie 的有明文 => cookie 判别型
      #       两次都空 => 真 JS 渲染; 两次都有明文 => 只是规则没命中, 别上 WebView
      ```
      cookie 值来源：App 用 WebView 打开该站任意一页过 CF 后从 CookieJar 取（本地取证用 `bypass_cf.py` 提取，但 cf_clearance 与 IP 绑定，手机上无效、不写死进书源）。
   - **硬防护（Cloudflare 挑战页 / Turnstile 勾选验证 / JS 指纹校验）** → 现在**优先用真实浏览器绕过**（见第六步）：`scripts/bypass_cf.py` 用 playwright+chromium 真实渲染，过 Challenge/Turnstile 并提取 `cf_clearance` Cookie；`verify_booksource.py` 已**自动集成**——抓到挑战页会自行调用 bypass 重抓。但沙盒是**数据中心 IP**，Cloudflare 对低信誉 IP 的强 Turnstile 可能仍不放行，此时按以下降级：
     1. **真实浏览器绕过（自动）**：`verify` 检测挑战页 → `bypass_cf` 过 CF → 拿到 clearance 后本地验证解析。提取的 Cookie **仅本地用，不写死进书源**（与 IP 绑定，手机无效）。
     2. 若绕过失败（IP 被标记）：看**首页/CDN 缓存**能否拿到内容，从中提取 URL 规律与 CMS 类型。
     3. 尝试 **archive.org 快照**（CDX API）拿历史页面样本。
     4. 若都拿不到真实 HTML，**基于 CMS 通用模板推测规则**，并在 `bookSourceComment` 与交付说明标注"推测版，待 App 实测"。
     5. 浏览器自动化（agent-browser）仅最后 1 次尝试，**不要反复等待**。

> 重要判断：CF 等硬防护拦的是**自动化指纹**；**Legado App 用真实 Android WebView 访问通常不触发挑战**，因此"推测版书源"在手机里大概率可用，只是需要用户实测确认解析命中。

#### 浏览器自动化局限与止损

- agent-browser / playwright-cli 是分析静态/动态站的主力，但 **headless 指纹会被 Cloudflare 识别**，Turnstile 的跨域 iframe 程序化点击不保证成功（`bypass_cf.py` 会尽力点子 frame 里的 checkbox，但常失败/无效，且循环等待会卡死 daemon）。
- **止损规则**：浏览器过不了 CF/Turnstile 时，**最多重试 1 次即降级**，不要循环等待。卡死的 daemon 用 `agent-browser close --all` 清理。

### 第二步：生成书源 JSON

1. 严格按 `booksource-schema.md` 的**必备字段规范**生成。
2. 确保 `header`（全局请求头）、`charset` 两块基石齐全——这是书源"写得对"和"跑得稳"的分水岭。（`ruleContent.replaceRegex` 在 3.25 生效但**必须以 `##` 开头**；净化仍优先写在 `content` 的 `<js>` / 行内 `##`）
3. 根据第一步结论，从 `parse-paths.md` 选择对应解析路径填充各 `rule` 区域。
4. **强制产出置信度标注**（不足复盘后新增）：在交付的书源与说明里，明确区分
   - **已确认项**：URL 规律、编码、header、CMS 类型等已实测/确定的内容；
   - **待验证项**：解析规则的 class/id 名（尤其硬防护站点只能按模板推测时）、动态站的字段路径。
   把"待验证项"写进 `bookSourceComment`，并提示用户导入 App 后，由我跑 `test_parse.py` 定位或对照浏览器 F12 的真实选择器微调。

### 第三步：验证解析命中（本地实测，关键）

> 本节只放**做法与命令**。踩坑铁律见 [pitfalls.md](pitfalls.md)，站点形态的成套解法见 [site-patterns.md](site-patterns.md)。

字段完整 ≠ 规则正确。`validate_booksource.py` 只查"有没有字段"，**不查"字段对不对"**。

**一键本地实测（推荐，生成书源后优先跑）**：`scripts/verify_booksource.py` 把"抓样本 → 验命中"合成一步——它用 curl_cffi 指纹伪装，按书源规则**自动抓真实页面**（搜索 → 首本书详情 → 目录 → 首章正文；外加发现频道首条入口），搜索抓不到时自动回退用发现频道取书，再把抓到的 HTML 存到本地工作目录并调 `test_parse.py` 验证、汇总 PASS/FAIL：

```bash
python3 scripts/verify_booksource.py <书源.json> --keyword 剑来
# 真实页面会存到输出的工作目录, FAIL 时会指向它供你回看修正
```

- 输出会明确哪些区域 `[MISS]`/`[ERR]`、总体 PASS/FAIL/未判定（本地零样本时结论为"未判定"，不是 PASS），并给出工作目录路径。
- 抓不到的页面（Turnstile / 受保护 ajax）标 `SKIP`，不计入 FAIL。

**手动验证（已有样本时）**：若你已手动拿到 HTML 样本，可直接用 `test_parse.py`：

```bash
python3 scripts/test_parse.py <书源.json> \
    --search 搜索结果页.html \
    --explore 发现列表页.html \
    --bookinfo 详情页.html \
    --toc 目录页.html \
    --content 正文页.html
# 动态站(JSONPath)追加: --json api_sample.json
```

> 取真实页面样本也可用 `scripts/fetch_page.py`（curl_cffi 指纹伪装，能过 CF 对普通页的拦截）：`python3 scripts/fetch_page.py <URL> -o page.html`。

- 脚本用 lxml 在本地跑每条 XPath，报告每个区域/字段是否命中、命中数、前几个样例。
- 目的是把"推测版"变成"可验证版"：若某字段 `[MISS]`，说明 class/id 猜错，需回第一步用真实 HTML 修正。
- CSS 选择器可本地验证（bs4 求值；`~=` 扩展属性走真 Jsoup 通道，无 jar 时标「需真机验证」；
  问号形态并非操作符——Jsoup 把 `?` 解析进属性名，恒不命中，同样路由到真通道得到真机一致的恒空）；JS 注入规则不本地执行，标「需真机验证」。

> ⚠️ **命中 ≠ 正确**：`[OK] 命中 1 条` 只能证明"选择器选到了东西"，值可能仍是错的。
> 因此 `test_parse` / `verify` 额外做**值合理性检查**，命中但可疑时会打 `[⚠ 可疑]` 并在结尾汇总：
> - 只取到标签文字（`作者：`）→ `##` 清洗写反了；
> - 值以 `#` 开头 → `##正则###$1` 写错，应为 `##正则##$1`；
> - `name/author/lastChapter` 取成了 URL → 选错节点；
> - `bookUrl/chapterUrl` 不以 `/` 或 `http` 开头 → `@href` 提取有问题；
> - `lastChapter` 取成日期 → `##` 清洗没生效。
>
> **看到 `⚠ 可疑` 必须处理，不能因为总体 PASS 就交付**（值层面检查里就包括"命中值以 `#` 开头 = `##正则###$1` 写错"这类选错/写错的真实缺陷）。

### 第四步：调试与校验（字段层面）

1. 运行校验脚本检查字段完整性：
   ```bash
   python3 scripts/validate_booksource.py <书源.json>
   # 校验书源组（数组）同样支持；加 --strict 把建议项也视为失败
   ```
2. **书源含 JS 就必须再跑 JS 层检查（与①两道，缺一不可）**：
   ```bash
   python3 scripts/js_layer_check.py --source <书源.json> [--html 夹具.html] [--url URL] [--code <验证码>]
   ```
   - **触发条件**：书源里出现 `loginCheckJs` / `webJs` / URL 行内选项 `js` / 任何规则 `<js>` 即跑——`validate_booksource.py` 只查字符串静态正确性，**不执行 JS**；只跑①就报"全绿"是虚假安全感（SKILL.md 核心工作流同款警告）。
   - **list-js 返回数组类型闸门**：`bookList`/`chapterList` 末段是纯 `<js>` 时，真机 `AnalyzeRule.getElements` 把 JS 返回值强转 `List`——**返回值必须数组**（`JSON.stringify(item)` 组成的数组），否则 `ClassCastException(String cannot be cast to List)` 直接崩溃（mowan v1 实证）；返回 `null` 不崩但静默空列表（书名全空，同样是事故）。本工具在 Node 里真跑并强制该校验。
   - **两形态契约（别扩大化）**：数组闸门只适用于「末段纯 `<js>`」；**链式形态** `<js>...</js>选择器` 的 JS 返串是后段输入（经 `Jsoup.parse` 成 DOM 供尾段求值），最终 result 是 Elements(List)，返串完全合法（58书屋在售源实证）。判定：`_is_pure_js_terminal`（规则串以 `<js>...</js>` 收尾且尾部 trim 为空）。
   - **`<js>` 求值作用域（dex 坐实）**：真机每个 `<js>` 都是独立作用域，跨片段共用 helper 只有两条合法通道——helper 放书源 `jsLib` 字段（真机 shareScope 原型链注入，本工具 `--source` 模式自动注入），或每个子规则内联自含；定义在 `bookList` 的 `<js>` 里对子规则不可见（真机 `ReferenceError` 取名空，见 `pitfalls.md` 铁律 26 坑②）。
   - **Node 缺失时**：本工具 exit 2 跳过（离线安全带，缺失不影响其他验证，仅跳过 JS 层模拟）；此时 `validate_booksource.py` 的 #12「末段纯 `<js>` + 纯选择器子规则」静态 WARN 仍兜最常见的坑②（字符串元素 + 选择器子规则 → 真机确定性取空）。
   - 验证人工弹码路径时加 `--code <码>`：输出出现 `弹码=True(java.getVerificationCode)` 才说明弹码分支真被走到。
3. 逐条验证 selector 是否命中（用 `test_parse.py` 或浏览器自动化 / 在线 XPath 测试工具）。
4. 对照下方「调试提示清单」逐项排查。

#### App「校验书源」到底验什么（来源：3.25 内置 `SourceMBookHelp.md`，已并入技能）

> **别把"校验成功"当成"书源能用"**。App 的 `校验书源`/`校验所选` 只做**空值与异常**巡检，**不校验选择器对错**：

- **"校验成功" = 所选校验项目全部通过**（搜索/发现/目录/正文各自返回非空且无 js 执行错误）；
- 它能自动识别的**失效形态只有这几类**：搜索为空、发现为空、搜索/发现目录为空、搜索/发现正文为空、校验超时、js 执行错误；其余一律判"网站失效"；
- **校验搜索优先用书源自己填的"校验关键字"**（`ruleSearch.checkKeyWord`，没有才用你输入的词）；
- 校验结束会**自动筛出"失效"书源**。

> **实战含义**：校验绿 ≠ 解析对。选择器写错（取到空 / 取到 URL / 只取到标签文字）校验照样可能"通过"或只报"为空"，**真正的命中验证靠 `test_parse.py` / `verify_booksource.py`**（见第三步），校验只是批量体检的粗筛，不能替代逐字段命中测试。

#### 字段归属铁律：字段放错规则组 = 被 Gson 静默丢弃（无任何报错）

Legado 导入书源用 **Gson 反序列化到实体类**。Gson 默认忽略未知键——**写错位置的字段不会报错、不会警告、
在 App 编辑界面里也根本看不到那个键**，只表现为"这个规则没生效"，然后静默回退到默认行为。
这是最难自查的一类 bug：规则和取值都对，就是放错了组。

**已实锤的字段归属**（反编译 `io.legado.app.data.entities.rule.*`，3.25 验证）：

| 字段 | 正确归属 | 常见放错位置 | 放错后的表现 |
|---|---|---|---|
| `tocUrl` | **`ruleBookInfo`** | `ruleToc` | 目录页 URL 回退 `bookUrl`（详情页）→ 双页站目录永远 0 条 → `TocEmptyException` |
| `status`（连载状态） | `ruleBookInfo` | `ruleSearch` / `ruleExplore` | 详情页状态永远空 |
| `updateTime` | `ruleBookInfo` / `ruleToc` 各自有 | 混用 | 更新时间不显示 |
| `bookList` / `name` / `bookUrl` | `ruleSearch` / `ruleExplore` | `searchUrl` 字符串内 | 全部搜索字段空 |

**自查方法（必做）**：生成 JSON 后核对每个键是否在对应组的白名单里；交付前再用 App「编辑书源」界面
点开对应规则组看**键的数量是否与 JSON 一致**（少一个键 = 被丢弃了）。
调试日志里「获取目录链接」那行如果等于详情页 URL，即可确诊 `tocUrl` 被丢弃。

### 第五步：闭环迭代（强制，禁止"推测版"直接交付）

`verify_booksource.py` 只**测**不**改**。生成书源后**必须跑它做本地实测**，出现 FAIL 时执行以下循环，直到 PASS 或被硬防护卡死——**不允许把未经验证的"推测版"直接交付用户**：

1. 读 `verify_booksource.py` 报告的 `[MISS]`/`[ERR]`，定位是哪个区域/字段。
2. 打开工作目录里对应的真实 HTML（`search.html` / `bookinfo.html` / `toc.html` / `content.html` / `explore.html`），用浏览器 F12 或 grep 找到正确的 class/id/属性。
3. 修正书源 JSON 里对应的 XPath/CSS。
4. **重跑 `verify_booksource.py`**，确认该字段变 `[OK]`。
5. 重复 1–4，直到全部核心字段命中（总体结果 **PASS**）。

> **边界（别死磕）**：若某区域页面根本抓不到（Turnstile 交互挑战 / 受保护的 ajax 接口，如 yndonie 的搜索），`verify` 会标 `SKIP` 而非 FAIL——这是**架构性无解**，不要反复改规则，应改用"发现"频道并在 `bookSourceComment` 标注"搜索不可用，待 App 实测"。CSS 规则本地可验（bs4 求值）；JS 规则不本地执行，标「需真机验证」。

### 第六步：反爬与加密逆向（防护站点专用增强）

当第一步识别到硬防护、或调试发现"签名错误 / 字体乱码 / 正文加密"时，启用本组工具做**逆向分析**。它们把"加密参数 / 字体"从黑盒变成可见线索，并尽量自动落地到书源。

> **🔴 6.0 强制前置 · L0 先证伪（再做任何逆向之前）**：调试发现"签名错误 / 403"时，**第一步必须是 L0 证伪**，不是上来就 `reverse_crypto` 抽常量复现。做法：`python3 scripts/l0_probe.py <书源.json>` 先识别签名特征，再依其输出**发一次乱填签名的请求**（把 `sign`/`_ts`/`nonce` 改成乱值），确认服务端到底校验不校验。判读：乱填仍 200 且内容与正常请求相似 → **服务端不校验**，纯算式即过（走 L1 eval 官方 signJs / L2 webView 即可，别复刻算法）；返回 403/错误页 → 才需逆向。
> **为什么是强制**：1.13.15 之前踩过这个坑——给 rrssk 中继搜索先逆了 v14→v17→v18 三版、还下过"Legado 不可能"的错结论，最后一道 5 分钟 L0 测试翻案（多数前端闸 `_ad52ca` DOM 指纹、`_b13bf3` isTrusted **服务端根本不校验**）。`validate_booksource.py` 现在会在"搜索含签名参数但 `comment` 无 `证伪/L0` 标记"时 WARN 提醒；做完证伪把结论写进 `comment` 即可消音。

> **合规边界**：以下工具仅用于**自有书源的本地调试验证**。沙盒为数据中心 IP，对 Cloudflare 强 Turnstile 未必放行；提取的 `cf_clearance` 与 IP 绑定，手机无效，**不写死进书源**（仅用于本地 verify，交付时标注"需 App WebView 自取"）。

#### 6.1 真实浏览器突破 Cloudflare（bypass_cf.py）
- 用途：curl_cffi 抓到 CF 挑战页时，用 playwright+chromium 真实渲染过 Challenge/Turnstile，提取 `cf_clearance`。
- **已自动化**：`verify_booksource.py` 抓到挑战页会**自动调用**它重抓，多数 CF 站点本地验证因此打通。
- 手动：`python3 scripts/bypass_cf.py <URL> --out page.html`（或 `--cookies-out cf.json` / `--wait-text 正文`）。
- 边界：数据中心 IP 可能被标记而失败；此时如实 SKIP，不要反复重试。

#### 6.2 加密参数（请求签名）诊断（reverse_crypto.py）
- 用途：站点搜索/接口需前端生成的 sign/token 时，识别签名参数、定位生成 JS、判定能否 `@js` 复现。
- 用法：`python3 scripts/reverse_crypto.py <URL> [--keyword 剑来] --out report.json`
- 输出：是否启用签名、可疑参数清单、window 签名函数、JS 生成点代码片段、结论（可 @js 复现 / 强校验无解）。
- 落地：若可复现，读生成点 JS 写出 `@js` 段挂到 `searchUrl`（参考 parse-paths.md 的 JS 注入）；**若签名依赖前端闸，先做 L0 证伪（scripts/l0_probe.py）：多数前端闸（DOM 指纹 `_ad52ca`、isTrusted `_b13bf3`）服务端根本不校验，纯算式即过，不必判无解**；只有签名本身依赖真实设备指纹（canvas/webgl 渲染值）且服务端强校验才判无解，此时改 WebView 或放弃。

#### 6.3 字体反爬 & 正文加密（reverse_font.py）
- 用途：字体加密（私有区编码乱码）、正文 base64/hex 加密的诊断与破解。
- 用法：`python3 scripts/reverse_font.py <页面URL或HTML文件> --out report.json`
- 字体：若字形名标准（uni4E00），**自动反推"编码→汉字"映射并生成 `replaceRegex` 条目**，可直接粘贴进 `ruleContent.replaceRegex`（本 App 生效），也可等价改写成 `content` 内 `<js>` 或行内 `##`；**必须 `##` 开头**。随机名（glyph0001）则标注需人工对照。
- 正文：检测 base64/hex，给出 `@js` 解密骨架提示。

#### 6.4 自建"访问验证"页 —— 明文 cookie 模式（实测可破，勿轻易判无解）

不少小说站（站群 CMS）对搜索单独设防，返回一个自建"访问验证"页（标题"访问验证"/文案"反机器人"）。**先看页面 JS 再下结论**——很多是"明文 cookie"模式，完全可破：

- 特征：页面内联 JS 含 `const encryptedCookieValue = "..."`，验证逻辑只是 `setCookie('is_human', 值, 1小时)` 后重定向，**无任何服务端交互**；
- **⚠️ 真相（legado 3.25 反编译版实锤 + 真机双证实）**：**`loginCheckJs` 在本 App 是生效字段，普通 HTTP 链路每次请求后都会执行**（走 webView 的站点/内部导航不触发，边界见铁律 16 v8 修正）。反编译 `BaseSource$DefaultImpls.putLoginHeader` 可见：loginCheckJs 返回值当 JSON，取 `Cookie`/`cookie` → `CookieStore.replaceCookie` 落库，同源 `getLoginHeader` 在后续请求自动带上。**用户 V14 用它过爪机书屋搜索墙，真机实测搜索正常；V15 弃用它改 `searchUrl` 内联 `<js>` 反而搜不到。** 所以过"明文 cookie"验证墙，**优先用 `loginCheckJs`**（最稳）。注意：其他 Legado 构建不一定如此——换 App 请用探针/调试桥实测确认，不要默认套本结论。
- **破法（首选 · `loginCheckJs` 过墙）**：把验证逻辑写进书源 `loginCheckJs` 字段——普通 HTTP 链路每次请求后执行它，检测响应里的 `encryptedCookieValue`、提取 `is_human` 并 `cookie.setCookie`，再用 `java.connect(result.url())` 带 cookie 重取；它返回的对象**必须带 `result`**（修改后的响应）。注意 `loginCheckJs` **不能带 `<js>` 标签**（3.25 不剥标签，Rhino 在 `<` 处语法错）：
  ```javascript
  var b = result.body();
  if (b && b.indexOf('encryptedCookieValue') > -1 && !cookie.getKey(baseUrl, 'is_human')) {
    var i = b.indexOf('encryptedCookieValue');
    var j = b.indexOf('"', i);
    var k = b.indexOf('"', j + 1);
    if (j > -1 && k > j) {
      cookie.setCookie(baseUrl, 'is_human=' + b.substring(j + 1, k));
      result = java.connect(result.url());
    }
  }
  result;
  ```
  关键点：
  - `cookie.getKey(baseUrl,'is_human')` 已设过就不再重连，防回环；`searchUrl` 因此可写回**纯 URL + `{{key}}`**，无需 `<js>`；
  - **用 `indexOf` 切片而不用正则字面量**——这是实战教训：模板若写成 `/encryptedCookieValue\s*=\s*"([^"]+)"/`，JSON 里的 `\s`、`\"` 经过"复制粘贴/网盘转存/剪贴板导入"任何一环都可能被转义破坏，App 里直接 `SyntaxError`（真机截图实锤）。防御版零反斜杠、零正则，任何 Rhino 版本都不会挂；
  - **`searchUrl` 里尽量少留 `<js>`**：本 App 下搜索过墙交给 `loginCheckJs` 更稳；`searchUrl` 内联 `<js>` 两步在部分站点实测不稳（V15 搜不到），非必要不用。
- **破法（次选 · `<js>` 搜索 / WebView）**：仅当 `loginCheckJs` 在你的 App 构建里确实不生效时，才在 `searchUrl` 用 `<js>` 两步（请求验证页→提 cookie→带 cookie 重请求）；CF 盾站用 WebView + `enabledCookieJar:true` 让 cookie 落到 OkHttp 复用。
- **verify 已支持**：`verify_booksource.py` 抓到验证页会先查 `encryptedCookieValue`（**先于 CF 判定**，避免被"访问验证"字样误判为 CF），自动提 cookie 重抓，搜索也能进闭环；
- **手机端搜索失败，先别改规则——用真机调试桥看真实返回（见第七步）**：沙盒能过 ≠ 手机能过。App 日志显示 `<js>` 执行成功、cookie 提取成功却仍拿到 404/验证页，说明是**设备侧**（网络出口、WebView 实现、Cookie 存储、Rhino 版本）差异，靠猜必错。务必用 `scripts/legado_debug_bridge.py` 连真机，把 App 真实回显的 HTML/报错贴出来再定位；
- 坑：此类页面标题也叫"访问验证"，**别和 Cloudflare 挑战混淆**——先查 `encryptedCookieValue` 特征再判 CF；若值是真加密/服务端强校验，才降级为无解。

#### 6.5 `<js>` 动态 URL 与 `##` 正则的语义坑（工具已内置处理）

- `searchUrl` 为 `<js>...</js>` 时：规则必须在顶层 `ruleSearch`；`validate/test_parse/verify` 均已识别；
- **`java` 对象的真实 API（别再猜）**：
  - 没有 `urlEncode` 方法（App 实测报 `Cannot find function urlEncode in object AnalyzeUrl`）；
  - **关键词编码用 `java.encodeURI(str, enc="UTF-8")`**（书源标准方法），或 Rhino 原生 `encodeURIComponent(key)`；
  - 搜索 URL 直接写纯字符串 + `{{key}}` 占位符（如 `https://站/search.php?searchkey={{key}}`），**Legado 会自动 URL 编码 `{{key}}`**，多数情况根本不需要 `<js>`；
  - `java.ajax(urlStr): String` 直接返回响应体**字符串**（不是包装对象）；`java.connect(urlStr): StrResponse`（有 `.body()/.code()/.url()/.headers()`）；`java.get/post/head` 返回 `Connection.Response`；（以上签名以 3.25 内置 `jsHelp.md` 为准，**均无 `callTimeout`/`header` 等较新版本参数**——见下方 ⚠️ 警告）
- **`java.log(msg)` 是首选调试手段**：规则里插入 `<js>java.log(result);</js>` 或 `java.log(xxx)` 把中间值打到 App 日志，连真机调试桥即可看到，杜绝盲改选择器；
- **`##` 清洗规则的真实语义（dex 实证，`AnalyzeRule$SourceRule.makeUpRule` 调 `kotlin.text.u.H0(rule, ["##"], 0, 6)`，末位 6 是 mask 不是 limit——实际 `ignoreCase=false, limit=0`，保留尾部空串，别再猜）**，四段含义依次是
  `[0]规则`、`[1]正则`、`[2]替换串（字段默认 ""）`、`[3]存在则只替换首个匹配`。
  - 只写 `规则##正则`（两段）→ **删除所有匹配**（不是"提取"！这是最容易搞反的一点）；
  - `规则##正则##替换` → 替换；`规则##正则##替换##x` → 只替换第一个；
  - **不存在 `###` 这种分隔符**：写 `##正则###$1` 会被切成替换串 `#$1`，结果前面多一个 `#`（`bookUrl` 会变成 `#/xxx/` 直接废掉）。**正确写法是 `##正则##$1`**；
  - 替换串的 `$N` 在 Python 侧转成 `\g<N>`（test_parse / verify 已按源码语义统一实现）。
- **`##` 切段机制的完整 jadx 反编译见 `references/evidence/AnalyzeRule-SourceRule.java`**（`AnalyzeRule$SourceRule.makeUpRule` 第 1844 行 `H0` 按 `##` 切四段；`splitRegex` 1719 行同用）。
- `@href` 这类裸属性选择器必须挂在列表容器节点上执行，不能直接对整文档跑（verify 的 `first_link_from_list` 已按 ruleChapterList 首节点处理）。

> 这三步是"辅助诊断 + 尽量自动落地"，**不承诺 100% 逆向**：混淆算法、浏览器指纹强校验、动态 WASM 加密等仍需人工读 JS 或在 Node 复现。技能负责把黑盒变成"看得见参数 / 找得到代码 / 能自动破标准字体"的可操作线索。

### 第七步：设备侧诊断（用户没电脑时的主力方案）

三种方案的做法、命令与探针报告判读见 `device-diagnosis.md`。

前提只有一条：**默认用户只有手机**（方案 A/B），只有用户主动说有电脑且同局域网时才用方案 C——别推荐对方用不了的方案，也别反复追问一个固定答案。

## 解析路径与引擎（路径规则与选择见 `parse-paths.md`）

| 路径 | 适用场景 | 在书源中的典型位置 |
|---|---|---|
| JSOUP 默认（`.类@标签@属性`） | 静态 HTML，用 `@` 分层级、写法比 XPath 短；**无引擎标志即走此引擎** | ruleSearch.bookList / ruleToc.chapterList / ruleContent.content（如 `.block@ul@li`、`-.info_chapters@ul@li@a`） |
| XPath | 静态 HTML 节点提取 | ruleSearch.bookList / ruleToc.chapterList / ruleContent.content |
| CSS | 静态 HTML，写法更简洁 | 同上，可作 XPath 替代（与 JSOUP 默认共享 Jsoup 引擎） |
| Regex | 字符串清洗、提取、广告过滤 | rule 末尾 `##正则##替换` / `ruleContent.replaceRegex`（本 App 生效，须 `##` 开头） |
| JSONPath | 动态站 JSON 接口数据 | 动态站的 ruleSearch / ruleToc / ruleContent |
| JS 注入 | 加密参数、签名、动态 URL、解密正文 | `<js>` 包裹的 searchUrl/规则、`@js:` |

## 调试提示清单

- **"改了规则还是同样的报错" → 第一步查导入是否真的成功**：App 导入弹窗的报错（如 `ImportError: Expected BEGIN_ARRAY but was BEGIN_OBJECT` = 文件是单对象不是数组）常被用户忽略，结果一直在调试旧书源。让用户进书源编辑页核对一个字段值（如 searchUrl）确认新文件已生效，再谈规则。
- **`<js>搜索:SyntaxError (Unknown source)#N`** → **`#N` 是出错行号，直接数第 N 行定位**（实战：第 4 行正是含 `\s`/`\"` 的正则行）。两种根因：① 书源是旧版/`<js>` 残留在 searchUrl；② 内嵌 JS 的 `\"`/`\s` 转义在复制/转存中被破坏成 `SyntaxError`。防御：searchUrl 用纯 URL+`{{key}}`；内嵌 JS 写成单行零双引号零反斜杠版（见上文「零转义铁律」）。看到这个报错先让用户核对书源编辑页内容，别急着改规则。
- **规则"命中 0 条"/`bookUrl` MISS/列表有数却被全部丢弃** → 先确认这条规则**意图用哪个引擎**，再对症：① **意图是 XPath 却写了前导点** `.//h3/a/@href` → Legado 只对 `startsWith("/")` 走 XPath，前导点被当成 JSOUP/CSS 静默取空，**必须改成 `//h3/a/@href`（不带点）**；② 但 `.class@tag@attr`（如 `.block@ul@li`、`.info_chapters@ul@li@a`）是**完全合法的 JSOUP 默认规则**——`@` 是层级分隔符、不是 XPath 轴，**不要把它"修"成 `//` 形式**，保留 `@` 分层即可；③ 写成了绝对路径 `/h3/a/@href` → 这是合法 XPath，但只从文档根部匹配，节点不在根部就取空，多数情况改用 `//h3/a/@href`（任意层级都搜）。一句话：**XPath 一律 `//` 开头；JSOUP 默认的 `.类@标签@属性` 就是对的**。详见 `parse-paths.md`「一、JSOUP 默认规则」一节。
- **乱码** → 检查 `charset`（GBK 站常错配为 UTF-8）
- **搜索 / 列表为空** → 先分清两种情形：① 站点实为动态加载且有**可达的 JSON 接口**（XHR 返回 JSON）：改用 JSONPath，先抓真实 API 再写规则；② 结果是 JS 动态填充且接口被 CF/防护拦住（如 yndonie 的 `ajax` 端点）：**Legado 拿不到任何数据源，不是规则写错**，应改用"发现"频道找书并在 comment 标注。另注意杰奇等 CMS 搜索参数坑（如 `searchtype=articlename` 而非 `all`）。
- **正文夹带广告 / 推荐** → 优先在 `ruleContent.content` 规则的 `<js>` 里按行 / 按段过滤（最稳，所有 App 都执行）；规则内联 `##正则##替换` 也可用。`ruleContent.replaceRegex` 在 3.25 **生效**，但必须 `##` 开头；**写裸正则会把正文取空并抛「内容为空」**——这比不生效危险得多。
- **软防护 403 / 空响应** → 补全 `header`：UA、Referer，必要时 Cookie（最常见、最容易解决）
- **硬防护（CF 挑战页 / Turnstile / 验证码）** → **补全 header 无效**；这是自动化指纹被拦。优先走第六步用 `bypass_cf` 真实浏览器绕过（`verify` 已自动触发）；若仍失败，降级为"换 WebView 实测 / 基于 CMS 模板推测 / 用真实 HTML 微调"，不要在 header 上反复试错
- **搜索/接口报签名错误、403 但 header 已对** → 站点可能启用了**请求签名**（sign/token）。**先做 L0 证伪**（`scripts/l0_probe.py` 发一次乱填签名看服务端是否校验）：多数前端闸（DOM 指纹/_ad52ca、isTrusted/_b13bf3）**服务端不校验**，纯算式即过，走 L1 eval 官方 signJs / L2 webView；只有签名本身依赖真实设备指纹（非前端闸）才判无解。确需逆向时用 `scripts/reverse_crypto.py` 诊断：识别签名参数、定位生成 JS、判定能否 `@js` 复现
- **抓到的正文是"乱码字符"（私有区编码）** → 站点用了**字体反爬**。用 `scripts/reverse_font.py` 解析字体：若字形名标准（uni4E00）可自动反推映射并生成 `replaceRegex`（`replaceRegex` 本 App 生效，须 `##` 开头）；否则标注需人工对照
- **正文是一长串 base64 / hex 无意义串** → 正文被**加密编码**，用 `reverse_font.py` 检测并用 `@js` 解码后填回 `ruleContent`
- **CF 挑战页 `verify` 标 SKIP** → 数据中心 IP 被 CF 标记，绕过失败；改用"发现"频道取书 + 标注"搜索需 App WebView 自取"
- **目录 / 正文链接不对** → 检查相对路径是否需拼接 `bookSourceUrl` 或 `baseUrl`
- **详情页字段缺失** → 确认数据在详情页本身，还是需 `ruleBookUrl` 二次跳转请求