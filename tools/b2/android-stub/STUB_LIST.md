# Android 最小桩清单（T2，方案 B）

> 策略：描述符驱动 + 链接即补循环。仅桩 `AnalyzeRule` 解析闭包真实触碰的 `android.*` 类/方法，
> 方法体返回安全默认值，**零外部依赖**。`android-stub.jar` 由 `build.sh` 编译 24 个桩类生成。

## 桩类清单（共 24 类）

| 桩类 | 类型 | 桩的方法 / 常量 | 为何需要 |
|---|---|---|---|
| `android.text.TextUtils` | class | `isEmpty(CharSequence)`、`equals`、`join`、`isDigitsOnly` | `AnalyzeRule` 直接调用 `TextUtils.isEmpty`（字节码实证 4 处） |
| `android.os.Parcelable` | interface | `describeContents()`、`writeToParcel(Parcel,int)`、`Creator<T>` | `BookSource` 及规则实体均 `implements Parcelable`，加载即需此接口 |
| `android.os.Parcelable$Creator<T>` | interface | `createFromParcel`、`newArray` | `BookSource.CREATOR` 静态字段需要其存在 |
| `android.os.Parcel` | class | `writeInt/readInt/...`（空实现） | 作为 `writeToParcel` 参数类型满足链接 |
| `android.os.Build` | class | `MODEL/BRAND/DEVICE/...` 常量 | Rhino evalJS 初始化读取构建信息 |
| `android.os.Build$VERSION` | class | `SDK_INT=0`、`RELEASE="0"` | 同上（Glide/legado 探测） |
| `android.os.Bundle` | class | `put/getString/Int/Boolean`、`Parcelable` 读写 | 个别书源 `Uri.parse`/参数构造时触碰 |
| `android.os.Looper` | class | `getMainLooper/myLooper`（返回 null） | Glide 探测路径占位 |
| `android.content.Context` | **abstract class**（非 interface！） | `getPackageName/getCacheDir/getFilesDir/getSharedPreferences/...` 抽象方法 | dex 代码按“类”使用 `Context`（如 `Context.class`），故必须声明为抽象类，否则 `IncompatibleClassChangeError` |
| `android.content.SharedPreferences` | interface | `getString/getInt/...`、`Editor`、`OnSharedPreferenceChangeListener` | `Context.getSharedPreferences` 返回类型 |
| `android.content.ContentResolver` | class | （空） | `Context.getContentResolver` 返回类型 |
| `android.content.pm.PackageManager` | class | （空） | `Context.getPackageManager` 返回类型 |
| `android.content.Intent` | class | 构造器、`setData/setClassName` | `Context.startActivity` 参数 |
| `android.content.IntentFilter` | class | 构造器、`addAction` | `registerReceiver` 参数 |
| `android.content.BroadcastReceiver` | abstract class | （空） | `registerReceiver` 参数 |
| `android.content.res.Resources` | class | （空） | `Context.getResources` 返回类型 |
| `android.net.Uri` | abstract class | `parse(String)` 返回包裹原串的 stub、`getQueryParameter` 等返回 null | 个别书源拼 URL 时 `Uri.parse` |
| `android.util.Log` | class | `d/i/w/e/v/wtf`（写 stderr，返回 0） | 解析分支调试日志 |
| `android.util.Base64` | class | `decode/encode`（委托 JDK `java.util.Base64`，行为等价） | `AnalyzeUrl` 等网络分支触碰（静态解析不调用） |
| `android.app.ActivityThread` | class | `currentActivityThread/currentProcessName/currentApplication` 返回 null | Glide 静态初始化 `Class.forName("android.app.ActivityThread")` 探测；**仅当触发 Glide 路径时需要**，harness 默认不触发 |
| `android.app.Application` | class | （空占位） | `ActivityThread.currentApplication` 返回类型 |
| `b2.B2Context`（harness 侧，非 stub） | class | 实现 `Context` 全部方法，返回安全默认值 + 真实临时目录 | 实验性：曾用于向 Glide 注入 appCtx（见下“已弃用路径”） |
| `b2.B2SharedPreferences`（harness 侧） | class | `SharedPreferences` 空实现 | 配合 `B2Context` |

## 关键修正记录（链接即补循环实证）

1. **`android.content.Context` 必须是 abstract class 而非 interface**：dex 内 legado 代码按类使用 `Context`
   （`Context.class`、类型强转、AppCompatActivity 继承），初版误写为 interface 导致
   `IncompatibleClassChangeError: Found interface ... but class was expected`。改为抽象类后解决。
2. **移除误桩的 `android.support.v4.media.c`**：该类**并非** Android 框架类，而是 dex 内被 ProGuard 混淆进
   `android.support.v4.media` 包名的 **jsoup/内部助手类**（在 `classes.jar` 真实存在）。初版在 android-stub 里
   造了一个假 `c` 类，因 android-stub.jar 在 classpath 最前而**遮蔽**了真类，导致 jsoup 解析
   `NoSuchMethodError: android.support.v4.media.c.l(String,String)`。移除该桩后，dex 真类正常提供方法，jsoup 全绿。
3. **`Build$VERSION` / `Context` / `Glide` 探测链**：Rhino evalJS 初始化会经 `getShareScope → io.legado.app.model.q1.<clinit> → com.bumptech.glide` 触发 Glide 的 `appCtx` 静态初始化；纯 JVM 下 Glide 要求 Android Application 上下文，会 `IllegalStateException` 乃至 JVM 崩溃（dex2jar/Android 运行时产物）。因此 harness 对 `<js>` 规则**不走 `AnalyzeRule.evalJS`**，改为直接驱动 dex 自带 Rhino（见 `RhinoEngine`），达到等价真机 JS 语义且稳定。

## 验证

```bash
java -noverify -cp "$(build-cp.sh)" b2.B2Harness --region all
# summary: {"total":12,"ok":12,"failed":0}
```
