package b2;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 单条规则的解析结果（调试契约的最小单元）。
 *
 * <p>字段对齐架构师契约：{@code region, rule, mode, result, ok, note/errorPhase}。
 */
public final class RuleResult {

    private final String region;     // 规则区：ruleContent / ruleBookInfo / ruleToc / ruleSearch
    private final String ruleKey;    // 规则字段名：content / name / author / chapterList ...
    private final String rule;       // 原始规则串
    private final String mode;       // jsoup / xpath / jsonpath / js / regex(在 jsoup 内)
    private String result = "";      // 解析结果（ok=true 时有效）
    private boolean ok = false;      // 是否成功产出
    private String note = "";        // 备注（成功时的说明）
    private String errorPhase = "";  // 失败阶段：execute:jsoup / execute:js / sample ...
    private String error = "";       // 失败信息（异常类名 + 消息）

    public RuleResult(String region, String ruleKey, String rule, String mode) {
        this.region = region;
        this.ruleKey = ruleKey;
        this.rule = rule;
        this.mode = mode;
    }

    public void setResult(String result) { this.result = result == null ? "" : result; }
    public void setOk(boolean ok) { this.ok = ok; }
    public void setNote(String note) { this.note = note == null ? "" : note; }
    public void setErrorPhase(String errorPhase) { this.errorPhase = errorPhase == null ? "" : errorPhase; }
    public void setError(String error) { this.error = error == null ? "" : error; }

    public String getRegion() { return region; }
    public String getRuleKey() { return ruleKey; }
    public String getRule() { return rule; }
    public String getMode() { return mode; }
    public String getResult() { return result; }
    public boolean isOk() { return ok; }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("region", region);
        m.put("ruleKey", ruleKey);
        m.put("rule", rule);
        m.put("mode", mode);
        m.put("result", result);
        m.put("ok", ok);
        if (ok) {
            if (!note.isEmpty()) m.put("note", note);
        } else {
            m.put("errorPhase", errorPhase);
            m.put("error", error);
            // 失败时也要输出诊断 note（如"环境限制·非书源问题"），否则提示写了却看不到
            if (!note.isEmpty()) m.put("note", note);
        }
        return m;
    }
}
