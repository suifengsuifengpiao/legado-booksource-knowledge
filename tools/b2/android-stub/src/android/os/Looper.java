package android.os;

/**
 * 方案 B 自产 minimal stub：Android {@code android.os.Looper}。
 * 仅作为 Glide/Handler 探测路径的占位返回类型；纯 JVM 不真正运行消息循环。
 */
public class Looper {
    public static Looper getMainLooper() { return null; }
    public static Looper myLooper() { return null; }
    public void loop() { /* no-op */ }
}
