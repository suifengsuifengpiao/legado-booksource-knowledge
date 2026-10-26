# B2 harness 依赖盘点报告（T1）

> 配套：`b2-harness-design.md`、本目录 `build-cp.sh` / `run.sh`。
> 环境：OpenJDK 20（Zulu 20.28），纯 JVM，无 Android Runtime。

## 1. 运行期 classpath（单 flat，确定性顺序）

```
android-stub.jar : out(harness) : classes.jar : classes2.jar : classes3.jar : classes4.jar
```

- `android-stub.jar`：`android-stub/build.sh` 自产（方案 B 最小 Android 桩，24 类，零外部依赖）。
- `classes*.jar`：位于 `/workspace/b2-work/`，为 Legado 3.25 APK 经 dex2jar 2.4 转换产物（4 个 dex）。
- `out`：harness 自身编译产物。

`build-cp.sh` 自动拼装该 classpath；`run.sh` 先构建 `android-stub.jar` 再编译 harness 并运行。

## 2. 实际用到的 jar 与“legado 自带 vs 外部”

| jar | 路径 | 来源 | 是否外部 | 用途 |
|---|---|---|---|---|
| `android-stub.jar` | 本目录 `android-stub/` | **自产**（方案 B） | 否（无下载） | 补齐 android.* 框架类 |
| `classes.jar` | `/workspace/b2-work/` | dex2jar 产物（APK 自带） | 否 | 含 jsoup / JsoupXpath / jayway / **`android.support.v4.media.c`（混淆后的 jsoup 助手类）** / Glide 等 |
| `classes2.jar` | 同上 | 同上 | 否 | 部分实体 |
| `classes3.jar` | 同上 | 同上 | 否 | **核心**：`io.legado.app.model.analyzeRule.*`、`io.legado.app.data.entities.*`、`com.google.gson`（**已混淆**）、`com.bumptech.glide`、`org.mozilla.javascript`、`cn.hutool` |
| `classes4.jar` | 同上 | 同上 | 否 | 其余 |

### 红线核查（架构师红线）

- ✅ **无任何外部 Rhino / 选择器 jar**：`org.mozilla.javascript`（Rhino，577 类）、`org.jsoup`（276）、`org.seimicrawler.xpath`（JsoupXpath，97）、`com.jayway.jsonpath`（jayway，221）、`com.google.gson`（gson，101，**但已被混淆**）、`okhttp3`、`cn.hutool`、`kotlin.*` 全部随 4 个 dex jar 免费提供，classpath **未引入** `/workspace/booksource_lint_assets/` 下的任何 `jsoup-1.17.2.jar` / `JsoupXpath` / jayway 等。
- ✅ **网络硬短路**：harness 永不真实联网；`<js>` 规则中的 `java.get/ajax` 改走 `NetworkStub` 返回注入样本（见 `NetworkStub.java` / `JavaShim.java`）。

## 3. 关键事实与偏差（已实证）

1. **`com.google.gson.Gson` 已被混淆**：dex 内 `com/google/gson/` 存在 101 个类，但 `Gson` / `JsonParser` / `JsonArray` 等公开类已被重命名为 `a`/`c`/`d`…，无法 `new Gson()` 直接反序列化 `BookSource`。
   - **对策（设计 R5 退化路径）**：用真实 `BookSource` 无参构造 `new BookSource()` 承载解析（dex 真实类），规则串由 harness 自带零依赖 `Json` 解析器从书源 JSON 抽取后逐条喂给 `AnalyzeRule.getString`。保真度不受影响——跑的是真 `AnalyzeRule`，规则串来自真书源。
2. **`android.support.v4.media.c` 是真实 dex 类（非 android 框架）**：ProGuard 把某个 jsoup/内部助手类混淆进了 `android.support.v4.media` 包。初版曾误桩它（android-stub.jar 在 classpath 最前会**遮蔽**真类），导致 jsoup 解析 `NoSuchMethodError`。移除该桩后，dex 内真实类（在 `classes.jar`）正常提供 `l(String,String)` 等方法，jsoup 全绿。
   - **教训**：android 桩类若与 dex 内某个“伪装成 android 包”的混淆类同名，会因 classpath 顺序被遮蔽。本目录其余桩类（`android.text.TextUtils` / `android.os.Build` / `android.content.Context` 等）经核查**不与任何 dex 真实类同名**。
3. **dex2jar 转换产物需 `-noverify`**：部分 dex2jar 转换类存在栈图（stackmap）校验产物，`java` 默认校验会抛 `VerifyError`；以 `-noverify`（并 `-Xverify:none`）关闭校验后正常加载。dex 类本身为真实 Legado 3.25 解析类，非伪造。

## 4. `Class.forName(AnalyzeRule)` 校验

```bash
java -noverify -cp "$(build-cp.sh)" \
  -e 'Class.forName("io.legado.app.model.analyzeRule.AnalyzeRule"); System.out.println("OK")'
# 输出：OK
```

`AnalyzeRule` 在仅含 android-stub + 4 个 dex jar 的 classpath 下可成功加载（其构造器仅依赖 `RuleDataInterface`/`BaseSource` 与少量 android 类，后者由 stub 补齐）。
