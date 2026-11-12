# references/evidence/ —— 结论的物证

这里放**支撑技能关键结论的原始材料**。为什么单开一个目录：结论抄进文档、证据留在 `/tmp`，
等于自包含性破了个洞——哪天临时目录一清，就只剩结论没有出处（1.13.24 修的就是这个）。

**随包约定（见 SKILL.md Resources）**：
- one-off 挖掘产物（jadx 反编译全文、从 APK 抽出的 jar）必须落到这里，
  并在文档里以 `references/evidence/jsoup-from-apk.jar` 这样的**技能内完整路径**引用；
- APK 内部类（如 `help/http/e.java`、`t6/i.java`）用户随时可再反编译复现，**不必随包**；
- 裸文件名引用既区分不了这两者、也逃过 `self_audit.py` 第 4 类检查，一律不写。

---

## AnalyzeByJSoup.kt（17 KB）

- **证明什么**：3.25 的属性选择器（含 `~=`）**委托 Jsoup 原生 `select()`**，不是 Legado 自己
  实现的匹配逻辑。由此推出 bs4/soupsieve 无法建模 `~=`，校验器必须走真 Jsoup 通道。
  ⚠️ 同通道实测订正（2026-10-25，jsoup-1.17.2 可复跑）：**`?=` 并非 Jsoup 操作符**——`?` 被
  解析进属性名，`[attr?=val]` 恒不命中、不报错；选择器既透传，真机同此结果（静默取空）。
- **怎么核对**：搜 `select(` 的调用点（第 77、124、296 行等），看属性选择器分支是否直接透传。
- **出处**：用户提供的 legado 3.25 反编译（jadx 输出）。

## jsoup-from-apk.jar（319 KB）

- **证明什么**：APK 内的 Jsoup **在纯 JVM 上跑不起来**——这就是"为什么不直接拿 APK 里的 Jsoup
  来对齐、而要用官方 `jsoup-1.17.2.jar`"（选项一判死）的依据。
- **精确机制**（1.13.24 实测订正，此前表述为"经 R8 魔改、不可独立运行"，过粗）：
  - 包名**仍为** `org/jsoup/**`，没有被打散——`javac -cp` 能编译通过，类也能正常加载；
  - 但一旦真正解析，就在 `org.jsoup.parser.Tag.<clinit>` 抛
    `NoClassDefFoundError: cn/hutool/core/map/f`——R8 把 hutool 的类**内联进 Jsoup 内部**
    并重命名成单字母类名，纯 JVM 上没有这些类，直接崩。
  - 所以是「**编译能过、加载能过、一跑就炸**」，不是"类找不到/包名打散"。
- **怎么复现**（自己跑一遍，别信我的转述）：

```bash
cd references/evidence
unzip -l jsoup-from-apk.jar | grep -c '\.class'      # 270
TMP=$(mktemp -d)
cat > "$TMP/T.java" <<'EOF'
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.select.Elements;
public class T {
  public static void main(String[] a) {
    Document d = Jsoup.parse("<div data-x='1'>hi</div>");
    Elements e = d.select("[data-x~=1]");
    System.out.println("命中=" + e.size());
  }
}
EOF
javac -cp jsoup-from-apk.jar -d "$TMP" "$TMP/T.java"   # 编译 OK
java -cp "$TMP:jsoup-from-apk.jar" T    # NoClassDefFoundError: cn/hutool/core/map/f
```

**同一段代码换个 jar 就通了**——这就是"用官方 jar 对齐"的完整依据（两条都实跑过）：

```bash
TMP=$(mktemp -d)  # 上一段已建则复用
java -cp "$TMP:jsoup-from-apk.jar" T      # NoClassDefFoundError: cn/hutool/core/map/f
java -cp "$TMP:../../scripts/jsoup_eval/jsoup-1.17.2.jar" T   # 命中=1
```

- **为什么保留 319 KB 原件而不是只贴报错文本**：转述的报错只能信我，原件谁都能自己跑一遍。
  占发布包约三分之一，换一个可随时复核的否定结论，值。
- **出处**：从用户提供的 legado 3.25 APK 的 dex 中提取。

## AnalyzeRule-SourceRule.java（约 13 KB）

- **证明什么**：`##` / `##$##` 切段的**完整 dex 实锤**——`makeUpRule` 调 `kotlin.text.u.H0(rule, {"##"}, 0, 6)` 把规则按 `##` 切成 4 段（末位 6 是 mask 不是 limit，`limit=0` 保留尾部空串）：第 0 段=规则主体 / 第 1 段=replaceRegex / 第 2 段=replacement / 第 3 段存在即 replaceFirst。这就是 `##正则##替换`、`##$##值` 等写法的引擎级依据。`splitRegex` / `splitSourceRule` 同用 `##` 切分。
- **怎么核对**：搜第 1844 行 `H0(rule, new String[]{"##"}, 0, 6)` 即切分点；1845-1854 是四段赋值；1719 的 `splitRegex` 也用同一 `H0` 切。`splitSourceRule`（965 行）按 `<js>` 等切分并构造 `SourceRule` 列表。
- **出处**：用户提供的 legado 3.25 APK（md5 `7c5ab9dfa751f58b8ef0220ae001d619`，vcode 15604）经 jadx 1.5.0 反编译 `io.legado.app.model.analyzeRule.AnalyzeRule$SourceRule`（classes3.dex）。反编译含 R8 混淆名（`kotlin.text.u.H0` / `d0.h0` / `k.*`），属真实产物非笔误。
- **引用约定**：references 里 `##` / `##$##` 相关论断一律以本文件**技能内完整路径** `references/evidence/AnalyzeRule-SourceRule.java` 引用，不要只写裸文件名（逃过 self_audit 第 4 类检查）。
