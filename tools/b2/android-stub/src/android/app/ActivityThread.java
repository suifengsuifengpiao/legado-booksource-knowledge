package android.app;

/**
 * 方案 B 自产 minimal stub：Android {@code android.app.ActivityThread}。
 *
 * <p>dex 内 Glide（com.bumptech.glide）在静态初始化时通过
 * {@code Class.forName("android.app.ActivityThread")} 探测是否处于 Android 运行环境。
 * 纯 JVM 下该类缺失会抛 ClassNotFoundException，导致依赖它的 legado 全局类（io.legado.app.model.q1）
 * 静态初始化失败，进而阻塞 evalJS。本 stub 仅提供该类以满足探测与常用的静态访问方法，
 * 返回安全默认值（不触达真实 Activity 生命周期）。
 */
public class ActivityThread {
    /** Glide 探测调用：返回 null 表示无真实 ActivityThread（纯 JVM 语义）。 */
    public static ActivityThread currentActivityThread() {
        return null;
    }

    public static android.app.Application currentApplication() {
        return null;
    }

    public static String currentPackageName() {
        return "b2.harness";
    }

    public static String currentProcessName() {
        return "b2.harness";
    }

    public static android.os.Looper getMainLooper() {
        return null;
    }

    public Object getSystemContext() {
        return null;
    }

    public void attach(boolean system) { /* no-op stub */ }
}
