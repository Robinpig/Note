#!/usr/bin/env python3
"""阶段②：跨框架双向链接矩阵。
对给定 (目标文件 -> [要链接的相对路径]) 字典，在目标文件 Links 区块
安全追加缺失的跨框架链接（已出现在正文或 Links 的跳过，保证双向）。
相对路径形如 'ZooKeeper/ZooKeeper.md'，解析为 /docs/CS/Framework/<path>。
"""
import os, re

# 仓库根：由本脚本位置回推（脚本在 scripts/ 下），不写死绝对路径。
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "CS", "Framework")
LINK_RE = re.compile(r'\((/docs/CS/Framework/[^)]+)\)')

# 目标文件 -> 要加的链接（相对 Framework 的路径）
MATRIX = {
    # 协调 / 注册 / 配置中心簇
    "etcd/etcd.md":          ["ZooKeeper/ZooKeeper.md", "nacos/Nacos.md"],
    "ZooKeeper/ZooKeeper.md":["etcd/etcd.md", "nacos/Nacos.md", "eureka/Eureka.md", "BooKeeper/BooKeeper.md"],
    "nacos/Nacos.md":        ["etcd/etcd.md", "ZooKeeper/ZooKeeper.md", "eureka/Eureka.md", "Spring_Cloud/Spring_Cloud.md"],
    "eureka/Eureka.md":      ["ZooKeeper/ZooKeeper.md", "nacos/Nacos.md", "Spring_Cloud/Spring_Cloud.md"],
    "BooKeeper/BooKeeper.md":["ZooKeeper/ZooKeeper.md"],
    "ZooKeeper/Curator.md":  ["ZooKeeper/ZooKeeper.md"],
    # RPC 簇
    "Dubbo/Dubbo.md":        ["gRPC/gRPC.md", "HSF/HSF.md", "ZooKeeper/ZooKeeper.md"],
    "gRPC/gRPC.md":          ["Dubbo/Dubbo.md", "Netty/Netty.md"],
    "HSF/HSF.md":            ["Dubbo/Dubbo.md"],
    # 网络 / IO 簇
    "Netty/Netty.md":        ["Tomcat/Tomcat.md", "Jetty/Jetty.md", "reactor/Reactor.md"],
    "Tomcat/Tomcat.md":      ["Netty/Netty.md", "Jetty/Jetty.md"],
    "Jetty/Jetty.md":        ["Netty/Netty.md", "Tomcat/Tomcat.md"],
    "reactor/Reactor.md":    ["Netty/Netty.md", "RxJava/RxJava.md", "Spring/Reactive.md"],
    # ORM 簇
    "MyBatis/MyBatis.md":    ["Hibernate/Hibernate.md", "Spring/Spring.md"],
    "Hibernate/Hibernate.md":["MyBatis/MyBatis.md", "Spring/Spring.md"],
    # 响应式
    "RxJava/RxJava.md":      ["reactor/Reactor.md", "Spring/Reactive.md"],
    "Spring/Reactive.md":    ["reactor/Reactor.md", "RxJava/RxJava.md", "Netty/Netty.md"],
    # 流 / 批
    "Flink/Flink.md":        ["Spark/Spark.md", "Hadoop/Hadoop.md"],
    "Spark/Spark.md":        ["Flink/Flink.md", "Hadoop/Hadoop.md"],
    "Hadoop/Hadoop.md":      ["Spark/Spark.md", "Flink/Flink.md"],
    # AI / 调度 / 事务
    "LangTool/LangChain.md":     ["Spring/AI.md"],
    "LangTool/LangChain4j.md":   ["Spring/AI.md"],
    "LangTool/LangGraph.md":     ["Spring/AI.md"],
    "LangTool/Langflow.md":      ["Spring/AI.md"],
    "Job/xxl-job.md":            ["Spring/Task.md"],
    "Job/ElasticJob.md":         ["Spring/Task.md", "ZooKeeper/ZooKeeper.md"],
    "Job/PowerJob.md":           ["Spring/Task.md"],
    "Job/DolphinScheduler.md":   ["Spring/Task.md"],
    "Job/ScheduleX.md":          ["Spring/Task.md"],
    "Sentinel/Sentinel.md":      ["Spring_Cloud/Hystrix.md", "Spring_Cloud/Resilience4j.md"],
    "Seata/Seata.md":            ["Spring/Transaction.md", "Spring/Spring.md", "Dubbo/Dubbo.md"],
    # 服务网格 / 网关簇
    "Higress/Higress.md":        ["Istio/Istio.md", "Spring_Cloud/Spring_Cloud.md", "Spring_Cloud/gateway.md"],
    "Istio/Istio.md":           ["Higress/Higress.md", "Spring_Cloud/Spring_Cloud.md"],
    "Spring_Cloud/gateway.md":   ["Higress/Higress.md"],
    "Spring_Cloud/Spring_Cloud.md": ["Istio/Istio.md"],
}

def strip_name(path):
    # /docs/CS/Framework/X/Y.md?id=zzz -> Y.md
    base = path.split('/')[-1]
    base = re.split(r'[?#]', base)[0]
    return base

for target_rel, links in MATRIX.items():
    tpath = os.path.join(ROOT, target_rel)
    if not os.path.exists(tpath):
        print(f"SKIP(文件不存在): {target_rel}")
        continue
    content = open(tpath, encoding='utf-8').read()
    m = re.search(r'(## Links\n)(.*?)(\n## |\Z)', content, re.S)
    if not m:
        print(f"SKIP(无Links区块): {target_rel}")
        continue
    block = m.group(2)
    # 正文（Links 之前）已出现的链接
    body = content.split('## Links')[0]
    existing = set(strip_name(p) for p in LINK_RE.findall(content))
    body_existing = set(strip_name(p) for p in LINK_RE.findall(body))

    lines = block.split('\n')
    last_link_idx = -1
    for i, l in enumerate(lines):
        if l.strip().startswith('- ['):
            last_link_idx = i
    insert_at = (last_link_idx + 1) if last_link_idx != -1 else 0

    added = []
    for rel in links:
        name = rel.split('/')[-1].replace('.md', '')
        target_full = f"/docs/CS/Framework/{rel}"
        if strip_name(target_full) in existing or strip_name(target_full) in body_existing:
            continue
        added.append(f"- [{name}]({target_full})")
    if not added:
        continue
    new_lines = lines[:insert_at] + added + lines[insert_at:]
    new_block = '\n'.join(new_lines)
    new_content = content[:m.start(2)] + new_block + content[m.end(2):]
    open(tpath, 'w', encoding='utf-8').write(new_content)
    print(f"+ {target_rel}: {[a for a in added]}")
