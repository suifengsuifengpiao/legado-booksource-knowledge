package android.os;

/**
 * 方案 B 自产 minimal stub：Android {@code android.os.Parcel}。
 *
 * <p>仅作为 {@link Parcelable#writeToParcel(Parcel, int)} 的参数类型存在，
 * 满足类链接需要；解析闭包（getString）不会调用 Parcel 写入/读取，故方法体为空实现。
 */
public class Parcel {
    public void writeInt(int val) { }
    public void writeLong(long val) { }
    public void writeString(String val) { }
    public void writeByte(byte val) { }
    public int readInt() { return 0; }
    public long readLong() { return 0L; }
    public String readString() { return null; }
}
