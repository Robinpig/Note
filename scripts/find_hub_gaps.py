#!/usr/bin/env python3
import os, re, glob

# 仓库根：由本脚本位置回推（脚本在 scripts/ 下），不写死绝对路径。
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "CS", "Framework")
LINK_RE = re.compile(r'\[[^\]]+\]\((/docs/CS/Framework/[^)]+)\)')

dirs = sorted([d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d))])
for d in dirs:
    dpath = os.path.join(ROOT, d)
    mds = [os.path.basename(f) for f in glob.glob(os.path.join(dpath, '*.md'))]
    hub = d + '.md' if (d + '.md') in mds else None
    line = f"\n### {d} (hub={hub}, files={len(mds)})"
    if hub:
        hpath = os.path.join(dpath, hub)
        content = open(hpath, encoding='utf-8').read()
        # 正文（Links 之前）已有的内部链接
        body = content.split('## Links')[0] if '## Links' in content else content
        body_links = set()
        for m in LINK_RE.finditer(body):
            body_links.add(m.group(1).split('/')[-1])
        # Links 区块
        m = re.search(r'## Links(.*?)(?:\n## |\Z)', content, re.S)
        linked = set()
        if m:
            for lm in LINK_RE.finditer(m.group(1)):
                linked.add(lm.group(1).split('/')[-1])
        children = [x for x in mds if x != hub]
        missing = [c for c in children if c not in linked and c not in body_links]
        already = [c for c in children if c in linked or c in body_links]
        print(line)
        print(f"  hub已链(含正文): {sorted(already)}")
        print(f"  hub未链(需补): {missing}")
    else:
        print(line)
        print(f"  无同名hub，全部文件: {mds}")
