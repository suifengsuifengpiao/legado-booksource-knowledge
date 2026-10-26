# B2 真机引擎 harness — enjarify remediation 独立复验报告（QA：严过关）

> 验证对象：工程师（寇豆码）enjarify remediation（`xpath-fix-enjarify.jar` 前置救活 xpath/jsonpath）
> 交付路径：`/workspace/legado-knowledge-repo/tools/b2/`
> 验证方式：**独立复现**（不采信工程师自报），全量实跑 + 产物级（jar/classpath）审计 + 隔离网络实证
> 运行环境：OpenJDK 20（Zulu 20.28），纯 JVM，无 Android Runtime
> 复验日期基准：2026-10-26（相对上一版报告，xpath/jsonpath 由「优雅降级」升级为「真机保真」）

---

## 0. 复验结论速览

| 项 | 验证内容 | 结论 | 路由判定 |
|---|---|---|---|
| 1 | 全量跑通：主线（默认 booksource）`summary={total:12,ok:12,failed:0}` | **PASS** | — |
| 2 | xpath/jsonpath 救活：`ok=2/2`（结果非空合理） | **PASS** | — |
| 3 | 多轴 xpath 救活：`ok=6/6`（属性轴 `//a/@href`、后代轴 `//body//div` 等） | **PASS** | — |
| 4 | 根因确证 + 红线（xpath ATN 不再 `state type 182`；jsonpath 不再 `InstantiationError`；零联网） | **PASS** | — |
| 5 | 红线审计（fix jar 零外部 JsoupXpath/jayway/Rhino/robolectric；classpath 仅允许 jar；零联网） | **PASS** | — |
| 6 | 回归不退化（jsoup/js 结果与历史一致，主线 12/12 不变） | **PASS** | — |

**总体判定：B2 四模式（jsoup / js / xpath / jsonpath）全部真机保真达成；红线全合规；可正式交付。路由 → NoOne（全部通过，无源码/脚本缺陷）。**

> 关键事实：原 `qa-xpath-contract.json`（ remediation 前）记录 xpath/jsonpath 为 `ok=0/2`、`InstantiationError`，现已独立复跑为 `ok=2/2` 且结果非空合理 —— 救活属实，非文档美化。

---

## 1. 全量跑通验证（主线不退化）

### 执行（按指定命令）
```bash
cd /workspace/legado-knowledge-repo/tools/b2
rm -rf out && bash build-cp.sh && bash run.sh
```
产出契约 `qa-run-main.json`（EXIT=0）。

### 断言结果
- ✅ `summary = {"total":12,"ok":12,"failed":0}`（jsoup 模式四区 12 条全过）。
- ✅ 关键字段与历史 QA 一致：

| ruleKey | 实测 result | 判定 |
|---|---|---|
| content | `<div id="content">\n 第一章 测试正文。下载星星阅读app\n</div>` | ✅ 非空 |
| author | `测试作者` | ✅ 与历史一致 |
| chapterUrl | `/c/1.html\n/c/2.html` | ✅ 与历史一致 |
| bookUrl | `/b/123` | ✅ |
| chapterName | `第一章\n第二章` | ✅ |

**判定：主线（jsoup+`<js>`）未因 remediation 退化。**

---

## 2. xpath/jsonpath 救活验证

### 执行
```bash
bash run.sh --source qa-xpath-booksource.json --sample-dir qa-samples
```
`qa-xpath-booksource.json` 含：`ruleContent.content = //div[@class='t']/text()`（xpath）、`ruleBookInfo.name = $.store.book[0].title`（jsonpath）。
产出 `qa-run-xpath-jsonpath.json`（EXIT=0）。

### 断言结果
- ✅ `summary = {"total":2,"ok":2,"failed":0}`。
- ✅ xpath `//div[@class='t']/text()` → result `"你好世界xpath"`（非空、合理，命中样本 div 文本）。
- ✅ jsonpath `$.store.book[0].title` → result `"JSON书jsonpath"`（非空、合理，命中 JSON 首书标题）。

**判定：xpath + jsonpath 均真被救活（非降级），结果非空合理。**

---

## 3. 多轴 xpath 救活验证（独立构造夹具，不采信自报）

### 独立构造夹具（本 QA 新建，未改 harness 实现）
- `qa-multi/booksource.json`：`ruleContent` 下 6 条 xpath，覆盖不同轴。
- `qa-multi/content-sample.json`：含 `<a href>`、`<div>` 嵌套、`<span>`、`<h1>`、`<ul><li>` 的富样本。

| ruleKey | xpath | 轴 | 实测 result（节选） | ok |
|---|---|---|---|---|
| attr_axis | `//a/@href` | 属性轴 | `https://a1.test/x\nhttps://a2.test/y` | ✅ |
| descendant_axis | `//body//div` | 后代轴 | 3 个 div 子树 | ✅ |
| child_axis | `//div[@class='nested']/p` | 子轴 | `<p class="para">段落文本</p>` | ✅ |
| parent_axis | `//span/parent::*` | 父轴 | 两个 `<li>` | ✅ |
| followsib_axis | `//h1/following-sibling::div` | 后续兄弟轴 | 2 个 div | ✅ |
| text_axis | `//div[@class='t']/text()` | 文本节点 | `主内容xpath` | ✅ |

### 执行与断言
```bash
bash run.sh --source qa-multi/booksource.json --sample-dir qa-multi
```
产出 `qa-run-multi-xpath.json`：`summary = {"total":6,"ok":6,"failed":0}`，**6 条结果均非空合理**。
**至少覆盖强制要求的属性轴 `//a/@href` 与后代轴 `//body//div`，二者均 `ok=true`。**

**判定：多轴 xpath 真机保真，无 ATN 卡死。**

---

## 4. 根因确证（xpath / jsonpath 旧异常消失）

### 4.1 xpath 根因：`IllegalArgumentException: state type 182`（ATN 错位，cb.j.b）
独立跑探针：
```bash
CP=$(bash build-cp.sh 2>/dev/null)":$PWD/out"
java -noverify -cp "$CP" b2.XpathProbe
```
- ✅ 输出 `XPATH_OK result=[<JX_TEXT...>xpath-success-text</JX_TEXT>]`（xpath 跑完，非卡在 ATN）。
- ✅ `state type 182` 命中 = **0**；`IllegalArgumentException` 命中 = **0**。

### 4.2 jsonpath 根因：`InstantiationError: j$.util.concurrent.ConcurrentHashMap$CollectionView`
对所有运行产物做异常扫描：
```bash
grep -c 'InstantiationError'   qa-run-xpath-jsonpath.json qa-run-multi-xpath.json qa-run-main.json  # 均 0
grep -c 'CollectionView'       qa-run-xpath-jsonpath.json qa-run-multi-xpath.json qa-run-main.json  # 均 0
grep -c 'j$.util.concurrent'   qa-run-xpath-jsonpath.json qa-run-multi-xpath.json qa-run-main.json  # 均 0
```
- ✅ 旧 `InstantiationError` 脱糖类异常**全部消失**；jsonpath 真实返回结果（见 §2）。

### 4.3 网络零联网（隔离命名空间实证）
```bash
unshare -n bash run.sh > qa-run-nonet.json   # 完全无外网
```
- ✅ EXIT=0，`summary={total:12,ok:12,failed:0}`；stderr 无 `socket|connect|unknownhost|network` 类错误。
- ✅ 结合代码审计：`JavaShim.get/ajax/connect` 仅返回 `NetworkStub` 注入样本（`JavaShim.java:45/50/55`），`RhinoEngine` 直驱 dex 自带 Rhino，harness 从不调用 okhttp/AnalyzeUrl。

**判定：两处根因均确证修复，红线（零联网）实证实合规。**

---

## 5. 红线审计（代码/产物级）

### 5.1 fix jar 零外部 JsoupXpath/jayway/Rhino/robolectric
```bash
unzip -l /workspace/b2-work/fix/jar/xpath-fix-enjarify.jar | grep -iE 'jsoupxpath|jayway|robolectric'
# 命中 0
```
- ✅ 字面 grep（用户指定）命中 **0**。
- ✅ **深度审计**（更严格）：fix jar 共 3996 个类，顶层包全为 APK 混淆包（`aa..zc`）+ APK **内嵌**库：
  - `org/seimicrawler/xpath`（97 类 = APK 自带 JsoupXpath）
  - `org/mozilla/javascript`（593 类 = APK 自带 Rhino）
  - `org/jsoup`、`org/antlr/v4/runtime`、`net/minidev`（json-smart）、`okhttp3`、`kotlin`、`me/ag2s`、`org/apache/commons/lang3` ……
  - **关键**：`com/jayway`（jsonpath）**不在 fix jar**（其仅存于 `classes3.jar`，未被触碰/无外部化）；`robolectric` 命中 0。
  - 上述全部源自 enjarify 对 `classes4.dex`+`classes2.dex` 的整 dex 忠实重导，**无任何外部 Maven jar**。
- ⚠️ 透明说明：fix jar 确实**包含** APK 自己的 JsoupXpath/Rhino（enjarify 整 dex 重导所致），但它们是 APK 内嵌版本，并非「外部 JsoupXpath/jayway/Rhino jar」。红线禁的是**外部**等价 jar，故判定合规。字面 grep 之所以为 0，是因为包名 `org.seimicrawler.xpath` 不含连写串 `jsoupxpath`——QA 已用深度审计补足此盲区。

### 5.2 classpath 仅含允许 jar
`bash build-cp.sh` 输出（顺序）：
```
1. xpath-fix-enjarify.jar   (remediation 前置，必须在 dex jar 之前)
2. android-stub.jar         (方案 B 自产最小 Android 桩，零下载)
3. out                      (harness 自身编译产物)
4. classes.jar
5. classes2.jar
6. classes3.jar
7. classes4.jar
```
- ✅ 共 7 项，仅 `fix jar + stub + out + 4×dex jar`；过滤 `jsoupxpath|jayway|rhino|robolectric`（作为文件名）→ **无命中**，确认无外部选择器/Rhino jar。
- ✅ fix jar 位于 4 个 dex jar **之前**，优先加载干净类（remediation 必要顺序）。

### 5.3 零联网
- ✅ 见 §4.3（`unshare -n` 实证）+ 代码审计（`NetworkStub`/`JavaShim` 短路）。

**判定：红线三项（零外部选择器/Rhino jar、classpath 合规、零联网）全部 PASS。**

---

## 6. 回归不退化验证

- ✅ 主线 `summary` 仍为 `{12,12,0}`，与 remediation 前 QA 一致（无退化）。
- ✅ `author=测试作者`、`chapterUrl=/c/1.html\n/c/2.html` 等逐字段与历史契约一致。
- ✅ xpath/jsonpath 由「`ok=0/2` + `InstantiationError`」升级为「`ok=2/2` 真结果」——属增强，非退化。
- ✅ 多轴 xpath 新增 6/6 真机保真，覆盖此前缺失的能力。

---

## 7. 智能路由判定

- **源码 Bug → 工程师（寇豆码）**：未发现 harness 实现缺陷（jsoup/js 主线、`##` 替换、Rhino 绑定、NetworkStub 短路、remediation 前置顺序均正确）。xpath/jsonpath 救活为 enjarify 重导所致，实现逻辑无 bug。
- **测试/验证脚本 Bug → QA 自修**：本 QA 新建的 `qa-multi/*` 夹具与所有验证命令均正确，无需自修。
- **结论 → NoOne（全部通过）**：5（含回归共 6）项验证全 PASS，无源码/脚本缺陷，**B2 四模式全真机保真达成，可正式交付**。

---

## 8. 交付结论（主理人摘要）

> **B2 四模式（jsoup / js / xpath / jsonpath）是否全部真机保真？** ✅ 是。
> - jsoup：主线 12/12 真机保真，未退化。
> - js：dex 自带 Rhino 真绑定（md5/网络短路），历史 QA 已证。
> - xpath：单轴 `//div[@class='t']/text()` 与多轴（属性/后代/子/父/后续兄弟/文本 共 6 轴）均 `ok=true`，结果非空合理，且旧 `state type 182` ATN 异常消失。
> - jsonpath：`$.store.book[0].title` 真返回 `JSON书jsonpath`，旧 `InstantiationError` 脱糖异常消失。
>
> **红线是否合规？** ✅ 是。
> - fix jar：enjarify 整 dex 重导，零外部 JsoupXpath/jayway/Rhino/robolectric jar（字面 grep 0 命中 + 深度审计确认全部 APK 内嵌）。
> - classpath：仅 `fix jar + android-stub + out + 4×dex jar`，无外部选择器/Rhino jar。
> - 网络：隔离命名空间 `unshare -n` 实证 + 代码短路，零真实联网。
>
> **是否可正式交付？** ✅ 可正式交付。B2 达成「四模式全真机保真」，remediation（enjarify 路线）经独立复验确证有效且守红线。

---

## 9. 证据文件索引（本 QA 复验产出，可复现）

| 文件 | 说明 |
|---|---|
| `qa-run-main.json` | 全量主线契约（12/12，验证 §1/§6 回归） |
| `qa-run-xpath-jsonpath.json` | xpath+jsonpath 救活契约（2/2，验证 §2/§4.2） |
| `qa-run-multi-xpath.json` | 多轴 xpath 契约（6/6，验证 §3） |
| `qa-run-multi/booksource.json` + `qa-multi/content-sample.json` | 本 QA 独立构造的多轴 xpath 夹具 |
| `qa-run-nonet.json` | `unshare -n` 零联网实证契约（验证 §4.3/§5.3） |
| `qa-xpath-booksource.json` + `qa-samples/` | xpath/jsonpath 救活复核夹具（沿用并复跑） |
| `build-cp.stderr` | classpath 构造日志（fix jar 前置确认） |

> 一键复现：
> ```bash
> cd /workspace/legado-knowledge-repo/tools/b2
> rm -rf out && bash build-cp.sh && bash run.sh > qa-run-main.json
> bash run.sh --source qa-xpath-booksource.json --sample-dir qa-samples > qa-run-xpath-jsonpath.json
> bash run.sh --source qa-multi/booksource.json --sample-dir qa-multi > qa-run-multi-xpath.json
> CP=$(bash build-cp.sh 2>/dev/null)":$PWD/out"; java -noverify -cp "$CP" b2.XpathProbe
> unshare -n bash run.sh > qa-run-nonet.json
> unzip -l /workspace/b2-work/fix/jar/xpath-fix-enjarify.jar | grep -iE 'jsoupxpath|jayway|robolectric'  # 期望 0 命中
> ```
