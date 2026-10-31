# Legado 3.25 书源开发与调试知识库

面向 Legado(阅读3.0) 书源制作、调试、APK 行为核对的跨 AI 知识库。
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
| `releases/` | **发布物（四件，按需取）**：<br>① **`legado-tools_v1.14.10.zip`（2.5MB）— 静态校验工具，解压即用**：15 个脚本 + `jsoup_eval/`（含 jar）+ `lint/` + **`AI-USAGE.md`（给其他 AI 的下载与使用指引）**。直链：`https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-tools_v1.14.10.zip`<br>② **`legado-tools-b2-runtime_v1.14.10.zip`（27MB）— B2 真机引擎运行时，解压即跑**：APK 转出的 4 个 `classes*.jar` + `xpath-fix-enjarify.jar` + 已编译 harness（`b2-out/`）+ `android-stub.jar` + **`rhino-resources.jar`（Rhino 本地化资源，dex2jar 会丢，缺了 JS 报错会被 MissingResourceException 盖住）** + `BUILD.md`（从零重建步骤）+ 源码。直链：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.14.10-b2.5/legado-tools-b2-runtime_v1.14.10.zip`<br>③ **`legado-booksource-debug_v1.14.10.skill`** — 书源工坊技能包，装到 `~/.codebuddy/skills/legado-booksource-debug/` 后本会话当场可用。直链：`https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-booksource-debug_v1.14.10.skill`<br>④ **`legado-booksource-debug_v1.15.0.skill`** — 技能包（2026-10-31）：3.25 `@html` 语义纠偏（删 script/style 后取**单条** outerHtml，≠ innerHTML）、新增 `all` 指示符（不删 script）、`test_parse` 末段 html/all 强制走真 Jsoup 通道、evals 新增「正文藏在 script 里」夹具 + 4 条 golden。**二进制不入 git（P0-4 裁决），走 Release**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.0/legado-booksource-debug_v1.15.0.skill` |

## 2026-10-31 更新

- **技能升级 v1.15.0**：`@html` 语义纠偏 —— 3.25 的 `AnalyzeByJSoup.getResultLast` 会先 `select("script").remove()` + `select("style").remove()` 再取 `outerHtml()`，**与 innerHTML 不同**；正文藏在 `<script>document.writeln(...)</script>` 的站点用 `@html` 会把正文删干净。新增 `all` 指示符（直接 `outerHtml()`，不删 script）。工具链三处同步（`JsoupRuleEval.java` / `test_parse.py` / evals golden），**铁律 27** 入库。全套回归 59/59 + equiv 19/19。
- **引擎侧独立复核（2026-10-31）**：对 `legado_app_3.25.apk` 定向反编译 `io.legado.app.model.analyzeRule.AnalyzeByJSoup`，确认上述 `html`/`all` 分支原文；并用构造的「正文在 script 里」页面本地实测 —— `#txt@html` 输出 97 字符（script 全删）、`#txt@all` 输出 273 字符（2 个 script 保留）。**本条不是转述，是原文 + 实测双证**。
- **新增 3 站档案**：百草露（正文脚本 Base64 + 章节分页跨章陷阱）、手机小说（搜索字节闸 + 限频 cookie）、八叉书库（接口型正文 + Rhino 跨语言两坑）。
- **坑点补遗 N10–N13**：`@html` 删 script / 分页变量跨章 / 搜索字节闸 / `Packages.java` 污染。

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
