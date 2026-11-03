#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跑书源校验器的正负样本集，验证检测器「不漏报、不误报」。

用法:
    python3 evals/run_evals.py [-v]

判定:
    bad 用例  -> 必须命中 expect_error_contains / expect_warn_contains 的每一条关键字(查不漏报)
    good 用例 -> ERROR/WARN 计数必须为 0，且输出里不得出现 forbid_contains 的关键字(查不误报)
    额外基线 -> samples/sample_booksource.json 必须 ERROR=0(样例始终代表"正确交付形态")
    文件级用例(带 file_content, 2026-10-25 P3-10 补) -> 内容逐字节写入临时文件喂校验器,
    主断言是 expect_exit_code(空输入/坏 JSON 就是 exit 2), expect_output_contains 兜文案
    请求层用例(带 booksource_file, v1.15.13 加) -> 不走校验器, 走 scripts/check_request_layer.py;
    标本路径**相对技能根目录**, 主断言 expect_exit_code + expect_error_count, 外加
    expect_attribution —— ERROR 的数字必须能追问到是在哪份 samples/ 文件上数的(E19)
    附加基线 request_layer_expected_output.txt -> 三份标本的闸输出必须与随包全文逐字一致

退出码: 0 = 全部通过；1 = 有失败；2 = 用例文件/校验器缺失。
"""
import os
import sys

# 禁止写 .pyc：测试动作不得污染技能目录（否则 .skill 打包会夹带 __pycache__）
# 两个都要设：sys.dont_write_bytecode 只管本进程，
# PYTHONDONTWRITEBYTECODE 才会被 subprocess 子进程继承——本脚本用 subprocess 调校验器，
# 真正的 pyc 是子进程 import scripts/ 下模块时写的，只设前者无效。
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import json
import re
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)


def _resolve_skill_dir(here):
    """定位含 `scripts/` 的技能根目录, 兼容两种布局。

    (a) 技能包布局: `<root>/evals/run_evals.py` + `<root>/scripts/` —— 直接取上一级。
    (b) 知识库 tools/ 布局: 脚本平铺在 `<root>/*.py`, 评测在 `<root>/evals/`,
        校验器**同级而非 scripts/** —— 旧版硬编码 `scripts/` 会报「找不到校验器」,
        于是知识库那边根本跑不了评测, 只能相信技能包里的那份结果。
    知识库侧 `tools/` 是**别人取工具的地方**, 那边跑不起来等于第二通道不存在。

    规则: 上一级有 `scripts/` 用它; 否则若评测目录的上一级**自身**含校验器, 用它;
    再否则向上找两级。找不到时回退旧行为, 由后续报错如实暴露, 不静默降级。
    """
    parent = os.path.dirname(here)
    if os.path.isdir(os.path.join(parent, "scripts")):
        return parent
    if os.path.isfile(os.path.join(parent, "validate_booksource.py")):
        return parent
    grand = os.path.dirname(parent)
    if os.path.isdir(os.path.join(grand, "scripts")):
        return grand
    if os.path.isfile(os.path.join(grand, "validate_booksource.py")):
        return grand
    return parent


SKILL_DIR = _resolve_skill_dir(HERE)


def _sdir(skill_dir, name):
    """脚本实际所在目录: 优先 `<根>/scripts/`, 平铺布局则退回 `<根>/` 本身。"""
    d = os.path.join(skill_dir, "scripts")
    return d if os.path.isdir(d) else skill_dir


SCRIPTS_BASE = _sdir(SKILL_DIR, None)

VALIDATOR = os.path.join(SCRIPTS_BASE, "validate_booksource.py")
CASES = os.path.join(HERE, "validate_cases.json")
SAMPLE = os.path.join(SKILL_DIR, "samples", "sample_booksource.json")
JS_LAYER = os.path.join(SCRIPTS_BASE, "js_layer_check.py")
SELF_AUDIT = os.path.join(SCRIPTS_BASE, "self_audit.py")
TEST_PARSE = os.path.join(SCRIPTS_BASE, "test_parse.py")
REALEQUIV = os.path.join(HERE, "jsoup_realdevice_equiv.py")
SCRIPTS_DIR = SCRIPTS_BASE
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
# 请求层闸(第五道闸)。用例里的 booksource_file 路径**相对技能根目录**解析，
# 这样标本固定放 samples/、可被引擎侧原样复跑（v1.15.13：此前 ERROR=4 没有落盘标本，
# 数字答不出「在哪份文件上数的」，属 E19 自犯）。
REQUEST_GATE = os.path.join(SCRIPTS_BASE, "check_request_layer.py")
ATTR_PATH = os.path.join(HERE, "request_layer_expected_output.txt")


def _split_output(out):
    """从校验器输出里拆出 [ERROR]/[WARN*]/[NOTE ] 行(断言只认带前缀的行, 见铁律 22/23)。"""
    # 只认行首前缀。v1.15.13 修三处叠加的「恒解析出 0 条」：
    #   ① 请求层闸带 ANSI 颜色码(`\033[31m[ERROR]\033[0m …`), 不剥就永远不 startswith("[ERROR]");
    #   ② [WARN ]/[NOTE ] 末尾有对齐空格, 长度 7 的前缀会吃掉真实内容首字符;
    #   ③ 子进程 stdout 首行为空行, 不 strip 则第一行判不中。
    # 三者任一都让 errors/warns 恒为空 → good 用例假绿、bad 用例假红。
    # v1.15.15：WARN 标签由 `[WARN ]` 改为 `[WARN·阻断]` / `[WARN·提示]`（对齐对称），
    # 旧正则 `^\[WARN\s?\]` 剥不掉新标签，warns 里会残留前缀（计数仍对、文案断言会歪）。
    # 改为吃掉整个方括号标签，两种旧/新形态都能剥。
    lines = [_ANSI_RE.sub("", l).strip() for l in out.splitlines()]
    errors = [re.sub(r"^\[ERROR\]\s?", "", l) for l in lines if l.startswith("[ERROR]")]
    warns = [re.sub(r"^\[WARN[^\]]*\]\s?", "", l) for l in lines if l.startswith("[WARN")]
    notes = [re.sub(r"^\[NOTE\s?\]\s?", "", l) for l in lines if l.startswith("[NOTE")]
    return errors, warns, notes, out


def run_validator(payload, use_stdin=False):
    """把 payload(已是最终文件形态) 交给校验器，返回 (errors, warns, notes, raw, exit_code)"""
    if not os.path.isfile(VALIDATOR):
        print("找不到校验器: %s" % VALIDATOR)
        sys.exit(2)
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        if use_stdin:
            # stdin 模式(`python3 validate_booksource.py -`, docstring 承诺的用法) 曾因
            # text 未赋值 100% 崩栈(UnboundLocalError)。固化为回归: 该路径必须与文件
            # 路径走同一套 json.loads。ensure_ascii=True 避开跨进程文本编码的边缘问题。
            proc = subprocess.run([sys.executable, VALIDATOR, "-"],
                                  input=json.dumps(payload, ensure_ascii=True),
                                  capture_output=True, text=True)
        else:
            proc = subprocess.run([sys.executable, VALIDATOR, path],
                                  capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
    finally:
        if os.path.exists(path):
            os.unlink(path)
    errors, warns, notes, raw = _split_output(out)
    return errors, warns, notes, raw, proc.returncode


def run_validator_file(content, use_stdin=False):
    """文件级用例(2026-10-25 P3-10 补): content 逐字节写入临时文件(或直接走 stdin),
    不走 json.dump —— 覆盖 0 字节/纯空白/[]/坏 JSON 这类"整个文件形态"的标本:
    它们没有 source 对象可包, 退出码(exit 2 输入错误)就是主断言。
    返回 (errors, warns, notes, raw, exit_code)。"""
    if not os.path.isfile(VALIDATOR):
        print("找不到校验器: %s" % VALIDATOR)
        sys.exit(2)
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        if use_stdin:
            proc = subprocess.run([sys.executable, VALIDATOR, "-"],
                                  input=content,
                                  capture_output=True, text=True)
        else:
            proc = subprocess.run([sys.executable, VALIDATOR, path],
                                  capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
    finally:
        if os.path.exists(path):
            os.unlink(path)
    errors, warns, notes, raw = _split_output(out)
    return errors, warns, notes, raw, proc.returncode


def check_case(case, verbose=False):
    src = case.get("source")
    file_content = case.get("file_content")
    if file_content is None and not isinstance(src, dict):
        return False, "用例缺少 source 对象(或 file_content 文件级内容)"
    if file_content is not None:
        # 文件级用例(P3-10): 整个文件形态喂给校验器, 退出码是主断言
        errors, warns, notes, raw, code = run_validator_file(
            file_content, use_stdin=bool(case.get("stdin")))
    else:
        payload = src if case.get("wrap") == "raw" else [src]
        errors, warns, notes, raw, code = run_validator(payload, use_stdin=bool(case.get("stdin")))
    all_text = "\n".join(errors) + "\n" + "\n".join(warns) + "\n" + "\n".join(notes)
    reasons = []

    # 校验器自身崩栈时, errors/warns 解析为空, good 用例会被假性通过(没有输出=没有告警)。
    # 这与本技能"失败不可静默 pass"同构: 堆栈必须让用例变红, 而不是悄悄放行。
    if "Traceback (most recent call last)" in raw:
        reasons.append("校验器在该用例上抛堆栈(见 -v 原始输出)")

    # 退出码断言: 文件级用例(空输入/坏 JSON)的主判据就是 exit 2(输入错误);
    # 行级关键字匹配兜底(退出码对、文案漂移也能发现)。
    if "expect_exit_code" in case and code != case["expect_exit_code"]:
        reasons.append("期望 exit=%s，实际 %s" % (case["expect_exit_code"], code))
    for kw in case.get("expect_output_contains", []):
        if kw not in raw:
            reasons.append("期望输出含 '%s'，实际未出现" % kw)

    for kw in case.get("expect_error_contains", []):
        if kw not in "\n".join(errors):
            reasons.append("期望 ERROR 含 '%s'，实际未报" % kw)
    for kw in case.get("expect_warn_contains", []):
        if kw not in "\n".join(warns):
            reasons.append("期望 WARN 含 '%s'，实际未报" % kw)
    for kw in case.get("expect_note_contains", []):
        if kw not in "\n".join(notes):
            reasons.append("期望 NOTE 含 '%s'，实际未报" % kw)
    if "expect_error_count" in case and len(errors) != case["expect_error_count"]:
        reasons.append("期望 ERROR=%d，实际 %d" % (case["expect_error_count"], len(errors)))
    if "expect_warn_count" in case and len(warns) != case["expect_warn_count"]:
        reasons.append("期望 WARN=%d，实际 %d" % (case["expect_warn_count"], len(warns)))
    if "expect_note_count" in case and len(notes) != case["expect_note_count"]:
        reasons.append("期望 NOTE=%d，实际 %d" % (case["expect_note_count"], len(notes)))
    # 某关键字的**条数**（而不是有没有出现）：用于锁住"同一段 JS 不得重复告警"这类降解,
    # 比 expect_warn_count(总条数, 随新规则增加就漂) 精准得多
    for kw, cnt in (case.get("expect_count_of") or {}).items():
        actual = len([x for x in (errors + warns + notes) if kw in x])
        if actual != cnt:
            reasons.append("含 '%s' 的输出期望 %d 条，实际 %d 条（重复告警/漏报都会在这里暴露）"
                           % (kw, cnt, actual))
    for kw in case.get("forbid_contains", []):
        if kw in all_text:
            reasons.append("不该出现的噪音 '%s'：%s" % (kw, _first_hit(all_text, kw)))

    if verbose and reasons:
        print("   ---- 校验器原始输出 ----")
        for l in raw.splitlines():
            print("   | %s" % l)
    return (not reasons), "; ".join(reasons)


def _first_hit(text, kw):
    for l in text.splitlines():
        if kw in l:
            return l.strip()[:120]
    return ""


def run_request_gate(rel_path, strict=False):
    """把书本样文件交给请求层闸跑一遍，返回 (errors, warns, notes, raw, exit_code)。

    与 run_validator 的区别：闸读的是**文件**而不是内存对象 —— 用例必须钉住一份真实落盘标本，
    引擎侧才能用同一条命令复跑出同一个数（E19：任何 N/N 都要答得出「在哪份文件上数的」）。
    """
    if not os.path.isfile(REQUEST_GATE):
        print("找不到请求层闸: %s" % REQUEST_GATE)
        sys.exit(2)
    # 用相对路径喂闸：报错文案/结论里若回显路径，读出来就是技能内的相对位置
    target = rel_path
    cmd = [sys.executable, REQUEST_GATE, target]
    if strict:
        cmd.append("--strict")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=SKILL_DIR, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    errors, warns, notes, raw = _split_output(out)
    return errors, warns, notes, raw, proc.returncode


def check_request_case(case, verbose=False):
    """请求层用例：多一项 expect_attribution —— 标本必须能答出「数字数的哪份文件」。"""
    rel = case.get("booksource_file")
    if not rel:
        return False, "请求层用例缺少 booksource_file"
    if not os.path.isfile(os.path.join(SKILL_DIR, rel)):
        return False, "请求层用例的标本文件不存在: %s（路径相对技能根目录）" % rel
    errors, warns, notes, raw, code = run_request_gate(rel, strict=bool(case.get("strict")))
    reasons = []
    if "Traceback (most recent call last)" in raw:
        reasons.append("请求层闸在该用例上抛堆栈(见 -v 原始输出)")
    if "expect_exit_code" in case and code != case["expect_exit_code"]:
        reasons.append("期望 exit=%s，实际 %s" % (case["expect_exit_code"], code))
    if case.get("expect_error_count") is not None and len(errors) != case["expect_error_count"]:
        reasons.append("期望 ERROR=%d，实际 %d" % (case["expect_error_count"], len(errors)))
    if case.get("expect_warn_count") is not None and len(warns) != case["expect_warn_count"]:
        reasons.append("期望 WARN=%d，实际 %d" % (case["expect_warn_count"], len(warns)))
    for kw in case.get("expect_output_contains", []):
        if kw not in raw:
            reasons.append("期望输出含 '%s'，实际未出现" % kw)
    for kw in case.get("forbid_contains", []):
        if kw in raw:
            reasons.append("不该出现的输出 '%s'：%s" % (kw, _first_hit(raw, kw)))
    # 归属断言：ERROR/WARN 的数字必须能追问到「哪份文件」——问不出就是没证
    if "expect_attribution" in case and errors + warns:
        if case["expect_attribution"] not in rel:
            reasons.append("归属不符：用例声称在 %s 上数，实际喂的是 %s"
                           % (case["expect_attribution"], rel))
    if verbose and reasons:
        print("   ---- 请求层闸原始输出 ----")
        for l in raw.splitlines():
            print("   | %s" % l)
    return (not reasons), "; ".join(reasons)


def main():
    verbose = "-v" in sys.argv
    if not os.path.isfile(CASES):
        print("找不到用例文件: %s" % CASES)
        sys.exit(2)
    with open(CASES, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=" * 62)
    print("书源校验器质量回归  (%s)" % data.get("desc", "")[:40])
    print("=" * 62)

    total = passed = 0
    for case in data.get("cases", []):
        total += 1
        # 带 booksource_file 的走请求层闸(第五道闸)，其余仍走书源校验器
        if case.get("booksource_file"):
            ok, reason = check_request_case(case, verbose)
        else:
            ok, reason = check_case(case, verbose)
        cid = case.get("id", "?")
        if ok:
            passed += 1
            print("[PASS] %-34s %s" % (cid, case.get("purpose", "")[:44]))
        else:
            print("[FAIL] %-34s %s" % (cid, reason))

    # 附加基线：自带样例必须零 ERROR(它代表正确的交付形态)
    total += 1
    if os.path.isfile(SAMPLE):
        with open(SAMPLE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        errors, warns, _, _, _ = run_validator(payload)
        if not errors:
            passed += 1
            print("[PASS] %-34s ERROR=%d WARN=%d" % ("sample_booksource.json(基线)", len(errors), len(warns)))
        else:
            print("[FAIL] %-34s %s" % ("sample_booksource.json(基线)", errors[0][:90]))
    else:
        print("[FAIL] %-34s 样例文件缺失" % "sample_booksource.json(基线)")

    # 附加: JS 层模拟回归(需 Node; 缺失则跳过不计失败)
    if os.path.isfile(JS_LAYER):
        total += 1
        proc = subprocess.run([sys.executable, JS_LAYER, "--self-test"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            passed += 1
            # 从输出解析真实用例数(不要写死: 新增用例后写死值会谎报)
            m = re.search(r"js_layer 回归: (\d+)/(\d+) 通过", proc.stdout or "")
            n = ("%s/%s" % (m.group(1), m.group(2))) if m else "全通过"
            print("[PASS] %-34s JS层回归 %s" % ("js_layer_check.py", n))
        elif proc.returncode == 2:
            print("[SKIP] %-34s 未检测到 Node, 跳过 JS 层回归" % "js_layer_check.py")
            total -= 1
        else:
            print("[FAIL] %-34s %s" % ("js_layer_check.py", (proc.stdout or proc.stderr).strip()[:120]))

    # 附加: 技能自身一致性自检(悬空引用 / CLI 参数 / 写死计数·版本 / 证据文件随包)
    # 为什么放在这里: 这两类缺陷每轮改动都会新产生(补一个洞就开出新接口), 而"接口接没接上"
    # 只存在于记忆里。挂进回归后, 改完技能跑这一条就够了。
    if os.path.isfile(SELF_AUDIT):
        total += 1
        proc = subprocess.run([sys.executable, SELF_AUDIT],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            passed += 1
            print("[PASS] %-34s 技能自检(悬空引用/CLI参数/写死计数/证据随包)" % "self_audit.py")
        else:
            detail = (proc.stdout or "").strip().splitlines()
            detail = [l for l in detail if l.startswith("[ERROR] ")] or detail
            print("[FAIL] %-34s %s" % ("self_audit.py", (detail[0][:110] if detail else "自检失败")))

    # 附加: 自检的自检(铁律 22/23 —— 检查器自己坏了必须有人知道, 否则"全绿"是虚假安全感)
    if os.path.isfile(SELF_AUDIT):
        total += 1
        proc = subprocess.run([sys.executable, SELF_AUDIT, "--self-test"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            passed += 1
            # 只认实输出里的 N/N; 匹配不上就如实打"未解析", 不要退化成"全通过"这种
            # 听起来像通过的兜底 —— 那正是本技能反复警告的虚假安全感。
            m = re.search(r"反例.*?(\d+)\s*/\s*(\d+)\s*类命中", proc.stdout or "")
            if not m:
                m = re.search(r"反例 (\d+)\s*/\s*(\d+)", proc.stdout or "")
            n = ("%s/%s" % (m.group(1), m.group(2))) if m else "未解析(数字缺失)"
            # 真实基线(1.13.27 加): 沙盒标本测的是虚拟树, 真实技能此刻健康不健康只有这一组在看。
            rb = re.search(r"真实基线.*?(\d+)\s*/\s*(\d+)\s*项通过", proc.stdout or "")
            extra = (", 真实基线 %s/%s" % (rb.group(1), rb.group(2))) if rb else ""
            print("[PASS] %-34s 自检的自检(反例 %s 类全抓%s)"
                  % ("self_audit.py --self-test", n, extra))
        else:
            detail = [l for l in (proc.stdout or "").splitlines()
                      if "漏抓" in l or "FAIL" in l or "真实基线未过" in l]
            print("[FAIL] %-34s %s" % ("self_audit.py --self-test",
                                       (detail[0][:110] if detail else "自测失败")))

    # 附加: 全部脚本冒烟(--help 不得抛堆栈)
    # 为什么需要: CLI 脚本若在 __main__ 里裸 open(sys.argv[1]) 又不校验存在性, 用户手滑打个 --help
    # 就甩一段 Python 堆栈 —— 而这类脚本平时没人跑、compileall 和 pyflakes 全都抓不到。
    # 1.13.24 审查时逐个脚本冒烟, scripts/ 里就 webview_probe.py 一个是裸 open, 已修。
    # 固化成回归: 以后谁再写出裸 open, 这一项立刻变红。
    total += 1
    crashed, smoked = [], 0
    for p in sorted(os.listdir(SCRIPTS_DIR)):
        if not p.endswith(".py"):
            continue
        try:
            proc = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, p), "--help"],
                                  capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            continue            # 真去跑网络/浏览器的脚本, 超时不算崩溃
        smoked += 1
        if "Traceback (most recent call last)" in (proc.stdout or "") + (proc.stderr or ""):
            crashed.append(p)
    if crashed:
        print("[FAIL] %-34s 抛堆栈: %s" % ("scripts 冒烟(--help)", ", ".join(crashed)))
    else:
        passed += 1
        print("[PASS] %-34s %d 个脚本均不抛堆栈" % ("scripts 冒烟(--help)", smoked))

    # 附加: JSOUP 默认引擎自检(铁律 22/23: 校验器自身要有自我证伪标本, 防止改坏默认规则解析)
    if os.path.isfile(TEST_PARSE):
        total += 1
        proc = subprocess.run([sys.executable, TEST_PARSE, "--self-test"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            passed += 1
            m = re.search(r"JSOUP 引擎自检通过", proc.stdout or "")
            print("[PASS] %-34s JSOUP 引擎自检 %s" % ("test_parse.py", "全通过" if m else ""))
        else:
            print("[FAIL] %-34s %s" % ("test_parse.py", (proc.stdout or proc.stderr).strip()[:200]))
    else:
        print("[FAIL] %-34s 文件缺失" % "test_parse.py")

    # 附加: 真机等价回归(校验器输出必须逐值对齐真机 Jsoup, 防「校验绿但真机跑不出」)
    if os.path.isfile(REALEQUIV):
        total += 1
        proc = subprocess.run([sys.executable, REALEQUIV],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            passed += 1
            print("[PASS] %-34s 真机等价回归(校验器 vs 真机 Jsoup)" % "jsoup_realdevice_equiv.py")
        else:
            print("[FAIL] %-34s %s" % ("jsoup_realdevice_equiv.py", (proc.stdout or proc.stderr).strip()[:200]))
    else:
        print("[FAIL] %-34s 文件缺失" % "jsoup_realdevice_equiv.py")

    # 附加基线：请求层闸的验收证据必须逐字对得上随包的全量输出（v1.15.13）
    # 为什么要这一条: ERROR=4 这个数字此前只活在信件里, 随包的 samples/ 里没有它数的那份文件,
    # 接收方无从复算(E19)。现在把闸的真实输出全文存进 evals/request_layer_expected_output.txt,
    # 每次回归逐字比对 —— 闸的任何行为漂移都会在这里变红, 而不是等对方来信问。
    total += 1
    if not os.path.isfile(REQUEST_GATE) or not os.path.isfile(ATTR_PATH):
        print("[FAIL] %-34s %s" % ("请求层闸证据", "闸或证据文件缺失"))
    else:
        # 证据文件 = 三份标本的真实输出依次拼接（生成命令见文件头）
        m = re.search(r"^\s*#\s*gen:(.*)$", open(ATTR_PATH, encoding="utf-8").read(), re.M)
        if not m:
            print("[FAIL] %-34s %s" % ("请求层闸证据", "证据文件缺 `# gen:` 生成命令行，无法复算"))
        else:
            cmds = [c.strip() for c in m.group(1).split(";;") if c.strip()]
            stored = open(ATTR_PATH, encoding="utf-8").read().replace("\r\n", "\n")
            stored_body = (stored.split("<!-- ACTUAL -->", 1)[1]
                           if "<!-- ACTUAL -->" in stored else stored).lstrip("\n")
            stored_segs = ["$ " + seg if not seg.startswith("$ ") else seg
                           for seg in ("$ " + stored_body).split("\n$ ")
                           if seg.strip()] if stored_body.strip() else []
            chunks, replayed = [], 0
            # 平铺布局(知识库 tools/): 证据里的 `python3 scripts/xxx.py` 没有 scripts/ 这一级,
            # 原样复跑会 "can't open file"。只在这时把开头的 `scripts/` 剥掉; 技能包布局
            # (SCRIPTS_BASE 就等于 <根>/scripts) 命令一字不改, 证据逐字比对的语义不受影响。
            _flat = os.path.basename(SCRIPTS_BASE.rstrip("/")) != "scripts"
            for i, c in enumerate(cmds):
                c_run, c_show = c, c
                if _flat:
                    c_run = re.sub(r"^(python3\s+)scripts/", r"\1", c)
                    # 比对用「规范化命令」：把平铺布局实际执行的命令还原成存档里的写法。
                    # 为什么必须还原而不是直接比：不一致要落在**输出**上才有意义；
                    # 若把 `$ python3 scripts/x.py` vs `$ python3 x.py` 也算差异，
                    # 平铺布局会永久红，等于把「布局不同」误报成「闸行为漂移」——
                    # 那是最容易让人关掉这条回归的一种假红。
                    c_show = c
                # 夹具路径不在技能目录里（如临时夹具）时无法保证它还在 —— 退化为读存档段落，
                # 并**明写退化了几条**。静默用存档顶替重跑 = 假绿，这里宁可多打印一行。
                fixture = c.split()[2] if len(c.split()) > 2 else ""
                if fixture and not os.path.exists(os.path.join(SKILL_DIR, fixture)):
                    if i < len(stored_segs):
                        chunks.append(stored_segs[i].rstrip("\n") + "\n")
                    replayed += 1
                    continue
                # 一律 sh -c：夹具路径允许含空格/中文，split() 会切坏；NO_COLOR 归一化颜色输出，
                # PYTHONIOENCODING 防子进程在非 UTF-8 locale 下把中文写崩
                env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")
                proc = subprocess.run(["sh", "-c", c_run], capture_output=True, text=True,
                                      cwd=SKILL_DIR, env=env)
                body = (proc.stdout or "") + (proc.stderr or "")
                # `$ 命令` 行也要比对：少了它，读者不知道这段输出是哪条命令跑出来的（E19 的同一套追问）
                chunks.append("$ %s\n%s[exit=%d]\n" % (c_show, body.rstrip() + "\n", proc.returncode))
            actual = "".join(chunks)
            if actual.strip() == stored_body.strip():
                passed += 1
                n_err = actual.count("[ERROR]")
                extra = ("；其中 %d 条为存档回放，未重跑" % replayed) if replayed else ""
                print("[PASS] %-34s 证据逐字一致(ERROR 行 %d 条%s)"
                      % ("请求层闸证据", n_err, extra))
            else:
                d1 = [l for l in actual.splitlines() if l not in stored_body.splitlines()]
                print("[FAIL] %-34s %s" % ("请求层闸证据",
                                           ("闸输出与随包证据不一致，新增行: " + (d1[0][:80] if d1 else "见 -v"))
                                           if d1 else "闸输出与随包证据不一致(有内容消失，见 -v)"))

    print("=" * 62)
    print("结果: %d/%d 通过" % (passed, total))
    print("=" * 62)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
