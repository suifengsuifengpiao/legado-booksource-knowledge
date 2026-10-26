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
                String r = RhinoEngine.evalJs(js, html, javaShim, "");
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
            String msg = t.getMessage();
            rr.setError(t.getClass().getSimpleName() + ": " + (msg == null ? "" : msg));
        }
        return rr;
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
