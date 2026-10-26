package android.net;

import java.util.HashMap;
import java.util.Map;

/**
 * 方案 B 自产 minimal stub：Android {@code android.net.Uri}。
 * 提供 {@link #parse(String)} 与常用访问方法；返回安全默认值，不依赖真实 Uri 解析。
 * 解析闭包仅在个别书源用 {@code Uri.parse} 拼 URL 时触碰，本 stub 返回原串即可。
 */
public abstract class Uri {
    /** 真实实现可用的简单具体子类（stub）。 */
    private static final class StubUri extends Uri {
        private final String raw;
        StubUri(String raw) { this.raw = raw; }
        @Override public String toString() { return raw; }
        @Override public String getRaw() { return raw; }
    }

    /** 工厂方法：直接返回包裹原串的 stub 实例。 */
    public static Uri parse(String uriString) {
        return new StubUri(uriString == null ? "" : uriString);
    }

    public String getScheme() { return null; }
    public String getAuthority() { return null; }
    public String getPath() { return null; }
    public String getQuery() { return null; }
    public String getLastPathSegment() { return null; }
    public String getQueryParameter(String key) { return null; }
    public String toString() { return ""; }

    /** 供 harness 安全获取原始串。 */
    public String getRaw() { return ""; }

    static { new HashMap<String, String>(); } // 占位，保证 Map 引用存在
}
