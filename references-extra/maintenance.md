# 维护本技能：改动后必查（自检清单）

> 来历：1.13.10 一次审计翻出 **7 处自身缺陷**，其中 5 处是上一轮"新增能力"的配套欠账——
> 写了铁律没写检测、写了引用没写章节、加了桩没加入口、加了标记没接输出、加了用例没改计数。
> 根因是**改动是点状的，技能内部是网状的**：补一个洞会顺带开出新接口，而"新接口接没接上"
> 只存在于人的记忆里。改完不查耦合点，下次检查必然再翻出新的。

## 机械部分（已固化，一条命令）

`python3 scripts/self_audit.py`
—— 悬空引用 / 文档参数 vs 脚本实现 / 写死计数与版本号漂移 / 证据文件随包；已挂进 `evals/run_evals.py` 回归。
设计上**宁可少抓不可乱叫**（裸的 `\d+/\d+`、不带 `.md` 的「术语」一律不查；第 4 类只认带
`references/ scripts/ evals/ samples/` 前缀的引用，初版放宽到所有反引号 token 时一跑刷出 50 条、
46 条是噪音）：噪音会被习惯性忽略，而被忽略的护栏比没有护栏更糟——它给的是虚假安全感。

**护栏的护栏（别跳过）**：`python3 scripts/self_audit.py --self-test`
—— 在临时沙盒搭一棵迷你技能树，注入五类缺陷（悬空引用 / 文档写了脚本不认的参数 / 写死计数 /
版本漂移 / 证据未随包），断言**每一类都被抓到**，同时断言干净树必须放行。
外加一组**真实基线**：真读本技能自己的 `SKILL.md` / `_meta.json` 并比对 version、再对真实目录跑一遍
自检要求 exit=0 —— 沙盒里的版本是写死的，测不到真实技能此刻到底健康不健康（1.13.25 的版本漂移
检查静默失效就是这么漏过去的：虚拟树照样 5/5 通过，真实链路已瞎）。
来历：四类检查此前只在 1.13.10 用手写植入验证过一次、没固化，检查器改坏了也没人知道，
照样打印"全部通过"。**写自测时踩的坑**：最初用 `marker in 全部输出` 判定，而脚本 header 本身就印着
「悬空引用 / CLI 参数 / 写死计数·版本 / 证据文件随包」，导致其中两类**恒真**、形同虚设；
是靠"故意改坏判据看它响不响"的证伪实验才暴露的。故断言只认 `[ERROR] ` 开头的行。

## 语义部分（脚本抓不到，必须人工过）


| 你加了什么 | 必须同时接上的下游 |
|---|---|
| 新增章节 / 术语 | 别处引用它的地方写了吗？它引用的东西存在吗？ |
| **改 `js_layer_check.py` 的 `<js>` 求值语义 / jsLib 注入** | 与 dex 实证（`apk-method-inventory.md`「`<js>` 求值作用域」：每片段独立作用域 + `jsLib` shareScope 原型链注入）对齐吗？改前必看该节；换 App 版本要重新取证（evalJS 新建 bindings / setPrototype(shareScope) 两条指令是判据） |
| **改 `_is_pure_js_terminal`（#12 与 list-js 闸门共用的「末段纯 `<js>`」判据）** | 该 helper 在 `validate_booksource.py` 与 `js_layer_check.py` **双副本逐字同义**（两文件独立分发、不共享导入）：改前必双扫（grep 两文件同名函数）、改后必同步并双跑回归（validate + js_layer self-test 都要绿）。当前无漂移（QA 2.5 双副本 diff 实证，仅 docstring 措辞不同） |
| **改 `JsoupRuleEval` 的取值指示符（`html`/`all`/`text`/`@attr`）** | 三处必须同步：① `scripts/jsoup_eval/JsoupRuleEval.java`（真通道，改后**必须重编译** `.class`）；② `test_parse.py` 的 `_jsoup_extract`（bs4 降级路径）；③ `evals/jsoup_realdevice_equiv.py` 的 golden。语义以 `AnalyzeByJSoup.getResultLast` 为准：`html` = 删 script/style 后 **单条** outerHtml；`all` = 不删的 **单条** outerHtml（铁律 27）。改完必跑 `run_evals.py`（含 equiv 与 test_parse --self-test） |
| 新增一条铁律 | `validate_booksource.py` 有对应检测吗？`validate_cases.json` 有回归用例吗？ |
| 新增 `java.*` 桩 / 可配置项 | 有注入入口吗（CLI 参数或 config 字段）？没有就是**死配置** |
| 新增标记 / 返回值 | 接到输出了吗？能断言吗？ |
| 新增回归用例 | 计数是写死的吗？文档里抄的项数更新了吗？ |
| **新增文件 / 目录** | Resources 索引里列了吗？**已复发两次**：1.13.15 抓到 `scripts/` 索引漏列两个脚本；1.13.24 又漏列新增的 `references/evidence/` |
| **改动技能文件结构**（新增 / 删除 / 改名） | `scripts/self_audit.py` 的沙盒树 `_sandbox_files()` 同步了吗？**真实有的沙盒不能缺**（缺了干净树被误判），**真实没有的沙盒不能依赖**（依赖了触发路径是假的）——详见该函数注释里 1.13.28 的两组实测 |
| **改文档示例 / 知识库陈述** | 机械回归管不到文档事实错误（`searchUrl` `<js>` 返回形态曾写成整体 JSON 对象，真机必 404，回归照样全绿）——改完必须人工核对每处示例与 `apk-3.25-verified-facts.md` 实证事实一致；铁律 25 的跨文件一致性扫描要把**示例代码**纳入（同一包内正确/错误示例共存也是矛盾） |
| **新增一类检查 / 护栏** | 有固化自测吗？故意改坏它会不会静默空转？（铁律 22/23：护栏缺护栏 = 虚假安全感） |
| **新闸报出的任何 N/N（如「ERROR=4」）** | 三件齐才算证：① 标本落盘 `samples/`（去掉无关字段但保留缺陷形态）；② `evals/validate_cases.json` 里有对应用例（`booksource_file` 相对技能根目录 + `expect_attribution`）；③ 全文输出进 `evals/request_layer_expected_output.txt`（`# gen:` 行写复算命令，回归逐字比对）。**缺 ① 就是 E19 自犯**——v1.15.12 时 ERROR=4 只活在信件里，接收方无从复算 |
| **改 `check_request_layer.py` 的检查项分支（哪些条目在哪些路径上跑）** | 每条规则都可能挂在多条路径上：`exploreUrl` 结构解析失败→NOTE 后 `return`，元素级规则**默认全部不跑**。v1.15.15 同版本补（M2.5）就是这里漏的——R5 被判在 NOTE 分支静默吞掉，`X5` 实证 `WARN=0`。改完必须回头问：**这条规则在「结构成功 / NOTE / ERROR」三条路径上分别跑不跑？** 判据函数要抽成共用一个（`_r5_volatile`），不得在两条路径各写一份；只在 NOTE 文案里「声明跳过」不算修复 |
| **`_r5_volatile` 取 path 的写法** | 用 `split("?",1)[0]`，**不用 `urlsplit(url).path`**。反证是**协议相对路径**（M2 实测，Python 3.11.1）：`urlsplit("//2026/list/")` 把 `//2026` 当 netloc → `path='/list/'` → 段 `2026` 丢失、一句不报，而 `//host/path` 这种写法在 exploreUrl 里合法。另：`urlsplit` 会做 scheme/netloc 归一（剥 host、剥 userinfo、小写化），R5 要的是「原串路径里有没有长数字」，任何归一都可能删信息；`split("?",1)[0]` 只做一件事，行为可预期。**别拿 `/list/2026/?cid=5` 当反证**——实测 urlsplit 对它返回 `path='/list/2026/'`，照样命中 `2026`（任务书原句举的就是这个例子，M2 复现不成立，已按实测改写结论的理由）。 |
| **R5 里剔占位符** | `{{page}}` 与 `__JS__` **必须一并剔除**。NOTE 路径判 R5 前 `{{...}}` 已被占位成 `__JS__`，只 `replace("{{page}}","")` 会失效；`__JS__` 本身不含数字不会误报，但占位残留会把段名拼歪、让 `[^/]*\d{4,}[^/]*` 的边界判错。当初评估过「引入独立占位符 `\x00PAGE\x00`」，结论是**不做**：`{}` 不在 `\d` 里、`{{page}}` 本来就会被正则切成不含数字的小段，而新占位符要连带改 `split_options` / R3 / `_escape_ctrl_in_strings` 三处，扩大改动面换一个不存在的问题 |
| **R5 只看 path 的放宽面（口径变化登记）** | 查询串里的 4+ 位数字**不再报**。已知由阻断转通过的形态：`c4_query_digits`（`/list?cid=1234&page={{page}}`）、`b10b_semicolon_newline`（`/x?d=1;3333333` + 裸换行）、`b10a_semicolon_clean`（同一 url 无换行）、`P2_query_longnum`。**这是口径变化，不是修复**——报告里不许与 A10 的漏报修复混记。若将来发现确有人把易失 id 放查询串，按任务书余地**降为提示级**，不得在 `_r5_volatile` 里私自扩判据 |
| **取「改前」基线做 A/B** | 只许用**真原版**（v1.15.15 = 全文 `82da0a70ddbd`，或从 git 外归档重建），**不许拿自己的中间态副本当基线**。M1 的 `/tmp/m1/oldtree/` 实际是「P0-2 已改、P0-1 未改」的中间态，拿它跑出「22 格两边都 44/44 全绿」= **假绿**。判据：拿基线跑一个**已知该红**的格（如 `sweep_*_note` 或 `B8b`），红了才证明它是真原版；没红就先怀疑基线。这是「先红后绿」的反面——红要红在真原版上 |
| **`check_request_layer.py` 的 R1 与 gson 宽容度（P1-1）** | 本闸 Python `json` 与宿主 `gson` 两套严格度：三档解析链（严格 `json.loads` → probe 占位+控制字符转义 → `_gson_lenient` 单引号键/无引号键/数组尾逗号），**三档全失败才 ERROR**；gson 能吃的三形态降 `[NOTE] R1` 且 R5 照常按条目判（`_r5_collect`）。只建模 gson-2.13.2 实测能吃的三形态；**无引号值/注释等未证形态仍判 ERROR**（两边一致，正确）。判据函数抽成 `_try_load(text)` 返回 `(值, None)` 或 `(None, 异常)`——避免「外层 except 照样产 ERROR 文案、实际解析从未执行」的静默失效（v1.15.17 踩过，6 轮对照才发现） |
| **改 `check_request_layer.py` 的 WARN/ERROR 口径** | 闸带 ANSI 颜色码、`[WARN ]`/`[NOTE ]` 带对齐空格：`run_evals.py` 的 `_split_output` 必须先剥色再 `strip` 再比前缀，否则计数恒为 0（good 假绿 / bad 假红）。v1.15.15 起 WARN 标签改为 `[WARN·阻断]` / `[WARN·提示]`：剥离要按**整个方括号**吃（`^\[WARN[^\]]*\]`），只认旧 `^\[WARN\s?\]` 会留下前缀——计数仍对、文案断言会歪。改口径后 `evals` 的「请求层闸证据」一项会因逐字不一致而变红，属**预期**——重跑一遍 `# gen:` 命令重生成证据，并在 CHANGELOG 写明数字变化 |
| **改 `skill-dependencies.json` / 碰 schema** | 官方 validate 白名单外的用法必须在下方「已登记的 schema 约定」登记（铁律 26）；`self_audit.py` 第 5 项检查会拦未登记的；改完必须跑一次官方 validate 确认 0 error |
| 改版本号 | SKILL.md `version:` 与 `_meta.json` 两处一致、版本自增语义正确（PATCH/MINOR/MAJOR）吗？ |

**三条铁律（维护骨架）**：文档写了的能力必须有检测兜底；脚本里的可配置项必须有入口；回归里的数字不能手写。

**新增铁律 22-26（改动习惯）**，堵五类反复出现的引入型 bug——护栏缺护栏 / 写完不立刻逼错 / 事实全称判断下太快 / 跨文件自相矛盾 / 悄悄私扩 schema：
- **铁律 22**：改验证器/桩后必须跑「正向用例 + 反向用例」双跑，两条都过才算数；
- **铁律 23**：校验器自身要有能区分正误的「自我证伪」标本（如正确/错误取码写法配对）；
- **铁律 24**：事实性「是否」断言必须枚举全部重载并附 dex 描述符，不得凭单点取样下结论；
- **铁律 25**：改了涉及节奏/顺序/可否的陈述后，必须 Grep 扫同类关键词确认无旧主张残留。
- **铁律 26**：schema 相关改动（check 类型/字段的增删改）交付前必须跑一次官方 `skill-crafting` 的
  `validate`——本技能 `self_audit.py` 的白名单是照它对齐的快照，官方更新后以官方为准；白名单外
  用法先登记再动手，不许“悄悄私扩、交付时才爆”（官方 validate/backup/package/install 全以
  白名单为门禁，私扩即整条交付链断裂）。
五者是对「三条铁律」的延伸。

## 已登记的 schema 约定（白名单外用法的登记放行）

> 登记规矩：官方 validate 的 check 类型/字段白名单确实表达不了的语义，才允许在白名单内字段上
> 约定新语义；能表达就不要另起炉灶。**新增白名单外类型/新字段这条路是堵死的**——官方
> validate/backup/package/install 全以白名单为门禁，私扩一次、交付链全断。登记是
> `self_audit.py` 第 5 项检查的放行依据：未登记的用法一律报 ERROR。

| 约定 | 用在哪里 | 语义 | 为什么需要 |
|---|---|---|---|
| `python` 型 check 带 `command` 字段 | `skill-dependencies.json` 的 6 个第三方包依赖（lxml / curl_cffi / playwright / fontTools / bs4 / jsonpath_ng） | `command` 值即 Python 模块名（如 `lxml.html`）；检查时真跑 `importlib.import_module` 验“包装没装” | 官方 `python` 型只验解释器版本下限，第三方包没装也报 ready（死配置）；装没装直接决定书源生成 / 字段校验 / 真站取证能不能跑 |

## 已知缺口（没落地的能力，别当成已经有）

| 缺口 | 出处 | 卡在哪 |
|---|---|---|
| **离线 HTML 夹具**：把 403 挑战页 / 限流页 / about:blank / 正常结果页做成固定夹具，判定做成确定性的，真站只留烟测 | 书迷楼 v2.0.0 实战复盘 | 挑战本身是概率性的（shumi99 实测约四成通过），真站结果不可复现。夹具没固化之前，凡是"是否命中挑战"的判定都带概率，回归用例不能依赖它 |
| **`##`/`@js:` 尾段 carve-out 过宽**：`bookList`/`chapterList` 写成 `<js>...</js>##广告` 或 `<js>...</js>@js:...` 时，`_is_pure_js_terminal` 判非「末段纯 `<js>`」→ #12 WARN（`validate_booksource.py`）与 list-js 数组闸门（`js_layer_check.py`）双双静默放过（QA 2.5 实测两形态 0 告警） | QA 首审 P3-5（印证蓝致远 minor 1）； carve-out 注释明示作者有意保守 | 漏报方向、真实书源罕见；收紧需 dex 描述符级证据坐实「尾段是 `##`/`@js:` 时 JS 返回值是否仍被强转 `List`」；与「#12 升 ERROR 需 dex 证据」同批处理 |
