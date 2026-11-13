#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_font.py — 字体反爬 & 正文加密 诊断与破解工具。

======================= 它能做什么 =======================
1. 字体反爬·站型 A【私有区码位重定向】(最常见):
   - 站点用自定义 web font, 把汉字映射到私有区编码(U+E000~F8FF), 抓到的 HTML 是"乱码字符"。
   - 本工具下载字体文件, 解析 cmap; 若字形名是标准的(uni4E00 / cidxxxx), 可【自动反推】
     "私有区编码 → 真实汉字" 映射, 直接生成书源 replaceRegex 片段, 一键落地!
   - 若字形名是随机名(glyph0001), 则标注"需人工对照", 输出私有区编码清单供比对。
2. 字体反爬·站型 B【CJK 基本区恒等 cmap + 字形轮廓替换】(v1.15.24 新增识别,
   v1.15.25 能力结论更正):
   - cmap 里【没有】私有区码位, 码位与字形名 uniXXXX 恒等自洽, 混淆发生在 glyph 轮廓
     重绘/重排；抓到的正文是"看得见却不认识"的汉字, 不是私有区乱码。
   - 只认站型 A 的工具会把这类字体误报成"可能非加密字体"(假阴性)。本工具显式分型。
   - 【v1.15.25 更正】字体文件的形态 ≠ 字符置换关系。站型 B 只说明"这份字体长什么样",
     不能据此判定规则层能否还原：站点若把有限套固定字符置换表按 font.url 索引下发,
     规则层用 jsLib 查表即可解码正文与目录。故本分支 rule_layer_recoverable 由 False
     改为 None(未判定), 不给假映射, 也不再下"规则层无法还原"的禁令。
   - 单份字体只判站型; "是否会话级动态字形"须另取多份同站字体比对轮廓集合, 不自动下结论。
3. 正文内容加密: 检测正文是否 base64 / hex 编码, 给出 @js 解密骨架提示。
======================================================================

用法:
  python3 reverse_font.py <页面URL 或 本地HTML文件> [--out report.json]
  python3 reverse_font.py <本地字体文件 .woff2/.woff/.ttf/.otf> [--out report.json]
    ^ SPA/JSON 接口站的字体不走 HTML @font-face(形如 font:{url:'/static/fonts/<hex>.woff2'}),
      页面夹具里没有可提取的 @font-face —— 直接把字体文件本身作为分析对象。
"""
import argparse
import json
import os
import re
import sys
import tempfile
from urllib.parse import urljoin

FONT_RE = re.compile(
    r'@font-face[^}]*?src:\s*url\((["\']?)([^"\'()]+\.(?:woff2?|ttf|otf))\1?\)',
    re.I | re.S,
)

try:
    import requests
    HAVE_REQUESTS = True
except Exception:
    HAVE_REQUESTS = False


def infer_unicode_from_glyphname(glyphname):
    """从字形名推断真实 unicode。uni4E00 -> 0x4E00; cid 形式无法单推, 返回 None。"""
    if not glyphname:
        return None
    m = re.match(r"uni([0-9A-Fa-f]{4,6})$", glyphname)
    if m:
        return int(m.group(1), 16)
    return None


# ---- 站型判据（v1.15.24 新增）----
# 只认「私有区码位重定向」会把另一类字体反爬判成「可能非加密字体」(假阴性)：
# 站点把 cmap 做成 CJK 基本区恒等映射、把混淆放在 glyph 轮廓重绘/重排上，
# 抓到的正文不是私有区乱码而是「看得见却不认识」的汉字。判据必须显式分型。
CJK_UNIFIED_START = 0x4E00
CJK_UNIFIED_END = 0x9FFF
CJK_CMAP_MIN_ENTRIES = 2000          # CJK 常用字集量级阈值，低于此不认为是整套字表
CJK_CMAP_MIN_RATIO = 0.90            # cmap 落在 CJK 基本区的比例下限
IDENTITY_GLYPHNAME_MIN_RATIO = 0.90  # uniXXXX 与码位自洽的比例下限


def read_font_format(path):
    """读文件头 4 字节判字体容器格式；纯函数，不解析字体本体。"""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        return {"format": "unknown", "magic": ""}
    if magic == b"wOF2":
        fmt = "woff2"
    elif magic == b"\x00\x01\x00\x00":
        fmt = "truetype"
    elif magic == b"OTTO":
        fmt = "cff/otf"
    else:
        fmt = "unknown"
    return {"format": fmt, "magic": magic.hex()}


def classify_font_obfuscation(bestcmap, font_path):
    """确定性站型分型：纯函数，只吃 cmap 与文件头，不联网、不做语义猜测。

    返回 {type, evidence, rule_layer_recoverable, note}。type 三态：
      pua_codepoint_redirect   私有区码位重定向（既有分支，可自动反推 replaceRegex）
      glyph_shape_cjk_identity CJK 基本区恒等 cmap + 字形轮廓替换
      no_font_obfuscation      未检出上述两类特征（不等于「没有加密」）

    rule_layer_recoverable 三态（v1.15.25 更正语义）:
      True  本工具已自动反推出可落地的映射（仅站型 A 且字形名标准时）
      False 已由独立复算证实规则层不可还原（当前无分支返回此值）
      None  未判定 —— 本工具只吃 cmap + 文件头, 判不了字符置换关系。
            站型 B 与 no_font_obfuscation 一律 None, 不得据此下"无解"结论。
    """
    total = len(bestcmap)
    fmt = read_font_format(font_path)
    priv = [c for c in bestcmap if (0xE000 <= c <= 0xF8FF) or c >= 0xF0000]

    if priv:
        return {
            "type": "pua_codepoint_redirect",
            "evidence": {"total_cmap": total, "private_count": len(priv), **fmt},
            "rule_layer_recoverable": True,
            "note": "私有区编码重定向：字形名为 uniXXXX 时可直接反推『私有区码位→真字』并生成 replaceRegex。",
        }

    cjk = [c for c in bestcmap if CJK_UNIFIED_START <= c <= CJK_UNIFIED_END]
    identity_named = sum(
        1 for code, gname in bestcmap.items()
        if infer_unicode_from_glyphname(gname) == code
    )
    cjk_ratio = (len(cjk) / total) if total else 0.0
    identity_ratio = (identity_named / total) if total else 0.0
    evidence = {
        "total_cmap": total,
        "cjk_basic_ratio": round(cjk_ratio, 4),
        "identity_glyphname_ratio": round(identity_ratio, 4),
        **fmt,
    }
    if (total >= CJK_CMAP_MIN_ENTRIES
            and cjk_ratio >= CJK_CMAP_MIN_RATIO
            and identity_ratio >= IDENTITY_GLYPHNAME_MIN_RATIO):
        return {
            "type": "glyph_shape_cjk_identity",
            "evidence": evidence,
            # v1.15.25: 由 False 改 None。False 是「已证实不可还原」的实证结论,
            # 而本工具只看字体形态, 从未取证过字符置换关系, 没有资格下这个结论。
            "rule_layer_recoverable": None,
            "note": (
                "字形轮廓替换站型：cmap 是 CJK 基本区恒等映射，混淆发生在 glyph 轮廓重绘/重排，"
                "不存在『私有区码位→真字』映射可反推。"
                "【v1.15.25 更正】此前本分支直接判 rule_layer_recoverable=False 并写"
                "『规则层无法自动还原 / 目录名仍不可救』, 已证伪：那三条限制"
                "（QueryTTF 无 woff2 解码分支 / glyphToUnicode 精确 HashMap 无容差 / 字形集合可随会话变）"
                "只封闭了『java.queryTTF + java.replaceFont 字体 API』这一条通道, "
                "并不封闭规则层的纯字符串置换解码通道 —— 后者完全不经过字体 API。"
                "实站反证 www.aaawz.cc：站点下发有限 16 套固定字符置换表, "
                "font.url 文件名前 12 位即表号; 规则层按表号查表可同时解码正文与目录名"
                "（本地四通道独立复算: Python 换语言 / Node 原始 jsLib / Node 端到端 ruleContent / "
                "Node 端到端 ruleToc; 实站夹具 1496 条目录全量解出、0 失败）。"
                "【不得据本判据下无解结论】规则层能否还原, 须另查响应体: "
                "① 正文/目录乱码是否来自有限套固定置换表; ② 表是否随响应下发或可按 font.url 索引; "
                "③ 是否能在 jsLib 内置表并由规则层逐字查表解码。三条任一成立即可还原。"
                "本判据只对单份字体判站型；『是否会话动态』须另取多份同站字体比对轮廓集合，本工具不自动下此结论。"
            ),
        }
    return {
        "type": "no_font_obfuscation",
        "evidence": evidence,
        "rule_layer_recoverable": None,
        "note": "未检出私有区重定向或 CJK 恒等 cmap 字形替换特征；不排除其它加密形态，需结合正文响应另行取证。",
    }


def build_mapping(bestcmap):
    """bestcmap: {codepoint(int): glyphname(str)}。
    返回 (auto_map, manual_codes):
      auto_map      : {私有区codepoint: 真实unicode}  推断成功的
      manual_codes  : [私有区codepoint...]             推断失败的(需人工对照字形)
    """
    auto_map = {}
    manual = []
    for code, gname in bestcmap.items():
        is_priv = (0xE000 <= code <= 0xF8FF) or (code >= 0xF0000)
        if not is_priv:
            continue
        real = infer_unicode_from_glyphname(gname)
        if real is not None:
            auto_map[code] = real
        else:
            manual.append(code)
    return auto_map, manual


def analyze_font(path):
    """解析字体文件, 返回诊断 dict。"""
    from fontTools.ttLib import TTFont
    f = TTFont(path)
    bestcmap = f.getBestCmap() or {}
    auto_map, manual = build_mapping(bestcmap)
    priv = [c for c in bestcmap if (0xE000 <= c <= 0xF8FF) or c >= 0xF0000]
    cls = classify_font_obfuscation(bestcmap, path)
    return {
        "path": path,
        "total_cmap": len(bestcmap),
        "private_codepoints": [hex(c) for c in priv],
        "auto_mapping": {hex(c): chr(r) for c, r in auto_map.items()},
        "auto_mapping_hex": {hex(c): hex(r) for c, r in auto_map.items()},
        "manual_codes": [hex(c) for c in manual],
        "fully_auto": bool(auto_map) and not manual,
        # v1.15.24 新增：站型分型（原字段一个不动，保证改前/改后可 A/B）
        # v1.15.25：能力字段为三态, None 表示未判定, 不再由站型直接推断
        "obfuscation_type": cls["type"],
        "rule_layer_recoverable": cls["rule_layer_recoverable"],
        "obfuscation_evidence": cls["evidence"],
        "obfuscation_note": cls["note"],
    }


def _decode_html(raw):
    """页面字节流解码: utf-8 严格优先, 失败退 gb18030(与 test_parse/reverse_crypto 同一套)。

    旧实现用 r.text(requests 无 charset 头时按 latin-1 兜底) —— GBK 页面整页乱码。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")


def _json_escape_char(ch):
    """把字符转成 JSON 安全形式(私有区/astral 字符原样, 控制字符用 \\uXXXX)。

    旧实现对 >U+FFFF 生成 `\\u%08X`(8位hex) —— 那不是合法 JSON 转义, 粘进书源的
    replaceRegex 会解析失败或还原成错字符(控制符+字面量)。astral 字符在 UTF-8 JSON
    里原样合法, Gson/Java(UTF-16)都能正确承接, 无需手工代理对。
    """
    o = ord(ch)
    if o < 0x20:
        return "\\u%04X" % o
    return ch


def _java_regex_literal(code):
    """私有区 codepoint -> Java 正则里可用的字面量。

    <=U+FFFF 用 `\\uXXXX`(Legado replaceRegex 的既定写法); astral(平面15/16 PUA,
    >0xFFFF)不能写 `\\u` + 5位hex(Java 正则只认4位), 原样字符在 UTF-8/UTF-16 下都安全。
    """
    if code <= 0xFFFF:
        return "\\u%04X" % code
    return chr(code)


def generate_replace_regex(auto_maps):
    """auto_maps: [{codepoint:real}, ...] 多个字体合并。返回 replaceRegex 条目列表(JSON 字符串)。"""
    merged = {}
    for am in auto_maps:
        merged.update(am)
    items = []
    for code, real in merged.items():
        pattern = _java_regex_literal(code)  # Java 正则字面量(astral 不能用 \u+5位hex)
        repl = _json_escape_char(chr(real))  # 真实汉字
        items.append('{"regex": "%s", "replacement": "%s", "useTo": 0}' % (pattern, repl))
    return items


def detect_content_crypto(html):
    """启发式检测正文是否被 base64 / hex 编码。"""
    res = {"suspect_base64": False, "suspect_hex": False, "note": ""}
    m = re.search(r'<div[^>]*id=["\']?article["\']?[^>]*>(.*?)</div>', html, re.S | re.I)
    text = m.group(1) if m else html
    plain = re.sub(r"<[^>]+>", "", text).strip()
    if not plain:
        return res
    if re.fullmatch(r"[A-Za-z0-9+/=\s]{40,}", plain):
        # 收窄防误报: 无标点的英文正文也全是 base64 字符集内的字母。真 base64 长度
        # 必为 4 的倍数且通常混数字; 两者都不满足时更像普通文本。
        compact = re.sub(r"\s", "", plain)
        if len(compact) % 4 == 0 and re.search(r"\d", compact):
            res["suspect_base64"] = True
            res["note"] = "正文疑似 base64 加密, 需用 @js 解码(base64)后填回 ruleContent"
    elif re.fullmatch(r"[0-9a-fA-F\s]{40,}", plain) and len(plain.replace(" ", "")) % 2 == 0:
        res["suspect_hex"] = True
        res["note"] = "正文疑似 hex 编码, 需用 @js 解码(hex->str)后填回 ruleContent"
    return res


def extract_fonts(html, base, out_dir):
    """从 HTML 的 @font-face 提取字体 URL 并下载到 out_dir。返回 [(url, local_path)]。"""
    if not HAVE_REQUESTS:
        return []
    found = dict.fromkeys(m.group(2) for m in FONT_RE.finditer(html or ""))
    out = []
    for u in found:
        absu = urljoin(base, u) if base else u
        try:
            r = requests.get(absu, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) < 5_000_000:
                fn = "font_%d" % len(out)
                p = os.path.join(out_dir, fn)
                with open(p, "wb") as _f:
                    _f.write(r.content)
                out.append((absu, p))
        except Exception:
            pass
    return out


FONT_FILE_SUFFIXES = (".woff2", ".woff", ".ttf", ".otf")


def _is_font_file(p):
    return isinstance(p, str) and p.lower().endswith(FONT_FILE_SUFFIXES)


def diagnose(target, out=None):
    local_font = _is_font_file(target)
    if local_font:
        # SPA/JSON 接口站的字体不走 HTML @font-face(形如 font:{url:'/static/fonts/<hex>.woff2'})，
        # 页面夹具里没有可提取的 @font-face —— 直接把字体文件本身作为分析对象。
        html = ""
        base = ""
    elif target.startswith("http://") or target.startswith("https://"):
        if not HAVE_REQUESTS:
            print("[错误] 需要 requests 才能抓取 URL"); sys.exit(2)
        r = requests.get(target, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        # r.content + 显式解码: 不用 r.text(无 charset 头时 latin-1 兜底 -> GBK 页面乱码)
        html = _decode_html(r.content)
        base = target
    else:
        with open(target, encoding="utf-8", errors="ignore") as _f:
            html = _f.read()
        base = ""

    tmp = tempfile.mkdtemp(prefix="legado_font_")
    print("[1/3] 直接分析本地字体文件..." if local_font else "[1/3] 提取并下载字体文件...")
    fonts = [(target, target)] if local_font else extract_fonts(html, base, tmp)
    font_reports = []
    auto_maps = []
    for u, p in fonts:
        try:
            fr = analyze_font(p)
            font_reports.append(fr)
            if "auto_mapping_hex" in fr:
                auto_maps.append({int(k, 16): ord(v) for k, v in fr["auto_mapping"].items()})
        except Exception as e:
            font_reports.append({"path": p, "error": str(e)})

    print("[2/3] 检测正文加密...")
    crypto = detect_content_crypto(html)

    print("[3/3] 生成诊断与书源落地模板...")
    items = generate_replace_regex(auto_maps) if auto_maps else []
    has_priv = any(fr.get("private_codepoints") for fr in font_reports if "private_codepoints" in fr)
    # v1.15.24：显式识别「CJK 恒等 cmap + 字形轮廓替换」站型，不再落到
    # 「未发现私有区编码(可能非加密字体)」——那句是本工具此前的假阴性结论。
    # v1.15.25：unrecoverable 只收「已独立证实不可还原」(False)；站型 B 现为 None,
    # 不进此列, verdict 也不再写「规则层无法自动还原」。
    shape_fonts = [fr for fr in font_reports
                   if fr.get("obfuscation_type") == "glyph_shape_cjk_identity"]
    unrecoverable = [fr for fr in font_reports if fr.get("rule_layer_recoverable") is False]
    if fonts and has_priv and items:
        verdict = "字体加密, 已自动反推映射, 可直接落地 replaceRegex"
    elif fonts and has_priv:
        verdict = "字体加密, 但字形名非标准, 需人工对照字形后补全映射"
    elif fonts and shape_fonts:
        verdict = ("字形轮廓替换站型(CJK 基本区恒等 cmap / 无私有区编码)："
                   "字体 API 通道不适用, 但规则层能力【未判定】; "
                   "须另查响应体有无可按 font.url 索引的有限置换表(见 obfuscation_note); "
                   "不生成假映射, 也不下无解结论")
    elif fonts:
        verdict = "检测到自定义字体但未发现私有区编码(可能非加密字体)"
    else:
        verdict = "未发现自定义字体(无字体反爬)"
    if crypto["suspect_base64"] or crypto["suspect_hex"]:
        verdict += "; 且正文疑似加密"

    report = {
        "target": target,
        "fonts": font_reports,
        "content_crypto": crypto,
        "auto_mapping_count": len(items),
        "replace_regex_items": items,
        "verdict": verdict,
        # v1.15.25 三态透传：旧写法 `False if unrecoverable else ... else True`
        # 会把站型 B 的 None 错报成 True(假绿)。现在只有真的反推出映射才给 True。
        "rule_layer_recoverable": (
            False if unrecoverable
            else True if items
            else None
        ),
        "shape_font_count": len(shape_fonts),
    }
    if out:
        with open(out, "w", encoding="utf-8") as _f:
            json.dump(report, _f, ensure_ascii=False, indent=2)
    return report


def _print_report(r):
    print("\n" + "=" * 56)
    print("字体 / 内容反爬诊断报告")
    print("=" * 56)
    print("结论: %s" % r["verdict"])
    for fr in r["fonts"]:
        if "error" in fr:
            print("  [字体] %s 解析失败: %s" % (fr["path"], fr["error"]))
            continue
        print("  [字体] %s" % os.path.basename(fr["path"]))
        print("        私有区编码: %s" % (", ".join(fr["private_codepoints"]) if fr["private_codepoints"] else "无"))
        if fr.get("obfuscation_type"):
            _rl = fr.get("rule_layer_recoverable")
            _rl_txt = {True: "可自动反推", False: "已证实不可还原", None: "未判定(须另取证)"}.get(_rl, str(_rl))
            print("        站型: %s ｜ 规则层能力: %s"
                  % (fr["obfuscation_type"], _rl_txt))
            print("        判据: %s" % json.dumps(fr.get("obfuscation_evidence"), ensure_ascii=False))
            print("        说明: %s" % fr.get("obfuscation_note"))
        if fr.get("auto_mapping"):
            sample = list(fr["auto_mapping"].items())[:8]
            print("        自动反推(编码->汉字): %s" % ", ".join("%s->%s" % (k, v) for k, v in sample))
        if fr.get("manual_codes"):
            print("        需人工对照: %s" % ", ".join(fr["manual_codes"][:10]))
    c = r["content_crypto"]
    if c["suspect_base64"] or c["suspect_hex"]:
        print("  [正文加密] %s" % c["note"])
    if r["replace_regex_items"]:
        print("\n-- 可直接粘贴进书源 replaceRegex 的条目 --")
        print("[\n" + ",\n".join("  " + it for it in r["replace_regex_items"]) + "\n]")


def main():
    ap = argparse.ArgumentParser(description="字体反爬 & 正文加密 诊断")
    ap.add_argument("target", help="页面 URL 或本地 HTML 文件")
    ap.add_argument("--out", help="报告保存为 JSON")
    args = ap.parse_args()
    r = diagnose(args.target, out=args.out)
    _print_report(r)
    if args.out:
        print("\n报告已保存 -> %s" % args.out)


if __name__ == "__main__":
    main()
