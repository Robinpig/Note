## Introduction

Swarm mode 是**内建于 Docker Engine** 的集群编排能力（由 SwarmKit 提供），`docker swarm init` / `join` 即可把多台 Docker 主机组成一个集群，用统一 CLI 部署服务、做滚动更新。

必须先厘清两个容易混淆的东西：

- **Swarm mode**（内建，Engine 1.12+ 就有）：**未宣布废弃**，功能可用，但官方投入放缓、让位 Kubernetes。
- **Docker Classic Swarm**（2014 年的独立老产品）：已在 **Engine 23.0 移除**，镜像标 `deprecated`——网上流传的"Swarm 死了"多半指它。

现状定位：Mirantis 承诺对 Swarm 支持到 **2030**；适合**小集群（数台~十几台）、单团队、负载简单、没人专职养集群**的场景。再大、再复杂、要 autoscaling / 服务网格，就上 [Kubernetes](/docs/CS/Container/k8s/K8s.md)。

## 架构

- **节点角色**：manager（通过 **Raft** 共识维护集群状态，推荐 **≤7 个**，容错 `(N-1)/2`）与 worker。两类节点都能用同一份 Engine 镜像起，角色在运行时分配。
- **服务（service）** 是核心抽象：声明式描述"我要几个副本、用什么镜像、什么网络"，manager 把服务拆成 **task** 调度到 worker，`desired state reconciliation` 持续把实际状态拉回期望（某节点挂了，就在别处补 task）。
- 这与单机 `docker run` 的本质区别：你不再管"跑在哪台"，只声明"要什么样"。

## 服务与栈

```bash
# 创建一个服务（3 副本，发布 8080）
docker service create --name web --replicas 3 -p 8080:80 nginx

docker service scale web=5
docker service update --image nginx:1.27 web     # 滚动更新
docker service rollback web                        # 回滚
docker service ps web                              # 看 task 分布
```

**栈（stack）** 用 Compose 文件批量部署一组服务：

```bash
docker stack deploy -c docker-compose.yml mystack
docker stack services mystack
```

⚠️ 坑：`docker stack deploy` 用的是**旧 Compose v3 子集**，与现行 Compose Spec **不完全兼容**——部分键（如 `depends_on` 高级写法、`deploy` 某些字段）会被**静默忽略并打印警告**。"在 Compose 能跑"不保证"在 stack 能跑"，反之亦然。

滚动更新参数：`--update-parallelism`、`--update-delay`、`--update-failure-action`，失败可 `--rollback`。

## 网络

- **overlay 网络**跨主机，swarm 自动给容器分配地址，并内建 **DNS**：服务名直接解析、自动负载均衡到各副本。
- **routing mesh（ingress LB）**：把 published 端口在**所有节点**上暴露，访问任意节点的 `IP:port` 都能命中服务（底层 VIP + iptables/IPVS 转发）。这让"外部流量进哪个节点"变得无所谓。
- 与单机网络模型的关系见 [Docker 网络](/docs/CS/Container/Docker/net.md)。注意：**Swarm 启用时无法开启 nftables**，仍走 iptables——而 nftables 是 Docker 未来的默认防火墙方向，这是 Swarm 的一个长期适配风险。

## 安全

- 节点间默认 **mTLS**（自动签发、定期轮换证书），集群内通信加密且双向认证。
- **secret**：`docker secret create`，挂载到容器 `/run/secrets/`，**加密存储**于 Raft 日志；适合密码、令牌。
- **config**：`docker config create`，但**不加密**、直接落到容器文件系统；secret 与 config 都有 **500KB** 上限。

```bash
echo "db_password" | docker secret create db_pw -
docker service create --name api --secret db_pw myapi:1.4
# 容器内读 /run/secrets/db_pw
```

## 与 Kubernetes 对比（何时选谁）

| 维度 | Swarm mode | Kubernetes |
| :-- | :-- | :-- |
| 复杂度 / 运维成本 | 低，Engine 内建 | 高，需专门能力 |
| 集群规模 | 小（数十节点量级） | 大（成百上千） |
| 自动扩缩容 | **无原生 HPA 类能力** | 原生 HPA/VPA |
| 存储 | CSI 支持**实验性**（无快照/扩容） | CSI 成熟 |
| 网络策略 / 服务网格 | 弱 | NetworkPolicy、Istio 等生态 |
| 生态与人才 | 萎缩 | 主流（~96% 企业采用） |

迁移映射（概念对应）：

- service → Deployment + Service
- stack（Compose v3）→ Helm / Kustomize
- overlay → CNI 插件 + NetworkPolicy
- secret → Kubernetes Secret
- config → ConfigMap

## 限制与排障

已知短板（决定它"能不能用"的关键）：

- **无原生 autoscaling**：HPA 类提案长期未实现。
- **CSI 存储实验性**：无快照、克隆、卷扩容。
- **stack 用旧 Compose 格式**：键静默忽略。
- **nftables 不兼容**：影响长期防火墙演进路线。
- 官方**不公布规模上限阈值**。

排障入口：

```bash
docker node ls              # 节点与状态
docker service ls / ps      # 服务与 task
docker stack ps mystack
journalctl -u docker.service   # daemon 日志（单节点）
```

## Links

- [Docker Compose](/docs/CS/Container/Docker/compose.md)
- [Docker 网络](/docs/CS/Container/Docker/net.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [Swarm mode overview](https://docs.docker.com/engine/swarm/)
2. [Swarm mode key concepts](https://docs.docker.com/engine/swarm/key-concepts/)
3. [Docker Swarm deprecated/retired products note](https://docs.docker.com/engine/deprecated/)
