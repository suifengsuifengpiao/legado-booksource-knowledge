package android.content;
/** 方案 B minimal stub：Intent（仅签名 + 常用构造器）。 */
public class Intent {
    public Intent() {}
    public Intent(String action) {}
    public Intent(String action, android.net.Uri data) {}
    public Intent setData(android.net.Uri data) { return this; }
    public Intent setClassName(String pkg, String cls) { return this; }
}
