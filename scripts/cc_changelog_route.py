#!/usr/bin/env python3
"""Claude Code CHANGELOG 分册路由器。

把官方 CHANGELOG 的Added / Changed 条目按主题归到 ClaudeCode 各分册，
用于版本更新后的增量补漏。CHANGELOG 是本系列笔记最细的事实源之一
（文档给概念、CHANGELOG 给字段级事实与版本边界），本脚本让「哪些条目
可能落进哪篇」变成可机械复查的清单。

用法：
    python3 scripts/cc_changelog_route.py                     # 默认区间 + 内置路由
    python3 scripts/cc_changelog_route.py --from 2.1.290       # 指定起始版本
    python3 scripts/cc_changelog_route.py --file CHANGELOG.md # 本地已有的 CHANGELOG
    python3 scripts/cc_changelog_route.py --unrouted-only     # 只看未命中条目

取 CHANGELOG（应用源码不开放，但 CHANGELOG 随官方仓库公开）：
    curl -sL https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md -o /tmp/CHANGELOG.md
    # 若raw 不通，走 contents API：
    #   curl -s "https://api.github.com/repos/anthropics/claude-code/contents/CHANGELOG.md?ref=main"

路由表是**刻意不完整**的：关键词命中只说明「这条可能属于哪篇」，
不命中不代表无关（编辑器/UI/Cloud会话类条目本就不属机制类分册）。
因此默认会打印未命中样例，供人工判断是否需要扩路由表。
"""

import argparse
import re
import sys
import urllib.request
import json
import base64
from collections import Counter

CHANGELOG_URL = "https://api.github.com/repos/anthropics/claude-code/contents/CHANGELOG.md?ref=main"
RAW_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"

# 分册 -> 关键词（正则）。顺序不影响结果，取命中集合的并集。
ROUTE = {
    "Architecture.md": [
        r"gateway", r"cloud session", r"Cowork", r"self-hosted", r"Bedrock", r"Vertex",
        r"Foundry", r"Mantle", r"1M context", r"advisor", r"MCP protocol",
        r"\bsurface\b", r"API request", r"context window",
    ],
    "Permission.md": [
        r"permission mode", r"auto mode", r"classifier", r"sandbox", r"\bbypass\b",
        r"dontAsk", r"allow rule", r"tool_decision", r"deny rule", r"ask rule",
        r"\bceiling\b", r"PermissionRequest",
    ],
    "Security.md": [
        r"deny rule", r"ask rule", r"managed settings", r"allowManaged", r"\btier\b",
        r"sec-default", r"MCP allowlist", r"managedMcp", r"\bpolicy\b",
        r"security-guidance",
    ],
    "Hooks.md": [
        r"\bhooks?\b", r"PreToolUse", r"PostToolUse", r"SessionStart", r"SessionEnd",
        r"Stop hook", r"WorktreeCreate", r"WorktreeRemove", r"asyncRewake",
        r"rewakeMessage", r"rewakeSummary",
    ],
    "Mods.md": [
        r"\bmods?\b", r"mod hook", r"\$\.", r"claude plugin", r"hot reload",
        r"plugin hooks worker", r"gatingHooks",
    ],
    "PluginSpec.md": [
        r"plugin\.json", r"frontmatter", r"manifest", r"CLAUDE_PLUGIN_ROOT",
        r"marketplace", r"plugin-dev",
    ],
    "HookPatterns.md": [
        r"security-guidance", r"pattern rule", r"security review", r"diff review",
    ],
    "Extensions.md": [
        r"\bskills?\b", r"\bplugins?\b", r"marketplace", r"\bMCP\b", r"output style",
        r"/plugin", r"/skill", r"/mcp",
    ],
    "Observability.md": [
        r"OpenTelemetry", r"OTEL", r"telemetry", r"tool_decision", r"api_request",
        r"user_prompt", r"GenAI", r"\bspan\b", r"tool_result", r"at_mention",
    ],
    "Memory.md": [
        r"CLAUDE\.md", r"AGENTS\.md", r"\bmemory\b", r"\.claude/rules", r"compaction",
        r"auto-compact", r"/compact", r"instruction",
    ],
    "Subagents.md": [
        r"sub-?agents?", r"\bagent teams?\b", r"teammate", r"agent\.spawn",
        r"fork agents?", r"worktree", r"Agent calls", r"/agents",
    ],
    "Headless.md": [
        r"claude -p", r"--bare", r"headless", r"\bSDK\b", r"GitHub Action",
        r"SIGTERM", r"SIGINT", r"exit code", r"\bstdin\b", r"--permission-mode",
    ],
}

# 机制类之外、但值得知道的界面/云侧主题——仅用于分类标注，不落到分册
CATEGORY = {
    r"^\[VSCode\]|VS Code|JetBrains": "UI:编辑器",
    r"^\[Cloud sessions\]|cloud session": "UI:云会话",
    r"^\[Claude Tag\]|Slack": "UI:Slack",
    r"Remote Control|remote-control": "UI:Remote Control",
    r"vim mode|fullscreen|terminal|ANSI|iTerm|VTE": "UI:终端渲染",
    r"artifact|Artifact": "UI:Artifacts",
    r"Claude Design|/design-": "UI:Claude Design",
}


def fetch_changelog():
    """先试 raw，失败走 contents API（base64 解码）。"""
    try:
        with urllib.request.urlopen(RAW_URL, timeout=60) as r:
            t = r.read().decode()
        if len(t) > 1000:
            return t
    except Exception:
        pass
    with urllib.request.urlopen(CHANGELOG_URL, timeout=60) as r:
        d = json.load(r)
    return base64.b64decode(d["content"]).decode()


def parse(text, lo, hi):
    """产出 (version, kind, line)，kind 为 Added / Changed / Removed。"""
    lo_t = tuple(int(x) for x in lo.split("."))
    hi_t = tuple(int(x) for x in hi.split("."))
    out = []
    for block in re.split(r"\n## ", text)[1:]:
        ver = block.split("\n")[0].strip()
        if not re.match(r"^\d+\.\d+\.\d+$", ver):
            continue
        # 逐段比较元组，避免 "2.1.90" >= "2.1.299" 这类字符串比较陷阱
        vt = tuple(int(x) for x in ver.split("."))
        if vt < lo_t or vt > hi_t:
            continue
        for line in block.split("\n")[1:]:
            s = line.strip()
            m = re.match(r"^- (?:\[[^\]]+\] )?(Added|Changed|Removed)\b", s)
            if m:
                out.append((ver, m.group(1), s[2:]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="本地 CHANGELOG.md；不给则联网取")
    ap.add_argument("--from", dest="lo", default="2.1.280")
    ap.add_argument("--to", dest="hi", default="9999.999.999")
    ap.add_argument("--unrouted-only", action="store_true")
    args = ap.parse_args()

    text = open(args.file).read() if args.file else fetch_changelog()
    rows = parse(text, args.lo, args.hi)
    if not rows:
        print(f"区间 [{args.lo}, {args.hi}] 内没有 Added/Changed/Removed 条目")
        return

    router = [(re.compile(p, re.I), n) for n, ps in ROUTE.items() for p in ps]
    cat_rx = [(re.compile(p, re.I), n) for p, n in CATEGORY.items()]

    buckets = {}
    unrouted = []
    for ver, kind, body in rows:
        hits = sorted({n for rx, n in router if rx.search(body)})
        if not hits:
            cat = next((n for rx, n in cat_rx if rx.search(body)), "UI:其他")
            unrouted.append((ver, kind, cat, body))
            if args.unrouted_only:
                continue
        else:
            for h in hits:
                buckets.setdefault(h, []).append((ver, kind, body))

    if args.unrouted_only:
        for ver, kind, cat, body in unrouted:
            print(f"[{ver}] {kind} ({cat}) {body}")
        print(f"\n未命中 {len(unrouted)} / 共 {len(rows)} 条", file=sys.stderr)
        return

    print(f"区间 [{args.lo}, {args.hi}] 共 {len(rows)} 条Added/Changed/Removed\n")
    for name in sorted(buckets):
        items = buckets[name]
        ac = sum(1 for _, k, _ in items if k == "Added")
        print(f"=== {name}  {len(items)} 条（Added {ac} / Changed {len(items)-ac}）")
        for ver, kind, body in items[:12]:
            print(f"  [{ver}] {kind}: {body[:110]}")
        if len(items) > 12:
            print(f"  …… 另有 {len(items)-12} 条")
        print()

    if unrouted:
        print(f"=== 未命中 {len(unrouted)} 条（多为 UI/编辑器/云会话，路由表刻意不含）")
        c = Counter(cat for _, _, cat, _ in unrouted)
        for k, v in c.most_common():
            print(f"  {v:4d}  {k}")
        print("  用 --unrouted-only 看逐条，必要时扩 ROUTE。")


if __name__ == "__main__":
    main()