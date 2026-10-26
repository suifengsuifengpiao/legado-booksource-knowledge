package android.text;

/**
 * 方案 B 自产 minimal stub：Android {@code android.text.TextUtils}。
 *
 * <p>AnalyzeRule 解析闭包真实触碰的方法仅有 {@link #isEmpty(CharSequence)}；
 * 为稳妥起见同时提供 legado 常用的几个静态工具方法，方法体返回安全默认值，
 * 不抛异常（与真机行为一致：空串/空判断返回 false/true）。
 *
 * <p>本类不含任何外部依赖，仅用于纯 JVM（无 Android Runtime）下链接 AnalyzeRule。
 */
public class TextUtils {

    /** 真机语义：null 或长度为 0 的 CharSequence 视为 empty。 */
    public static boolean isEmpty(CharSequence str) {
        return str == null || str.length() == 0;
    }

    public static boolean equals(CharSequence a, CharSequence b) {
        if (a == b) return true;
        int length;
        if (a != null && b != null && (length = a.length()) == b.length()) {
            if (a instanceof String && b instanceof String) {
                return a.equals(b);
            }
            for (int i = 0; i < length; i++) {
                if (a.charAt(i) != b.charAt(i)) return false;
            }
            return true;
        }
        return false;
    }

    public static String join(CharSequence delimiter, Iterable<?> tokens) {
        StringBuilder sb = new StringBuilder();
        boolean first = true;
        for (Object token : tokens) {
            if (first) {
                first = false;
            } else {
                sb.append(delimiter);
            }
            sb.append(token);
        }
        return sb.toString();
    }

    public static boolean isDigitsOnly(CharSequence str) {
        if (str == null) return false;
        int len = str.length();
        for (int i = 0; i < len; i++) {
            char c = str.charAt(i);
            if (c < '0' || c > '9') return false;
        }
        return true;
    }
}
