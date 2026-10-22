#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_font.py — 字体反爬 & 正文加密 诊断与破解工具。

======================= 它能做什么 =======================
1. 字体反爬(最常见的小说站加密):
   - 站点用自定义 web font, 把汉字映射到私有区编码(U+E000~F8FF), 抓到的 HTML 是"乱码字符"。
   - 本工具下载字体文件, 解析 cmap; 若字形名是标准的(uni4E00 / cidxxxx), 可【自动反推】
     "私有区编码 → 真实汉字" 映射, 直接生成书源 replaceRegex 片段, 一键落地!
   - 若字形名是随机名(glyph0001), 则标注"需人工对照", 输出私有区编码清单供比对。
2. 正文内容加密: 检测正文是否 base64 / hex 编码, 给出 @js 解密骨架提示。
======================================================================

用法:
  python3 reverse_font.py <页面URL 或 本地HTML文件> [--out report.json]
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
    return {
        "path": path,
        "total_cmap": len(bestcmap),
        "private_codepoints": [hex(c) for c in priv],
        "auto_mapping": {hex(c): chr(r) for c, r in auto_map.items()},
        "auto_mapping_hex": {hex(c): hex(r) for c, r in auto_map.items()},
        "manual_codes": [hex(c) for c in manual],
        "fully_auto": bool(auto_map) and not manual,
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
                open(p, "wb").write(r.content)
                out.append((absu, p))
        except Exception:
            pass
    return out


def diagnose(target, out=None):
    if target.startswith("http://") or target.startswith("https://"):
        if not HAVE_REQUESTS:
            print("[错误] 需要 requests 才能抓取 URL"); sys.exit(2)
        r = requests.get(target, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        # r.content + 显式解码: 不用 r.text(无 charset 头时 latin-1 兜底 -> GBK 页面乱码)
        html = _decode_html(r.content)
        base = target
    else:
        html = open(target, encoding="utf-8", errors="ignore").read()
        base = ""

    tmp = tempfile.mkdtemp(prefix="legado_font_")
    print("[1/3] 提取并下载字体文件...")
    fonts = extract_fonts(html, base, tmp)
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
    if fonts and has_priv and items:
        verdict = "字体加密, 已自动反推映射, 可直接落地 replaceRegex"
    elif fonts and has_priv:
        verdict = "字体加密, 但字形名非标准, 需人工对照字形后补全映射"
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
    }
    if out:
        json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
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
