#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断探针书源生成器 —— 给「没有电脑、连不了 Web 服务」的用户用的设备侧诊断方案。

原理
----
不依赖任何外部调试通道：探针本身就是一个正常书源，走 Legado 的完整请求链路
（含 loginCheckJs / cookie / header / charset），但在搜索结果阶段用 @js 把
**设备侧真实拿到的东西**逐条拼成"书名"显示出来。用户在 App 里搜任意词，
列表就是一份诊断报告，截图/复制发出来即可定位。

用法
----
  # 生成一个站点的诊断探针
  python3 make_probe_source.py --url https://www.yndonie.com \
      --search-url "https://www.yndonie.com/modules/article/search.php?searchkey={{key}}&searchtype=articlename" \
      --charset gbk --out ./yndonie_probe.json

  # 带上与正式书源一致的 loginCheckJs（用于验证 loginCheckJs 在真机上到底跑没跑）
  python3 make_probe_source.py --url https://www.example.com \
      --search-url "https://www.example.com/search?q={{key}}" --login-check-js ./login_check.js

  # 探针 2 号：探测详情页/正文（给一个真实书籍 URL）
  python3 make_probe_source.py --url https://www.example.com --detail-url "https://www.example.com/book/123/"

生成后交给用户：App → 书源管理 → 导入（本地/剪贴板）→ 搜索任意词 → 截图列表。
"""

import argparse
import json
import os
import re
import sys


# ── 探针核心 JS：分析设备侧真实响应，产出逐条诊断 ──────────────────────────────
# get_source_js 由调用方注入：决定从哪里拿"设备拿到的源码"
# mode: list  → 返回数组（每个诊断项一本书，列表一行一条）
#       single → 返回拼好的字符串（整份报告作为一本书的书名）
def _probe_js(get_source_js, mode):
    tail = "o;" if mode == "list" else "o.join('\\n');"
    return r"""
var b = '';
try { b = %s; } catch (e) { b = String(result || ''); }
if (!b) { b = String(result || src || ''); }

var o = [];
function add(s) { o.push(String(s)); }
function has(re) { try { return new RegExp(re, 'i').test(b); } catch (e) { return false; } }

add('【诊断关键词: ' + (typeof key !== 'undefined' ? key : '') + '】源码长度=' + (b ? b.length : 0));

/* ① 环境探测：java 对象上到底有哪些方法（踩过 urlEncode 不存在的坑） */
var api = [];
var names = ['encodeURI', 'ajax', 'connect', 'startBrowserAwait', 'webView', 'log'];
for (var i = 0; i < names.length; i++) {
  var t = 'undefined';
  try { t = typeof java[names[i]]; } catch (e) { t = 'err'; }
  if (t !== 'undefined' && t !== 'err') { api.push(names[i]); }
}
add('① java 可用方法: ' + (api.join(',') || '（一个都没有，java 对象异常）'));

/* ② 验证墙命中 */
var wall = '无';
if (has('encryptedCookieValue')) wall = '自建验证页(明文cookie，loginCheckJs 可解)';
else if (has('访问验证|安全验证|浏览器检查')) wall = '自建验证页(没找到明文cookie值，站点可能已改成加密)';
else if (has('_cf_chl|cf-browser-verification|Just a moment|turnstile')) wall = 'Cloudflare 盾';
else if (has('captcha|滑动验证|请输入验证码')) wall = '疑似验证码页';
add('② 命中验证墙: ' + wall);

/* ③ cookie 状态（验证 loginCheckJs 有没有真的把 cookie 写进去） */
var ck = '';
try {
  ck = cookie.getKey(baseUrl, 'is_human') || '';
} catch (e) {
  ck = '取cookie异常:' + e;
}
add('③ is_human cookie: ' + (ck ? ('已设置=' + String(ck).substring(0, 24)) : '未设置'));

/* ④ 编码是否正常（GBK 站配 UTF-8 会出一堆替换符） */
var bad = 0;
try { bad = (b.match(/\ufffd/g) || []).length; } catch (e) {}
add('④ 乱码替换符数: ' + bad + (bad > 20 ? '  ← 编码错了，检查 charset' : ''));

/* ⑤ 是否真的有数据（按常见 CMS 特征粗判） */
var feats = ['bookname', 'class="even"', 'class="odd"', 'class="s2"', 'class="grid"',
             'class="list"', 'book-info', 'result-item', 'author', 'update'];
var hitList = [];
for (var j = 0; j < feats.length; j++) { if (has(feats[j])) { hitList.push(feats[j]); } }
add('⑤ 搜索结果特征: ' + (hitList.length ? ('疑似有(' + hitList.slice(0, 4).join('/') + ')') : '未识别'));

/* ⑥ 设备拿到的内容预览（去标签） */
var preview = '';
try { preview = b.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').substring(0, 150); } catch (e) { preview = '解析失败:' + e; }
add('⑥ 前150字: ' + (preview || '（空！请求没拿到内容）'));

/* ⑦ HTTP 错误页线索（只在短页面/标题里判，避免正文含数字被误报） */
var t7 = '';
try {
  var tm = b.match(/<title[^>]*>([\s\S]{0,60}?)<\/title>/i);
  t7 = tm ? tm[1] : b.substring(0, 60);
} catch (e) { t7 = b.substring(0, 60); }
if (b.length < 1500) add('⑦ 响应很短(' + b.length + ')，基本没拿到内容');
else if (/404|not found|不存在|错误/i.test(t7)) add('⑦ 标题疑似错误页: ' + t7.replace(/\s+/g, ' ').substring(0, 40));
else if (/403|forbidden|拒绝/i.test(t7)) add('⑦ 标题疑似 403: ' + t7.replace(/\s+/g, ' ').substring(0, 40));
else add('⑦ 未见 HTTP 错误页特征，标题: ' + t7.replace(/\s+/g, ' ').substring(0, 30));

/* ⑧ 关键词有没有真的被拿去搜 */
add('⑧ 页面含搜索词\"' + (typeof key !== 'undefined' ? key : '') + '\": ' + (has(key || 'zzz_never') ? '是' : '否'));

%s
""".strip() % (get_source_js, tail)


# 探针 A：bookList 用 @js 直接产出数组，源码来自 result/src
_GET_SRC_LIST = "(typeof result === 'string' && result) ? result : (typeof src === 'string' ? src : String(result || ''))"
# 探针 B：bookList 用 XPath 命中 body，源码从 Element 上取（不依赖 @js 数组是否被支持）
_GET_SRC_SINGLE = "(result && result.html) ? result.html() : ((result && result.text) ? result.text() : String(result || ''))"


def _js_str(value):
    """把用户可控字符串安全嵌成 JS 字符串字面量。

    URL 直接拼进 `@js:'...'` 是注入面: URL 里一个单引号(或换行)就能截断字面量、
    注入任意 JS 到书源里(App 侧 @js 即代码执行)。json.dumps 产出的双引号字面量
    对引号/反斜杠/控制字符全部转义, 且是合法的 JS 表达式, Legado @js: 原样执行。
    """
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def build_probe(url, search_url=None, detail_url=None, charset="", login_check_js="", name="", mode="list"):
    url = url.rstrip("/")
    host = re.sub(r"^https?://", "", url).split("/")[0]
    src_name = name or (f"{host} 诊断探针A" if mode == "list" else f"{host} 诊断探针B")
    target = detail_url or search_url or (url + "/")

    # charset 只能写在 URL 行内选项里(书源顶层 charset 是死字段, 3.25 Gson 静默丢弃);
    # 探针的乱码嗅探在 JS 里自己做, 这里给的 charset 是让 App 抓响应时按声明编码解码
    search_url_value = search_url or detail_url or (url + "/")
    if charset and not re.search(r",\s*\{", search_url_value):
        search_url_value = search_url_value + ",{\"charset\": " + json.dumps(charset) + "}"

    src = {
        "bookSourceName": src_name,
        "bookSourceUrl": url + "/",
        "bookSourceType": 0,
        "bookSourceGroup": "诊断",
        "enabled": True,
        "header": "",
        "searchUrl": search_url_value,
        "bookSourceComment": (
            "诊断探针：搜索任意关键词，结果列表就是设备侧真实诊断报告"
            "（java方法/验证墙/cookie/编码/数据特征/内容预览）。截图发给开发者即可定位。诊断完可删除。"
        ),
    }

    if mode == "list":
        src["ruleSearch"] = {
            "checkKeyWord": "test",
            "bookList": "@js:" + _probe_js(_GET_SRC_LIST, "list"),
            "name": "@js:result",
            "author": "@js:''",
            "intro": "@js:''",
            "kind": "@js:'诊断'",
            "lastChapter": "@js:'点开无内容，这是诊断条目'",
            "coverUrl": "@js:''",
            "bookUrl": "@js:" + _js_str(target),
        }
    else:
        src["ruleSearch"] = {
            "checkKeyWord": "test",
            "bookList": "//body",
            "name": "@js:" + _probe_js(_GET_SRC_SINGLE, "single"),
            "author": "@js:'诊断报告见书名'",
            "intro": "@js:''",
            "kind": "@js:'诊断'",
            "lastChapter": "@js:'点开无内容，这是诊断条目'",
            "coverUrl": "@js:''",
            "bookUrl": "@js:" + _js_str(target),
        }

    if login_check_js:
        src["loginCheckJs"] = login_check_js

    return src


def main():
    p = argparse.ArgumentParser(
        description="生成 Legado 诊断探针书源（无电脑也能做的设备侧诊断）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__,
    )
    p.add_argument("--url", required=True, help="站点根 URL（用作 bookSourceUrl 与相对路径基准）")
    p.add_argument("--search-url", default="", help="搜索 URL，含 {{key}} 占位符")
    p.add_argument("--detail-url", default="", help="改为探测某个详情页/目录页 URL")
    p.add_argument("--charset", default="", help="站点编码（gbk/utf-8），不填则留空由 App 判断")
    p.add_argument("--login-check-js", default="", help="loginCheckJs 文件路径，验证它在真机上是否生效")
    p.add_argument("--name", default="", help="书源名称（默认「<域名> 诊断探针」）")
    p.add_argument("--out", required=True, help="输出 JSON 路径")
    args = p.parse_args()

    lc = ""
    if args.login_check_js:
        path = os.path.expanduser(args.login_check_js)
        if not os.path.isfile(path):
            print(f"错误: loginCheckJs 文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            lc = f.read().strip()

    # 两个探针一起给：A 走 @js 数组多条目，B 走 XPath+单条目书名，互为备份
    pa = build_probe(args.url, args.search_url, args.detail_url, args.charset, lc, args.name, "list")
    pb_name = (args.name + "-B") if args.name else ""
    pb = build_probe(args.url, args.search_url, args.detail_url, args.charset, lc, pb_name, "single")
    out = os.path.expanduser(args.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump([pa, pb], f, ensure_ascii=False, indent=2)
    print(f"✓ 诊断探针已生成（A/B 两个，一次导入即可）: {out}")
    print("  交给用户：App → 书源管理 → 导入 → 分别搜索任意词 → 列表/书名即诊断报告，截图发回。")


if __name__ == "__main__":
    main()
