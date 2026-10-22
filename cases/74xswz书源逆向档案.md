# 74xswz（74小说网）书源逆向档案 · v2

> 更新：2026-10-06 · 书源 `74xswz.json`（已真机验证可用）
> 相比 v1 的核心变化：**搜索签名从「抽常量复刻」改为「直接执行官方 signJs」**，详见 §5。

---

## 1. 站点基本信息

| 项 | 值 |
|---|---|
| 站点 | `https://www.74xswz.com` |
| WAF | GoEdge，**只放行 `curl/` 前缀的 User-Agent**，其他 UA 一律拦截 |
| 书源 UA | `curl/8.5.0` |
| 站点自身搜索 | **无**。首页搜索框是 `onclick="location.href='https://www.rrssk.com/003Q.html'"`，直接跳第三方中继 |

### 频道结构

- 男生 `/list-1/`、女生 `/list-2/`、二次元 `/list-3/`
- 分类页 `/list-N/`，翻页 `/list-N-P/`
- 书源 `exploreUrl` 共 18 条：**男生 13 + 二次元 5，不含女生**（用户明确要求剔除）
- 前缀名为 `男生·` / `二次元·`；分页用 `{{page==1?'':'-'+page}}`
- `ruleExplore.bookList = //div[contains(@class,"cateIBox")]//ul/li`

---

## 2. 目录（ruleToc）

书籍页有**两个**目录容器，顺序是：

1. `div.direList` — 最新章节，末 20 章，在**前面**
2. `div.direList.listData` — 前段章节，前 100 章，在**后面**

**坑**：v1 只从 `listData` 截取，导致末段章节名丢失。现改为从第一个 `direList` 起截取，到 `speIBox` / `rankSBox` / `bookBox` 结束。

服务端写入的章节名**末尾粘了序号**（如 `第43章 乔迁之喜43`），真实章节名优先取 DOM。

### AES 目录接口（DOM 取不全时的补充）

```
POST https://www.74xswz.com/index.php?action=loadChapterPage
body: data=<base64(AES-CBC-Pkcs7({"id":"<bookId>","page":<n>}))>
key : 9Ug2kRcmX9MxFyRR0lbX4OayTqgVtsQ2
iv  : 7011822584532415
响应: 明文 JSON，含 chaptername / chapterurl / chapterorder
```

**有频率限制**（调试时本机 IP 曾被限流）。Legado 侧用 `java.aesEncodeToBase64String(明文, KEY, 'AES/CBC/PKCS5Padding', IV)`。

### 规则写法要点

`chapterList` 必须以 `<js>…</js>//a` 链式收尾。原因：Legado `AnalyzeRule.getElements()` 要求**最后一步返回 List**；纯 `<js>` 返回 String 会抛 `ClassCastException: String cannot be cast to List`。

---

## 3. 正文（ruleContent）

两种模板并存：

- **A 分章型**：`/book/{id}-{n}.html`，底部是「下一章」
- **B 分页型**：`/book/{id}-{n}-{p}.html`，中间页是「下一页」，末页才是「下一章」

```js
nextContentUrl = //a[contains(text(),"下一页")]/@href||//a[contains(text(),"下一章")]/@href
```

Legado 的 `||` 语义是**取第一个非空**（`&&` 才是合并全部），所以「下一页」优先、「下一章」兜底。
> 注：`||` 由 `AnalyzeByXPath` 内部的 `splitRule("&&","||","%%")` 处理，是支持的（早期误判为不支持）。

---

## 4. 搜索链路（rrssk 中继）

```
https://www.rrssk.com/003Q.html        ← 中转页，取 _t、signJs 路径、PHPSESSID
  ↓
https://www.rrssk.com/?action=signJs&v=<版本>-<日期>   ← 取一次性 __snc + 当日算法源码
  ↓
POST https://www.rrssk.com/?action=search
  body: keyword=<urlencoded>&_t=<t>&_ts=<ts>&_s=<签名>
  ↓
结果页 /?action=find&v=<v>&q=<q>&page=<n>
```

关键约束：

- **`__snc` 一次性**，每次搜索必须重走完整流程，不能复用
- **`_ts` 必须与签名使用的 `ts` 完全一致**（v14 曾两次取时间戳，跨秒就 403，已修）
- 翻页走 `cache.putMemory/getFromMemory` 复用 `v`/`q`，不重新签名

---

## 5. 签名机制：为什么改成「执行官方源码」

### 每日轮换的不是常量，是整套内核

| 版本 | 内核 |
|---|---|
| v14 | `f=(f*K1 + c + K2)>>>0` 逐字符累加 |
| v17（2026-10-06） | FNV-1a 变体 + xorshift 混合（`u4=(u4^(u4>>>13))*3481`，循环 38543 次） |

v17 实测源码：

```js
var f2=60825,i5=27443,w=38543,u4=2166136261;
for(s9=0;s9<s.length;s9++){ u4=(u4^s.charCodeAt(s9))>>>0; u4=(u4*f2)>>>0;
                            u4=(u4+s9*i5+t.charCodeAt(s9%t.length))>>>0; }
u4=(u4^ts)>>>0;
for(y3=0;y3<38543;y3++){ u4=((u4^(u4>>>13))*3481)>>>0; }
u4=(u4^(u4>>>16))>>>0;
a8 = parseInt(hex8(u4),16) ^ ((_ad52ca*7+3)>>>0)
```

**结论：抽常量复刻必然过期**，抠得再准也没用。

### 两道闸只唬页面，不唬服务端

v17 在 `window.__SIGN.f` 里加了两道检查：

```js
if(_ad52ca!==33) return "00000000";   // DOM 指纹，14 项三元累加
if(_b13bf3!==1)  return "00000000";   // 必须有 isTrusted 的真实交互
```

实测：用**纯算式签名**（零浏览器、零鼠标点击）直接 POST，**服务端返回 200 并给出结果页**。
→ 服务端只校验最终那 8 位十六进制，两道闸只在「页面自己算签名」时生效。

> v1 曾据此误判「Legado 过不了交互闸，搜索不可行」，该结论**已推翻**。

### v2 方案：直接 eval 官方 signJs

1. 拉回 signJs 源码
2. 正则把 DOM 指纹三元 `...?N:0;` 改写成 `+=N;` → `_ad52ca` 正好累加到 **33**，源码里 `document.` 残留 **0** 处
3. 伪造 `window.addEventListener` 收集回调，eval 后派发 `{isTrusted:true}` → `_b13bf3=1`
4. 调 `window.__SIGN.f(enc(key), _t, ts)`；找不到时自动扫描 window 上其他对象兜底

**只要官方继续用 `window.__SIGN.f` 这个接口名，算法换什么内核都自动跟随。**

### 验证

- 下载 Rhino 1.7.14 实测：函数内 `eval` 可用，签名与手算**完全一致**
- 真 Rhino 端到端（mock 回放）：第 1 页返回 `action=find&v=16&q=…`，第 2 页命中翻页缓存
- 真实 POST：纯算式签名 200，结果页 39KB

---

## 6. Legado 规则引擎踩坑记录

| 现象 | 原因 |
|---|---|
| `ClassCastException: String cannot be cast to List` | `chapterList` 最后一步必须是返回 List 的规则（用 `//a` 收尾） |
| 正则全页匹配 `<a>` 导致第 1 章名错位 | 把「在线阅读」按钮当成了章节，需限定在目录容器内 |
| 末段章节名丢失 | 只截了 `listData`，漏掉前面的 `direList`（末 20 章） |
| 调试时 AES 接口 `code:-1` | 本机 IP 被限流，非规则问题 |

---

## 7. 维护指引：真机调试日志

书源内置 `[blm]` 前缀日志（Legado 书源调试可见）：

| 日志 | 含义 | 是否需要改书源 |
|---|---|---|
| `p5 ok v=xx` | 成功 | 否 |
| `p3 eval fail: …` | Rhino 执行官方源码失败（日志附源码前 140 字符） | **是** |
| `p3 no __SIGN.f keys=…` | 官方改了接口名 | **是** |
| `p4 fail head=搜索凭证失效` | 签名被拒 / 触发限流，通常过会儿重试即可 | 否 |
| `p2 snc fail` | 未拿到 `__snc` cookie | 检查网络 |

**只有 `p3 eval fail` 和 `p3 no __SIGN.f` 需要维护**，换算法内核不需要。

---

## 8. 归档位置

- 网盘目录 `IcIEGGNjIEGI`：`74xswz.json`（书源本体）、`74xswz书源逆向档案.md`（本文件）
- 同目录另有：`菠萝猫书源修复总结.md`、`站点档案_菠萝猫.md`
