#!/usr/bin/env bash
# 校验 index.html 里所有外部资源（CDN 脚本/样式）当前是否真的可取。
#
# 背景：站点全部依赖挂在公共 CDN 上。CDN 挂掉或被墙时，docsify 核心
# (docsify.min.js) 加载失败，表现为「页面完全无法渲染」——浏览器里一片
# 空白，但本地文件、Markdown 内容全都正常，容易误判成笔记写坏了。
# 本脚本把所有 src/href 抽出来逐条请求，把「网络问题」和「内容问题」分开。
#
# 用法：
#   bash scripts/check_cdn.sh              # 校验全部外部资源
#   bash scripts/check_cdn.sh --js-only    # 只校验 .js（跳过 .css）
#   RETRY=5 bash scripts/check_cdn.sh      # 加大重试次数（网络抖动时）
#
# 退出码：0 = 全部可达；1 = 有资源不可达（此时页面在受限网络下会白屏）
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
INDEX="$REPO/index.html"
RETRY="${RETRY:-3}"
JS_ONLY=0
[ "${1:-}" = "--js-only" ] && JS_ONLY=1

command -v curl >/dev/null 2>&1 || { echo "需要 curl"; exit 2; }
[ -f "$INDEX" ] || { echo "找不到 index.html：$INDEX"; exit 2; }

TMP_URLS="$(mktemp)"; TMP_DIR="$(mktemp -d)"
trap 'rm -f "$TMP_URLS"; rm -rf "$TMP_DIR"' EXIT

# 抽出所有 src="..." / href="..."，只保留绝对/协议相对 URL，去重。
# 先剥掉 HTML 注释块：index.html 里保留了不少已停用插件（mermaid、disqus 等），
# 它们的 URL 写在注释中，不参与实际加载，校验它们只会产生误报。
sed -e 's/<!--/\n<!--\n/g' -e 's/-->/\n-->\n/g' "$INDEX" \
  | awk '/<!--/{inc=1; next} /-->/{inc=0; next} !inc' \
  | grep -oE '(src|href)="[^"]+"' \
  | sed -E 's/^(src|href)="//; s/"$//' \
  | grep -E '^(https?:)?//' | sort -u > "$TMP_URLS"

if [ "$JS_ONLY" = "1" ]; then
  grep '\.js$' "$TMP_URLS" > "$TMP_URLS.js" && mv "$TMP_URLS.js" "$TMP_URLS"
fi

total=$(wc -l < "$TMP_URLS" | tr -d ' ')
[ "$total" -eq 0 ] && { echo "index.html 里没有外部资源引用"; exit 0; }

echo "==> 校验 index.html 外部资源（共 $total 条，重试 $RETRY 次）"
fail=0
while IFS= read -r u; do
  case "$u" in
    //*) full="https:$u" ;;
    *)full="$u" ;;
  esac

  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
    --retry "$RETRY" --retry-all-errors "$full")

  if [ "$code" = "200" ]; then
    printf '  [OK]   %s\n' "$u"
  else
    printf '  [%s] %s\n' "$code" "$u"
    fail=$((fail + 1))
  fi
done < "$TMP_URLS"

echo "---"
if [ "$fail" -eq 0 ]; then
  echo "全部可达（${total}/${total}）"
  exit 0
fi
echo "不可达 ${fail}/${total} —— 受限网络下站点会白屏，先换 CDN 再排查笔记内容"
exit 1