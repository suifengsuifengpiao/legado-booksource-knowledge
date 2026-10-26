#!/usr/bin/env bash
# =============================================================================
# build-cp.sh —— 生成 B2 harness 运行期 classpath
#
# 设计红线（架构师高见远）：单 flat classpath，顺序固定为
#   android-stub.jar : harness编译产物(out) : 4个legado jar(自包含)
# 其中 4 个 legado jar 已自带 jsoup/gson/okhttp3/kotlin/hutool/jayway/Rhino/
# JsoupXpath，**严禁任何外部 Rhino/选择器 jar** 混入，版本与真机一致是保真根本。
# android-stub.jar 由方案 B（自产 minimal android stub）生成，不含任何外部下载。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEX_DIR="${DEX_DIR:-/workspace/b2-work}"
STUB_JAR="${STUB_JAR:-$SCRIPT_DIR/android-stub/android-stub.jar}"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/out}"

# -----------------------------------------------------------------------------
# Remediation 前置覆盖 jar（xpath/jsonpath 救活）—— enjarify 路线（2026-10-26）。
#
# 用 Google 官方 enjarify 把 classes4.dex / classes2.dex 直接 dalvik→JVM 字节码重导，
# 整 dex 内部一致、忠实于 APK 原始字节码（不走"反编译成 Java"），产出
# xpath-fix-enjarify.jar（= 完整 enjarify classes4 + classes2 中干净的
# j$/util/concurrent 脱糖包）。它修复了 dex2jar 2.4 的两处损坏：
#   1) xpath 引擎 cb 包 ATN 反序列化器（cb.j.b，原 state type 182）—— enjarify 忠实保留；
#   2) 脱糖 JDK 类 j$.util.concurrent.ConcurrentHashMap（DEX2JAR 与 enjarify 都会丢
#      ValuesView / 误用抽象 CollectionView，导致 InstantiationError）—— 本 jar 用
#      enjarify 对 classes2.dex 干净重导的 j$/util/concurrent/* 覆盖。
# 必须位于 4 个 dex jar 之前，以优先加载干净类。全部类源自 APK（enjarify 重导），
# 不含任何外部 JsoupXpath/jayway jar，严守红线。
# 仅当前置 jar 实际存在时才注入，保证主线缺失该 jar 时行为不变（不破坏主线）。
# 可用 FIX_JAR 环境变量覆盖默认路径（旧 jadx 路线产物见 xpath-jsonpath-fix.jar，可回滚）。
# -----------------------------------------------------------------------------
FIX_JAR="${FIX_JAR:-/workspace/b2-work/fix/jar/xpath-fix-enjarify.jar}"

# -----------------------------------------------------------------------------
# Rhino 本地化资源包（必需，2026-10-26 实测补）
#
# dex2jar 只转 class，**丢弃 jar 内非 class 资源**；而 Rhino 在抛任何内部错误时都要读
# org/mozilla/javascript/resources/Messages.properties 做本地化。缺失后果：
#   书源里任意 @js: 规则一旦出错 → MissingResourceException: Can't find bundle for base
#   name org.mozilla.javascript.resources.Messages —— 真实错误（TypeError/ReferenceError）
#   被彻底覆盖，排查方向被误导。
# 该 jar 由 APK 内同名资源直接打包（见 make-rhino-res.sh），非外部下载。
# -----------------------------------------------------------------------------
RHINO_RES_JAR="${RHINO_RES_JAR:-$SCRIPT_DIR/rhino-resources.jar}"

CP="$STUB_JAR:$OUT_DIR"
if [[ -f "$RHINO_RES_JAR" ]]; then
  CP="$CP:$RHINO_RES_JAR"
else
  echo "WARN: 缺少 Rhino 资源包: $RHINO_RES_JAR（JS 出错时会被 MissingResourceException 覆盖）" >&2
fi
if [[ -f "$FIX_JAR" ]]; then
  CP="$FIX_JAR:$CP"
  echo "[build-cp] 已前置 remediation fix.jar: $FIX_JAR" >&2
else
  echo "WARN: 未找到 remediation fix.jar: $FIX_JAR（跳过前置覆盖）" >&2
fi
for j in classes.jar classes2.jar classes3.jar classes4.jar; do
  if [[ -f "$DEX_DIR/$j" ]]; then
    CP="$CP:$DEX_DIR/$j"
  else
    echo "WARN: 缺少 dex jar: $DEX_DIR/$j" >&2
  fi
done

echo "$CP"
