#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真机调试桥 —— 直连手机端「开源阅读(Legado)」App 的 Web 调试接口，跑真实规则、看真实报错。

为什么需要它？
------------
书源在沙盒/服务器上能跑通 ≠ 在手机上能跑通。真机有独立的网络出口、WebView 实现、
Cookie 存储和 Rhino 版本差异。靠在远端猜"为什么手机 404/空列表"几乎必错。
这个脚本把书源推到手机，让 Legado 真机执行解析，并把 App 真实返回的每一步调试
输出（含实际拿到的 HTML、报错、解析结果）原样回显，让诊断有据可依。

原理（协议经开源阅读 3.25 APK 反编译逐行确认，见下面"协议证据"）：
  1. POST http://<手机IP>:1122/saveBookSource   把书源 JSON 推到手机 App（App 必须先入库）
  2. WS   ws://<手机IP>:1123/bookSourceDebug    建立调试通道（端口 = HTTP 端口 + 1）
  3. 发送 {"tag": 书源URL, "key": 调试内容}（两个字段都不能为空，否则 App 直接关连接）
  4. 收集 App 回传的所有调试消息，直到连接关闭

协议证据（Legado 3.25，jadx 反编译 classes3.dex）：
  WebService.java      : HTTP 端口取 webPort 默认 1122；WebSocketServer(port + 1) → 1123
  HttpServer$serve$1   : /saveBookSource → d.R(postData)，POST 体即书源 JSON
  WebSocketServer      : /bookSourceDebug → BookSourceDebugWebSocket
  ...$onMessage$1      : Gson 解析 Map<String,String>，取 tag/key；
                         AppDatabaseKt.getAppDb().getBookSourceDao().getBookSource(tag) 取书源；
                         n0.b = webSocket; n0.f(scope, bookSource, key) 开始调试
  ...$printLog$1       : send(纯文本)；state == -1 || 1000 时 close(NormalClosure, "调试结束")
  model/n0.java  f()   : key 判定顺序 → URL?详情 : 含"::"?发现 : "++"?目录 : "--"?正文 : 搜索

前置条件：
  - 手机「开源阅读」App 已开启 Web 服务（设置 → 网络 → Web 服务 / Web 调试）
  - 运行脚本的电脑与手机在同一局域网，且能访问手机的 Web 服务端口（默认 1122）
  - Python 3.8+；可选 PyYAML（若要直接读 .yaml/.yml 书源）

用法：
  # 调试搜索（书源是 .json）
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="系统" --phase 1

  # 调试发现 / 详情 / 目录 / 正文
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="月票榜::https://.../xstop_allvisit_1.html" --phase 2
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="https://www.yndonie.com/book/12345/" --phase 3
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="++https://.../read/12345" --phase 4
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="--https://.../chapter/1.html" --phase 5

  # 一次跑多个阶段（搜索 + 详情 + 正文）
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json \
      --phase 1,3,5 --key="系统" --key3="https://.../book/123/" --key5="--https://.../1.html"

  # 只把书源推到手机（不调试，用于先导入再看）
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --save-only

  # 经代理连接（脚本与手机不互通、需跳板时）
  python3 legado_debug_bridge.py --host 192.168.1.100 --source ./yndonie.json --key="系统" --phase 1 --proxy http://127.0.0.1:7898

--key 格式（App 侧 n0.f() 的判定顺序，写错就跑错阶段）：
  1) 是 URL（http/https 开头）  → 详情页
  2) 含 "::"                    → 发现页（取 "::" 之后的部分当 URL）
  3) 以 "++" 开头               → 目录页（TocUrl）
  4) 以 "--" 开头               → 正文页（章节 URL）
  5) 其他                       → 搜索（当搜索词）

  搜索   "系统"
  发现   "玄幻::https://.../xssort_1_1.html"
  详情   "https://.../book/123/"
  目录   "++https://.../read/123"
  正文   "--https://.../chapter/1.html"

注意：`--key` 用等号形式传值（`--key="--https://..."`），因为正文的 key 本身以 `--` 开头，
用空格形式会被 argparse 当成选项吞掉。

退出码：0=解析完成(成功)  1=失败/连接错误
"""

import argparse
import base64
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ─── WebSocket 客户端（纯 stdlib，兼容 Legado 调试端点）────────────────────

def ws_connect(host, port, path, use_ssl=False, proxy=None, timeout=30):
    if proxy:
        parsed = urlparse(proxy)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((parsed.hostname, parsed.port or 80))
        sock.sendall(
            f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode()
        )
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("代理连接失败: 无响应")
            resp += chunk
        if "200" not in resp.split(b"\r\n")[0].decode():
            raise ConnectionError("代理隧道建立失败")
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

    if use_ssl:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)

    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("WebSocket 握手失败: 连接关闭")
        resp += chunk
    status_line = resp.split(b"\r\n")[0].decode()
    if "101" not in status_line:
        raise ConnectionError(f"WebSocket 握手失败: {status_line}")
    return sock


def ws_send(sock, message):
    payload = message.encode("utf-8")
    mask_key = os.urandom(4)
    masked = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    frame = bytearray([0x81])
    length = len(payload)
    if length < 126:
        frame.append(0x80 | length)
    elif length < 65536:
        frame.append(0x80 | 126)
        frame += struct.pack(">H", length)
    else:
        frame.append(0x80 | 127)
        frame += struct.pack(">Q", length)
    frame += mask_key
    frame += masked
    sock.sendall(frame)


def ws_recv(sock):
    header = _recv_exact(sock, 2)
    if header is None:
        return None
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F
    if length == 126:
        data = _recv_exact(sock, 2)
        if data is None:
            return None
        length = struct.unpack(">H", data)[0]
    elif length == 127:
        data = _recv_exact(sock, 8)
        if data is None:
            return None
        length = struct.unpack(">Q", data)[0]
    if masked:
        mask_key = _recv_exact(sock, 4)
        if mask_key is None:
            return None
        payload = _recv_exact(sock, length)
        if payload is None:
            return None
        payload = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    else:
        payload = _recv_exact(sock, length)
        if payload is None:
            return None
    if opcode == 0x8:
        return None  # close frame: 对端正常结束
    if opcode in (0x9, 0xA):
        return ""    # ping/pong: 非业务消息
    return bytes(payload).decode("utf-8", errors="replace")


def _recv_exact(sock, n):
    """精确收取 n 字节。

    超时时**向上抛 socket.timeout**(旧实现吞成 None, 上层把"20秒没新消息"当成
    连接结束 break —— 慢站点真机调试会被本地提前判"未通过", 是假阴性); EOF 才返回 None。
    """
    if n == 0:
        return bytearray()
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None  # EOF: 对端关闭
        buf += chunk
    return buf


# ─── HTTP 操作 ───────────────────────────────────────────────────────────────

def _opener(proxy):
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def save_book_source(host, port, source_json, proxy=None, timeout=15):
    url = f"http://{host}:{port}/saveBookSource"
    data = json.dumps(source_json, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"isSuccess": False, "errorMsg": f"连接失败: {e.reason}"}
    except Exception as e:  # noqa
        return {"isSuccess": False, "errorMsg": f"请求异常: {e}"}


# ─── 调试 ─────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://", re.I)


def detect_phase(key):
    """按 App 侧 n0.f() 的真实判定顺序推断 key 会跑哪个阶段，用于纠错提示。"""
    if _URL_RE.match(key or ""):
        return 3
    if "::" in (key or ""):
        return 2
    if (key or "").startswith("++"):
        return 4
    if (key or "").startswith("--"):
        return 5
    return 1


def debug_source(host, http_port, ws_port, source_json, key, proxy=None, timeout=120):
    """保存书源并直连真机调试，返回 (messages, success)"""
    source_url = source_json.get("bookSourceUrl", "")
    if not source_url:
        raise RuntimeError(
            "书源缺少 bookSourceUrl 字段：App 用它当 tag 查库（getBookSource(tag)），"
            "没有它就调不起来调试。请先补上 bookSourceUrl（一般用站点首页）。"
        )
    result = save_book_source(host, http_port, source_json, proxy)
    if not result.get("isSuccess"):
        raise RuntimeError(
            f"保存书源失败: {result.get('errorMsg', '未知错误')}\n"
            "  常见原因：手机 Web 服务没开 / 端口不对 / 不在同一局域网 / 手机锁屏断网。"
        )

    sock = ws_connect(host, ws_port, "/bookSourceDebug", proxy=proxy, timeout=30)
    ws_send(sock, json.dumps({"tag": source_url, "key": key}, ensure_ascii=False))

    messages = []
    deadline = time.time() + timeout
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                messages.append(f"⏱ 本地等待超时（{timeout}s），App 没在时限内结束调试。")
                break
            sock.settimeout(min(20, remaining))
            try:
                text = ws_recv(sock)
            except socket.timeout:
                # 20s 没有新消息只是"暂时安静", 不是连接结束 —— 慢站点(验证码页/慢响应)
                # 正是真机调试最常见的形态。继续等到总 deadline, 只有 EOF/close 才结束。
                continue
            if text is None:
                break
            if text:
                messages.append(text)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            sock.close()
        except Exception:  # noqa
            pass

    success = any("解析完成" in m or "调试完成" in m for m in messages[-5:])
    return messages, success


# ─── 主入口 ───────────────────────────────────────────────────────────────────

_PHASE_NAMES = {1: "搜索", 2: "发现", 3: "详情", 4: "目录", 5: "正文"}


def load_source(path):
    if not os.path.isfile(path):
        print(f"错误: 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    with open(path, "rb") as _f:
        raw = _f.read()

    def _decode_source_text(data):
        """utf-8 优先, GBK 文件的字节对可能意外构成合法 UTF-8(如 0xD5BE -> U+057E),
        因此 utf-8 解码成功后再做一次乱码嗅探: 书源(中文+ASCII+JSON)里出现
        西里尔/亚美尼亚区块几乎必是 GBK 被 utf-8 误解码的产物, 改判 gb18030。"""
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("gb18030", errors="replace")
        if re.search(r"[\u0400-\u058F\u0600-\u06FF]", text):
            try:
                alt = data.decode("gb18030")
            except UnicodeDecodeError:
                return text
            if re.search(r"[\u4e00-\u9fff]", alt):
                return alt
        return text

    text = _decode_source_text(raw)
    if ext in (".yaml", ".yml"):
        if not _YAML_AVAILABLE:
            print("错误: YAML 需要 PyYAML，请运行: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        source_json = yaml.safe_load(text)
    else:
        try:
            source_json = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"错误: 书源不是合法 JSON: {e}", file=sys.stderr)
            sys.exit(1)
    if isinstance(source_json, list):
        source_json = source_json[0] if source_json else {}
    return source_json


def abs_url(url, source_json):
    """相对路径按 bookSourceUrl 补全；绝对路径原样返回。"""
    url = (url or "").strip()
    if not url or _URL_RE.match(url):
        return url
    base = (source_json.get("bookSourceUrl") or "").rstrip("/")
    if not base:
        return url
    return base + ("" if url.startswith("/") else "/") + url


def first_explore_key(source_json):
    """从书源 exploreUrl 里取第一个分类，拼成发现阶段的 key：分类名::URL"""
    raw = source_json.get("exploreUrl", "")
    items = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        txt = raw.strip()
        if txt.startswith("["):
            try:
                items = json.loads(txt)
            except Exception:  # noqa
                items = [x for x in re.split(r"[\n,]+", txt.strip("[]")) if x.strip()]
        else:
            items = [x for x in txt.split("\n") if x.strip()]
    for it in items:
        if isinstance(it, dict):
            title = it.get("title") or it.get("name") or "分类"
            url = it.get("url") or it.get("urlRule") or ""
            if url:
                return f"{title}::{abs_url(url, source_json)}"
        elif isinstance(it, str):
            if "::" in it:
                title, _, url = it.partition("::")
                return f"{title.strip()}::{abs_url(url, source_json)}"
            if _URL_RE.search(it):
                return f"分类::{abs_url(it, source_json)}"
    return ""


def default_key(phase, source_json):
    """尽量自动猜一个 key；猜不出来就返回空，由调用方报错提示。"""
    if phase == 1:
        rules = source_json.get("ruleSearch") or {}
        return rules.get("checkKeyWord") or "我的"
    if phase == 2:
        return first_explore_key(source_json)
    return ""


def main():
    p = argparse.ArgumentParser(
        description="开源阅读(Legado)真机调试桥（直连手机 Web 调试接口，看真实报错）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__,
    )
    p.add_argument("--host", default="127.0.0.1", help="手机 Legado Web 服务地址（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=1122, help="HTTP 端口（默认 1122，WS 自动 +1）")
    p.add_argument("--ws-port", type=int, default=0, help="单独指定 WebSocket 端口")
    p.add_argument("--source", required=True, help="书源文件路径（.json/.yaml/.yml）")
    p.add_argument("--key", default="", help="调试关键字（单阶段；默认自动猜：搜索取 checkKeyWord，发现取首个分类）")
    p.add_argument("--keys", default="", help='多阶段各自的 key，JSON：{"1":"系统","5":"--https://..."}')
    p.add_argument("--phase", default="1", help="阶段 1-5（搜索/发现/详情/目录/正文），多个用逗号：1,3,5")
    p.add_argument("--timeout", type=int, default=120, help="单个阶段等待 App 调试结束的秒数（默认 120）")
    p.add_argument("--out", default="", help="把调试输出写入文件（便于整段贴回来分析）")
    p.add_argument("--proxy", default="", help="HTTP 代理，如 http://127.0.0.1:7898")
    p.add_argument("--save-only", action="store_true", help="仅保存书源到手机，不调试")
    args = p.parse_args()

    http_port = args.port
    ws_port = args.ws_port or (http_port + 1)
    source_json = load_source(os.path.expanduser(args.source))
    name = source_json.get("bookSourceName", source_json.get("sourceName", "未命名"))
    proxy = args.proxy or None

    if args.save_only:
        r = save_book_source(args.host, http_port, source_json, proxy)
        if r.get("isSuccess"):
            print(f"✓ 书源「{name}」已推送到手机 {args.host}:{http_port}")
        else:
            print(f"✗ 推送失败: {r.get('errorMsg', '未知错误')}", file=sys.stderr)
            print("  排查：手机 Web 服务开了吗？端口对吗？同局域网吗？手机锁屏会断网。", file=sys.stderr)
            sys.exit(1)
        return

    try:
        phases = [int(x) for x in str(args.phase).split(",") if x.strip()]
    except ValueError:
        print("错误: --phase 只能是 1-5 的数字，多个用逗号分隔", file=sys.stderr)
        sys.exit(1)

    keys_map = {}
    if args.keys:
        try:
            keys_map = {int(k): v for k, v in json.loads(args.keys).items()}
        except Exception as e:  # noqa
            print(f"错误: --keys 不是合法 JSON 映射: {e}", file=sys.stderr)
            sys.exit(1)

    out_lines = []
    overall_ok = True

    def emit(line=""):
        print(line)
        if args.out:
            out_lines.append(line)

    for phase in phases:
        phase_name = _PHASE_NAMES.get(phase, str(phase))
        key = keys_map.get(phase) or args.key or default_key(phase, source_json)
        if not key:
            emit(f"✗ 阶段{phase}({phase_name}) 缺少 key，无法调试。")
            emit(f"  阶段{phase} 需要显式给 key，例如：")
            emit('    --key="https://站点/book/123/"' if phase == 3 else
                 '    --key="++https://站点/read/123"' if phase == 4 else
                 '    --key="--https://站点/chapter/1.html"' if phase == 5 else
                 '    --key="分类名::https://站点/list.html"')
            overall_ok = False
            continue

        # 相对路径补全（目录/正文/详情传相对路径时 App 未必会拼 baseUrl，这里提前拼好）
        actual = detect_phase(key)
        if actual == 3:
            key = abs_url(key, source_json)
        elif actual in (4, 5):
            key = key[:2] + abs_url(key[2:], source_json)

        actual = detect_phase(key)
        emit(f"\n── 真机调试：阶段{phase}({phase_name}) 书源「{name}」 手机 {args.host}:{http_port} (WS {ws_port}) ──")
        emit(f"── key: {key} ──")
        if actual != phase:
            emit(f"⚠ 注意：按 App 判定规则，这个 key 会被当成【{_PHASE_NAMES.get(actual)}】处理，"
                 f"和你指定的【{phase_name}】不一致。请检查 key 格式："
                 f"详情=URL / 发现=名::URL / 目录=++URL / 正文=--URL / 搜索=普通词")

        try:
            messages, success = debug_source(
                args.host, http_port, ws_port, source_json, key, proxy, args.timeout
            )
        except Exception as e:  # noqa
            emit(f"✗ 调试失败（多半是连接/网络问题，先确认手机 Web 服务已开、同局域网可达）: {e}")
            overall_ok = False
            break

        emit("════════ 设备真实调试输出（下面就是手机 Legado 实际跑出来的内容）════════")
        for msg in messages:
            emit(msg)
        emit("════════════════════════════════════════════════════════════════════")

        if success:
            emit(f"✓ 阶段{phase}({phase_name}) 通过：App 返回「解析完成」，规则在该设备真实可用。")
        else:
            overall_ok = False
            emit(f"✗ 阶段{phase}({phase_name}) 未通过：没有收到「解析完成」。重点看上面输出里的 HTML/报错——")
            emit("  - 出现 404 / 验证页 / 空列表 → 设备侧真实问题，把上面输出整段发出来即可精准定位。")
            emit("  - 完全无输出 → 确认手机没锁屏、Web 服务端口可达、书源已保存成功。")

    if args.out:
        try:
            with open(os.path.expanduser(args.out), "w", encoding="utf-8") as f:
                f.write("\n".join(out_lines))
            print(f"\n（调试输出已写入 {args.out}）")
        except OSError as e:  # noqa
            print(f"（写日志失败: {e}）", file=sys.stderr)

    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
