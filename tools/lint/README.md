# booksource_lint —— 书源离线检查工具

单文件书源检查器（不依赖任何 Skill，拷走就能跑）。以 `legado_app_3.25.apk`
（`io.legado.app.release` / v3.25 / vcode 15604）的反编译产物为唯一证据源，
离线复刻 App「书源调试」页的核心动作：逐条规则判定成败并给样例。

```bash
python3 booksource_lint.py <书源.json>            # 仅静态
python3 booksource_lint.py --self-test            # 自检（静态标本 + 资产可用性）
```

> **本 README 描述的是修复后的真实能力**，不再宣称"三层真引擎全可用"。
> 每层到底跑的是真引擎、近似还是没跑，看运行时报告头的「能力探测」区块，
> 以及 `ASSET-MISSING` / `DYN-DEGRADED` / `DYN-JP-SKIP` / `DYN-JS-FAIL` 这些告警。

---

## 1. 三层能力（与真实行为对齐）

| 层 | 触发方式 | 依赖 | 真实引擎 | 资产缺失时 |
|---|---|---|---|---|
| **静态** | 默认（不给任何参数） | 纯标准库 + `requests`（模块级硬依赖） | 无外部进程（可选 `node --check` 校验 JS 语法） | 不受资产影响 |
| **DYN 动态** | `--dynamic` + 样本（`--html` / `--search-html` … / `--json`） | `java`、`node`、资产目录 | jsoup 真 jar、JsoupXpath 真引擎、jayway 同构引擎 | 见 §3 |
| **LIVE 链路** | `--keyword` / `--explore` / 纯发现源自动 | `requests`、可选 Chromium、`node` | 真联网 + 真引擎 + loginCheckJs | 见 §3 |

### 1.1 各引擎的真实状态

| 引擎 | 资产 | 说明 |
|---|---|---|
| Jsoup（CSS 选择器） | `assets/jsoup-1.17.2.jar` + `assets/JsoupRuleEval.class` | **真 jar**。`_find_jsoup_jar` 依次找：自身资产目录 → 同仓 `tools/jsoup_eval` → 技能侧 `scripts/jsoup_eval`（最后的借用兜底）。借用会在报告头用 md5 标出来。 |
| XPath | `assets/jxpath/`（`XPathBench.jar` + 6 个依赖 jar） | **真 JsoupXpath 2.5.5**（`org.seimicrawler.xpath`，与 APK 同包名），含表格包裹预处理与 `<?xml` 切 xmlParser。 |
| JSONPath | `assets/jayway_compat.py` | **jayway 同构引擎**（对齐真机 jayway 2.9.x）。 |
| `<js>` / `@js:` | `assets/js_eval.js` + `node` | DYN 层会**先剥掉** JS 段、只校验语法，**不实跑**；LIVE 层才真正求值。 |
| loginCheckJs | `assets/login_check.js` + `node` | 仅 LIVE 层执行（`java.ajax` 真发请求，cookie 合并进会话）。 |

---

## 2. 用法

```bash
# 静态（最常用）
python3 booksource_lint.py 书源.json

# 动态：给样本实跑每条规则（无样本时只做引擎语法编译校验）
python3 booksource_lint.py 书源.json --dynamic \
    --html sample.html \
    --search-html s.html --bookinfo-html i.html \
    --toc-html t.html --content-html c.html \
    --json api.json

# 真实链路：真联网跑 搜索→详情→目录→正文
python3 booksource_lint.py 书源.json --keyword "斗破"
python3 booksource_lint.py 书源.json --explore            # 发现/探索入口
python3 booksource_lint.py 书源.json --keyword "斗破" --browser   # 强制 headless Chromium
python3 booksource_lint.py 书源.json --browser --no-browser       # 禁止浏览器自动升级

# 其它
python3 booksource_lint.py -                      # 从 stdin 读
python3 booksource_lint.py 书源.json --strict     # WARN 也判失败（exit 1）
python3 booksource_lint.py --self-test            # 自检
```

**退出码**：`0` = 通过（无 ERROR；`--strict` 下也无 WARN）；`1` = 有 ERROR（或 `--strict` 下有 WARN）；`2` = 参数/书源解析错误。

**报告分级**：`[ERROR]` 会导致取空/静默丢弃的真实问题（必须修）；`[WARN]` 健壮性/性能隐患；`[INFO]` 提示。

---

## 3. 资产目录与「能力探测」

真引擎资产放在脚本旁，按以下顺序探测（**不再硬编码单一目录名**）：

```
$BOOKSOURCE_LINT_ASSETS  >  <脚本目录>/assets  >  <脚本目录>/booksource_lint_assets
```

每次运行都会在报告头打印「能力探测」区块，列出每类资产的路径与 md5 前 12 位：

```
能力探测（本次真实生效的引擎）:
  资产目录: /…/tools/lint/assets
  ✅ Jsoup 真 jar 1.17.2         [DYN/LIVE]     …/assets/jsoup-1.17.2.jar  md5=d9dd58c3f8a0
  ✅ JsoupXpath 真引擎 jxpath      [DYN-XPath]    …/assets/jxpath  md5=8356f130e938
  ❌ JSONPath jayway 同构引擎       [DYN-JSONPath] 缺失
```

**资产缺失不再静默**：缺失项会落 `ASSET-MISSING` WARN（写明影响哪一层），
并且 `--self-test` 会因此**判定失败（exit 1）**。

---

## 4. 已知局限（修正版）

> 这一节逐条对应"声称 vs 实际"，写完以实跑为准。凡"没跑真引擎"的结论必在报告里留痕。

### 4.1 静态层

1. **`requests` 是模块级硬导入**：docstring 说静态层"纯标准库"，实际没装 requests 连静态层都起不来。未改（超出本次修复范围），运行前请 `pip install requests`。
2. **`replaceRegex` 判定待复核**：`DEAD-FIELDS` 仍把 `ruleContent.replaceRegex` 当死字段报 WARN。dex 级 xref 取证显示它在 3.25 有消费点（`webBook.w.b` → `AnalyzeRule.getString`），**这一条是待定的误报**，等二次复核定稿后删除，本批次未动。
3. **`java.*` 调用不做全量比对**：只查 `check_urls` 覆盖面内的 `loginCheckJs` / `webJs` 里一小部分"工具未仿真"清单（`_UNEMU`），普通规则里的 `java.xxx` 不扫；伪造 API（真机必 ReferenceError）零提示。真值清单正在由另一路从 dex 产出，到位后单独立项。
4. **不扫 `jsLib`**：`_collect_js` 不覆盖 `jsLib` 字段，自定义 helper 里的语法/API 问题看不见。

### 4.2 DYN 动态层

5. **JSONPath 缺失 = 整类不检查，不是降级**：jayway 不可用时 JSONPath 规则**完全不做动态检查**（上游 `jsonpath_ok` 闸门拦死，走不到 jsonpath_ng 兜底）。报告用 `DYN-JP-SKIP` **WARN** 明示——不要再理解成"降级到 jsonpath_ng"。
6. **XPath 缺失 = lxml 近似，会报 `DYN-DEGRADED`**：lxml 是标准 XPath 1.0，非 seimicrawler 语法、不做表格包裹预处理、不切 xmlParser，可能与真机不一致。命中行会带「（lxml 近似）」标记。
7. **DYN 层不实跑 `<js>` / `@js:` 段**：进入引擎前先剥掉 JS 段，JS 只做 `node --check` 语法校验。要验证 JS 取值必须走 LIVE 层（`--keyword` / `--explore`）。

### 4.3 LIVE 链路层

8. **`<js>` 求值失败不再静默**：`js_eval.js` / `node` 缺失时所有 JS 段**整类未求值** → `DYN-JS-FAIL` WARN（环境问题）；环境正常仍抛错 → `DYN-JS-FAIL` ERROR（该段在引擎里真的失败，本条结果不可信）。
9. **`java.*` 仿真覆盖很窄**：`assets/js_eval.js` 只实现了 `md5` / `md5Hex` / `base64*` / `aes*` / `ajax` / `get` / `put` 等少数几个，**其余调用会返回空串**（例如 `java.md5Encode(...)` → `''`）。这是"JS 静默取空"的残留风险面，属 §4.1 #3 的立项范围。
10. **cheerio 未安装是"失效态"**：`assets/package.json` 声明了 cheerio/iconv-lite，但 `node_modules` 不存在。`Packages.org.jsoup.*` 桥因此必抛错——**这恰好与 Rhino"调用不存在的 Java 类抛错"语义一致**。请不要用 `npm i` 去"修"它：装上之后会出现真正危险的静默取空。
11. **依赖真联网**：LIVE 层结果受目标站当时的反爬/登录态影响，不可复现是常态；翻页有护栏（`MAX_TOC_PAGES=100` / `MAX_CONTENT_PAGES=200`），真机无此上限。

---

## 5. 与技能侧 `validate_booksource.py` 的关系

两个工具**故意不合并**：漏检面互补，互跑对照比合并更划算（保持差异冗余）。
子规则字段口径已对齐（位置串同为 `ruleExplore#N`，序号从 0 起）：

| 场景 | 本工具 | 技能侧 | 状态 |
|---|---|---|---|
| 子规则缺 `name` / `bookUrl` | `EXPLORE-SUB-REQ` ERROR | ERROR | ✅ 一致 |
| 子规则缺 `bookList` | `EXPLORE-SUB-WARN` **WARN** | **ERROR** | ⚠️ **待协调**：真机 `bookList` 省略合法（规则作用于整页），判 ERROR 会误杀单条目源；本批次只改了 lint 侧，技能侧需同步降为 WARN |
| 子规则缺 `chapterList`（ruleToc） | 不查 | ERROR | ⚠️ 同上，待统一下一批 |
| `exploreUrl` 条目 `url` 为空（分组标题） | 跳过 | 未排除（可能误报） | ⚠️ 技能侧需补 `if not url: continue` |
| `exploreUrl` 形如 JSON 却解析失败 | `EXPLORE-URL-PARSE` WARN | — | lint 独有（不静默跳过） |

---

## 6. 目录结构

```
tools/lint/
├── booksource_lint.py       # 单文件主程序
├── README.md                # 本文件
└── assets/                  # 真引擎资产（目录名可被 $BOOKSOURCE_LINT_ASSETS 覆盖）
    ├── jsoup-1.17.2.jar          # Jsoup 真 jar
    ├── JsoupRuleEval.java/.class # Jsoup 桥接（.class 需与 .java 同源）
    ├── jxpath/                   # JsoupXpath 2.5.5 + XPathBench + 依赖 jar
    ├── jayway_compat.py          # JSONPath jayway 同构引擎
    ├── js_eval.js                # node 侧 JS 求值桥
    ├── login_check.js            # node 侧 loginCheckJs 通道
    └── package.json              # node 依赖声明（node_modules 未安装，见 §4.3 #10）
```

**已知资产治理遗留**（未在本批次处理）：
`JsoupRuleEval.class` 与技能侧同名文件 md5 不同（`9b088b2a…` vs `57c0baa8…`），
且 `.class` 是否由仓库内的 `.java` 现编译得到未验证；建议后续改为"`.class` 不入库 + 一条命令从 `.java` 重建"。
