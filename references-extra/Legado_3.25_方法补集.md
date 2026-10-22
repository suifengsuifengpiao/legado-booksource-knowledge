# Legado 3.25 方法清单补集（dex 提取）

> **本文件只列 `legend-js-api.md` / `apk-3.25-verified-facts.md` 未覆盖的方法**，避免重复。
> 常用网络请求、webView、字体验证码等见那两个文件；本文件按「写源时突然要用、又不确定有没有」的场景组织。
> 取证对象：`legado_app_3.25.apk`（classes.dex×4）。复现方式见文末 §6。

## 1. 对称加解密（本次 74xswz 书源踩过，`legend-js-api.md` 未收）

**参数顺序一律是 `(data, key, transformation, iv)`**，`transformation` 填标准名如 `AES/CBC/PKCS5Padding`。

| 方法 | 返回 | 说明 |
|---|---|---|
| `aesEncodeToBase64String(data, key, transformation, iv)` | String | **最常用**，一步出 base64 密文 |
| `aesEncodeToBase64ByteArray(data, key, transformation, iv)` | byte[] | |
| `aesEncodeToString(data, key, transformation, iv)` | String | 非 base64 版 |
| `aesEncodeToByteArray(data, key, transformation, iv)` | byte[] | |
| `aesEncodeArgsBase64Str(a,b,c,d,e)` | String | 五参重载 |
| 解码侧（`aesBase64DecodeToString` / `aesDecodeToString`） | String | ⚠️ **没有** `aesDecodeToBase64String` 这个方法（dex 全量核对无此法），别照编码侧名字反推 |
| `aesBase64DecodeToByteArray` / `aesDecodeToByteArray` | byte[] | |
| `aesDecodeArgsBase64Str(a,b,c,d,e)` | String | |

**DES 同构四件套**（参数同为 data,key,transformation,iv）：
`desEncodeToString` `desEncodeToBase64String` `desDecodeToString` `desBase64DecodeToString`

**3DES 五参组**：
`tripleDESEncodeBase64Str` `tripleDESEncodeArgsBase64Str` `tripleDESDecodeStr` `tripleDESDecodeArgsBase64Str`

**摘要 / MAC**（dex 全量核对，方法名以本节为准，不要按泛称猜）：
`digestBase64Str(data, alg)` `HMacBase64(data, key, alg)` `HMacHex(data, key, alg)`

> 已验证实例：74xswz 目录 AES 接口用
> `java.aesEncodeToBase64String(json, KEY, 'AES/CBC/PKCS5Padding', IV)` 与服务端对齐。

## 2. 压缩包：不用落地就能读.zip/.7z/.rar 内容

| 方法 | 说明 |
|---|---|
| `getZipStringContent(pathOrUrl, entryName[, charset])` | **直接取压缩包内某文件内容** |
| `get7zStringContent(pathOrUrl, entryName[, charset])` | 同上，7z |
| `getRarStringContent(pathOrUrl, entryName[, charset])` | 同上，rar |
| `getZipByteArrayContent` / `get7zByteArrayContent` / `getRarByteArrayContent` | 字节版，配合封面/字体解密 |
| `unzipFile(path)` / `un7zFile(path)` / `unrarFile(path)` / `unArchiveFile(path)` | 解压到本地并返回路径（自动判格式） |
| `getTxtInFolder(path)` | 读文件夹下所有 txt 并拼接 |

> 打包类书源（整本 txt.zip 下载）省掉「下载→解压→读取」三步。

## 3. 其余工具方法

| 方法 | 说明 |
|---|---|
| `getSource()` → `BaseSource` | **拿到当前书源对象自身**，可读 `bookSourceUrl` 等，免硬编码 |
| `base64Encode(s[, flags])` | `legend-js-api.md` 只写了 decode 侧 |
| `hexEncodeToString(s)` / `hexDecodeToString(s)` / `hexDecodeToByteArray(s)` | 十六进制互转 |
| `htmlFormat(html)` | HTML 格式化，正文中文/标签混乱时救急 |
| `utf8ToGbk(s)` | 老站编码转换 |
| `toNumChapter(name)` | 章节名转数字序号 |
| `deleteFile(path)` → boolean | |

## 4. `cache` 带类型读取（`legend-js-api.md` 只列了 6 个基础方法）

| 方法 | 说明 |
|---|---|
| `getInt` / `getLong` / `getFloat` / `getDouble` | 省去 parseInt/parseFloat |
| `getByteArray(key)` | 缓存二进制（如字体） |
| `getQueryTTF(key)` | 缓存 QueryTTF，避免每次重解析字体 |
| `put(key, value, seconds)` / `putFile(key, path, seconds)` | **第三参是有效期秒数** |
| `get(key)` / `delete(key)` / `deleteMemory(key)` | |

## 5. 发现页结构限制（dex 实证）

```kotlin
ExploreKind(title: String, url: String, style: Style)
```

**只有三个属性，没有 group 字段** → Legado 发现页**结构上不可能分组**。
想让分类看起来有层级，只能用 `男生·都市` 这类前缀伪装，别浪费时间找分组字段。

`Style` 支持 flexbox 微调（JSON 中嵌套 style 对象）：
`layout_flexBasisPercent` `layout_flexGrow` `layout_flexShrink` `layout_wrapBefore` `layout_alignSelf`

## 6. 复现方法（换版本时用）

```bash
pip3 install androguard
unzip -o legado_app_x.xx.apk 'classes*.dex'
```

```python
from androguard.core.dex import DEX
d = DEX(open('classes3.dex','rb').read())
for cls in d.get_classes():
    if str(cls.get_name()) == 'Lio/legado/app/help/JsExtensions;':
        for m in cls.get_methods():
            print(m.get_name(), m.get_descriptor())
```

**提取实体字段 / JSON key**：`cls.get_fields()` 即字段名
**提取死字段 / 运行时常量**：遍历 `m.get_instructions()`，正则抽 `const-string`

关键类位置（3.25）：
`io.legado.app.help.JsExtensions` / `CacheManager` / `model.analyzeRule.AnalyzeUrl$UrlOption`
`data.entities.BookSource` / `data.entities.rule.{Search,Toc,Content,Explore,BookInfo,Review}Rule`

## 7. dex 方法真值表（**写 `java.xxx()` 前先在这里 grep**）

> 来历：本文件第一版靠人工罗列方法名，1.13.14 自检时用 dex 反向核校，**抓出 `aesDecodeToBase64String` 这个方法根本不存在**
> （顺着编码侧名字反推出来的）。教训是手写清单不可靠，于是把这版**全量真值表**直接贴上来——
> 描述符即参数顺序，比任何表格都不会主观。

#### `JsExtensions`（86 个公开方法，已剔除 `$` 合成方法）

```
HMacBase64                         (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
HMacHex                            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesBase64DecodeToByteArray         (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)[B
aesBase64DecodeToString            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesDecodeArgsBase64Str             (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesDecodeToByteArray               (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)[B
aesDecodeToString                  (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesEncodeArgsBase64Str             (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesEncodeToBase64ByteArray         (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)[B
aesEncodeToBase64String            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
aesEncodeToByteArray               (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)[B
aesEncodeToString                  (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
ajax                               (Ljava/lang/Object;)Ljava/lang/String;
ajaxAll                            ([Ljava/lang/String;)[Lio/legado/app/help/http/StrResponse;
androidId                          ()Ljava/lang/String;
base64Decode                       (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
base64DecodeToByteArray            (Ljava/lang/String; I)[B
base64Encode                       (Ljava/lang/String; I)Ljava/lang/String;
bytesToStr                         ([B Ljava/lang/String;)Ljava/lang/String;
cacheFile                          (Ljava/lang/String; I)Ljava/lang/String;
connect                            (Ljava/lang/String; Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;
createAsymmetricCrypto             (Ljava/lang/String;)Lw6/a;
createSign                         (Ljava/lang/String;)Lw6/b;
createSymmetricCrypto              (Ljava/lang/String; [B [B)Lcn/hutool/crypto/symmetric/SymmetricCrypto;
deleteFile                         (Ljava/lang/String;)Z
desBase64DecodeToString            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
desDecodeToString                  (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
desEncodeToBase64String            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
desEncodeToString                  (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
digestBase64Str                    (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
digestHex                          (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
downloadFile                       (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
encodeURI                          (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
get                                (Ljava/lang/String; Ljava/util/Map;)Lorg/jsoup/Connection$Response;
get7zByteArrayContent              (Ljava/lang/String; Ljava/lang/String;)[B
get7zStringContent                 (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
getCookie                          (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
getFile                            (Ljava/lang/String;)Ljava/io/File;
getRarByteArrayContent             (Ljava/lang/String; Ljava/lang/String;)[B
getRarStringContent                (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
getSource                          ()Lio/legado/app/data/entities/BaseSource;
getTxtInFolder                     (Ljava/lang/String;)Ljava/lang/String;
getVerificationCode                (Ljava/lang/String;)Ljava/lang/String;
getWebViewUA                       ()Ljava/lang/String;
getZipByteArrayContent             (Ljava/lang/String; Ljava/lang/String;)[B
getZipStringContent                (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
head                               (Ljava/lang/String; Ljava/util/Map;)Lorg/jsoup/Connection$Response;
hexDecodeToByteArray               (Ljava/lang/String;)[B
hexDecodeToString                  (Ljava/lang/String;)Ljava/lang/String;
hexEncodeToString                  (Ljava/lang/String;)Ljava/lang/String;
htmlFormat                         (Ljava/lang/String;)Ljava/lang/String;
importScript                       (Ljava/lang/String;)Ljava/lang/String;
log                                (Ljava/lang/Object;)Ljava/lang/Object;
logType                            (Ljava/lang/Object;)V
longToast                          (Ljava/lang/Object;)V
md5Encode                          (Ljava/lang/String;)Ljava/lang/String;
md5Encode16                        (Ljava/lang/String;)Ljava/lang/String;
post                               (Ljava/lang/String; Ljava/lang/String; Ljava/util/Map;)Lorg/jsoup/Connection$Response;
queryBase64TTF                     (Ljava/lang/String;)Lio/legado/app/model/analyzeRule/QueryTTF;
queryTTF                           (Ljava/lang/Object; Z)Lio/legado/app/model/analyzeRule/QueryTTF;
randomUUID                         ()Ljava/lang/String;
readFile                           (Ljava/lang/String;)[B
readTxtFile                        (Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
replaceFont                        (Ljava/lang/String; Lio/legado/app/model/analyzeRule/QueryTTF; Lio/legado/app/model/analyzeRule/QueryTTF; Z)Ljava/lang/String;
s2t                                (Ljava/lang/String;)Ljava/lang/String;
startBrowser                       (Ljava/lang/String; Ljava/lang/String;)V
startBrowserAwait                  (Ljava/lang/String; Ljava/lang/String;)Lio/legado/app/help/http/StrResponse;
strToBytes                         (Ljava/lang/String; Ljava/lang/String;)[B
t2s                                (Ljava/lang/String;)Ljava/lang/String;
timeFormat                         (J)Ljava/lang/String;
timeFormatUTC                      (J Ljava/lang/String; I)Ljava/lang/String;
toNumChapter                       (Ljava/lang/String;)Ljava/lang/String;
toURL                              (Ljava/lang/String; Ljava/lang/String;)Lio/legado/app/utils/JsURL;
toast                              (Ljava/lang/Object;)V
tripleDESDecodeArgsBase64Str       (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
tripleDESDecodeStr                 (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
tripleDESEncodeArgsBase64Str       (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
tripleDESEncodeBase64Str           (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
un7zFile                           (Ljava/lang/String;)Ljava/lang/String;
unArchiveFile                      (Ljava/lang/String;)Ljava/lang/String;
unrarFile                          (Ljava/lang/String;)Ljava/lang/String;
unzipFile                          (Ljava/lang/String;)Ljava/lang/String;
utf8ToGbk                          (Ljava/lang/String;)Ljava/lang/String;
webView                            (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
webViewGetOverrideUrl              (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
webViewGetSource                   (Ljava/lang/String; Ljava/lang/String; Ljava/lang/String; Ljava/lang/String;)Ljava/lang/String;
```

#### `CacheManager`（16 个公开方法，已剔除 `$` 合成方法）

```
<clinit>                           ()V
<init>                             ()V
delete                             (Ljava/lang/String;)V
deleteMemory                       (Ljava/lang/String;)V
get                                (Ljava/lang/String;)Ljava/lang/String;
getByteArray                       (Ljava/lang/String;)[B
getDouble                          (Ljava/lang/String;)Ljava/lang/Double;
getFile                            (Ljava/lang/String;)Ljava/lang/String;
getFloat                           (Ljava/lang/String;)Ljava/lang/Float;
getFromMemory                      (Ljava/lang/String;)Ljava/lang/Object;
getInt                             (Ljava/lang/String;)Ljava/lang/Integer;
getLong                            (Ljava/lang/String;)Ljava/lang/Long;
getQueryTTF                        (Ljava/lang/String;)Lio/legado/app/model/analyzeRule/QueryTTF;
put                                (Ljava/lang/String; Ljava/lang/Object; I)V
putFile                            (Ljava/lang/String; Ljava/lang/String; I)V
putMemory                          (Ljava/lang/String; Ljava/lang/Object;)V
```
