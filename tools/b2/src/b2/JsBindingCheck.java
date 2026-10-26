package b2;

import io.legado.app.data.entities.BookSource;
import io.legado.app.model.analyzeRule.AnalyzeRule;
import io.legado.app.model.analyzeRule.RuleData;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * T5 验证：Rhino 真绑定 + {@code java.*} 真绑定（加密） + 联网型硬短路。
 *
 * <p>要点（架构师红线）：
 * <ul>
 *   <li>用<b> dex 自带 Rhino</b>（{@link RhinoEngine}）真实执行 {@code <js>} 规则；</li>
 *   <li>{@code java.md5Encode / java.base64Encode} 委托给<b>真实</b> {@link AnalyzeRule}
 *       （底层 dex hutool），与真机一致；</li>
 *   <li>{@code java.get('https://...')} 走 {@link NetworkStub} 返回注入样本，<b>绝不真实联网</b>；</li>
 *   <li>对比真机预期：md5('abc')=900150983cd24fb0d6963f7d28e17f72，base64('hello')=aGVsbG8=。</li>
 * </ul>
 *
 * <p>注意：此处不调用 {@code AnalyzeRule.evalJS}（其内部触发 Glide appCtx 静态初始化，
 * 纯 JVM 下会致 JVM 崩溃，属 dex2jar/Android 运行时产物）；改为直接驱动 dex Rhino，
 * 达到等价真机 JS 语义。
 */
public final class JsBindingCheck {

    public static void main(String[] args) {
        AnalyzeRule ar = new AnalyzeRule(new RuleData(), new BookSource());
        NetworkStub net = new NetworkStub();
        net.register("https://api.test/x", "{\"injected\":true,\"via\":\"NetworkStub\"}");
        JavaShim shim = new JavaShim(ar, net);

        List<Map<String, Object>> cases = new ArrayList<>();

        // 1) java.md5Encode（真实 hutool）
        String md5 = RhinoEngine.evalJs("java.md5Encode('abc')", "", shim, "");
        cases.add(caseMap("java.md5Encode('abc')", md5, "900150983cd24fb0d6963f7d28e17f72"));

        // 2) java.base64Encode（真实 hutool）
        String b64 = RhinoEngine.evalJs("java.base64Encode('hello')", "", shim, "");
        cases.add(caseMap("java.base64Encode('hello')", b64, "aGVsbG8="));

        // 3) java.base64Decode 回环
        String b64d = RhinoEngine.evalJs("java.base64Decode(java.base64Encode('hello'))", "", shim, "");
        cases.add(caseMap("base64 回环", b64d, "hello"));

        // 4) 联网型硬短路：java.get 返回注入样本，绝不真实请求
        String got = RhinoEngine.evalJs("java.get('https://api.test/x')", "", shim, "");
        cases.add(caseMap("java.get('https://api.test/x') [硬短路]", got, "{\"injected\":true,\"via\":\"NetworkStub\"}"));

        // 5) <js> 处理 content（source 绑定）
        String jsContent = RhinoEngine.evalJs("source.toUpperCase()", "<div>abc 正文</div>", shim, "");
        cases.add(caseMap("<js> source.toUpperCase()", jsContent, "<DIV>ABC 正文</DIV>"));

        // 6) result 绑定存在性（真机语义：规则首段 result 初值 = 当前内容）
        String tResult = RhinoEngine.evalJs("typeof result", "<p>x</p>", shim, "", "<p>x</p>");
        cases.add(caseMap("typeof result（初值=内容）", tResult, "string"));

        // 6b) 首段 result 就是内容本身（书源普遍写法 ''+result）
        String r0 = RhinoEngine.evalJs("''+result", "<p>abc</p>", shim, "", "<p>abc</p>");
        cases.add(caseMap("''+result（首段=内容）", r0, "<p>abc</p>"));

        // 7) result 传值（模拟链式规则的上一步结果）
        String useResult = RhinoEngine.evalJs("result + '!'", "", shim, "", "上一段");
        cases.add(caseMap("result + '!'（传值）", useResult, "上一段!"));

        // 8) result 为 null 时书源最常见的写法不能崩
        String nullSafe = RhinoEngine.evalJs("(result || 'fallback')", "", shim, "", null);
        cases.add(caseMap("(result || 'fallback')（null 安全）", nullSafe, "fallback"));

        // 9) 其余真机绑定必须存在（否则 ReferenceError 误导排查）
        String binds = RhinoEngine.evalJs(
                "[typeof src, typeof title, typeof cookie, typeof book, typeof chapter, typeof cache, typeof nextChapterUrl].join(',')",
                "", shim, "", null);
        cases.add(caseMap("绑定存在性 src/title/cookie/book/chapter/cache/nextChapterUrl", binds,
                "string,string,object,object,object,object,string"));

        Map<String, Object> root = new LinkedHashMap<>();
        root.put("engine", DebugContract.ENGINE);
        root.put("engineVersion", DebugContract.ENGINE_VERSION);
        root.put("check", "T5-JsBinding");
        root.put("networkHardShortCircuit", true);
        root.put("cases", cases);

        String json = Json.toJson(root);
        if (args.length > 0 && args[0].endsWith(".json")) {
            try {
                java.nio.file.Files.write(java.nio.file.Paths.get(args[0]),
                        json.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                System.out.println("[T5] 输出: " + args[0]);
            } catch (Exception e) {
                System.out.println("[T5] 写文件失败: " + e.getMessage());
            }
        }
        System.out.println(json);
    }

    private static Map<String, Object> caseMap(String expr, String actual, String expected) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("expr", expr);
        m.put("actual", actual);
        m.put("expected", expected);
        m.put("match", actual != null && actual.equals(expected));
        return m;
    }
}
