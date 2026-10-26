package android.os;

/**
 * 方案 B 自产 minimal stub：Android {@code android.os.Parcelable} 接口。
 *
 * <p>legado 的 {@code BookSource} 及其规则实体（SearchRule/ContentRule/...）均
 * {@code implements android.os.Parcelable}。纯 JVM 加载这些类仅要求该接口存在
 * （含嵌套 {@code Creator<T>}），方法体本身由 dex 内真实实现提供，本 stub 不会被调用。
 */
public interface Parcelable {
    /** 真实实现位于 dex 内（BookSource.writeToParcel），此处仅声明。 */
    int describeContents();

    /** 真实实现位于 dex 内；参数类型 android.os.Parcel 由本 stub 包提供。 */
    void writeToParcel(Parcel dest, int flags);

    /** Parcelable 的工厂接口，用于反序列化（dex 内 CREATOR 字段需要其存在）。 */
    interface Creator<T> {
        T createFromParcel(Parcel source);
        T[] newArray(int size);
    }
}
