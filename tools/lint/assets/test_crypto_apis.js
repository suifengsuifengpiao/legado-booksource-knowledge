#!/usr/bin/env node
/*
 * test_crypto_apis.js —— java API 加密/编码层单测（对拍独立基准）
 * 基准来源：Python hashlib/hmac/base64 + pycryptodome + openssl（与被测代码零共享实现）
 * 运行：node test_crypto_apis.js
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');

const BRIDGE = path.join(__dirname, 'login_check.js');

function runEval(js) {
  const out = execFileSync('node', ['--openssl-legacy-provider', BRIDGE], {
    input: JSON.stringify({ __eval__: js }),
    maxBuffer: 16 * 1024 * 1024, timeout: 20000,
  });
  return JSON.parse(out.toString());
}

let pass = 0, fail = 0;
const failures = [];

function t(name, js, expect, opts) {
  let got, err = null;
  try {
    const r = runEval(js);
    if (r.error) { err = r.error; got = '<<ERROR: ' + r.error + '>>'; }
    else got = r.eval;
  } catch (e) {
    got = '<<THROW: ' + e.message + '>>';
    err = e.message;
  }
  const norm = s => String(s).replace(/\s+$/, '');
  const ok = (opts && opts.expectError)
    ? got.indexOf('<<ERROR') === 0 || got.indexOf('<<THROW') === 0
    : norm(got) === norm(expect);
  if (ok) {
    pass++;
    // console.log('PASS', name);
  } else {
    fail++;
    failures.push({ name, expect: norm(expect), got: norm(got), js });
  }
}

// ============ 1. digest（基准: Python hashlib） ============
t('md5(abc)', 'java.md5Encode("abc")', '900150983cd24fb0d6963f7d28e17f72');
t('md5Encode16(abc)', 'java.md5Encode16("abc")', '3cd24fb0d6963f7d');
t('digestHex(MD5)', 'java.digestHex("abc","MD5")', '900150983cd24fb0d6963f7d28e17f72');
t('digestHex(SHA-1)', 'java.digestHex("abc","SHA-1")', 'a9993e364706816aba3e25717850c26c9cd0d89d');
t('digestHex(sha-256 小写横线)', 'java.digestHex("abc","sha-256")', 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
t('digestHex(SHA224)', 'java.digestHex("abc","SHA224")', '23097d223405d8228642a477bda255b32aadbce4bda0b3f7e36c9da7');
t('digestHex(SHA384)', 'java.digestHex("abc","SHA384")', 'cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed8086072ba1e7cc2358baeca134c825a7');
t('digestHex(SHA512)', 'java.digestHex("abc","SHA-512")', 'ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f');
t('digestBase64Str(SHA-256)', 'java.digestBase64Str("abc","SHA-256")', 'ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0=');

// ============ 2. HMac（基准: Python hmac） ============
t('HMacBase64(HmacSHA256,key/data)', 'java.HMacBase64("data","HmacSHA256","key")', 'UDH+PZicbRU3oBP6bnOdojRj/a7DtwE32Cjjas4iG9A=');
t('HMacHex(HmacSHA256)', 'java.HMacHex("data","HmacSHA256","key")', '5031fe3d989c6d1537a013fa6e739da23463fdaec3b70137d828e36ace221bd0');
t('HMacBase64(HmacSHA1,中文data)', 'java.HMacBase64("消息中文","HmacSHA1","secret")', 'sNVhQ5LE993zs9t6lnLrVewjLqw=');
t('HMacHex(HmacMD5)', 'java.HMacHex("data","HmacMD5","key")',
   require('crypto').createHmac('md5', 'key').update('data').digest('hex'));

// ============ 3. base64（基准: Android flag=2 ≡ 标准带 padding 无换行） ============
t('base64Encode(Legado)', 'java.base64Encode("Legado")', 'TGVnYWRv');
t('base64Decode(TGVnYWRv)', 'java.base64Decode("TGVnYWRv")', 'Legado');
t('base64Encode(中文)', 'java.base64Encode("中文")', '5Lit5paH');
t('base64Decode(GBK)', 'java.base64Decode("z7XNsw==","GBK")', '系统');
t('base64Decode(s, 2 flags)', 'java.base64Decode("TGVnYWRv", 2)', 'Legado');
t('base64Encode(不换行 >76 字符)', 'java.base64Encode("' + 'x'.repeat(80) + '").indexOf("\\n") >= 0', 'false');
t('base64Encode(DEFAULT 76字符换行)', 'java.base64Encode("' + 'x'.repeat(80) + '", 0).indexOf("\\n") >= 0', 'true');
t('base64DecodeToByteArray', 'java.base64DecodeToByteArray("TGVnYWRv").toString("hex")', '4c656761646f');
t('base64DecodeToByteArray(str,1)', 'java.base64DecodeToByteArray("TGVnYWRv", 1).toString("hex")', '4c656761646f');

// ============ 4. AES（基准: openssl/pycryptodome） ============
const K16 = '1234567890123456';
const K32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ123456';
const IV16 = String.fromCharCode(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16); // 含 \t \n 控制字符，必须转义后插入
const IVLIT = JSON.stringify(IV16);
const ECB = 'd8Lkw35blj1J1S/ED5d7kQ==';
const CBC256 = '6FVN9i/Uuh4FAWTC0wqZnA==';
t('aesEncodeToBase64String ECB', `java.aesEncodeToBase64String("Legado","${K16}","AES/ECB/PKCS5Padding","")`, ECB);
t('aesDecodeToString ECB(decryptStr)', `java.aesDecodeToString("${ECB}","${K16}","AES/ECB/PKCS5Padding","")`, 'Legado');
t('aesBase64DecodeToString 同语义', `java.aesBase64DecodeToString("${ECB}","${K16}","AES/ECB/PKCS5Padding","")`, 'Legado');
t('aesEncodeToString = decryptStr(3.25 语义!)', `java.aesEncodeToString("${ECB}","${K16}","AES/ECB/PKCS5Padding","")`, 'Legado');
t('aesEncodeToByteArray hex', `java.aesEncodeToByteArray("Legado","${K16}","AES/ECB/PKCS5Padding","").toString("hex")`, Buffer.from(ECB, 'base64').toString('hex'));
t('aesEncodeToBase64ByteArray', `java.aesEncodeToBase64ByteArray("Legado","${K16}","AES/ECB/PKCS5Padding","").toString("hex")`, Buffer.from(ECB).toString('hex')); // p0.i = base64文本的 UTF-8 字节
t('aesDecodeToByteArray hex', `java.aesDecodeToByteArray("${ECB}","${K16}","AES/ECB/PKCS5Padding","").toString("hex")`, Buffer.from('Legado').toString('hex'));
t('aesBase64DecodeToByteArray hex', `java.aesBase64DecodeToByteArray("${ECB}","${K16}","AES/ECB/PKCS5Padding","").toString("hex")`, Buffer.from('Legado').toString('hex'));
t('AES-256-CBC 中文+IV', `java.aesEncodeToBase64String("消息中文abc","${K32}","AES/CBC/PKCS5Padding",${IVLIT})`, CBC256);
t('AES-256-CBC 解密还原', `java.aesDecodeToString("${CBC256}","${K32}","AES/CBC/PKCS5Padding",${IVLIT})`, '消息中文abc');

// Args 变体：Encode key=UTF-8 原样 / Decode key=Base64（p0.h vs p0.e 实证差异）
const B64K16 = Buffer.from(K16).toString('base64'); // MTIzNDU2Nzg5MDEyMzQ1Ng==
t('aesEncodeArgsBase64Str(key UTF-8)', `java.aesEncodeArgsBase64Str("Legado","${K16}","ECB","PKCS5Padding","")`, ECB);
t('aesDecodeArgsBase64Str(key Base64)', `java.aesDecodeArgsBase64Str("${ECB}","${B64K16}","ECB","PKCS5Padding","")`, 'Legado');

// ============ 5. DES / 3DES（基准: pycryptodome） ============
const K24 = 'ABCDEFGHIJKLMNOPQRSTUVWX';    // DESede key 24 字节
const K8 = 'ABCDEFGH';                       // DES key 必须 8 字节（DESKeySpec）
const DESIV = 'ABCDEFGH';
const DESEDE = 'rqaycAShQzuoEjaAjR0uqA==';   // DESede/CBC 24B key
const DESCBC = 'XT5PMv1sm5i8ddAIXlfKvA==';   // DES/CBC 8B key
t('desEncodeToBase64String(transform=DES/CBC)', `java.desEncodeToBase64String("hello legado","${K8}","DES/CBC/PKCS5Padding","${DESIV}")`, DESCBC);
t('desDecodeToString(DES/CBC)', `java.desDecodeToString("${DESCBC}","${K8}","DES/CBC/PKCS5Padding","${DESIV}")`, 'hello legado');
t('desEncodeToString = decryptStr(3.25 语义)', `java.desEncodeToString("${DESCBC}","${K8}","DES/CBC/PKCS5Padding","${DESIV}")`, 'hello legado');
t('tripleDESEncodeBase64Str(key UTF-8)', `java.tripleDESEncodeBase64Str("hello legado","${K24}","CBC","PKCS5Padding","${DESIV}")`, DESEDE);
t('tripleDESDecodeStr(key UTF-8)', `java.tripleDESDecodeStr("${DESEDE}","${K24}","CBC","PKCS5Padding","${DESIV}")`, 'hello legado');
t('tripleDESEncodeArgsBase64Str(key Base64)', `java.tripleDESEncodeArgsBase64Str("hello legado","${Buffer.from(K24).toString('base64')}","CBC","PKCS5Padding","${DESIV}")`, DESEDE);
t('tripleDESDecodeArgsBase64Str(key Base64)', `java.tripleDESDecodeArgsBase64Str("${DESEDE}","${Buffer.from(K24).toString('base64')}","CBC","PKCS5Padding","${DESIV}")`, 'hello legado');
t('tripleDES 16B key → K1K2K1 展开', `java.tripleDESEncodeBase64Str("hello","${K16}","ECB","PKCS5Padding","")`, 'qpbpZnxzFqQ=');

// ============ 6. createSymmetricCrypto 对象 ============
t('createSymmetricCrypto.encryptBase64', `java.createSymmetricCrypto("AES/ECB/PKCS5Padding","${K16}","").encryptBase64("Legado")`, ECB);
t('createSymmetricCrypto.decryptStr', `java.createSymmetricCrypto("AES/ECB/PKCS5Padding","${K16}","").decryptStr("${ECB}")`, 'Legado');
t('createSymmetricCrypto.t,key 两参', `java.createSymmetricCrypto("AES/ECB/PKCS5Padding","${K16}").encryptBase64("Legado")`, ECB);

// ============ 7. hex / charset / URLEncoder ============
t('hexEncodeToString(Legado)', 'java.hexEncodeToString("Legado")', '4c656761646f');
t('hexDecodeToString', 'java.hexDecodeToString("4c656761646f")', 'Legado');
t('hexDecodeToByteArray', 'java.hexDecodeToByteArray("4c656761646f").toString("hex")', '4c656761646f');
t('strToBytes(Legado)', 'java.strToBytes("Legado").toString("hex")', '4c656761646f');
t('strToBytes GBK roundtrip', 'java.bytesToStr(java.strToBytes("系统","GBK"),"GBK")', '系统');
t('encodeURI UTF-8(含空格)', 'java.encodeURI("中国 书","UTF-8")', '%E4%B8%AD%E5%9B%BD+%E4%B9%A6');
t('encodeURI GBK', 'java.encodeURI("中国书","GBK")', '%D6%D0%B9%FA%CA%E9');
t('encodeURI 保留字符(.-*_)', 'java.encodeURI("a-b.c*d_e","UTF-8")', 'a-b.c*d_e');
t('utf8ToGbk(中) → U+FFFD×2', 'java.utf8ToGbk("中")', '\uFFFD\uFFFD');

// ============ 8. 错误路径（真机会抛 CryptoException，工具抛错即对齐） ============
t('AES 错误 key 长度抛错', `java.aesEncodeToBase64String("x","short","AES/ECB/PKCS5Padding","")`, '<<ERROR', { expectError: true });
t('不支持的算法抛错', `java.digestHex("x","WHIRLPOOL")`, '<<ERROR', { expectError: true });
t('ECB 缺 IV 不抛错(模式本就无 IV)', `java.aesEncodeToBase64String("x","${K16}","AES/ECB/PKCS5Padding","")`, '5Zk+zP5W9vbM6S3qG0C21w==');

// ============ 汇总 ============
console.log('');
for (const f of failures) {
  console.log('FAIL:', f.name);
  console.log('  js     :', f.js.slice(0, 150));
  console.log('  expect :', f.expect.slice(0, 120));
  console.log('  got    :', f.got.slice(0, 120));
}
console.log('crypto APIs: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
