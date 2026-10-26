package b2;

import org.seimicrawler.xpath.JXDocument;

import java.lang.reflect.Method;

/**
 * 直接探针：绕开 harness 的 catch，打印 xpath 执行完整堆栈，定位
 * InstantiationError: j$.util.concurrent.ConcurrentHashMap$CollectionView 的真实触发点。
 */
public final class XpathProbe {
    public static void main(String[] args) throws Exception {
        String html = "<html><body><div class=\"t\">xpath-success-text</div><div class=\"x\">ignored</div></body></html>";
        String xpath = "//div[@class='t']/text()";
        try {
            // 复刻 legado 调用链：org.seimicrawler.xpath.JXDocument.create(html).sel(xpath)
            Class<?> jxd = Class.forName("org.seimicrawler.xpath.JXDocument");
            Method create = jxd.getMethod("create", String.class);
            Object doc = create.invoke(null, html);
            Method sel = jxd.getMethod("sel", String.class);
            Object res = sel.invoke(doc, xpath);
            System.out.println("XPATH_OK result=" + res);
        } catch (Throwable t) {
            System.out.println("XPATH_THROW: " + t.getClass().getName() + ": " + t.getMessage());
            t.printStackTrace(System.out);
        }
    }
}
