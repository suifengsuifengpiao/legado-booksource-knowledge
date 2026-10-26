# 输出契约（T6 / DebugContract）

> 类：`b2.DebugContract`（`DebugContract.java`）。所有 JSON 由 harness 自带零依赖 `b2.Json` 序列化。
> 用途：把逐规则解析结果汇总为可机器消费的契约，供 `booksource_lint.py --real-engine` 或调试器消费。

## 1. 顶层结构

```json
{
  "engine": "legado-dex-real",
  "engineVersion": "Legado 3.25 / dex 4-jar (OpenJDK 20, -noverify)",
  "bookSource": "<书源名或源文件路径>",
  "summary": { "total": 12, "ok": 12, "failed": 0 },
  "rules": [ { ...RuleResult... } ]
}
```

| 字段 | 含义 |
|---|---|
| `engine` | 固定 `legado-dex-real`：标识由真机 dex `AnalyzeRule` 产出（区别于 lint 克隆层） |
| `engineVersion` | 引擎版本与运行环境 |
| `bookSource` | 书源名（`bookSourceName`）或源文件路径 |
| `summary.total/ok/failed` | 规则总数 / 成功数 / 失败数 |
| `rules` | 逐规则结果数组（见下） |

## 2. RuleResult（逐规则单元）

```json
{
  "region": "ruleContent",
  "ruleKey": "content",
  "rule": "@CSS:div#content@html##下载星星阅读app[^<]*(?:<br\\s*/?>\\s*)+|\\s*手机版阅读网址[^\\n]*##",
  "mode": "jsoup",
  "result": "<div id=\"content\">\n 第一章 测试正文。</div>",
  "ok": true,
  "note": "dex-Rhino + java.* 真绑定(加密走真实hutool, 网络走NetworkStub)"
}
```

| 字段 | 含义 |
|---|---|
| `region` | 规则区：`ruleContent` / `ruleBookInfo` / `ruleToc` / `ruleSearch` |
| `ruleKey` | 规则字段名：`content` / `name` / `author` / `chapterList` / `bookUrl` … |
| `rule` | 原始规则串（未改写） |
| `mode` | 模式：`jsoup` / `xpath` / `jsonpath` / `js`（由 `RegionRunner.detectMode` 按语法自动识别，**无 mask 参数**） |
| `result` | `ok=true` 时的解析结果文本 |
| `ok` | 是否成功产出 |
| `note` | `ok=true` 时的备注（如 js 模式说明绑定来源） |
| `errorPhase` | `ok=false` 时的失败阶段：`execute:jsoup` / `execute:js` / `sample` |
| `error` | `ok=false` 时的异常类名 + 消息（如 `InstantiationError: java.lang.Enum` 标注 xpath 引擎 dex2jar 损坏） |

> **errorPhase 区分「桩缺失」vs「规则空取」**：`sample`=缺样本页；`execute:<mode>`=引擎执行期异常（可据异常类判断是否 dex2jar 产物，如 `InstantiationError: java.lang.Enum` 即 xpath ANTLR 枚举损坏）。

## 3. T5（JS 绑定）契约

`b2.JsBindingCheck` 输出独立契约（见 `t5-result.json`）：

```json
{
  "engine": "legado-dex-real",
  "engineVersion": "Legado 3.25 / dex 4-jar (OpenJDK 20, -noverify)",
  "check": "T5-JsBinding",
  "networkHardShortCircuit": true,
  "cases": [
    { "expr": "java.md5Encode('abc')", "actual": "900150983cd24fb0d6963f7d28e17f72",
      "expected": "900150983cd24fb0d6963f7d28e17f72", "match": true },
    { "expr": "java.get('https://api.test/x') [硬短路]", "actual": "{\"injected\":true,\"via\":\"NetworkStub\"}",
      "expected": "{\"injected\":true,\"via\":\"NetworkStub\"}", "match": true }
  ]
}
```

`networkHardShortCircuit: true` 证明 `java.get/ajax` 全程返回注入样本，**零真实联网**。

## 4. lint 集成语义（`--real-engine`）

`booksource_lint.py --real-engine` 调用 B2 产出上述契约，并将每条 `RuleResult` 作为
`REAL-ENGINE-RULE`（成功→INFO）/ `REAL-ENGINE-RULE-FAIL`（失败→WARN）注入 lint 报告；
若 B2 不可用（缺 dex jar / 桩不全 / JVM 崩溃），则发 `REAL-ENGINE-FALLBACK` 告警并**优雅降级回模拟层**，
不阻断既有 lint 流程。
