package b2;

import io.legado.app.model.analyzeRule.AnalyzeRule;

/**
 * Rhino {@code java} 绑定垫片（仅用于 {@code <js>} 模式）。
 *
 * <p>真机中 legado 把 {@code java} 绑定到 {@code AnalyzeRule} 自身（实现 {@code JsExtensions}），
 * 其 {@code get/ajax/connect} 会走真实 okhttp 网络。为严守“永不真实联网”红线，本垫片：
 * <ul>
 *   <li><b>加密类</b>（md5/base64/aes/des…）委托给<b>真实的</b> {@link AnalyzeRule} 实例方法
 *       （底层为 dex 自带 hutool，与真机一致）；</li>
 *   <li><b>网络类</b>（get/ajax/connect）改走 {@link NetworkStub}，返回注入样本，绝不联网。</li>
 * </ul>
 *
 * <p>这样在纯 JVM 下以 dex 自带 Rhino 真实执行 {@code <js>} 规则，并获得与真机等价的
 * {@code java.*} 绑定语义，同时硬短路网络。
 */
public final class JavaShim {

    private final AnalyzeRule analyzeRule;
    private final NetworkStub network;

    public JavaShim(AnalyzeRule analyzeRule, NetworkStub network) {
        this.analyzeRule = analyzeRule;
        this.network = network;
    }

    // ---------------- 加密 / 编码（委托真实 AnalyzeRule → 真实 hutool） ----------------

    // ---- 规则求值转发（真机 java 即 AnalyzeRule，这些方法都可用）----
    // 2026-10-26 补：此前缺 getString，导致 nextContentUrl 用 `java.getString('#pb_next@href')`
    // 在 B2 里报 "Cannot find function getString" —— 是 harness 缺陷造成的假失败，不是书源问题。
    public String getString(String rule) { return analyzeRule.getString(rule); }
    public String getString(String rule, Object content) { return analyzeRule.getString(rule, content); }

    public String md5Encode(String s) { return analyzeRule.md5Encode(s); }
    public String md5Encode16(String s) { return analyzeRule.md5Encode16(s); }
    public String base64Encode(String s) { return analyzeRule.base64Encode(s); }
    public String base64Encode(String s, int flags) { return analyzeRule.base64Encode(s, flags); }
    public String base64Decode(String s) { return analyzeRule.base64Decode(s); }
    public String base64Decode(String s, String charset) { return analyzeRule.base64Decode(s, charset); }
    public String encodeURI(String s) { return analyzeRule.encodeURI(s); }
    public String encodeURI(String s, String enc) { return analyzeRule.encodeURI(s, enc); }
    public String androidId() { return analyzeRule.androidId(); }
    public String getCookie(String url) { return ""; }
    public String getCookie(String url, String key) { return ""; }

    // ---------------- 网络（硬短路，返回注入样本） ----------------

    public String get(String url) {
        String inj = network.getInjected(url);
        return inj == null ? "" : inj;
    }

    public String ajax(Object o) {
        // 真机 ajax 接受 Map/JSONObject；此处仅演示短路，返回注入或空
        return "";
    }

    public String connect(String url) {
        String inj = network.getInjected(url);
        return inj == null ? "" : inj;
    }

    public String put(String k, String v) { return ""; }
    public String getSource() { return ""; }
}
