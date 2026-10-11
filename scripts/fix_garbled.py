#!/usr/bin/env python3
"""清理 validate_links.py 报告的 GARBLED：在 CJK 与 Latin 字符边界补空格。

仅处理非代码块行（围栏 ``` / ~~~ 内跳过），保留代码标识符与代码块内容。
修复的是中文排版（CJK 与英文术语间应加空格），同时消除误报。

用法:
    python3 scripts/fix_garbled.py [文件或目录...]   # 目录递归取 *.md（跳过 img/）
    python3 scripts/fix_garbled.py                   # 不带参数时处理下方默认文件列表
"""
import os
import re
import sys

# 仓库根：由本脚本位置回推（脚本在 scripts/ 下），不写死绝对路径。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    "docs/CS/Framework/Spring/AI.md",
    "docs/CS/Framework/Spring/Task.md",
    "docs/CS/Framework/Spring_Boot/Spring_Boot.md",
    "docs/CS/Framework/Spring_Boot/Start.md",
    "docs/CS/Framework/Spring_Cloud/Hystrix.md",
    "docs/CS/Framework/Spring_Cloud/Spring_Cloud.md",
]


def collect(args):
    """把命令行给定的文件/目录展开成仓库相对路径列表。"""
    out = []
    for a in args:
        p = a if os.path.isabs(a) else os.path.join(ROOT, a)
        p = os.path.normpath(p)
        if os.path.isdir(p):
            for base, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d != "img"]
                for n in sorted(names):
                    if n.endswith(".md"):
                        out.append(os.path.relpath(os.path.join(base, n), ROOT))
        elif os.path.isfile(p):
            out.append(os.path.relpath(p, ROOT))
        else:
            print("not found: %s" % a, file=sys.stderr)
    return sorted(set(out))

GARBLED_RE = re.compile(r'[\u4e00-\u9fff][A-Za-z\u0400-\u04ff]{1,12}[\u4e00-\u9fff]')
CJK = r'[\u4e00-\u9fff]'
LAT = r'[A-Za-z\u0400-\u04ff]'
SUB1 = re.compile(r'(%s)(%s)' % (CJK, LAT))
SUB2 = re.compile(r'(%s)(%s)' % (LAT, CJK))


def space(s: str) -> str:
    s = SUB1.sub(r'\1 \2', s)
    s = SUB2.sub(r'\1 \2', s)
    return s


TARGETS = collect(sys.argv[1:]) if len(sys.argv) > 1 else FILES

for rel in TARGETS:
    path = os.path.join(ROOT, rel)
    lines = open(path, encoding='utf-8').read().split('\n')
    in_fence = False
    changed = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if GARBLED_RE.search(line):
            new = space(line)
            if new != line:
                lines[i] = new
                changed += 1
    if changed:
        open(path, 'w', encoding='utf-8').write('\n'.join(lines))
        print("%s: fixed %d lines" % (rel, changed))
