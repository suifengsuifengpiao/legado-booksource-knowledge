# -*- coding: utf-8 -*-
"""
jayway JsonPath 兼容层 —— 源码同构自 legado_app_3.25.apk (3.25) 反编译产物。

真机引擎链（已逐类反编译取证）:
  AnalyzeByJSonPath.java            Legado 三入口包装: getString/getStringList/getList
  com.jayway.jsonpath.internal.path.PathCompiler          路径文法（递归下降）
  com.jayway.jsonpath.internal.filter.FilterCompiler      谓词语法（|| > && > ! > 关系）
  com.jayway.jsonpath.internal.filter.EvaluatorFactory     求值器注册表
  com.jayway.jsonpath.internal.filter.ValueNodes$*         值节点与类型转换
  com.jayway.jsonpath.internal.function.PathFunctionFactory 函数表
  com.jayway.jsonpath.internal.path.*Token                 token 求值
  com.jayway.jsonpath.internal.DefaultsImpl                 默认配置: JsonSmart + options=空 EnumSet

关键默认语义（DefaultsImpl.options() = EnumSet.noneOf）:
  - 无 ALWAYS_RETURN_LIST   : definite 路径返回单值, indefinite 返回 List
                              (EvaluationContextImpl.getValue: definite 无结果抛 PathNotFoundException)
  - 无 DEFAULT_PATH_LEAF_TO_NULL: definite 叶子缺失同样抛异常（由 Legado catch 兜底）
  - 无 SUPPRESS_EXCEPTIONS  : 一切异常上抛（Legado 层 getList/getString try/catch 吞掉）

definite 判定（isTokenDefinite 汇总, PathToken.isPathDefinite 链式 AND）:
  Root=true; Property(单属性/多属性merge)=true; ArrayIndex(单索引)=true;
  Wildcard=false; Slice=false; Scan(..)=false; Predicate=false; Function=true(尾函数不改变 definite)
"""

import json
import re
from decimal import Decimal, InvalidOperation


class InvalidPath(Exception):
    """对应 com.jayway.jsonpath.InvalidPathException"""


class PathNotFound(Exception):
    """对应 com.jayway.jsonpath.PathNotFoundException"""


class _JavaRuntimeErr(Exception):
    """Java 侧非 InvalidPathException 的运行时异常（NumberFormatException /
    PatternSyntaxException / IllegalArgumentException）。
    FilterCompiler.compile 的 catch(Exception) 会把它包装成 InvalidPathException;
    readExpression 的 catch(InvalidPathException) 不会捕获它 —— 故不触发 EXISTS 回退。"""


class JsonPathErr(Exception):
    """对应 com.jayway.jsonpath.JsonPathException（聚合/序列函数的运行时异常）"""


class _KeySet(object):
    """Java Map.keySet()（JsonSmartJsonProvider.getPropertyKeys → Set）
    序列化: read → String.valueOf → '[a, b]'; getString → read.toString();
    getList → cast ArrayList 失败 → []"""

    def __init__(self, d):
        self.keys = list(d.keys())

    def __str__(self):
        return "[" + ", ".join(str(k) for k in self.keys) + "]"


# ---------------------------------------------------------------------------
# 值节点（ValueNodes 同构）
# ---------------------------------------------------------------------------
UNDEFINED = object()   # ValueNodes.UNDEFINED


class _Node(object):
    """ValueNode 基类的类型标记与转换骨架"""

    def is_number_node(self):
        return False

    def is_string_node(self):
        return False

    def is_boolean_node(self):
        return False

    def is_null_node(self):
        return False

    def is_pattern_node(self):
        return False

    def is_json_node(self):
        return False

    def is_value_list_node(self):
        return False

    def is_undefined_node(self):
        return False

    def as_number_node(self):
        return NAN

    def as_string_node(self):
        return self

    def as_boolean_node(self):
        # ValueNode.asBooleanNode 默认: throw InvalidPathException("Expected boolean node")
        raise InvalidPath("Expected boolean node")

    def as_predicate_node(self):
        # ValueNode.asPredicateNode 默认: throw
        raise InvalidPath("Expected predicate node")

    def as_class_node(self):
        # ValueNode.asClassNode 默认: throw
        raise InvalidPath("Expected class node")

    def as_value_list_node(self, root):
        # 标量 → 单元素列表（ValueListNode 包装）
        if self.is_value_list_node():
            return self
        return ValueListNode([self])

    def equals(self, other):
        return self is other


class ClassNode(_Node):
    """TYPE 右值占位（解析层本不可达, 仅为求值器同构保留）"""

    def __init__(self, clazz):
        self.clazz = clazz

    def is_class_node(self):
        return True

    def as_class_node(self):
        return self

    def equals(self, other):
        return isinstance(other, ClassNode) and self.clazz == other.clazz


class NumberNode(_Node):
    def __init__(self, num):
        # jayway: BigDecimal；NAN 用 number=None 表示（ValueNodes$NumberNode.NAN）
        if num is None:
            self.number = None
        else:
            self.number = num if isinstance(num, Decimal) else Decimal(str(num))

    def is_number_node(self):
        return True

    def as_number_node(self):
        # ValueNodes$NumberNode.asNumberNode: return this
        return self

    def as_string_node(self):
        # ValueNodes$NumberNode.asStringNode: new StringNode(number.toString())
        if self.number is None:
            return StringNode("NaN")
        return StringNode(_bigdecimal_str(self.number))

    def equals(self, other):
        # NumberNode.equals: obj 是 Number/String → asNumberNode != NAN 且 compareTo == 0
        if isinstance(other, (NumberNode, StringNode)):
            n = other.as_number_node()
            if n is not NAN and self.number is not None and n.number is not None \
                    and self.number == n.number:
                return True
        return False


class StringNode(_Node):
    def __init__(self, s, strip_quotes=False):
        # ValueNodes$StringNode(CharSequence, z): z=true 时剥首尾配对引号后 unescape;
        # z=false（PathNode.evaluate 的 createStringNode(v,false)）原样
        if strip_quotes and len(s) > 1 and s[0] == s[-1] and s[0] in "'\"":
            s = s[1:-1]
        self.string = _unescape(s)

    def is_string_node(self):
        return True

    def as_number_node(self):
        # asNumberNode: BigDecimal(string) 失败 → NAN
        try:
            return NumberNode(Decimal(self.string))
        except (InvalidOperation, ValueError, ArithmeticError):
            return NAN

    def equals(self, other):
        # StringNode.equals: obj 是 String/Number → 双方转 StringNode 后字符串比较
        if isinstance(other, (StringNode, NumberNode)):
            return self.string == other.as_string_node().string
        return False


class BooleanNode(_Node):
    def __init__(self, v):
        self.value = v

    def is_boolean_node(self):
        return True

    def as_boolean_node(self):
        # ValueNodes$BooleanNode.asBooleanNode: return this
        return self

    def get_boolean(self):
        return self.value

    def equals(self, other):
        if isinstance(other, BooleanNode):
            return self.value == other.value
        return False


class NullNode(_Node):
    def is_null_node(self):
        return True


class PatternNode(_Node):
    """`/re/flags`"""

    def __init__(self, raw):
        # raw 形如 `/abc/i` —— FilterCompiler.readPattern 带引号斜杠整体取出
        body = raw[1:]
        m = re.match(r"^(.*)/([a-zA-Z]*)$", body, re.S)
        if not m:
            raise InvalidPath("Pattern not closed. Expected /")
        pat, flags_s = m.group(1), m.group(2)
        # ValueNodes$PatternNode: PatternFlag.parseFlags —— CASE_INSENSITIVE/UNICODE_CASE 等
        re_flags = 0
        if "i" in flags_s:
            re_flags |= re.IGNORECASE
        if "d" in flags_s:
            re_flags |= re.UNICODE
        if "x" in flags_s:
            re_flags |= re.VERBOSE
        if "s" in flags_s:
            re_flags |= re.DOTALL
        if "m" in flags_s:
            re_flags |= re.MULTILINE
        try:
            self.pattern = re.compile(pat, re_flags)
        except re.error as e:
            # Java: Pattern.compile → PatternSyntaxException（不被 readExpression 捕获）
            raise _JavaRuntimeErr("Bad pattern: %s" % e)

    def is_pattern_node(self):
        return True


class JsonNode(_Node):
    """JSON 字面量（`{...}` / `[...]`）—— Java JsonNode: parse(ctx) 惰性"""

    def __init__(self, text=None, parsed=None):
        if parsed is not None:
            self.value = parsed
            self.parsed = True
        else:
            self.text = text
            self.value = None
            self.parsed = False

    def _parse(self):
        if not self.parsed:
            try:
                self.value = json.loads(self.text)
            except Exception as e:
                # Java JsonNode.parse(ctx) → IllegalArgumentException（求值期, 非解析期）
                raise _JavaRuntimeErr("Failed to parse json literal: %s" % e)
            self.parsed = True
        return self.value

    def is_json_node(self):
        return True

    def as_value_list_node(self, root):
        # JsonNode.asValueListNode(ctx): 非数组 → UNDEFINED; 数组 → ValueListNode(逐项 toValueNode)
        v = self._parse()
        if not isinstance(v, list):
            return UNDEFINED
        return ValueListNode([_wrap(x) for x in v])


class ValueListNode(_Node):
    def __init__(self, nodes):
        self.nodes = nodes

    def is_value_list_node(self):
        return True

    def __iter__(self):
        return iter(self.nodes)

    def contains(self, node):
        # ValueListNode.contains → ArrayList.contains(o): o.equals(element)（参数 equals 元素）
        return any(node.equals(n) for n in self.nodes)


NAN = NumberNode(None)
TRUE = BooleanNode(True)
FALSE = BooleanNode(False)
NULL_NODE = NullNode()
UNDEFINED_NODE = _Node()


def _bigdecimal_str(d):
    # Java BigDecimal.toString 对整数不含小数点
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return str(d)


def _wrap(v):
    """PathNode.evaluate 的 unwrap 类型映射: Number→NumberNode / String→StringNode /
    bool→Boolean / null→NULL / list/map→JsonNode"""
    if v is None:
        return NULL_NODE
    if isinstance(v, bool):
        return BooleanNode(v)
    if isinstance(v, (int, float, Decimal)):
        return NumberNode(v)
    if isinstance(v, str):
        return StringNode(v)
    return JsonNode(parsed=v)


# ---------------------------------------------------------------------------
# 路径编译（PathCompiler.compile 同构）
# ---------------------------------------------------------------------------
class _Tok(object):
    is_definite = True

    def evaluate(self, obj, root, emit):
        raise NotImplementedError


class _RootTok(_Tok):
    def __init__(self, frag):
        self.frag = frag
        self.next = None

    def evaluate(self, obj, root, emit):
        if self.next is not None:
            self.next.evaluate(obj, root, emit)


class _PropertyTok(_Tok):
    """属性 token: `.name` / `['name']` / `['a','b']`"""

    def __init__(self, props):
        self.props = props
        self.next = None
        # PathToken.isUpstreamDefinite: 编译期填入（此前所有 token 均 definite）
        self.upstream_definite = True

    def evaluate(self, obj, root, emit):
        if not isinstance(obj, dict):
            # PropertyPathToken.evaluate: 非 map; 上游 definite 且默认 options 空 → 抛
            if self.upstream_definite:
                frag = "[" + ",".join("'" + p + "'" for p in self.props) + "]"
                raise PathNotFound(
                    "Expected to find an object with property %s but found '%s'. "
                    "This is not a json object according to the JsonProvider."
                    % (frag, obj))
            return
        if len(self.props) == 1:
            p = self.props[0]
            if p in obj:
                v = obj[p]
                if self.next is None:
                    emit(v)
                else:
                    self.next.evaluate(v, root, emit)
            # 属性缺失: 默认 options 为空 EnumSet → 无结果（definite 场景由 read 抛 PathNotFound）
        elif self.next is None:
            # multiPropertyMergeCase (isLeaf && size>1): 合并 map, 仅含存在的属性
            merged = {}
            for p in self.props:
                if p in obj:
                    merged[p] = obj[p]
            emit(merged)
        else:
            # multiPropertyIterationCase (!isLeaf && size>1): 逐属性向下游展开
            for p in self.props:
                if p in obj:
                    self.next.evaluate(obj[p], root, emit)


class _ScanTok(_Tok):
    """`..` 深度扫描"""

    is_definite = False

    def __init__(self):
        self.next = None

    def _walk(self, node, root, predicate_next):
        """ScanPathToken.walkObject/walkArray 同构: **先匹配当前节点本身**(含根),
        再递归子节点（map 按 value 序 / array 按元素序）"""
        # createScanPredicate: 后随 property → 该节点是 map 且含属性键;
        # 后随 wildcard → 恒真; 后随 filter → 过滤; 其它 → FALSE_PREDICATE
        if predicate_next(node):
            self.next.evaluate(node, root, self._emit_leaf)
        if isinstance(node, dict):
            children = list(node.values())
        elif isinstance(node, list):
            children = list(node)
        else:
            return
        for child in children:
            self._walk(child, root, predicate_next)

    def _emit_leaf(self, v):
        self._sink(v)

    # jayway walkObject/walkArray 对匹配节点应用 next.evaluate
    def evaluate(self, obj, root, emit):
        self._sink = emit
        nxt = self.next

        def predicate(child):
            if nxt is None:
                return False
            if isinstance(nxt, _PropertyTok):
                return isinstance(child, dict) and any(p in child for p in nxt.props)
            if isinstance(nxt, _WildcardTok):
                return True
            if isinstance(nxt, _PredicateTok):
                return nxt.accept_one(child, root)
            return False

        self._walk(obj, root, predicate)


class _WildcardTok(_Tok):
    is_definite = False

    def __init__(self):
        self.next = None

    def evaluate(self, obj, root, emit):
        vals = list(obj.values()) if isinstance(obj, dict) else (
            list(obj) if isinstance(obj, list) else [])
        for v in vals:
            if self.next is None:
                emit(v)
            else:
                self.next.evaluate(v, root, emit)


class _ArrayIndexTok(_Tok):
    """`[0]` / `[-1]` / `[0,1]`"""

    def __init__(self, indices):
        self.indices = indices
        self.next = None
        # isTokenDefinite = isSingleIndexOperation
        self.is_definite = len(indices) == 1

    def evaluate(self, obj, root, emit):
        if not isinstance(obj, list):
            return
        n = len(obj)
        for i in self.indices:
            idx = i + n if i < 0 else i
            if 0 <= idx < n:
                v = obj[idx]
                if self.next is None:
                    emit(v)
                else:
                    self.next.evaluate(v, root, emit)


class _ArraySliceTok(_Tok):
    """`[1:5]` / `[:5]` / `[1:]`（ArraySliceOperation: from/to, 无 step）"""

    is_definite = False

    def __init__(self, frm, to):
        self.frm = frm
        self.to = to
        self.next = None

    def evaluate(self, obj, root, emit):
        if not isinstance(obj, list):
            return
        n = len(obj)
        # JsonSmartJsonProvider.arraySlice 主流语义: 负索引回绕后夹取
        start = 0 if self.frm is None else max(self.frm + n, 0) if self.frm < 0 else min(self.frm, n)
        end = n if self.to is None else max(self.to + n, 0) if self.to < 0 else min(self.to, n)
        for i in range(start, max(start, end)):
            v = obj[i]
            if self.next is None:
                emit(v)
            else:
                self.next.evaluate(v, root, emit)


class _PredicateTok(_Tok):
    """`[?(...)]` 过滤"""

    is_definite = False

    def __init__(self, predicate):
        self.predicate = predicate
        self.next = None

    def accept_one(self, obj, root):
        # Predicate.apply(PredicateContextImpl(item, obj, root, configuration))
        try:
            return self.predicate.evaluate(obj, root)
        except InvalidPath:
            raise
        except Exception:
            return False

    def evaluate(self, obj, root, emit):
        # PredicatePathToken.evaluate: array 逐项, 单项 accept
        if isinstance(obj, list):
            for item in obj:
                if self.accept_one(item, root):
                    if self.next is None:
                        emit(item)
                    else:
                        self.next.evaluate(item, root, emit)
        else:
            if self.accept_one(obj, root):
                if self.next is None:
                    emit(obj)
                else:
                    self.next.evaluate(obj, root, emit)


class _FunctionTok(_Tok):
    """`.length()` 等尾函数"""

    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.next = None

    def evaluate(self, obj, root, emit):
        # FunctionPathToken.evaluate: model = 上游单模型（链式逐值驱动;
        # 通配/扫描上游的多结果由调用方逐次 invoke 到本 token）
        res = _eval_function(self.name, self.params, obj, root)
        if self.next is None:
            emit(res)
        else:
            self.next.evaluate(res, root, emit)


# ---------------------------------------------------------------------------
# 路径编译器
# ---------------------------------------------------------------------------
class JsonPath(object):
    def __init__(self, rule):
        self.rule = rule
        self.tokens, self.definite = _compile_path(rule)

    def read(self, data):
        """jayway ReadContext.read 语义"""
        results = []

        def emit(v):
            results.append(v)

        for t in self.tokens:
            t.evaluate(data, data, emit)
            break  # RootTok 只有一个（_compile_path 保证链头是 root）
        # 上面只对 root 求值；root.next 链自带后续
        if self.definite:
            # getValue: definite 无结果 → PathNotFoundException; 取最后一个
            if not results:
                raise PathNotFound("No results for path: %s" % self.rule)
            return results[-1]
        # indefinite → valueResult 整体（list）
        return results


_WS = " \t\n\r"


def _compile_path(rule):
    """PathCompiler.compile 同构。返回 (tokens, definite)"""
    s = rule.strip() if rule else ""
    if not s:
        raise InvalidPath("empty path")
    if s[0] not in "$@":
        # compile(): 不以 $/@ 开头 → 自动前缀 "$."
        s = "$." + s
    if s.endswith("."):
        raise InvalidPath("Path must not end with a '.' or '..'")
    pos = [0]

    def err(msg):
        raise InvalidPath("%s (path: %s)" % (msg, rule))

    # root
    root = _RootTok(s[0])
    pos[0] = 1
    if pos[0] >= len(s):
        return [root], True
    if s[pos[0]] not in ".[":
        err("Illegal character at position %d expected '.' or '['" % pos[0])
    cur = root
    tokens_all = [root]

    def append(tok):
        nonlocal cur
        cur.next = tok
        cur = tok
        tokens_all.append(tok)

    while pos[0] < len(s):
        c = s[pos[0]]
        if c == "*":
            # readWildCardToken（点后或独立位置）
            append(_WildcardTok())
            pos[0] += 1
            continue
        if c == ".":
            if pos[0] + 1 < len(s) and s[pos[0] + 1] == ".":
                # readDotToken: ".." → scan
                append(_ScanTok())
                pos[0] += 2
            else:
                pos[0] += 1
            if pos[0] >= len(s):
                err("Path must not end with a '.'")
            if s[pos[0]] == ".":
                err("Character '.' is not valid")
            continue
        if c == "[":
            tok, pos[0] = _parse_bracket(s, pos[0], err)
            append(tok)
            continue
        if c == " ":
            raise InvalidPath("Use bracket notion ['my prop'] if property contains blank")
        # readPropertyOrFunctionToken
        start = pos[0]
        j = start
        func = False
        while j < len(s):
            ch = s[j]
            if ch == " ":
                raise InvalidPath("Use bracket notion ['my prop'] if property contains blank")
            if ch in ".[":
                break
            if ch == "(":
                func = True
                break
            j += 1
        end = j if not func else j
        if func:
            # 找配对右括号
            k = j + 1
            depth = 1
            while k < len(s):
                if s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                elif s[k] == "(":
                    depth += 1
                k += 1
            if depth != 0:
                err("Arguments to function are not closed properly")
            name = s[start:j]
            # PathCompiler.readPropertyOrFunctionToken 的位置推进（jayway 2.9.0 怪癖）:
            # - 有参: setPosition(endPosition+1) → parseFunctionParameters 吃到 ')' 后 → k+1
            # - 无参: setPosition(readPosition+1) → position 落在 ')' 上;
            #   若 ')' 非末字符, 它会被 readNextToken 读成属性 ')'（keys().length() 实证）
            # - '(' 后无字符: setPosition(readPosition) 即 '(' 位
            # 之后 currentIsTail(position >= endPosition=len-1) 决定是否继续
            if j + 1 < len(s):
                if s[j + 1] != ")":
                    params = _parse_function_params(s[j + 1:k])
                    pos[0] = k + 1
                else:
                    params = []
                    pos[0] = j + 1
            else:
                params = []
                pos[0] = j
            append(_FunctionTok(name, params))
            if pos[0] >= len(s) - 1:
                break  # currentIsTail
        else:
            append(_PropertyTok([s[start:end]]))
            pos[0] = end
    # PropertyPathToken.isTokenDefinite: singlePropertyCase(size==1) ||
    # multiPropertyMergeCase(leaf && size>1); 多属性非叶子（iteration）→ indefinite
    for t in tokens_all:
        if isinstance(t, _PropertyTok):
            t.is_definite = len(t.props) == 1 or (t.next is None and len(t.props) > 1)
    # PathToken.isUpstreamDefinite: 编译期推导（此前全链 definite, 不含自身）
    up = True
    for t in tokens_all:
        if hasattr(t, "upstream_definite"):
            t.upstream_definite = up
        up = up and t.is_definite
    definite = all(t.is_definite for t in tokens_all)
    return tokens_all, definite


def _parse_bracket(s, i, err):
    """readNextToken 的 '[' 分支: bracket-property / array / wildcard / filter 四合一"""
    j = i + 1
    while j < len(s) and s[j] in _WS:
        j += 1
    if j >= len(s):
        err("unclosed bracket")
    c = s[j]
    # readBracketPropertyToken: ['name'] / ['a','b']（转义 + 逗号分隔 + 空属性检测）
    if c in "'\"":
        quote = c
        props = []
        k = j  # Java readBracketPropertyToken: position 从开引号位开始扫描
        in_str = False
        item_start = k
        empty_pending = False
        while k < len(s):
            ch = s[k]
            if ch == "\\":
                k += 2
                continue
            if ch == quote:
                if in_str:
                    nxt = s[k + 1] if k + 1 < len(s) else ""
                    if nxt not in (",", "]"):
                        kk = k + 1
                        while kk < len(s) and s[kk] in _WS:
                            kk += 1
                        if kk >= len(s) or s[kk] not in ",]":
                            err("Property must be separated by comma or terminated close square bracket at index %d" % k)
                    props.append(_unescape(s[item_start:k]))
                    in_str = False
                    empty_pending = False
                else:
                    item_start = k + 1
                    in_str = True
                    empty_pending = False
            elif ch == "," and not in_str:
                if empty_pending or not props:
                    err("Found empty property at index %d" % k)
                empty_pending = True
            elif ch == "]" and not in_str:
                if empty_pending or not props:
                    err("Found empty property at index %d" % k)
                break
            k += 1
        if in_str:
            err("Property has not been closed - missing closing %s" % quote)
        # 定位收尾 ]
        close = k
        while close < len(s) and s[close] != "]":
            close += 1
        if close >= len(s):
            err("Property has not been closed - missing ]")
        if not props:
            err("Found empty property")
        return _PropertyTok(props), close + 1
    # readArrayToken / readWildCardToken / readFilterToken
    close = s.find("]", j)
    if close == -1:
        err("unclosed bracket")
    inner = s[k + 1:close].strip() if False else s[j:close].strip()
    # readWildCardToken: [*]
    if inner == "*":
        return _WildcardTok(), close + 1
    # readFilterToken: [?...
    if inner.startswith("?"):
        # 找闭合括号 ]
        op = s.find("(", j)
        if op == -1:
            err("Expected filter '('")
        end = _index_of_closing_bracket(s, op, True)
        if end == -1 or not _next_sig_is(s, end, "]"):
            err("bad filter")
        endq = s.find("]", end)
        if endq == -1:
            err("bad filter")
        pred = FilterCompiler.compile(s[i:endq + 1])
        return _PredicateTok(pred), endq + 1
    # readArrayToken: 数字/逗号/冒号/负号
    if not inner or all(ch.isdigit() or ch in ",-: " for ch in inner):
        if ":" in inner:
            parts = inner.split(":")
            def _rd(x):
                x = x.strip()
                return int(x) if x else None
            return _ArraySliceTok(_rd(parts[0]), _rd(parts[1]) if len(parts) > 1 else None), close + 1
        idxs = [int(x.strip()) for x in inner.split(",") if x.strip()]
        return _ArrayIndexTok(idxs), close + 1
    err("Could not parse token starting at %d. Expected ?, ', 0-9, *" % i)


def _unescape(s):
    # Utils.unescape: \' \" \\ \/ \b \f \n \r \t \uXXXX 等
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            if c in "'\"\\/":
                out.append(c)
                i += 2
                continue
            if c == "u" and i + 5 < len(s) + 1:
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            mp = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
            if c in mp:
                out.append(mp[c])
                i += 2
                continue
            out.append(c)
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _next_sig_is(s, i, ch):
    j = i
    while j < len(s) and s[j] in _WS:
        j += 1
    return j < len(s) and s[j] == ch


def _index_of_closing_bracket(s, open_pos, allow_nested):
    """indexOfClosingBracket 同构: 从 open_pos 的 '(' 起找与外层 '[' 配对的 ']'"""
    depth = 0
    i = open_pos
    in_str = None
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "]" and depth == 0:
            return i
        i += 1
    return -1


def _parse_function_params(s):
    """parseFunctionParameters 简化: 支持 JSON / 路径参数"""
    params = []
    depth = 0
    cur = []
    in_str = None
    for ch in s:
        if in_str:
            cur.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in "'\"":
            in_str = ch
            cur.append(ch)
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            params.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        params.append(tail)
    return params


# ---------------------------------------------------------------------------
# 谓词编译器（FilterCompiler.compile 同构）
# ---------------------------------------------------------------------------
class _Pred(object):
    def evaluate(self, item, root):
        raise NotImplementedError


class _Not(_Pred):
    def __init__(self, p):
        self.p = p

    def evaluate(self, item, root):
        return not self.p.evaluate(item, root)


class _And(_Pred):
    def __init__(self, ps):
        self.ps = ps

    def evaluate(self, item, root):
        return all(p.evaluate(item, root) for p in self.ps)


class _Or(_Pred):
    def __init__(self, ps):
        self.ps = ps

    def evaluate(self, item, root):
        return any(p.evaluate(item, root) for p in self.ps)


class _Rel(_Pred):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

    def evaluate(self, item, root):
        ln = _eval_value_node(self.left, item, root)
        rn = _eval_value_node(self.right, item, root)
        op = self.op.upper()
        if op == "EXISTS":
            # ExistsEvaluator: 两侧都须 BooleanNode, 布尔值相等
            if not ln.is_boolean_node() or not rn.is_boolean_node():
                raise InvalidPath("Failed to evaluate exists expression")
            return ln.get_boolean() == rn.get_boolean()
        if op in ("===", "TSNE"):
            # TypeSafeEquals/NotEquals: Number vs Number / String vs String 才比较
            eq = _typesafe_eq(ln, rn)
            return eq if op == "===" else not eq
        if op == "==":
            if ln.is_json_node() and rn.is_json_node():
                # JsonNode.equals(JsonNode, ctx): json.equals(other.parse(ctx))
                # 左侧字面量未解析（json 是原始串）, 路径求值来的 JsonNode 已解析
                lv = ln._parse() if ln.parsed else ln.text
                return lv == rn._parse()
            return ln.equals(rn)
        if op == "!=":
            return not (ln.equals(rn))
        if op in ("<", "<=", ">", ">="):
            if ln.is_number_node() and rn.is_number_node():
                c = _cmp(ln.number, rn.number)
            elif ln.is_string_node() and rn.is_string_node():
                c = _cmp(ln.string, rn.string)
            else:
                return False
            if op == "<":
                return c < 0
            if op == "<=":
                return c <= 0
            if op == ">":
                return c > 0
            return c >= 0
        if op == "=~":
            # RegexpEvaluator: 恰一侧 PatternNode, pattern.matches(全匹配)
            if ln.is_pattern_node() == rn.is_pattern_node():
                return False
            if ln.is_pattern_node():
                return ln.pattern.fullmatch(_regex_input(rn)) is not None
            if rn.is_pattern_node():
                return rn.pattern.fullmatch(_regex_input(ln)) is not None
            return False
        if op in ("IN", "NIN", "CONTAINS", "ALL", "ANYOF", "NONEOF", "SUBSETOF", "SIZE", "EMPTY", "MATCHES", "TYPE"):
            return _eval_keyword(op, ln, rn, item, root)
        raise InvalidPath("Filter operator %s is not supported" % self.op)


def _cmp(a, b):
    return -1 if a < b else (1 if a > b else 0)


def _regex_input(node):
    # RegexpEvaluator.getInput: String/Number → asStringNode; Boolean → toString; 其它 → ""
    if node.is_string_node() or node.is_number_node():
        return node.as_string_node().string
    if node.is_boolean_node():
        return str(node.value)
    return ""


def _typesafe_eq(a, b):
    if a.is_number_node() and b.is_number_node():
        return a.number == b.number
    if a.is_string_node() and b.is_string_node():
        return a.string == b.string
    return a is b


def _as_vln_strict(node):
    """ValueNode.asValueListNode() 无 ctx 版（ValueNodes$ValueNode:79-81）:
    仅 ValueListNode 返回 this, 其余（含 JsonNode/Scalar）抛 InvalidPathException"""
    if node.is_value_list_node():
        return node
    raise InvalidPath("Expected value list node")


def _json_to_vln(node, root):
    """JsonNode.asValueListNode(ctx): 数组 → ValueListNode; 非数组 → UNDEFINED"""
    v = node._parse()
    if isinstance(v, list):
        return ValueListNode([_wrap(x) for x in v])
    return UNDEFINED


def _eval_keyword(op, a, b, item, root):
    # ---- EvaluatorFactory 2.9.0 同构 ----
    if op == "IN":
        # InEvaluator
        if b.is_json_node():
            vn = _json_to_vln(b, root)
            if vn is UNDEFINED:
                return False
            vln = vn
        else:
            vln = _as_vln_strict(b)
        return vln.contains(a)  # ArrayList.contains: a.equals(element)
    if op == "NIN":
        return not _eval_keyword("IN", a, b, item, root)
    if op == "CONTAINS":
        # ContainsEvaluator
        if a.is_string_node() and b.is_string_node():
            return b.string in a.string
        if a.is_json_node():
            vn = _json_to_vln(a, root)
            if vn is UNDEFINED:
                return False
            return vn.contains(b)  # b.equals(element)
        return False
    if op == "SIZE":
        # SizeEvaluator
        if not b.is_number_node():
            return False
        expected = b.number
        if a.is_string_node():
            return len(a.string) == expected
        if a.is_json_node():
            v = a._parse()
            n = len(v) if isinstance(v, list) else -1
            return n == expected
        return False
    if op == "EMPTY":
        # EmptyEvaluator: right 须 BooleanNode（Java asBooleanNode 默认抛）
        bv = b.as_boolean_node().get_boolean()
        if a.is_string_node():
            return (len(a.string) == 0) == bv
        if a.is_json_node():
            v = a._parse()
            if isinstance(v, (list, dict)):
                return (len(v) == 0) == bv
            if isinstance(v, str):
                return (len(v) == 0) == bv
            return True == bv
        return False
    if op == "ALL":
        # AllEvaluator: requiredValues = right.asValueListNode() 无 ctx 版
        required = _as_vln_strict(b)
        if a.is_json_node():
            vn = _json_to_vln(a, root)
            if vn is UNDEFINED:
                return True  # left 非数组 → true（Java 原样）
            return all(vn.contains(r) for r in required)
        return False
    if op in ("ANYOF", "NONEOF", "SUBSETOF"):
        # 任一侧 JsonNode 非数组 → false
        if b.is_json_node():
            rb = _json_to_vln(b, root)
            if rb is UNDEFINED:
                return False
        else:
            rb = _as_vln_strict(b)
        if a.is_json_node():
            la = _json_to_vln(a, root)
            if la is UNDEFINED:
                return False
        else:
            la = _as_vln_strict(a)
        if op == "ANYOF":
            return any(x.equals(y) for x in la for y in rb)
        if op == "NONEOF":
            return not any(x.equals(y) for x in la for y in rb)
        return all(any(x.equals(y) for y in rb) for x in la)  # SUBSETOF
    if op == "MATCHES":
        # PredicateMatchEvaluator: right.asPredicateNode().getPredicate().apply(ctx)
        return b.as_predicate_node().get_predicate().evaluate(item, root)
    if op == "TYPE":
        # TypeEvaluator: right.asClassNode().getClazz() == left.type(ctx)
        return b.as_class_node().clazz == _node_type(a)
    return False


def _node_type(node):
    # ValueNode.type(ctx)
    if node.is_json_node():
        v = node._parse()
        if isinstance(v, list):
            return "list"
        if isinstance(v, dict):
            return "map"
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, str):
            return "string"
        return "void"
    if node.is_number_node():
        return "number"
    if node.is_string_node():
        return "string"
    if node.is_boolean_node():
        return "boolean"
    return "void"


class _ValuePath(object):
    """`@`/`$` 路径（PathNode 同构）"""

    def __init__(self, path, should_exist=True, exists_check=False):
        self.path = path
        # FilterCompiler.readPath: 前一有效字符是 '!' → shouldExist=false（取反存在检查）
        self.should_exist = should_exist
        # PathNode.asExistsCheck: readExpression 回退时置位
        self.exists_check = exists_check

    def evaluate(self, item, root):
        # PathNode.evaluate: path.evaluate(item or root).getValue()
        data = root if self.path[0] == "$" else item
        if self.exists_check:
            # existsCheck 分支: REQUIRE_PROPERTIES 配置; definite 无结果 → FALSE
            try:
                JsonPath(self.path).read(data)
                return TRUE
            except PathNotFound:
                return FALSE
            except InvalidPath:
                raise
            except Exception:
                return FALSE
        p = JsonPath(self.path)
        try:
            v = p.read(data)
        except PathNotFound:
            return UNDEFINED_NODE
        except InvalidPath:
            raise
        except Exception:
            return UNDEFINED_NODE
        return _wrap(v)


class _ValueLit(object):
    def __init__(self, node):
        self.node = node

    def evaluate(self, item, root):
        return self.node


class _ValueFilterRef(object):
    """`?` 占位引用: MATCHES 场景少见, 预留"""

    def __init__(self, f):
        self.f = f

    def evaluate(self, item, root):
        return _ValueList([_PredValue(self.f)])


class _PredValue(object):
    def __init__(self, f):
        self.f = f

    def evaluate(self, item, root):
        return self.f.evaluate(item, root)


class _ValueList(object):
    def __init__(self, items):
        self.items = items

    def is_json_node(self):
        return False

    def is_value_list_node(self):
        return True

    def equals(self, other):
        return False


class _PredAsValue(object):
    """把谓词包装成可 evaluate 的 value（供 MATCHES / IN 的列表参数）"""

    def __init__(self, pred):
        self.pred = pred

    def evaluate(self, item, root):
        return BooleanNode(self.pred.evaluate(item, root))


def _eval_value_node(vn, item, root):
    if vn is None:
        return UNDEFINED_NODE
    if hasattr(vn, "evaluate"):
        return vn.evaluate(item, root)
    if isinstance(vn, _Node):
        return vn
    return UNDEFINED_NODE


class _FilterParser(object):
    """FilterCompiler 同构: 递归下降 || > && > ! > 关系表达式"""

    def __init__(self, s):
        self.s = s
        self.i = 0

    # ---- 基础 ----
    def _ws(self):
        while self.i < len(self.s) and self.s[self.i] in _WS:
            self.i += 1

    def _peek(self):
        self._ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def _eat(self, ch):
        self._ws()
        if self.i < len(self.s) and self.s[self.i] == ch:
            self.i += 1
            return True
        return False

    # ---- 文法 ----
    def compile(self):
        node = self.read_or()
        self._ws()
        if self.i < len(self.s):
            raise InvalidPath("Expected end of filter expression instead of: %s"
                              % self.s[self.i:])
        return node

    def read_or(self):
        arr = [self.read_and()]
        while True:
            mark = self.i
            if self._has_seq("||"):
                arr.append(self.read_and())
            else:
                self.i = mark
                break
        return arr[0] if len(arr) == 1 else _Or(arr)

    def read_and(self):
        arr = [self.read_and_operand()]
        while True:
            mark = self.i
            if self._has_seq("&&"):
                arr.append(self.read_and_operand())
            else:
                self.i = mark
                break
        return arr[0] if len(arr) == 1 else _And(arr)

    def _has_seq(self, seq):
        j = self.i
        while j < len(self.s) and self.s[j] in _WS:
            j += 1
        if self.s.startswith(seq, j):
            self.i = j + len(seq)
            return True
        return False

    def read_and_operand(self):
        mark = self.i
        if self._peek() == "!":
            self.i += 1
            c2 = self._peek()
            if c2 not in "$@":
                return _Not(self.read_and_operand())
            self.i = mark
        if self._peek() == "(":
            self.i += 1
            node = self.read_or()
            if not self._eat(")"):
                raise InvalidPath("Expected )")
            return node
        return self.read_expression()

    def read_expression(self):
        left = self.read_value_node()
        savepoint = self.i  # jar 2.9.0: savepoint 在 left 读取之后
        try:
            op = self.read_relational_operator()
            right = self.read_value_node()
            return _Rel(left, op, right)
        except InvalidPath:
            # readExpression 回退: position 恢复到 left 后（如 ')' 前）, path → EXISTS
            self.i = savepoint
            if isinstance(left, _ValuePath):
                # left.asPathNode().asExistsCheck(shouldExists); right = shouldExists ? TRUE : FALSE
                left = _ValuePath(left.path, left.should_exist, exists_check=True)
                rn = TRUE if left.should_exist else FALSE
                return _Rel(left, "EXISTS", rn)
            raise

    def read_value_node(self):
        c = self._peek()
        if c == "!":
            self.i += 1
            c2 = self._peek()
            if c2 == "$":
                return self.read_path()
            if c2 == "@":
                return self.read_path()
            raise InvalidPath("Unexpected character: !")
        if c == "$" or c == "@":
            # 注: 不能用 c in "$@" —— Python 空串是任意串子串（越界陷阱）
            return self.read_path()
        return self.read_literal()

    def read_path(self):
        # readPath: 一路吃到关系符/空格/')'/边界; '[' 需配对; 前一有效字符 '!' → 取反
        self._ws()
        prev = ""
        j = self.i - 1
        while j >= 0 and self.s[j] in _WS:
            j -= 1
        if j >= 0:
            prev = self.s[j]
        should = prev != "!"
        start = self.i
        self.i += 1
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch == "[":
                close = self.s.find("]", self.i)
                if close == -1:
                    raise InvalidPath("Square brackets does not match in filter")
                self.i = close + 1
                continue
            if ch == ")":
                # closing function bracket 简化处理
                nxt = self.i + 1
                while nxt < len(self.s) and self.s[nxt] in _WS:
                    nxt += 1
                if self.s[self.i - 1:self.i] == "(" and prev_is_func_call(self.s, start, self.i):
                    self.i += 1
                    continue
                break
            if ch in "<>=~!" or ch == " ":
                break
            self.i += 1
        return _ValuePath(self.s[start:self.i].strip(), should)

    def read_relational_operator(self):
        self._ws()
        start = self.i
        c = self.s[self.i] if self.i < len(self.s) else ""
        if c in "<>=~!":
            while self.i < len(self.s) and self.s[self.i] in "<>=~!":
                self.i += 1
        else:
            while self.i < len(self.s) and self.s[self.i] != " ":
                self.i += 1
        op = self.s[start:self.i]
        if not op:
            raise InvalidPath("Expected relational operator")
        return op

    def read_literal(self):
        self._ws()
        c = self.s[self.i] if self.i < len(self.s) else ""
        if c in "'\"":
            return _ValueLit(self._read_string(c))
        if c == "-":
            return _ValueLit(self._read_number())
        if c == "/":
            return _ValueLit(self._read_pattern())
        if c == "[":
            return _ValueLit(self._read_json("[", "]"))
        if c == "{":
            return _ValueLit(self._read_json("{", "}"))
        if c == "t":
            return self._read_bool("true", TRUE)
        if c == "f":
            return self._read_bool("false", FALSE)
        if c == "n":
            return self._read_null()
        return _ValueLit(self._read_number())

    def _read_bool(self, word, node):
        if self.s.startswith(word, self.i):
            self.i += len(word)
            return node
        raise InvalidPath("Expected boolean literal")

    def _read_null(self):
        if self.s.startswith("null", self.i):
            self.i += 4
            return NULL_NODE
        raise InvalidPath("Expected <null> value")

    def _read_string(self, q):
        start = self.i
        self.i += 1
        while self.i < len(self.s):
            if self.s[self.i] == "\\":
                self.i += 2
                continue
            if self.s[self.i] == q:
                self.i += 1
                return StringNode(self.s[start:self.i], True)
            self.i += 1
        raise InvalidPath("String literal does not have matching quotes")

    def _read_number(self):
        # CharacterIndex.isNumberCharacter: digit | '-' | '.' | 'e' | 'E'（无 '+'）
        start = self.i
        while self.i < len(self.s) and (self.s[self.i].isdigit() or self.s[self.i] in "-.eE"):
            self.i += 1
        text = self.s[start:self.i]
        try:
            return NumberNode(Decimal(text))
        except (InvalidOperation, ValueError, ArithmeticError):
            # Java: new BigDecimal(text) → NumberFormatException（不被 readExpression 捕获）
            raise _JavaRuntimeErr("Failed to parse number literal: %r" % text)

    def _read_pattern(self):
        start = self.i
        close = -1
        j = self.i + 1
        while j < len(self.s):
            if self.s[j] == "\\":
                j += 2
                continue
            if self.s[j] == "/":
                close = j
                break
            j += 1
        if close == -1:
            raise InvalidPath("Pattern not closed. Expected / in " + self.s)
        # endOfFlags: 闭合 '/' 后连续的 PatternFlag 字符（d i x m s u U）并入 flags
        end = close + 1
        while end < len(self.s) and self.s[end] in "dixmsuU":
            end += 1
        self.i = end
        return PatternNode(self.s[start:self.i])

    def _read_json(self, o, c):
        start = self.i
        depth = 0
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch in "'\"":
                self._read_string(ch)
                continue
            if ch in "[{(":
                depth += 1
            elif ch in "]})":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return JsonNode(self.s[start:self.i])
            self.i += 1
        raise InvalidPath("JSON literal not closed")


def prev_is_func_call(s, path_start, paren_pos):
    """currentCharIsClosingFunctionBracket: ')' 前是 '(' 且更前是 '.函数名'"""
    if paren_pos == 0 or s[paren_pos - 1] != "(":
        return False
    j = paren_pos - 2
    while j >= path_start and (s[j].isalnum() or s[j] == "_"):
        j -= 1
    return j >= path_start and s[j] == "."


class FilterCompiler(object):
    @staticmethod
    def compile(expr):
        """compile: 形如 `[?(@.a>1)]` / `[?(@.a)]`"""
        s = expr.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1].strip()
        else:
            raise InvalidPath("Filter must start with '[' and end with ']'. " + expr)
        if s.startswith("?"):
            s = s[1:].strip()
        else:
            raise InvalidPath("Filter must start with '[?' and end with ']'. " + expr)
        if s.startswith("(") and s.endswith(")"):
            # FilterCompiler.compile(): InvalidPathException 原样抛; 其它 Exception 包装
            try:
                return _FilterParser(s).compile()
            except InvalidPath:
                raise
            except Exception as e:
                raise InvalidPath("Failed to parse filter: %s, error: %s" % (s, e))
        raise InvalidPath("Filter must start with '[?(' and end with ')]'. " + expr)


# ---------------------------------------------------------------------------
# 函数（PathFunctionFactory 同构 + 主流 evaluate 语义）
# ---------------------------------------------------------------------------
def _java_double(d):
    """Java Double.toString: 整数值也带 .0（2 → "2.0"）。
    Python str(float) 与 Java Double.toString 在常规小数域一致; 科学计数法边界未实证"""
    return float(d)


def _eval_function(name, params, model, root):
    # PathFunctionFactory.FUNCTIONS: avg/stddev/sum/min/max/concat/length/size/append/keys/first/last/index
    if name in ("length", "size"):
        # Length: isArray/isMap → length; 否则 null（jsonProvider.length: array size / map size）
        if isinstance(model, (list, dict)):
            return len(model)
        return None
    if name == "keys":
        # KeySetFunction: isMap → getPropertyKeys（Map.keySet, Set 语义）; 否则 null
        if isinstance(model, dict):
            return _KeySet(model)
        return None
    if name in ("first", "last", "index"):
        # AbstractSequenceAggregation: 非数组 → JsonPathException
        if not isinstance(model, list):
            raise JsonPathErr("Aggregation function attempted to calculate value using empty array")
        if name == "first":
            if not model:
                raise IndexError("Index 0 out of bounds for length 0")
            return model[0]
        if name == "last":
            real = len(model) - 1  # targetIndex = -1
            if real > 0:
                return model[real]
            raise JsonPathErr("Target index:-1 larger than object count:%d" % len(model))
        try:
            i = int(params[0])
        except (IndexError, ValueError, TypeError):
            raise JsonPathErr("Target index requires integer parameter")
        if i >= 0:
            if i >= len(model):
                raise IndexError("Index %d out of bounds for length %d" % (i, len(model)))
            return model[i]
        real = len(model) + i
        if real > 0:
            return model[real]
        raise JsonPathErr("Target index:%d larger than object count:%d" % (i, len(model)))
    if name in ("min", "max", "sum", "avg", "stddev"):
        # AbstractAggregation: 数组内 Number 才计数; count == 0 → JsonPathException
        nums = []
        if isinstance(model, list):
            for v in model:
                if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                    nums.append(Decimal(str(v)))
        if not nums:
            raise JsonPathErr("Aggregation function attempted to calculate value using empty array")
        # AbstractAggregation: 全部走 Number.doubleValue() → Double.toString
        if name == "min":
            return _java_double(min(nums))
        if name == "max":
            return _java_double(max(nums))
        if name == "sum":
            return _java_double(sum(nums))
        if name == "avg":
            return _java_double(sum(nums) / len(nums))
        mean = sum(nums) / len(nums)
        var = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)
        return _java_double(var.sqrt())  # stddev
    if name == "concat":
        # Concatenate: 参数依次与上游结果拼接
        args = []
        for p in params:
            if p and p[0] in "$@":
                try:
                    args.append(JsonPath(p).read(root))
                except (PathNotFound, InvalidPath):
                    pass
            else:
                args.append(p)
        base = "" if model is None else _java_to_string(model)
        for a in args:
            base = "%s%s" % (base, a)
        return base
    if name == "append":
        base = list(model) if isinstance(model, list) else []
        for p in params:
            if p and p[0] in "[{":
                try:
                    base.append(json.loads(p))
                except Exception:
                    pass
            else:
                base.append(p)
        return base
    raise InvalidPath("Function with name: %s does not exist." % name)


# ---------------------------------------------------------------------------
# Legado 三入口（AnalyzeByJSonPath 同构）
# ---------------------------------------------------------------------------
def _read_to_string(v):
    """read 结果 → String: List → "\\n" join(String.valueOf 逐项); 单值 toString() ——
    单值为 null 时真机 NPE 被 catch（上层返回 ""），故此处上抛 None 由调用方处理"""
    if isinstance(v, list):
        return "\n".join(_java_to_string(x) for x in v)
    if v is None:
        raise PathNotFound("null toString")
    return _java_to_string(v)


def _java_to_string(x):
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, Decimal):
        return _bigdecimal_str(x)
    if isinstance(x, dict):
        # Java Map.toString: {k=v, k2=v2}
        return "{" + ", ".join("%s=%s" % (_java_to_string(k), _java_to_string(v))
                               for k, v in x.items()) + "}"
    if isinstance(x, list):
        # Java Collection.toString: [a, b, c]
        return "[" + ", ".join(_java_to_string(i) for i in x) + "]"
    return str(x)


def _inner_default_rule(rule, get_string_fn, data):
    """RuleAnalyzer.innerRule("{$.", 0, 0, fr) 同构: 处理 `{$.a||默认}` 块"""
    queue = rule
    start_x = 0
    out = []
    pos = 0
    while True:
        idx = queue.find("{$.", pos)
        if idx == -1:
            break
        end = _chomp_code_balanced(queue, idx)
        if end == -1:
            pos = idx + 1
            continue
        inner = queue[idx + 2:end]  # startStep=0, endStep=0 → 块内容（含 $ 前缀）
        rep = get_string_fn(inner, data)
        if rep:
            out.append(queue[start_x:idx])
            out.append(rep)
            start_x = end + 1
        pos = idx + 1
    if start_x == 0 and not out:
        return ""
    if start_x == 0:
        return ""
    out.append(queue[start_x:])
    return "".join(out)


def _chomp_code_balanced(s, open_pos):
    """chompCodeBalanced('{','}') 同构: 返回配对 '}' 的下标（从 open_pos 的 '{' 起）"""
    depth = 0
    i = open_pos
    in_str = None
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_rule(rule, seps):
    """RuleAnalyzer.splitRule(seps...) 同构（简化）: 顶层按 &&/||/%% 切分"""
    parts = []
    depth = 0
    in_str = None
    cur = []
    i = 0
    while i < len(rule):
        c = rule[i]
        if in_str:
            cur.append(c)
            if c == "\\":
                if i + 1 < len(rule):
                    cur.append(rule[i + 1])
                    i += 2
                    continue
            elif c == in_str:
                in_str = None
            i += 1
            continue
        if c in "'\"":
            in_str = c
            cur.append(c)
            i += 1
            continue
        if c in "[({":
            depth += 1
        elif c in "])}":
            depth -= 1
        if depth == 0:
            hit = None
            for sep in seps:
                if rule.startswith(sep, i):
                    hit = sep
                    break
            if hit:
                parts.append("".join(cur))
                cur = []
                i += len(hit)
                continue
        cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


def legado_get_string(rule, data):
    """AnalyzeByJSonPath.getString 同构"""
    if not rule:
        return None
    inner = _inner_default_rule(rule, legado_get_string, data)
    if inner:
        return inner
    split = _split_rule(rule, ("&&", "||"))
    if len(split) == 1:
        try:
            p = JsonPath(rule)
            v = p.read(data)
            return _read_to_string(v)
        except (PathNotFound, InvalidPath):
            return ""
        except Exception:
            return ""
    out = []
    for seg in split:
        s = legado_get_string(seg, data)
        if s:
            out.append(s)
            # || 命中即断
            if "||" in rule:
                break
    return "\n".join(out)


def legado_get_string_list(rule, data):
    """AnalyzeByJSonPath.getStringList 同构"""
    out = []
    if not rule:
        return out
    inner = _inner_default_rule(rule, legado_get_string_list, data)
    if inner:
        out.append(inner)
        return out
    split = _split_rule(rule, ("&&", "||", "%%"))
    if len(split) == 1:
        try:
            p = JsonPath(rule)
            v = p.read(data)
            if isinstance(v, list):
                out.extend(_java_to_string(x) for x in v)
            elif v is None:
                raise PathNotFound("null toString")  # 真机 NPE → catch
            else:
                out.append(_java_to_string(v))
        except (PathNotFound, InvalidPath):
            pass
        except Exception:
            pass
        return out
    # 多段组合（%% 交错合并 / 顺序追加）
    lists = []
    for seg in split:
        l = legado_get_string_list(seg, data)
        if l:
            lists.append(l)
    if not lists:
        return out
    if "%%" in rule:
        for i in range(len(lists[0])):
            for l in lists:
                if i < len(l):
                    out.append(l[i])
    else:
        for l in lists:
            out.extend(l)
    return out


def legado_get_list(rule, data):
    """AnalyzeByJSonPath.getList 同构: ctx.read → cast ArrayList, 异常 → 空"""
    if not rule:
        return []
    split = _split_rule(rule, ("&&", "||", "%%"))
    if len(split) == 1:
        try:
            p = JsonPath(rule)
            v = p.read(data)
            if isinstance(v, list):
                return v
            return []  # cast ClassCastException → catch
        except (PathNotFound, InvalidPath):
            return []
        except Exception:
            return []
    lists = []
    for seg in split:
        l = legado_get_list(seg, data)
        if l:
            lists.append(l)
            if "||" in rule:
                break
    out = []
    if "%%" in rule and lists:
        for i in range(len(lists[0])):
            for l in lists:
                if i < len(l):
                    out.append(l[i])
    else:
        for l in lists:
            out.extend(l)
    return out
