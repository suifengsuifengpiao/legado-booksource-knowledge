# 过盾专题：盾的物种分类与 Turnstile 三层死结

> 来源：20 天 17 站实战档案（2026-10-04 ~ 10-24）蒸馏。核心结论：**过盾之前先给盾定性，不同物种的处置手段完全不同，用错手段（如对 Turnstile 写 JS）是架构性无解，不是努力问题。**

## 1. 盾的物种分类（按实战遭遇排序）

| 物种 | 特征 | 代表站 | 处置 | 结论 |
|---|---|---|---|---|
| **Cookie 壳页型** | 首访返回 403 + `location.href="/"` 壳页 + Set-Cookie，带 cookie 二访即过 | book55（无限小说网） | 普通 HTTP + `loginCheckJs` 检测壳页重取，**不用 webView** | ✅ 可过，见《站点档案_book55》 |
| **GoEdge WAF 验证码** | 只放行 `curl/` 前缀 UA；中继站需双 cookie + 会话预热 | 菠萝猫、3Q中文网 | UA 伪装 + PHPSESSID/`__snc` 双 cookie + `_t` 预热 + 每日轮换签名常量正则提取 | ✅ 可过 |
| **CF 五秒盾（JS Challenge，无交互）** | 页面显示"Just a moment..."，约 5 秒自动放行 | 黄金屋（仅 /search 端点） | `searchUrl` 内联 `webView:true` + `webWait≥12000`，让真实内核自己跑完 JS | ✅ 可过（真机实证） |
| **CF Turnstile（交互质询）** | 复选框/图片质询，核心逻辑在 `challenges.cloudflare.com` 跨域 iframe | xs5200（搜索端点） | **无解**，认盾走兜底（见第 3 节） | ❌ 过不去 |
| **altcha（PoW 手动）** | `altcha-widget` 复选框需人点，`auto:"off"` | 纸间阅读（正文） | webJs 检测未 checked 自动 `.click()`，等 `.prose` 渲染出段落 | ✅ 可过（Playwright 复现 t=6s 出 54 段） |

### 关键判别：五秒盾 vs Turnstile

先用**真机浏览器**访问目标页面：自动放行的是五秒盾，要求交互的是 Turnstile。注意真机浏览器能过 ≠ Legado 隐藏 WebView 能过——后者 UA 带 `; wv` 标记、缺 `window.chrome`，CF 一眼识破。黄金屋的实证是：同一条 `/search` 端点，隐藏 WebView 配 `webView:true + webWait:12000` 真机可过。

### 关键判别：altcha 与 Turnstile 为何不同命

altcha 的验证 widget 与正文**同源同页**（ PoW 算完本地提交 `/api/captcha/altcha/verify` 拿 `captcha_token`，5 分钟有效，正文接口带 token 即可），所以 webJs 注入宿主页后能模拟点击；Turnstile 的核心逻辑在 **CF 跨域 iframe** 里，同源策略禁止触碰，Rhino/WebView 都够不着。**同为"人机验证"，能不能 webJs 点，取决于验证组件是否与目标内容同源。**

## 2. Turnstile 三层死结（xs5200 实证，10-23 定论）

| 层 | 障碍 | 实证细节 |
|---|---|---|
| 形态层 | Legado 隐藏 WebView | UA 带 `; wv`、缺 `window.chrome`，CF 识破；切桌面 UA 会被站点 JS 按屏幕宽度/触摸能力检测强制跳回 m 域，改 UA 无用 |
| 执行层 | Turnstile 质询 | 核心逻辑在 challenges.cloudflare.com 跨域 iframe，Rhino 的 window/document/cookie 一行都够不着；webJs 只作用于 WebBook 场景，搜索链路根本不注入 |
| 凭证层 | cf_clearance / wsii.sig | 实测该站**不签发 cf_clearance**，验证态为站长自签 `wsii.sig` cookie，绑设备 TLS 指纹 + IP，跨端移植无效（真机 vConsole + Cookie Editor 双重查证） |

**"写 JS 过盾"为何不行**：同源策略（跨域 iframe 碰不到）/ 环境证明（验 window.chrome、navigator.webdriver、Canvas/WebGL/TLS 指纹，Rhino 全没有）/ 服务端验签（cf_clearance 由 CF 私钥签发绑 IP+UA，伪造无效；证件是**发**出来的，不是**算**出来的）。**社区无 Rhino 手搓 Turnstile 成功先例。**

## 3. 盾过不去时的最优终态（按性价比排序）

1. **主搜索走 Bing 兜底**：兜底 searchUrl 直接写 `site:目标域名 + 关键词` 的 Bing 查询，用 Bing 索引当站内搜索使，覆盖面往往比站内还全；
2. **发现页分流**：分类 / 排行榜 / 全本已覆盖"随便看看"场景，多数阅读不必走搜索；
3. **一书多源**：采集站的书在没盾的站通常也有，优先换源；
4. **快速失败**：`webWait` 从 30000 降到 ~10000，别让每次搜索先白等 30 秒。

## 4. webWait 取值参考

| 场景 | 建议值 | 依据 |
|---|---|---|
| CF 五秒盾过盾 | `12000` | 五秒盾经常要更久，5000ms 容易取空导致搜索偶发 0 条（黄金屋 v3 注释写 12000 实际配 5000 的自相矛盾已修复） |
| 已知过不去、快速失败 | `10000` | xs5200 收尾值，减少每次搜索的白等 |

## 5. JS 在过盾链路里的真实角色

从来是**"盾后打扫"**，不是"盾前刚盾"：

- book55 的 `loginCheckJs`：跟随 `Set-Cookie` 重取 + 剔除 `ss_search_delay` 冷却 cookie——盾放过之后清理战场；
- 黄金屋：`webView:true + webWait:12000` 过的是五秒盾（无交互 JS Challenge，真内核自己跑完就放行）——借力真实内核，不是 Rhino 刚盾；
- 纸间阅读：webJs 点击 altcha 复选框——验证组件与内容同源时才成立。
