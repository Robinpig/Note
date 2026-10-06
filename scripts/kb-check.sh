#!/usr/bin/env bash
# 本地知识库质量门禁：与 .github/workflows/ci.yml 保持一致的校验。
# 覆盖两个活跃子树：Framework 与 Linux 内核。
# 用法：bash scripts/kb-check.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-python3}"

# 任一门禁失败即退出（set -e 只看最后一条命令的退出码，
# 这里显式 check，避免前面的失败被后续步骤掩盖）。
check() {
  local what="$1"; shift
  echo "==> ${what}"
  if ! "$@"; then
    echo "!!! 门禁未通过：${what}" >&2
    exit 1
  fi
}

check "站内链接校验 · Framework（GARBLED 仅告警不阻断）" \
  "$PY" .workbuddy/tools/validate_links.py docs/CS/Framework

check "站内链接校验 · Linux 内核（GARBLED 仅告警不阻断）" \
  "$PY" .workbuddy/tools/validate_links.py docs/CS/OS/Linux

check "站内链接校验 · 消息队列（GARBLED 仅告警不阻断）" \
  "$PY" .workbuddy/tools/validate_links.py docs/CS/MQ

check "交叉链接密度门禁 · Framework（无孤立页 + 平均链入>=3.5）" \
  "$PY" .workbuddy/tools/analyze_crosslinks.py --gate --min-indegree 3.5

check "交叉链接密度门禁 · Linux 内核（无孤立页 + 平均链入>=3.5）" \
  "$PY" .workbuddy/tools/analyze_crosslinks.py \
    --root "$PWD/docs/CS/OS" --dirs Linux --gate --min-indegree 3.5

# dot 图校验：Graphviz 2.40（viz.js 1.7.1）不支持 `subgraph ID [标签]`、
# `label:` 冒号写法与 `-->` 粗箭头，语法错误会让 Viz() 抛异常并中断整页渲染。
NODE="${NODE:-node}"
if command -v "$NODE" >/dev/null 2>&1; then
  check "dot 图可渲染校验 · 全库（防止 Viz 抛异常导致白屏）" \
    "$NODE" .workbuddy/tools/check_dot.js docs
else
  echo "==> 跳过 dot 图校验（未找到 node）"
fi

echo "==> 全部通过"

