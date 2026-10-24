# 站点档案：book55（无限小说网）

> 建档 2026-10-11（v1.4b 定稿，真机验证通过）。**cookie 壳页型过墙的标准样本 + loginCheckJs 误判坑的教科书案例。**

## 1. 站点概况

| 项 | 值 |
|---|---|
| 域名 | book55（shumi99 系，无限小说网） |
| 过墙型 | **Cookie 壳页型**：首访（新 IP/cookie 失效）返回 `403 + window.location.href="/"` 壳页 + Set-Cookie，浏览器带 cookie 二访即过墙 |
| 处置 | 普通 HTTP + `loginCheckJs` 检测壳页重取，**不用 webView** |
| 终态 | v1.4b：Cookie 双保险，真机验证通过 |

## 2. loginCheckJs 标准写法（3.25 规范）

```js
var b = '' + (result.body() || '');
if (b && b.indexOf('location.href =') > -1) {   // 注意：匹配赋值形态，带 =
    java.connect(result.url());                  // 带 cookie 重取壳页
}
result;                                          // 末尾必须返回 result
```

铁律：**不能带 `<js>` 标签**（直接是 JS 代码）、**返回值必须带 `result`**。

## 3. ⚠️ 头号误判坑：`indexOf('location.href')` 太宽

v1.1 用 `indexOf('location.href')` 判断壳页，结果**正常的章节页被误判成壳页反复重抓**，抓回来的都是书页（含"查看全部章节 ↓"、无正文），表现为**正文空**。

根因：章节页的阅读记录追踪脚本 `read.set('/97_97344/', window.location.href, ...)` 含字面量 `window.location.href`。

**判别法**：壳页是**赋值** `location.href =`（带 `=`），章节页是**参数** `window.location.href,`（逗号）。两者能干净区分。

> 同类教训：壳页特征匹配要取"赋值/跳转"形态，不能取裸字面量——正常页面到处都可能有 `location.href`。

## 4. Cookie 双保险（v1.4b 核心配置）

站点对搜索有冷却 cookie（`ss_search_delay`）限流，发作时"搜一次就冷却"：

1. **断自动落库**：`enabledCookieJar=false`——不让阅读器自动维护 CookieJar，避免脏 cookie 反复触发冷却；
2. **末端按名剔除**：`loginCheckJs` 里按名剔除 `ss_search_delay` 冷却 cookie（token 由 while 循环内从 `Set-Cookie` 响应头手动写，不看 CookieJar 开关）；
3. **searchUrl 内不放 JS**：实测 searchUrl 内的 `<js>`/`@js:` 在该阅读器不执行，**纯 URL 才稳**。

## 5. 版本演进史（失败链比成功更有教学价值）

| 版本 | 现象 | 根因 |
|---|---|---|
| v1.6 | 搜索全崩 | cookie 自动落库撞冷却 |
| v1.5 | 正文 8 秒 | 壳页误判链（见第 3 节）叠加 |
| v1.4b | 定稿 | 双保险 + 赋值形态匹配 |

> 用户当时的质问："越来越差了，你到底验没验证呢？"——教训：**每次只改一个变量，改完立即真机验证**，多变量并发修改出的回归无法归因。

## 6. 其他规则要点

- 目录：`.chapterlist a`（实测命中 1574 且无噪音）；
- 正文容器：`.readcontent`（id=rtext）；
- 详情页 = 目录页三合一，`ruleBookInfo.tocUrl` **留空**；
- 目录里有一条假章节入口"查看全部章节 ↓"（在 `dl dd` 里、类 `visible-xs`）需排除；
- 搜索 POST body 编码需按站点实际表单对齐。
