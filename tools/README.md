# Legado 书源工具链（legado-booksource-debug 技能 v1.15.20）

本地化校验与真机语义对齐工具集。核心原则：**本地不建模的语义如实降级为「需真机验证」，绝不跑出与真机不符的假结果**。

> **同步状态（2026-11-03）**：本目录 17 个脚本已与技能 `scripts/` **逐文件 md5 一致**（对应技能 v1.15.20）。
> 本轮追平的五处：`check_request_layer.py` / `check_version_sync.py` / `test_parse.py` / `validate_booksource.py` / `verify_booksource.py`。此前本目录停在更早版本，含 v1.15.16–v1.15.19 的请求层闸修复（R2 分隔符 / R5 剥锚点与 host / 选项段 gson lenient / `<js>` 短路 / 类型守卫）、`check_version_sync` 非技能包 exit=1 与 `display_name` 版本比对、`validate_booksource` 类型守卫前置，以及 v1.15.20 的四项解析层修复（`ruleExplore` 空对象回退 `ruleSearch` / 列表链接 `//x`→`.//x` / JSOUP 求值兜底 / `@CSS:` 大小写不敏感）。**旧版会误判正常书源**，已全部替换。
> 注意：本目录脚本平铺在根目录（非 `scripts/` 子目录）。v1.15.21 起 `evals/run_evals.py` 已支持平铺定位，可在本目录原地跑，结果为 **94/96**——差的 2 条恒为 `self_audit`（检的是技能包自身结构，本目录没有 `references/` 文档树）。技能包内跑仍是 **96/96**。
> **防复发门禁**：`python3 tools/md5_sync_check.py <技能包目录> [--run-evals]`
> - 只比 md5：一致 `exit=0`、漂移或缺失 `exit=1`、路径错 `exit=2`
> - 加 `--run-evals`：md5 一致后再在本目录原地跑评测，**豁免名单精确到用例名**，只有 `self_audit.py` 与 `self_audit.py --self-test` 两条（`tools/` 无 `SKILL.md`/`references/`，必然失败），其余任一失败即 `exit=1`
> - 实测基线：正常 `PASS 94 / FAIL 2（豁免 2）exit=0`；删掉 `scripts/jsoup_eval/` 后 `PASS 93 / FAIL 3（豁免 2 + 触发 1）exit=1`——**红三条、只豁免两条**，别把豁免的两条漏记成「只坏一处」
> - 为什么要有第二项：本轮事故正是**文件 md5 全一致、目录结构却不同**，脚本各自没错、合起来跑不起来。md5 抓不到这种，得真跑一遍。
> - 下次升级技能后先跑这条，再谈别的。
> 另：`lint/booksource_lint.py`（知识库侧 lint 工具，非技能脚本）含 `strip_url_options()`。
>
> **最新技能包（v1.15.20）**：`https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.15.20/legado-booksource-debug_v1.15.20.skill`（解压即用，内含 `scripts/` 与本目录同名同 md5 的 17 个脚本）。
> **历史独立包**：`releases/legado-tools_v1.14.10.zip`（2.5MB，解压即用，不需要装技能；**不含 b2**）——已过期，仅存档。
> B2 真机引擎单独发包：`legado-tools-b2-runtime_v1.14.10.zip`（27MB，含 APK 转出的 4 个 jar + enjarify 修复包 + 已编译 harness，解压即跑）。
> 下载走 Release 附件（raw 对 >20MB 文件返回 403）：https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.14.10-b2.5/legado-tools-b2-runtime_v1.14.10.zip
> ```bash
> curl -L -o legado-tools.zip "https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-tools_v1.14.10.zip"
> unzip -o -q legado-tools.zip -d . && python3 legado-tools/validate_booksource.py 你的书源.json
> ```
> 包内 `AI-USAGE.md` 是写给 AI 的完整使用指引（下载方式 / 依赖 / 常用命令 / 症状对照表）。

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `md5_sync_check.py` | **同源同步门禁**：本目录与技能包 `scripts/` 逐文件 md5 比对，任一不一致 `exit=1`（缺失也算）。`python3 md5_sync_check.py <技能包目录>`；加 `--run-evals` 再原地跑评测（`self_audit` 按布局豁免）。存在意义：本目录是技能 `scripts/` 的镜像，一旦漂移，下游会拿到与技能包判定不同的旧工具——比没有工具更坏 |
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
