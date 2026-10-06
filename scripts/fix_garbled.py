#!/usr/bin/env python3
"""清理 validate_links.py 报告的 GARBLED：在 CJK 与 Latin 字符边界补空格。

仅处理非代码块行（围栏 ``` / ~~~ 内跳过），保留代码标识符与代码块内容。
修复的是中文排版（CJK 与英文术语间应加空格），同时消除误报。
"""
import os
import re

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

GARBLED_RE = re.compile(r'[\u4e00-\u9fff][A-Za-z\u0400-\u04ff]{1,12}[\u4e00-\u9fff]')
CJK = r'[\u4e00-\u9fff]'
LAT = r'[A-Za-z\u0400-\u04ff]'
SUB1 = re.compile(r'(%s)(%s)' % (CJK, LAT))
SUB2 = re.compile(r'(%s)(%s)' % (LAT, CJK))


def space(s: str) -> str:
    s = SUB1.sub(r'\1 \2', s)
    s = SUB2.sub(r'\1 \2', s)
    return s


for rel in FILES:
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
    else:
        print("%s: no change" % rel)
