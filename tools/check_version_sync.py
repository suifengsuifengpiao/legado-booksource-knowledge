#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本同步检查（打包前门禁）· check_version_sync.py
=================================================
用途：在把技能包推送 / 打包前，确认三处版本声明一致：
  - SKILL.md 的 frontmatter `version: X.Y.Z`
  - _meta.json 的 `"version": "X.Y.Z"`
  - 各 scripts/*.py 模块 docstring 中的显式「当前版本：vX.Y.Z」标注（若有）

来历：v1.15.17 收口时，check_request_layer.py 的 docstring 已标 1.15.17，
      但 SKILL.md / _meta.json 当时仍是 1.15.16，文档未同步——漂移靠人工收口才发现。
      引擎侧回执（2026-11-02）建议门禁加「打包前比对 docstring 与 version」。

退出码：0 一致 / 1 不一致 / 2 用法错误
"""
import sys, os, re, json, glob


def extract_current_version(path):
    """取模块 docstring 中形如『当前版本：vX.Y.Z』或『版本 vX.Y.Z』的显式声明。
    不含此类声明的脚本返回 None（不强制检查，避免误伤历史变更注释里的版本号）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(4000)
    except OSError:
        return None
    m = re.search(r'当前版本[:：]?\s*v?(\d+\.\d+\.\d+)', text)
    if m:
        return m.group(1)
    return None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    skill_md = os.path.join(root, "SKILL.md")
    meta_json = os.path.join(root, "_meta.json")
    if not os.path.isfile(skill_md) or not os.path.isfile(meta_json):
        print(f"[SKIP] 非技能包（缺 SKILL.md / _meta.json）：{root}")
        return 0

    fail = 0

    # ---- SKILL.md frontmatter version ----
    ver_skill = None
    with open(skill_md, encoding="utf-8") as fh:
        head = fh.read(4000)
    m = re.search(r"^version:\s*([\w.]+)", head, re.M)
    if m:
        ver_skill = m.group(1)
    else:
        print("[ERROR] SKILL.md frontmatter 未找到 version")
        fail = 1

    # ---- _meta.json version ----
    ver_meta = None
    try:
        with open(meta_json, encoding="utf-8") as fh:
            meta = json.load(fh)
        ver_meta = str(meta.get("version", ""))
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] _meta.json 解析失败：{e}")
        fail = 1

    print(f"[INFO] SKILL.md  version = {ver_skill}")
    print(f"[INFO] _meta.json version = {ver_meta}")

    if ver_skill != ver_meta:
        print(f"[ERROR] 二者不一致：SKILL.md={ver_skill} vs _meta.json={ver_meta}")
        fail = 1

    # ---- scripts 显式标注（只看形如「当前版本：vX.Y.Z」的声明）----
    if ver_skill:
        for py in sorted(glob.glob(os.path.join(root, "scripts", "*.py"))):
            decl = extract_current_version(py)
            if decl is None:
                continue
            print(f"[INFO] {os.path.basename(py)} 当前版本标注 = {decl}")
            if decl != ver_skill:
                print(f"[ERROR] {os.path.basename(py)} 标注 {decl} ≠ 版本 {ver_skill}")
                fail = 1

    if fail:
        print("[RESULT] 版本同步：不一致（exit=1）")
        return 1
    print("[OK] 版本同步：SKILL.md / _meta.json / 显式标注脚本 三处一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
