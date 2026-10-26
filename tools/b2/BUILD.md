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

### 6.3 隔离网络复核（可选，证明零联网）

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
| `VerifyError` / 栈图校验失败 | dex2jar 产物特性 | 运行时加 `-noverify`（`run.sh` 已带） |
| 只要 jsoup 就够、xpath 也用不上 | 可以不前置 fix jar | 但 `xpath`/`jsonpath` 规则会优雅失败（不崩溃） |

---

## 8. 耗时与体积参考

| 项 | 实测 |
|---|---|
| dex2jar 转 4 个 dex | 约 2~4 分钟 |
| enjarify 重导 classes4+classes2 | 约 3~6 分钟（含 Python 3.11 兼容修补，首次约 15 分钟） |
| 编译 harness | 约 5 秒 |
| 运行时 jar 合计 | 约 31MB（classes 9.6 + 0.75 + 11.7 + 4.6 + fix 4.8） |
