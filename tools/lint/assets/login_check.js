#!/usr/bin/env node
/*
 * login_check.js —— 在沙箱里模拟 Legado 的 loginCheckJs 执行（对齐 AnalyzeUrl.evalJS）。
 *
 * 真机语义（反编译 WebBook/x0.smali + AnalyzeUrl.smali 实证）：
 *   - 每步请求拿到 StrResponse 后，若有 loginCheckJs，调 AnalyzeUrl.evalJS(loginCheckJs, response)
 *   - JS 内 result 是响应对象（.body/.url/.header/.cookie），java 是 AnalyzeUrl 实例
 *   - java.ajax 是【同步阻塞】(okhttp 同步)，发的请求 cookie 自动进 okhttp cookieJar，后续自动带
 *   - 返回值（response 对象或字符串）替换原响应
 *
 * 本脚本把 java.ajax 实现为【同步】：用 curl 子进程（自带 cookie jar + 跟随重定向），
 * 对齐真机"阻塞式发请求后才继续脚本"的时序，避免 Promise 未 resolve 就 return 的陷阱。
 *
 * stdin JSON:  { js, response:{url,body,header}, baseUrl, cookie, headers }
 * stdout JSON: { cookie:"k=v; ...", body:"...", error:"..." }
 *
 * 运行依赖（重要）：
 *   1. 必须带 --openssl-legacy-provider 启动 —— Node22 的 OpenSSL3 把单 DES
 *      (DES/ECB、DES/CBC...) 挪进了 legacy provider，而真机 javax/Conscrypt 原生
 *      支持；不加该参数 DES 变换会抛 ERR_OSSL_EVP_UNSUPPORTED（与真机行为不符）。
 *   2. 需要 node_modules/iconv-lite（Java Charset.forName 支持 GBK/Big5 等，
 *      node Buffer 不支持，故 base64Decode(charset)/strToBytes(charset)/GBK URL
 *      编码都依赖它）。
 *   3. 测试通道：stdin 传 { "__eval__": "java.digestHex('abc','MD5')" } 直接返回
 *      JS completion value（不发请求），供 test_crypto_apis.js 单测使用。
 *
 * 加密/编码层语义全部由真机 3.25 反编译源码实证：
 *   - io.legado.app.help.p0（hutool/Android Base64 封装）
 *   - cn.hutool.crypto.symmetric.SymmetricCrypto / a / b（加解密）
 *   - cn.hutool.crypto.digest.Digester/HMac、cn.hutool.crypto.KeyUtil
 *   - BaseSource$DefaultImpls（接口默认方法 → p0 的映射，决定 Encode/Decode 真实语义）
 *   - kotlin.text.a.f9738a = UTF-8；kotlin.text.d0.a0(s) = s.getBytes(UTF-8)
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { URL } = require('url');
const crypto = require('crypto');
const iconv = require(path.join(__dirname, 'node_modules', 'iconv-lite'));

// ============================================================
// 加密/编码工具层 —— 全部语义对齐真机 3.25 反编译源码：
//   io.legado.app.help.p0          (hutool/Android Base64 封装)
//   cn.hutool.crypto.symmetric.*   (SymmetricCrypto/HMac/Digester)
//   kotlin.text.a.f9738a = UTF-8   (kotlin/text/a.java:22)
//   kotlin.text.d0.a0(s) = s.getBytes(UTF-8)  (kotlin/text/d0.java:16)
// ============================================================

// ---- charset（Java Charset.forName 全集 → iconv-lite） ----
function csBytes(str, charset) {
  try { return iconv.encode(String(str), charset || 'UTF-8'); }
  catch (e) { throw new Error('Unsupported charset: ' + charset); }
}
function csStr(bytes, charset) {
  try { return iconv.decode(Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes || []), charset || 'UTF-8'); }
  catch (e) { throw new Error('Unsupported charset: ' + charset); }
}

// ============================================================
// 文件/归档/工具类辅助（JsExtensions 接口；DefaultImpls→p0 实证，可离线实现）
//   - zip 内容读取用 `unzip -p`（环境已验证 unzip 可用）
//   - 7z/rar 本环境无 7z CLI（apt 不可用），内核无法离线读取，优雅返回空（不崩溃）
//   - GUI/TTF 反爬/非对称签名/toNumChapter 无头环境不支持，返回 null/'' 由文档标注未对齐
// ============================================================
function _readEntry(cli, args, charset, asBytes) {
  try {
    const buf = execFileSync(cli, args, { maxBuffer: 50 * 1024 * 1024, timeout: 15000 });
    if (asBytes) return buf.toString('base64');   // lint 场景 byte[] 不可序列化 → base64 字符串
    return csStr(buf, charset);
  } catch (e) { return asBytes ? '' : ''; }
}
function _extractZip(zipPath, outDir) {
  try {
    fs.mkdirSync(outDir, { recursive: true });
    execFileSync('unzip', ['-o', zipPath, '-d', outDir], { timeout: 20000 });
    return outDir;
  } catch (e) { return ''; }
}
function formatHtml(html) {
  // 真机用 jsoup 重新解析并格式化输出；无头环境做轻量块级缩进（语义近似，仅供 lint）
  const depthByTag = /^(html|head|body|div|table|tr|td|th|ul|ol|li|section|article|header|footer|nav|main|dl|dd|dt|figure|blockquote)$/i;
  let depth = 0; const out = [];
  String(html || '').replace(/(<\/?[a-zA-Z][^>]*>)|([^<]+)/g, (m, tag, text) => {
    if (tag) {
      const closing = /^<\//.test(tag);
      const self = /\/>$/.test(tag) || /^<(br|img|hr|input|meta|link|area|base|col|embed|source|track|wbr)\b/i.test(tag);
      if (closing) depth = Math.max(0, depth - 1);
      out.push((depth > 0 ? '  '.repeat(depth) : '') + tag);
      if (!closing && !self) depth++;
    } else if (text != null) {
      const t = text.trim();
      if (t) out.push((depth > 0 ? '  '.repeat(depth) : '') + t);
    }
    return m;
  });
  return out.join('\n');
}

// ---- java.net.URLEncoder.encode(s, enc)（p0.P: URLEncoder.encode, 失败返回 ""） ----
const URLEN_SAFE = /[A-Za-z0-9\-*._]/;
function formEncode(str, enc) {
  try {
    const b = csBytes(str, enc);
    let out = '';
    for (const x of b) {
      if (x === 0x20) out += '+';
      else if (URLEN_SAFE.test(String.fromCharCode(x))) out += String.fromCharCode(x);
      else out += '%' + x.toString(16).toUpperCase().padStart(2, '0');
    }
    return out;
  } catch (e) { return ''; }
}

// ---- android.util.Base64（flag: DEFAULT=0 NO_PADDING=1 NO_WRAP=2 CRLF=4 URL_SAFE=8） ----
function b64Wrap(s, flags) {
  if (flags & 2) return s;                       // NO_WRAP
  let out = '';
  while (s.length > 76) {
    out += s.slice(0, 76) + ((flags & 4) ? '\r\n' : '\n') + s.slice(76);
    s = s.slice(76);
  }
  return out + s;
}
function androidB64Enc(bytes, flags) {
  let s = Buffer.from(bytes).toString('base64');
  if (flags & 8) s = s.replace(/\+/g, '-').replace(/\//g, '_');
  if (flags & 1) s = s.replace(/=+$/, '');
  return b64Wrap(s, flags);
}
function androidB64Dec(str, flags) {
  let s = String(str);
  if (flags & 8) s = s.replace(/-/g, '+').replace(/_/g, '/');
  if (flags & 1 && s.length % 4 !== 0) s += '='.repeat((4 - s.length % 4) % 4);
  return Buffer.from(s, 'base64');
}
// Android Base64 flag=2 输出 ≡ hutool Base64.encode（java.util.Base64: 无换行、保留 padding）
function aB64(bytes) { return androidB64Enc(bytes, 2); }

// ---- MessageDigest / Mac 算法名（JCA 名大小写不敏感 → node crypto） ----
const DIGESTS = { md5:'md5', md2:null, sha1:'sha1', sha224:'sha224', sha256:'sha256', sha384:'sha384', sha512:'sha512' };
function digestName(n) {
  const k = String(n || '').replace(/[-\s_]/g, '').toLowerCase();
  if (!(k in DIGESTS) || !DIGESTS[k]) throw new Error('Unsupported digest algorithm: ' + n + '（真机 MessageDigest 无此算法或工具未实现）');
  return DIGESTS[k];
}
function macName(n) {
  const k = String(n || '').replace(/^hmac[-\s_]*/i, '').replace(/[-\s_]/g, '').toLowerCase();
  if (!(k in DIGESTS) || !DIGESTS[k]) throw new Error('Unsupported HMac algorithm: ' + n);
  return DIGESTS[k];
}

// ---- javax Cipher transformation → node ----
function parseTransformation(t) {
  let s = String(t);
  let zeroPad = false;
  if (s.indexOf('ZeroPadding') >= 0) { s = s.replace(/ZeroPadding/g, 'NoPadding'); zeroPad = true; } // SymmetricCrypto.init:166-170
  const parts = s.split('/').map(x => x.trim());
  const algo = (parts[0] || '').toUpperCase();
  // javax: mode/padding 可省略 → provider 默认 ECB/PKCS5Padding；node 同样归一
  const mode = (parts[1] || 'ECB').toUpperCase();
  const padding = (parts[2] || 'PKCS5Padding').toUpperCase();
  const MODES = { ECB:'ecb', CBC:'cbc', CTR:'ctr', OFB:'ofb', CFB:'cfb', CFB128:'cfb', CFB8:'cfb8',
                  NOFB:'ofb', CFB64:'cfb1' /* node无64位视同 cfb1，罕见 */ };
  if (!MODES[mode]) throw new Error('Unsupported cipher mode: ' + t);
  let autoPad = true;
  if (padding === 'NOPADDING') autoPad = false;
  else if (padding === 'PKCS5PADDING' || padding === 'PKCS7PADDING' || padding === 'ISO10126PADDING') autoPad = true;
  else throw new Error('Unsupported cipher padding: ' + t);
  let nodeAlgo;
  if (algo === 'AES') nodeAlgo = 'aes';
  else if (algo === 'DESEDE' || algo === 'TRIPLEDES' || algo === 'DESEDEWRAP') nodeAlgo = 'des-ede3';
  else if (algo === 'DES') nodeAlgo = 'des';
  else throw new Error('Unsupported cipher algorithm: ' + t + '（真机 javax Cipher 不支持或工具未实现）');
  return { nodeAlgo, mode: MODES[mode], autoPad, zeroPad };
}

// KeyUtil.generateKey(KeyUtil.java:generateDESKey)：DES 必须 8 字节；DESede 16/24（16 展开 K1K2K1，>24 截断前 24 实为报错由 DESedeKeySpec 抛）
function normKey(nodeAlgo, keyBuf) {
  if (nodeAlgo === 'des') {
    if (keyBuf.length !== 8) throw new Error('DES key must be 8 bytes (DESKeySpec)');
    return keyBuf;
  }
  if (nodeAlgo === 'des-ede3') {
    if (keyBuf.length === 16) return Buffer.concat([keyBuf, keyBuf.slice(0, 8)]); // DESedeKeySpec: K1K2K1
    if (keyBuf.length === 24) return keyBuf;
    throw new Error('DESede key must be 16 or 24 bytes (DESedeKeySpec)');
  }
  return keyBuf; // AES: SecretKeySpec 原样，长度 16/24/32 由 node 决定
}

// SymmetricCrypto（SymmetricCrypto.java）
function makeSymmetric(transformation, keyBuf, ivBuf) {
  const { nodeAlgo, mode, autoPad, zeroPad } = parseTransformation(transformation);
  const key = normKey(nodeAlgo, keyBuf);
  const iv = (mode !== 'ecb' && ivBuf && ivBuf.length > 0) ? ivBuf : null;
  if (mode !== 'ecb' && !iv) {
    if (transformation.indexOf('/ECB/') < 0) throw new Error('cipher needs an IV but none given');
  }
  const ivLen = nodeAlgo === 'des' || nodeAlgo === 'des-ede3' ? 8 : 16;
  if (iv && iv.length !== ivLen) throw new Error('IV length must be ' + ivLen + ' bytes');
  const name = nodeAlgo === 'aes' ? nodeAlgo + '-' + (key.length * 8) + '-' + mode
             : nodeAlgo + '-' + mode;  // des / des-ede3 无位数后缀
  function enc(buf) {
    let data = Buffer.from(buf);
    if (zeroPad && data.length % ivLen !== 0) {
      data = Buffer.concat([data, Buffer.alloc(ivLen - data.length % ivLen)]); // paddingDataWithZero
    }
    const c = crypto.createCipheriv(name, key, iv ? Buffer.from(iv) : null, { autoPadding: autoPad });
    return Buffer.concat([c.update(data), c.final()]);
  }
  function dec(buf) {
    const c = crypto.createDecipheriv(name, key, iv ? Buffer.from(iv) : null, { autoPadding: autoPad });
    let out = Buffer.concat([c.update(buf), c.final()]);
    if (zeroPad) { let i = out.length; while (i > 0 && out[i - 1] === 0) i--; out = out.slice(0, i); } // removePadding
    return out;
  }
  return {
    encrypt(buf) { return enc(Buffer.from(buf)); },
    decrypt(buf) { return dec(Buffer.from(buf)); },
    encryptBase64(s) { return aB64(enc(Buffer.from(String(s), 'utf-8'))); },   // b.f: encryptBase64(String)
    encryptStr(s) { return Buffer.from(String(s), 'utf-8'); },                  // 预留
    encryptHex(s) { return enc(Buffer.from(String(s), 'utf-8')).toString('hex'); },
    decrypt(b64s) { return dec(androidB64Dec(String(b64s), 0)); },              // SecureUtil.decode → decrypt
    decryptStr(b64s) { return csStr(dec(androidB64Dec(String(b64s), 0)), 'UTF-8'); }, // a.e: decryptStr
    decryptHex(hexs) { return dec(Buffer.from(String(hexs), 'hex')); }
  };
}

// ---------------- 简易内存 cookie jar（按 domain） ----------------
let JAR = {}; // domain -> [{name, value, domain}]

function domainOf(u) {
  try { return new URL(u).hostname; } catch (e) { return ''; }
}
function cookieHeaderFor(url) {
  const d = domainOf(url);
  const out = [];
  for (const dom of Object.keys(JAR)) {
    if (d === dom || d.endsWith('.' + dom) || ('.' + d).endsWith('.' + dom)) {
      for (const e of JAR[dom]) out.push(e.name + '=' + e.value);
    }
  }
  return out.join('; ');
}
function jarToString() {
  const out = [];
  for (const dom of Object.keys(JAR)) for (const e of JAR[dom]) out.push(e.name + '=' + e.value);
  return out.join('; ');
}
// 真机 StrResponse(io/legado/app/help/http/StrResponse.smali) 实证方法集:
//   body():193 与 getBody():234 同义(都取 body 字段); url():369 / getUrl():267;
//   headers():282 / code():204 / isSuccessful():301 / message():320 / raw():339
//   errorBody():223 / getRaw():256 / getErrorBody():245 / toString():350
function makeStrResponse(r) {
  const b = (r && r.body) || '';
  const u = (r && r.url) || '';
  return {
    body: () => b,
    getBody: () => b,
    url: () => u,
    getUrl: () => u,
    headers: () => (r && r.header) || '',
    code: () => 200,
    isSuccessful: () => true,
    message: () => '',
    raw: () => null,
    getRaw: () => null,
    errorBody: () => null,
    getErrorBody: () => null,
    cookie: (r && r.cookie) || '',
    header: (r && r.header) || '',
    toString: () => b,
  };
}

function applyCookieString(str, baseUrl) {
  if (!str) return;
  const d = domainOf(baseUrl);
  for (const part of str.split(';')) {
    const kv = part.trim();
    if (!kv || kv.indexOf('=') < 0) continue;
    const [n, ...v] = kv.split('=');
    JAR[d] = JAR[d] || [];
    let found = false;
    for (const e of JAR[d]) if (e.name === n.trim()) { e.value = v.join('=').trim(); found = true; }
    if (!found) JAR[d].push({ name: n.trim(), value: v.join('=').trim(), domain: d });
  }
}
function ingestCookieFile(file) {
  try {
    const lines = fs.readFileSync(file, 'utf-8').split('\n');
    for (const l of lines) {
      if (l.startsWith('#') || !l.trim()) continue;
      const p = l.split('\t');
      if (p.length >= 7 && p[5]) {
        const dom = p[0].replace(/^\./, ''), name = p[5], val = p[6];
        JAR[dom] = JAR[dom] || [];
        let found = false;
        for (const e of JAR[dom]) if (e.name === name) { e.value = val; found = true; }
        if (!found) JAR[dom].push({ name, value: val, domain: dom });
      }
    }
  } catch (e) {}
}

// ---------------- 同步发请求（curl：cookie jar + 跟随重定向） ----------------
function doRequestSync(target, method, body, headers, baseUrl) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lcs-'));
  const cj = path.join(tmp, 'cj.txt');
  fs.writeFileSync(cj, '');
  let url = target;
  try { url = new URL(url, baseUrl).toString(); } catch (e) {}
  let last = { url, body: '', header: '', cookie: '' };
  for (let i = 0; i < 6; i++) {
    const args = ['-s', '-i', '-L', '-m', '20', '-X', (method || 'GET').toUpperCase(), url,
                  '-b', cj, '-c', cj];
    for (const k in (headers || {})) args.push('-H', k + ': ' + headers[k]);
    const ch = cookieHeaderFor(url);
    if (ch) args.push('-H', 'Cookie: ' + ch);
    if (body && (method || 'GET').toUpperCase() !== 'GET') args.push('--data', String(body));
    let raw;
    try {
      raw = execFileSync('curl', args, { maxBuffer: 20 * 1024 * 1024, timeout: 25000 });
    } catch (e) {
      raw = e.stdout || Buffer.alloc(0);
      last.header = String(e.stderr || '');
    }
    const txt = raw.toString('utf-8');
    const idx = txt.indexOf('\r\n\r\n');
    const head = idx >= 0 ? txt.slice(0, idx) : '';
    const bdy = idx >= 0 ? txt.slice(idx + 4) : txt;
    last = { url, body: bdy, header: head, cookie: cookieHeaderFor(url) };
    const loc = head.match(/location:\s*(\S+)/i);
    if (loc && i < 5) { url = new URL(loc[1], url).toString(); continue; }
    break;
  }
  // 把 curl 写入的 cookie 合并进内存 jar
  ingestCookieFile(cj);
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) {}
  return last;
}

// ---------------- java 对象（对齐 AnalyzeUrl 暴露给 JS 的 API） ----------------
function makeJava(baseUrl, defaultHeaders) {
  return {
    ajax(input) {
      let u, m = 'GET', b = null, hd = Object.assign({}, defaultHeaders);
      if (typeof input === 'string') u = input;
      else if (input && typeof input === 'object') {
        u = input.url; m = input.method || 'GET'; b = input.body;
        if (input.headers) Object.assign(hd, input.headers);
      }
      if (!u) return '';
      // 真机 java.ajax 返回响应正文字符串(okhttp String), 非对象
      return doRequestSync(u, m, b, hd, baseUrl).body;
    },
    ajaxAll(arr) {
      if (typeof arr === 'string') arr = arr.split(',').map(s => s.trim()).filter(Boolean);
      if (!Array.isArray(arr)) arr = [arr];
      return arr.map(x => this.ajax(x));
    },
    getBaseUrl() { return baseUrl; },
    getCookie(url) { return cookieHeaderFor(url || baseUrl); },
    setCookie(url, cookieStr) { applyCookieString(cookieStr, url || baseUrl); },
    saveCookie() { return jarToString(); },   // 真机持久化到 DB；工具侧由 Python 并入 Session
    // ── 以下 API 名与签名对齐真机 JsExtensions 接口声明 ──
    get(u) { return this.ajax(u); },                    // 真机 java.get = 同步 GET 取正文
    connect(u, headers) {                               // 返回 StrResponse 对象(真机 3.25 仅 getBody())
      let hd = Object.assign({}, defaultHeaders);
      if (typeof headers === 'string' && headers.trim()) {
        try { Object.assign(hd, JSON.parse(headers)); } catch (e) {}
      } else if (headers && typeof headers === 'object') Object.assign(hd, headers);
      const r = doRequestSync(u, 'GET', null, hd, baseUrl);
      return makeStrResponse(r);
    },
    post(u, body, headers) {                            // 返回 StrResponse 对象(真机 3.25 仅 getBody())
      let hd = Object.assign({}, defaultHeaders);
      if (typeof headers === 'string' && headers.trim()) {
        try { Object.assign(hd, JSON.parse(headers)); } catch (e) {}
      } else if (headers && typeof headers === 'object') Object.assign(hd, headers);
      const r = doRequestSync(u, 'POST', body, hd, baseUrl);
      return makeStrResponse(r);
    },
    head(u, headers) {
      const r = this.connect(u, headers);
      return r.header;
    },
    // ── 摘要（i1.b/c + p0.K/L: Digester(String) → MessageDigest.getInstance(JCA 名, 大小写不敏感)） ──
    md5Encode(s) { return crypto.createHash('md5').update(csBytes(s, 'UTF-8')).digest('hex'); },
    md5Encode16(s) { return this.md5Encode(s).substring(8, 24); },
    digestHex(data, algorithm) {
      return crypto.createHash(digestName(algorithm)).update(csBytes(data, 'UTF-8')).digest('hex');
    },
    digestBase64Str(data, algorithm) {
      return aB64(crypto.createHash(digestName(algorithm)).update(csBytes(data, 'UTF-8')).digest());
    },
    HMacBase64(data, algorithm, key) {          // p0.a: new HMac(algorithm, key.getBytes(UTF8)).digest(data) → Base64.encodeToString(h, 2)
      return aB64(crypto.createHmac(macName(algorithm), csBytes(key, 'UTF-8')).update(csBytes(data, 'UTF-8')).digest());
    },
    HMacHex(data, algorithm, key) {             // p0.b: digestHex
      return crypto.createHmac(macName(algorithm), csBytes(key, 'UTF-8')).update(csBytes(data, 'UTF-8')).digest('hex');
    },
    // ── 对称加密（p0 + hutool SymmetricCrypto；JS 传 key/iv 均为字符串; iv 空串视同无 IV） ──
    createSymmetricCrypto(transformation, key, iv) {   // p0.C: key/iv = getBytes(UTF-8)
      let keyBuf = Buffer.isBuffer(key) ? key : csBytes(key, 'UTF-8');
      let ivBuf = iv == null ? null : (Buffer.isBuffer(iv) ? iv : csBytes(iv, 'UTF-8'));
      return makeSymmetric(transformation, keyBuf, ivBuf);
    },
    aesEncodeToString(data, key, transformation, iv) {        // BaseSource:150 → p0.l → a.e = decryptStr（3.25 实为解密语义）
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    aesDecodeToString(data, key, transformation, iv) {        // BaseSource:109 → p0.g → a.e
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    aesBase64DecodeToString(data, key, transformation, iv) {  // BaseSource:84 → p0.d → a.e
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    aesEncodeToBase64String(data, key, transformation, iv) {  // BaseSource:134 → p0.j → encryptBase64
      return this.createSymmetricCrypto(transformation, key, iv).encryptBase64(data);
    },
    aesEncodeToByteArray(data, key, transformation, iv) {     // BaseSource:142 → p0.k → encrypt(String) byte[]
      return this.createSymmetricCrypto(transformation, key, iv).encrypt(data);
    },
    aesEncodeToBase64ByteArray(data, key, transformation, iv) { // BaseSource:126 → p0.i
      return csBytes(this.aesEncodeToBase64String(data, key, transformation, iv), 'UTF-8');
    },
    aesDecodeToByteArray(data, key, transformation, iv) {     // BaseSource:101 → p0.f → a.b = decrypt(Base64.decode)
      return this.createSymmetricCrypto(transformation, key, iv).decrypt(data);
    },
    aesBase64DecodeToByteArray(data, key, transformation, iv) { // BaseSource:76 → p0.c → a.b
      return this.createSymmetricCrypto(transformation, key, iv).decrypt(data);
    },
    aesEncodeArgsBase64Str(data, key, mode, padding, iv) {    // p0.h: "AES/mode/padding", key/getUTF8(iv)【无 Base64】
      return makeSymmetric('AES/' + mode + '/' + padding, csBytes(key, 'UTF-8'), csBytes(iv, 'UTF-8')).encryptBase64(data);
    },
    aesDecodeArgsBase64Str(data, key, mode, padding, iv) {    // p0.e: key/iv 均 Base64.decode(x, 2)
      return makeSymmetric('AES/' + mode + '/' + padding, androidB64Dec(String(key), 2), androidB64Dec(String(iv), 2)).decryptStr(data);
    },
    desEncodeToString(data, key, transformation, iv) {        // BaseSource:245 → p0.J → a.e（解密语义）
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    desDecodeToString(data, key, transformation, iv) {        // BaseSource:229 → p0.H → a.e
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    desBase64DecodeToString(data, key, transformation, iv) {  // BaseSource:221 → p0.G → a.e
      return this.createSymmetricCrypto(transformation, key, iv).decryptStr(data);
    },
    desEncodeToBase64String(data, key, transformation, iv) {  // BaseSource:237 → p0.I → encryptBase64
      return this.createSymmetricCrypto(transformation, key, iv).encryptBase64(data);
    },
    tripleDESEncodeBase64Str(data, key, mode, padding, iv) {  // p0.K0: key 原样 getBytes(UTF8) + encryptBase64
      return makeSymmetric('DESede/' + mode + '/' + padding, csBytes(key, 'UTF-8'), csBytes(iv, 'UTF-8')).encryptBase64(data);
    },
    tripleDESEncodeArgsBase64Str(data, key, mode, padding, iv) { // p0.J0: Base64.decode(key,2) + getUTF8(iv)
      return makeSymmetric('DESede/' + mode + '/' + padding, androidB64Dec(String(key), 2), csBytes(iv, 'UTF-8')).encryptBase64(data);
    },
    tripleDESDecodeStr(data, key, mode, padding, iv) {        // p0.I0: key 原样 + a.e
      return makeSymmetric('DESede/' + mode + '/' + padding, csBytes(key, 'UTF-8'), csBytes(iv, 'UTF-8')).decryptStr(data);
    },
    tripleDESDecodeArgsBase64Str(data, key, mode, padding, iv) { // p0.H0: Base64.decode(key,2) + getUTF8(iv) + a.e
      return makeSymmetric('DESede/' + mode + '/' + padding, androidB64Dec(String(key), 2), csBytes(iv, 'UTF-8')).decryptStr(data);
    },
    randomUUID() {
      try { return crypto.randomUUID(); } catch (e) { return ''; }
    },
    timeFormat(ms) {
      const d = new Date(Number(ms) || Date.now());
      const p = (n) => String(n).padStart(2, '0');
      return d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate()) + ' ' +
             p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    },
    timeFormatUTC(ms, format, sh) {
      const d = new Date((Number(ms) || Date.now()) + (Number(sh) || 0) * 3600000);
      return this.timeFormat(d.getTime());
    },
    // ── hex（BaseSource:605-615 → hutool HexUtil；UTF-8 进出） ──
    hexEncodeToString(s) { return csBytes(s, 'UTF-8').toString('hex'); },
    hexDecodeToString(s) { return csStr(Buffer.from(String(s), 'hex'), 'UTF-8'); },
    hexDecodeToByteArray(s) { return Buffer.from(String(s), 'hex'); },
    strToBytes(s, charset) { return csBytes(s, charset || 'UTF-8'); },            // p0.y0/z0
    bytesToStr(b, charset) { return csStr(b, charset || 'UTF-8'); },              // p0.u/v
    androidId() { return ''; },                          // 真机设备相关, 工具无设备
    log(...a) { try { require('fs').appendFileSync('/tmp/legado_js_log.txt', a.map(String).join(' ') + '\n'); } catch (e) {} return ''; },
    toast() { return ''; },
    longToast() { return ''; },
    cacheFile(u, saveTime) { const r = this.ajax(u); return r; },
    getSource() { return { bookSourceUrl: baseUrl, bookSourceName: '' }; },
    getWebViewUA() { return (defaultHeaders && defaultHeaders['User-Agent']) || ''; },
    // ── p0.M0: str.getBytes(GBK) → 再以 UTF-8 解读成字符串（GBK 高位字节按 UTF-8 解码，非法序列变 U+FFFD，真机同） ──
    utf8ToGbk(s) { return csStr(csBytes(s, 'GBK'), 'UTF-8'); },
    // ── p0.P: URLEncoder.encode(s, enc)（j$.net.URLEncoder = java.net.URLEncoder form 编码, 失败返回 ""） ──
    encodeURI(s, enc) { return formEncode(s, enc || 'UTF-8'); },
    decodeURI(s) { try { return decodeURIComponent(String(s).replace(/\+/g, '%20')); } catch (e) { return String(s); } },
    // ── base64（p0.o/p/t/s/q/r + BaseSource default） ──
    base64Decode(s, flagsOrCharset) { // (str) | (str, int flags) | (str, charset)
      if (flagsOrCharset === undefined) return csStr(androidB64Dec(String(s), 0), 'UTF-8');
      if (typeof flagsOrCharset === 'string') return csStr(androidB64Dec(String(s), 0), flagsOrCharset);
      return csStr(androidB64Dec(String(s), Number(flagsOrCharset) || 0), 'UTF-8');
    },
    base64DecodeToByteArray(s, flags) {
      if (flags === undefined) return androidB64Dec(String(s), 0);
      return androidB64Dec(String(s), Number(flags) || 0);
    },
    base64Encode(s, flags) { return androidB64Enc(csBytes(s, 'UTF-8'), flags === undefined ? 2 : (Number(flags) || 0)); }, // 单参 = encodeToString(bytes, 2)
    // ── 文件/归档/工具类（JsExtensions 接口；DefaultImpls→p0 实证） ──
    downloadFile(u, savePath) {                        // 真机落地到下载目录并返回绝对路径；lint 落到临时文件
      try {
        const r = doRequestSync(u, 'GET', null, defaultHeaders, baseUrl);
        if (!r || r.body == null) return '';
        const fp = (typeof savePath === 'string' && savePath) ? savePath
          : path.join(os.tmpdir(), 'legado_dl_' + Date.now());
        fs.mkdirSync(path.dirname(fp), { recursive: true });
        fs.writeFileSync(fp, r.body, 'binary');
        return fp;
      } catch (e) { return ''; }
    },
    deleteFile(p) {
      try { fs.unlinkSync(p); return true; }
      catch (e) { return false; }
    },
    getFile(p) {                                        // 真机 java.io.File；lint 返回轻量 File 包装避免方法调用崩溃
      const ap = path.resolve(String(p || ''));
      return {
        getAbsolutePath: () => ap,
        getPath: () => ap,
        getName: () => path.basename(ap),
        exists: () => { try { fs.accessSync(ap); return true; } catch (e) { return false; } },
        isDirectory: () => { try { return fs.statSync(ap).isDirectory(); } catch (e) { return false; } },
        listFiles: () => { try { return fs.readdirSync(ap); } catch (e) { return []; } },
        toString: () => ap,
      };
    },
    getTxtInFolder(folder) {                            // 真机列出目录内 .txt 文件（绝对路径换行连接）
      try {
        const files = fs.readdirSync(folder).filter(f => f.toLowerCase().endsWith('.txt'));
        return files.map(f => path.join(path.resolve(folder), f)).join('\n');
      } catch (e) { return ''; }
    },
    htmlFormat(html) {                                   // 真机 jsoup 重新格式化；无头做轻量缩进
      try { return formatHtml(String(html || '')); } catch (e) { return String(html || ''); }
    },
    getZipStringContent(zipPath, entryName, charset) { return _readEntry('unzip', ['-p', zipPath, entryName], charset || 'UTF-8', false); },
    getZipByteArrayContent(zipPath, entryName) { return _readEntry('unzip', ['-p', zipPath, entryName], 'UTF-8', true); },
    get7zStringContent(zipPath, entryName, charset) { return ''; },   // 本环境无 7z CLI，离线不可读（文档标注未对齐）
    get7zByteArrayContent(zipPath, entryName) { return ''; },
    getRarStringContent(zipPath, entryName, charset) { return ''; },  // 本环境无 rar 解压，离线不可读
    getRarByteArrayContent(zipPath, entryName) { return ''; },
    unzipFile(p) {                                       // 返回解压目录绝对路径；失败返回空
      try { return _extractZip(p, p.replace(/\.(zip|ZIP)$/, '') + '_unzip'); }
      catch (e) { return ''; }
    },
    un7zFile(p) { return ''; },                          // 无 7z CLI，未对齐
    unrarFile(p) { return ''; },                         // 无 rar 解压，未对齐
    unArchiveFile(p) {                                   // 自动识别归档：zip 走 unzip，7z/rar 离线未对齐
      try {
        if (/\.(zip|ZIP)$/.test(p)) return _extractZip(p, p.replace(/\.(zip|ZIP)$/, '') + '_unzip');
        return '';
      } catch (e) { return ''; }
    },
    importScript(name) { return ''; },                   // 真机从书源脚本目录加载；无头不支持
    s2t(s) { return String(s == null ? '' : s); },       // opencc 未打包，原样返回（标注未对齐）
    t2s(s) { return String(s == null ? '' : s); },
    toURL(u, base) { try { return new URL(String(u), base || baseUrl || undefined).toString(); } catch (e) { return String(u); } },
    // ── 无头环境不支持（GUI / TTF 反爬 / 非对称签名 / toNumChapter 正则未实证）──
    webView() { return null; },
    webViewGetSource() { return null; },
    webViewGetOverrideUrl() { return null; },
    startBrowser() { return null; },
    startBrowserAwait() { return null; },
    getVerificationCode() { return null; },
    queryTTF() { return null; },
    queryBase64TTF() { return null; },
    replaceFont(s) { return String(s == null ? '' : s); },   // 无 TTF 数据，原样返回
    createSign() { return null; },
    createAsymmetricCrypto() { return null; },
    toNumChapter(s) { return String(s == null ? '' : s); },   // t6 正则未在 dex 定位，未实证，原样返回
    md5() { return ''; },
    time() { return Date.now(); },
  };
}

// ---------------- 主流程 ----------------
const vm = require('vm');

// 对齐 Rhino eval 语义: 返回【最后一个表达式语句】的值(completion value)。
// vm.runInContext 原生具备该语义; 含顶层 return 的脚本(常见于 loginCheckJs)回退 IIFE 包裹。
function runRhinoStyle(code, sb) {
  const ctx = vm.createContext(sb);
  try {
    return vm.runInContext(code, ctx, { timeout: 30000, displayErrors: true });
  } catch (e) {
    // 注意: vm 抛的 SyntaxError 来自另一个 realm, instanceof 判不出来, 用 e.name
    if (e && (e.name === 'SyntaxError' || e instanceof SyntaxError)) {
      return (new Function('java', 'result', 'source', 'baseUrl', 'cookie', 'key', 'page',
        'return (function(){' + code + '\n})();'))(
        sb.java, sb.result, sb.source, sb.baseUrl, sb.cookie, sb.key, sb.page);
    }
    throw e;
  }
}

function main() {
  let input = '';
  process.stdin.on('data', d => input += d);
  process.stdin.on('end', () => {
    let cfg;
    try { cfg = JSON.parse(input); } catch (e) {
      process.stdout.write(JSON.stringify({ error: 'JSON parse: ' + e })); return;
    }
    const baseUrl = cfg.baseUrl || '';
    const headers = cfg.headers || {};
    // 测试通道：{"__eval__": "java.digestHex('abc','MD5')"} → 直接返回 completion value，不发请求
    if (typeof cfg.__eval__ === 'string') {
      applyCookieString(cfg.cookie, baseUrl);
      const java = makeJava(baseUrl, headers);
      const sb = { java, result: { url: '', body: '', header: '', cookie: '' },
                   source: { bookSourceUrl: baseUrl }, baseUrl, cookie: jarToString(),
                   key: '', page: '1' };
      try {
        const ret = runRhinoStyle(cfg.__eval__, sb);
        let txt;
        if (Buffer.isBuffer(ret)) txt = 'BUF:' + ret.toString('hex');
        else if (ret && typeof ret === 'object') txt = JSON.stringify(ret);
        else txt = String(ret);
        process.stdout.write(JSON.stringify({ eval: txt, error: '' }));
      } catch (e) {
        process.stdout.write(JSON.stringify({ eval: '', error: String(e && e.message ? e.message : e) }));
      }
      return;
    }
    const js = cfg.js || '';
    applyCookieString(cfg.cookie, baseUrl);
    const response = {
      url: (cfg.response && cfg.response.url) || '',
      body: (cfg.response && cfg.response.body) || '',
      header: (cfg.response && cfg.response.header) || '',
      cookie: cookieHeaderFor((cfg.response && cfg.response.url) || baseUrl),
    };
    const java = makeJava(baseUrl, headers);
    let out = { cookie: '', body: response.body, error: '' };
    try {
      if (js.trim()) {
        // 真机 3.25 绑定语义(反编译实证):
        //   result = StrResponse —— 只有 getBody(), 无 body()(k.smali:148/158)
        //   cookie = CookieStore 对象 —— 有 setCookie(url,"k=v") / getCookie(url)
        const sb = { java, result: makeStrResponse(response), source: { bookSourceUrl: baseUrl },
                     baseUrl,
                     cookie: {
                       setCookie: (u, s) => {
                         applyCookieString(String(s == null ? '' : s), u || baseUrl);
                         return true;
                       },
                       getCookie: (u) => cookieHeaderFor(u || baseUrl),
                       toString: () => jarToString(),
                     },
                     key: cfg.key !== undefined ? String(cfg.key) : '',
                     page: String(cfg.page || 1) };
        const ret = runRhinoStyle(js, sb);
        if (ret && typeof ret === 'object') {
          if (typeof ret.body === 'string') out.body = ret.body;
          else if (typeof ret.getBody === 'function') out.body = String(ret.getBody());
        } else if (typeof ret === 'string') out.body = ret;
      }
    } catch (e) {
      out.error = String(e && e.message ? e.message : e);
    }
    out.cookie = jarToString();
    process.stdout.write(JSON.stringify(out));
  });
}
main();
