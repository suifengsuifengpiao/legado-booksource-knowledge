#!/usr/bin/env bash
# 公开仓推送前脱敏自检
#
# 来历：2026-10-27。Gitee 长期令牌落盘到 .credentials/ 后，出现一条此前不存在的泄露路径——
# 令牌若被写进记忆层（MEMORY.md），而记忆层又计划推上「公开」仓，即等于公开令牌。
# 本脚本把人工 grep 固化为门禁。
#
# 用法： precheck_public_push.sh <待推送目录>
# 退出码：0 通过 / 1 检出问题 / 2 用法错误

set -u
DIR="${1:-.}"
TOKEN_FILE="/root/.codebuddy/.credentials/gitee_token"
fail=0

if [ ! -d "$DIR" ]; then
  echo "用法错误：目录不存在 -> $DIR" >&2
  exit 2
fi

# ---- 1. 令牌明文（硬失败）----
if [ -s "$TOKEN_FILE" ]; then
  token="$(cat "$TOKEN_FILE")"
  # 注意：--exclude-dir 必须在路径参数【之前】。放在路径后 GNU grep 会停止选项解析、
  # 把它当文件路径处理 -> 退出码 2 -> if 判为假 -> 打印"未检出"。
  # 这是本脚本 2026-10-27 实测踩到的假阴性：门禁显示通过，实际一次都没检查。
  if hits="$(grep -rIlF --exclude-dir=.git -- "$token" "$DIR" 2>/dev/null)"; then
    echo "❌ 检出令牌明文，禁止推送："
    echo "$hits" | sed 's/^/     /'
    fail=1
  else
    echo "✅ 令牌明文：未检出"
  fi
else
  echo "⚠️  令牌文件缺失或为空（$TOKEN_FILE），跳过第 1 项检查"
fi

# ---- 2. 常见凭证模式（硬失败）----
pat='(password|passwd|pwd)[[:space:]]*[:=]|access[_-]?token[[:space:]]*[:=]|secret[_-]?key[[:space:]]*[:=]|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}'
if hits="$(grep -rInE --exclude-dir=.git -- "$pat" "$DIR" 2>/dev/null)"; then
  echo "❌ 检出疑似凭证串："
  echo "$hits" | head -10 | sed 's/^/     /'
  fail=1
else
  echo "✅ 凭证模式：未命中"
fi

# ---- 3. 记忆层越界（告警，不阻断）----
found=0
while IFS= read -r f; do
  echo "⚠️  待推送区含记忆层文件：$(basename "$f") —— 确认已取得用户同意"
  found=1
done < <(find "$DIR" -maxdepth 1 \( -name 'SOUL.md' -o -name 'MEMORY.md' \) 2>/dev/null)
[ "$found" -eq 0 ] && echo "✅ 记忆层文件：未出现在待推送区"

# ---- 4. 沙箱内部标识（硬失败）----
# 来历：2026-10-27 12:45。回执里贴 `find` 输出时把路径写成 `.../<会话UUID前8位>-.../v1140/...`，
# 以为把尾部省成 "..." 就脱敏了，实际把 UUID 前缀原样留在了公开库里；对方随即把这串
# 误当成「引擎侧绝对标识」。**省略号只缩短显示，不改变泄露。**
# 故把"本机 hostname"与"本会话 UUID 前缀"都固化为门禁项，命中即阻断。
SANDBOX_ID_HIT=0
sn_host="$(hostname 2>/dev/null || true)"
if [ -n "$sn_host" ] && [ "${#sn_host}" -ge 8 ]; then
  if hits="$(grep -rIlF --exclude-dir=.git -- "$sn_host" "$DIR" 2>/dev/null)"; then
    echo "❌ 检出本机 hostname（$sn_host），禁止推送："
    echo "$hits" | sed 's/^/     /'
    SANDBOX_ID_HIT=1
  fi
fi
# 会话 UUID：从本会话工作目录 / 日志文件名提取前 8 位十六进制前缀
uuid_prefix=""
for cand in /root/.codebuddy/projects/*/*.jsonl; do
  [ -e "$cand" ] || continue
  base="$(basename "$cand" .jsonl)"
  case "$base" in
    *-*-*-*-*) uuid_prefix="${base%%-*}"; break ;;
  esac
done
if [ -n "$uuid_prefix" ] && [ "${#uuid_prefix}" -ge 8 ]; then
  if hits="$(grep -rIlE --exclude-dir=.git -- "$uuid_prefix" "$DIR" 2>/dev/null)"; then
    echo "❌ 检出本会话 UUID 前缀（${uuid_prefix}…），禁止推送："
    echo "$hits" | sed 's/^/     /'
    SANDBOX_ID_HIT=1
  fi
fi
if [ "$SANDBOX_ID_HIT" -eq 1 ]; then
  fail=1
else
  echo "✅ 沙箱内部标识（hostname / 会话 UUID）：未检出"
fi

# ---- 5. 版本同步（技能包硬失败）----
# 来历：v1.15.17 收口时 docstring 已标 1.15.17 而 SKILL.md/_meta.json 仍是 1.15.16，
# 漂移靠人工收口才发现。引擎侧回执（2026-11-02）建议门禁加「打包前比对 docstring 与 version」。
# 仅对待推送目录是技能包（含 SKILL.md + _meta.json）时生效；非技能包跳过。
if [ -f "$DIR/SKILL.md" ] && [ -f "$DIR/_meta.json" ]; then
  VS="$DIR/scripts/check_version_sync.py"
  if [ -f "$VS" ]; then
    vs_out="$(python3 "$VS" "$DIR" 2>&1)"; vs_rc=$?
    if [ "$vs_rc" -ne 0 ]; then
      echo "❌ 版本同步检查未通过："
      echo "$vs_out" | sed 's/^/     /'
      fail=1
    else
      echo "✅ 版本同步：SKILL.md / _meta.json / 显式标注脚本 三处一致"
    fi
  else
    echo "⚠️  技能包内缺 scripts/check_version_sync.py，跳过第 5 项（请先同步工具）"
  fi
else
  echo "✅ 版本同步：非技能包，跳过"
fi

# ---- 6. 归档包内脱敏（v1.15.24 新增）----
# 来历：2026-11-12。1~5 项的 grep -rI 只扫平铺文本文件；待推送区里的 .zip/.tar.gz
# 是二进制，grep -I 直接跳过 —— 包内若含令牌明文或记忆层文件，门禁四项全绿、exit=0
# （假阴性，比假红更危险）。本项把包解到临时目录，用与 1~4 项同一套判据补扫一遍；
# 只做文本比对，不执行包内任何文件，检查完即删临时目录。
ARCHIVE_TMP=""
cleanup_archive_tmp() { [ -n "$ARCHIVE_TMP" ] && [ -d "$ARCHIVE_TMP" ] && rm -rf "$ARCHIVE_TMP"; }
trap cleanup_archive_tmp EXIT

archives=0
ARCHIVE_TMP="$(mktemp -d /tmp/precheck_arch_XXXXXX)"
while IFS= read -r -d '' arc; do
  # 边界：异常大的包不解包（避免撑爆临时盘），显式告警不静默跳过。
  sz="$(wc -c < "$arc")"
  if [ "$sz" -gt 52428800 ]; then
    echo "⚠️  压缩包超过 50MB，跳过包内扫描（已知边界）: $(basename "$arc")"
    continue
  fi
  archives=$((archives + 1))
  sub="$ARCHIVE_TMP/a$archives"
  mkdir -p "$sub"
  case "$arc" in
    *.zip) unzip -q -o "$arc" -d "$sub" >/dev/null 2>&1 \
             || echo "⚠️  解包失败(跳过该包): $(basename "$arc")" ;;
    *)     tar -xzf "$arc" -C "$sub" >/dev/null 2>&1 \
             || echo "⚠️  解包失败(跳过该包): $(basename "$arc")" ;;
  esac
done < <(find "$DIR" -maxdepth 1 -type f \( -name '*.zip' -o -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' \) -print0 2>/dev/null)

if [ "$archives" -eq 0 ]; then
  echo "✅ 归档包内：待推送区无压缩包，跳过"
else
  ARCH_FAIL=0
  # 6a 令牌明文（同第 1 项判据）
  if [ -s "$TOKEN_FILE" ]; then
    token="$(cat "$TOKEN_FILE")"
    if hits="$(grep -rIlF -- "$token" "$ARCHIVE_TMP" 2>/dev/null)"; then
      echo "❌ 检出令牌明文【压缩包内】，禁止推送："
      echo "$hits" | sed 's/^/     /'
      ARCH_FAIL=1
    fi
  fi
  # 6b 常见凭证模式（同第 2 项判据）
  if hits="$(grep -rInE -- "$pat" "$ARCHIVE_TMP" 2>/dev/null)"; then
    echo "❌ 检出疑似凭证串【压缩包内】："
    echo "$hits" | head -10 | sed 's/^/     /'
    ARCH_FAIL=1
  fi
  # 6c 记忆层文件（同第 3 项判据，告警不阻断）
  while IFS= read -r f; do
    echo "⚠️  压缩包内含记忆层文件：$(basename "$f") —— 确认已取得用户同意"
  done < <(find "$ARCHIVE_TMP" -type f \( -name 'SOUL.md' -o -name 'MEMORY.md' \) 2>/dev/null)
  # 6d 沙箱内部标识（同第 4 项判据；sn_host / uuid_prefix 由第 4 项赋值）
  if [ -n "$sn_host" ] && [ "${#sn_host}" -ge 8 ]; then
    if hits="$(grep -rIlF -- "$sn_host" "$ARCHIVE_TMP" 2>/dev/null)"; then
      echo "❌ 检出本机 hostname【压缩包内】，禁止推送："
      echo "$hits" | sed 's/^/     /'
      ARCH_FAIL=1
    fi
  fi
  if [ -n "$uuid_prefix" ] && [ "${#uuid_prefix}" -ge 8 ]; then
    if hits="$(grep -rIlE -- "$uuid_prefix" "$ARCHIVE_TMP" 2>/dev/null)"; then
      echo "❌ 检出本会话 UUID 前缀【压缩包内】，禁止推送："
      echo "$hits" | sed 's/^/     /'
      ARCH_FAIL=1
    fi
  fi
  if [ "$ARCH_FAIL" -eq 1 ]; then
    fail=1
  else
    echo "✅ 归档包内（$archives 个压缩包）：令牌 / 凭证 / 沙箱标识 未检出"
  fi
fi

exit "$fail"
