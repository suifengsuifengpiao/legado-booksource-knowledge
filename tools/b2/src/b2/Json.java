package b2;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 轻量 JSON 工具：解析 + 序列化 + 路径取值。
 *
 * <p>设计约束：dex 内 {@code com.google.gson} 已被混淆（{@code Gson} 类重命名为 a/c/d…），
 * 且 {@code org.json} 不在 4 个 legado jar 内，故 harness 自带一个零依赖的 JSON 读写器，
 * 用于解析书源 JSON 并抽取规则串，以及把调试契约序列化回 JSON。
 */
public final class Json {

    private Json() {}

    // ===================== 解析 =====================

    /** 解析 JSON 文本为树：Map<String,Object> / List<Object> / String / Long / Double / Boolean / null。 */
    public static Object parse(String text) {
        return new Parser(text).parse();
    }

    private static final class Parser {
        private final String s;
        private int i;

        Parser(String s) { this.s = s; }

        private void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        Object parse() { ws(); return value(); }

        private Object value() {
            ws();
            char c = s.charAt(i);
            if (c == '{') return object();
            if (c == '[') return array();
            if (c == '"') return string();
            if (c == 't' || c == 'f') return bool();
            if (c == 'n') { i += 4; return null; }
            return number();
        }

        private Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; // skip {
            ws();
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws();
                String k = string();
                ws();
                i++; // skip :
                Object v = value();
                m.put(k, v);
                ws();
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == '}') { i++; break; }
            }
            return m;
        }

        private List<Object> array() {
            List<Object> l = new ArrayList<>();
            i++; // skip [
            ws();
            if (s.charAt(i) == ']') { i++; return l; }
            while (true) {
                l.add(value());
                ws();
                char c = s.charAt(i);
                if (c == ',') { i++; continue; }
                if (c == ']') { i++; break; }
            }
            return l;
        }

        private String string() {
            i++; // skip opening quote
            StringBuilder sb = new StringBuilder();
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    char e = s.charAt(i++);
                    switch (e) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'n': sb.append('\n'); break;
                        case 't': sb.append('\t'); break;
                        case 'r': sb.append('\r'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'u':
                            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                            i += 4;
                            break;
                        default: sb.append(e);
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Boolean bool() {
            if (s.charAt(i) == 't') { i += 4; return Boolean.TRUE; }
            i += 5;
            return Boolean.FALSE;
        }

        private Object number() {
            int start = i;
            while (i < s.length()) {
                char c = s.charAt(i);
                if ("0123456789+-.eE".indexOf(c) >= 0) i++;
                else break;
            }
            String n = s.substring(start, i);
            if (n.contains(".") || n.contains("e") || n.contains("E")) return Double.parseDouble(n);
            try {
                return Long.parseLong(n);
            } catch (NumberFormatException ex) {
                return Double.parseDouble(n);
            }
        }
    }

    // ===================== 路径取值 =====================

    /** 沿路径（对象键 / 数组下标）取 String；任一环节缺失返回 null。 */
    @SuppressWarnings("unchecked")
    public static String getString(Object root, String... path) {
        Object cur = root;
        for (String p : path) {
            if (cur instanceof Map) cur = ((Map<String, Object>) cur).get(p);
            else if (cur instanceof List) cur = ((List<Object>) cur).get(Integer.parseInt(p));
            else return null;
        }
        return cur == null ? null : cur.toString();
    }

    // ===================== 序列化 =====================

    public static String toJson(Object o) {
        StringBuilder sb = new StringBuilder();
        write(sb, o);
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder sb, Object o) {
        if (o == null) {
            sb.append("null");
        } else if (o instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                sb.append('"').append(escape(e.getKey())).append("\":");
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (o instanceof List) {
            sb.append('[');
            boolean first = true;
            for (Object x : (List<Object>) o) {
                if (!first) sb.append(',');
                first = false;
                write(sb, x);
            }
            sb.append(']');
        } else if (o instanceof String) {
            sb.append('"').append(escape((String) o)).append('"');
        } else if (o instanceof Number || o instanceof Boolean) {
            sb.append(o.toString());
        } else {
            sb.append('"').append(escape(o.toString())).append('"');
        }
    }

    private static String escape(String s) {
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\': sb.append("\\\\"); break;
                case '"': sb.append("\\\""); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default: sb.append(c);
            }
        }
        return sb.toString();
    }
}
