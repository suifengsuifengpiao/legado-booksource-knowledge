package b2;

import android.content.BroadcastReceiver;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.Resources;

import java.io.File;

/**
 * 纯 JVM 下的最小 Android {@link Context} 实现，用于注入 Glide 的静态 appCtx 字段。
 *
 * <p>背景（2026-10-26 验收反馈定位）：某些书源规则会经由
 * {@code BaseSource$DefaultImpls.getShareScope} 触发 Glide 静态初始化，
 * 而 {@code com.bumptech.glide.c.q()}（即 getApplicationContext）在
 * {@code com.bumptech.glide.c.a == null} 时抛
 * {@code IllegalStateException: appCtx has not been initialized!}，
 * 外层被包装成 {@code ExceptionInInitializerError}（getMessage() 为 null，
 * 真实根因极易被吞掉）。
 *
 * <p>做法：在 harness 启动时把本类实例反射写入 {@code com.bumptech.glide.c.a}。
 * 所有取值方法返回安全默认值（包名 / 临时目录 / 空对象），不触碰真实 Android。
 */
public class B2Context extends Context {

    private static final File BASE = new File(System.getProperty("java.io.tmpdir"), "b2-android");

    @Override
    public String getPackageName() {
        return "io.legado.app";
    }

    @Override
    public Context getApplicationContext() {
        return this;
    }

    @Override
    public Context getBaseContext() {
        return this;
    }

    @Override
    public Object getSystemService(String name) {
        return null;
    }

    @Override
    public SharedPreferences getSharedPreferences(String name, int mode) {
        return null;
    }

    @Override
    public SharedPreferences getSharedPreferences(String name, int mode, int userId) {
        return null;
    }

    @Override
    public File getFilesDir() {
        return ensure(new File(BASE, "files"));
    }

    @Override
    public File getCacheDir() {
        return ensure(new File(BASE, "cache"));
    }

    @Override
    public File getExternalFilesDir(String type) {
        return ensure(new File(BASE, "ext"));
    }

    @Override
    public ContentResolver getContentResolver() {
        return new ContentResolver();
    }

    @Override
    public PackageManager getPackageManager() {
        return new PackageManager();
    }

    @Override
    public int checkSelfPermission(String permission) {
        return 0; // PERMISSION_GRANTED
    }

    @Override
    public void startActivity(Intent intent) {
        // no-op
    }

    @Override
    public Intent registerReceiver(BroadcastReceiver receiver, IntentFilter filter) {
        return null;
    }

    @Override
    public void unregisterReceiver(BroadcastReceiver receiver) {
        // no-op
    }

    @Override
    public Resources getResources() {
        return new Resources();
    }

    @Override
    public SharedPreferences getDefaultSharedPreferences(Context context) {
        return null;
    }

    private static File ensure(File f) {
        //noinspection ResultOfMethodCallIgnored
        f.mkdirs();
        return f;
    }
}
