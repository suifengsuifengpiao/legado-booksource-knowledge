package android.os;

import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/**
 * 方案 B 自产 minimal stub：Android {@code android.os.Bundle}。
 * 实现 Parcelable，仅提供常用 put/get 方法；解析闭包基本不触碰。
 */
public class Bundle implements Parcelable {
    private final Map<String, Object> map = new HashMap<>();

    public Bundle() {}
    public Bundle(Bundle b) { if (b != null) map.putAll(b.map); }

    public void putString(String k, String v) { map.put(k, v); }
    public String getString(String k) { return (String) map.get(k); }
    public String getString(String k, String d) { Object v = map.get(k); return v != null ? (String) v : d; }
    public void putInt(String k, int v) { map.put(k, v); }
    public int getInt(String k, int d) { Object v = map.get(k); return v instanceof Integer ? (Integer) v : d; }
    public void putBoolean(String k, boolean v) { map.put(k, v); }
    public boolean getBoolean(String k, boolean d) { Object v = map.get(k); return v instanceof Boolean ? (Boolean) v : d; }
    public void putParcelable(String k, Parcelable p) { map.put(k, p); }
    public <T extends Parcelable> T getParcelable(String k) { return (T) map.get(k); }
    public boolean containsKey(String k) { return map.containsKey(k); }
    public void remove(String k) { map.remove(k); }
    public void clear() { map.clear(); }
    public Set<String> keySet() { return map.keySet(); }
    public int size() { return map.size(); }

    @Override public int describeContents() { return 0; }
    @Override public void writeToParcel(Parcel dest, int flags) { /* no-op stub */ }
}
