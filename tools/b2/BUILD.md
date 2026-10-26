# BUILD.md — B2 运行时从零构建（操作视角）

> 这份文档回答「**怎么做**」，不是「为什么」。
> 讲原理的复盘在 `REMEDIATION_XPATH_JSONPATH.md`，两篇配合看：先照本文把环境跑起来，出问题再翻那篇。

---

## 0. 环境要求

| 组件 | 版本（实测通过） | 用途 |
|---|---|---|
| JDK | **OpenJDK 20**（Zulu 20.0.x） | 编译/运行 harness |
| Python | 3.11（3.9+ 应可） | 跑 enjarify |
| dex2jar | **v2.4**（`dex-tools-v2.4`） | dex → jar |
| enjarify | google/enjarify master（2017 版） | classes4/classes2 干净重导 |
| Legado APK | **3.25**（md5 `7c5ab9dfa751f58b8ef0220ae001d619`） | 唯一的类来源 |
| unzip / zip | 任意 | 解包打包 |

内存建议 ≥ 4GB（`classes3.dex` 11MB，dex2jar 吃内存）。

---

## 1. 从 APK 提取 dex

```bash
mkdir -p b2-work/dex
unzip -o -q legado_app_3.25.apk 'classes*.dex' -d b2-work/dex
ls -l b2-work/dex
# 预期 4 个：classes.dex 8.6MB / classes2.dex 684KB / classes3.dex 9.3MB / classes4.dex 4.2MB
```

---

## 2. dex2jar 转 4 个 jar

```bash
cd dex-tools-v2.4
chmod +x *.sh bin/*.sh

for n in classes classes2 classes3 classes4; do
  bash d2j-dex2jar.sh -o ../b2-work/$n.jar ../b2-work/dex/$n.dex
done
```

产物（`b2-work/`）：`classes.jar` 9.6MB、`classes2.jar` 755KB、`classes3.jar` 11.7MB、`classes4.jar` 4.6MB。

**JDK 20 直接可用**，不需要降级 JDK（dex2jar 2.4 在这版 JDK 上实测正常）。

---

## 3. enjarify 重导 classes4 + classes2（**关键步骤**）

dex2jar 会转坏两处，必须用 enjarify 覆盖：

| 损坏点 | 症状 |
|---|---|
| `org.antlr.v4.runtime` / xpath 引擎 `cb` 包的 **ATN 反序列化器** | `IllegalArgumentException: state type 182` |
| 脱糖 JDK 类 `j$.util.concurrent.ConcurrentHashMap` | `InstantiationError: j$.util.concurrent.ConcurrentHashMap$CollectionView`（抽象类被当实现 new） |

```bash
cd enjarify-master

# Python 3.11 兼容：enjarify 是 2017 年的代码，直接跑会报
#   from collections import Mapping  →  改为 collections.abc
# 按报错逐个修（一般是 collections 导入 + 少量 str/bytes 处理），改完先验证：
python3 enjarify.py -h

# 重导（两个 dex 都要，classes2 里是 j$/util/concurrent 脱糖包）
python3 enjarify.py ../b2-work/dex/classes4.dex -o ../b2-work/fix/enjarify-classes4.jar
python3 enjarify.py ../b2-work/dex/classes2.dex -o ../b2-work/fix/enjarify-classes2.jar

# 合并成前置覆盖 jar（放在 4 个 dex jar 之前加载）
mkdir -p ../b2-work/fix/jar ../b2-work/fix/merged
cd ../b2-work/fix/merged && unzip -oq ../enjarify-classes4.jar && unzip -oq ../enjarify-classes2.jar
cd .. && jar cf jar/xpath-fix-enjarify.jar -C merged .

# ⚠️ 必须校验完整性（2026-10-26 踩过：只合并了 33 个 j$/util 类，实跑报
#    NoClassDefFoundError: j$/util/Collection$-EL）
unzip -l jar/xpath-fix-enjarify.jar | tail -1                      # 类总数应 ≈4507
unzip -l jar/xpath-fix-enjarify.jar | grep -c 'j\$/util/'         # 应 ≈418
```

产物：`b2-work/fix/jar/xpath-fix-enjarify.jar`（约 4.8MB）。

> 为什么合并：enjarify 产出的 classes4 已含干净的 `org/antlr/**` 与 `cb/**`，classes2 含干净的 `j$/util/concurrent/**`；两者要**同一个 jar 一起前置**，否则会出现"一半干净一半脏"的类加载分歧。

---

## 3.5 提取 Rhino 本地化资源（**必需，最容易漏**）

**dex2jar 只转 class，会丢掉 jar 内所有非 class 资源。** Rhino 一旦要报错就读
`org/mozilla/javascript/resources/Messages.properties` 做本地化，缺了它：

```
任意 @js: 规则出错 → MissingResourceException: Can't find bundle for base name
                    org.mozilla.javascript.resources.Messages
```

真正的 `TypeError` / `ReferenceError` 被彻底盖住，排查方向直接被带偏（会以为是 harness 坏了）。

```bash
bash make-rhino-res.sh                      # 默认读 /workspace/legado_app_3.25.apk
# 或
bash make-rhino-res.sh /path/to/legado_app_3.25.apk ./rhino-resources.jar
```

产物 20KB，`build-cp.sh` 会自动把它拼进 classpath（变量 `RHINO_RES_JAR` 可覆盖）。

**验证修复是否生效**——跑一个必然出错的 JS：

```bash
cat > /tmp/T.java <<'EOF'
import org.mozilla.javascript.*;
public class T {
  public static void main(String[] a) {
    Context cx = Context.enter();
    try { cx.evaluateString(cx.initStandardObjects(), "null.foo", "t", 1, null); }
    catch (Throwable e) { System.out.println(e.getClass().getSimpleName() + ": " + e.getMessage()); }
    finally { Context.exit(); }
  }
}
EOF
javac -cp "$(bash build-cp.sh)" -d /tmp /tmp/T.java && java -cp "$(bash build-cp.sh):/tmp" T
```

- ❌ 没修：`MissingResourceException: Can't find bundle for base name ...`
- ✅ 修好：`EcmaError: TypeError: Cannot read property "foo" from null (t#1)`

---

## 3.6 JS 作用域绑定（**缺一个就 ReferenceError**）

真机 `AnalyzeRule.evalJS` 的作用域变量（dex 字符串常量实证）：

| 变量 | 含义 | harness 取值 |
|---|---|---|
| `result` | **上一步结果；规则首段时为当前内容（mContent）** | 传入当前内容 |
| `baseUrl` | 当前 URL | 样本 URL |
| `source` | BaseSource 对象（真机）；harness 兼容为样本内容 | 内容 |
| `src` | 请求返回的源码 | 内容 |
| `title` / `nextChapterUrl` | 章节标题 / 下一章 URL | 空串 |
| `cookie` / `cache` / `book` / `chapter` | 对应对象 | null（**存在**，不是 undefined） |
| `java` | 当前类扩展（真机即 `AnalyzeRule` 自身，此时**已 setContent(当前页)**） | `JavaShim`；js 分支已对 `AnalyzeRule` 做 `setContent(当前内容)` |

两条铁律：

1. **名字必须存在**。真机无值时为 `null`；"不存在"是 `ReferenceError`，而书源普遍写 `''+result`、`result || ''`，一崩就是整条规则失败。
2. **`result` 初值 = 当前内容**。证据：黄金屋 `ruleToc.nextTocUrl = @js:(function(){var h=''+result,u=''+baseUrl,...` —— 它拿 `result` 去正则匹配目录页 HTML 找"下一页"。若按 null 处理，`''+null` = `"null"`，永远匹配不到。
3. **`java.getString(rule)` 依赖 `setContent`**。真机里 `java` 就是 `AnalyzeRule` 本身，且求值时已 `setContent(当前页)`；harness 必须同样先 `setContent(当前内容)`，否则 `java.getString('#x@href')` 会**静默返回空**（不报错，比报错更危险——会误判"规则没问题"）。
   > 2026-10-26 实证：猫扑 `nextContentUrl = @js:java.getString('#pb_next@href')`，补 setContent 前恒为空，补后返回 `/1360294/105767659/2.html`，与真机 `/737/22729/2.html` 同形态。

---

## 4. 目录布局（构建机）

```
/workspace/b2-work/
├── dex/classes.dex classes2.dex classes3.dex classes4.dex
├── classes.jar classes2.jar classes3.jar classes4.jar
└── fix/
    ├── enjarify-classes4.jar
    ├── enjarify-classes2.jar
    └── jar/xpath-fix-enjarify.jar
```

`tools/b2/build-cp.sh` 默认就按这个布局取，路径可用环境变量覆盖：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEX_DIR` | `/workspace/b2-work` | 4 个 classes*.jar 所在目录 |
| `FIX_JAR` | `/workspace/b2-work/fix/jar/xpath-fix-enjarify.jar` | 前置覆盖 jar |
| `STUB_JAR` | `<b2>/android-stub/android-stub.jar` | Android 桩 |
| `OUT_DIR` | `<b2>/out` | harness 编译输出 |

---

## 5. 编译并运行

```bash
cd tools/b2
bash run.sh          # 内部：build android-stub → 编译 src → 运行 B2Harness
```

classpath 顺序（`build-cp.sh` 输出，**不能改**）：

```
<FIX_JAR> : <STUB_JAR> : <OUT_DIR> : classes.jar : classes2.jar : classes3.jar : classes4.jar
```

**顺序错了会怎样**：`xpath-fix-enjarify.jar` 若排在 4 个 dex jar 之后，JVM 会先命中 dex2jar 的脏类，xpath 立刻回到 `state type 182`，jsonpath 回到 `InstantiationError`。这是最容易复发的坑。

---

## 6. 验证（怎么确认环境是好的）

### 6.1 主回归：四区 12 规则

```bash
cd tools/b2 && bash run.sh 2>&1 | grep -o '{"engine".*'
```

**期望**：

```json
"summary": {"total": 12, "ok": 12, "failed": 0}
```

### 6.2 xpath / jsonpath 探针

```bash
java -noverify -Db2.home="$(pwd)" -cp "$(bash build-cp.sh):out" b2.XpathProbe
```

**期望**：xpath 多轴用例 6/6、jsonpath 2/2 全部 `ok=true`。这两个探针是判断"enjarify 是否真的救活了"的唯一硬指标——主回归 12 条全是 jsoup 模式，**不覆盖** xpath/jsonpath。

### 6.3 JS 绑定自检（**必跑**，2026-10-26 因漏检吃过亏）

```bash
java -noverify -Db2.home="$(pwd)" -cp "$(bash build-cp.sh):out" b2.JsBindingCheck
```

**期望**：`cases` 全 `match=true`（当前 10 条）。

覆盖：`java.md5Encode` / `base64Encode` / `base64Decode` 回环 / `java.get` 硬短路 / `source` / **`result`（初值=内容、传值、null 安全）** / 其余绑定存在性（`src/title/cookie/book/chapter/cache/nextChapterUrl`）。

> 为什么必须跑：主回归 12 条全在 jsoup 模式，**完全覆盖不到 JS 绑定**。曾经 12/12 全绿但 `result` 未绑定，直到拿真实书源（黄金屋 `nextTocUrl`）才暴露。

### 6.4 隔离网络复核（可选，证明零联网）

```bash
unshare -n bash run.sh 2>&1 | grep -o '{"engine".*'
```

**期望**：仍 `ok=12`（`NetworkStub` 硬短路，不发真实请求）。

---

## 7. 已知坑速查

| 现象 | 判定 | 处置 |
|---|---|---|
| `state type 182` / ANTLR ATN 反序列化失败 | xpath 引擎被 dex2jar 转坏 | 确认 `FIX_JAR` 前置且 jar 内有 `cb/j.class`；可用 `javap -p -c` 对照 |
| `InstantiationError: ...ConcurrentHashMap$CollectionView` | 脱糖 JDK 类被转坏 | 确认 `xpath-fix-enjarify.jar` 含 `j$/util/concurrent/*`（来自 classes2） |
| `NoClassDefFoundError: android/...` | 桩缺类 | 补 `android-stub/src`，重跑 `android-stub/build.sh` |
| `MissingResourceException: Can't find bundle for base name org.mozilla.javascript.resources.Messages` | **dex2jar 丢了 Rhino 的非 class 资源** | 跑 `make-rhino-res.sh` 生成 `rhino-resources.jar`，确认它在 classpath 里（§3.5） |
| `NoClassDefFoundError: j$/util/Collection$-EL`（或其它 `j$/util/*`） | **enjarify 合并 jar 不完整**：只把部分类合进去（实测只剩 33 个 `j$/util/*`，应 418 个），desugar 合成类缺失 | 重新**完整**合并 `enjarify-classes4.jar` + `enjarify-classes2.jar`（先解 4 再解 2，2 覆盖同名），按 §3 末尾两条命令校验类总数≈4507、`j$/util/*`≈418 |
| `ReferenceError: "result" is not defined` | **JS 作用域没绑 `result`**（真机绑定清单：`source/baseUrl/result/chapter/nextChapterUrl/book/cookie/cache/title`） | 按 §3.6 绑全；**注意真机语义：规则首段的 `result` 初值就是当前内容（mContent）**，不是 null |
| `TypeError: Cannot find function getString in object b2.JavaShim` | harness 的 `java` 垫片缺方法（真机 `java` 是 `AnalyzeRule`，方法全有） | 已修：`JavaShim` 转发 `getString(String)` / `getString(String,Object)`，并在 js 分支补 `AnalyzeRule.setContent`（否则返回空） |
| `java.getString(...)` 恒返回空（不报错） | js 分支没给 `AnalyzeRule` 设当前内容 | 已修（同上）。若是自建 harness，记得先 `analyzeRule.setContent(内容)` 再 eval |
| `VerifyError` / 栈图校验失败 | dex2jar 产物特性 | 运行时加 `-noverify`（`run.sh` 已带） |
| `ExceptionInInitializerError: (message 为空)` | 该异常 `getMessage()` 恒为 null，只取 SimpleName+Message 会把根因吞掉 | 已修：harness 递归展开 cause 链 + 各层首帧；根因通常是 next row |
| `IllegalStateException: appCtx has not been initialized`（被 EIIE 包裹） | 规则触发了依赖 Android appCtx 的路径（Glide 静态初始化） | **环境限制，非书源问题**；输出会带 note 明确标注。可试 `-Db2.injectAppCtx=true`，但实测会触发 JVM SIGSEGV，默认关闭 |
| 连锁 `NoClassDefFoundError: Could not initialize class ...` | 某类静态初始化已失败，后续访问必然失败 | 看同批次**最早**那条 `ExceptionInInitializerError` 的 cause，别逐条查 |
| `SelectorParseException: String must not be empty`（规则形如 `..xxx`） | **`..` 不是 Legado 语法**（真机 `AnalyzeRule`/`RuleAnalyzer` 均无预处理，dex 常量实证） | 书源笔误，改单点 `.xxx`。已实测 `.info_chapters@ul@li@a` 通过、`..info_chapters@...` 报错 |
| 只要 jsoup 就够、xpath 也用不上 | 可以不前置 fix jar | 但 `xpath`/`jsonpath` 规则会优雅失败（不崩溃） |

---

## 7.5 已知不可用边界：依赖 Android appCtx 的规则

部分书源规则（多为 `ruleBookInfo` / `ruleToc` 里用到 `@js:` 且触发 `BaseSource.getShareScope`）会让
Glide 做静态初始化 → 需要 Android `appCtx`。纯 JVM 下：

- **默认**：抛 `ExceptionInInitializerError`，cause 是 `IllegalStateException: appCtx has not been initialized`。
  harness 会输出 **note: 【环境限制·非书源问题】**，并给出定位信息；
- **`-Db2.injectAppCtx=true`**：注入 `B2Context` 后能往下走，但实测在 Glide 深处触发
  **JVM SIGSEGV**（`JfrResolution::on_runtime_resolution`，dex 转换类的畸形字节码所致），
  比可捕获异常更糟，故默认关闭。

**结论**：这类规则在 B2 上验不了，必须在真机确认；B2 对它们的价值是"**告诉你这不是书源写错**"。

---

## 8. 耗时与体积参考

| 项 | 实测 |
|---|---|
| dex2jar 转 4 个 dex | 约 2~4 分钟 |
| enjarify 重导 classes4+classes2 | 约 3~6 分钟（含 Python 3.11 兼容修补，首次约 15 分钟） |
| 编译 harness | 约 5 秒 |
| 运行时 jar 合计 | 约 31MB（classes 9.6 + 0.75 + 11.7 + 4.6 + fix 4.8） |
