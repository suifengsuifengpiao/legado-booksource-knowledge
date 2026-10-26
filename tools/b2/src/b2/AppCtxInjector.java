package b2;

import java.lang.reflect.Field;

/**
 * 把 {@link B2Context} 注入 Glide 的静态 appCtx 字段，避免
 * {@code IllegalStateException: appCtx has not been initialized!} 引发的
 * {@code ExceptionInInitializerError}（其 getMessage 为 null，真实根因会被吞）。
 *
 * <p>注入点：{@code com.bumptech.glide.c.a}（public static Context）。
 * 该字段为 null 时 {@code com.bumptech.glide.c.q()} 直接抛异常；赋值后
 * {@code BaseSource.getShareScope} 等依赖 appCtx 的路径可正常返回默认值。
 *
 * <p>必须在任何规则执行前调用（类初始化一旦失败，后续同类访问会变成
 * {@code NoClassDefFoundError: Could not initialize class ...}，无法补救）。
 */
public final class AppCtxInjector {

    private AppCtxInjector() {}

    private static boolean installed = false;
    private static String status = "未执行";

    /** 幂等安装；失败不抛，只记录状态（注入失败仍可跑多数书源）。 */
    public static synchronized void install() {
        if (installed) return;
        installed = true;
        try {
            Class<?> glide = Class.forName("com.bumptech.glide.c");
            Field f = glide.getField("a");
            Object cur = f.get(null);
            if (cur != null) {
                status = "已存在 appCtx（未覆盖）";
                return;
            }
            f.set(null, new B2Context());
            status = "已注入 B2Context -> com.bumptech.glide.c.a";
        } catch (Throwable t) {
            status = "注入失败: " + t.getClass().getSimpleName() + ": " + t.getMessage();
        }
    }

    public static String status() {
        return status;
    }
}
