import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * 真机等价求值助手: 用真 org.jsoup 复刻 Legado 3.25 默认 JSOUP 引擎的 `@` 层级语义,
 * 对单条规则求值并返回提取文本。供 Python 校验器在 bs4 无法等价建模时调用:
 *   ~= : Jsoup 原生语义是【正则匹配】(无词边界), bs4/soupsieve 的 ~= 是 CSS 词包含, 无法等价;
 *   ?= : 不是操作符——Jsoup 把 ? 解析进【属性名】, [attr?=val] 恒不命中、不报错, 真机同结果。
 * 两类规则都走真 Jsoup 通道, 保证「校验结果 == 真机」(?= 拿到的是真实的恒空, 而非假装有语义)。
 *
 * 用法: java -cp jsoup-1.17.2.jar:. JsoupRuleEval <html-file> <rule>
 * 输出: 每个提取结果占一行, base64 编码(utf-8), 便于含换行/特殊字符的值安全回传。
 * 异常: 打到 stderr 并以非 0 退出。
 */
public class JsoupRuleEval {
    static Document load(String f) throws Exception {
        return Jsoup.parse(Files.readString(Path.of(f)));
    }

    // 复刻 Legado ElementsSingle.getElementsSingle 的 beforeRule 处理(真 Jsoup 原生行为)
    static List<Element> jsoupSingle(Element el, String before) {
        List<Element> res = new ArrayList<>();
        if (before.isEmpty()) { for (Element c : el.children()) res.add(c); return res; }
        String[] parts = before.split("\\.", 6);
        String typ = parts[0];
        if (typ.equals("children")) { for (Element c: el.children()) res.add(c); return res; }
        if (typ.equals("class")) { if (parts.length>1) res.addAll(el.select("."+parts[1])); return res; }
        if (typ.equals("tag"))   { if (parts.length>1) res.addAll(el.select(parts[1])); return res; }
        if (typ.equals("id"))    { if (parts.length>1) res.addAll(el.select("#"+parts[1])); return res; }
        if (typ.equals("text"))  { if (parts.length>1) res.addAll(el.getElementsContainingOwnText(parts[1])); return res; }
        // default: 整段当 CSS, 真 Jsoup 原生解析(含未加引号的属性值。
        // ~= 是 Jsoup 正则匹配而非 CSS 词包含;
        // ?= 非操作符, ? 被解析进属性名, [attr?=val] 恒不命中)
        res.addAll(el.select(before));
        return res;
    }

    // 只匹配末尾 [数字] 作为元素索引(对齐 Legado findIndexSet 只解 [\d+]);
    // 属性选择器里的 [attr=val] 含 '[' 但非数字索引, 必须原样保留。
    static final java.util.regex.Pattern IDX_PAT = java.util.regex.Pattern.compile("\\[(\\d+)\\]$");
    static String[] stripIndex(String seg) {
        String[] r = {seg, ""};
        java.util.regex.Matcher m = IDX_PAT.matcher(seg);
        if (m.find()) { r[0] = seg.substring(0, m.start()); r[1] = m.group(1); }
        return r;
    }
    static List<Element> applyIndex(List<Element> list, String num) {
        if (num.isEmpty()) return list;
        try { int idx = Integer.parseInt(num);
              if (idx>=0 && idx<list.size()) return List.of(list.get(idx)); }
        catch (Exception e) {}
        return new ArrayList<>();
    }

    static List<String> extract(List<Element> els, String seg) {
        List<String> out = new ArrayList<>();
        if (seg.startsWith("@")) { String a = seg.substring(1); for (Element e: els) out.add(e.attr(a)); return out; }
        if (seg.equals("text")) { for (Element e: els) out.add(e.text()); return out; }
        // 3.25 真机语义(AnalyzeByJSoup.getResultLast): "html" 先删 script/style 再取 outerHtml。
        // 早期本地实现返回 innerHtml 且不删 script —— 与真机不一致, 会让「正文藏在 <script> 里」的站点
        // 本地全绿、真机拿到去壳后的空容器(百草露 2026-10-31 实证: 本地 6088 字符, 真机 127 字符)。
        // 注意: 真机是 **一次性** 把整个 Elements 的 outerHtml 拼成 **单条** 结果
        // (getResultLast 里 textS.add(elements.outerHtml())), 不是逐元素各出一条。
        if (seg.equals("html")) {
            Elements copy = new Elements();
            for (Element e: els) copy.add(e.clone());
            copy.select("script").remove();
            copy.select("style").remove();
            out.add(copy.outerHtml());
            return out;
        }
        // "all" 不删 script/style, 返回 outerHtml —— 需要脚本内容作载体的站点必须用它。
        if (seg.equals("all")) {
            Elements copy = new Elements();
            for (Element e: els) copy.add(e.clone());
            out.add(copy.outerHtml());
            return out;
        }
        for (Element e: els) out.add(e.hasAttr(seg) ? e.attr(seg) : e.text());
        return out;
    }

    static List<String> analyze(Document doc, String rule) {
        boolean rev = rule.startsWith("-");
        String core = rev ? rule.substring(1) : rule;
        String sel = core, regexPart = null, replacement = "";
        int h1 = core.indexOf("##");
        if (h1 >= 0) {
            sel = core.substring(0, h1);
            String rest = core.substring(h1+2);
            int h2 = rest.indexOf("##");
            if (h2 >= 0) { regexPart = rest.substring(0, h2); replacement = rest.substring(h2+2); }
            else { regexPart = rest; }
        }
        String[] segs = sel.split("@");
        List<Element> current = new ArrayList<>(); current.add(doc);
        List<String> collected = new ArrayList<>();
        for (int i=0; i<segs.length; i++) {
            String s = segs[i];
            String[] si = stripIndex(s);
            boolean isLast = (i == segs.length-1);
            if (isLast) { collected.addAll(extract(current, si[0])); break; }
            List<Element> next = new ArrayList<>();
            for (Element el : current) next.addAll(jsoupSingle(el, si[0]));
            next = applyIndex(next, si[1]);
            current = next;
            if (current.isEmpty()) break;
        }
        if (regexPart != null) {
            List<String> out = new ArrayList<>();
            for (String t : collected)
                out.add(regexPart.equals("$") ? replacement : t.replaceAll(regexPart, replacement));
            collected = out;
        }
        if (rev) Collections.reverse(collected);
        return collected;
    }

    // 以列表子元素为根求值(对齐 Legado 对 bookList/chapterList 每个元素的子规则应用):
    // root 是单个容器元素, 规则相对该元素 select/取属性, 而非从 document 根开始。
    static List<String> analyzeRoot(Element root, String rule) {
        boolean rev = rule.startsWith("-");
        String core = rev ? rule.substring(1) : rule;
        String sel = core, regexPart = null, replacement = "";
        int h1 = core.indexOf("##");
        if (h1 >= 0) {
            sel = core.substring(0, h1);
            String rest = core.substring(h1+2);
            int h2 = rest.indexOf("##");
            if (h2 >= 0) { regexPart = rest.substring(0, h2); replacement = rest.substring(h2+2); }
            else { regexPart = rest; }
        }
        String[] segs = sel.split("@");
        List<Element> current = new ArrayList<>(); current.add(root);
        List<String> collected = new ArrayList<>();
        for (int i=0; i<segs.length; i++) {
            String s = segs[i];
            String[] si = stripIndex(s);
            boolean isLast = (i == segs.length-1);
            if (isLast) { collected.addAll(extract(current, si[0])); break; }
            List<Element> next = new ArrayList<>();
            for (Element el : current) next.addAll(jsoupSingle(el, si[0]));
            next = applyIndex(next, si[1]);
            current = next;
            if (current.isEmpty()) break;
        }
        if (regexPart != null) {
            List<String> out = new ArrayList<>();
            for (String t : collected)
                out.add(regexPart.equals("$") ? replacement : t.replaceAll(regexPart, replacement));
            collected = out;
        }
        if (rev) Collections.reverse(collected);
        return collected;
    }

    // 列表容器迭代(对齐 Legado ruleSearch.bookList / ruleToc.chapterList):
    // 返回每个匹配元素的 outerHtml, 供 Python 逐条套用 name/bookUrl 等子规则。
    static List<String> analyzeElems(Document doc, String rule) {
        boolean rev = rule.startsWith("-");
        String core = rev ? rule.substring(1) : rule;
        String sel = core;
        int h = core.indexOf("##");
        if (h >= 0) sel = core.substring(0, h); // 列表规则忽略 ## 替换
        String[] segs = sel.split("@");
        List<Element> current = new ArrayList<>(); current.add(doc);
        for (int i=0; i<segs.length; i++) {
            String s = segs[i];
            String[] si = stripIndex(s);
            boolean isLast = (i == segs.length-1);
            List<Element> next = new ArrayList<>();
            if (isLast) {
                for (Element el : current) next.addAll(jsoupSingle(el, si[0]));
                next = applyIndex(next, si[1]);
                List<String> out = new ArrayList<>();
                for (Element e: next) out.add(e.outerHtml());
                return out;
            }
            for (Element el : current) next.addAll(jsoupSingle(el, si[0]));
            next = applyIndex(next, si[1]);
            current = next;
            if (current.isEmpty()) break;
        }
        return new ArrayList<>();
    }

    static List<String> dedup(List<String> v) {
        List<String> d = new ArrayList<>();
        for (String s: v) if (!d.contains(s)) d.add(s);
        return d;
    }

    public static void main(String[] a) throws Exception {
        if (a.length < 2) { System.err.println("usage: JsoupRuleEval <html-file> <rule> [mode]"); System.exit(2); }
        Document doc = load(a[0]);
        String mode = a.length >= 3 ? a[2] : "text";
        List<String> vals;
        if (mode.equals("elem")) vals = analyzeElems(doc, a[1]);
        else if (mode.equals("elemrule")) {
            Element root = doc.body().children().isEmpty() ? doc : doc.body().child(0);
            vals = dedup(analyzeRoot(root, a[1]));
        }
        else vals = dedup(analyze(doc, a[1]));
        Base64.Encoder enc = Base64.getEncoder();
        for (String v : vals) {
            System.out.println(enc.encodeToString(v.getBytes(StandardCharsets.UTF_8)));
        }
    }
}
