# 环境配置与降级指南

本技能按能力（capability）过滤依赖清单：只做本地校验时几乎零配置，只有真实抓取和防护逆向才需要装库。

## 何时检查环境

进入主流程前先跑一次只读检查，并按本次要用到的能力过滤：

```bash
python3 scripts/check_environment.py --capability field-validation
python3 scripts/check_environment.py --capability live-fetch --network
```

`--capability` 可重复传入。四种结果与下一步：

| 状态 | 含义 | 下一步 |
|---|---|---|
| `ready` | 所需依赖都可用 | 跳过配置，直接干活 |
| `partial` | 核心可用，部分可选能力不可用 | 继续，只说明受影响功能与降级方式 |
| `needs_setup` | 必需依赖缺失 | 只安装缺失项，然后重检 |
| `unavailable` | 依赖存在但服务/版本异常 | 按下面"恢复与降级"处理 |

已经通过的项目再次检查时不会重复引导。

## 安装与最小验证

| 清单 id | 依赖 | 安装 | 最小验证 | 支撑能力 |
|---|---|---|---|---|
| `python-runtime` | Python 3.10+ | 系统包管理器或官网安装包 | `python3 --version` | 全部 |
| `lxml` | lxml | `pip3 install lxml` | `python3 -c "import lxml.html"` | 规则命中验证 |
| `curl-cffi` | curl_cffi | `pip3 install curl_cffi` | `python3 -c "from curl_cffi import requests"` | 真实抓取、防护逆向 |
| `playwright` | playwright | `pip3 install playwright` 然后 `playwright install chromium` | `python3 -c "from playwright.sync_api import sync_playwright"` | 防护逆向（真实浏览器过 CF） |
| `fonttools` | fontTools | `pip3 install fonttools` | `python3 -c "from fontTools.ttLib import TTFont"` | 字体反爬解析 |
| `network-access` | 外网 HTTPS | 无需安装，确认网络可达 | `python3 scripts/check_environment.py --network --capability live-fetch`，参照 https://docs.python.org/3/ 的匿名只读探测 | 真实抓取、防护逆向 |
| `node-runtime` | Node.js 16+ | 系统包管理器或官网安装包 | `node --version` | webJs/js 层 JS 校验（`scripts/js_layer_check.py`，Rhino 钩子语法/运行校验，缺失时该脚本自动跳过、回归标 SKIP） |
| `beautifulsoup4` | beautifulsoup4 | `pip3 install beautifulsoup4` | `python3 -c "import bs4"` | JSOUP `@` 链式规则命中验证（`scripts/test_parse.py` 的 JSOUP 引擎） |
| `java-runtime` | Java 11+ | 系统包管理器或 https://www.java.com/ 安装包 | `java -version` | 真 Jsoup 通道（`scripts/jsoup_eval/`：`JsoupRuleEval.java` + `jsoup-1.17.2.jar`），校验 `~=` 属性选择器（正则匹配语义）；问号形态为幻影——`?` 被解析进属性名，恒不命中，走同通道得真机一致的恒空 |
| `jsonpath-ng` | jsonpath-ng | `pip3 install jsonpath-ng` | `python3 -c "import jsonpath_ng"` | JSONPath 规则（`$.xxx`）本地命中验证，缺失时相关规则误判 `[ERR]` |

**检查器的能力边界（如实说明）**：`check_environment.py` 按 `skill-dependencies.json` 的清单逐项探测——
Python 运行时可导入模块（`python` 型 check 的 `command` 字段，语义见 `references/maintenance.md`「已登记的 schema 约定」）、第三方库导入性（lxml/curl_cffi/playwright/fontTools/bs4/jsonpath_ng）、
`node`/`java` CLI 版本比对（`--version` 实测）、加 `--network` 时的匿名 HTTPS 连通性探测。
上表"最小验证"列的命令也可手动复核。

## 官方入口

| 依赖 | 官方主页 | 官方文档 |
|---|---|---|
| Python | https://www.python.org/ | https://docs.python.org/3/ |
| lxml | https://lxml.de/ | https://lxml.de/ |
| curl_cffi | https://github.com/lexiforest/curl_cffi | https://curl-cffi.readthedocs.io/ |
| playwright | https://playwright.dev/python/ | https://playwright.dev/python/docs/intro |
| fontTools | https://fonttools.readthedocs.io/en/latest/ | 同上 |
| Node.js | https://nodejs.org/ | https://nodejs.org/docs/latest/api/ |
| BeautifulSoup | https://www.crummy.com/software/BeautifulSoup/ | https://www.crummy.com/software/BeautifulSoup/bs4/doc/ |
| Java | https://www.java.com/ | https://docs.oracle.com/en/java/ |
| jsonpath-ng | https://github.com/httplib2/jsonpath-ng | https://github.com/httplib2/jsonpath-ng |

核验日期：python-runtime/lxml/curl-cffi/playwright/fonttools/network-access 为 2026-10-02；
node-runtime 为 2026-10-03；beautifulsoup4/java-runtime/jsonpath-ng 为 2026-10-08（与 `skill-dependencies.json`
各条目的 `verified_at` 一致）。核验时执行环境为受限网络，`www.python.org` 与 `github.com` 未能完成探测
（同域的 `docs.python.org` 与 `curl-cffi.readthedocs.io` 均返回 200），这两个地址按官方已知入口填写。

## 安全与隐私

- 全部依赖**无需任何登录、Token 或 API Key**，也不要求把凭据写进环境变量。
- 抓取只在本地临时工作目录留下 HTML 样本；**抓到的 Cookie 只用于本次对比取证，不写回书源文件**
  （cookie 与 IP、设备绑定，写进书源在手机上无效）。
- `bypass_cf.py` 的浏览器在本地临时会话中打开目标页面，不保存登录态，不上传数据。
- 脚本不读取书源以外的本地文件；外发请求只有两类：抓取目标站点本身，以及 `check_environment.py --network`
  对 https://docs.python.org/3/ 的匿名只读连通性探测（只为判断"网络通不通"，不携带任何业务数据）。

## 恢复与降级

- **网络不通**：`live-fetch` 与 `protection-reverse` 降级为"用户回传页面源码 + 本地样本验证"；
  此时**不能**断言站点是静态加载还是 JS 渲染，也不能宣称绕过了防护。
- **防护过不去**：Cloudflare 挑战连续失败最多重试 1 次，之后转推测版并明确标注需真机实测。
- **样本缺失**：只验证已提供的区域，其余标 SKIP；交付时必须把未验证区域列为待验证项。
- **用户拒绝安装依赖**：核心的字段校验与铁律检测（纯标准库）仍然可用，
  真实抓取与防护逆向停用，交付说明中标注为"未实测"。
