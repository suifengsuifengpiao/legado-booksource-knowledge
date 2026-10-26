# B2 真机引擎 harness

在**纯 JVM** 里加载 Legado 3.25 APK 的**真实** `io.legado.app.model.analyzeRule.AnalyzeRule` 解析类，用真机同款引擎跑书源规则——不是为了跑得快，是为了**解析结果和真机一致**。

## 能做什么

| 模式 | 保真度 | 说明 |
|---|---|---|
| jsoup（CSS） | 真机级 | 12/12 实测通过 |
| `@js:` / `<js>`（Rhino） | 真机级 | 5/5，含 `java.md5Encode` 等绑定 |
| xpath | 真机级 | 6/6，含属性轴/后代轴/父子轴 |
| jsonpath | 真机级 | 2/2 |

红线：**零外部选择器/Rhino jar**（全部类从 APK dex 提取）、**网络硬短路**（不发真实请求，`unshare -n` 隔离网络实测仍 12/12）。

## 前置条件（必须先准备）

本仓库**不包含**从 APK 转出的 jar（体积大且属第三方版权物），需要自己生成：

1. `dex2jar` 转 APK 的 4 个 dex → `classes.jar` / `classes2.jar` / `classes3.jar` / `classes4.jar`
2. `enjarify` 重导 `classes4.dex`（修复 dex2jar 对 ANTLR/jayway 枚举的损坏）→ `xpath-fix-enjarify.jar`
3. 以上文件放到 `/workspace/b2-work/`（路径见 `build-cp.sh` 里的变量，可改）

> 修复过程与根因见 `REMEDIATION_XPATH_JSONPATH.md`（dex2jar 把 `org.antlr.v4.runtime.*` 与 jayway 的脱糖类转坏，enjarify 重导才救活 xpath/jsonpath）。

## 怎么跑

```bash
bash build-cp.sh          # 拼 classpath（android-stub.jar + 4×classes*.jar + fix jar）
bash run.sh               # 跑默认样本（四区 12 规则 + xpath/jsonpath 探针）
```

单区调试：

```bash
java -noverify -Db2.home="$(pwd)" -cp "$(bash build-cp.sh):out" b2.B2Harness \
  --source 书源.json --sample-dir samples --region ruleToc
```

## 目录

| 路径 | 内容 |
|---|---|
| `src/b2/` | Java 源码：`B2Harness` / `RegionRunner` / `NetworkStub` / `RhinoEngine` / `JavaShim` / `DebugContract` |
| `android-stub/` | 最小 Android 桩（24 类，`build.sh` 可重建，`STUB_LIST.md` 记录范围） |
| `samples/` | 书源与页面样本 |
| `QA_REPORT.md` | QA 独立复验报告（全 PASS，路由 NoOne） |
| `OUTPUT_CONTRACT.md` | 输出契约：`{region,rule,mode,result,ok,note/errorPhase}` |
| `DIFF_REPORT.md` | 与旧「模拟层」结果比对 |

## 边界（诚实说明）

- **不联网**：只解析你注入的样本 HTML/JSON。真实抓取请在真机做。
- **Android 层是桩**：`Context/Log/Uri/Build` 等为自产 stub，解析行为不受影响，但不是真 Android Runtime。
- **不覆盖动态渲染**：需要执行 JS 才出内容的页面，它拿到的是原始 HTML，拿不到渲染后的 DOM。
