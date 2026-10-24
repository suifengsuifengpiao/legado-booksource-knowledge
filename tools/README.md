# Legado 书源工具链（legado-booksource-debug 技能 v1.14.2）

本地化校验与真机语义对齐工具集。核心原则：**本地不建模的语义如实降级为「需真机验证」，绝不跑出与真机不符的假结果**。

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `validate_booksource.py` | 书源结构体检：字段校验、铁律检测、searchUrl `<js>` 返回值契约（返回整体 JSON 对象=ERROR；POST body 预编码=WARN）、charset 死字段检测 |
| `test_parse.py` | 本地规则求值：CSS/XPath/Regex/JSONPath 五路径；`:` 正则列表模式与 `<js>` 容器不本地建模，命中即标「需真机验证」 |
| `verify_booksource.py` | 端到端验证：抓真实页面跑完整规则链 |
| `realcheck.py` | 真机等价检查：带/不带 cookie 对比取证 |
| `bypass_cf.py` | Cloudflare 五秒盾/JS 挑战过法探测 |
| `webview_probe.py` | webView 站点渲染命中探测 |
| `js_layer_check.py` | `<js>` 规则 Node 层执行检查 |
| `reverse_crypto.py` / `reverse_font.py` | 加密参数逆向 / 字体反爬(QueryTTF)还原 |
| `fetch_page.py` | 页面抓取（UA/编码/重定向处理） |
| `l0_probe.py` | L0 证伪探针：窄范围快速验证假设 |
| `make_probe_source.py` | 生成诊断探针书源 JSON（用户没电脑也能定位问题） |
| `check_environment.py` | 环境/依赖检测（`--capability live-fetch --network`，清单见 `skill-dependencies.json`） |
| `self_audit.py` | 技能自身一致性审计 |
| `legado_debug_bridge.py` | 调试桥：与 Legado 调试页日志对接 |
| `jsoup_eval/JsoupRuleEval.java` | Jsoup 规则 Java 求值器（对齐真机 bookList/chapterList 子规则语义；`elem`/`elemrule` 两种模式） |

## 用法示例

```bash
# 结构体检（ERROR=0 才可交付）
python3 validate_booksource.py 书源.json

# 环境检测
python3 check_environment.py --capability live-fetch --network

# Jsoup 规则求值（需 javac + jsoup jar）
javac -cp jsoup.jar jsoup_eval/JsoupRuleEval.java
java -cp .:jsoup.jar JsoupRuleEval page.html "tag.a@text"
```

## 设计红线

1. 本地无 Rhino → `<js>` 一律不假装能跑，标「需真机验证」；
2. `:` 正则模式是书籍/目录列表专用，本地不建模；
3. 顶层 `charset` 是 3.25 死字段，只认 searchUrl 行内 options；
4. 空规则/空文档中性跳过，不计失败。
