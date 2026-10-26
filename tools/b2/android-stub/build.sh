#!/usr/bin/env bash
# =============================================================================
# android-stub/build.sh —— 编译「方案 B：自产 minimal android stub」并打成 jar
#
# 策略（架构师设计 §2.2/可行性 §3.3）：描述符驱动 + 链接即补循环。
# 仅桩 AnalyzeRule 解析闭包真实触碰的 android.* 类/方法；方法体返回安全默认值。
# 新增桩类后重跑 build.sh 即可（classpath 自动包含 android-stub.jar）。
# 仅有源码在 src/ 下，零外部依赖。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
OUT_DIR="$SCRIPT_DIR/classes"
JAR="$SCRIPT_DIR/android-stub.jar"

# 依赖 legado 自带类（用于编译期类型引用，例如 android.os.Parcelable 等接口）
DEX_DIR="${DEX_DIR:-/workspace/b2-work}"
DEX_CP=""
for j in classes.jar classes2.jar classes3.jar classes4.jar; do
  if [[ -f "$DEX_DIR/$j" ]]; then DEX_CP="$DEX_CP:$DEX_DIR/$j"; fi
done
DEX_CP="${DEX_CP#:}"

mkdir -p "$OUT_DIR"
find "$OUT_DIR" -name '*.class' -delete 2>/dev/null || true

if compgen -G "$SRC_DIR/**/*.java" >/dev/null 2>&1 || ls "$SRC_DIR" >/dev/null 2>&1; then
  # 收集全部源码
  mapfile -t SRCS < <(find "$SRC_DIR" -name '*.java')
  if [[ ${#SRCS[@]} -gt 0 ]]; then
    javac -d "$OUT_DIR" -cp "$DEX_CP" "${SRCS[@]}"
  fi
fi

# 打成 jar（含 manifest，便于 java -jar 备选）
cd "$OUT_DIR"
jar cf "$JAR" .
echo "BUILD android-stub.jar -> $JAR ($(find . -name '*.class' | wc -l) classes)"
