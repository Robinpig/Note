#!/usr/bin/env python3
"""阶段①：框架内 hub 页 Links 区块补齐未链的子笔记（消除孤立页）。
策略：在 Links 区块最后一个 '- [' 链接行之后插入新行，保留原有内容。
仅补充"正文和 Links 均未出现"的子笔记（由 find_hub_gaps 预先核对）。
"""
import os, re, glob

# 仓库根：由本脚本位置回推（脚本在 scripts/ 下），不写死绝对路径。
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "CS", "Framework")
LINK_RE = re.compile(r'\(/docs/CS/Framework/([^)]+?)(?:#|\?id=)?\)')

# hub_rel -> 需补的子笔记（相对于该 hub 同目录）
GAPS = {
    "Dubbo/Dubbo.md": ["Consumer.md", "config.md", "Metadata.md"],
    "Netty/Netty.md": ["NewEventLoop.md", "HashedWheelTimer.md", "MpscLinkedQueue.md"],
    "Sentinel/Sentinel.md": ["work.md", "RateLimiter.md"],
    "Spring/Spring.md": ["SPI.md", "Event.md", "JPA.md"],
    "Spring_Boot/Spring_Boot.md": ["cache.md"],
    "Tomcat/Tomcat.md": ["threads.md", "WebSocket.md", "memory.md"],
    "ZooKeeper/ZooKeeper.md": ["Recipes.md", "Curator.md", "Jute.md", "IO.md", "client.md"],
    "etcd/etcd.md": ["lease.md", "watch.md", "compact.md", "security.md", "net.md", "client.md"],
}

for hub_rel, children in GAPS.items():
    hub_path = os.path.join(ROOT, hub_rel)
    hub_dir = os.path.dirname(hub_rel)
    content = open(hub_path, encoding='utf-8').read()

    m = re.search(r'(## Links\n)(.*?)(\n## |\Z)', content, re.S)
    if not m:
        print(f"SKIP(无Links区块): {hub_rel}")
        continue
    block = m.group(2)
    # 已出现的内部链接（文件名集合），正文+Links 一起判断
    existing = set(x.split('/')[-1] for x in LINK_RE.findall(content))

    lines = block.split('\n')
    last_link_idx = -1
    for i, l in enumerate(lines):
        if l.strip().startswith('- ['):
            last_link_idx = i
    insert_at = (last_link_idx + 1) if last_link_idx != -1 else 0

    added = []
    for c in children:
        if c in existing:
            continue
        name = c[:-3]
        link = f"- [{name}](/docs/CS/Framework/{hub_dir}/{c})"
        added.append(link)
    if not added:
        print(f"OK(无需补): {hub_rel}")
        continue

    new_lines = lines[:insert_at] + added + lines[insert_at:]
    new_block = '\n'.join(new_lines)
    new_content = content[:m.start(2)] + new_block + content[m.end(2):]
    open(hub_path, 'w', encoding='utf-8').write(new_content)
    print(f"+ {hub_rel}: {added}")
