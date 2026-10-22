# Legado 书源排错与实战经验（多站案例集）

> 配套文档：`Legado_3.25_书源编写参考.md`（APK 逆向出的 `java.xxx`/字段/规则表）、`Legado_3.25_方法补集.md`（AES/压缩包/dex 真值表）。
> **本文件补「实战层」空白**：API 文档告诉你*有什么方法*，本文件告诉你*遇到「搜不到/列表空/正文乱/翻页失效」时怎么排*，全部来自真实修复过的站点。
> 修复过的样本源：兔九三(tu93)、74小说网(74xswz)、3Q中文网(3qdus)、菠萝猫(boluomao)、速读谷(suduguu)、黄金屋(huangjinwu)。

---

## 0. 排错总原则（先取证，再改规则）

1. **先抓真实页面再写规则**：用 `curl -A "<UA>"` 或 Playwright 抓首页/搜索/详情/目录/正文五类样本，确认结构与线上一致，再动手。站点常改版（结构、域名、加密），凭记忆写规则必翻车。
2. **区分「搜不到」和「解析错」**：
   - 返回 0 条 / 跳转到奇怪域名 → 多半是**请求层**问题（域名、重定向、POST/GTT、参数、UA、验证码墙），不是选择器问题。
   - 有列表但字段错位 → 才是**选择器/字段**问题。
3. **真机/本地双验证**：本地用 BeautifulSoup 复刻 Jsoup CSS 语义验证选择器命中，再用 `js_layer_check.py`（Node 跑 `<js>`）与 `validate_booksource.py` 校验。最后务必真机点一遍。
4. **改一处验一处**：不要一次性大改，否则不知道哪步引入新问题。

---

## 1. 案例 A：兔九三 —— 域名迁移把搜索打空（最典型的「0 结果」根因）

**症状**：书源 `bookSourceUrl=https://www.tu93.org`，搜索返回 0 条，或被重定向到垃圾站。

**根因链**（一环扣一环）：
1. 旧域名 `tu93.org` **301 跳转到 `tu93.xyz`**（Cloudflare 托管）。
2. Legado 跟随 301 时，OkHttp 会把 **POST 退化成 GET**。
3. 站点对「无效搜索」（GET 无 body / 缺 keyword / 空 keyword）不做 404，而是 **302 随机重定向**到垃圾站（如 `m.xhwx8.com`）或站内随机页。
4. 结果：所有搜索请求先吃 301、再吃 302，列表永远 0 条。

**修复**：`bookSourceUrl` / `bookUrlPattern` 直接改成新域名 `tu93.xyz`。改完用 curl 实测 `POST /search` 带 `keyword=X` 即返回结果（实测 107978 条），结构正常。

**衍生修复点（同一次改版暴露的）**：
- 发现页 `table.mytable tr` 无 `<tbody>`，原规则 `tbody tr!0` 失效 → 改为 `table.mytable tr!0`。
- 封面域名 `statics.tu93.org` DNS 已死 → 封面改为按书籍 URL 用 JS 计算：`img.tu93.xyz/{id前三位||0}/{id}/{id}s.jpg`（有封面书 200，无封面书 404 属正常）。
- 详情页信息走 `og:` meta：`[property$=book_name]@content` 等（`$=` 是「后缀匹配」属性选择器）。
- 原 `ruleContent.replaceRegex` 是 3.25 **死字段**（写了不执行）→ 净化移入 `content` 的 `<js>`。
- 原 `nextContentUrl` 用 base64+数组重排算下一页，实测是误导 → 删掉，目录导航交给 `ruleToc.chapterList`（本章站每章一页，靠 TOC 列表跳章即可）。

> ⚠️ **关键陷阱**：本类「旧域名 301」问题在任意老书源上都可能出现。书源突然全站 0 结果，第一反应应是 `curl -I` 看域名是否 301。

---

## 2. 案例 B：74小说网 —— 站点自身没搜索 + AES 加密目录

**症状**：搜索无结果（不是规则错，是站点压根没搜索框）；目录拿不到完整章节。

**修复手法**：
- **站点无搜索 → 中继 `@js`**：搜索框 `onclick` 直接跳第三方中继（`rrssk`），所以 `searchUrl` 写成 `<js>` 调用 `java.ajax` 走中继接口，而非本站 `/search`。
- **目录 JS 重建**：书籍页目录被分在两个容器（`.listData` 等），且章节 URL 形如 `/book/{id}-{n}.html`，用纯选择器拼不齐。于是 `ruleToc.chapterList` 用 `<js>`：
  - 正则抽 `articleid`（或退而从 `og:url` 取 book id）；
  - 扫全页 `/book/{id}-(\d+)\html` 找最大章节号 `maxN`；
  - 合并两个容器里的 `<a>` 重建完整列表。
- **AES 加密接口**：该站部分接口用 `java.aesEncodeToBase64String(json, KEY, 'AES/CBC/PKCS5Padding', IV)` 与服务端对齐（参数顺序固定 `data,key,transformation,iv`，见方法补集）。

> 经验：遇到「目录少一半/章节号对不上」，优先看是不是站点把目录拆了容器或做了加密，纯选择器救不了就上 JS 重建。

---

## 3. 案例 C：菠萝猫 / 3Q中文网 —— GoEdge WAF 验证码墙

**症状**：请求被挡，返回带 `GOEDGE_WAF_CAPTCHA_ID` 的验证码页，书源拿不到内容。

**修复手法**：用 `loginCheckJs`（每次请求后回调）做**双清闭环**：
```js
var b=result.body();
if(b && b.indexOf('GOEDGE_WAF_CAPTCHA_ID')>-1){
  var u=String(result.url());
  var sl=u.indexOf('/',8);
  var dm=(sl>-1)?u.substring(0,sl):'https://www.boluomao1.com';
  // 1. 抠验证码图 URL
  var i=b.indexOf('id="ui-captcha-image"');
  var j=b.indexOf('src="',i); var k=b.indexOf('"',j+5);
  var img=b.substring(j+5,k).split('&amp;').join('&');
  if(img.indexOf('http')!==0){ img=dm+img; }
  // 2. 弹验证码识别（真机会弹 UI 让用户输入）
  var code=java.getVerificationCode(img);
  // 3. 抠 cid 并回传 POST，清掉墙
  var i2=b.indexOf('name="GOEDGE_WAF_CAPTCHA_ID"');
  var j2=b.indexOf('value="',i2); var k2=b.indexOf('"',j2+7);
  var cid=b.substring(j2+7,k2);
  if(code&&cid){
    var body='GOEDGE_WAF_CAPTCHA_ID='+cid+'&GOEDGE_WAF_CAPTCHA_CODE='+code;
    java.post(u, body, {'Content-Type':'application/x-www-form-urlencoded'});
  }
}
result;
```
配合 `enabledCookieJar:true` 让清墙后的 Cookie 被记住，后续请求不再弹。

> 经验：WAF/验证码墙别硬刚逆向，优先 `loginCheckJs + enabledCookieJar + java.getVerificationCode` 走官方识别通道。`pitfalls.md` 铁律 16 也强调：限流/墙优先这套，比在 `searchUrl` 里写死闭环稳。

---

## 4. 案例 D：速读谷 —— GET key 搜索 + 正文分页

**症状**：搜索要用 GET 而非 POST；长正文跨多页，只取一页会缺内容。

**修复手法**：
- **搜索用 GET**：`searchUrl: "/i/sor.aspx?key={{key}},{\"charset\":\"utf-8\"}"`。站点不接受 POST 搜索时，别硬套 POST，看准它真实用的是 GET 还是 POST（`curl` 试两种）。
- **正文分页 `nextContentUrl`**：`ruleContent.nextContentUrl` 填「下一页链接规则」，Legado 会自动把多页正文拼接。配合 `content` 的 `<js>` 各自清洗每页，再合并。
- 同样模式也见于菠萝猫（`ruleContent` 含 `content` + `nextContentUrl` 两个 `<js>`）。

> 经验：正文明显「到某段戛然而止」→ 多半是分页，上 `nextContentUrl`；它和 `ruleToc.nextTocUrl`（目录分页）是两回事，别混。

---

## 4.5. 案例 E：黄金屋 (huangjinwu.org) —— Cloudflare 按「端点」盾 + `nextTocUrl` 取「尾页」丢章

**症状**：搜索返回 0 条；目录翻 1~2 页后章节数停在某中间值（读者目录 `(1/298)`，但详情页写 `共998章`），后续全丢。

**两根因链（一环扣一环，定位花了三轮）**：

1. **搜索被 CF 五秒盾按「端点」拦截**：全站只有 `/search?keyword=X` 被 Cloudflare 挑战（直连返回"正在检查您的浏览器"空壳），首页/分类/详情/目录/正文/`robots.txt` 全部 200 明文。
   - ⚠️ **纠偏（关键）**：早期误判"残留 `ruleSearch.checkKeyWord` 会过滤掉不含该词的结果→搜索恒 0 条"。经 3.25 反编译实锤：`checkKeyWord` 只是「校验书源用的测试关键字（调试用）」，**不参与真实搜索结果过滤**。搜索恒 0 条的唯一真凶是 `/search` 的 CF 盾；删 checkKeyWord 只是清理调试残留，与 0 条无因果。**技能铁律里绝不能写"checkKeyWord 会过滤结果"**。
   - **修复**：只给 `searchUrl` 内联过盾（**不要**把 `webView` 加到 `chapterUrl`/`bookUrl`，否则每章多等数秒）：`/search?keyword={{key}},{"charset":"utf-8","webView":true,"webWait":12000}`（`webWait` 必须够 CF 放行，默认 ~1000ms 会取空）。
2. **`nextTocUrl` 取到了分页条的「最后一个链接（尾页）」而非「下一页」**：
   - 原 `nextTocUrl: ".page-link:last-child@href"`。分页条 `.page-link` 是一组：首页/上一页/1/2/…/下一页/尾页。`last-child` 取到的是**整条分页里最后一个链接（尾页）**。于是第 1 页→直接跳尾页（如第 10 页）→再翻仍尾页，中间 2~9 页全跳过 ⇒ 998 章只拿到 ~298 章。
   - **修复**：纯 JS 按页码确定性递增（下一页链接优先，否则 `page+1`；末页返回空串让 Legado 自然停止，防回环）。**终止判据必须用"是否还存在下一页"**——本站越界页（`?page=6` 超出实际 5 页）被服务端**钳到末页**而非 404，故"越界判定"失效：
     ```javascript
     @js:(function(){
       var h=''+result, u=''+baseUrl, out='';
       var mm=h.match(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(?:(?!<\/a>)[\s\S]){0,80}?下一页/);
       if(mm&&mm[1]){ out=mm[1]; }
       else {
         var cur=1,max=0,has=false,pm=u.match(/[?&]page=(\d+)/);
         if(pm){ cur=parseInt(pm[1],10)||1; has=true; }
         var nr=/[?&]page=(\d+)/g,v;
         while((v=nr.exec(h))){ var n=parseInt(v[1],10); if(n>max){max=n;} }
         var nx=cur+1;
         if(max>=nx){ out=has ? u.replace(/([?&]page=)\d+/,'$1'+nx)
                               : (u+(u.indexOf('?')>-1?'&':'?')+'page='+nx); }
       }
       return out;
     })()
     ```
   - **铁证**：修复前读者目录 `(1/298)`、详情 `共998章`；修复后真机目录 `(1/998)` 全加载。

**衍生修复点（同一次改版暴露）**：
- 详情/搜索/发现统一走 `og:` meta 与 `.book-card` 系列（`.book-title`/`.book-author`/`.book-desc`/`.book-badge`/`img@src`），`book-author` 用 `##^[\w ]{2}：` 去"作者："前缀。
- 内嵌 JS（`nextTocUrl` 的 `@js:`）交付前必过 `validate_booksource.py` + `js_layer_check.py`，语法错会"本地绿、真机挂"。

> 经验：① **逐入口取证**是分"全站 CF"与"按端点 CF"的唯一办法——只给被墙的入口上 `webView`，别株连其它入口；② `nextTocUrl` 里凡是 `.page-link:last-child` / `:last-of-type` / 含"尾页"字样的选择器，九成是取尾页反模式，应换成「下一页」优先 + JS 页码递增；③ `checkKeyWord` 只是调试关键字，别把它当"过滤器"写进任何铁律。

---

## 5. 可复用片段（直接抄）

**封面计算（按书籍 URL 算 `img.tu93.xyz` 风格，无封面返回空）**：
```js
// 拼在 coverUrl 规则后，result 为书籍 URL 字符串
@js:(function(){
  var u=String(result);
  var m=u.match(/\/book\/(\d+)\.html/);
  if(!m)return '';
  var id=m[1];
  var pre=id.length>3?id.substring(0,id.length-3):'0';
  return 'https://img.tu93.xyz/'+pre+'/'+id+'/'+id+'s.jpg';
})()
```
> 详情页想用 `baseUrl`（当前书 URL）代替 `result` 也可：`var u=baseUrl;`（实时验证 `baseUrl` 在 Legado 里即当前 url）。

**正文去广告（取 `#htmlContent` 内 `<p>`，过滤站尾广告段）**：
```js
<js>(function(){
  var h=String(result);
  var m=h.match(/<div[^>]*id="htmlContent"[^>]*>([\s\S]*?)<\/div>/);
  var inner=m?m[1]:h;
  var ps=inner.match(/<p[^>]*>[\s\S]*?<\/p>/g)||[];
  var out=[];
  for(var i=0;i<ps.length;i++){
    var t=ps[i].replace(/<[^>]+>/g,'').replace(/^\s+|\s+$/g,'');
    if(!t)continue;
    if(/章节缺失|有缺失|请使用其它|提醒您|全网首发|Ｘ更新最快|请来.*看/.test(t))continue;
    out.push(t);
  }
  return out.join('\n');
})()</js>
```
> 注意：`<js>` 规则体**必须用 IIFE 包裹**（`(function(){...})()`），顶层 `return` 在 Rhino 会报 `invalid return`。

**中继搜索骨架（站点无搜索时）**：`searchUrl` 写 `<js>`，内部 `java.ajax` 调第三方/本站隐藏接口，返回 JSON 或 HTML 串。

---

## 6. 铁律清单（踩过的坑）

- **死字段**：`ruleContent.replaceRegex` 在 3.25 不执行，净化只能放 `content` 的 `<js>` 或 `##` 正则。
- **IIFE 包裹**：所有 `<js>` / `@js:` 规则体用 `(function(){...})()`，否则 Rhino 顶层 return 报错。
- **CSS vs XPath**：Legado 用 **Jsoup CSS** 选择器（`.col-md-10`、`table.mytable tr!0`、`[property$=book_name]`）。**只有以 `/` 开头才当 XPath**。
- **`test_parse.py` 局限性**：该工具求值器只认 XPath，会把所有 CSS/属性选择器报 `[ERR] XPath不支持...Invalid expression`——**这是工具局限不是规则错**。验证 CSS 规则请改用 BeautifulSoup 复刻命中，或真机。
- **翻页 `{{page}}`**：`searchUrl` / `exploreUrl` 支持 `{{page}}`，但首页必须是 `page=1`（实测与「无 page」返回一致才安全）；搜索 POST 翻页实测 `keyword=X&page=N` 有效。
- **一个书两个 URL**：部分站详情页同时有数字 id（`/book/628321.html`）和别名 slug（`/book/fpzbzbbjhl.html`），`og:url` 常给 slug；解析用的 `bookUrl`/`baseUrl` 是导航到的数字 id，封面计算要用数字 id。访问数字 id **不会** 301 到 slug。
- **`enabledCookieJar`**：登录态 / 验证码墙 / 限流站必备，记得开。
- **`concurrentRate`**：分页目录/正文/发现的站点**不要**随便设（会把并发强制串行拖慢），限流优先用 CookieJar + loginCheckJs。
- **字段放对组**：`tocUrl` 是 `ruleBookInfo` 的键不是 `ruleToc` 的；放错组的键被 App 静默丢弃还不报错。

---

## 7. 验证工具链（在 `legado-booksource-debug` 技能内）

| 工具 | 用途 | 注意 |
|---|---|---|
| `validate_booksource.py <源.json>` | 字段完整性/死字段检查 | 期望 `ERROR=0`；`NOTE` 多为 JS 语法覆盖提示，非失败 |
| `js_layer_check.py --source <源.json> --url <真实页>` | Node 跑 `<js>` 规则，验证 JS 逻辑 | 不模拟 `baseUrl`/网络 fetch，纯逻辑验证；content 规则喂**章节页** HTML 而非详情页 |
| `test_parse.py --search/--explore/--bookinfo/--toc/--content <样本.html>` | 本地 XPath 命中 | **仅支持 XPath**；CSS 选择器会误报 ERR，属工具局限 |
| 自行 `curl`/`BeautifulSoup` 复刻 | 验证 CSS 选择器命中数与字段映射 | 最可靠的「选择器对不对」判据 |

> 工作流：写规则 → `validate_booksource.py` 过字段 → `js_layer_check.py` 验 JS → BeautifulSoup 验 CSS 命中 → 真机闭环。
