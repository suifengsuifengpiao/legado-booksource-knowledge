// ====================================================================
// 物证：legado_app_3.25.apk 的 jadx 1.5.0 反编译产物（单一真相源，禁止下官方源码）
//   apk md5 : 7c5ab9dfa751f58b8ef0220ae001d619   (vcode 15604 / 3.25)
//   类      : io.legado.app.model.analyzeRule.AnalyzeRule$SourceRule
//   来源 dex: classes3.dex
// 证明什么  : ## 切段机制 —— makeUpRule 调 kotlin.text.u.H0(rule, {"##"}, 0, 6)
//             把规则按 "##" 切成 4 段，mask=6(末位) 不是 limit，limit=0 保留尾部空串：
//               第0段 = 规则主体；第1段 = replaceRegex；第2段 = replacement；第3段存在 => replaceFirst
//             这就是 references 里 "##正则##替换" / "##$##值" 等写法的 dex 实锤。
// 怎么核对  : 搜 line 1844 的 H0 切分，1845-1854 的四段赋值；splitRegex(1716) 同用 "##" 切。
// 注意      : 反编译含 R8 混淆名(kotlin.text.u.H0 / d0.h0 / k.*)，属真实产物，非笔误。
// ====================================================================
    /* loaded from: classes3.dex */
    public final class SourceRule {
        private final int defaultRuleType;
        private final int getRuleType;
        private final int jsRuleType;
        private Mode mode;
        private final HashMap<String, String> putMap;
        private boolean replaceFirst;
        private String replaceRegex;
        private String replacement;
        private String rule;
        private final ArrayList<String> ruleParam;
        private final ArrayList<Integer> ruleType;
        final /* synthetic */ AnalyzeRule this$0;

        public SourceRule(AnalyzeRule analyzeRule, String ruleStr, Mode mode) {
            Mode mode2;
            k.e(ruleStr, "ruleStr");
            k.e(mode, "mode");
            this.this$0 = analyzeRule;
            this.mode = mode;
            this.replaceRegex = "";
            this.replacement = "";
            HashMap<String, String> hashMap = new HashMap<>();
            this.putMap = hashMap;
            this.ruleParam = new ArrayList<>();
            this.ruleType = new ArrayList<>();
            this.getRuleType = -2;
            this.jsRuleType = -1;
            Mode mode3 = this.mode;
            Mode mode4 = Mode.Js;
            int i3 = 0;
            if (mode3 != mode4 && mode3 != Mode.Regex) {
                if (d0.k0(ruleStr, "@CSS:", true)) {
                    this.mode = Mode.Default;
                } else if (d0.k0(ruleStr, "@@", false)) {
                    this.mode = Mode.Default;
                    ruleStr = ruleStr.substring(2);
                    k.d(ruleStr, "substring(...)");
                } else if (d0.k0(ruleStr, "@XPath:", true)) {
                    this.mode = Mode.XPath;
                    ruleStr = ruleStr.substring(7);
                    k.d(ruleStr, "substring(...)");
                } else if (!d0.k0(ruleStr, "@Json:", true)) {
                    if (!analyzeRule.isJSON && !d0.k0(ruleStr, "$.", false) && !d0.k0(ruleStr, "$[", false)) {
                        if (d0.k0(ruleStr, "/", false)) {
                            this.mode = Mode.XPath;
                        }
                    } else {
                        this.mode = Mode.Json;
                    }
                } else {
                    this.mode = Mode.Json;
                    ruleStr = ruleStr.substring(6);
                    k.d(ruleStr, "substring(...)");
                }
            }
            this.rule = ruleStr;
            this.rule = analyzeRule.splitPutRule(ruleStr, hashMap);
            Matcher matcher = AnalyzeRule.evalPattern.matcher(this.rule);
            if (matcher.find()) {
                String substring = this.rule.substring(0, matcher.start());
                k.d(substring, "substring(...)");
                Mode mode5 = this.mode;
                if (mode5 != mode4 && mode5 != (mode2 = Mode.Regex) && (matcher.start() == 0 || !kotlin.text.u.l0(substring, "##", false))) {
                    this.mode = mode2;
                }
                int i10 = 0;
                do {
                    if (matcher.start() > i10) {
                        String substring2 = this.rule.substring(i10, matcher.start());
                        k.d(substring2, "substring(...)");
                        splitRegex(substring2);
                    }
                    String group = matcher.group();
                    if (d0.k0(group, "@get:", true)) {
                        this.ruleType.add(Integer.valueOf(this.getRuleType));
                        ArrayList<String> arrayList = this.ruleParam;
                        String substring3 = group.substring(6, kotlin.text.u.p0(group));
                        k.d(substring3, "substring(...)");
                        arrayList.add(substring3);
                    } else if (d0.k0(group, "{{", false)) {
                        this.ruleType.add(Integer.valueOf(this.jsRuleType));
                        ArrayList<String> arrayList2 = this.ruleParam;
                        String substring4 = group.substring(2, group.length() - 2);
                        k.d(substring4, "substring(...)");
                        arrayList2.add(substring4);
                    } else {
                        splitRegex(group);
                    }
                    i10 = matcher.end();
                } while (matcher.find());
                i3 = i10;
            }
            if (this.rule.length() > i3) {
                String substring5 = this.rule.substring(i3);
                k.d(substring5, "substring(...)");
                splitRegex(substring5);
            }
        }

        private final boolean isRule(String ruleStr) {
            if (!kotlin.text.u.J0(ruleStr, '@') && !d0.k0(ruleStr, "$.", false) && !d0.k0(ruleStr, "$[", false) && !d0.k0(ruleStr, "//", false)) {
                return false;
            }
            return true;
        }

        private final void splitRegex(String ruleStr) {
            Mode mode;
            int i3 = 0;
            Matcher matcher = AnalyzeRule.regexPattern.matcher((CharSequence) kotlin.text.u.H0(ruleStr, new String[]{"##"}, 0, 6).get(0));
            if (matcher.find()) {
                Mode mode2 = this.mode;
                if (mode2 != Mode.Js && mode2 != (mode = Mode.Regex)) {
                    this.mode = mode;
                }
                do {
                    if (matcher.start() > i3) {
                        String substring = ruleStr.substring(i3, matcher.start());
                        k.d(substring, "substring(...)");
                        this.ruleType.add(Integer.valueOf(this.defaultRuleType));
                        this.ruleParam.add(substring);
                    }
                    String group = matcher.group();
                    ArrayList<Integer> arrayList = this.ruleType;
                    String substring2 = group.substring(1);
                    k.d(substring2, "substring(...)");
                    arrayList.add(Integer.valueOf(Integer.parseInt(substring2)));
                    this.ruleParam.add(group);
                    i3 = matcher.end();
                } while (matcher.find());
            }
            if (ruleStr.length() > i3) {
                String substring3 = ruleStr.substring(i3);
                k.d(substring3, "substring(...)");
                this.ruleType.add(Integer.valueOf(this.defaultRuleType));
                this.ruleParam.add(substring3);
            }
        }

        /* renamed from: getMode$app_appRelease, reason: from getter */
        public final Mode getMode() {
            return this.mode;
        }

        public final int getParamSize() {
            return this.ruleParam.size();
        }

        public final HashMap<String, String> getPutMap$app_appRelease() {
            return this.putMap;
        }

        /* renamed from: getReplaceFirst$app_appRelease, reason: from getter */
        public final boolean getReplaceFirst() {
            return this.replaceFirst;
        }

        /* renamed from: getReplaceRegex$app_appRelease, reason: from getter */
        public final String getReplaceRegex() {
            return this.replaceRegex;
        }

        /* renamed from: getReplacement$app_appRelease, reason: from getter */
        public final String getReplacement() {
            return this.replacement;
        }

        /* renamed from: getRule$app_appRelease, reason: from getter */
        public final String getRule() {
            return this.rule;
        }

        public final void makeUpRule(Object result) {
            List list;
            String str;
            StringBuilder sb = new StringBuilder();
            if (!this.ruleParam.isEmpty()) {
                int size = this.ruleParam.size();
                while (true) {
                    int i3 = size - 1;
                    if (size <= 0) {
                        break;
                    }
                    Integer num = this.ruleType.get(i3);
                    k.d(num, "get(...)");
                    int intValue = num.intValue();
                    if (intValue > this.defaultRuleType) {
                        if (result instanceof List) {
                            list = (List) result;
                        } else {
                            list = null;
                        }
                        if (list != null) {
                            if (list.size() > intValue && (str = (String) list.get(intValue)) != null) {
                                sb.insert(0, str);
                            }
                        } else {
                            sb.insert(0, this.ruleParam.get(i3));
                        }
                    } else if (intValue == this.jsRuleType) {
                        String str2 = this.ruleParam.get(i3);
                        k.d(str2, "get(...)");
                        if (isRule(str2)) {
                            AnalyzeRule analyzeRule = this.this$0;
                            String str3 = this.ruleParam.get(i3);
                            k.d(str3, "get(...)");
                            sb.insert(0, AnalyzeRule.getString$default(analyzeRule, t.T(new SourceRule(analyzeRule, str3, null, 2, null)), null, false, false, 14, null));
                        } else {
                            AnalyzeRule analyzeRule2 = this.this$0;
                            String str4 = this.ruleParam.get(i3);
                            k.d(str4, "get(...)");
                            Object evalJS = analyzeRule2.evalJS(str4, result);
                            if (evalJS != null) {
                                if (evalJS instanceof String) {
                                    sb.insert(0, (String) evalJS);
                                } else if ((evalJS instanceof Double) && ((Number) evalJS).doubleValue() % 1.0d == 0.0d) {
                                    sb.insert(0, String.format("%.0f", Arrays.copyOf(new Object[]{evalJS}, 1)));
                                } else {
                                    sb.insert(0, evalJS.toString());
                                }
                            }
                        }
                    } else if (intValue == this.getRuleType) {
                        AnalyzeRule analyzeRule3 = this.this$0;
                        String str5 = this.ruleParam.get(i3);
                        k.d(str5, "get(...)");
                        sb.insert(0, analyzeRule3.get(str5));
                    } else {
                        sb.insert(0, this.ruleParam.get(i3));
                    }
                    size = i3;
                }
                this.rule = sb.toString();
            }
            List H0 = kotlin.text.u.H0(this.rule, new String[]{"##"}, 0, 6);
            this.rule = kotlin.text.u.T0((String) H0.get(0)).toString();
            if (H0.size() > 1) {
                this.replaceRegex = (String) H0.get(1);
            }
            if (H0.size() > 2) {
                this.replacement = (String) H0.get(2);
            }
            if (H0.size() > 3) {
                this.replaceFirst = true;
            }
        }

        public final void setMode$app_appRelease(Mode mode) {
            k.e(mode, "<set-?>");
            this.mode = mode;
        }

        public final void setReplaceFirst$app_appRelease(boolean z) {
            this.replaceFirst = z;
        }

        public final void setReplaceRegex$app_appRelease(String str) {
            k.e(str, "<set-?>");
            this.replaceRegex = str;
        }

        public final void setReplacement$app_appRelease(String str) {
            k.e(str, "<set-?>");
            this.replacement = str;
        }

        public final void setRule$app_appRelease(String str) {
            k.e(str, "<set-?>");
            this.rule = str;
        }

        public /* synthetic */ SourceRule(AnalyzeRule analyzeRule, String str, Mode mode, int i3, e eVar) {
            this(analyzeRule, str, (i3 & 2) != 0 ? Mode.Default : mode);
        }
    }
}
