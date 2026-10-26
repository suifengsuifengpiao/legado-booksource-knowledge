# 给 AI 助手的下载与使用指引（Legado 书源工具链）

> 这份文件是给**其他会话 / 其他 AI 助手**看的。用户让你修书源、查书源问题时，先按本文把工具拿到本地，再动手。

## 一、这是什么

Legado（阅读 3.0）书源校验与调试工具链，Python 3 脚本，语义对齐真机 Legado 3.25。
核心原则：**本地不建模的语义如实降级为「需真机验证」，绝不跑出与真机不符的假结果**。

## 二、下载（二选一）

### 方式 A：只要工具（推荐给「临时修一个源」的场景）

```bash
curl -L -o legado-tools.zip "https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-tools_v1.14.10.zip"
unzip -o -q legado-tools.zip -d .
# 解压后得到 ./legado-tools/ 目录
```

### 方式 B：装成技能（推荐给「长期反复写源」的场景，仅 WorkBuddy/CodeBuddy 类客户端可用）

```bash
curl -L -o skill.zip "https://gitee.com/z157001/legado-booksource-knowledge/raw/main/releases/legado-booksource-debug_v1.14.10.skill"
mkdir -p ~/.codebuddy/skills/legado-booksource-debug
unzip -o -q skill.zip -d ~/.codebuddy/skills/legado-booksource-debug
```

技能装好后**本会话当场可用**（无需重启）。注意：每个会话是独立沙箱，技能不会自动共享给别的会话，每个会话都要各自装一次。

## 三、有没有依赖

| 依赖 | 是否必需 | 说明 |
|---|---|---|
| Python 3.9+ | 必需 | 全部校验脚本都是 py |
| Node.js | 部分必需 | `<js>` 规则本地求值、`js_layer_check.py` 需要 |
| Java 8+ | 可选 | `jsoup_eval/` 的 Jsoup 规则真语义求值需要（jar 已随包提供） |

自检：

```bash
cd legado-tools
python3 check_environment.py --capability live-fetch --network
```

## 四、常用命令（照抄即可）

### 1. 体检一个书源（最常用，先跑这个）

```bash
python3 legado-tools/validate_booksource.py 你的书源.json
```

查：字段合法性、铁律、`searchUrl` 的 `<js>` 返回值契约、charset 死字段、顶层 `replaceRegex`（3.25 无此字段，会被 Gson 静默丢弃）等。

### 2. 本地跑规则，看能不能解析出东西

```bash
python3 legado-tools/test_parse.py 你的书源.json --html 样本.html
```

支持 CSS / XPath / Regex / JSONPath 五路径；`:` 正则列表模式与 `<js>` 容器**不本地建模**，命中会明确标「需真机验证」——这是设计，不是缺陷。

### 3. 端到端：真抓页面 → 跑完整规则链

```bash
python3 legado-tools/verify_booksource.py 你的书源.json --keyword "关键词"
```

### 4. 抓页面（带 UA / 编码 / 重定向处理）

```bash
python3 legado-tools/fetch_page.py "https://站点/搜索?q=x" --out page.html
```

### 5. `<js>` 规则检查

```bash
python3 legado-tools/js_layer_check.py 你的书源.json
```

含「列表 `<js>` 返回数组类型闸门」与 jsLib 作用域建模。

### 6. 生成探针书源（用户没有电脑、只能在手机上调试时）

```bash
python3 legado-tools/make_probe_source.py --help
```

> **注意：`b2/` 真机引擎不在本工具包内。**
> 本包（`legado-tools_v1.14.10.zip`）只含静态校验工具，解压即用。
> 需要「JVM 加载 APK 真实 AnalyzeRule」的真机级解析验证时，另下运行时包：
> `legado-tools-b2-runtime_v1.14.10.zip`（27MB，含 APK 转出的 4 个 jar + enjarify 修复包 + 已编译 harness，**同样解压即跑**）：
> ```bash
> curl -L -o b2.zip "https://gitee.com/z157001/legado-booksource-knowledge/releases/download/v1.14.10-b2.5/legado-tools-b2-runtime_v1.14.10.zip"
> unzip -q b2.zip && cd legado-tools-b2-runtime_v1.14.10 && bash run.sh
> ```
> （走 **Release 附件**而不是 raw 直链——Gitee 对 >20MB 的 raw 文件要求登录，匿名下载会 403）

## 五、遇到具体症状查哪

| 症状 | 先看 |
|---|---|
| 搜索/发现列表为空 | `references-extra/pitfalls.md` 坑 N1~N9；`validate_booksource.py` |
| 正文只出一段 + "只支持手机浏览器" | **坑 N8：先加手机 UA，别上 webView** |
| 目录解析崩、`Cannot convert ... to java.lang.Long` | **坑 N9：`java.timeFormat` 只吃时间戳** |
| Cloudflare 五秒盾 / Turnstile | `bypass_cf.py` + `cases/过盾专题` |
| 规则写着写着不确定语法 | 知识库 `official-help/ruleHelp.md`（官方原文） |

## 六、给 AI 的执行纪律

1. **先体检再改**：拿到书源先跑 `validate_booksource.py`，别凭感觉改。
2. **不要编造真机结论**：本地模拟不出来的（`<js>`、`:正则列表`、webView 渲染），必须标「需真机验证」。
3. **网络请求要克制**：能离线判定就别联网；抓页面失败不代表规则错（可能是站点封机房 IP，见知识库 `cases/` 里的实例）。
4. **改完给对照**：用户要的是「为什么错」+「改成什么」，不是一段 JSON。

## 七、版本

- 工具链版本与技能 `legado-booksource-debug` 严格同步：**v1.14.10**
- 知识库主页：`https://gitee.com/z157001/legado-booksource-knowledge`
