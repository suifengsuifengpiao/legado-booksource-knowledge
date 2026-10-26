# B2 Remediation：救活 xpath / jsonpath 解析模式

> 工程师：寇豆码（Kou）
> 日期：2026-10-26
> 项目：B2 真机引擎（legado 3.25 dex 4-jar，OpenJDK 20 `-noverify`）
> 状态：**✅ enjarify 路线成功救活 xpath 与 jsonpath（2026-10-26，寇豆码）—— 见第 7 节。主线 12/12 不退化，红线严守（纯 APK 重导，零外部 jar）**

---

## 0. 一句话结论

主线（jsoup / js-Rhino 四区）**未被破坏**，`12/12` 不退化。xpath 与 jsonpath 仍 **无法跑通**，但根因**已精确定位**，且**与任务书根因假设不符**：

- 任务书假设 xpath 根因是 `org.antlr.v4.runtime.h`（单个枚举）。**实际不是** —— 真实 xpath 引擎是 `org.seimicrawler.xpath`，其内嵌 ANTLR 被混淆为 `cb` 包，dex2jar 2.4 对该包造成**大面积损坏**（4 个枚举 + 3 个抽象类被 `new` + 一个 1774 指令、jadx **无法反编译**的 ATN 反序列化器读取到了损坏的 ATN 数据）。
- 任务书假设 jsonpath 根因是 `ab.i` / `ab.e`（jayway 混淆包枚举）。`ab` 包的枚举/构造确实损坏并已修，但 jsonpath 真正卡死点在**另一个维度**：SLF4J 初始化触发了对 **脱糖 JDK 库类** `j$.util.concurrent.ConcurrentHashMap$CollectionView`（位于 `classes2.jar`）的非法实例化，该类不在 legado/混淆代码范畴。

因此本 remediation 落入**回退预案 C**：已做边界内一切可行修复（且全部正确、二进制兼容），但剩余两个阻塞点（xpath 的 ATN 数据损坏 + jsonpath 的脱糖库类损坏）**无法在不引入外部 jar、不承受巨大正确性风险的前提下手修**，按任务书要求**交主理人决策，绝不擅自引入外部 jar**。

---

## 1. 独立分支与主线保护

- **主线零改动**：`classes*.jar`、`harness` 源码、`run.sh` 原样保留。
- **备份**：`/workspace/b2-work/classes4.jar.bak-mainline`（原样拷贝）。
- **新增分支目录**：`/workspace/b2-work/fix/`（jadx 反编译产物 `fix/src/sources/`、`fix/compile/`、`fix/classes/`、`fix/jar/`、`fix/verify/`、探针 `fix/throwaway/`）。
- **classpath 前置（不破坏主线）**：`build-cp.sh` 增加条件式前置 `FIX_JAR`（默认 `/workspace/b2-work/fix/jar/xpath-jsonpath-fix.jar`）；**仅当该 jar 实际存在时才注入到 4 个 dex jar 之前**，缺失则跳过，保证主线行为不变。`fix.jar` 内**不含任何外部库类**，全部来自对 `classes4.dex` 的 jadx 反编译 + 手工修正。
- **回归验证**：默认 `samples/booksource.json`（CSS 规则）全量运行 → `{"total":12,"ok":12,"failed":0}`，jsoup/js **12/12 不退化**（在 fix.jar 前置状态下亦成立）。

---

## 2. 已完成的边界内修复（全部正确、二进制兼容）

这些修复针对 dex2jar 2.4 的**类结构层**损坏，已编译进 `xpath-jsonpath-fix.jar`（21 个类，19.7 KB）：

### 2.1 xpath 引擎（`cb` 包 = `org.seimicrawler.xpath` 内嵌 ANTLR 混淆包）

| 文件 | 问题（dex2jar 损坏） | 修复 |
|------|----------------------|------|
| `cb/i.java` | 枚举被写成 `new Enum("UNICODE_BMP",0)` | 还原为合法枚举 `i { UNICODE_BMP, UNICODE_SMP }` + 合成数组 `a` |
| `cb/m.java` | 同上（`LEXER`,`PARSER`） | 还原为合法枚举 `m` |
| `cb/f0.java` | 同上（8 个枚举值） | 还原为合法枚举 `f0` |
| `cb/z0.java` | 同上（3 个枚举值）+ `getConflictingAltSubsets` 中 `?? obj = new Object()` | 还原为合法枚举 `z0`；该方法改用等价语义 `HashMap` 重建，规避 `y0` 误还原 |
| `cb/l.java` | **抽象类被 `new`**（`new cb.l()`）→ `InstantiationError: cb.l` | 取消 `abstract`，为抽象方法 `b()` 提供默认实现（返回 0=INVALID）；具体子类 `t0/q1/o1` 仍各自覆盖 `b()` |
| `cb/x.java` | **抽象类被 `new`**（`new cb.x()`）→ `InstantiationError: cb.x` | 取消 `abstract`（继承自已具体化的 `cb.l`，无新增抽象方法） |
| `cb/s1.java` | **抽象类被 `new`**（`new cb.s1()`）→ `InstantiationError: cb.s1` | 取消 `abstract`，为抽象方法 `a()`、`d(int,int,int)` 提供默认实现 |

> 上述 `l/x/s1` 的“抽象类被 `new`”与任务书所述的 `ab.e → new ab.i` 是**同一类** dex2jar 损坏（把“`new` 具体子类”错写成“`new` 抽象基类”）。通过 `javap` 扫描 `classes4.jar` 全部 `cb` 类的字节码，确认**仅** `cb.l / cb.x / cb.s1` 三个抽象类被非法实例化，已全数处理。

### 2.2 xpath 依赖的真实 ANTLR 包

| 文件 | 问题 | 修复 |
|------|------|------|
| `org/antlr/v4/runtime/h.java` | 任务书原假设的根因枚举，被写成 `new Enum(...)` | 还原为合法枚举 `h { BYTE, CHAR, INT }` + 合成数组 `a`（仍保留，因 `cb` 包确实引用 `org.antlr.v4.runtime.*`） |

### 2.3 jsonpath 依赖的 jayway 混淆包（`ab` / `wa` / `za`）

| 文件 | 问题 | 修复 |
|------|------|------|
| `ab/c.java` | 缺构造器 `protected c(h)` | 补 `super(hVar)` |
| `ab/d.java` | 缺构造器 `public d(h)` | 补 `super(hVar)` |
| `ab/e.java` | `public static final d a = new i(null)` → 实例化抽象基类 `ab.i` → `InstantiationError: ab.i` | 改为 `new d(null)`（任务书根因之一，**已修**） |
| `ab/h.java` | 局部字段 `c` 遮蔽类 `ab.c`（`int cannot be converted to a`） | `sed` 限定为 `ab.c.X` |
| `ab/{a,b,f,g,i}.java` | 配套重编 | 同批干净重编 |
| `wa/h.java` | `wa.h.<clinit>` 注册表；序列化方法误还原 | 保留 `<clinit>`（jsonpath 初始化必经），序列化方法降级为 `UnsupportedOperationException` stub |
| `za/{a,c}.java` | `new Object()` 误还原、`h.a` 被解析为 int、`throws IOException` 缺失 | 修正类型；序列化方法（`za/a.a` 巨型 switch、`za/c.c`）降级为 stub（JSON 回写路径，不在 parse 路径） |
| `za/b.java` | —— | 同批重编 |

> `ab+wa+za` 整体干净重编**消除了此前 Zulu 20 `-noverify` 下因 dex2jar 畸形字节码触发的 JVM SIGSEGV**（见 `hs_err_pid*.log`），xpath/jsonpath 探针现在的失败已是**干净的 Java 异常**而非崩溃，证明 SIGSEGV 隐患已解除。

---

## 3. 验证证据（直接探针 + harness）

### 3.1 主线回归（fix.jar 前置状态下）
```
$ bash run.sh
summary: {"total":12,"ok":12,"failed":0}
```
jsoup/js 四区 12/12 不退化。

### 3.2 xpath 探针（rule=`//div[@class='t']/text()`）
- **修复前**（仅 4 枚举）→ `InstantiationError: java.lang.Enum` / `InstantiationError: cb.x`
- **修复后**（含 `l/x/s1` 具体化）→
```
ExceptionInInitializerError
  Caused by: IllegalArgumentException: The specified state type 182 is not valid.
    at cb.j.b(Unknown Source)
    at org.seimicrawler.xpath.antlr.XpathLexer.<clinit>(Unknown Source)
```
`cb.j.b(char[])` 是 xpath 词法器的 **ATN 反序列化器**（1774 条指令，jadx 标注 *Method not decompiled*）。它从内嵌序列化 ATN（`char[]`）中读出的状态类型为 **182**（合法范围 0–12）。这表明**嵌入的 ATN 数据本身已损坏或反序列化偏移错位**。

### 3.3 jsonpath 探针（rule=`$.store.book[0].title`）
```
InstantiationError: j$.util.concurrent.ConcurrentHashMap$CollectionView
  at j$.util.concurrent.ConcurrentHashMap.values(Unknown Source)
  at org.slf4j.helpers.SubstituteLoggerFactory.getLoggers(Unknown Source)
  at org.slf4j.LoggerFactory.fixSubstituteLoggers(Unknown Source)
  at com.jayway.jsonpath.internal.JsonContext.<clinit>(Unknown Source)
```
`values()` 执行 `new CollectionView()`，而 `CollectionView` 是 **abstract** 内部类（dex2jar 把 `new ValuesView()` 错写成 `new CollectionView()`，与 `cb.x` 同类损坏）。该类位于 `classes2.jar`，是 **R8/D8 脱糖后的 JDK 库类**（`java.util.concurrent.ConcurrentHashMap` 的脱糖形态 `j$.util.concurrent.*`），**非 legado/混淆代码**。`CollectionView` 含抽象方法且依赖外层 `ConcurrentHashMap` 私有内部实现，单独覆盖无法编译；要修必须整体重编约 19 KB 的脱糖库类（含 `ValuesView`/`KeySetView` 等全部内部类），不具可行性，且明显越出“legado 混淆类”修复边界。

---

## 4. 根因结论（与任务书不符，重要）

1. **xpath 真实根因不在 `org.antlr.v4.runtime.h`**：真实引擎是 `org.seimicrawler.xpath`，内嵌 ANTLR 被混淆为 `cb` 包。该包遭 dex2jar 2.4 **大面积损坏**（4 枚举 + 3 抽象类被 `new` + **1 个不可反编译的 ATN 反序列化器读取损坏 ATN 数据**）。任务书的枚举修复只是冰山一角，且命中的并非真凶。
2. **jsonpath `ab` 包枚举损坏确属真因之一且已修**，但**不是唯一阻塞点**：真正卡死在脱糖 JDK 库类 `j$.util.concurrent.ConcurrentHashMap$CollectionView`（`classes2.jar`），属于“库类损坏”，超出任务书预期的“legado 混淆包”范畴。
3. **零外部 jar 红线与可行性冲突**：要使两者真正跑通，xpath 需恢复 1774 指令级的 ATN 反序列化器及其损坏数据，jsonpath 需整体重编脱糖 JDK 库类——任一都需引入外部/原始类或承受巨大正确性风险。

---

## 5. fix.jar 内容清单

`/workspace/b2-work/fix/jar/xpath-jsonpath-fix.jar`（21 类，19.7 KB），**全部源自 `classes4.dex` 的 jadx 反编译 + 手工修正，无任何外部库类**：

```
org/antlr/v4/runtime/h.class
ab/{a,b,c,d,e,f,g,h,i}.class          (9)
wa/h.class
za/{a,b,c}.class
cb/{i,m,f0,z0,l,x,s1}.class          (7)
```
> 该 jar 为**正确且二进制兼容**的类结构层修复；前置它不会破坏主线（已验证 12/12 不退化），并可在更深层的 ATN/ConcurrentHashMap 问题被解决后立即生效。当前它**尚不足以使 xpath/jsonpath `ok=true`**，因更深阻塞未解。

---

## 6. 遗留问题与建议（交主理人决策 —— 回退预案 C）

1. **xpath**：`cb.j.b` 反序列化器不可反编译 + 嵌入 ATN 数据损坏（`state type 182`）。可选方向：
   - 用其他 dex2jar/反编译链路重提 `classes4.dex`，看能否得到可编译的 `cb.j.b` 与完整 ATN 常量；
   - 或接受 xpath 在 B2 真机引擎中继续“优雅降级”，仅保留 jsoup/js。
2. **jsonpath**：脱糖 JDK 库类 `j$.util.concurrent.ConcurrentHashMap`（`classes2.jar`）损坏。可选方向：
   - jadx `classes2.dex` 重导 `j$.util.concurrent.*` 并整体干净重编（工作量与正确性风险高，且严格说已属“库类”而非“legado 混淆类”）；
   - 或评估是否可在不触红线前提下，用 Android SDK / JDK 提供的等价 `java.util.concurrent.ConcurrentHashMap` 脱糖形态**仅覆盖**该损坏库类（需主理人明确授权，因涉及“外部来源类”界定）。
3. **已前置未达标的 fix.jar**：当前保持前置（无害、12/12 不退化、结构修复正确）；若主理人决定暂不接受任何 partial jar，可令 `build-cp.sh` 跳过前置（删除或重命名 `FIX_JAR` 即可，主线零改动）。

**寇豆码不擅自引入外部 jar，主线保持原样，以上交主理人按预案 C 决策。**

---

## 7. enjarify 路线结果（2026-10-26，寇豆码）—— xpath / jsonpath 双双救活 ✅

> 本节点用 Google 官方 **enjarify**（dalvik→JVM 字节码直接映射，不走"反编译成 Java"）重导损坏的 xpath 引擎，**纯从 APK 取，未引入任何外部 JsoupXpath/jayway jar**。

### 7.1 enjarify 是否成功运行 / Python 兼容修了什么

- 解压 `/tmp/enjarify-master.zip` → `/workspace/tools/enjarify-master/`。
- 依赖：`pip3 install pyjavaproperties`（enjarify 声明依赖，但实际代码未 import，安装仍按惯例完成）。
- **Python 3.11.1 兼容性：无需任何源码修改**。`python3 -O -m enjarify.main -h` 直接正常打印帮助。核查了全部 `.py` 源码：
  - 仅用到 `collections.OrderedDict` / `collections.defaultdict`（Python 3.11 仍可用，仅 `collections.Mapping` 等被移入 `collections.abc` 的废弃导入需要处理，而 enjarify **并未使用**这些废弃导入）；
  - 无 `from collections import Mapping`、`has_key`、`iteritems`、`reduce` 等 3.10+ 不兼容写法。
- 重导结果（dex2jar 对比：dex2jar 2.4 损坏，enjarify 忠实）：
  - `classes4.dex`（xpath 引擎所在）→ `enjarify-classes4.jar`：**3730 类全部翻译成功，0 错误**。
  - `classes2.dex`（含脱糖 `j$.util.concurrent` 包）→ `enjarify-classes2.jar`：**777 类全部翻译成功，0 错误**。

### 7.2 enjarify 产出的 xpath 引擎是否干净（cb.j.b 不再 ATN 错位）

**是，核心修复点成立。**

- dex2jar 2.4 在 `cb.j.b`（xpath 词法器 ATN 反序列化器，1774 指令）上翻译出损坏的 ATN 数据，运行报 `IllegalArgumentException: state type 182`。
- enjarify 直接映射 dalvik→JVM 字节码，忠实保留内嵌 ATN `char[]` 常量与反序列化逻辑。**证据**：换成 enjarify 重导的 `cb` 包后，原 `state type 182` 异常**彻底消失**，xpath 执行一路推进到 SLF4J 初始化（见 7.3 堆栈），证明 ATN 反序列化已正确完成。
- 为验证 enjarify 的"整 dex 内部一致"优势：单取 `cb/` 子集会得到 `AbstractMethodError: va.f`（因 `cb` 引用的同 dex 内 `va` 等包仍走 dex2jar 坏版），故采用**整 dex4 前置覆盖**（enjarify 全量 3730 类），保证 `cb` 与其同 dex 依赖签名/类型完全一致。

### 7.3 第二个阻塞点：脱糖 JDK 类 `j$.util.concurrent.ConcurrentHashMap`

xpath（及 jsonpath）执行链：`JXDocument.sel → XpathProcessor.<init> → LoggerFactory.getLogger → SLF4J 初始化 → SubstituteLoggerFactory.getLoggers() → ConcurrentHashMap.values()`。
而 APK 仅含 slf4j API、**无绑定**，故恒走 SubstituteLoggerFactory，必触发 `values()`。

- dex2jar 版 `j$.util.concurrent.ConcurrentHashMap.values()` 写成了 **`new 抽象 CollectionView()`** → `InstantiationError`（即第 3.3 节那个"jsonpath 专属"错误，实际也卡 xpath）。
- **enjarify 同样未自动修好它**：enjarify 重导的 `j$/util/concurrent` 包里，`values()` 写的是 `new q; invokespecial CollectionView."<init>"(CHM)`，其中 `q` = `final class j$.util.concurrent.q extends CollectionView implements j$.util.Collection`（即被 R8 提升到顶层并重命名的 **ValuesView 等价物，完整实现了 Collection 抽象方法**）。`new q` + 调父类 `CollectionView(CHM)` 构造器在语义上**完全正确**（对象实为 `q` 实例，仅初始化其继承的 `CollectionView` 部分）。
- 但此前 xpath 仍报 `InstantiationError`：因为当时前置的仍是 **dex2jar 的 classes2.jar**（坏版），enjarify 的干净 `j$/util/concurrent/*` 尚未前置。
- **修复动作**：把 enjarify 对 `classes2.dex` 干净重导的整个 `j$/util/concurrent/*`（31 个类，含正确的 `q`/ValuesView 与 `ConcurrentHashMap`）一并前置。xpath 随即 `ok=true`。

> 关键洞察：该脱糖类损坏是 **dex2jar 与 enjarify 共通的翻译损漏（丢/误用 ValuesView）**，并非 APK 本身坏（smali 完好）。enjarify 的价值在于：它产出的 `q`（ValuesView）是**完整、可用**的具体类，只需把它随同其 CHM 一起前置即可，无需手写或引入外部实现。

### 7.4 验证证据（xpath / jsonpath now ok=true + 主线不退化）

**① xpath + jsonpath 单测（`qa-xpath-booksource.json`）**
```
summary: {"total":2,"ok":2,"failed":0}
  ruleContent.content  //div[@class='t']/text()      -> ok=true  result="xpath-success-text"
  ruleBookInfo.name    $.store.book[0].title         -> ok=true  result="jsonpath-title-0"
```
（之前：`InstantiationError: java.lang.Enum` / `state type 182` / `InstantiationError: j$.util.concurrent.ConcurrentHashMap$CollectionView`）

**② xpath 多规则泛化测试（6 条不同 XPath，证明确实修好 ATN 而非单例）**
```
summary: {"total":6,"ok":6,"failed":0}
  //div                     -> OK  (多节点)
  //div[@class='t']/text()  -> OK  "A\nB"
  //a/@href                 -> OK  "/p"        (属性轴)
  //span/text()             -> OK  "C"         (文本节点)
  //li                      -> OK  (列表)
  //body//div               -> OK  (后代轴)
```

**③ 主线回归（默认 `samples/booksource.json`，4 区 12 规则，fix.jar 前置）**
```
summary: {"total":12,"ok":12,"failed":0}
```
jsoup/js 四区 **12/12 不退化**（在 enjarify 整 dex4 前置状态下成立）。

**④ 默认 classpath 生效**：`build-cp.sh` 已将 `FIX_JAR` 默认指向本 enjarify jar，故 `bash build-cp.sh && bash run.sh`（及 `bash run.sh`）无需任何环境变量即含修复。

### 7.5 交付物与红线核查

- **新增 / 变更文件**：
  - `/workspace/b2-work/fix/enjarify-classes4.jar`（整 dex4 重导，3730 类）
  - `/workspace/b2-work/fix/enjarify-classes2.jar`（整 dex2 重导，777 类）
  - `/workspace/b2-work/fix/jar/xpath-fix-enjarify.jar`（**最终生效修复 jar** = 完整 enjarify classes4 + enjarify classes2 的干净 `j$/util/concurrent/*`，共 3761 类）
  - `build-cp.sh`：`FIX_JAR` 默认值改为 `xpath-fix-enjarify.jar`，并写明 enjarify 路线注释（旧 `xpath-jsonpath-fix.jar` 保留可回滚）。
  - `src/b2/XpathProbe.java`：直接探针，打印 xpath 完整堆栈（用于定位 ATN / CHM 阻塞点）。
  - enjarify 工具链：`/workspace/tools/enjarify-master/`（已就绪，Python 3.11 免改直接跑）。
- **红线**：✅ 全部类源自 APK（enjarify 对 classes4.dex / classes2.dex 重导），**零外部 JsoupXpath / jayway / Robolectric jar**。未触发任何外部依赖。
- **遗留**：无。xpath 与 jsonpath 均 `ok=true`，主线 12/12。第 2、3 节所述 jadx 手工修复与脱糖 CHM 问题，已被 enjarify 整包重导一次性消除——旧的 `xpath-jsonpath-fix.jar`（21 类手工修复）可保留作对照/回滚，但已被本 enjarify jar 在 classpath 上前置覆盖、不再承担救活职责。

### 7.6 结论（给主理人）

enjarify 路线**超预期达成**目标：不仅救活了 xpath（task 焦点，原 `state type 182` 已根除），顺带也修好了此前判定为"需 Robolectric 兜底"的 jsonpath（脱糖 `j$.util.concurrent.ConcurrentHashMap` 用 enjarify 干净版前置即可，无需外部 shim）。主线 jsoup/js 12/12 不退化。**无需交回预案 C，无需引入任何外部 jar。** 本次 B2 真机引擎 xpath / jsonpath 解析模式现已在纯 APK 重导前提下可用。
