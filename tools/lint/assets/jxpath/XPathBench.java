import org.seimicrawler.xpath.JXDocument;
import org.seimicrawler.xpath.JXNode;
import java.util.List;
import java.util.ArrayList;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * 真机 XPath 引擎桥接: 复刻 legado 3.25 AnalyzeByXPath 的**单段**语义。
 *   - strToJXDocument 表格包裹预处理: 含 </td> -> 包 <tr>; 含 </tr>|</tbody> -> 包 <table>
 *   - <?xml 开头(trim 后, ignoreCase) -> Jsoup xmlParser, 否则 HTML
 *   - 单段求值走 JXDocument.selN (绝对选择, 对齐 getResult 的 JXDocument 分支)
 *   - 序列化用 JXNode.asString() (对齐 getStringList; 元素->outerHTML, 文本->文本, 属性->值)
 * 组合符 &&/||/%% 由 Python 侧 _eval_combo 负责(已对齐 splitRule), 本桥接只处理单段。
 * 输出: 首行结果数 N, 随后 N 行 base64(UTF-8); compile 模式输出 OK/ERR。
 */
public class XPathBench {
    static String preprocess(String s) {
        if (s.contains("</td>")) {
            s = "<tr>" + s + "</tr>";
        }
        if (s.contains("</tr>") || s.contains("</tbody>")) {
            s = "<table>" + s + "</table>";
        }
        return s;
    }

    static JXDocument makeDoc(String html) {
        String t = html.trim();
        if (t.regionMatches(true, 0, "<?xml", 0, 5)) {
            org.jsoup.nodes.Document d =
                org.jsoup.Jsoup.parse(html, org.jsoup.parser.Parser.xmlParser());
            return JXDocument.create(d);
        }
        return JXDocument.create(preprocess(html));
    }

    /** 单段 selN -> asString 列表 (对齐 getStringList 单段语义). */
    static List<String> evalList(String html, String xpath) throws Exception {
        JXDocument doc = makeDoc(html);
        List<JXNode> nodes = doc.selN(xpath);
        List<String> out = new ArrayList<>();
        for (JXNode n : nodes) out.add(n.asString());
        return out;
    }

    /** 语法校验: 用最小文档触发 antlr 编译, 语法错抛 XpathSyntaxErrorException. */
    static boolean compile(String xpath) {
        try {
            JXDocument.create("<html></html>").selN(xpath);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    public static void main(String[] a) throws Exception {
        String action = a[0];
        if (action.equals("compile")) {
            System.out.println(compile(a[1]) ? "OK" : "ERR");
            return;
        }
        String htmlFile = a[1];
        String xpath = a[2];
        String html = new String(Files.readAllBytes(Paths.get(htmlFile)), StandardCharsets.UTF_8);
        List<String> res = evalList(html, xpath);
        System.out.println(res.size());
        for (String s : res) {
            System.out.println(Base64.getEncoder().encodeToString(
                s.getBytes(StandardCharsets.UTF_8)));
        }
    }
}
