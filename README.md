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

## 来源与版权

- 官方帮助文档: Legado(gedoor/legado) APK 3.25 内置 assets, 版权归原项目及作者
- 类索引/解析状态: 对 legado_app_3.25.apk 的 jadx 1.5.0 反编译(99.4%) + apktool 完整反汇编盘点得出
- 本仓库为学习研究用知识整理, 与 Legado 官方无隶属关系
