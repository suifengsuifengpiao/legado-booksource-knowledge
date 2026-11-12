# 设备侧诊断（用户没电脑时的主力方案）

流程位置：主流程第七步，完整流程见 [workflow-detail.md](workflow-detail.md)。
前提：**默认用户只有手机**，直接按方案 A/B（探针 / App 内调试界面）走；只有用户主动说"有电脑且同局域网"才用方案 C（调试桥）。
别推荐对方用不了的方案，也别反复追问——这个答案对同一用户是固定的。

---

### 第七步：设备侧诊断（用户没电脑时的主力方案）

> **血泪教训**：书源在沙盒/服务器能跑通，≠ 在用户手机能跑通。真机有独立的网络出口、WebView 实现、Cookie 存储、Rhino 版本差异。凡是"导入 App 后搜索空/404/报错但沙盒正常"的问题，**必须拿到设备侧真实返回**，而不是反复改规则猜根因。
>
> **方案选择由第零步的环境确认决定**：没电脑 → 方案 A（主力）；不愿装额外书源 → 方案 B；有电脑且同网 → 方案 C。

#### 方案 A：诊断探针书源（没电脑也能做，首选）

思路：不做任何外部连接，而是**让 App 自己把诊断结果打印出来**。探针本身是一个正常书源，
走 Legado 完整请求链路（含 `loginCheckJs`/cookie/header/charset），但在搜索结果阶段用 `@js`
把**设备侧真实拿到的东西**逐条拼成"书名"显示。用户搜任意词，列表就是一份诊断报告。

```bash
python3 scripts/make_probe_source.py --url https://www.yndonie.com \
    --search-url "https://www.yndonie.com/modules/article/search.php?searchkey={{key}}&searchtype=articlename" \
    --charset UTF-8 --login-check-js ./login_check.js --out ./yndonie_probe.json
```

一次性生成 **A/B 两个探针**（互为备份，避免某种写法在该版本 App 上不生效）：
- **A**：`bookList` 用 `@js` 直接产出诊断数组 → 列表每行一条；`name` 用 `@js:result`
- **B**：`bookList` 用 XPath `//body` → `name` 用 `@js` 输出整份报告（不依赖 `@js` 数组是否被支持）

探针报告的 8 项内容（已用真实站点源码在本地 Node 里跑通验证）：

| 项 | 内容 | 能定位什么问题 |
|---|---|---|
| ① | `java` 对象上实际可用的方法 | API 差异（如某版本没有 `urlEncode`/`dnsIp`） |
| ② | 是否命中验证墙及类型 | 明文 cookie 可解（靠 searchUrl `<js>` 或 WebView+CookieJar 过）/ 已改加密不可解 / CF 盾 |
| ③ | `is_human` cookie 是否已写入 | 反映 CookieJar 是否落库——本 App 下 `loginCheckJs` 在普通 HTTP 链路每次请求后执行、会把 `is_human` 写进 CookieJar（`getLoginHeader` 自动带上；走 webView 的站不触发）；若没写，检查 loginCheckJs 是否生效 |
| ④ | 乱码替换符 `�` 数量 | 抓取编码与页面实际编码不一致（`--charset` 写进 searchUrl 行内选项 `{"charset":"..."}`；顶层 charset 是死字段，写了不生效） |
| ⑤ | 搜索结果特征命中 | 列表选择器该往哪写 |
| ⑥ | 设备拿到的前 150 字 | 直接看真机拿到的是验证页还是真内容 |
| ⑦ | 标题/长度判断错误页 | 404/403/空响应 |
| ⑧ | 页面是否含搜索词 | 搜索请求有没有真发出去 |

**给用户的话术**（照抄即可）：
> 这个文件里是两个"诊断探针"书源，App → 书源管理 → 导入。导入后在**搜索框搜任意词**（搜"的"就行），
> 结果列表里显示的不是小说，是诊断信息。给两个探针都搜一次，**截图发我**。看完删掉就行。

**判读要点**：② 显示"自建验证页" → 用 searchUrl `<js>` 两步过墙（明文 cookie 可解）；② 显示"CF 盾" →
用 WebView + `enabledCookieJar:true` 过（③ 看 CookieJar 是否落库）；② 显示"无"且 ⑥ 是正常内容 → 网络没问题，
那就是**解析规则**的问题，回到第三步用 `test_parse.py` 核对选择器。

#### 方案 B：用 App 自带调试界面（零导入成本）

App 内书源调试界面的输出可以**长按复制 / 截图 / 分享**。让用户把整段输出发回来（或截图），
按第六步的知识解读即可。适合用户不想导入额外书源的场景。

#### 方案 C：Web 服务调试桥（**仅当用户有电脑且同局域网**）

**协议已核对到具体实现（开源阅读 3.25，jadx 反编译 `classes3.dex` 逐行确认，非猜）**：

| 事实 | 证据位置 | 结论 |
|---|---|---|
| HTTP 端口默认 **1122** | `service/WebService.java`：`getInt("webPort", 1122)` | 用户改过端口要跟着改 `--port` |
| WebSocket 端口 = HTTP **+1**（1123） | `WebService.java`：`new WebSocketServer(c + 1)` | 脚本已自动 +1，别手填错 |
| 书源必须先入库 | `web/HttpServer$serve$1.java`：`/saveBookSource → d.R(postData)` | 所以脚本第一步永远是 POST 推送 |
| 调试端点 | `web/WebSocketServer.java`：`/bookSourceDebug → BookSourceDebugWebSocket` | 另有 `/searchBook`、`/rssSourceDebug` |
| 消息格式 | `...$onMessage$1.java`：Gson 解析 `Map<String,String>`，取 `tag`/`key` | 必须 `{"tag":书源URL,"key":调试内容}` |
| `tag` 就是 `bookSourceUrl` | 同上：`getBookSourceDao().getBookSource(tag)` | 书源**必须有 `bookSourceUrl`**，否则调不起来 |
| 输出是纯文本 | `...$printLog$1.java`：`send(String)`；`state == -1 \|\| 1000` 时 `close(1000,"调试结束")` | 收到"调试结束"即结束；成功标志是"解析完成" |

**准备（Phase 0）**：让用户做两件事——
1. 手机「开源阅读」App 打开 **Web 服务 / Web 调试**（设置 → 网络 → Web 服务），记下通知栏显示的 IP 与端口（默认 **1122**）；
2. 确认运行脚本的电脑与手机**同一局域网、能 ping 通手机 IP**（手机锁屏会断网，调试时保持亮屏）。

**连接真机跑规则**（脚本在 `scripts/legado_debug_bridge.py`，纯 stdlib，无需装包；已用模拟 Legado 服务做过端到端自测）：

```bash
# 搜索（key 缺省自动取 ruleSearch.checkKeyWord）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="剑来" --phase 1
# 发现（不给 key 时自动从 exploreUrl 取第一个分类，并已把相对路径拼成绝对 URL）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --phase 2
# 详情 / 目录 / 正文（必须显式给 key；--key 一定要用等号形式，否则 --https:// 会被当成选项）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="https://www.yndonie.com/book/123/" --phase 3
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="++https://.../read/123" --phase 4
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="--https://.../chapter/1.html" --phase 5
# 一次跑多个阶段 + 把输出落盘（便于把整段贴回来分析）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json \
    --phase 1,3,5 --keys '{"1":"剑来","3":"https://.../book/123/","5":"--https://.../1.html"}' \
    --timeout 180 --out ./device_debug.log
# 只推送书源到手机（不调试）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --save-only
# 跨网络跳板（脚本与手机不互通时走代理）
python3 scripts/legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="剑来" --phase 1 --proxy http://127.0.0.1:7898
```

**`--key` 决定跑哪个阶段（App 侧 `model/n0.java → f()` 的真实判定顺序）**：

| 判定顺序 | key 形态 | 阶段 | 示例 |
|---|---|---|---|
| 1 | `http(s)://` 开头 | 详情 | `https://站点/book/123/` |
| 2 | 含 `::` | 发现（取 `::` 后的部分为 URL） | `玄幻::https://站点/xssort_1_1.html` |
| 3 | `++` 前缀 | 目录 | `++https://站点/read/123` |
| 4 | `--` 前缀 | 正文 | `--https://站点/chapter/1.html` |
| 5 | 其他 | 搜索 | `剑来` |

写错了就跑错阶段——脚本会按这张表自检并在不一致时告警。**注意**：调试正文/目录时 App 构造的是"空壳 Book"（书名等字段为 null），若规则用到 `book.name` 之类会拿到空值，这是调试环境的固有限制，不代表线上有问题。

- 脚本会 POST 书源到手机、经 WebSocket `/bookSourceDebug` 让 App 真机解析，并**原样回显设备返回的每一步调试输出**（含实际拿到的 HTML、报错、"解析完成"）；
- 用户把整段输出贴回来（或给 `--out` 落盘），就能**精准定位**是验证页没过、cookie 没设、选择器不匹配还是网络被拦——这是唯一能终结"沙盒正常但手机不行"死循环的办法；
- `--phase` 对应 1=搜索 2=发现 3=详情 4=目录 5=正文；exit 0=全部阶段返回"解析完成"（真机可用）。

**调试纪律（配合 `java.log`）**：真机调试命中异常字段时，在对应规则里插 `<js>java.log(结果变量);</js>` 打印中间值，再连桥看日志，**禁止盲改选择器**。
