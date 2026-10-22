#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L0 先证伪探针(rrssk 中继搜索实证, 1.13.16 新增).

为什么需要它(1.13.15 之前踩的坑):
    给 74xswz/rrssk 中继搜索做签名时, 一上来就抽页面常量、复刻 FNV-1a+xorshift 算法(v14→v17→v18),
    还下过"Legado 不可能"的错结论。事后用一道 5 分钟廉价测试翻案: 把签名乱填发一次, 返回 200 ——
    因为多数前端闸(DOM 指纹/_ad52ca、isTrusted/_b13bf3)**服务端根本不校验**, 纯算式即过。
    这个探针就是把"先证伪"从一条红规变成一道绕不过去的步骤。

设计原则(对应利弊权衡, 见 SKILL.md 复盘清单第 19 条):
    - 窄范围: 只当书源搜索含签名特征(sign/token/_sig/...)时才激活; 否则直接退出 0, 不打扰 happy path。
    - mock 优先、绝不主动打真站: 默认【对比模式】吃你提供的两份响应(--baseline 正确签名 / --garbage 乱填签名),
      只做客观 diff, 报告"服务端是否区分两者"。这避开了 rrssk 实测踩过的坑(__snc 一次性 + 本机 IP 限流:
      探针自己打真站会烧掉一次性 token、把 IP 限流, 反而让后面真请求 403)。
    - 不下最终结论: 只报"服务端是否校验", 不替你判"有解/无解"——后者永远在 agent 脑子里。
    - 无样本时给一段可直接跑的 curl 模板(把签名参数改成乱值), 由你手动发一次看状态码/响应差异。

用法:
    python3 l0_probe.py <书源.json>
    python3 l0_probe.py <书源.json> --baseline ok.html --garbage bad.html
    python3 l0_probe.py <书源.json> --json        # 机器可读输出

退出码: 0 = 正常(无论证伪结论如何, 它只是辅助提醒, 不阻断构建)
"""
import sys
import re
import json
import argparse
import difflib

# 签名特征参数(故意排除裸 auth/ts: author 含 auth、时间戳几乎必有, 否则误伤普通源)
# 每个元素 = (展示名, 正则)
SIGN_PATTERNS = (
    ("sign", r"\bsign\b"), ("signature", r"signature"), ("_sig", r"_sig\b"),
    ("token", r"\btoken\b"), ("nonce", r"\bnonce\b"), ("hmac", r"\bhmac\b"),
    ("md5", r"\bmd5\b"), ("encrypt", r"encrypt"), ("_snc", r"_snc\b"),
    ("snc", r"\bsnc\b"), ("vcode", r"vcode"), ("captcha", r"captcha"),
    ("verification", r"verification"),
)
# comment 里的"已完成 L0"标记: 含任一词即视为已证伪, 不再 WARN
# 词表刻意窄: generic 词(probe/已测/先测)太容易误命中 —— 书源 comment 出现
# "webview probe"/"已测搜索" 就跟"签名是否被服务端校验已证伪"无关, 误判会静默
# 跳过证伪提醒, 正是本探针要防的假绿。只留明确指向"签名证伪已做"的说法。
L0_MARKERS = ("l0证伪", "l0 证伪", "证伪过", "先证伪", "l0_probe", "签名不校验", "签名已证伪")


def detect_signature(text):
    return [name for name, pat in SIGN_PATTERNS if re.search(pat, text, re.I)]


def _search_blob(src):
    blob = ""
    su = src.get("searchUrl")
    if isinstance(su, str):
        blob += su + " "
    rs = src.get("ruleSearch")
    if isinstance(rs, dict):
        blob += json.dumps(rs, ensure_ascii=False) + " "
    return blob


def _comment(src):
    return " ".join(str(src.get(k, "")) for k in ("comment", "bookSourceComment"))


def load_source(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data[0] if data else {}
    return data


def _read_file(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _diff(baseline, garbage):
    """对比两份响应, 客观报告服务端是否区分。不替 agent 下"有解/无解"结论。"""
    b1, b2 = _read_file(baseline), _read_file(garbage)
    ratio = difflib.SequenceMatcher(None, b1, b2).ratio()
    len1, len2 = len(b1), len(b2)
    print("  baseline 长度: %d   garbage 长度: %d   文本相似度: %.2f" % (len1, len2, ratio))
    if ratio >= 0.9:
        print("  → 两份响应高度相似: 服务端大概率【不校验】签名(乱填也返回同样内容)。")
        print("    走 L1 eval 官方 signJs / L2 webView 让其自行算签名即可, 无需本地复刻算法。")
    elif ratio <= 0.3:
        print("  → 两份响应截然不同: 服务端大概率【校验】签名(乱填被拦/返回错误页)。")
        print("    需 L1 eval 官方 JS 或 L2 webView; 若签名本身依赖真实设备指纹则书源可能无解。")
    else:
        print("  → 两份响应部分相似: 无法单凭文本相似度判定, 请结合状态码/错误文案人工判断。")


def main():
    ap = argparse.ArgumentParser(description="L0 先证伪探针: 确认书源签名是否被服务端校验(窄范围/mock 优先)")
    ap.add_argument("source", help="书源 JSON(单对象或数组)")
    ap.add_argument("--baseline", help="正确签名时的响应文件(html/json), 用于对比模式")
    ap.add_argument("--garbage", help="乱填签名时的响应文件(html/json), 用于对比模式")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    try:
        src = load_source(args.source)
    except Exception as e:
        print("[L0] 无法解析书源 %s: %s" % (args.source, e), file=sys.stderr)
        return 0

    blob = _search_blob(src)
    found = detect_signature(blob)
    if not found:
        if args.json:
            print(json.dumps({"signature_detected": False, "l0_required": False}, ensure_ascii=False))
        else:
            print("[L0] 未检测到签名特征(sign/token/_sig/signature/...), 无需证伪。退出。")
        return 0

    cmt = _comment(src)
    l0_done = any(mk.lower() in cmt.lower() for mk in L0_MARKERS)

    if args.json:
        out = {"signature_detected": True, "indicators": found, "l0_done": l0_done}
        if args.baseline and args.garbage:
            out["mode"] = "compare"
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("[L0] 检测到签名特征: %s" % ", ".join(found))
        if l0_done:
            print("[L0] comment 含证伪标记, 视为已完成 L0, 跳过提醒。")
            return 0
        print("[L0] 尚未发现 L0 证伪记录 —— 动手逆向前先做这道廉价测试:")
        if args.baseline and args.garbage:
            print("  [对比模式] baseline=%s  garbage=%s" % (args.baseline, args.garbage))
            _diff(args.baseline, args.garbage)
        else:
            print("  步骤: 用正确签名发一次拿 ok.html, 把签名参数(sign/_ts/nonce...)改成乱值再发一次拿 bad.html,")
            print("        然后: python3 l0_probe.py <书源.json> --baseline ok.html --garbage bad.html")
            print("  或直接手跑(把签名参数改成乱值, 看状态码/响应是否和正常请求不同):")
            # 单百分号: 这里不经 % 格式化, curl 的 -w 占位符必须原样是 %{http_code};
            # 写成 %% 会让用户照抄到手的模板失效(双百分号被 curl 当字面量)。
            print('    curl -s -o bad.html -w "%{http_code}\\n" "https://站/s?q=剑来&sign=AAAA&_ts=9999999999"')
            print("  判读: bad 返回 200 且内容与正常请求相似 → 服务端不校验, 纯算式即过,")
            print("        可走 L1 eval 官方 signJs / L2 webView; 返回 403/400 或错误页 → 服务端校验, 才需逆向。")
            print("  ⚠️ 不要替代理由: 本探针只给证据, 不下'有解/无解'结论; 最终判断在 agent。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
