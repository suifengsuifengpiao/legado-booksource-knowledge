# 标本：CJK 恒等 cmap 字体站型被判成「可能非加密字体」（假阴性）

> 归档：2026-11-13，随技能 v1.15.24 并入。
> 来源：书源侧排查 `www.aaawz.cc` 目录/正文「看得见却不认识」乱码时的实测（信件 `致引擎侧_v1.15.24_字体站型分型与三处判定失真修复_20261112.md`）。
> **证据等级（如实）**：本标本的实站字体样本、A/B 夹具、跨会话轮廓比对数字均**未随包**（会话级 woff2 无法固化，存书源侧会话沙箱 `/root/.codebuddy/backup_20261112_tools_v11524/`），引擎侧**未独立复现**。引擎侧独立验到的只有一层：`classify_font_obfuscation` 纯函数用**合成 cmap** 复算的六组真值表 6/6（纯逻辑自洽，不涉及实站样本）。不得把下面的数字当作引擎侧已交付证据。

## 一、症状（病在工具，不在书源）

正文抓到的是**正常汉字字形，但字形与 Unicode 不对应**——「看得见却不认识」。与常见「私有区乱码字符」是完全不同的两类站型：

| | 站型 A · 私有区码位重定向 | 站型 B · CJK 恒等 cmap + 字形轮廓替换 |
|---|---|---|
| cmap 特征 | 含 `U+E000~F8FF` 或 `≥U+F0000` 私有区码位 | **无私有区**；码位集中 CJK 基本区，字形名 `uniXXXX` 与码位恒等自洽 |
| 混淆发生在 | cmap 映射（码位 → 字形） | `glyf` 轮廓重绘 / 重排（码位本身没变） |
| 抓到的正文 | 私有区乱码字符 | 正常汉字字形，但字与 Unicode 不对应 |
| 规则层能否还原 | 能：`replaceFont` / `replaceRegex` 反推映射 | **不能**（3.25 `QueryTTF` 三条独立限制，见下） |

`reverse_font.py`（v1.15.23 及更早）只认站型 A：对该站字体返回 `private_codepoints: []`、无任何站型字段，`diagnose()` 报「检测到自定义字体但未发现私有区编码（可能非加密字体）」——把**真加密**判成「可能没加密」，是假阴性。误导方向是让人继续在规则层调 XPath / 换字体 API / 截正则，白费工。

## 二、根因：3.25 `QueryTTF` 的三条独立限制（合并进 §1.5 的能力边界）

依据 3.25 `classes*.dex` 内 `QueryTTF` 本体 + 抽取的 `QueryTTF.java` + fontTools 独立复算（判据标 L1）：

1. **格式**：构造函数按手写 TTF 表目录解析（sfntVersion / numTables / cmap / loca / maxp / glyf），**没有 woff2 解码分支**。站点只发 `wOF2` 时须外部转标准 TTF 才可能进这条通道。
2. **匹配口径**：`getGlyfById()` 把简单字形轮廓序列化成 `x,y|x,y` 坐标串；`glyphToUnicode` 是**精确 HashMap 匹配**（`glyphString → codepoint`），无容差、无相似度阈值。轮廓一旦重绘 / 重排 / 量化即失配。
3. **会话动态**：字形集合可锚在会话级 guard cookie（如 `reader_guard_id`）上，每次会话下发不同字库；固定字体表无法跨会话复用，正文与目录名共用同一套字形防护。

> 三条互相独立，任一成立即足以让「固定映射还原」失效；站型 B 通常三条同时成立。**规则层无解**，现实出路是浏览器阅读 / 换源 / 会话级字体人工导入（目录名仍不可救）。

## 三、修法（v1.15.24，只改判据不动既有分支）

新增 `classify_font_obfuscation(bestcmap, font_path)` 确定性纯函数，按四个量分三态：

- `pua_codepoint_redirect`：cmap 含私有区码位 → 既有分支，`rule_layer_recoverable=True`，可自动反推 `replaceRegex`；
- `glyph_shape_cjk_identity`：无私有区，且 `total≥2000` / CJK 基本区比例 `≥0.90` / `uniXXXX` 自洽比例 `≥0.90` → `rule_layer_recoverable=False`、**不生成假映射**、verdict 明写「规则层无法自动还原」；
- `no_font_obfuscation`：未检出上述两类特征（**不等于「没有加密」**）。

`analyze_font()` 追加 4 个字段、原字段一个不动；新增本地字体文件直通（`.woff2/.woff/.ttf/.otf`），覆盖 SPA/JSON 接口站 `font:{url:'/static/fonts/<hex>.woff2'}` 这类 HTML 里没有 `@font-face` 的形态。`FONT_RE` / `build_mapping` / `generate_replace_regex` 一行未改。

## 四、引擎侧独立核（这一层是实测，别和上面转述混）

从**实际发布的 `.skill` 解包**，用合成 cmap 复算纯函数六组真值表：

| 组 | 输入 | 期望 | 实测 |
|---|---|---|---|
| 站型 A | 私有区码位 + `uniXXXX` | `pua_codepoint_redirect` | PASS |
| 站型 B | CJK 基本区恒等 cmap（6763 条自洽） | `glyph_shape_cjk_identity` | PASS（`cjk_ratio=1.0` / `identity_ratio=1.0` / `recoverable=False`） |
| 普通 | 无混淆特征 | `no_font_obfuscation` | PASS |
| 反例① | 小字表（<2000 条） | 不误判站型 B | PASS |
| 反例② | 随机字形名（不自洽） | 不误判站型 B | PASS |
| 反例③ | 非 CJK 码位 | 不误判站型 B | PASS |

**6/6 通过**。这验的是「判据逻辑自洽、防假阳反例有效」，**不验**「实站字体确属站型 B」——后者需实站 woff2 样本，未随包。

## 五、写书源的人的操作顺序

1. 遇到「乱码 / 看不懂的汉字」→ 先取字体文件，跑 `reverse_font.py <字体文件>` 看 `obfuscation_type`。
2. `pua_codepoint_redirect` → 走 §1.5 既有 `replaceFont` / `replaceRegex` 通道。
3. `glyph_shape_cjk_identity` → **不要在规则层继续调 XPath、换字体 API 或截正则**；在书源 `bookSourceComment` 写明「规则层无法还原」，转浏览器阅读或换源。
4. 单份字体只能判站型；要判「会话动态」须取多份同站字体按字体站型文档 §4 的 fontTools 自包含片段复算轮廓集合。

## 六、与假绿标本的对照

| 标本 | 工具怎么错的 | 误导方向 |
|---|---|---|
| `标本_吾看书_工具三类失真回归.md` / 判定层假红 | 把正常书源判坏 | 改坏正确的书源 |
| `标本_汇总判定把SKIP与JS未验算进PASS_假绿.md` | 把「没验全」判成 `PASS` | 误以为全链路验过 |
| **本标本（字体站型假阴性）** | 把真加密判成「可能非加密字体」 | 在规则层继续做无用功 |

三者共同点：**都是「工具结论与物理事实不符」而非书源坏**。判定层出问题比单个规则写错更危险——它会系统性地把人带偏。
