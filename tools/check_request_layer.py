#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
请求层闸（第五道闸）· check_request_layer.py
=============================================
当前版本：v1.15.21
用途：在把书源交给宿主（Legado）之前，模拟宿主对 **URL / 请求参数** 的解析，
      抓出「解析层四道闸永远看不到」的错误。

由来（2026-11-02 duomle 真机事故）：
  - exploreUrl 用 JSON 数组格式，却把 ,{"webView":true} 直接塞进 url 字符串未转义
    → 宿主 gson 抛 MalformedJsonException: Unterminated object at line 1 column 74 path $[0].url
    → 发现页整段崩溃，而 validate / test_parse 全绿（它们不碰 URL 字符串）
  - searchUrl 同时写 method:POST 与 webView:true
    → Android WebView 只能 GET，POST body 丢失 → 服务端收不到关键词 → 列表为空
    → 真机日志「获取书籍列表 → 列表为空，按详情页解析」→ 0 本

检查项：
  R1 exploreUrl 语法：以 [ 开头必须为合法 JSON（逐项 title/url）。
     v1.15.15：直接解析失败时按**宿主 gson 宽容度**再解一次（{{...}} 占位 + 字符串内
     \\n/\\r/\\t 转义）——复解通过 = 只是 Python 比 gson 严 → NOTE；仍失败 = 结构真错 → ERROR
  R2 exploreUrl 文本行格式：每行 标题::URL（以 @js: / <js> 开头时为 JS 动态发现，
     本闸不解析 JS，转 NOTE 提示另验——手机小说真机已验证 @js: 形态合法）
  R3 exploreUrl 各项 URL：内嵌选项 ,{...} 二次解析；相对路径在 bookSourceUrl
     非空时由宿主拼接（合法），bookSourceUrl 为空才报 ERROR。
     不含 {{page}} 是**提示级**（分页机会提示，榜单/分类首页本来只有一页），不阻断 --strict
  R4 searchUrl 结构 + method 与 webView 互斥（相对路径同 R3 口径）
  R5 易失地址启发式（路径含 4+ 位数字，需多会话复验）
  R6 GET searchUrl 里的 {{key}} 中文编码提示：GET 的查询串由宿主 AnalyzeUrl
     编码与否取决于写法，若未编码中文关键词可能取空——WARN 提示改
     {{java.encodeURI(key)}} 或实测确认。**不写选项 = 默认 GET，同样适用**
     （v1.15.13 修：此前 R6 嵌在 `if opt:` 内，裸写法漏报）；显式 method:POST 不报
     （POST 关键词在 body，编码路径不同）
  R7 bookSourceUrl 协议与各规则 URL 协议一致性

切分算法（v1.15.13 重写，逐条对 3.25 dex）：
  `<clinit>` paramPattern = "\\s*,\\s*(?=\\{)"；`analyzeUrl()` 在**首次**匹配处切分
  （url=substring(0,start)、选项=substring(end) 交 gson fromJson），无匹配则整串当 url +
  默认 GET；解析失败被 runCatching 吞成 null（宿主按默认选项继续，不崩）。
  exploreUrl 另走一条：paramPattern 无匹配时 seek=0 → **整串都是 url，不切选项**。
  旧版用 rfind(",{") + json.loads(整段后缀)，两头都比宿主严：既误杀 @js:/<js> 尾部 JS，
  也误判数组内 "url" 值里的 \\",{...}\\"（实测：12 本已交付书源里 3 本被误判 ERROR）。

退出码：0 = 无 ERROR（默认口径，WARN 不阻断）；1 = 有 ERROR，或 --strict 下有阻断级 WARN
用法：python3 check_request_layer.py <书源.json> [--strict]
      --strict：WARN 亦视为失败（R6 这类「编码可能有问题」在严格模式下应阻断交付）
      v1.15.13 前 --strict 只写在用法里、无实现分支，传了等于没传
"""
import json
import re
import sys
import os

RED = "\033[31m"
YEL = "\033[33m"
GRN = "\033[32m"
CYN = "\033[36m"
RST = "\033[0m"

# 3.25 AnalyzeUrl.<clinit>：paramPattern = "\\s*,\\s*(?=\\{)"
PARAM_RE = re.compile(r"\s*,\s*(?=\{)")


class Result:
    def __init__(self):
        self.errors = []
        self.warns = []
        self.notes = []

    def err(self, code, msg):
        self.errors.append((code, msg))

    def warn(self, code, msg, blocking=True):
        """blocking=True：--strict 下视为失败（真的会让你交付后出事）。
        blocking=False：提示性（已真机验证可过、只是建议再确认），--strict 不阻断。
        v1.15.14：此前一刀切「WARN 即失败」，导致 duomle 修复版（真机已验证）在 --strict 下也红，
        把「建议实测确认」和「真的会坏」混为一谈。"""
        self.warns.append((code, msg, blocking))

    def note(self, code, msg):
        self.notes.append((code, msg))


def split_options(raw, host="?"):
    """按 **3.25 宿主自己的算法** 把 'url,{...}' 切分（v1.15.13 重写）。

    旧实现用 `rfind(",{")` + `json.loads(整段后缀)`，与本闸要防的误判同源：
    宿主根本不按"最后一个 ,{" 切，也**不会**因为后缀含多余内容就失败。

    3.25 反编译实证（classes3.dex → `io/legado/app/model/analyzeRule/AnalyzeUrl`）：
      · `<clinit>` 的 `paramPattern = Pattern.compile("\\s*,\\s*(?=\\{)")`
      · `analyzeUrl()` 在该 pattern **首次**匹配处切分：url = substring(0, start)，
        选项 = substring(end)，交给 gson `fromJson(..., UrlOption.class)`；无匹配 → 用整个 ruleUrl、默认选项
      · 选项解析失败被 `runCatching` 吞成 null → 宿主按 **默认 GET + 无选项** 继续（不是崩溃）
      · exploreUrl 另走一条：dex 里 `paramPattern.find()` 为假时 seek=0，即**整串都算 url**，
        不做切分 → 数组里 "url" 值内层带 \",{...}\" 不会被宿主当选项
    gson 按"解析完一个完整对象即返回、忽略其后多余内容"工作（java_probe/Probe3 实测），
    所以 `@js:` / `<js>` 尾部 trailing 的 JS 源码不会让宿主失败。

    返回 (url_part, opt_dict|None, err|None)。err 仅在**选项段本身**不是合法 JSON 对象时给出，
    且在 host=explore 时按宿主口径降级为该段整串当 url 的一部分。
    """
    s = raw.strip()
    if host == "explore":
        # 宿主对 exploreUrl 不切选项（dex: paramPattern.find() 为假 → seek=0，整串当 url）
        return s, None, None
    m = PARAM_RE.search(s)
    if not m:
        return s, None, None
    url_part = s[:m.start()].strip()
    opt_part = s[m.end():].strip()
    if not opt_part.startswith("{"):
        return url_part, None, None
    try:
        # M1：选项段先过 _gson_lenient，与 R1/R2 的宽容度口径一致
        # （单引号键/值、无引号键、尾逗号等 gson 能吃的形态不再误判 R4 ERROR）
        opt_part = _gson_lenient(opt_part)
        opt = json.JSONDecoder().raw_decode(opt_part)[0]
        if not isinstance(opt, dict):
            return url_part, None, f"选项不是 JSON 对象：{opt_part[:80]}"
        return url_part, opt, None
    except Exception as e:
        return url_part, None, f"选项 JSON 非法（{e}）：{opt_part[:120]}"


def _escape_ctrl_in_strings(s):
    r"""把 JSON **字符串内部**的裸控制字符转成转义序列（\n \r \t）。

    只处理引号内的字符：结构层的换行/缩进是合法 JSON 空白，一起转义反而会把整串弄坏。
    反斜杠状态要跟着走——`"a\\"` 里第二个引号是字符串结尾，`"a\"b"` 里的引号不是。
    v1.15.15 两步走的第 ② 步：建模宿主 gson 对控制字符的宽容度，而不是笼统放过。
    """
    out = []
    in_str = False
    esc = False
    mapping = {"\n": r"\n", "\r": r"\r", "\t": r"\t"}
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == '"':
                out.append(ch)
                in_str = False
                continue
            out.append(mapping.get(ch, ch))
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def _gson_lenient(s):
    r"""把 **宿主 gson 默认 lenient 能吃、Python json 吃不下** 的三类形态转成严格 JSON。

    v1.15.17（P1-1 选 (a)）。由来：本闸用 Python `json` / `raw_decode` 解析，
    宿主用 gson；两套严格度不同 → 同一份书源在两处结论相反。gson-2.13.2 实测（/tmp/p11/P.java）：

      | 形态                     | gson | Python json | 本函数 |
      |--------------------------|------|-------------|--------|
      | `{'k':'v'}`   单引号键/值 | OK   | FAIL        | 转双引号 |
      | `{k:"v"}`     无引号键     | OK   | FAIL        | 补双引号 |
      | `[{...},]`    数组尾逗号   | OK（多出一个 **null 元素**） | FAIL | 删逗号，**补一个 null 项** |
      | `{k:v}`       无引号值     | FAIL | FAIL        | 不处理，仍判 ERROR |

    尾逗号那一行必须补 null：gson 把 `[obj,]` 读成 `[obj, null]`（同一探针两处打印均为
    `[{...},null]`）。不补就是「条目数少一个」——元素级规则按 i 归属，少一项会让后面所有
    `[JSON[i]]` 整体前移一格，比不解析更坏。这是本函数唯一一处**故意不守恒长度**的地方。

    未覆盖（照旧 ERROR，不假装能吃）：
      · 无引号**值**（`{url:https://…}`）——gson 也不吃，两边一致（E2b2 探针 FAIL）
      · 注释（`//`、`/* */`）——未进 E2 样本，按「未建模」处理，见 maintenance.md

    只做**单趟**转译，不做反复试探：转完仍解析失败 = 结构真错，交回上层报 ERROR。
    字符串内（含 `\"` 转义状态）一律不动，避免把 URL 里的单引号/逗号改坏。
    """
    out = []
    n = len(s)
    i = 0
    in_str = False
    q = ""            # 当前字符串的定界符（' 或 "）
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            if ch == q:
                out.append('"')     # 单引号字符串 → 双引号
                in_str = False
                i += 1
                continue
            if ch == '"':
                out.append('\\"')   # 单引号串内的裸双引号必须转义，否则提前闭合
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            out.append('"')
            in_str = True
            q = "'"
            i += 1
            continue
        if ch == '"':
            out.append('"')
            in_str = True
            q = '"'
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            # 裸标识符：后面（跳过空白）跟冒号 → 是键，补引号；否则是值（true/null/裸值），原样。
            # 键**紧跟**冒号才算（`url:`）——`http:` 这种「值里的词 + 冒号」前面不是 `{` / `,`，
            # 由 _lenient_candidate 那关挡住（先转译再判定，单趟字符串扫描分不清两者）。
            j = i
            while j < n and (s[j].isalnum() or s[j] in "_$"):
                j += 1
            word = s[i:j]
            k = j
            while k < n and s[k] in " \t\r\n":
                k += 1
            if k == j and k < n and s[k] == ":":
                out.append('"%s"' % word)
            else:
                out.append(word)
            i = j
            continue
        out.append(ch)
        i += 1
    text = "".join(out)

    # 尾逗号（gson lenient 接受）：对象尾逗号删逗号、数组尾逗号补 null。
    # 两遍顺序：先对象尾（只动 `}`）再数组尾（只动 `]`），不能把 `,]` 用「删逗号」与「补 null」各做一遍——
    # 补 null 产生的 `,null]` 会被删逗号那遍的 `,]` 二次匹配破坏（v1.15.17 实测 E2c 仍 ERROR）。
    text = re.sub(r",(\s*)\}", r"\1}", text)
    text = re.sub(r",(\s*)\]", r",null\1]", text)
    return text


def _r5_volatile(url):
    """易失地址启发式：返回**路径**里含 4+ 位连续数字的段。

    v1.15.15 起抽成函数共用：JSON 结构成功路径与「宽容度差异 NOTE」路径调的是**同一套判据**。
    两处各写一份必然漂移——M2.5 的教训正是「一条本该拦的规则，因为走的是另一条分支就消失」。

    v1.15.14：先把行内选项 ,{...} 从路径里剥掉再判——宿主虽不把它当选项解析（explore 口径），
    但它显然不是 URL 路径的一段；不剥会让 {"webWait":3000} 里的 3000 被误判成易失长数字段。

    v1.15.16 两处改（P0-2 + P0-1 副作用）：
      ① **只看 path，不看查询串**。`/search?cid=1234&page={{page}}` 里的 `cid=1234` 是查询参数，
         不是「按年月日变动的静态化路径」；旧版不切 `?`，把整段当路径，--strict 下
         把正常带 id 的分类页判成阻断级（挡合格书源）。查询串长数字**不报**——
         若将来发现确有人把易失内容放查询串，再按任务书给的余地降为提示级，不在这里自己扩。
      ② `{{page}}` 与 NOTE 路径的替代占位 `__JS__` 一并剔除。NOTE 路径判 R5 前 `{{...}}`
         已被占位成 `__JS__`，只 replace("{{page}}", "") 会失效——本闸不建模「占位符展开后
         会不会引入 4+ 位数字」，因为那取决于宿主运行时，静态判不了；照实剔除。
    """
    # 先剥锚点（# 之后不是路径，误判会拦合格书源）
    u = url.split("#", 1)[0]
    # 再剥行内选项 ,{...}（宿主 explore 口径不解析，且显然不是路径段）
    u = re.sub(r"\s*,\s*\{.*$", "", u, flags=re.S)
    # 再剥 scheme + host：https?://host 里的数字不是路径（book2024.example.com 不应被误报）
    u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/?#]+", "", u, count=1)
    path = u.split("?", 1)[0]
    path = path.replace("{{page}}", "").replace("__JS__", "")
    return [seg for seg in re.findall(r"[^/]*\d{4,}[^/]*", path) if re.search(r"\d{4,}", seg)]


def _try_load(text):
    """(值, None) 或 (None, 异常)。代替 try/except 包在分支里——
    v1.15.17 踩过：三层嵌套 try 里那句 `arr = json.loads(probe)` 实际上从未执行，
    而外层 except 照样产出 ERROR 文案，整条 NOTE 路径静默失效（6 轮对照才发现）。
    收成函数后，「解成功了没有」只看返回值，不再靠缩进猜。"""
    try:
        return json.loads(text), None
    except Exception as exc:      # noqa: BLE001 —— 任何解析失败都要能落到 ERROR 分支
        return None, exc


def _r5_collect(arr):
    """[(i, title, seg)]：元素级 R5 的唯一实现。

    结构成功路径、NOTE 路径、ERROR 路径三处都调它 —— v1.15.16 的教训是「同一判据写三份必然漂移」，
    一份漏了就出现「有控制字符错 + 有易失数字段 → 两个都不报」（X5）。
    非 dict 元素（含尾逗号补出的 None）跳过：它们没有 url 可判。
    """
    hits = []
    for i, it in enumerate(arr if isinstance(arr, list) else []):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title", ""))
        for seg in _r5_volatile(str(it.get("url", ""))):
            hits.append((i, title, seg))
    return hits


def check_explore(explore, res, base=""):
    if not explore:
        res.note("R1", "exploreUrl 为空，跳过发现页检查")
        return
    if not isinstance(explore, str):
        res.err("R1", f"exploreUrl 类型异常（应为字符串，实得 {type(explore).__name__}）：无法逐行解析，须改为字符串")
        return

    # @js: / <js> 开头 = JS 动态发现，宿主先 evalJS 再用返回值；本闸不解析 JS，
    # 按文本行/JSON 逐行解析只会刷出成片误报（亲亲小说 15 条全是这类）。
    # 手机小说书源真机已验证 @js: exploreUrl 合法。
    if re.match(r"^\s*(@js:|<js>)", explore):
        res.note("R1", "exploreUrl 为 JS 动态生成（@js:/<js>），本闸不解析 JS；"
                       "JS 语法另用 js_layer_check.py / 真机验证")
        return

    is_json = explore.lstrip().startswith("[")
    items = []

    if is_json:
        # 本闸用 Python json，宿主用 gson，两套严格度不同。v1.15.17（P1-1）把「差在哪、谁让谁」
        # 收成一条链，三档逐档严格，**每档吃下的形态都明确登记**（详见 _gson_lenient 与 main 的 NOTE）：
        #   ① 严格 json.loads
        #   ② probe：{{...}} 占位 + 字符串内控制字符转义（v1.15.15 起，建模 gson 对控制字符的宽容）
        #   ③ _gson_lenient：单引号键/值、无引号键、尾逗号（v1.15.17 起，建模 gson lenient）
        # 三档全失败才判 ERROR。为什么不再「一律严格」：E2a/E2b 是 gson 真能吃下的合格写法，
        # 判 ERROR 就是挡合格书源（与 P0-2 同族）。为什么不能只降 NOTE 不取 arr：R5 要按条目归属，
        # 没有结构就没有 `[JSON[i]]「title」`，只能退回「原文抽取」猜——那条路已因 B8b/D3b 删掉。
        lenient = None
        try:
            arr = json.loads(explore)
        except Exception as e:
            # 尽量给出列号，对齐宿主 gson 的报错位置
            col = getattr(e, "colno", None)
            pos = f"，约第 {col} 列" if col else ""
            # {{ }} 内嵌多行 JS 时 Python 的 json 会因裸回车报错，而宿主 gson **能过**
            # （八叉书库实证：java_probe/Probe.java → gson [OK] 元素数=15，格 2 实测）。
            # v1.15.14 的处理是「见 Invalid control character 且含 {{ }} → 整段 NOTE 后 return」，
            # 那是一条**顺序敏感短路**：json.loads 停在第一个错误处，裸换行在前时先报控制字符
            # → 直接 return，后面的未转义选项**永远不会被看见**（g10b 实证 ERROR=0 放过）。
            # v1.15.15 改两步走，把「宽容度差异」与「结构真错」分开：
            #   ① {{...}} 占位成 __JS__（宿主先算 JS 再解析，JS 正文不参与 JSON 结构）
            #   ② 字符串内 \n \r \t 转成字面两字符（gson 宽容接受，本闸建模它的宽容度）
            #   ③ 再 json.loads：成功 = 差异只在宽容度 → NOTE；失败 = 结构本身有问题 → ERROR
            # 不按「有没有 {{ }}」分流：{{ }} 只是常见伴随特征，不是判据。
            probe = _escape_ctrl_in_strings(re.sub(r"\{\{.*?\}\}", "__JS__", explore, flags=re.S))
            # ---- 第 ② 档：probe（控制字符建模）----
            arr, e2 = _try_load(probe)
            lenient = None
            if e2 is not None:
                # ---- 第 ③ 档：gson lenient（单引号/无引号键/尾逗号）----
                # 必须先确认转译真的改动了原文：没改动的形态本闸不建模，不能拿 ② 档的错冒充 ③ 档的错
                # （E24 同族：报文写「含 gson lenient 复解」而实际没跑过 = 把没建模说成建模过）。
                cand = _gson_lenient(probe)
                if cand != probe:
                    arr3, e3 = _try_load(cand)
                    if e3 is None:
                        arr, e2, lenient = arr3, None, "gson lenient（单引号/无引号键/尾逗号）"
                        stage = ""
                    else:
                        e2 = e3
                        stage = "按宿主宽容度复解（含 gson lenient）后仍失败"
                else:
                    stage = ("按宿主宽容度复解后仍失败；gson lenient 档未适用"
                             "（无可代换形态）→ 本闸不建模该形态，判 ERROR")
            if e2 is not None:
                # ---- 第 ③ 档：gson lenient（单引号/无引号键/尾逗号）----
                # 先确认转译真的改动了原文：没改动的形态本闸不建模，不能拿 ② 档的错冒充 ③ 档的错
                # （E24 同族：报文里写「含 gson lenient 复解」而实际没跑过 = 把没建模说成建模过）。
                cand = _gson_lenient(probe)
                if cand != probe:
                    arr, e3 = _try_load(cand)
                    if e3 is not None:
                        e2 = e3
                        stage = "按宿主宽容度复解（含 gson lenient）后仍失败"
                    else:
                        lenient = "gson lenient（单引号/无引号键/尾逗号）"
                        stage = ""
                else:
                    stage = ("按宿主宽容度复解后仍失败；gson lenient 档未适用"
                             "（无可代换形态）→ 本闸不建模该形态，判 ERROR")
            if e2 is not None:
                col2 = getattr(e2, "colno", None)
                pos2 = f"，约第 {col2} 列" if col2 else ""
                res.err("R1", f"exploreUrl 声明为 JSON 数组但解析失败{pos2}：{e2}"
                               f"（{stage}；直接解析报：{e}）")
                # 直接解析报的是控制字符错时，它不是缺陷本身（gson 宽容接受），复解后的结构错才是真错；
                # 此时不再复述「双引号提前闭合」定位——同一处缺陷会被报成三条（g10b 实证）。
                # 直接解析已是结构错（如 duomle v4 的 Expecting ',' delimiter）时保留定位与两条修法。
                if "Invalid control character" not in str(e):
                    m = re.search(r'"[^"]*?,\{"', explore)
                    if m:
                        res.err("R1", f"疑似未转义的内嵌选项（此处双引号提前闭合字符串）：…{explore[max(0,m.start()-40):m.end()+40]}…")
                        res.err("R1", '修法一：内层引号转义为 \\" ；修法二（更稳）：改用文本行格式 标题::URL,{"webView":true}')
                # v1.15.15 起：即使判 ERROR，也不能吞掉 R5。判 ERROR 只说明「结构有缺陷」，
                # 而 R5 判的是 url 路径有没有 4+ 位长数字段——缺陷前提下该报的照样要报，
                # 否则「有控制字符错 + 有易失数字段」会两个都不报（X5 实证 ERROR=0 WARN=0）。
                r5_err = _r5_collect(arr)
                for i, title, seg in r5_err:
                    res.warn("R5", f"[JSON[{i}]]「{title}」路径含长数字段 '{seg}'，疑似易失地址；须用 3 个独立会话复验是否稳定")
                res.note("R1", f"R1 判 ERROR，但结构已按 gson 口径复解出，R5 照常按条目判：命中 {len(r5_err)} 段")
                return
            # 以下为「复解成功」：R1 降 NOTE，元素级 R5 与结构成功路径走同一个 _r5_collect，
            # 输出同一种 `[JSON[i]]「title」` 归属格式（B8b/D3b 的教训：不再从原文猜 URL）。
            r5_hits = _r5_collect(arr)
            for i, title, seg in r5_hits:
                res.warn("R5", f"[JSON[{i}]]「{title}」路径含长数字段 '{seg}'，疑似易失地址；须用 3 个独立会话复验是否稳定")
            n_items = len(arr) if isinstance(arr, list) else 0
            r5_txt = (f"R5 已按复解出的 {n_items} 个条目逐条补判：命中 {len(r5_hits)} 段" if r5_hits
                      else f"R5 已按复解出的 {n_items} 个条目逐条补判：无 4+ 位长数字段")
            same = "**R3 因 {{...}} 已被占位、分页判据不可靠而跳过**（未检查 ≠ 已通过）；"
            if lenient:
                res.note("R1", "exploreUrl 为 JSON 数组：Python json 直接解析失败（"
                               + str(e) + "），按宿主 gson 宽容度代换后通过（{{...}} 占位 + 字符串内控制字符转义"
                               " + gson lenient 单引号/无引号键/尾逗号）→ 判为解析器宽容度差异；"
                               "**该档只建模上述三形态**（gson-2.13.2 探针实测），无引号值等未证形态仍判 ERROR；"
                               "gson 对数组尾逗号会多读出一个 null 元素，本闸按同口径补齐，"
                               "否则 [JSON[i]] 归属会整体前移一格；" + same + r5_txt +
                               "；JS 语法另用 js_layer_check.py / 真机验证")
            else:
                res.note("R1", "exploreUrl 为 JSON 数组：Python json 直接解析失败（"
                               + str(e) + "），但按宿主 gson 宽容度复解通过"
                               "（{{...}} 占位 + 字符串内控制字符转义）→ 判为解析器宽容度差异；"
                               + same + r5_txt +
                               "；JS 语法另用 js_layer_check.py / 真机验证")
            return
        if not isinstance(arr, list) or not arr:
            res.err("R1", "exploreUrl JSON 不是非空数组")
            return
        for i, it in enumerate(arr):
            if not isinstance(it, dict):
                res.err("R1", f"第 {i} 项不是对象：{it!r}")
                continue
            if "title" not in it or "url" not in it:
                res.err("R1", f"第 {i} 项缺 title/url：{list(it.keys())}")
                continue
            items.append((it["title"], str(it["url"]), f"JSON[{i}]"))
    else:
        # 文档口径（references/booksource-schema.md）：exploreUrl 文本行支持「换行 / &&」分隔多行 URL。
        # 故每行再按 && 拆成多个独立分类项，逐项判 R2/R5，避免 `A::url1&&B::url2` 被并成 1 项、长数字归属错（H1）。
        for ln, line in enumerate(explore.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            for sub in line.split("&&"):
                sub = sub.strip()
                if not sub:
                    continue
                if "::" not in sub:
                    res.err("R2", f"第 {ln} 行缺 '标题::URL' 分隔符：{sub[:80]}")
                    continue
                title, url = sub.split("::", 1)
                items.append((title.strip(), url.strip(), f"行{ln}"))

    if not items:
        res.err("R1", "exploreUrl 未解析出任何分类项")
        return

    res.note("R1", f"exploreUrl 格式={'JSON数组' if is_json else '文本行'}，共 {len(items)} 项")

    for title, raw, where in items:
        url, opt, oerr = split_options(raw, host="explore")
        if oerr:
            res.err("R3", f"[{where}]「{title}」内嵌选项非法：{oerr}")
            continue
        if not re.match(r"^https?://", url):
            # 相对路径：宿主 AnalyzeUrl 以 bookSourceUrl 为基拼接（workflow-detail.md 既有结论；
            # 来读读 2026-10-31 真机调通、读书斋已交付，均为相对 exploreUrl）。
            # bookSourceUrl 为空时无处可拼 → 才是 ERROR。
            if base:
                res.note("R3", f"[{where}]「{title}」为相对路径，宿主以 bookSourceUrl({base}) 拼接")
            else:
                res.err("R3", f"[{where}]「{title}」URL 不以 http(s):// 开头且 bookSourceUrl 为空，宿主无处拼接基址：{url[:80]}")
        if "{{page}}" not in url:
            # v1.15.15：降为提示级。原文是「**可能**永远只取第 1 页」——推测；且实测红的全是
            # 榜单页 / 分类首页（读书斋 10 条分类首页、百草露 2 条榜、yqkxs 7 条榜），本来只有一页。
            # 宿主对 exploreUrl 的翻页只认 {{page}} 模板，不含即不翻页——这是**机制事实**；
            # 但「该分类有没有第二页」静态判不了，按缺陷判会误伤，故只提示、不阻断 --strict。
            res.warn("R3", f"[{where}]「{title}」URL 不含 {{{{page}}}}：分页机会提示（榜单/分类首页本来只有一页，"
                           f"是否缺陷取决于该分类有无第二页，静态判断不了）", blocking=False)
        # 易失地址启发式（判据见 _r5_volatile，与 NOTE 路径共用同一函数，不各写一份）
        for seg in _r5_volatile(url):
            res.warn("R5", f"[{where}]「{title}」路径含长数字段 '{seg}'，疑似易失地址；须用 3 个独立会话复验是否稳定")


def check_search(search, res, base=""):
    if not search:
        res.note("R4", "searchUrl 为空，跳过搜索检查")
        return
    if not isinstance(search, str):
        res.err("R4", f"searchUrl 类型异常（应为字符串，实得 {type(search).__name__}）：无法解析，须改为字符串")
        return
    # @js: / <js> 包裹：宿主先 evalJS 再用返回值，原始 JS 不进 AnalyzeUrl 的 ,{选项} 切分路径；
    # 若调 split_options 会把 JS 代码体内的 `,{`（如函数解构参数）误当行内选项切出 → R4 误报（H6）。
    if re.match(r"^\s*(@js:|<js>)", search):
        url, opt, oerr = search, None, None
    else:
        url, opt, oerr = split_options(search)
    if oerr:
        res.err("R4", f"searchUrl 选项 JSON 非法：{oerr}")
        return
    if not re.match(r"^https?://", url):
        # 与 R3 同口径：相对路径 + bookSourceUrl 非空 = 宿主拼接（来读读真机调通同形态）
        if base:
            res.note("R4", f"searchUrl 为相对路径，宿主以 bookSourceUrl({base}) 拼接")
        else:
            res.err("R4", f"searchUrl 不以 http(s):// 开头且 bookSourceUrl 为空：{url[:80]}")
    # 关键词载体（v1.15.13 精修两处漏报，均为实测）：
    #   ① `"{{key}}" not in url` 会把 R6 自己建议的处方 {{java.encodeURI(key)}} 判成 ERROR ——
    #      处方执行完反而新增一条红，见 `references/maintenance.md` 与 CHANGELOG；
    #   ② `@js:` / `<js>` 动态 URL 里关键词常以 `+key+` 拼接、或整串由 JS 返回，原逻辑只认字面
    #      `{{key}}` → 已交付的 八叉书库 / 手机小说 / luyouxs 三本被误判 ERROR（它们是 JS 返回形态）。
    # 载体判定：整个 searchUrl 原文（含 JS 源码）或 body 里出现 key 变量或 {{key}} 即算。
    # 宿主在 analyzeUrl 之前就把整个串当 URL 处理，故原文（含 JS 尾巴）要一起看。
    # 注意不能用 `search` 全文：`cookie` / `searchkey` 里的 "key" 会被子串匹配骗过
    # （正则已带词边界，但关键词本身可能只出现在 JS 尾巴里，故只取 url 段 + body，不做全文）。
    key_src = url + "\n" + str((opt or {}).get("body", ""))
    KEY_VAR_RE = re.compile(r"(?<![A-Za-z0-9_$])key(?![A-Za-z0-9_$])")
    if "{{key}}" not in key_src and not KEY_VAR_RE.search(key_src):
        res.err("R4", "searchUrl 与 body 里都找不到 key（{{key}} / +key+ / {{java.encodeURI(key)}}），搜索词无处可去")
    # v1.15.13：无选项 = 默认 GET，与显式 method:GET 同口径。
    # 旧写法把 R6 整段嵌在 `if opt:` 内，裸 searchUrl（不写选项）走 else 只打 NOTE
    # → 「GET URL 含 {{key}} 未编码」这条最常命中的提示，恰恰在最常见的写法上不响。
    if opt:
        method = str(opt.get("method", "GET")).upper()
        webview = bool(opt.get("webView"))
        if method == "POST" and webview:
            res.err("R4", "method=POST 与 webView=true 互斥：Android WebView 只能 GET，POST body 会丢失，服务端收不到关键词（duomle 真机事故根因）")
        res.note("R4", f"searchUrl method={method}, webView={webview}")
    else:
        method = "GET"
        res.note("R4", "searchUrl 无选项 → 按默认 method=GET, webView=False 检查")
    # method 显式 POST 不报：关键词走 body，编码由 body 路径决定，与 URL 查询串无关。
    # 已经显式编码的写法（{{java.encodeURI(key)}} 等）不再提示——它是本条 WARN 的处方，
    # 处方执行完还响 = 永远消不掉的红灯（v1.15.13 实测：照建议改完反而先被 R4 判 ERROR）。
    if method == "GET" and "{{key}}" in url:
        res.warn("R6", "GET URL 含 {{key}}：若宿主未自动编码，中文关键词可能未编码；建议 {{java.encodeURI(key)}} 或实测确认",
                     blocking=False)   # v1.15.14：宿主 AnalyzeUrl 默认会对 {{key}} 做 URL 编码（多本已交付源真机可搜），
                     # 属"建议再确认"而非"交付后会坏"；duomle 修复版真机通过却因此被判 strict 失败，是误伤。


def check_consistency(book, res):
    base = book.get("bookSourceUrl")
    if not isinstance(base, str):
        _t = type(base).__name__ if base is not None else "null"
        res.err("R7", f"bookSourceUrl 类型异常（应为字符串，实得 {_t}）：无法判定协议，须改为字符串")
        return
    if not base:
        res.err("R7", "bookSourceUrl 为空")
        return
    b_scheme = "https" if base.startswith("https://") else "http" if base.startswith("http://") else "?"
    if b_scheme == "?":
        res.err("R7", f"bookSourceUrl 协议异常：{base[:60]}")
    for field in ("searchUrl", "exploreUrl"):
        v = book.get(field)
        if not isinstance(v, str):
            continue  # 非字符串字段（数组/空等）无协议可查，跳过
        schemes = set(re.findall(r"https?://", v))
        if schemes and b_scheme != "?":
            other = schemes - {b_scheme + "://"}
            if other:
                res.warn("R7", f"{field} 混用协议 {sorted(schemes)}，bookSourceUrl={b_scheme}；https 若证书不匹配会整段失败")


def main():
    # v1.15.13：--strict 从「只写在用法里」改为真实现。旧版两处用法文本都写了它，
    # 却没有一个分支读它 —— 传了等于没传，WARN 在严格模式下静默放行。
    strict = "--strict" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python3 check_request_layer.py <书源.json> [--strict]")
        sys.exit(2)
    path = args[0]
    if not os.path.exists(path):
        print(f"{RED}文件不存在：{path}{RST}")
        sys.exit(2)

    # v1.15.17（P2-2）：0 字节 / 纯空白 / 非法 JSON 给 exit=2 + 中文结论，
    # 与 validate_booksource.py / js_layer_check.py 同口径（不再抛 Python 堆栈、exit=1）。
    # 合法但无内容（[] / {}）正常走，不在此处误判；读不到内容才 exit=2。
    try:
        with open(path, encoding="utf-8") as _fh:
            _raw = _fh.read()
        data = json.loads(_raw)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as _e:
        _size = 0
        try:
            _size = os.path.getsize(path)
        except OSError:
            pass
        print(f"{RED}文件为空或无有效 JSON（{_size} 字节）：{path}{RST}")
        sys.exit(2)
    books = data if isinstance(data, list) else [data]

    total_err = 0
    total_warn = 0
    total_warn_info = 0
    for bi, book in enumerate(books):
        name = book.get("bookSourceName", f"#{bi}")
        print(f"\n{CYN}{'='*64}{RST}")
        print(f"{CYN}请求层闸 · {name}{RST}")
        print(f"{CYN}{'='*64}{RST}")
        res = Result()
        base = book.get("bookSourceUrl", "")
        check_explore(book.get("exploreUrl"), res, base)
        check_search(book.get("searchUrl"), res, base)
        check_consistency(book, res)

        for c, m in res.errors:
            print(f"{RED}[ERROR]{RST} {c} {m}")
        for c, m, blocking in res.warns:
            # v1.15.15：标签对称。`[WARN ]` 的尾空格看着像排版，实际让「阻断/提示」在肉眼上
            # 无法对齐分辨（一个 6 字、一个 8 字）；改成两个都是 8 字宽的中文标签。
            tag = "[WARN·阻断]" if blocking else "[WARN·提示]"
            print(f"{YEL}{tag}{RST} {c} {m}")
        for c, m in res.notes:
            print(f"{GRN}[NOTE ]{RST} {c} {m}")

        n_block = sum(1 for w in res.warns if w[2])
        n_info = len(res.warns) - n_block
        print(f"\n小计：ERROR={len(res.errors)}  WARN={len(res.warns)}"
              f"（阻断 {n_block} / 提示 {n_info}）  NOTE={len(res.notes)}")
        total_err += len(res.errors)
        total_warn += n_block
        total_warn_info += n_info

    print(f"\n{'='*64}")
    if total_err:
        print(f"{RED}结论：请求层不通过，ERROR={total_err}——这些错误 validate / test_parse 都查不出来，必须修完再交付。{RST}")
        sys.exit(1)
    if strict and total_warn:
        print(f"{RED}结论：--strict: 阻断级 WARN 视为失败，请求层不通过（阻断 WARN={total_warn}）。"
              f"这些是「交付后真会坏」的隐患（分页失效/地址易失/证书不匹配），必须处理。{RST}")
        sys.exit(1)
    if total_warn_info:
        print(f"{YEL}提示：有 {total_warn_info} 条提示级 WARN（不阻断 --strict）——建议实测确认，但不影响交付判定。{RST}")
    # v1.15.17（P2-1）：默认模式下若存在**阻断级** WARN，结论行必须改口。
    # 旧行为是「标签写 [WARN·阻断]、结论写『请求层通过』、exit=0」——同一份报告自相矛盾，
    # 读的人只会看见最后那句「通过」。exit 仍为 0：10 本已交付源在默认模式下的既有结论不能变，
    # 改 exit 会让历史日志与现有判定对不上（任务书明写不许动）。
    if total_warn:
        print(f"{YEL}结论：请求层无 ERROR，但有 {total_warn} 条阻断级隐患"
              f"（未加 --strict，按默认口径放行）——交付前须逐条处理：{RST}"
              f"这些是「交付后真会坏」的隐患（分页失效/地址易失/证书不匹配）。")
    else:
        # 通过时不复述 --strict 口径：回退实验里那句话会让「分支被短路」的日志与正常日志只差 exit code，
        # 从输出看不出"本该失败"（v1.15.13 实测）。口径只在失败分支说一次。
        print(f"{GRN}结论：请求层通过（ERROR=0）。注意：本闸只验「宿主能否解析并发出请求」，不验站点是否真返回预期内容，后者仍需真实页/真机证据。{RST}")
    sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
