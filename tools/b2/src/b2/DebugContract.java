package b2;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 调试契约（输出适配层）。
 *
 * <p>把逐规则结果汇总为可机器消费的 JSON，供 lint（{@code --real-engine}）或调试器消费：
 * <pre>
 * {
 *   "engine": "legado-dex-real",
 *   "engineVersion": "Legado 3.25 / dex 4-jar",
 *   "bookSource": "...",
 *   "summary": { "total": N, "ok": M, "failed": K },
 *   "rules": [ {region, ruleKey, rule, mode, result, ok, note|errorPhase, error}, ... ]
 * }
 * </pre>
 *
 * <p>所有输出 JSON 由 {@link Json} 序列化，零外部依赖。
 */
public final class DebugContract {

    public static final String ENGINE = "legado-dex-real";
    public static final String ENGINE_VERSION = "Legado 3.25 / dex 4-jar (OpenJDK 20, -noverify)";

    private final String bookSource;
    private final List<RuleResult> rules;

    public DebugContract(String bookSource, List<RuleResult> rules) {
        this.bookSource = bookSource;
        this.rules = rules == null ? new ArrayList<>() : rules;
    }

    public Map<String, Object> toMap() {
        int ok = 0;
        int failed = 0;
        for (RuleResult r : rules) {
            if (r.isOk()) ok++; else failed++;
        }
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("total", rules.size());
        summary.put("ok", ok);
        summary.put("failed", failed);

        List<Object> ruleMaps = new ArrayList<>();
        for (RuleResult r : rules) ruleMaps.add(r.toMap());

        Map<String, Object> root = new LinkedHashMap<>();
        root.put("engine", ENGINE);
        root.put("engineVersion", ENGINE_VERSION);
        root.put("bookSource", bookSource);
        root.put("summary", summary);
        root.put("rules", ruleMaps);
        return root;
    }

    public String toJson() {
        return Json.toJson(toMap());
    }
}
