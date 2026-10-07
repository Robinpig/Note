#!/usr/bin/env python3
"""分析 KB 笔记的交叉链接密度。

扫描指定根目录下各主题子目录的 .md 笔记（默认 Note/docs/CS/Framework，跳过 img/），
构建由站内 `/docs/...md` 链接构成的有向图，按顶层子目录（主题）分组统计链入/链出、
孤立页、弱链出页、目录内/跨目录链接数等，用于衡量与监控笔记间的交叉链接密度。

用法:
    # 分析整个 Framework（默认根）
    python3 analyze_crosslinks.py

    # 只分析部分主题子目录（--dirs 接根目录下的顶层子目录名，可多个）
    python3 analyze_crosslinks.py --dirs Spring Spring_Boot Spring_Cloud

    # 指定其它根（例如整个 CS）
    python3 analyze_crosslinks.py --root "$PWD/docs/CS"

    # CI 密度门禁：出现孤立页 / 弱链出页 / 平均链入低于阈值则以退出码 1 失败
    python3 analyze_crosslinks.py --dirs Spring Spring_Boot Spring_Cloud --gate --min-indegree 4.0

站内链接的识别形如 `](/docs/xxx.md)`，**带 `?id=` 与 `#` 片段的链接同样计入**，
路径会先 unquote（`%20` 等转义与含空格的目录是常见写法）。根目录下的散文件（如
`CS.md`、`Languages.md`）不计入图的节点，只统计各主题子目录。
"""
import os
import re
import sys
from collections import defaultdict
from urllib.parse import unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（脚本在 scripts/ 下）
DEFAULT_ROOT = os.path.join(REPO, "docs", "CS", "Framework")

# 站内链接：/docs/xxx.md，允许后接 ?id=slug 或 #slug（docsify 锚点写法）
LINK_RE = re.compile(r"\]\((/docs/[^)\s]+?\.md)(?:[?#][^)\s]*)?\)")

# 不在站内链接图范围内的外部链接类型
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "?")


def collect(root, dirs=None):
    """返回 {相对根的路径: 绝对路径}，仅收集 .md，跳过 img/。"""
    files = {}
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        if not os.path.isdir(d):
            continue
        if entry in ("img",):
            continue
        if dirs and entry not in dirs:
            continue
        for dirpath, _, fnames in os.walk(d):
            if os.path.basename(dirpath) == "img":
                continue
            for fn in sorted(fnames):
                if fn.endswith(".md"):
                    key = os.path.relpath(os.path.join(dirpath, fn), root)
                    files[key] = os.path.join(dirpath, fn)
    return files


def top_dir(key):
    return key.split("/", 1)[0]


def main(argv):
    root = DEFAULT_ROOT
    dirs = None
    gate = False
    min_indegree = 3.0

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root":
            root = argv[i + 1]; i += 2
        elif a == "--dirs":
            dirs = []
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                dirs.append(argv[i]); i += 1
        elif a == "--gate":
            gate = True; i += 1
        elif a == "--min-indegree":
            min_indegree = float(argv[i + 1]); i += 2
        elif a in ("-h", "--help"):
            print(__doc__); return 0
        else:
            # 位置参数不受支持：目录一律走 --root / --dirs，避免误当路径传入
            print("未知参数: %s" % a)
            print("用法: analyze_crosslinks.py [--root <目录>] [--dirs <子目录>...] "
                  "[--gate] [--min-indegree N]")
            print("（目录清单请用 --dirs，例：--dirs Spring Spring_Boot；-h 看完整说明）")
            return 2

    files = collect(root, dirs)

    # 构建有向边（仅统计目标也在 files 集合内的站内链接）
    out_deg = defaultdict(set)
    in_deg = defaultdict(set)
    edges = set()
    inter = intra = 0
    for key, path in files.items():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(_SKIP_PREFIXES):
                continue
            if not target.startswith("/docs/"):
                continue
            # /docs/CS/Framework/Spring/IoC.md -> Spring/IoC.md (相对 root)
            # 先 unquote：站内存在含空格与 %20 的路径，不还原会漏计边
            abs_target = os.path.join(REPO, unquote(target).lstrip("/"))
            rel = os.path.relpath(abs_target, root).replace(os.sep, "/")
            if rel in files:
                if rel == key:
                    continue  # 自链接不计
                out_deg[key].add(rel)
                in_deg[rel].add(key)
                if (key, rel) in edges:
                    continue
                edges.add((key, rel))
                if top_dir(key) == top_dir(rel):
                    intra += 1
                else:
                    inter += 1

    print("=" * 78)
    print("根目录: %s" % root)
    if dirs:
        print("限定主题: %s" % ", ".join(dirs))
    print("文件总数: %d" % len(files))
    print("=" * 78)

    # 孤立页
    orphans = sorted(k for k in files if len(in_deg[k]) == 0)
    if orphans:
        print("\n### 孤立页 (无任何来自本范围内的内部链入)")
        for k in orphans:
            print("  [孤立] %s  (自身链出 %d)" % (k, len(out_deg[k])))

    # 弱链出页
    weak = sorted(k for k in files if len(out_deg[k]) <= 1)
    if weak:
        print("\n### 弱链出页 (<=1 条内部链接)")
        for k in weak:
            print("  [弱链出] %s  链出=%d 链入=%d" % (k, len(out_deg[k]), len(in_deg[k])))

    # 枢纽页 Top 10
    print("\n### 链入最多 (枢纽页 Top 10)")
    for k in sorted(files, key=lambda x: -len(in_deg[x]))[:10]:
        print("  [枢纽] %-42s 链入=%d 链出=%d" % (k, len(in_deg[k]), len(out_deg[k])))

    # 目录内/跨目录
    print("\n### 目录内 vs 跨目录 链接数")
    print("  目录内链接: %d" % intra)
    print("  跨目录链接: %d" % inter)
    print("  去重后总边数: %d" % len(edges))

    # 各目录分布
    print("\n### 各顶层目录 被链入分布")
    dirs_members = defaultdict(list)
    for k in files:
        dirs_members[top_dir(k)].append(k)
    for d in sorted(dirs_members):
        members = dirs_members[d]
        total_in = sum(len(in_deg[k]) for k in members)
        zero = sum(1 for k in members if len(in_deg[k]) == 0)
        print("  %-14s 成员=%2d 总链入=%3d 平均链入=%.2f 孤立=%d"
              % (d, len(members), total_in, total_in / len(members), zero))

    overall_avg = sum(len(in_deg[k]) for k in files) / len(files) if files else 0
    print("\n### 整体平均链入: %.2f" % overall_avg)

    # 门禁判定
    if gate:
        failures = []
        if orphans:
            failures.append("存在 %d 个孤立页" % len(orphans))
        if overall_avg < min_indegree:
            failures.append("整体平均链入 %.2f < 阈值 %.2f" % (overall_avg, min_indegree))
        # 弱链出页只链 hub 是叶子节点的正常形态（KB 规范认可），仅告警不阻断
        print("\n### 密度门禁 (--gate, 阈值 平均链入>=%.2f)" % min_indegree)
        if weak:
            print("  [WARN] 存在 %d 个弱链出页(链出<=1)，仅告警不阻断" % len(weak))
        if failures:
            for f in failures:
                print("  [FAIL] %s" % f)
            print("门禁结果: 不通过")
            return 1
        print("门禁结果: 通过")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
