#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
self_audit.py —— 技能自身的一致性自检（改完技能必跑）。

为什么需要它（1.13.10 审计的教训）：
    改技能是"点状"的, 但技能内部是"网状"依赖的 —— 文档互相引用、文档描述脚本参数、文档抄了当前
    用例数。补一个洞会顺带开出新接口, 而"新接口接没接上"只存在于人的记忆里。于是每次改完技能,
    下次检查总能翻出新的悬空引用 / 死配置 / 写死计数(1.13.10 一次审计就翻出 7 处, 其中 5 处是
    上一轮新增能力的配套欠账)。本脚本把"能 100% 确定、零误报"的三类机械检查固化, 不靠记忆。

刻意不做的事（宁可少抓, 不可乱叫）：
    - 不做语义检查。"铁律写了却没配套检测"这类抓不到 —— 靠 SKILL.md 的「改动本技能后必查」清单人工过。
    - 不查不带 .md 文件名的「」引用。中文引号大量是术语(「双清闭环」「获取成功」), 一律当引用会
      产生几十条噪音; 噪音会被习惯性忽略, 而被忽略的护栏比没有护栏更糟(它给的是虚假安全感)。
    - 不检查"文档提到的参数脚本不认"之外的方向(实现有、文档没提), 那类多为可选参数, 报了是噪音。

四项检查：
    1. 悬空引用: 形如 `xxx.md「yyy」` 的明确指向, 必须在目标文档里能找到对应章节(精确/包含/字覆盖)。
    2. CLI 参数一致性: 文档里写在脚本名旁边的 `--xxx`, 脚本必须真的认(get_opt 或字面量)。
    3. 写死计数 / 版本号漂移: 文档或脚本里写死的 "N/N"、"N 项回归"; CHANGELOG 末条版本 ≠ SKILL.md version。
    4. 证据文件随包: 文档按文件名引用的证据(`.kt/.java/.jar/.dex/.apk/.skill/.html/.png`),
       必须在技能目录里真实存在 —— 防止"结论进了技能、证据留在 /tmp"这类自包含性破口。

用法:
    python3 scripts/self_audit.py            # 全量自检; 有 ERROR 则 exit 1
    python3 scripts/self_audit.py --verbose  # 额外打印目标文档的章节清单(排查"匹配规则太严"时用)
    python3 scripts/self_audit.py --self-test  # 自检的自检: 沙盒正/反标本 + 真实技能基线(铁律 22/23)
"""
import os
import re
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)

DOC_FILES = sorted(glob.glob(os.path.join(SKILL_DIR, "references", "*.md")))
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
if os.path.isfile(SKILL_MD):
    DOC_FILES.append(SKILL_MD)
PY_FILES = sorted(glob.glob(os.path.join(SKILL_DIR, "scripts", "*.py"))) + \
           sorted(glob.glob(os.path.join(SKILL_DIR, "evals", "*.py")))

EMOJI = "🔴🔥⚠️✅📌🚀💡❌"


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _norm(s):
    return re.sub(r"[\s%s]" % EMOJI, "", s or "")


def _anchors(text):
    """可被引用的锚点 = `#` 章节标题 + 列表项里的加粗短语。

    后者必须收: 文档里大量引用的是「双清闭环」「铁律 16」这类写在列表项里的术语
    (`- **铁律 16：…的正解 = 「双清闭环」…**`), 只认 `#` 标题会把它们全误判成悬空。
    """
    out = []
    for line in text.splitlines():
        m = re.match(r"^#{2,6}\s+(.*)", line)
        if m:
            out.append(m.group(1).strip())
            continue
        m2 = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*", line)
        if m2:
            out.append(m2.group(1).strip()[:80])
    return out


# ---------------------------------------------------------------- 1) 悬空引用
# 只认"明确指向某个 md 文件"的引用: xxx.md「yyy」 / xxx.md 的「yyy」
REF_RE = re.compile(r"([a-zA-Z0-9_\-]+\.md)\s*[的]?\s*[「『]([^」』]{2,60})[」』]")


def _match_any(q, titles):
    """引用内容是否能在某个章节标题里对上。逐级放宽: 精确包含 → 去括号后缀 → 去斜杠 → 字覆盖率。"""
    if not q:
        return False        # 全空白引用(如 `xxx.md「  」`): 空串是任何标题的子串, 会恒真假放行
    for t in titles:
        if q in t or t in q:
            return True
        t2 = re.sub(r"[（(].*?[)）]", "", t)          # 去掉标题里的 (补充说明)
        if q in t2 or t2 in q:
            return True
        q3, t3 = q.replace("/", ""), t2.replace("/", "")
        if q3 in t3 or t3 in q3:
            return True
        if q3 and sum(1 for c in set(q3) if c in t3) / float(len(set(q3))) >= 0.8:
            return True     # 字覆盖率: 容忍「目录/正文翻页」vs 标题「目录/正文分页翻页(…)」这类措辞差
    return False


def check_dangling_refs(errors, verbose=False):
    titles = {}
    for p in DOC_FILES:
        titles[os.path.basename(p)] = [_norm(t) for t in _anchors(_read(p))]
    for p in DOC_FILES:
        for i, line in enumerate(_read(p).splitlines(), 1):
            for mdname, quoted in REF_RE.findall(line):
                cand = titles.get(mdname)
                if cand is None:
                    errors.append(
                        "[%s:%d] 引用了不存在的文档 `%s`（「%s」）→ 文件不在 references/ 下"
                        % (os.path.basename(p), i, mdname, quoted))
                    continue
                if not _match_any(_norm(quoted), cand):
                    msg = ("[%s:%d] 悬空引用: `%s` 里没有与「%s」对应的章节 → 读者按指引会扑空。"
                           "要么补写该章节, 要么改掉引用。"
                           % (os.path.basename(p), i, mdname, quoted))
                    if verbose:
                        msg += " 现有章节: %s" % " / ".join(titles[mdname])[:400]
                    errors.append(msg)


# ---------------------------------------------------------------- 2) CLI 参数一致性
def _impl_args(src):
    """脚本实际认的参数: get_opt("--x") 调用 + 源码里的 "--xxx" 字面量"""
    out = set(re.findall(r'get_opt\(\s*["\'](--[a-zA-Z][a-zA-Z0-9\-]*)', src))
    out |= {x for x in re.findall(r'["\'](--[a-zA-Z][a-zA-Z0-9\-]{2,})["\']', src)}
    return out


def _doc_args(script_name, docs):
    """文档里写在脚本名旁边的 --xxx。

    窗口必须卡死在「同行 + 遇到下一个 .py 之前」: 放宽到跨行/固定长度会把**别的脚本**的参数
    算到它头上(实测 220 字符窗口给 validate_booksource.py 抓出 --cold/--source —— 那俩是
    realcheck 和 js_layer_check 的), 一开箱就是十几条噪音。宁可漏, 不可吵。
    """
    out = set()
    for name, text in docs:
        for line in text.splitlines():
            for m in re.finditer(re.escape(script_name), line):
                seg = line[m.end():]
                nxt = re.search(r"[a-zA-Z0-9_\-]+\.py", seg)
                if nxt:
                    seg = seg[:nxt.start()]
                # 排除 `--https://...` 这类: 那是 Legado 调试命令里"只调正文页"的 URL 前缀, 不是本脚本参数
                seg = re.sub(r"--[a-zA-Z][a-zA-Z0-9\-]*://", " ", seg)
                out |= set(re.findall(r"(--[a-zA-Z][a-zA-Z0-9\-]{2,})", seg))
    return out


def check_cli_args(errors):
    docs = [(os.path.basename(p), _read(p)) for p in DOC_FILES]
    for p in PY_FILES:
        name = os.path.basename(p)
        if name == "self_audit.py":
            continue        # 不自检自己, 避免自指噪音
        impl = _impl_args(_read(p))
        doc = _doc_args(name, docs)
        for a in sorted(doc - impl):
            errors.append("[%s] 文档写了参数 `%s`, 但脚本不认(实现只认: %s) → 照文档跑会静默无效"
                          % (name, a, ", ".join(sorted(impl)) or "无"))


# ---------------------------------------------------------------- 3) 写死计数 / 版本漂移
# 只认"回归/通过/用例"语境里的 N/N —— 裸的 \d+/\d+ 满地都是(HTTP 404/403、铁律 15/16、
# 步骤 1/4), 一律当计数会刷出十几条噪音。噪音会被习惯性忽略, 等于没有护栏。
# 方向必须两边都看: 当初的真实 bug 是 `JS层回归 7/7`(关键词在数字**前面**),
# 只看后面会漏掉它。行级是否含回归语境由下面的 `re.search(回归|通过|用例)` 把关。
COUNT_RE = re.compile(r"(?<![\w.])(\d{1,3})\s*/\s*(\d{1,3})(?![\w.])")
ITEM_RE = re.compile(r"(\d{1,3})\s*项(?:回归|用例)")


def check_hardcoded(errors):
    # 3a) 写死的计数: 用例数会随能力增长, 抄进代码必然过期。
    #     只查 .py —— 文档里大量 N/N 是"实测六种形态 6/6 通过"这类历史叙述, 一律报会刷屏;
    #     而真正的写死计数只可能出现在回归脚本的打印/断言里(当初的 bug 就在 run_evals.py 的字符串里)。
    for p in PY_FILES:
        base = os.path.basename(p)
        if base == "self_audit.py":
            continue
        for i, line in enumerate(_read(p).splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if "re.search" in s or "re.compile" in s or "%s/%s" in s or r"(\d" in s:
                continue        # 解析用的正则串, 不是写死值
            if not re.search(r"回归|通过|用例|self-test", line):
                continue        # 必须带回归语境; "步骤 1/4" 之类不算
            for m in COUNT_RE.finditer(line):
                errors.append("[%s:%d] 写死计数 '%s' → 用例数会增长, 必须解析实输出而非手写"
                              % (base, i, m.group(0)))
            for m in ITEM_RE.finditer(line):
                errors.append("[%s:%d] 写死项数 '%s' → 同上, 改为解析实输出"
                              % (base, i, m.group(0)))

    # 3b) 版本漂移: CHANGELOG 末条的"版本 A → B" 必须等于 SKILL.md 的 version
    if not os.path.isfile(SKILL_MD):
        return
    text = _read(SKILL_MD)
    m = re.search(r"^version:\s*([\d.]+)", text, re.M)
    if not m:
        errors.append("[SKILL.md] 缺少 version 声明")
        return
    ver = m.group(1)
    # 三处 version 必须一致: SKILL.md frontmatter / _meta.json / (若有)CHANGELOG 末条。
    # 不能只依赖 CHANGELOG —— 变更日志一旦移出正文, hist 恒为空, 这道检查会静默失效。
    meta_p = os.path.join(SKILL_DIR, "_meta.json")
    if os.path.isfile(meta_p):
        try:
            import json as _json
            mv = _json.load(open(meta_p, encoding="utf-8")).get("version")
            if mv and mv != ver:
                errors.append("[版本漂移] SKILL.md version=%s, _meta.json version=%s → 两处必须同步"
                              % (ver, mv))
        except Exception:
            pass
    else:
        # 数据源消失不能静默：文件不在就整段跳过 = 这道检查随之消失，而自检照样打印"全部通过"。
        # 注：_meta.json 是本技能 .skill 包的组成部分，随包分发；若你是手工建目录、本就没有
        # 此文件的场景，这条可忽略 —— 那种情况下版本漂移检查确实无数据源可用。
        errors.append("[版本漂移] _meta.json 缺失 → 版本漂移检查已失去数据源, 无法判定"
                      "(手工安装无此文件时可忽略)")
    hist = re.findall(r"版本\s*([\d.]+)\s*→\s*([\d.]+)", text)   # 保留，有日志时仍然生效
    if hist and hist[-1][1] != ver:
        errors.append("[SKILL.md] 版本漂移: CHANGELOG 末条写到 %s, 但 version 是 %s"
                      % (hist[-1][1], ver))


# ---------------------------------------------------------------- 4) 证据文件随包
# 教训(1.13.23 之后补): 文档按**文件名**引用了证据(如 `AnalyzeByJSoup.kt`), 但该文件只存在于
# /tmp、从未进技能包 —— 技能包自包含性破了, 唯一副本还在易失目录里, 哪天 /tmp 一清就只剩结论没有出处。
# 第 1 类悬空引用只管 `xxx.md「yyy」` 这种**文档章节**指向, 抓不到文件级引用, 故单列一类。
#
# 宁可少抓不可乱叫 —— 这里是踩过坑才收紧的:
#   初版查"所有带这些扩展名的反引号 token", 一跑刷出 50 条, 其中 46 条是噪音:
#     站点 URL 路径(`/list/N/{{page}}.html`、`rrssk.com/003Q.html`)、APK 内部类
#     (`help/http/e.java`、`BookContent.kt`、`service/WebService.java`)、CHANGELOG 里的
#     `v1.13.xx.skill` 历史叙述、外部工具 `rhino-1.7.14.jar`、Legado 调试语法 `--https://…html`。
#   噪音会被习惯性忽略, 被忽略的护栏比没有护栏更糟(虚假安全感)。故只保留**零误报**的那一种形状:
#   **只查带技能内目录前缀的引用**(`references/ scripts/ evals/ samples/`)。
#
# 由此立下约定: 引用证据一律写**技能内路径**(如 `references/evidence/AnalyzeByJSoup.kt`),
# 不要只写裸文件名 —— 裸名既无法区分"APK 内部类"还是"本技能证据", 也逃过本检查。
EVID_RE = re.compile(
    r"`((?:references|scripts|evals|samples)/[^`\s]+?"
    r"\.(?:kt|java|jar|dex|apk|skill|html|png|json))`")


def check_evidence_files(errors):
    for p in DOC_FILES:
        for i, line in enumerate(_read(p).splitlines(), 1):
            for token in EVID_RE.findall(line):
                if os.path.exists(os.path.join(SKILL_DIR, token)):
                    continue
                errors.append(
                    "[%s:%d] 证据文件未随包: 文档引用了 `%s`, 但技能目录里找不到 → "
                    "结论无出处可核。把文件放进技能内(如 references/evidence/)再引用"
                    % (os.path.basename(p), i, token))


# ---------------------------------------------------------------- 自检的自检(--self-test)
# 铁律 22/23: 校验器自身必须有能区分正误的标本, 否则"检查器坏了"和"确实没问题"的输出长得
# 一模一样 —— 护栏反而给虚假安全感。四类检查此前只在 1.13.10 用**手工植入**验证过一次,
# 那份验证没固化进任何脚本, 所以之后若有人改坏正则(比如 EVID_RE 永远不匹配), 检查会静默空转,
# 而技能每次自检都打印"全部通过"。本函数把正/反标本固化成一条命令。
#
# 做法: 在临时目录搭一棵迷你技能树, 用 subprocess 真跑本脚本。
# 为什么不直接调 check_*(errors): 那测的是函数, 测不到"模块级常量靠 __file__ 推导 SKILL_DIR"
# 这条真实链路; 沙盒跑的是端到端行为, 顺带把目录推导也验了。
_PITFALLS = """\
## 正文空根因决策树
- **双清闭环**：先 header 清、再 content 清。
"""


def _sandbox_files(dirty):
    """迷你技能树。dirty=True 时注入四类缺陷, 每类对应一个可被断言的关键词。

    **沙盒必须与真实技能结构双向同步**（1.13.28 立，两轮各踩一次才抽象出来）：
      · 真实有的，沙盒不能缺 —— 缺了会让"干净树"被误判，正例直接 0/1。
        实测：沙盒未放 `_meta.json`，而主自检新增了"缺失即报错"，干净树反而被拦，
        回归掉到 39/40。
      · 真实没有的，沙盒不能依赖 —— 依赖了触发路径就是假的，删掉即漏抓。
        实测：沙盒靠正文 changelog 触发版本漂移，而真实技能 1.13.25 已删正文日志，
        后人一旦以"日志都移出正文了"为由清理那两行，这条反例就只剩 4/5。
    缺任何一半都会瞎，且瞎法不同：前者"该放行的被拦"，后者"该抓的抓不到"。
    改技能文件结构（增删改名）后，回来同步这棵树。
    """
    demo = 'TIMES = get_opt("--times")\n'
    if dirty:
        demo += 'print("回归: 38/38 通过")\n'                  # 3a 写死计数
        ev = "references/evidence/missing.kt"                 # 4 证据未随包
        changelog = "版本 0.9.9 → 2.0.0"                       # 3b 版本漂移
        extra = ("引用 `references/pitfalls.md「根本不存在的章节xyz」`\n"   # 1 悬空引用
                 "跑 `python3 scripts/demo.py --no-such-flag`\n")          # 2 CLI 参数
    else:
        ev = "references/evidence/real.kt"
        changelog = "版本 0.9.9 → 1.0.0"
        extra = ("引用 `references/pitfalls.md「双清闭环」`\n"
                 "跑 `python3 scripts/demo.py --times 3`\n")
    return {
        "SKILL.md": "---\nversion: 1.0.0\n---\n" + extra +
                    "证据见 `%s`\nCHANGELOG: %s\n" % (ev, changelog),
        "references/pitfalls.md": _PITFALLS,
        "scripts/demo.py": demo,
        "references/evidence/real.kt": "// 占位\n",
        # dirty 时故意与沙盒 SKILL.md 的 1.0.0 不一致：让「版本漂移」走 _meta.json 比对这条
        # **真实链路**，而不是只靠正文 changelog（真实技能已无正文日志，那是一条假路径）。
        "_meta.json": '{"version": "9.9.9"}' if dirty else '{"version": "1.0.0"}',
    }


# 反向标本: 缺陷 → 报错里必现的关键词(少一个就说明那类检查空转了)
_DIRTY_MARKERS = [
    ("悬空引用", "悬空引用"),
    ("CLI 参数", "文档写了参数"),
    ("写死计数", "写死计数"),
    ("版本漂移", "版本漂移"),
    ("证据随包", "证据文件未随包"),
]


def _real_baseline():
    """真实技能树的基线断言 —— 补虚拟沙盒压根测不到的那一段。

    沙盒里 version 写死 1.0.0、变更日志写死「版本 0.9.9 → X」, 它验证的只是"判据能不能
    匹配上这段假文本", 真实技能当前是哪版、两处 version 同不同步、真实目录跑一遍是不是
    真绿, 它一概不知。1.13.25 就栽在这: 正文变更日志移出后, 版本漂移检查的数据源恒为空、
    整段永不触发, 而 --self-test 因为喂的是写死的虚拟日志照样报 5/5 通过 —— 真实链路已瞎,
    护栏还在喊绿。本组断言把真实文件拉进自测, 让"--self-test 绿"真的等于"本技能当前健康"。
    """
    import subprocess

    checks = []   # [(名字, 通过?, 备注)]

    ver = None
    if os.path.isfile(SKILL_MD):
        m = re.search(r"^version:\s*([\d.]+)", _read(SKILL_MD), re.M)
        ver = m.group(1) if m else None
    checks.append(("真实 SKILL.md 能取到 version", ver is not None, ver or "取不到"))

    mv = None
    meta_p = os.path.join(SKILL_DIR, "_meta.json")
    if os.path.isfile(meta_p):
        try:
            import json as _json
            mv = _json.load(open(meta_p, encoding="utf-8")).get("version")
        except Exception:
            mv = None
    checks.append(("真实 _meta.json 能取到 version", mv is not None, mv or "取不到"))

    checks.append(("两处 version 同步",
                   bool(ver) and bool(mv) and ver == mv,
                   "%s vs %s" % (ver, mv)))

    p = subprocess.run([sys.executable, os.path.abspath(__file__)],
                       capture_output=True, text=True)
    checks.append(("真实技能自检 exit=0", p.returncode == 0,
                   "exit=%d" % p.returncode))
    return checks


def self_test(verbose=True):
    import shutil
    import subprocess
    import tempfile

    tmp = tempfile.mkdtemp(prefix="selfaudit_selftest_")
    sd = os.path.join(tmp, "scripts")
    try:
        os.makedirs(sd, exist_ok=True)
        shutil.copy2(os.path.abspath(__file__), os.path.join(sd, "self_audit.py"))

        def run(dirty):
            for rel, text in _sandbox_files(dirty).items():
                fp = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(text)
            p = subprocess.run([sys.executable, os.path.join(sd, "self_audit.py")],
                               capture_output=True, text=True)
            return p.returncode, (p.stdout or "") + (p.stderr or "")

        ok = True
        lines = []
        rc, out = run(False)
        pos_ok = (rc == 0)
        ok &= pos_ok
        lines.append("  正例(干净树应放行): %s" % ("OK exit=0" if pos_ok else "FAIL\n%s" % out[:400]))

        rc, out = run(True)
        # 必须只在 [ERROR] 行里找 marker —— 踩过坑: 最初用 `marker in out` 匹配整个输出,
        # 而脚本 header 本身就印着「悬空引用 / CLI 参数 / 写死计数·版本 / 证据文件随包」,
        # 于是「悬空引用」「写死计数」两条**恒真**, 反向标本形同虚设。证伪实验(故意把
        # 悬空引用判据改成 `if False:`)才暴露它: 检查器已然全瞎, 自测照样报 5/5 通过。
        # 教训: 断言要盯"报错行", 不是"程序输出过这个词"。
        err_lines = [l for l in out.splitlines() if l.startswith("[ERROR] ")]
        hit = 0
        for name, marker in _DIRTY_MARKERS:
            got = any(marker in l for l in err_lines)
            hit += 1 if got else 0
            if not got:
                lines.append("  反例漏抓: %s(输出里没有「%s」)" % (name, marker))
        neg_ok = (rc != 0 and hit == len(_DIRTY_MARKERS))
        ok &= neg_ok
        lines.append("  反例(注入缺陷应全抓): %d/%d 类命中, exit=%d"
                     % (hit, len(_DIRTY_MARKERS), rc))

        # 真实基线: 上面两组都是虚拟树, 测不到"本技能此刻到底健康不健康"
        real = _real_baseline()
        real_ok_n = sum(1 for c in real if c[1])
        ok &= (real_ok_n == len(real))
        lines.append("  真实基线(本技能当前状态): %d/%d 项通过" % (real_ok_n, len(real)))
        for name, good, note in real:
            if not good:
                lines.append("    真实基线未过: %s (%s)" % (name, note))

        if verbose:
            print("=" * 62)
            print("self_audit 自检(护栏的护栏)")
            print("=" * 62)
            for l in lines:
                print(l)
            print("-" * 62)
            print("self_audit 自检: 正例 %d/1, 反例 %d/%d, 真实基线 %d/%d → %s"
                  % (1 if pos_ok else 0, hit, len(_DIRTY_MARKERS),
                     real_ok_n, len(real), "通过" if ok else "失败"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--self-test" in sys.argv:
        return self_test()
    verbose = "--verbose" in sys.argv
    errors = []
    check_dangling_refs(errors, verbose)
    check_cli_args(errors)
    check_hardcoded(errors)
    check_evidence_files(errors)
    print("=" * 62)
    print("技能自身一致性自检 (悬空引用 / CLI 参数 / 写死计数·版本 / 证据文件随包)")
    print("=" * 62)
    if not errors:
        print("[OK] 四项检查全部通过")
        return 0
    for e in errors:
        print("[ERROR] %s" % e)
    print("-" * 62)
    print("自检结果: ERROR=%d" % len(errors))
    return 1


if __name__ == "__main__":
    sys.exit(main())
