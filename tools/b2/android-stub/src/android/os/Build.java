package android.os;

/**
 * 方案 B 自产 minimal stub：Android {@code android.os.Build} 及其内部类 {@code VERSION}。
 *
 * <p>Rhino evalJS 路径（AnalyzeRule.evalJS / JsExtensions）在初始化时会读取
 * {@code Build.VERSION.SDK_INT} / {@code Build.MODEL} 等构建信息。本 stub 仅提供
 * 静态常量，返回安全默认值，不依赖真实设备。
 */
public class Build {
    public static final String MODEL = "unknown";
    public static final String BRAND = "unknown";
    public static final String DEVICE = "unknown";
    public static final String MANUFACTURER = "unknown";
    public static final String PRODUCT = "unknown";
    public static final String HARDWARE = "unknown";
    public static final String DISPLAY = "unknown";
    public static final String ID = "unknown";

    /** 嵌套构建版本信息类。 */
    public static class VERSION {
        public static final int SDK_INT = 0;
        public static final String RELEASE = "0";
        public static final String INCREMENTAL = "0";
        public static final String CODENAME = "REL";
    }
}
