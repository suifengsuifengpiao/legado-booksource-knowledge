package b2;

import org.mozilla.javascript.Context;
import org.mozilla.javascript.Scriptable;

/**
 * dex 自带 Rhino 引擎驱动（真机同款 JS 引擎，禁止外部 Rhino）。
 *
 * <p>用于执行书源 {@code <js>} 规则。要点：
 * <ul>
 *   <li>使用 dex 内 {@code org.mozilla.javascript}（577 类，随 jar 免费），不引入任何外部 Rhino；</li>
 *   <li>优化级别设为 -1（解释执行），规避 dex2jar 转换类在 JIT/字节码生成期的偶发不稳定；</li>
 *   <li>绑定 {@code source}（样本内容）、{@code java}（见 {@link JavaShim}）、{@code baseUrl}，
 *       与真机 evalJS 的绑定名一致；</li>
 *   <li><b>不走</b> {@code AnalyzeRule.evalJS}——后者内部会触发 Glide 的 Android appCtx 静态初始化，
 *       在纯 JVM 下导致 JVM 崩溃（dex2jar/Android 运行时产物，非 harness 缺陷）。
 *       改为直接驱动 dex Rhino，达到等价的真机 JS 语义。</li>
 * </ul>
 */
public final class RhinoEngine {

    private RhinoEngine() {}

    /**
     * 以 dex Rhino 执行 JS 表达式。
     *
     * @param js        JS 源码（不含 {@code @js:} 前缀）
     * @param source    绑定到 JS 变量 {@code source} 的样本内容
     * @param javaShim  绑定到 JS 变量 {@code java} 的垫片
     * @param baseUrl   绑定到 JS 变量 {@code baseUrl} 的基准地址
     * @return JS 求值结果的字符串形式；null 返回 null
     */
    public static String evalJs(String js, String source, Object javaShim, String baseUrl) {
        Context cx = Context.enter();
        try {
            cx.setOptimizationLevel(-1);
            Scriptable scope = cx.initStandardObjects();
            scope.put("source", scope, source == null ? "" : source);
            scope.put("java", scope, javaShim);
            scope.put("baseUrl", scope, baseUrl == null ? "" : baseUrl);
            Object result = cx.evaluateString(scope, js, "b2-js", 1, null);
            return result == null ? null : Context.toString(result);
        } finally {
            Context.exit();
        }
    }

    /** 剥离 {@code @js:} / {@code @JS:} 前缀，返回纯 JS 源码。 */
    public static String stripPrefix(String rule) {
        if (rule == null) return "";
        if (rule.startsWith("@js:")) return rule.substring(4);
        if (rule.startsWith("@JS:")) return rule.substring(4);
        return rule;
    }
}
