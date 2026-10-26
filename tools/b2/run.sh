#!/usr/bin/env bash
# =============================================================================
# run.sh —— B2 harness 编译 + 运行入口
#
# 职责：
#   1) 构建 android-stub.jar（方案 B 最小 Android 桩，零外部依赖）
#   2) 编译 harness 源码到 out/
#   3) 以 -noverify 运行（dex2jar 转换类存在偶发栈图校验产物，需关闭 JVM 校验；
#      dex 类本身为真实 legado 3.25 解析类，非伪造）
#   4) 注入 -Db2.home 使 samples/ 相对路径可解析
#
# 红线：classpath 仅含 android-stub.jar + 4 个 dex jar + harness 自身，无任何外部
#       Rhino / 选择器 / gson jar；运行期永不真实联网。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) Android 桩
"$SCRIPT_DIR/android-stub/build.sh"

# 2) 编译 harness
mkdir -p "$SCRIPT_DIR/out"
CP="$("$SCRIPT_DIR/build-cp.sh")"
echo "[run.sh] 编译 harness 源码..."
javac -d "$SCRIPT_DIR/out" -cp "$CP" $(find "$SCRIPT_DIR/src" -name '*.java')

# 3) 运行（透传参数给主类；无参数时默认跑 B2Harness 全规则区）
if [ "$#" -eq 0 ]; then
  MAIN="b2.B2Harness"
  ARGS=()
elif [[ "$1" != -* ]] && [[ "$1" == *.* ]]; then
  # 形如 "b2.B2Harness" 的首参视为主类
  MAIN="$1"; shift; ARGS=("$@")
else
  # 首参为选项（如 --region），默认主类 + 透传全部选项
  MAIN="b2.B2Harness"; ARGS=("$@")
fi
exec java -noverify -Db2.home="$SCRIPT_DIR" -cp "$CP:$SCRIPT_DIR/out" "$MAIN" "${ARGS[@]}"
