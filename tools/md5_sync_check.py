#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/ 与技能包 scripts/ 的同源同步门禁。

用途：知识库 tools/ 是技能包 scripts/ 的镜像副本。工具判错一次，下游会拿
错误结论去改本来没坏的书源——比没有工具更坏。本脚本把「两处是否同源」
变成可机器判定的门禁，任一脚本不一致即 exit=1。

用法：
    python3 md5_sync_check.py <技能包目录或 scripts 目录>
    python3 md5_sync_check.py --scripts /path/to/legado-booksource-debug/scripts

判定：
    同名文件 md5 不同      -> FAIL（双源漂移）
    scripts 有、tools 无    -> FAIL（缺失）
    tools 有、scripts 无    -> WARN（本地特化脚本，不阻断）

退出码：
    0  全部一致（允许有 WARN）
    1  存在 FAIL
    2  用法错误或路径不存在
"""

import argparse
import hashlib
import os
import sys

SELF = os.path.basename(os.path.abspath(__file__))


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_scripts(path):
    """允许传技能包根目录、scripts 目录，或直接传某个 .py。"""
    if os.path.isfile(path) and path.endswith(".py"):
        return os.path.dirname(os.path.abspath(path))
    if os.path.isdir(os.path.join(path, "scripts")):
        return os.path.join(os.path.abspath(path), "scripts")
    if os.path.isdir(path):
        return os.path.abspath(path)
    return None


def main():
    ap = argparse.ArgumentParser(
        description="比对知识库 tools/ 与技能包 scripts/ 的逐文件 md5")
    ap.add_argument("source", nargs="?",
                    help="技能包根目录 / scripts 目录 / 其中任一 .py")
    ap.add_argument("--scripts", dest="scripts_opt",
                    help="显式指定 scripts 目录（等价于位置参数）")
    ap.add_argument("--tools", default=os.path.dirname(os.path.abspath(__file__)),
                    help="tools 目录，默认取本脚本所在目录")
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args()

    src_arg = args.scripts_opt or args.source
    if not src_arg:
        print("[ERROR] 需要指定技能包目录或 scripts 目录（--help 看用法）")
        return 2

    scripts_dir = resolve_scripts(src_arg)
    if not scripts_dir or not os.path.isdir(scripts_dir):
        print(f"[ERROR] 找不到 scripts 目录：{src_arg}")
        return 2

    tools_dir = os.path.abspath(args.tools)
    if not os.path.isdir(tools_dir):
        print(f"[ERROR] 找不到 tools 目录：{tools_dir}")
        return 2

    src = {f for f in os.listdir(scripts_dir)
           if f.endswith(".py") and os.path.isfile(os.path.join(scripts_dir, f))}
    dst = {f for f in os.listdir(tools_dir)
           if f.endswith(".py") and os.path.isfile(os.path.join(tools_dir, f))}
    dst.discard(SELF)  # 本门禁脚本自身不是技能脚本

    fails, warns, oks = [], [], []

    for name in sorted(src & dst):
        a = md5_of(os.path.join(tools_dir, name))
        b = md5_of(os.path.join(scripts_dir, name))
        if a == b:
            oks.append(name)
        else:
            fails.append((name, a, b))

    for name in sorted(src - dst):
        fails.append((name, "(缺失)", "存在"))

    for name in sorted(dst - src):
        warns.append(name)

    for name, a, b in fails:
        if a == "(缺失)":
            print(f"[FAIL] {name}  tools 缺失，scripts 有")
        else:
            print(f"[FAIL] {name}  tools={a[:8]} scripts={b[:8]}")
    if not args.quiet:
        for name in warns:
            print(f"[WARN] {name}  仅 tools 有（本地特化，不同步）")
        for name in oks:
            print(f"[ OK ] {name}")

    print("=" * 60)
    print(f"[INFO] scripts: {scripts_dir}")
    print(f"[INFO] tools  : {tools_dir}")
    print(f"[INFO] 一致 {len(oks)} / 漂移或缺失 {len(fails)} / 本地特化 {len(warns)}")

    if fails:
        print(f"[ERROR] 双源漂移：{len(fails)} 个脚本不一致——下游会拿到与技能包不同的判定结果")
        return 1
    print("[OK] tools/ 与 scripts/ 逐文件 md5 全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
