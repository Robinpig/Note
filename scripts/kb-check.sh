#!/usr/bin/env bash
# 本地知识库质量门禁：与 .github/workflows/ci.yml 同源，但范围更大。
# 覆盖三个活跃子树（Framework / Linux 内核 / 消息队列）+ 全库 dot 图可渲染校验；
# ci.yml 只跑其中 Framework 与 Linux 两项。
# 依赖同目录下的脚本，全部随仓库入库（不再依赖 .workbuddy/ 这种本机目录）。
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
  "$PY" scripts/validate_links.py docs/CS/Framework

check "站内链接校验 · Linux 内核（GARBLED 仅告警不阻断）" \
  "$PY" scripts/validate_links.py docs/CS/OS/Linux

check "站内链接校验 · 消息队列（GARBLED 仅告警不阻断）" \
  "$PY" scripts/validate_links.py docs/CS/MQ

check "交叉链接密度门禁 · Framework（无孤立页 + 平均链入>=3.5）" \
  "$PY" scripts/analyze_crosslinks.py --gate --min-indegree 3.5

check "交叉链接密度门禁 · Linux 内核（无孤立页 + 平均链入>=3.5）" \
  "$PY" scripts/analyze_crosslinks.py \
    --root "$PWD/docs/CS/OS" --dirs Linux --gate --min-indegree 3.5

# dot 图校验：Graphviz 2.40（viz.js 1.7.1）不支持 `subgraph ID [标签]`、
# `label:` 冒号写法与 `-->` 粗箭头，语法错误会让 Viz() 抛异常并中断整页渲染。
NODE="${NODE:-node}"
if command -v "$NODE" >/dev/null 2>&1; then
  check "dot 图可渲染校验 · 全库（防止 Viz 抛异常导致白屏）" \
    "$NODE" scripts/check_dot.js docs
else
  echo "==> 跳过 dot 图校验（未找到 node）"
fi

# CDN 可达性检查：站点全部依赖挂在公共 CDN 上，CDN挂掉/被墙时 docsify 核心加载失败，
# 表现为「页面完全无法渲染」而非某篇笔记变样。**只告警不阻断**——可达性取决于运行环境，
# 受限网络下这本就应该是失败态，不能因此让本地门禁和 CI 全部报错。
if [ "${SKIP_CDN:-0}" != "1" ]; then
  echo "==> CDN 可达性检查 · index.html 外部资源（仅告警）"
  bash scripts/check_cdn.sh || \
    echo "!!! 警告：部分外部资源不可达，当前网络下站点会白屏（不影响笔记内容本身）"
fi

echo "==> 全部通过"

