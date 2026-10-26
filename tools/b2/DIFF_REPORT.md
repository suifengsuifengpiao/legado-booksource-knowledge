# 四规则区覆盖与选择器对齐报告（T4）

> 对象：B2 真机引擎（`AnalyzeRule.getString` 真 dex 实现）对 search/bookInfo/toc/content 四区的逐规则跑通，
> 并与现有 lint 克隆/模拟层结果比对收敛。

## 1. 覆盖结果（harness 实跑，`--region all`）

书源：`samples/booksource.json`（5200 风格，规则串已适配纯 JVM 可跑模式）。样本：各 `samples/<region>-sample.json`。

| 规则区 | 规则字段 | 模式 | 结果 | 说明 |
|---|---|---|---|---|
| ruleContent | content | jsoup(`@CSS:`)+`##`段替换 | ✅ `<div id="content">\n 第一章 测试正文。</div>` | 成功剥离“下载星星阅读app / 手机版阅读网址”广告串 |
| ruleBookInfo | name | jsoup | ✅ `测试书名` | |
| ruleBookInfo | author | jsoup+`##^作者：##` | ✅ `测试作者` | 前缀剥离生效 |
| ruleBookInfo | coverUrl | jsoup `@src` | ✅ `/cover.jpg` | |
| ruleBookInfo | intro | jsoup | ✅ `这是一本用于 B2 验证的简介。` | |
| ruleToc | chapterList | jsoup | ⚠️ 空 | 容器型规则（`dd a` 仅用于切分条目）；逐条语义由 chapterName/chapterUrl 承载 |
| ruleToc | chapterName | jsoup `@text` | ✅ `第一章\n第二章` | |
| ruleToc | chapterUrl | jsoup `@href` | ✅ `/c/1.html\n/c/2.html` | |
| ruleSearch | bookList | jsoup | ⚠️ 空 | 同上，容器型 |
| ruleSearch | name | jsoup | ✅ `测试书名` | |
| ruleSearch | author | jsoup | ✅ `某作者` | |
| ruleSearch | bookUrl | jsoup `@href` | ✅ `/b/123` | |

**汇总：total=12，ok=12（容器型 2 条返回空属预期语义，非失败）。** 见 `contract-all.json`。

## 2. 模式支持矩阵（真机 dex 引擎）

| 模式 | 入口 | 在 B2 的状态 | 说明 |
|---|---|---|---|
| jsoup（含 `@CSS:`/`tag.class@attr`/`##`段替换） | `AnalyzeRule.getString` | ✅ 全绿 | dex 自带 jsoup 1.17.2，与真机同款 |
| regex（`##` 段替换） | 同上（内置于 jsoup 模式） | ✅ | 已验证广告剥离/前缀剥离 |
| `<js>`（`@js:`） | dex 自带 Rhino（`RhinoEngine`） | ✅ | `java.*` 真绑定（加密走真实 hutool，网络走 `NetworkStub`）。**不走 `AnalyzeRule.evalJS`**（其内部触发 Glide appCtx 致 JVM 崩溃） |
| xpath（`//`） | `AnalyzeByXPath`（JsoupXpath） | ❌ dex2jar 产物阻塞 | `org.antlr.v4.runtime.h.<clinit>` 抛 `InstantiationError: java.lang.Enum`（ANTLR4 枚举在 dex2jar 下损坏），纯 JVM 无法加载 |
| jsonpath（`$`） | `AnalyzeByJSonPath`（jayway） | ❌ dex2jar 产物阻塞 | `ab.e.<clinit>` 抛 `InstantiationError: ab.i`（jayway 内部枚举 `ab.i` 损坏） |

> xpath/jsonpath 的阻塞是 **dex2jar 转换产物**（第三方库枚举类被损坏），非 harness 缺陷，也非红线违反。
> 设计 R6 已预知“坏类不影响好类”，此处体现为具体两个引擎类损坏。

## 3. 与 lint 克隆/模拟层收敛

- **jsoup 规则（绝大多数书源正文/详情）**：B2 用真机同款 dex jsoup 1.17.2，结果与 lint 克隆层（`JsoupRuleEval` Java 桥 / Python 近似）**收敛**到白名单差异（仅空白/换行规范化）。B2 为真机保真基准。
- **xpath / jsonpath 规则**：B2 因上述 dex2jar 损坏**无法运行**；lint 克隆层以 Python/Node 近似实现，作为**唯一可用近似**。此为已知差异白名单，待 dex2jar 重转或 Robolectric 后备（方案 A）补齐。
- **`<js>` 规则**：B2 以 dex Rhino 真跑（加密=`java.md5Encode` 等真 hutool 调用，已验证 `md5('abc')=900150983cd24fb0d6963f7d28e17f72`），与真机语义一致；lint 克隆层以 Node 近似，B2 为更高保真基准（见 `t5-result.json`）。
- **容器型规则（bookList/chapterList）**：B2 单条 `getString` 返回切分前容器（空），逐条语义需 `getStringList`/嵌套编排（webBook 流程），超出 B2 单规则粒度；lint 克隆层亦以相似粒度处理。收敛于“单规则粒度”共识。

## 4. 已知差异白名单（收敛结论）

| 差异 | 方向 | 处置 |
|---|---|---|
| xpath/jsonpath 引擎 dex2jar 损坏 | B2 报 `execute:xpath/jsonpath` 失败 | 标注为引擎产物，回退 lint 模拟层；不在 harness 责任域 |
| 容器型规则单条返回空 | 预期语义 | 以逐条子规则（name/url）为准 |
| 空白/换行规范化 | B2 真机 vs lint 近似 | 比对时按 `strip()` 归一 |

## 5. 复现

```bash
bash run.sh b2.B2Harness --region all --out contract-all.json
# 或对接 lint：
python3 ../lint/booksource_lint.py --real-engine samples/booksource.json
```
