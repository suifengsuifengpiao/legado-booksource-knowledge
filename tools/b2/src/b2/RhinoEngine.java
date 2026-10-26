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
        return evalJs(js, source, javaShim, baseUrl, null);
    }

    /**
     * 以 dex Rhino 执行 JS 表达式（带 {@code result} 绑定，真机等价语义）。
     *
     * @param js        JS 源码（不含 {@code @js:} 前缀）
     * @param source    样本内容（同时绑定为 {@code src}，真机语义）
     * @param javaShim  绑定到 JS 变量 {@code java} 的垫片
     * @param baseUrl   绑定到 JS 变量 {@code baseUrl} 的基准地址
     * @param result    绑定到 JS 变量 {@code result} 的值。真机 RuleAnalyzer 语义：
     *                  <b>规则首段的 result 初值就是当前内容（mContent）</b>，后续段为上一段结果；
     *                  传 null 表示显式的空上一步。绝不可"不绑定"——未绑定会抛
     *                  {@code ReferenceError: "result" is not defined}，而书源普遍写 {@code +result}。
     * @return JS 求值结果的字符串形式；null 返回 null
     */
    public static String evalJs(String js, String source, Object javaShim, String baseUrl, String result) {
        Context cx = Context.enter();
        try {
            cx.setOptimizationLevel(-1);
            Scriptable scope = cx.initStandardObjects();
            scope.put("source", scope, source == null ? "" : source);
            scope.put("java", scope, javaShim);
            scope.put("baseUrl", scope, baseUrl == null ? "" : baseUrl);

            // ---- 真机 evalJS 绑定（dex 反查 AnalyzeRule 字符串常量实证）----
            // source / baseUrl / result / chapter / nextChapterUrl / book / cookie / cache / title
            // 关键：这些名字必须**存在**。真机里无值时为 null，而"不存在"会抛
            // ReferenceError: "result" is not defined —— 书源里 `result || ''` 这类写法直接崩。
            scope.put("result", scope, result);
            scope.put("src", scope, source == null ? "" : source);
            scope.put("title", scope, "");
            scope.put("nextChapterUrl", scope, "");
            scope.put("cookie", scope, null);
            scope.put("cache", scope, null);
            scope.put("book", scope, null);
            scope.put("chapter", scope, null);

            Object result2 = cx.evaluateString(scope, js, "b2-js", 1, null);
            return result2 == null ? null : Context.toString(result2);
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
