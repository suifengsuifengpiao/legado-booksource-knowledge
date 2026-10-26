#!/usr/bin/env bash
# =============================================================================
# make-rhino-res.sh —— 从 Legado APK 提取 Rhino 本地化资源，打 rhino-resources.jar
#
# 为什么需要：
#   dex2jar 只把 class 转成 jar，**丢弃 jar 内的非 class 资源**；而 Rhino 抛任何内部错误
#   时都要读 org/mozilla/javascript/resources/Messages.properties 做本地化。
#   缺了它，书源里任意 @js: 规则一出错就变成
#       MissingResourceException: Can't find bundle for base name
#       org.mozilla.javascript.resources.Messages
#   把真正的 TypeError / ReferenceError 彻底盖住。
#
# 用法：
#   bash make-rhino-res.sh [APK路径] [输出jar路径]
#   默认：/workspace/legado_app_3.25.apk  →  <本目录>/rhino-resources.jar
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK="${1:-/workspace/legado_app_3.25.apk}"
OUT="${2:-$SCRIPT_DIR/rhino-resources.jar}"

if [[ ! -f "$APK" ]]; then
  echo "ERROR: 找不到 APK: $APK" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

unzip -o -q "$APK" 'org/mozilla/javascript/*' -d "$TMP"
n=$(find "$TMP/org" -name "*.properties" | wc -l | tr -d ' ')
if [[ "$n" -eq 0 ]]; then
  echo "ERROR: APK 内未找到 org/mozilla/javascript/**/*.properties" >&2
  exit 1
fi

(cd "$TMP" && jar cf "$OUT" org)
echo "OK: 已打包 $n 个资源文件 -> $OUT ($(stat -c%s "$OUT") 字节)"
echo "    classpath 中请放在 4 个 dex jar 之后即可（资源查找与类加载顺序无关）"
