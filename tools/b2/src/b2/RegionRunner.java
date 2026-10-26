package b2;

import io.legado.app.model.analyzeRule.AnalyzeRule;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 规则区执行器（T4 四区覆盖）。
 *
 * <p>遍历某个规则区（search/bookInfo/toc/content）内的每条叶子规则，调用真实
 * {@link AnalyzeRule#getString(String, Object)}（jsoup/xpath/jsonpath/regex 模式）或
 * dex 自带 Rhino（{@code <js>} 模式，经 {@link JavaShim} 短路网络）跑出结果。
 *
 * <p>模式自动识别遵循架构师纠偏：<b>无 mask 参数</b>，由规则串语法决定：
 * {@code @js:}→js、{@code //}→xpath、{@code $}→jsonpath、默认→jsoup（含 {@code ##} 段替换）。
 */
public final class RegionRunner {

    private final AnalyzeRule analyzeRule;
    private final NetworkStub network;
    private final JavaShim javaShim;

    public RegionRunner(AnalyzeRule analyzeRule, NetworkStub network) {
        this.analyzeRule = analyzeRule;
        this.network = network;
        this.javaShim = new JavaShim(analyzeRule, network);
    }

    /**
     * 执行单个规则区。
     *
     * @param region 规则区标识（ruleContent / ruleBookInfo / ruleToc / ruleSearch）
     * @param ruleObj 该区的规则对象（字段名→规则串）
     * @param html    该区对应的样本内容（HTML/JSON 文本）
     * @return 逐条规则结果
     */
    public List<RuleResult> runRegion(String region, Map<String, Object> ruleObj, String html) {
        List<RuleResult> out = new ArrayList<>();
        if (ruleObj == null) return out;
        for (Map.Entry<String, Object> e : ruleObj.entrySet()) {
            Object val = e.getValue();
            if (!(val instanceof String)) continue; // 仅处理字符串规则字段
            out.add(runOne(region, e.getKey(), (String) val, html));
        }
        return out;
    }

    /** 执行单条规则（按模式分流）。 */
    RuleResult runOne(String region, String ruleKey, String rule, String html) {
        String mode = detectMode(rule);
        RuleResult rr = new RuleResult(region, ruleKey, rule, mode);
        try {
            if ("js".equals(mode)) {
                String js = RhinoEngine.stripPrefix(rule);
                // 真机语义补全：真机里 java 绑定就是 AnalyzeRule 自身，且此时已 setContent(当前页)，
                // 所以 `java.getString('#x@href')` 能取到值。此前 harness 未 setContent，
                // 导致该写法在 B2 内**静默返回空**（不是报错，比报错更危险：会误判成"规则没问题"）。
                try {
                    analyzeRule.setContent(html);
                } catch (Throwable ignore) {
                    // 内容绑定失败不阻塞 JS 执行：java.getString 退化为空（与旧行为一致）
                }
                String r = RhinoEngine.evalJs(js, html, javaShim, "", html);  // 真机语义: result 初值 = 当前内容(mContent)
                rr.setResult(r);
                rr.setOk(true);
                rr.setNote("dex-Rhino + java.* 真绑定(加密走真实hutool, 网络走NetworkStub)");
            } else {
                // jsoup / xpath / jsonpath / regex(##) 统一走真实 AnalyzeRule.getString
                String r = analyzeRule.getString(rule, html);
                rr.setResult(r);
                rr.setOk(true);
            }
        } catch (Throwable t) {
            rr.setOk(false);
            rr.setErrorPhase("execute:" + mode);
            rr.setError(describe(t));
            String hint = diagnose(t);
            if (hint != null) rr.setNote(hint);
        }
        return rr;
    }

    /**
     * 把"环境限制"与"书源问题"区分开，直接写进 note，避免使用者误判。
     *
     * <p>2026-10-26 验收反馈：多份书源出现 {@code ExceptionInInitializerError} 与连锁
     * {@code NoClassDefFoundError: Could not initialize class ...}，使用者会以为是
     * dex2jar/enjarify 转换不全；实测根因是纯 JVM 缺少 Android appCtx。
     */
    static String diagnose(Throwable t) {
        Throwable cur = t;
        int depth = 0;
        while (cur != null && depth < 6) {
            String m = cur.getMessage();
            if (m != null) {
                if (m.contains("appCtx has not been initialized")) {
                    return "【环境限制·非书源问题】该规则触发了依赖 Android appCtx 的路径（Glide 静态初始化）。"
                            + "B2 是纯 JVM 未注入 appCtx；可试 -Db2.injectAppCtx=true（实测有 JVM SIGSEGV 风险，默认关闭）。";
                }
                if (m.contains("Could not initialize class")) {
                    return "【连锁失败】该类的静态初始化此前已失败，后续访问必然 NoClassDefFoundError；"
                            + "请先看同一批次里最早的 ExceptionInInitializerError 那条的 cause。";
                }
            }
            cur = cur.getCause();
            depth++;
        }
        return null;
    }

    /**
     * 把异常还原成**可排查**的文本：递归展开 cause 链 + 各层首帧。
     *
     * <p>动机（2026-10-26 验收反馈）：{@code ExceptionInInitializerError} 的 getMessage()
     * 通常为 null，只取 SimpleName+Message 会得到 {@code "ExceptionInInitializerError: "}——
     * 真正的根因（NoClassDefFoundError / NPE / 第三方 SDK 初始化失败）全被吞掉，无法定位。
     *
     * <p>输出形如：
     * {@code ExceptionInInitializerError: (message 为空) @ A.<clinit>(A.java:1) <- NoClassDefFoundError: android/content/Context @ ...}
     */
    static String describe(Throwable t) {
        StringBuilder sb = new StringBuilder();
        Throwable cur = t;
        int depth = 0;
        while (cur != null && depth < 5) {
            if (depth > 0) sb.append(" <- ");
            sb.append(cur.getClass().getName());
            String m = cur.getMessage();
            if (m == null || m.trim().isEmpty()) {
                sb.append(": (message 为空)");
            } else {
                String one = m.replace("\n", " ").replace("\r", " ").trim();
                sb.append(": ").append(one.length() > 300 ? one.substring(0, 300) + "…" : one);
            }
            StackTraceElement[] st = cur.getStackTrace();
            if (st != null && st.length > 0) sb.append(" @ ").append(st[0]);
            cur = cur.getCause();
            depth++;
        }
        return sb.toString();
    }

    /** 规则串 → 模式（与真机 RuleAnalyzer 自动识别对齐，供契约上报）。 */
    public static String detectMode(String rule) {
        if (rule == null) return "unknown";
        String r = rule.trim();
        if (r.startsWith("@js:") || r.startsWith("@JS:")) return "js";
        if (r.startsWith("//")) return "xpath";
        if (r.startsWith("$")) return "jsonpath";
        // 默认 jsoup（覆盖 @CSS: / tag.class@attr / 纯 CSS / 以及内含 ## 段替换）
        return "jsoup";
    }
}
