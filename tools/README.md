# Legado 书源工具链（legado-booksource-debug 技能 v1.14.10）

本地化校验与真机语义对齐工具集。核心原则：**本地不建模的语义如实降级为「需真机验证」，绝不跑出与真机不符的假结果**。

> **同步状态（2026-10-26 20:46）**：本目录 15 个脚本已与技能 `scripts/` **逐文件 md5 一致**。
> 本次补齐差距：`test_parse.py` / `validate_booksource.py` 从 v1.14.9 旧版更新到含「`ruleContent.replaceRegex` 在 3.25 是活字段、但必须以 `##` 开头；书源顶层 `replaceRegex` 不是 3.25 字段会被 Gson 静默丢弃」的纠错版。
> 另：`lint/booksource_lint.py`（知识库侧 lint 工具，非技能脚本）新增 `strip_url_options()`。
>
> **独立发布包（给其他会话 / 其他 AI）**：`releases/legado-tools_v1.14.10.zip`（2.5MB，解压即用，不需要装技能；**不含 b2**）。
> B2 真机引擎单独发包：`legado-tools-b2-runtime_v1.14.10.zip`（27MB，含 APK 转出的 4 个 jar + enjarify 修复包 + 已编译 harness，解压即跑）。
> 下载走 Release 附件（raw 对 >20MB 文件返回 403）：https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.14.10-b2.2/legado-tools-b2-runtime_v1.14.10.zip
> ```bash
> curl -L -o legado-tools.zip "https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-tools_v1.14.10.zip"
> unzip -o -q legado-tools.zip -d . && python3 legado-tools/validate_booksource.py 你的书源.json
> ```
> 包内 `AI-USAGE.md` 是写给 AI 的完整使用指引（下载方式 / 依赖 / 常用命令 / 症状对照表）。

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `validate_booksource.py` | 书源结构体检：字段校验、铁律检测、searchUrl `<js>` 返回值契约（返回整体 JSON 对象=ERROR；POST body 预编码=WARN）、charset 死字段检测 |
| `test_parse.py` | 本地规则求值：CSS/XPath/Regex/JSONPath 五路径；`:` 正则列表模式与 `<js>` 容器不本地建模，命中即标「需真机验证」 |
| `verify_booksource.py` | 端到端验证：抓真实页面跑完整规则链 |
| `realcheck.py` | 真机等价检查：带/不带 cookie 对比取证 |
| `bypass_cf.py` | Cloudflare 五秒盾/JS 挑战过法探测 |
| `webview_probe.py` | webView 站点渲染命中探测 |
| `js_layer_check.py` | `<js>` 规则 Node 层执行检查；**列表 `<js>` 返回数组类型闸门**（末段纯 `<js>` 返非数组真机 ClassCastException，链式形态 `<js>…</js>选择器` 不适用）；jsLib 共享作用域建模 |
| `validate_booksource.py` 补充 | 检查 #12「末段纯 `<js>` 列表 + 纯选择器子规则」WARN（真机不解析字符串元素）；空输入口径：0 字节/纯空白文件 exit 2 报错（不静默放行），`[]` 放行 |
| `reverse_crypto.py` / `reverse_font.py` | 加密参数逆向 / 字体反爬(QueryTTF)还原 |
| `fetch_page.py` | 页面抓取（UA/编码/重定向处理） |
| `l0_probe.py` | L0 证伪探针：窄范围快速验证假设 |
| `make_probe_source.py` | 生成诊断探针书源 JSON（用户没电脑也能定位问题） |
| `check_environment.py` | 环境/依赖检测（`--capability live-fetch --network`，清单见 `skill-dependencies.json`） |
| `self_audit.py` | 技能自身一致性审计 |
| `legado_debug_bridge.py` | 调试桥：与 Legado 调试页日志对接 |
| `jsoup_eval/` | Jsoup 规则 Java 求值器（对齐真机 bookList/chapterList 子规则语义；`elem`/`elemrule` 两种模式）：`JsoupRuleEval.java` 源码 + 已编译 `JsoupRuleEval.class` + 随附 `jsoup-1.17.2.jar`，三者齐备可直接 `java -cp` 跑 |

## 用法示例

```bash
# 结构体检（ERROR=0 才可交付）
python3 validate_booksource.py 书源.json

# 环境检测
python3 check_environment.py --capability live-fetch --network

# 书源含 JS 就必须跑 JS 层检查（与结构体检两道，缺一不可）
python3 js_layer_check.py --source 书源.json [--html 夹具.html] [--url URL] [--code 验证码]

# Jsoup 规则求值（jar 已随附）
java -cp jsoup_eval:jsoup_eval/jsoup-1.17.2.jar JsoupRuleEval page.html "tag.a@text"
```

## 设计红线

1. 本地无 Rhino → `<js>` 一律不假装能跑，标「需真机验证」；
2. `:` 正则模式是书籍/目录列表专用，本地不建模；
3. 顶层 `charset` 是 3.25 死字段，只认 searchUrl 行内 options；
4. 空规则/空文档中性跳过，不计失败。
