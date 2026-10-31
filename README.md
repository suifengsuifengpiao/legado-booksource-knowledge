# Legado 3.25 书源开发与调试知识库

面向 Legado(阅读3.0) 书源制作、调试、APK 行为核对的跨 AI 知识库。

> **技能包在哪？** 在仓库的 [发行版(Releases)](https://gitee.com/z157001/legado-booksource-knowledge/releases) 页面，**不在**代码标签页的 `releases/` 文件夹里。后者只是 2026-10-26 之前的早期归档，详见 [`releases/README.md`](releases/README.md)。手机网页版顶部没有「发行版」入口，需下拉点「桌面版」或直接输入上面的链接。

任何 AI 助手: 先读 `LEGADO-书源调试知识库.md`(索引+核心文档), 按需查 `official-help/`(官方帮助全文)。

## 内容清单

| 路径 | 内容 |
|---|---|
| `LEGADO-书源调试知识库.md` | 主知识库: APK 解析状态、书源/调试相关类索引(含路径)、4 份核心官方文档 |
| `official-help/` | Legado APK 内置全部 16 份官方帮助文档原文 |

## official-help/ 文档索引

- `ruleHelp.md` — 源规则总说明: 规则标志(@@/@XPath:/@Json:/:regex)、jsLib、并发率、书源类型
- `jsHelp.md` — JS 与 `java.*` API 全清单(写 `<js>` 的权威依据): java.ajax/createSign/connect/get/encodeJS…
- `debugHelp.md` — 书源调试说明: 搜索=关键词, 发现=名称::URL, 目录=++URL, 正文=--URL
- `SourceMBookHelp.md` — 书源管理界面与批量校验判定口径
- `SourceMRssHelp.md` — 订阅源帮助
- `regexHelp.md` / `xpathHelp.md` — 正则 / XPath 专题
- `txtTocRuleHelp.md` — TXT 目录规则(67KB)
- `replaceRuleHelp.md` / `dictRuleHelp.md` / `httpTTSHelp.md` / `readMenuHelp.md`
- `webDavHelp.md` / `webDavBookHelp.md` / `ExtensionContentType.md` / `appHelp.md`

## 新增目录（2026-10-22）

| 路径 | 内容 |
|---|---|
| `tools/` | 书源工具链 **v1.14.10**（脚本与技能 scripts/ 严格同步）：validate_booksource / test_parse / realcheck / bypass_cf / js_layer_check / reverse_crypto / reverse_font / webview_probe / l0_probe / make_probe_source / check_environment / self_audit / verify_booksource / legado_debug_bridge / fetch_page 共 15 个 + `jsoup_eval/`（.java/.class/jar 三件齐备）+ 清单 README；另含 `lint/booksource_lint.py`（知识库侧 lint 工具，v1.14.10 新增 `strip_url_options()`：抓取前剥离 `url,{...}` 请求选项，修掉带 webView/method/body 的书源被误报「抓取失败」） |
| `tools/b2/` | **B2 真机引擎 harness**（2026-10-26）：在纯 JVM 加载 Legado 3.25 APK 真实 `AnalyzeRule` 解析类，四模式（jsoup / js-Rhino / xpath / jsonpath）真机保真；零外部选择器 jar、网络硬短路。含 `android-stub/`（最小 Android 桩 24 类 + 构建脚本）、`B2Harness`/`RegionRunner`/`NetworkStub` 等源码、`samples/`、`QA_REPORT.md`（独立复验全 PASS）、`OUTPUT_CONTRACT.md`。前置条件见 `deps-report.md`（需要 `/workspace/b2-work/classes*.jar` 与 enjarify 修复包，由 APK 现转） |
| `docs/` | B2 引擎设计文档：`b2-harness-design.md`（架构 + T1–T6 任务分解）、`b2-harness-class.mermaid`、`b2-harness-sequence.mermaid`、`b2-feasibility.md`（可行性评估） |
| `cases/` | 实战层：多站案例集（兔九三/74xswz/3qdus/菠萝猫/速读谷/黄金屋/book55/纸间阅读/xs5200 9 站修复记录）+ **过盾专题（CF 盾物种分类：cookie壳页/GoEdge/五秒盾/Turnstile/altcha，Turnstile 三层死结）** + 黄金屋/book55/xs5200 站点档案 + 菠萝猫修复总结/站点档案 + 74xswz 书源逆向档案（签名机制演进：抽常量复刻→eval 官方 signJs；AES 目录接口；引擎坑记录）+ 格格党站点档案（零防护静态站基准样本：POST 搜索隐藏字段/目录全量内嵌判据/_N 页内分页三态断链/lazy 封面/搜索发现双列表结构）+ **站点档案（百草露 / 手机小说 / 八叉书库 3 站，2026-10-31）** |
| `references-extra/` | API 文档层：Legado_3.25 书源编写参考、方法补集、pitfalls（铁律 26「真机才暴露的列表规则三坑」+ 2026-10-24 新坑补遗 N1~N9：桩书/壳页赋值形态/nextTocUrl尾页/searchUrl内联JS不执行/altcha可webJs点/webWait别配短/UA跳域/正文只给一段实为UA分流/java.timeFormat只吃时间戳 **+ 2026-10-31 补遗 N10~N13：`@html`删script、分页变量跨章、搜索字节闸、`Packages.java`污染**）、site-patterns（含混合聚合站 SPA+CDN 四 type 样本、纯 JS 判下一页页码判据）、legend-js-api、parse-paths、booksource-schema、apk-3.25-verified-facts |
| `samples/` | 真机验证过的书源样本 10 份（黄金屋/无限小说网/5200小说网/话本小说/笔趣阁biquge/篱笆好文学/格格党/**百草露/手机小说/八叉书库**） |
| `releases/` | **发布物（五件，按需取）**：<br>① **`legado-tools_v1.14.10.zip`（2.5MB）— 静态校验工具，解压即用**：15 个脚本 + `jsoup_eval/`（含 jar）+ `lint/` + **`AI-USAGE.md`（给其他 AI 的下载与使用指引）**。直链：`https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-tools_v1.14.10.zip`<br>② **`legado-tools-b2-runtime_v1.14.10.zip`（27MB）— B2 真机引擎运行时，解压即跑**：APK 转出的 4 个 `classes*.jar` + `xpath-fix-enjarify.jar` + 已编译 harness（`b2-out/`）+ `android-stub.jar` + **`rhino-resources.jar`（Rhino 本地化资源，dex2jar 会丢，缺了 JS 报错会被 MissingResourceException 盖住）** + `BUILD.md`（从零重建步骤）+ 源码。直链：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.14.10-b2.5/legado-tools-b2-runtime_v1.14.10.zip`<br>③ **`legado-booksource-debug_v1.14.10.skill`** — 书源工坊技能包，装到 `~/.codebuddy/skills/legado-booksource-debug/` 后本会话当场可用。直链：`https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-booksource-debug_v1.14.10.skill`<br>④ **`legado-booksource-debug_v1.15.0.skill`** — 技能包（2026-10-31）：3.25 `@html` 语义纠偏（删 script/style 后取**单条** outerHtml，≠ innerHTML）、新增 `all` 指示符（不删 script）、`test_parse` 末段 html/all 强制走真 Jsoup 通道、evals 新增「正文藏在 script 里」夹具 + 4 条 golden。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.0/legado-booksource-debug_v1.15.0.skill`<br>⑤ **`legado-booksource-debug_v1.15.2.skill`** — 技能包（2026-10-31 23:35）：纯工具修复三处 —— `test_parse.py` 补点号/冒号索引与 `tag.` 语法糖；`validate_booksource.py` 新增 `check_verify_coverage()`（`&&`/`||`、`td.0,2` 混合索引、`@js:`/`<js>` 三类「本地验不到」显式点名，NOTE 级）；`verify_booksource.py` POST 补 `Content-Type`。`SKILL.md` 输出契约新增「验证覆盖率必须交代」。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.2/legado-booksource-debug_v1.15.2.skill` |
<br>⑥ **`legado-booksource-debug_v1.15.3.skill`** — 技能包（2026-11-01 00:08）：修 `_meta.json` 的 `display_name` 版本漂移（`version` 到 1.15.2 而展示名仍写 v1.15.0，**两侧自检都通过**——旧检查只比对 `version` 字段）。`self_audit.py` 新增检查 3c：从 `display_name` 正则取 `v?\d+\.\d+\.\d+` 与 `version` 比对，展示名不含版本号则跳过。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.3/legado-booksource-debug_v1.15.3.skill`<br>⑦ **`legado-booksource-debug_v1.15.4.skill`** — 技能包（2026-11-01 00:50）：修「数据源损坏 → 自检全绿放行」。`_meta.json` 损坏成非法 JSON（或空文件）时，3b/3c 两段被 `except Exception: pass` 同时吞掉，自检照常打印「五项检查全部通过」——**护栏停摆且自称正常**。两处改为报 ERROR，并新增第三组反例「畸形 meta」进 `--self-test` 永久防回归。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.4/legado-booksource-debug_v1.15.4.skill` |
<br>⑧ **`legado-booksource-debug_v1.15.5.skill`** — 技能包（2026-11-01 01:05）：把「判不了」从静默改成明说。`display_name` 版本检查此前只认三段式，两段式 `v1.15` 与 `1.15(beta)` 落进「无版本号」分支被**静默跳过**——看起来检查过了，实际没判。本轮正则放宽为 `v?(\d+(?:\.\d+)+)`，段数≠3 改为 **NOTE 非阻断**（新增 `notices` 通道，`[NOTE]` 与 `[OK]` 可同屏且互不冒充），`--self-test` 增第四组反例「两段式 NOTE」。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.5/legado-booksource-debug_v1.15.5.skill` |
<br>⑨ **`legado-booksource-debug_v1.15.6.skill`** — 技能包（2026-11-01 01:55）：修「日期在前的误报」，并证明漏报没废。`display_name` 版本检查原用 `v?(\d+(?:\.\d+)+)`，`v?` 让前缀**可选** ⇒ 等价于「版本号 = 展示名里第一个数字串」，于是 `书源工坊 2026.11.01 v1.15.5` 取到日期 `2026.11.01`，**对着正确的版本号报 ERROR**。改为两级：先 `[vV]\s*(\d+(?:\.\d+)+)`（语义上就是版本），找不到才退回裸数字串（保持纯日期旧行为）。**误报修了、漏报没废**：`2026.11.01 v1.15.0` 仍 ERROR 且指向 `1.15.0`。新增第五组反例「日期在前须放行」，**方向与前四组相反**（这一组要求 `exit==0`），必须独立成组。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.6/legado-booksource-debug_v1.15.6.skill` |

## 2026-10-31 更新

- **技能升级 v1.15.0**：`@html` 语义纠偏 —— 3.25 的 `AnalyzeByJSoup.getResultLast` 会先 `select("script").remove()` + `select("style").remove()` 再取 `outerHtml()`，**与 innerHTML 不同**；正文藏在 `<script>document.writeln(...)</script>` 的站点用 `@html` 会把正文删干净。新增 `all` 指示符（直接 `outerHtml()`，不删 script）。工具链三处同步（`JsoupRuleEval.java` / `test_parse.py` / evals golden），**铁律 27** 入库。全套回归 59/59 + equiv 19/19。
- **引擎侧独立复核（2026-10-31）**：对 `legado_app_3.25.apk` 定向反编译 `io.legado.app.model.analyzeRule.AnalyzeByJSoup`，确认上述 `html`/`all` 分支原文；并用构造的「正文在 script 里」页面本地实测 —— `#txt@html` 输出 97 字符（script 全删）、`#txt@all` 输出 273 字符（2 个 script 保留）。**本条不是转述，是原文 + 实测双证**。
- **新增 3 站档案**：百草露（正文脚本 Base64 + 章节分页跨章陷阱）、手机小说（搜索字节闸 + 限频 cookie）、八叉书库（接口型正文 + Rhino 跨语言两坑）。
- **3 站真机验证状态（2026-10-31 收口）**：百草露、手机小说、八叉书库三份书源**均已真机验证通过、可用**（用户确认）。百草露原「未跑真机 e2e」标注已撤销，其档案第五节改为「真机通过后仍存的未知项」（拼页逐章取证、超 8 页截断、多页目录、搜索 POST 抓法四项，均为可用性之外的细节边界）。**注意：`samples/手机小说书源.json` 原件为导出态 `enabled:false`，直接导入处于禁用状态，需手动启用**（归档样本保持原样，不改动提交方原件）。
- **坑点补遗 N10–N13**：`@html` 删 script / 分页变量跨章 / 搜索字节闸 / `Packages.java` 污染。
- **技能自检 v1.15.3（2026-11-01 00:08，元数据显示修复，不影响解析）**：`_meta.json` 的 `display_name` 内含版本号与 `version` 不一致（`version=1.15.2` / `display_name=书源工坊 v1.15.0`），**我方与书源侧两侧自检均通过**——旧检查只比对 `version` 字段，从不看展示名。后果仅为技能市场展示旧版本号，属**静默不一致**。修法：新增检查 3c，从 `display_name` 取 `v?\d+\.\d+\.\d+` 与 `version` 比对，展示名不含版本号则跳过（避免误伤）。**先红后绿已双向实测**。
- **技能自检 v1.15.6（2026-11-01 01:55，修反向误报）**：`display_name` 版本检查的 `v?` 让前缀可选，等价于「取展示名里第一个数字串」，`2026.11.01 v1.15.5` 因此取到日期当版本、对着正确版本号报 ERROR。改为两级匹配（带 `v/V` 前缀优先，无前缀才退回裸数字串）。**验收标准是双向的**：① 日期在前的**正确**展示名须放行（`exit=0` 且无「版本漂移」）；② 日期在前的**错误**展示名须照旧 `exit!=0` 且指向真版本号。只验 ① 会顺手把检查器改瞎——`--self-test` 第五组方向与前四组相反（要求 `exit==0`），必须独立成组，混在一起会互相抵消。\n- **技能自检 v1.15.5（2026-11-01 01:05，判不了就说判不了）**：`display_name` 版本检查的正则原为 `v?(\d+\.\d+\.\d+)`，两段式 `v1.15`、`1.15(beta)` 匹配不上 → 落进「无版本号 → 跳过」→ **静默放行且自检全绿**。这是「样本不合预期 → 静默 → 绿」的第四例（前三例：`display_name` 不同步、`_meta.json` 损坏、两段式）。修法：正则放宽到 `v?(\d+(?:\.\d+)+)`；**恰好三段**照旧比对、不一致报 ERROR；**段数≠3** 报 NOTE 非阻断；**完全无版本数字**才真正跳过。新增 `notices` 通道，`main()` 在 `[OK]` 之前打印 `[NOTE]`，**exit code 不变**——`[OK] 五项检查全部通过` 与 `[NOTE] 判不了` 必须能同时出现且不互相冒充。`--self-test` 增第四组反例「两段式 NOTE」，独立成组（断言 `exit=0` 且输出 `[NOTE]`，方向与前两组相反，混在一起会互相掩盖）。
- **技能自检 v1.15.4（2026-11-01 00:50，修护栏静默停摆）**：`_meta.json` 损坏（非法 JSON / 空文件）时，3b 与 3c 两段被 `except Exception: pass` 同时吞掉，**自检输出 `[OK] 五项检查全部通过`**——文件删干净了会报错、文件坏掉了却放行，同一道防线只堵了一半。修法：两处 `pass` 改报 ERROR（「存在但无法解析」），并用 `meta_unreadable` 标志避免同一故障报两条；新增第三组反例「畸形 meta」进 `--self-test`。**三组毒标本实测**：截断 JSON → 报错、空文件 → 报错、合法但缺 `version` → 不误报。
- **工具链 v1.15.2（2026-10-31 23:35，纯修工具误判，不改书源语义）**：三处——
  ① `test_parse.py` 补 Legado 点号/冒号索引（`span.0`、`span.1:2:4`、`-1`）与 `tag.` 语法糖；原实现只有方括号索引，合法规则被 bs4 当 CSS 类名报 `Malformed class selector`，`tag.span` 更是被当未知标签名**静默返 0**；
  ② `validate_booksource.py` 新增 `check_verify_coverage()`：把「本地验不到却显示通过」的三类规则点名（`&&`/`||` 并联、`td.0,2` 混合索引、`@js:`/`<js>` 终结），**NOTE 级**——手机小说已真机通过却含 4 处并联，判 WARN 会让 `--strict` 无故失败；
  ③ `verify_booksource.py` POST 补 `Content-Type: application/x-www-form-urlencoded`（`curl_cffi` 传 str 不自动补，PHP `$_POST` 空 → **所有 POST 书源被误判成规则写错**）。
  **引擎侧独立复验**：点号索引 3/3 命中（实测 `.book_box tag.span.0@text` 等）、并联检测确实报 NOTE、Content-Type 补头在代码 L136-137 且带 dex 依据注释；`self_audit` 五项通过、`test_parse --self-test` 通过、`run_evals 59/59`。
  `SKILL.md`「输出契约」新增一条硬约束：**`NOTE` 非 0 时必须逐条交代未验字段与另验手段，禁止用「test_parse 全绿」概括**；只有 `NOTE=0` 才允许写「全部字段本地已验证」。

## 2026-10-26 更新

- **新增 `tools/b2/` + `docs/`：B2 真机引擎**。在纯 JVM 加载 Legado 3.25 APK 真实 `AnalyzeRule`，jsoup / js(Rhino) / xpath / jsonpath 四模式真机保真；零外部选择器 jar（全部类由 APK dex 经 dex2jar + enjarify 重导）、网络硬短路（隔离网络实测仍 12/12）。QA 独立复验全 PASS。
- **`tools/lint/booksource_lint.py` 新增 `strip_url_options()`**：抓取前剥离 `url,{...}` 请求选项，修掉「带 webView / method / body 的书源被误报抓取失败」的长期误报；self-test 8/8。
- **技能升级 v1.14.10**（全批次收口），发布包见 `releases/`。
- **坑点补 N8 / N9**：N8 = 正文只给一段 + "只支持手机浏览器" 实为**按 UA 分流**（先加手机 UA，别上 webView），并附 3.25 请求选项实证（`webView`/`webWait` 默认 1000ms，`webViewDelayTime` 不存在，`webViewUA` 改不了）；N9 = `java.timeFormat` 只吃时间戳，传日期字符串会崩掉整个目录区域。

阅读顺序建议：`LEGADO-书源调试知识库.md`（索引）→ `解析要点-核心引擎行为与实战坑点.md`（引擎行为）→ `cases/Legado_书源排错与实战经验_多站案例集.md`（排错实战）→ `tools/README.md`（要动手时）。

## 来源与版权

- 官方帮助文档: Legado(gedoor/legado) APK 3.25 内置 assets, 版权归原项目及作者
- 类索引/解析状态: 对 legado_app_3.25.apk 的 jadx 1.5.0 反编译(99.4%) + apktool 完整反汇编盘点得出
- 本仓库为学习研究用知识整理, 与 Legado 官方无隶属关系
