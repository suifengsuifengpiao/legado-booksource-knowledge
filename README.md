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
| `tools/` | 书源工具链 **v1.14.9**（脚本与技能 scripts/ 严格同步）：validate_booksource / test_parse / realcheck / bypass_cf / js_layer_check / reverse_crypto / reverse_font / webview_probe / l0_probe / make_probe_source / check_environment / self_audit / verify_booksource / legado_debug_bridge / fetch_page 共 15 个 + `jsoup_eval/`（.java/.class/jar 三件齐备）+ 清单 README；另含 `lint/booksource_lint.py`（知识库侧 lint 工具） |
| `cases/` | 实战层：多站案例集（兔九三/74xswz/3qdus/菠萝猫/速读谷/黄金屋/book55/纸间阅读/xs5200 9 站修复记录）+ **过盾专题（CF 盾物种分类：cookie壳页/GoEdge/五秒盾/Turnstile/altcha，Turnstile 三层死结）** + 黄金屋/book55/xs5200 站点档案 + 菠萝猫修复总结/站点档案 + 74xswz 书源逆向档案（签名机制演进：抽常量复刻→eval 官方 signJs；AES 目录接口；引擎坑记录）+ 格格党站点档案（零防护静态站基准样本：POST 搜索隐藏字段/目录全量内嵌判据/_N 页内分页三态断链/lazy 封面/搜索发现双列表结构） |
| `references-extra/` | API 文档层：Legado_3.25 书源编写参考、方法补集、pitfalls（铁律 26「真机才暴露的列表规则三坑」+ 2026-10-24 新坑补遗 N1~N7：桩书/壳页赋值形态/nextTocUrl尾页/searchUrl内联JS不执行/altcha可webJs点/webWait别配短/UA跳域）、site-patterns（含混合聚合站 SPA+CDN 四 type 样本、纯 JS 判下一页页码判据）、legend-js-api、parse-paths、booksource-schema、apk-3.25-verified-facts |
| `samples/` | 真机验证过的书源样本 7 份（黄金屋/无限小说网/5200小说网/话本小说/笔趣阁biquge/篱笆好文学/格格党） |

阅读顺序建议：`LEGADO-书源调试知识库.md`（索引）→ `解析要点-核心引擎行为与实战坑点.md`（引擎行为）→ `cases/Legado_书源排错与实战经验_多站案例集.md`（排错实战）→ `tools/README.md`（要动手时）。

## 来源与版权

- 官方帮助文档: Legado(gedoor/legado) APK 3.25 内置 assets, 版权归原项目及作者
- 类索引/解析状态: 对 legado_app_3.25.apk 的 jadx 1.5.0 反编译(99.4%) + apktool 完整反汇编盘点得出
- 本仓库为学习研究用知识整理, 与 Legado 官方无隶属关系
