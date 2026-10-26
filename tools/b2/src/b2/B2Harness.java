package b2;

import io.legado.app.data.entities.BookSource;
import io.legado.app.model.analyzeRule.AnalyzeRule;
import io.legado.app.model.analyzeRule.RuleData;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * B2 真机引擎 harness 入口（T3/T4）。
 *
 * <p>在纯 JVM（OpenJDK 20，无 Android Runtime）加载 legado 3.25 真实解析类
 * （{@link AnalyzeRule} 等），喂入“书源 JSON + 抓回样本页面”，驱动真实
 * {@link AnalyzeRule#getString(String, Object)} 跑出与真机逐规则一致的解析结果，
 * 并以调试契约 JSON 暴露给 lint 工具。
 *
 * <p><b>红线遵守</b>：全程硬短路，永不真实联网；仅用 dex 自带选择器/Rhino，无外部 jar。
 *
 * <p>用法：
 * <pre>
 *   java -noverify -cp &lt;cp&gt; b2.B2Harness [--source &lt;booksource.json&gt;]
 *                                            [--region all|content|bookinfo|toc|search]
 *                                            [--out &lt;contract.json&gt;]
 * </pre>
 */
public final class B2Harness {

    /** 规则区 → 样本文件短名 映射。 */
    private static final Map<String, String> REGION_TO_SAMPLE = new LinkedHashMap<>();
    static {
        REGION_TO_SAMPLE.put("ruleContent", "content");
        REGION_TO_SAMPLE.put("ruleBookInfo", "bookinfo");
        REGION_TO_SAMPLE.put("ruleToc", "toc");
        REGION_TO_SAMPLE.put("ruleSearch", "search");
    }

    private static String homeDir() {
        String h = System.getProperty("b2.home");
        return h == null ? "." : h;
    }

    /** 样本目录（可由 --sample-dir 覆盖，便于与 lint --real-engine 对接）。 */
    private static String SAMPLE_DIR = ".";

    public static void main(String[] args) throws Exception {
        // 0) 可选：注入 Glide appCtx。默认关闭——实测注入后走到 Glide 深处会触发
        //    dex2jar 转换类的 JVM SIGSEGV（JfrResolution::on_runtime_resolution），
        //    比"可捕获的 ExceptionInInitializerError"更糟。开启：-Db2.injectAppCtx=true
        if (Boolean.getBoolean("b2.injectAppCtx")) {
            AppCtxInjector.install();
        }

        String sourcePath = homeDir() + "/samples/booksource.json";
        String region = "all";
        String outPath = null;
        String sampleDir = homeDir() + "/samples";

        for (int i = 0; i < args.length; i++) {
            if ("--source".equals(args[i]) && i + 1 < args.length) sourcePath = args[++i];
            else if ("--region".equals(args[i]) && i + 1 < args.length) region = args[++i];
            else if ("--out".equals(args[i]) && i + 1 < args.length) outPath = args[++i];
            else if ("--sample-dir".equals(args[i]) && i + 1 < args.length) sampleDir = args[++i];
        }
        SAMPLE_DIR = sampleDir;

        // 1) 载入书源 JSON，抽取四区规则对象
        String raw = readFile(sourcePath);
        Object parsed = Json.parse(raw);
        if (parsed instanceof List) parsed = ((List<?>) parsed).get(0);
        @SuppressWarnings("unchecked")
        Map<String, Object> bs = (Map<String, Object>) parsed;

        Map<String, Map<String, Object>> regions = new LinkedHashMap<>();
        for (String r : REGION_TO_SAMPLE.keySet()) {
            Object o = bs.get(r);
            if (o instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) o;
                regions.put(r, m);
            }
        }

        // 2) 构造真实 dex 对象
        BookSource bookSource = new BookSource();                 // 真实 dex 类（无参构造，R5 退化路径）
        RuleData ruleData = new RuleData();                       // 真实 dex 类
        AnalyzeRule analyzeRule = new AnalyzeRule(ruleData, bookSource); // 真实 dex 类
        NetworkStub network = new NetworkStub();
        network.register("https://api.test/x", "{\"injected\":true}"); // 演示用注入样本
        RegionRunner runner = new RegionRunner(analyzeRule, network);

        // 3) 逐规则区执行（支持全名 ruleContent 与短名 content）
        String fullRegion = region;
        if (!regions.containsKey(fullRegion)) {
            for (Map.Entry<String, String> e : REGION_TO_SAMPLE.entrySet()) {
                if (e.getValue().equals(region)) { fullRegion = e.getKey(); break; }
            }
        }
        List<String> toRun = region.equals("all")
                ? new ArrayList<>(regions.keySet())
                : Collections.singletonList(fullRegion);

        List<RuleResult> results = new ArrayList<>();
        for (String reg : toRun) {
            Map<String, Object> ruleObj = regions.get(reg);
            if (ruleObj == null) continue;
            String html = readSampleHtml(reg);
            if (html == null) {
                RuleResult rr = new RuleResult(reg, "(no-sample)", "", "unknown");
                rr.setOk(false);
                rr.setErrorPhase("sample");
                rr.setError("未能读取样本 HTML（samples/" + REGION_TO_SAMPLE.get(reg) + "-sample.json）");
                results.add(rr);
                continue;
            }
            results.addAll(runner.runRegion(reg, ruleObj, html));
        }

        // 4) 汇总为调试契约 JSON
        String name = Json.getString(bs, "bookSourceName");
        DebugContract contract = new DebugContract(name == null ? sourcePath : name, results);
        String json = contract.toJson();

        if (outPath != null) {
            writeFile(outPath, json);
            System.out.println("[B2] 契约已写出: " + outPath);
        }
        System.out.println(json);
    }

    private static String readSampleHtml(String region) {
        String shortName = REGION_TO_SAMPLE.get(region);
        if (shortName == null) return null;
        String path = SAMPLE_DIR + "/" + shortName + "-sample.json";
        try {
            Object o = Json.parse(readFile(path));
            if (o instanceof Map) {
                Object html = ((Map<?, ?>) o).get("html");
                if (html != null) return html.toString();
            }
        } catch (IOException e) {
            return null;
        }
        return null;
    }

    private static String readFile(String path) throws IOException {
        return new String(Files.readAllBytes(Paths.get(path)), StandardCharsets.UTF_8);
    }

    private static void writeFile(String path, String content) throws IOException {
        Files.write(Paths.get(path), content.getBytes(StandardCharsets.UTF_8));
    }
}
