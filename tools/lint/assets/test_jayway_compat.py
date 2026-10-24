# -*- coding: utf-8 -*-
"""jayway_compat 对拍单测 —— 与真 jayway json-path 2.9.0（Java）零共享对拍。

基准: /tmp/jwbench/java_out.tsv（Bench.java 跑出, 复刻 legado_app_3.25.apk 内
com.jayway.jsonpath 2.9.x 行为 + AnalyzeByJSonPath 三入口）。
用例: /tmp/jwbench/cases.jsonl

跑法: python3 test_jayway_compat.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jayway_compat as J

CASES = os.environ.get("JW_CASES", "/tmp/jwbench/cases.jsonl")
JAVA_OUT = os.environ.get("JW_JAVA_OUT", "/tmp/jwbench/java_out.tsv")

EXC_MAP = {
    "PathNotFoundException": J.PathNotFound,
    "InvalidPathException": J.InvalidPath,
    "JsonPathException": J.JsonPathErr,
}


def py_value(rule, data, mode):
    if mode == "read":
        v = J.JsonPath(rule).read(data)
        return "OK:" + _ser(v)
    if mode == "getString":
        return "OK:" + _ser_str(J.legado_get_string(rule, data))
    if mode == "getStringList":
        return "OK:" + _ser_list(J.legado_get_string_list(rule, data))
    if mode == "getList":
        v = J.legado_get_list(rule, data)
        return "OK:" + _ser(v)
    if mode == "compile":
        J.JsonPath(rule)
        return "OK:compiled"
    raise ValueError(mode)


def _ser(v):
    """对齐 Bench.scalarOrJson: 标量→Java 风格, 容器→json-smart 紧凑格式"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    if hasattr(v, "__str__") and type(v).__name__ == "_KeySet":
        # keys() → Map.keySet(); Bench.scalarOrJson: JsonPath.parse(Set) 抛 → String.valueOf → '[a, b]'
        return str(v)
    return str(v)


def _ser_str(s):
    if s is None:
        return "null"
    return json.dumps(s, ensure_ascii=False)


def _ser_list(l):
    return "[" + ",".join(_ser_str(x) if isinstance(x, str) else _ser(x) for x in l) + "]"


def main():
    cases = [json.loads(l) for l in open(CASES, encoding="utf-8") if l.strip()]
    expected = {}
    for line in open(JAVA_OUT, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            expected[parts[0]] = (parts[1], parts[2])
    npass = nfail = 0
    fails = []
    for c in cases:
        cid, mode, rule = c["id"], c["mode"], c["rule"]
        data = json.loads(c["json"])
        exp = expected.get(cid)
        if exp is None or exp[0] != mode:
            fails.append("%s: Java 基准缺失" % cid)
            nfail += 1
            continue
        try:
            got = py_value(rule, data, mode)
            if got == exp[1]:
                npass += 1
            else:
                nfail += 1
                fails.append("%s [%s] %s\n    java: %s\n    py  : %s"
                             % (cid, mode, rule, exp[1], got))
        except Exception as e:
            etype = type(e).__name__
            m = {v.__name__: k for k, v in EXC_MAP.items()}
            got = "ERR:" + m.get(etype, etype)
            if got == exp[1]:
                npass += 1
            else:
                nfail += 1
                fails.append("%s [%s] %s\n    java: %s\n    py  : %s (%s)"
                             % (cid, mode, rule, exp[1], got, e))
    print("对拍: %d 通过 / %d 失败（共 %d）" % (npass, nfail, npass + nfail))
    for f in fails:
        print("FAIL", f)
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
