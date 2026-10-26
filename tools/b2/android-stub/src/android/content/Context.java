package android.content;

/**
 * 方案 B 自产 minimal stub：Android {@code android.content.Context}。
 *
 * <p>注意：真机中 Context 是<b>抽象类</b>而非接口；dex 内 legado 代码按“类”使用
 * （如 {@code Context.class}、类型强转、AppCompatActivity 继承等），故此处必须声明为
 * abstract class，否则运行时抛 {@code IncompatibleClassChangeError}。
 *
 * <p>Rhino evalJS 初始化与 Glide appCtx 探测路径会访问 Context 获取包名、缓存目录等；
 * 本 stub 提供抽象方法签名，由 harness 侧 {@code b2.B2Context} 给出安全默认实现。
 */
public abstract class Context {
    public static final int MODE_PRIVATE = 0;
    public static final int MODE_WORLD_READABLE = 1;
    public static final int MODE_WORLD_WRITEABLE = 2;
    public static final int MODE_MULTI_PROCESS = 4;
    public static final int MODE_APPEND = 0x8000;

    public abstract String getPackageName();
    public abstract Context getApplicationContext();
    public abstract Context getBaseContext();
    public abstract Object getSystemService(String name);
    public abstract android.content.SharedPreferences getSharedPreferences(String name, int mode);
    public abstract android.content.SharedPreferences getSharedPreferences(String name, int mode, int userId);
    public abstract java.io.File getFilesDir();
    public abstract java.io.File getCacheDir();
    public abstract java.io.File getExternalFilesDir(String type);
    public abstract android.content.ContentResolver getContentResolver();
    public abstract android.content.pm.PackageManager getPackageManager();
    public abstract int checkSelfPermission(String permission);
    public abstract void startActivity(android.content.Intent intent);
    public abstract android.content.Intent registerReceiver(android.content.BroadcastReceiver receiver,
                                                           android.content.IntentFilter filter);
    public abstract void unregisterReceiver(android.content.BroadcastReceiver receiver);
    public abstract android.content.res.Resources getResources();
    public abstract android.content.SharedPreferences getDefaultSharedPreferences(android.content.Context context);
}
