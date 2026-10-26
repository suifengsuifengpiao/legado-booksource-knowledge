package android.content;

import java.util.Map;
import java.util.Set;

/**
 * 方案 B 自产 minimal stub：Android {@code android.content.SharedPreferences} 接口。
 *
 * <p>解析闭包可能通过 Context.getSharedPreferences 读取配置；本 stub 提供接口签名，
 * 由 harness 侧返回空实现（所有 get 返回默认值，edit 为 no-op）。
 */
public interface SharedPreferences {
    Map<String, ?> getAll();
    String getString(String key, String defValue);
    Set<String> getStringSet(String key, Set<String> defValues);
    int getInt(String key, int defValue);
    long getLong(String key, long defValue);
    float getFloat(String key, float defValue);
    boolean getBoolean(String key, boolean defValue);
    boolean contains(String key);
    android.content.SharedPreferences.Editor edit();
    void registerOnSharedPreferenceChangeListener(android.content.SharedPreferences.OnSharedPreferenceChangeListener listener);
    void unregisterOnSharedPreferenceChangeListener(android.content.SharedPreferences.OnSharedPreferenceChangeListener listener);

    interface Editor {
        android.content.SharedPreferences.Editor putString(String key, String value);
        android.content.SharedPreferences.Editor putInt(String key, int value);
        android.content.SharedPreferences.Editor putLong(String key, long value);
        android.content.SharedPreferences.Editor putFloat(String key, float value);
        android.content.SharedPreferences.Editor putBoolean(String key, boolean value);
        android.content.SharedPreferences.Editor remove(String key);
        android.content.SharedPreferences.Editor clear();
        boolean commit();
        void apply();
    }

    interface OnSharedPreferenceChangeListener {
        void onSharedPreferenceChanged(android.content.SharedPreferences sharedPreferences, String key);
    }
}
