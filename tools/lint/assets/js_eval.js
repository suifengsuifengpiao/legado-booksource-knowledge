// 书源 <js>/@js: 求值器 (对齐 APK AnalyzeRule.evalJS 的 Rhino 绑定)
// 输入: JSON {code, result, vars}  输出: 求值结果字符串
const crypto = require('crypto');

// ---- Packages.org.jsoup 桥 (对齐 Rhino 的 Java 桥; cheerio 实现 jsoup 子集) ----
// 支持: Jsoup.parse(html) -> Document; Parser.unescapeEntities(s, inAttr);
// Document/Element: select/attr/text/html/outerHtml/remove/size/get;
// Elements: size/get/text/html/attr。未收录的 jsoup API 返回 undefined(Rhino 会抛错, 与真机一致)。
let _JSOUP_OK = false;
let Packages = undefined, org = undefined;
(function () {
  let cheerio;
  try { cheerio = require('cheerio'); } catch (e) { return; }
  _JSOUP_OK = true;

  const NAMED_ENTITIES = { nbsp: ' ', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'",
    copy: '©', reg: '®', trade: '™', mdash: '—', ndash: '–', hellip: '…',
    ldquo: '“', rdquo: '”', lsquo: '‘', rsquo: '’', middot: '·', bull: '•',
    laquo: '«', raquo: '»', deg: '°', plusmn: '±', times: '×', divide: '÷',
    dagger: '†', permil: '‰', sup2: '²', sup3: '³', frac12: '½', frac14: '¼', frac34: '¾' };
  function decodeEntities(s, inAttr) {
    return String(s).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, function (m, g) {
      if (g.charAt(0) === '#') {
        const num = g.charAt(1) === 'x' || g.charAt(1) === 'X'
          ? parseInt(g.slice(2), 16) : parseInt(g.slice(1), 10);
        if (!isFinite(num) || num < 0 || num > 0x10FFFF) return m;
        try { return String.fromCodePoint(num); } catch (e) { return m; }
      }
      return NAMED_ENTITIES.hasOwnProperty(g) ? NAMED_ENTITIES[g] : m;
    });
  }

  function JElems($, sel) { this.$ = $; this.sel = sel; }
  JElems.prototype.size = function () { return this.sel.length; };
  JElems.prototype.get = function (i) {
    const node = this.sel.get(i);
    if (!node) return new JEl(this.$, this.$({ length: 0 }));
    return new JEl(this.$, this.$(node));
  };
  JElems.prototype.text = function () { return this.sel.text() || ''; };
  JElems.prototype.html = function () { const h = this.sel.html(); return h == null ? '' : h; };
  JElems.prototype.attr = function (n) { const v = this.sel.attr(n); return v == null ? '' : v; };
  JElems.prototype.remove = function () { this.sel.remove(); return this; };

  function JEl($, sel) { this.$ = $; this.sel = sel; }
  JEl.prototype.select = function (css) { return new JElems(this.$, this.sel.find(String(css))); };
  JEl.prototype.attr = function (n) { const v = this.sel.attr(String(n)); return v == null ? '' : v; };
  JEl.prototype.text = function () { return this.sel.text() || ''; };
  JEl.prototype.html = function () { const h = this.sel.html(); return h == null ? '' : h; };
  JEl.prototype.outerHtml = function () {
    let h = '';
    const $ = this.$;
    this.sel.each(function () { h += $.html(this) || ''; });
    return h;
  };
  JEl.prototype.remove = function () { this.sel.remove(); return this; };
  JEl.prototype.size = function () { return this.sel.length; };
  JEl.prototype.get = function (i) { return new JElems(this.$, this.sel).get(i); };

  function parseDoc(html) {
    const $ = cheerio.load(String(html == null ? '' : html));
    return new JEl($, $.root());
  }

  const Jsoup = { parse: parseDoc };
  const Parser = { unescapeEntities: decodeEntities };
  const _jsoup = { Jsoup: Jsoup, Parser: Parser, parser: { Parser: Parser } };
  // 层级: Packages.org.jsoup.Jsoup / Packages.org.jsoup.parser.Parser (Rhino Java桥)
  const _org = new Proxy({}, {
    get: function (t, p) { return p === 'jsoup' ? _jsoup : undefined; },
  });
  Packages = new Proxy({}, {
    get: function (t, p) { return p === 'org' ? _org : undefined; },
  });
  org = _org;
})();

function readStdin() {
  return new Promise((resolve) => {
    let d = '';
    process.stdin.on('data', (c) => (d += c));
    process.stdin.on('end', () => resolve(d));
  });
}

function b64decode(s) {
  try { return Buffer.from(String(s), 'base64').toString('utf-8'); }
  catch (e) { return ''; }
}
function b64encode(s) {
  try { return Buffer.from(String(s), 'utf-8').toString('base64'); }
  catch (e) { return ''; }
}
function md5(s) { return crypto.createHash('md5').update(String(s)).digest('hex'); }
function md5Hex(s) { return md5(s); }
function sha1(s) { return crypto.createHash('sha1').update(String(s)).digest('hex'); }

// AES 解密 (Legado: aesDecodeToString(content,key,iv,mode)); 容错降级
function aesKey(key) {
  const k = Buffer.alloc(16);
  const src = Buffer.from(String(key), 'utf-8');
  src.copy(k, 0, 0, Math.min(16, src.length));
  return k;
}
function aesIv(iv) {
  const v = Buffer.alloc(16);
  if (iv) { const s = Buffer.from(String(iv), 'utf-8'); s.copy(v, 0, 0, Math.min(16, s.length)); }
  return v;
}
function aesDecrypt(content, key, iv, mode) {
  try {
    mode = (mode || 'CBC').toUpperCase();
    const alg = 'aes-128-' + (mode === 'ECB' ? 'ecb' : 'cbc');
    const decipher = crypto.createDecipheriv(alg, aesKey(key), mode === 'ECB' ? null : aesIv(iv));
    let out = decipher.update(String(content), 'base64', 'utf-8');
    out += decipher.final('utf-8');
    return out;
  } catch (e) {
    return '';
  }
}
function aesEncrypt(content, key, iv, mode) {
  try {
    mode = (mode || 'CBC').toUpperCase();
    const alg = 'aes-128-' + (mode === 'ECB' ? 'ecb' : 'cbc');
    const cipher = crypto.createCipheriv(alg, aesKey(key), mode === 'ECB' ? null : aesIv(iv));
    let out = cipher.update(String(content), 'utf-8', 'base64');
    out += cipher.final('base64');
    return out;
  } catch (e) {
    return '';
  }
}

async function main() {
  const input = await readStdin();
  let data;
  try { data = JSON.parse(input); } catch (e) { process.stdout.write(''); return; }
  const code = data.code || '';
  const vars = data.vars || {};
  let result = data.result;

  // 未知方法优雅降级为返回 '' (对齐 App 中未实现桩的 java.* 调用)
  const _stub = () => '';
  const java = new Proxy({
    base64Decode: b64decode,
    base64Encode: b64encode,
    md5: md5,
    md5Hex: md5Hex,
    sha1: sha1,
    aesDecodeToString: aesDecrypt,
    aesDecrypt: aesDecrypt,
    aesDecodeToByteArray: aesDecrypt,
    aesEncodeToString: aesEncrypt,
    aesEncrypt: aesEncrypt,
    substring: (s, a, b) => String(s).substring(a, b),
    encodeURI: (s) => encodeURIComponent(String(s)).replace(/%20/g, '+'),
    decodeURI: (s) => decodeURIComponent(String(s).replace(/\+/g, ' ')),
    encodeURIWithPercent: (s) => encodeURIComponent(String(s)),
    get: (k) => (vars[k] !== undefined ? vars[k] : ''),
    put: (k, v) => { vars[k] = v; return v; },
    connect: () => '',
    ajax: () => '',
  }, {
    get(target, prop) { return prop in target ? target[prop] : _stub; },
  });

  const source = { bookSourceUrl: vars.baseUrl || '' };
  const book = { bookUrl: vars.bookUrl || '' };
  // 真机绑定(AnalyzeRule.smali:2502 实证): src = AnalyzeRule.content（整页源码）
  const src = data.src || '';
  const baseUrl = vars.baseUrl || '';
  const cookie = {};
  const cache = {};
  const chapter = {};

  var out;
  try {
    // Rhino 返回脚本最后一个表达式的值; 直接 eval 贴近该行为(可访问闭包内的
    // result/java/book 绑定)。外层用 var 声明 out, 与规则内 var out 重声明不冲突
    // (仅 let/const 词法重声明才会 SyntaxError), 保持 Rhino 兼容。
    out = eval(code);
  } catch (e) {
    out = '<<JS_ERROR:' + e.message + '>>';
  }
  if (out === undefined || out === null) out = '';
  // 列表模式: 真机 Rhino 返回 NativeArray → getElements 按 List 逐元素取(不是按行拆)。
  // 以 JSON 数组整体回传, Python 侧 json.loads 还原逐元素; 字符串结果仍按 \n 拆(真机语义)。
  if (data.list_mode && Array.isArray(out)) {
    process.stdout.write(JSON.stringify(out.map((x) => (x == null ? '' : String(x)))));
    return;
  }
  if (typeof out === 'object') out = JSON.stringify(out);
  process.stdout.write(String(out));
}

main();
