package b2;

import io.legado.app.help.http.StrResponse;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 网络硬短路桩（红线：永不真实联网）。
 *
 * <p>harness 全程不发出任何真实 HTTP 请求。所有 {@code java.get / ajax / connect} 调用
 * 一律返回本桩中预先注入的样本响应（或空串）。本类同时负责：
 * <ul>
 *   <li>维护 url → 注入样本响应体 的映射（{@link #register}）；</li>
 *   <li>为 {@link JavaShim} 提供 {@link #getInjected(String)} 查询；</li>
 *   <li>按 dex 真实类型构造 {@link StrResponse}，以贴合真机返回结构（供契约与调试使用）。</li>
 * </ul>
 *
 * <p>注意：dex 内 {@code AnalyzeUrl}/{@code CustomUrl} 走 okhttp 真实网络；本 harness 通过
 * 让 {@code <js>} 规则中的 {@code java.get/ajax} 改走本桩（见 {@link JavaShim}），
 * 从源头保证零联网。绝不直接调用 {@code AnalyzeUrl} 等真实网络分支。
 */
public final class NetworkStub {

    private final Map<String, String> injected = new LinkedHashMap<>();

    public NetworkStub() {}

    /** 注入一条 url → 响应体的样本（支持前缀匹配）。 */
    public void register(String url, String body) {
        injected.put(url, body);
    }

    /**
     * 查询注入样本。优先精确匹配，其次前缀匹配（如 {@code https://api.test/} 命中
     * {@code https://api.test/x}）。无样本返回 null（调用方据此返回空串，绝不联网）。
     */
    public String getInjected(String url) {
        if (url == null) return null;
        if (injected.containsKey(url)) return injected.get(url);
        for (Map.Entry<String, String> e : injected.entrySet()) {
            if (url.startsWith(e.getKey())) return e.getValue();
        }
        return null;
    }

    /** 构造 dex 真实 {@link StrResponse}（String,String 构造器），贴合真机返回体结构。 */
    public StrResponse makeResponse(String url, String body) {
        return new StrResponse(body == null ? "" : body, url == null ? "" : url);
    }

    /** 返回当前注入样本清单（用于契约/审计）。 */
    public Map<String, String> snapshot() {
        return new LinkedHashMap<>(injected);
    }
}
