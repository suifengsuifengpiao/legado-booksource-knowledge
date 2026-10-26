# B2 真机解析引擎 JVM harness 可行性 + 范围界定

> 文档角色：架构师（高见远 / Bob）产出。只读分析，未改动任何既有源码（`diff` 为零）。
> 依据产物：`dex_recheck_report.md`（43KB，规则语义/消费点取证）、`java_api_dex_whitelist.json`（136 API 真值清单）、`booksource_lint.py`（Python 克隆编排 + 真 jar 选择器层）、`assets/`（jsoup-1.17.2.jar / JsoupRuleEval / jayway_compat / js_eval.js）。
> 环境实测：`uname`/JVM = OpenJDK 20 (Zulu)；`javac` 20 在；`kotlinc` 不在；jadx 1.5.0 在；dex 已解压于 `/tmp/dex_forensics/{classes,classes2,classes3,classes4}.dex`；APK 内 `META-INF/rhino_release.kotlin_module` 证实 Rhino 随包打包。

---

## 总体结论（GO / NO-GO + 置信度）

**结论：GO（有条件）。** 技术方案成立、置信度约 **85%**：dex 寄存器字节码无法直接被标准 JVM `ClassLoader` 加载这一前提成立，但 dex→jar 转换是成熟可走的路径；关键入口已精确锁定——`AnalyzeRule.getString(String, Object, mask=4)` 为入口、调用方为 `io.legado.app.model.webBook.w.b`（dex_recheck 双工具逐指令坐实）；Rhino 随 APK 打包（`org.mozilla.javascript.*`，含部分混淆类 `org.mozilla.javascript.a`），故 `<js>` 里的 `java.*` 真绑定保真度高；选择器库与现有 lint 动态层**同款**（jsoup 1.17.2 真 jar、JsoupXpath `cn.wanghaomiao.xpath`、jayway `com.jayway.jsonpath`）。**唯一阻塞项不在技术而在采购**：本沙箱内 dex→jar 工具 **dex2jar 无法从 GitHub 内容主机 / Maven Central 直接获取**（实测 GitHub releases/archive 返回 404/9 字节拦截页，Maven 不托管该包），且 **kotlinc 未安装**（jadx 子集重编译备选路径被阻断）。需主理人授权从可用镜像 / 离线包提供 `dex2jar-2.1.zip`（或 `sdk install kotlin` 开启备选）。该阻塞解除后置信度升至 **~95%**。

---

## 0. 范围与定位

- **做（B2）**：在 OpenJDK 加载 APK **真实**解析类（`AnalyzeRule` 编排 + `AnalyzeBy*` 选择器 + 实体 + 随包 Rhino），桩接 Android/App 依赖，喂样本 HTML 驱动真实 `AnalyzeRule`，产出与真机逐规则一致的解析结果。对标"真机调试"——给定抓回的页面，看真机到底取到了什么。
- **不做（明确划界）**：B1（真 Android hook，鸿蒙 7.0+卓易通 + 无 Android 环境，已判不可行，本次不涉及）；**真实联网抓取**（java.get/ajax/post→OkHttp 封装、WebView 在 B2 范围外，以桩代替）；APK 全量加载（只加载解析子系统子集与其传递闭包）。
- **与现有 lint 的关系**：复用现有静态层（结构/字段/正则/JS 语法/java.* 比对，已 59/59）+ 真 jar 选择器层（jsoup/JsoupXpath/jayway），**替换** Python 克隆编排层（`_sr_get_string`/`_sr_eval_seg`）+ Node JS 层（`_eval_js`）→ 新增 `--real-engine` 模式。

---

## 1. dex 加载策略（方案成立前提）

### 1.1 事实前提
- dex 是 **寄存器式** Dalvik 字节码，标准 JVM `ClassLoader` 不能直接加载（类型描述符虽兼容 Java，但指令集与 `dex` 容器格式不同）。
- 本沙箱 **无 Android 运行时**（无 adb/emulator/ART/sdkmanager/frida/dex2jar 预装），**命令行 ART 路线基本排除**——ART 需要完整 Android 系统镜像与 `/system` 框架，无法在纯 Linux 容器裸跑。结论：**必须在 JVM 侧把 dex 转成 .class/.jar**。

### 1.2 三条候选路径对比

| 路径 | 原理 | 优点 | 缺点 / 本沙箱实测 | 判定 |
|---|---|---|---|---|
| **dex2jar**（dex-translator，Java） | 整 dex → jar（每 dex 一个 jar，再合并） | 产标准 jar，OpenJDK 直接加载；**无需 Kotlin 编译器**；对子集容错（坏类不影响好类） | 对 Kotlin 合成类/默认方法/lambda 偶有报错；本沙箱**无二进制**（GitHub 内容主机被拦、Maven 不托管） | **首选 GO（待就位）** |
| **enjarify**（Google，Python） | Python 重写 dex→jar，字节码 cleaner | 对部分结构处理优于 dex2jar | 停止维护，Py2/Py3 兼容坑；`pip install enjarify` **无此发行包**；本沙箱不可装 | **NO-GO** |
| **jadx 反编译 → javac/kotlinc 重编译** | 反编译为 .java 再编译 | 可读、可手工修 | 重度 R8 混淆 Kotlin 重编译极难；**kotlinc 未安装**（`which kotlinc` 空），且需 Kotlin 标准库/协程源码级对齐 | **CONDITIONAL（需 `sdk install kotlin`，成本高于 dex2jar）** |

### 1.3 选型结论与安装步骤
- **主选 dex2jar 2.1**（成熟、无需 Kotlin 编译器、对"只加载子集"天然友好）。安装步骤（网络可装，但需可用源）：
  1. 获取 `dex-tools-2.1.zip`（含 `d2j-dex2jar.sh`）。本沙箱实测 GitHub `releases/download` 与 `codeload` 均被拦截；需主理人提供**离线包**或**可达镜像**。
  2. `unzip` 后 `chmod +x d2j-dex2jar.sh`。
  3. 对 4 个 dex 分别：`d2j-dex2jar.sh --force classesN.dex -o classesN.jar`（多 dex → 4 个 jar，统一放 classpath，解析跨 dex 引用）。
  4. `java -cp "classes1.jar:...:stub.jar:jsoup-1.17.2.jar:..." com.xxx.HarnessMain` 验证 `AnalyzeRule` 可实例化。
- **备选 jadx 子集重编译**：仅当 dex2jar 长期无法就位时启用。需 `sdk install kotlin` + `kotlin-stdlib` 上 classpath；用 `jadx --single-class` 反编译目标类（dex_recheck 已证明 jadx 能吐出 `webBook.w` 1774 条指令级 Java），手工修 R8 混淆导致的不可编译点，再 `kotlinc` 编。成本明显更高，故排第二。

### 1.4 多 dex / R8 混淆 / Kotlin metadata 障碍与对策
- **多 dex**：4 个 dex 分别转换、合并放 classpath 即可；跨 dex 类引用在解析期自动解析。对策：4 jar 全上 classpath，不提前合并（避免重复类冲突）。
- **R8 混淆**：类名单字母（`webBook.w`）、方法名短。dex2jar 把混淆名当合法标识符处理，**不影响执行**；只是反编译可读性差——但 B2 不依赖人类读源码，只依赖运行时链接，故混淆**不构成障碍**。
- **Kotlin metadata**：dex2jar 转换的是**字节码**而非 metadata，Kotlin 特有 metadata 对运行时无影响；真正需要的是 `kotlin-stdlib`（提供 `kotlin.text.u.H0` 等 `AnalyzeRule$SourceRule.makeUpRule` 实际调用的运行时函数）。`org.jetbrains.kotlin:kotlin-stdlib` 以标准 jar 上 classpath（Maven 可达，host 已验证可达，仅 dex2jar 不在）。
- **协程**：`AnalyzeUrl` 有 `...Await(Lkotlin/coroutines/g;)` 等 suspend 方法，但解析入口 `AnalyzeRule.getString` 是**同步**方法；B2 不调用 suspend 分支，只需 `kotlinx-coroutines-core` 在 classpath 满足**链接**（dex 内已捆绑 257 个 coroutines 描述符，可直接用 dex 自带或补标准 jar）。

### 1.5 GO / NO-GO 判断框
| 判断项 | 结果 |
|---|---|
| dex→JVM 转换技术路线存在且成熟 | ✅ GO |
| 本沙箱 dex2jar 二进制可获取 | ⚠️ 待主理人授权/镜像（非技术未知） |
| 混淆/Kotlin/多 dex 致路线不成立 | ❌ 均不构成致命障碍 |
| **dex 加载策略总体** | **GO（有条件：工具就位后转 GO）** |

---

## 2. 类抽取清单（执行一次解析所需加载的真实 dex 类）

已用 `strings` 从 4 个 dex 实提描述符（非推测），去重确认如下。包名以 dex 为准，构造方式在 P0/P1 用 `jadx --single-class` 复核。

### 2.1 解析引擎（包 `io.legado.app.model.analyzeRule`）
| 类（真实描述符） | 作用 | 必抽 |
|---|---|---|
| `Lio/legado/app/model/analyzeRule/AnalyzeRule;` | **编排核心**，`getString`/`getStringList`/`splitSourceRule`/`splitPutRule` | ★ |
| `AnalyzeRule$SourceRule` | `makeUpRule`（切 `##`）、`splitRegex`、`getReplaceRegex` 落点 | ★ |
| `AnalyzeRule$Mode` | 模式枚举（1=evalJS,2=JsonPath,3=XPath,4=JSOUP） | ★ |
| `AnalyzeRule$Companion` / `$WhenMappings` | 伴生/when 映射 | ★ |
| `AnalyzeByJSoup`(+`$SourceRule`,`$Companion`,`$ElementsSingle`) | Jsoup 选择器（真 jsoup 1.17.2） | ★ |
| `AnalyzeByXPath` | XPath（真 JsoupXpath） | ★ |
| `AnalyzeByJSonPath`(+`$Companion`) | JSONPath（真 jayway） | ★ |
| `AnalyzeByRegex` | 正则分支 | ★ |
| `AnalyzeUrl`(+`$UrlOption`,`$ConcurrentRecord`) | URL 规则求值 / url JS 的 `java` 绑定源 | ★（P3） |
| `Lio/legado/app/help/JsExtensions;` | 86 API 接口（get/post/ajax/md5Encode…） | ★ |
| `Lio/legado/app/ui/rss/read/RssJsExtensions;` | RSS 专用（书源无关，仅备案） | 否 |
| `RuleDataInterface`、`QueryTTF` | `getRuleData` 返回 / 字体反爬 | 传递闭包 |

### 2.2 规则实体（包 `io.legado.app.data.entities.rule`）
`SearchRule` `BookInfoRule` `TocRule` `ContentRule` `BookListRule` `ExploreRule` `ReviewRule`（各含 `$Companion`/`$Creator`，Gson Parcelable）。`ContentRule` 9 键已坐实（content/title/nextContentUrl/webJs/sourceRegex/replaceRegex/imageStyle/imageDecode/payAction）。

### 2.3 顶层实体（包 `io.legado/app/data/entities`）
`BookSource`（30 字段，已坐实无顶层 `replaceRegex`）、`BaseSource`、`Book`、`BookChapter`、`BaseBook`。

### 2.4 选择器引擎依赖的真实库（dex 内已捆绑，转换后随 jar 免费获得）
| 库 | dex 内描述符计数 | 说明 |
|---|---|---|
| `org.jsoup` | 269 | 与 lint 动态层**同款 1.17.2**，可直接用 lint 的 `jsoup-1.17.2.jar` |
| `cn.wanghaomiao` (JsoupXpath) | ≥2 | XPath 引擎同款（`org.seimicrawler.xpath`） |
| `com.jayway.jsonpath`（待 P0 复核） | — | JSONPath 引擎；lint 用 `jayway_compat.py` 桥，真机应同款 |
| `okhttp3` | 317 | **网络层，B2 桩接**（不真实联网） |
| `cn.hutool` | 994 | crypto API（`aesEncodeToBase64String` 等）真实现 |
| `com.google.gson` | 98 | 实体 JSON 反序列化 |
| `kotlinx.coroutines` | 257 | 仅链接（不调用 suspend 分支） |
| `org.mozilla.javascript` | 大量（含混淆 `a/b/...`） | **随包 Rhino，java.* 真绑定源** |

### 2.5 抽取原则
**子集而非全量**：dex2jar 对整个 22MB dex 转换，坏类（如某些 Android 视图类）报错不影响目标类；harness 只实例化 `AnalyzeRule`/实体/选择器，传递闭包自动拉入 jsoup/hutool/gson/rhino/kotlin-stdlib/coroutines。

---

## 3. 依赖面与桩计划

### 3.1 依赖分类（可桩接 / 难桩接 / 致命）
| 分类 | 典型类 | 处理 |
|---|---|---|
| **可桩接（无副作用、纯取值）** | `android.util.Log`、`android.net.Uri`、`android.content.Context`（仅取 packageName 等）、`android.os.Build` | 桩返回常量/空实现，不影响解析结果 |
| **难桩接（返回对象被后续使用）** | `androidx.media3.common.MediaItem`（getMediaItem 返回）、`android.graphics.Bitmap`（图片解码）、`android.webkit.WebView` | 桩返回最小合法对象；B2 不触发这些分支（imageDecode 可推迟到 P4 或标 N/A） |
| **致命（真实联网/UI，B2 范围外）** | `okhttp3.OkHttpClient`、`WebView` 渲染、`android.app.Activity` | **一律桩接并短路**：java.get/ajax/post 返回桩响应或抛"范围外"；绝不真实发起请求 |
| **App 内部（网络/Cookie 罐/协程）** | `io.legado.app.help.http.*`（a~s0 混淆包，OkHttp 封装、CookieStore）、`AnalyzeUrl` 的 Await 系列 | 网络分支桩接；Cookie 罐桩内存实现（解析多段时复用同一罐即可） |

### 3.2 关键 Android/App 类清单（需桩，按 dex 描述符驱动生成，见 3.3）
- Android：`android.util.Log`、`android.net.Uri`、`android.content.Context`、`android.os.Build`、`android.os.Bundle`、`android.content.SharedPreferences`。
- AndroidX：仅解析闭包实际触碰者（如 `androidx.media3.common.MediaItem`、`androidx.lifecycle` 若被拉入）；**不必桩全 7829 个 androidx 描述符**——用"链接即补"法（见下）。
- App：`io.legado.app.help.http.{CookieStore, StrResponse, a..s0}`、`AnalyzeUrl$UrlOption`、`AnalyzeUrl$ConcurrentRecord`。

### 3.3 桩签名保真度方案（核心要求：桩签名必须与真类**逐字节吻合**否则链接失败）
推荐**描述符驱动生成**，杜绝手工签名漂移：
1. 用 `androguard`/`jadx` 枚举 dex 中所有被目标类引用的 `android.*`/`androidx.*`/`io.legado.app.help.http.*` **方法描述符**（已在 `/tmp/dex_forensics` 用 `strings` 验证可提取：全 dex `android.*` 1233 / `androidx.*` 7829 条描述符）。
2. 对每条描述符生成最小 `.java` 桩：类声明 + 方法签名**原样照搬** + 返回默认值（`return 0/null/false`；抽象/接口给空实现；`void` 空体）。
3. 编译为 `stub.jar`，置于 classpath **优先于**其他（或单独加载）。
4. **链接即补循环**：运行 → 捕获 `NoClassDefFoundError`/`NoSuchMethodError` → 补对应桩 → 重跑，直到目标类链路稳定。如此只需桩"解析闭包真实触碰"的少量 Android 类，而非 9000+ 全量。

### 3.4 范围外（明确以桩代替）
- **联网**：`java.get/ajax/post` / `AnalyzeUrl` 的 `getStrResponse`/`getResponse` 系列 → 桩，返回 harness 注入的样本响应或从样本 JSON 读取，B2 **不真实抓取**。
- **WebView**：`getWebViewUA` 等 → 桩返回常量 UA；WebView 渲染类整体不加载。
- **TTF 字体反爬**（`queryTTF`/`replaceFont`/`queryBase64TTF`，17 未仿真中的字体项）：B2 默认 N/A，命中即标"需真机"，不阻断主流程。

---

## 4. Rhino `java.*` 真绑定

### 4.1 绑定机制（whitelist `binding_facts` 实证）
- 规则 `<js>` / 规则内 JS：`AnalyzeRule.evalJS` 内 `scriptBindings.put("java", this)` → `java` = **AnalyzeRule 实例**（同时实现 `JsExtensions`）。
- URL 行内 `js` / `webJs`：`AnalyzeUrl.evalJS` 同理，`java` = **AnalyzeUrl 实例**。
- `java.xxx()` 即调用 `JsExtensions` 的 86 接口方法（get/post/ajax/md5Encode/base64Encode/aes…/s2t/log…），书源可用并集 **136**（`union_booksource`）。

### 4.2 harness 复现（无需重实现绑定）
因为 B2 **加载真实 `AnalyzeRule`**，其 `evalJS` 自带正确绑定——harness 只需：
1. 用 dex 自带的 **真实 Rhino**（`org.mozilla.javascript.*`，含混淆类，随 jar 免费）作为 `ScriptEngine`，**不**引入外部 Rhino 版本（否则与混淆引用错配）。
2. 直接调用真实 `AnalyzeRule.getString(rule, content)` → 内部 `evalJS` 自动把 `java` 绑到真实 `AnalyzeRule` 实例 → `<js>` 里的 `java.md5Encode/java.base64Encode/...` 对**真实对象**执行，结果逐字节与真机一致。
3. 对 `java.get/ajax/post` 等**联网型** API，在真实 `JsExtensions` 实现里它们会走到桩网络层（见 3.4）→ 返回样本响应。其余纯计算/加密 API 直接真跑。

### 4.3 Rhino 版本/构建
- 版本 = legado 打包版本（Rhino 1.7.x 系 + 其补丁），**无需知晓具体号**——直接用 dex 内随包 Rhino，保证 `Scriptable`/`NativeArray` 行为与真机一致（这是比 lint 当前 Node 近似 `js_eval.js` 高保真的根本原因）。
- 风险：Rhino 部分混淆（`org.mozilla.javascript.a`）——因与 `AnalyzeRule` 同处一个 dex，转换后同 jar 内链接自洽，**不增加风险**。

---

## 5. harness 设计

### 5.1 架构（组件 + 真实 jar / 桩边界）
```
┌─────────────────────────── B2 harness (OpenJDK 20) ───────────────────────────┐
│                                                                               │
│  ┌──────────────┐   书源JSON+样本HTML    ┌──────────────────────────────────┐  │
│  │ 输入适配层   │ ───────────────────►   │ 真实 dex 类 (classes*.jar)       │  │
│  │ (Gson→实体)  │                        │  AnalyzeRule + AnalyzeBy* +     │  │
│  └──────────────┘                        │  SearchRule/ContentRule/... +   │  │
│         │ 复用 lint 静态层                │  随包 Rhino (org.mozilla.js*)   │  │
│  ┌──────▼───────┐                        └───────────────┬──────────────────┘  │
│  │ 模式派发     │ (复用 _rule_kind / _split_combination)   │ 真实 getString       │
│  │ (_rule_kind) │ ───────────────────────────────────────►│                     │  │
│  └──────────────┘                                        │                     │
│                                                          ▼                     │
│  ┌──────────────┐   真 jar 选择器层                        ┌──────────────────┐  │
│  │ 输出适配层   │◄─────────────────── jsoup-1.17.2 / JsoupXpath / jayway ─────┤   │
│  │ (逐规则结果) │                                        └──────────────────┘  │
│  └──────────────┘                                                                │
│        ▲                                    ┌──────────────────────────────┐    │
│        │ 桩拦截(java.get/WebView/Log/Uri…)  │ stub.jar (dex 描述符驱动生成) │    │
│        └───────────────────────────────────│ android.* / androidx.* / http.*│    │
│                                            └──────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 输入契约
- **书源 JSON**：与 lint 现有输入一致（`BookSource` 全字段）。
- **各规则区样本**：`{ "search": <html>, "bookinfo": <html>, "toc": <html>, "content": <html>, "url": <html/json> }`——抓取回的真实页面（或从 lint self-test 用例抽取）。
- **可选桩响应**：`java.get/ajax/post` 期望返回（用于需要联网型 `<js>` 的书源，P3 后）。

### 5.3 执行流程（对齐 `webBook` 规则求值顺序 + 真实 `AnalyzeRule`）
```mermaid
flowchart TD
    A[载入书源JSON → Gson 构造 BookSource/规则实体] --> B[注入样本HTML 为 mContent]
    B --> C{按 webBook 顺序遍历规则区}
    C -->|search| D1[AnalyzeRule.getString rule,html,mask]
    C -->|bookinfo| D2[AnalyzeRule.getString]
    C -->|toc| D3[AnalyzeRule.getString]
    C -->|content| D4[AnalyzeRule.getString mask=4]
    D1 & D2 & D3 & D4 --> E[SourceRule.makeUpRule 切##/组合&&||%%]
    E --> F{按 mode 派发}
    F -->|js| G1[真实 Rhino evalJS, java=真实AnalyzeRule]
    F -->|regex| G2[AnalyzeByRegex]
    F -->|jsoup| G3[AnalyzeByJSoup → 真 jsoup jar]
    F -->|xpath| G4[AnalyzeByXPath → JsoupXpath]
    F -->|jsonpath| G5[AnalyzeByJSonPath → jayway]
    G1 & G2 & G3 & G4 & G5 --> H[replaceRegex 段替换]
    H --> I[逐规则结果 + 错误码 收集]
    I --> J[输出契约 JSON]
```

### 5.4 输出契约
```json
{
  "source": "<bookSourceName>",
  "rules": [
    {"region":"content","rule":"...","mode":"jsoup","result":"<提取文本/列表>",
     "ok":true,"note":""},
    {"region":"content","rule":"##广告##","mode":"regex-replace","result":"...",
     "ok":true,"note":"replaceRegex 已生效"}
  ],
  "errors": [ {"region":"toc","rule":"...","error":"NoClassDefFoundError: androidx...","phase":"stub"} ]
}
```
- 逐规则给出：提取结果（与真机逐规则比对）、是否成功、失败原因（区分"桩缺失" vs "规则本身空取"）。

### 5.5 与 `booksource_lint.py` 集成（新增 `--real-engine` 模式）
- **复用**：静态层（L54–L~800 结构/字段/正则/JS 语法/java.* 比对）、真 jar 选择器层（`_assets_dir` 已能定位 `jsoup-1.17.2.jar`/`JsoupRuleEval`/`jayway_compat`）、模式派发（`_rule_kind` L833 / `_split_combination` L886）。
- **替换**：`_sr_get_string`（L1527，Python 克隆段循环）→ 调用真实 `AnalyzeRule.getString`；`_eval_js`（L1636，Node 桥）→ 真实 Rhino（dex 自带）。
- **开关**：`--real-engine` 时走真实编排；缺 dex jar / 桩不全时优雅降级回 Python 克隆并告警（保证 lint 既有 59/59 回归不破）。
- **回归**：复用现有 self-test 框架（`evals/validate_cases.json` 中 `##广告` 等用例），对比 `--real-engine` 与克隆层输出一致性。

---

## 6. 风险登记

| # | 风险 | 等级 | 影响 | 对策 |
|---|---|---|---|---|
| R1 | 桩保真度（android/androidx 签名不匹配致链接失败） | 高 | 目标类无法加载/运行 | 描述符驱动生成桩 + 链接即补循环（§3.3） |
| R2 | dex2jar 转换失败 / 本沙箱装不上 | 高(阻塞) | 路线前提不成立 | 主选 dex2jar；备选 jadx 子集重编译（需 `sdk install kotlin`） |
| R3 | Rhino 版本错配（引入外部 Rhino） | 中 | `java.*` 行为偏离真机 | 强制用 dex 自带 Rhino，禁外部版本 |
| R4 | R8 混淆致某些类不可转换 | 中 | 个别类缺 | 子集策略：坏类不影响目标类；必要时 jadx 手工补 |
| R5 | Kotlin/协程耦合（实体 Gson 自定义适配器） | 中 | 实体构造/链接难 | 用 dex 自带 gson+适配器；或反射逐字段构造 |
| R6 | 多 dex 类解析（跨 dex 引用） | 低 | 个别 NoClassDefFound | 4 jar 全上 classpath |
| R7 | 选择器引擎与编排层 HTML 规范化差异 | 中 | 提取结果微差 | 用真 jsoup/JsoupXpath/jayway（同款），差异应趋零；P2 逐用例比对 |
| R8 | 网络/WebView 误触发真实调用 | 高(安全) | 意外联网 | 桩层硬短路，禁止任何真实请求（§3.4） |
| R9 | JsoupXpath/jayway 真 jar 版本与 dex 内引用不一致 | 中 | XPath/JSONPath 链接失败 | P0 确认 dex 内实际包名/版本，对齐提供 |

---

## 7. 分阶段实施计划 + 检查点

| 阶段 | 目标 | 完成判据（明确） | 依赖 |
|---|---|---|---|
| **P0** | dex→jar 成功，AnalyzeRule 可在 OpenJDK 实例化 | 4 dex 转 jar；`new AnalyzeRule(...)`（或等效构造）+ 最少桩下 `Class.forName` 不抛 `NoClassDefFoundError`；打印类方法签名 | 工具就位（R2 解除） |
| **P1** | 单条 `getString` 在样本上跑通 | 给定一条 content 规则 + 样本 HTML，真实 `AnalyzeRule.getString` 返回非空/预期文本；与克隆层输出对照 | P0 |
| **P2** | 覆盖完整规则区 | search/bookinfo/toc/content 四区样本均逐规则产出结果；与克隆层差异收敛到已知白名单（如格式化差异） | P1 |
| **P3** | Rhino `java.*` 真绑定 | 一条含 `<js>` 且调用 `java.md5Encode/java.base64Encode` 的规则，真实 Rhino 跑出与真机一致结果；联网型 `java.get` 走桩返回样本 | P2 |
| **P4** | 集成进 lint + 回归 | `booksource_lint.py --real-engine` 接入；`evals/validate_cases.json` 全量回归，real-engine 与克隆层一致性达标；缺桩/缺工具时优雅降级告警 | P3 |

检查点节奏：每阶段出口须通过"完成判据"方可进下一阶段；R8（安全）为 P0 即生效的硬约束。

---

## 8. 工作量估算（人/机时量级）

| 阶段 | 工作量（机时为主） | 说明 |
|---|---|---|
| P0 | 0.5–1 人日 + 下载/转换机时数分钟 | 工具就位后纯机械；主要耗在桩初版 + 链接即补 |
| P1 | 0.5–1 人日 | 构造 AnalyzeRule + 单规则打通 |
| P2 | 1–2 人日 | 四区样本 + 选择器对齐 + 差异收敛 |
| P3 | 1–2 人日 | Rhino 真绑定 + 联网型桩 |
| P4 | 1 人日 | lint 集成 + 回归 |
| **合计** | **约 4–7 人日**（不含等待工具授权的挂起时间） | 风险缓冲另计 R1/R2/R5 |

---

## 附录 A：本沙箱实测记录（结论依据，非实现）
- JVM：`openjdk 20`(Zulu)；`javac 20` 在；`kotlinc` 不在；jadx 1.5.0 在。
- dex 已解压 `/tmp/dex_forensics/{classes,classes2,classes3,classes4}.dex`（md5 见 whitelist `meta.dex`）。
- APK 含 `META-INF/rhino_release.kotlin_module` → Rhino 随包。
- `strings` 实提：解析引擎/实体/Rhino/BookSource 描述符（§2）；全 dex `android.*`=1233、`androidx.*`=7829、`okhttp3`=317、`cn.hutool`=994、`org.jsoup`=269、`kotlinx.coroutines`=257、`com.google.gson`=98 条描述符。
- **dex2jar 获取阻塞**：GitHub `releases/download/2.1/dex-tools-2.1.zip` 与 `codeload .../zip/refs/tags/2.1` 返回 404/9 字节拦截页；Maven Central 不托管 `com.googlecode.dex2jar`；`pip install enjarify` 无发行包。→ 需主理人提供离线包/镜像。
- 未改动任何源码；本附录仅为可行性论证的取证留痕。

## 附录 B：主理人二次实测补充（2026-10-26，环境可达性矩阵）

上一附录确认 dex2jar 阻塞。本次进一步实测，明确"真正的 B2（加载 APK 真实类）"在本沙箱被**两个文件**同时卡死，并发现一个**无需这两个文件即可开工的降级路径**。

### 可达性矩阵（实测）
| 资源 | 结论 | 证据 |
|---|---|---|
| `org.mozilla:rhino:1.7.14`（真 JS 引擎） | ✅ 可下 | Maven Central / 阿里云 `application/java-archive` 200 |
| `org.jetbrains.kotlin:kotlin-stdlib:1.9.22` | ✅ 可下 | Maven Central 200 |
| `jsoup` / `org.seimicrawler`(JsoupXpath) / `jayway` | ✅ 可下（APK 亦自带） | Maven Central |
| **dex2jar（dex→jar 转换）** | ❌ 全路不通 | `github.com/pxb1988/dex2jar/releases` 直链无响应；`ghproxy.net`/`mirror.ghproxy.com`/`ghproxy.com` 三个变体均 9 字节垃圾或超时；`sourceforge` 404 |
| **enjarify** | ❌ 不存在 | `pip install enjarify` → PyPI 404，无任何发行包 |
| **android.jar（Android 框架桩）** | ❌ 拿不到 | 无 Android SDK；Maven Central 不托管现代 API 级 `android.jar` |
| `kotlinc` | ❌ 未装 | `javac 20` 可替代（仅当走 jadx→java 重编译路径时需要） |

### 阻塞定性
- **更新（2026-10-26 二次实测）**：`android.jar` 阻塞已解除——`org.robolectric:android-all-instrumented:14-robolectric-10818077-i6`（Maven Central，HTTP 200 可下）即各 API 级 Android 框架 jar 等价物，可作编译/运行期 `android.*` 桩底座。
- **真正的 B2（JVM 加载 APK 真实 `AnalyzeRule` 类）现仅剩单文件阻塞：`dex2jar`**（dex→jar 转换器）。`android.jar` 已由 robolectric 解决。
- jadx→java 重编译备选路径**现已解除 android.jar 依赖**（android-all-instrumented 可下），仅余 R8 混淆重编译脆弱性 + 需 `javac`（已具备）。故该路径在无 dex2jar 时仍可作为不依赖外部文件的后备。

### 降级路径 B2-lite（无需被阻塞的两个文件，可立即开工）
- 既然 Rhino / kotlin-stdlib / 选择器 jar 均可从 Maven 取得，**JS 层可改为真 Rhino（`org.mozilla:rhino`）+ 自行实现的 `java.*` 作用域（委托给真 jsoup / 真 okhttp / 真 crypto）**，替换当前 `Node + cheerio` 近似与"java.* 仅静态校验"。
- 编排层（`AnalyzeRule.getString` 规则串联 / replaceRegex / 模式派发）暂沿用现有已验证的 Python 重实现 + 真选择器 jar。
- 价值：把当前工具最"不像真机"的 JS/java.* 环节升级为**真执行**；局限：未加载 App 自身编排类，故不声称逐字节真机对齐。
- 适用场景：用户暂无法提供 `dex2jar`+`android.jar` 时的务实交付。

### 两条路交给主理人/用户裁定
- **路径 A（真 B2，干净）**：用户在可正常联网的 PC 下载 `dex-tools-2.1.zip`（唯一剩余阻塞文件），放入 `/workspace/dex-tools/`；`android.jar` 已由 robolectric `android-all-instrumented` 自动取得。解除后执行本方案 P0–P4（真 `AnalyzeRule` 加载 + Rhino java.* 真绑定）。
- **路径 B（B2-lite）**：本沙箱立即开工，先落地真 Rhino + 真 java.* 绑定，作为 80% 真机对标；真 B2 留待 A 路径文件到位。
- **路径 C（真 B2，无外部文件）后备**：若用户无法提供 dex2jar，则由工程师尝试 jadx 反编译解析类 → `javac` 重编译（依赖已具备的 `android-all-instrumented` + `kotlin-stdlib`），绕开 dex2jar；风险为 R8 混淆重编译脆弱，先做 P0（AnalyzeRule 能否实例化）探针再决定是否继续。
