import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.TextNode;
import org.jsoup.select.Elements;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * 真机等价求值助手: 用真 org.jsoup 复刻 Legado 3.25 默认 JSOUP 引擎的 `@` 层级语义,
 * 对单条规则求值并返回提取文本。供 Python 校验器在 bs4 无法等价建模的扩展属性选择器
 * (~=/?= 等 Jsoup 原生操作符) 时调用, 保证「校验结果 == 真机」。
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
        // default: 整段当 CSS, 真 Jsoup 原生解析(含未加引号的属性值、~=/?= 等扩展操作符)
        res.addAll(el.select(before));
        return res;
    }

    // ── 对齐 APK AnalyzeByJSoup$ElementsSingle.findIndexSet (本地 smali 285-1150 行实证) ──
    // 倒序扫描规则串: 末尾数字前若是 '.'(0x2e)/'!'(0x21) 分隔 -> indexDefault; ':' 允许多重;
    // 末字符 ']'(0x5d) 走方括号 indexes(IntRange) 路径; 无数字分隔 -> 整段即 CSS。
    static final class IndexSet {
        char split = ' ';
        String beforeRule = "";
        List<Integer> indexDefault = new ArrayList<>(); // "tag.N" 0 基索引, 负数倒数
        List<Object> indexes = new ArrayList<>();        // "tag[N]" / "[N:M]" / "[N,M]"
    }
    static IndexSet findIndexSet(String rule) {
        IndexSet r = new IndexSet();
        String s = rule.trim();
        int n = s.length();
        if (n > 0 && s.charAt(n-1) == ']') {
            // 方括号路径(近似还原): 从右往左解析数字/'-'/':'/','/[', 收集索引与范围
            List<Integer> nums = new ArrayList<>();
            StringBuilder cur = new StringBuilder();
            boolean neg = false;
            for (int i = n-2; i >= 0; i--) {
                char c = s.charAt(i);
                if (c >= '0' && c <= '9') { cur.insert(0, c); continue; }
                if (c == '-') { neg = true; continue; }
                if (c == '[') {
                    if (cur.length() > 0) { nums.add(neg ? -Integer.parseInt(cur.toString()) : Integer.parseInt(cur.toString())); }
                    r.indexes.addAll(nums);
                    r.beforeRule = s.substring(0, i);
                    return r;
                }
                if (c == ':' || c == ',') {
                    if (cur.length() > 0) { nums.add(neg ? -Integer.parseInt(cur.toString()) : Integer.parseInt(cur.toString())); }
                    cur.setLength(0); neg = false;
                    continue;
                }
                break;
            }
            // 结构异常时按普通 CSS 兜底
            r.beforeRule = s;
            return r;
        }
        // 点号/感叹号路径: 从右往左收数字, 遇 '.' / '!' / ':' 收尾
        StringBuilder num = new StringBuilder();
        boolean neg = false;
        for (int i = n-1; i >= 0; i--) {
            char c = s.charAt(i);
            if (c >= '0' && c <= '9') { num.insert(0, c); continue; }
            if (c == '-') { neg = true; continue; }
            if (c == ' ' || c == '\t') { continue; }
            if (c == '.' || c == '!' || c == ':') {
                if (num.length() > 0) {
                    int v = Integer.parseInt(num.toString());
                    r.indexDefault.add(neg ? -v : v);
                    if (c == ':') { num.setLength(0); neg = false; continue; }
                    r.split = c;
                    r.beforeRule = s.substring(0, i);
                    return r;
                }
                r.split = ' ';
                r.beforeRule = s;
                return r;
            }
            r.split = ' ';
            r.beforeRule = s;
            return r;
        }
        r.split = ' ';
        r.beforeRule = s;
        return r;
    }

    // 对齐 getElementsSingle 索引应用: LinkedHashSet 倒序, 0 基正索引 / 倒序负索引, 越界忽略;
    // 无索引段(indexDefault 与 indexes 均空)原样返回
    static List<Element> applyIndexSet(List<Element> list, IndexSet is) {
        if (is.indexDefault.isEmpty() && is.indexes.isEmpty()) return list;
        LinkedHashSet<Integer> idx = new LinkedHashSet<>();
        for (int i = is.indexDefault.size()-1; i >= 0; i--) {
            int v = is.indexDefault.get(i);
            if (v >= 0 && v < list.size()) idx.add(v);
            else if (v < 0 && list.size() >= -v) idx.add(list.size()+v);
        }
        for (Object o : is.indexes) {
            if (o instanceof Integer) { int v = (Integer) o; if (v >= 0 && v < list.size()) idx.add(v); }
        }
        List<Element> out = new ArrayList<>();
        for (int i : idx) out.add(list.get(i));
        return out;
    }

    // 对齐 APK AnalyzeByJSoup.getResultLast 的最后一段取值语义（真 Jsoup 实证）：
    //   text/ownText: 逐元素取文本, 空串跳过, 不去重
    //   textNodes:   逐元素 textNodes, 空串跳过, 不去重
    //   all:         整个匹配集 outerHtml(不移除), 直接加入
    //   html:        整个匹配集移除 script/style 后 outerHtml, 空跳过
    //   @attr/属性名(elelse): attr(type), 空串跳过, contains 去重
    //   (属性不存在时 Jsoup attr() 返回 "" —— 真机即跳过, 不回退取 text)
    static List<String> extract(List<Element> els, String seg) {
        List<String> out = new ArrayList<>();
        String t = seg.startsWith("@") ? seg.substring(1) : seg;
        if (t.equals("text")) {
            for (Element e : els) { String v = e.text(); if (!v.isEmpty()) out.add(v); }
        } else if (t.equals("ownText")) {
            for (Element e : els) { String v = e.ownText(); if (!v.isEmpty()) out.add(v); }
        } else if (t.equals("textNodes")) {
            for (Element e : els) for (TextNode n : e.textNodes()) { String v = n.text(); if (!v.isEmpty()) out.add(v); }
        } else if (t.equals("all")) {
            StringBuilder sb = new StringBuilder();
            for (Element e : els) sb.append(e.outerHtml());
            out.add(sb.toString());
        } else if (t.equals("html")) {
            StringBuilder sb = new StringBuilder();
            for (Element e : els) { Element c = e.clone(); c.select("script").remove(); c.select("style").remove(); sb.append(c.outerHtml()); }
            if (sb.length() > 0) out.add(sb.toString());
        } else {
            for (Element e : els) { String v = e.attr(t); if (!v.isEmpty() && !out.contains(v)) out.add(v); }
        }
        return out;
    }

    static List<String> analyze(Document doc, String rule) {
        boolean rev = rule.startsWith("-");
        String core = rev ? rule.substring(1) : rule;
        if (core.startsWith("@css:")) core = core.substring(5); // 剥离 3.x CSS DSL 前缀
        String sel = core, regexPart = null, replacement = "";
        int h1 = core.indexOf("##");
        if (h1 >= 0) {
            sel = core.substring(0, h1);
            String rest = core.substring(h1+2);
            int h2 = rest.indexOf("##");
            if (h2 >= 0) { regexPart = rest.substring(0, h2); replacement = rest.substring(h2+2); }
            else { regexPart = rest; }
        }
        List<String> segs = splitAt(sel);
        List<Element> current = new ArrayList<>(); current.add(doc);
        List<String> collected = new ArrayList<>();
        for (int i=0; i<segs.size(); i++) {
            String s = segs.get(i);
            IndexSet is = findIndexSet(s);
            boolean isLast = (i == segs.size()-1);
            if (isLast) { collected.addAll(extract(current, is.beforeRule)); break; }
            List<Element> next = new ArrayList<>();
            for (Element el : current) next.addAll(jsoupSingle(el, is.beforeRule));
            next = applyIndexSet(next, is);
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
        if (core.startsWith("@css:")) core = core.substring(5); // 剥离 3.x CSS DSL 前缀
        String sel = core, regexPart = null, replacement = "";
        int h1 = core.indexOf("##");
        if (h1 >= 0) {
            sel = core.substring(0, h1);
            String rest = core.substring(h1+2);
            int h2 = rest.indexOf("##");
            if (h2 >= 0) { regexPart = rest.substring(0, h2); replacement = rest.substring(h2+2); }
            else { regexPart = rest; }
        }
        List<String> segs = splitAt(sel);
        List<Element> current = new ArrayList<>(); current.add(root);
        List<String> collected = new ArrayList<>();
        for (int i=0; i<segs.size(); i++) {
            String s = segs.get(i);
            IndexSet is = findIndexSet(s);
            boolean isLast = (i == segs.size()-1);
            if (isLast) { collected.addAll(extract(current, is.beforeRule)); break; }
            List<Element> next = new ArrayList<>();
            for (Element el : current) next.addAll(jsoupSingle(el, is.beforeRule));
            next = applyIndexSet(next, is);
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
        if (core.startsWith("@css:")) core = core.substring(5); // 剥离 3.x CSS DSL 前缀
        String sel = core;
        int h = core.indexOf("##");
        if (h >= 0) sel = core.substring(0, h); // 列表规则忽略 ## 替换
        List<String> segs = splitAt(sel);
        List<Element> current = new ArrayList<>(); current.add(doc);
        for (int i=0; i<segs.size(); i++) {
            String s = segs.get(i);
            IndexSet is = findIndexSet(s);
            boolean isLast = (i == segs.size()-1);
            List<Element> next = new ArrayList<>();
            if (isLast) {
                for (Element el : current) next.addAll(jsoupSingle(el, is.beforeRule));
                next = applyIndexSet(next, is);
                List<String> out = new ArrayList<>();
                for (Element e: next) out.add(e.outerHtml());
                return out;
            }
            for (Element el : current) next.addAll(jsoupSingle(el, is.beforeRule));
            next = applyIndexSet(next, is);
            current = next;
            if (current.isEmpty()) break;
        }
        return new ArrayList<>();
    }

    // 对齐 RuleAnalyzer.splitRule("@"): 括号 [ ] / ( ) 与引号内的 '@' 受保护;
    // 另对齐 RuleAnalyzer.trim(): 规则前置的 '@' 与空白符先修剪(真机元素链式前置赘余处理)
    static List<String> splitAt(String s) {
        int b = 0;
        while (b < s.length() && (s.charAt(b) == '@' || s.charAt(b) <= ' ')) b++;
        s = s.substring(b);
        List<String> out = new ArrayList<>();
        int start = 0, depth = 0;
        boolean inS = false, inD = false;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\'' && !inD) inS = !inS;
            else if (c == '"' && !inS) inD = !inD;
            else if (!inS && !inD) {
                if (c == '\\') { i++; continue; }
                if (c == '[' || c == '(') depth++;
                else if (c == ']' || c == ')') depth--;
                else if (depth == 0 && c == '@') { out.add(s.substring(start, i)); start = i + 1; }
            }
        }
        out.add(s.substring(start));
        return out;
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
            vals = analyzeRoot(root, a[1]);
        }
        else vals = analyze(doc, a[1]);
        Base64.Encoder enc = Base64.getEncoder();
        for (String v : vals) {
            System.out.println(enc.encodeToString(v.getBytes(StandardCharsets.UTF_8)));
        }
    }
}
