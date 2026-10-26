package android.util;

/**
 * 方案 B 自产 minimal stub：Android {@code android.util.Log}。
 * 解析闭包在调试分支会调用 Log.d/i/w/e；本 stub 输出到 stderr 并返回 0，
 * 与真机“写日志”语义一致，且不影响解析结果。
 */
public class Log {
    private static final String TAG = "B2Harness";

    public static int d(String tag, String msg) { System.err.println("[Log.d][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
    public static int i(String tag, String msg) { System.err.println("[Log.i][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
    public static int w(String tag, String msg) { System.err.println("[Log.w][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
    public static int e(String tag, String msg) { System.err.println("[Log.e][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
    public static int v(String tag, String msg) { System.err.println("[Log.v][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
    public static int wtf(String tag, String msg) { System.err.println("[Log.wtf][" + (tag == null ? TAG : tag) + "] " + msg); return 0; }
}
