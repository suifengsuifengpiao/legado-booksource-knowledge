package android.util;

/**
 * 方案 B 自产 minimal stub：Android {@code android.util.Base64}。
 * 提供与真机同签名的两个静态工具方法；实现委托到 JDK 内置 java.util.Base64，行为等价。
 * 仅 AnalyzeUrl 等网络分支触碰，静态解析不调用。
 */
public class Base64 {
    public static final int DEFAULT = 0;
    public static final int NO_PADDING = 1;
    public static final int NO_WRAP = 2;
    public static final int URL_SAFE = 8;

    public static byte[] decode(String str, int flags) {
        try {
            return java.util.Base64.getDecoder().decode(str);
        } catch (IllegalArgumentException e) {
            return new byte[0];
        }
    }

    public static byte[] decode(byte[] input, int flags) {
        return decode(new String(input), flags);
    }

    public static String encodeToString(byte[] input, int flags) {
        return java.util.Base64.getEncoder().encodeToString(input);
    }

    public static byte[] encode(byte[] input, int flags) {
        return java.util.Base64.getEncoder().encode(input);
    }
}
