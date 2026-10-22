## Introduction

部署（deployment）回答两个正交的问题：**作业以什么模式提交**（集群生命周期与 main() 在哪里跑），以及**资源由谁提供**（底层集群管理器）。Flink 在这两个维度上都是可插拔的，同一个作业 JAR 可以不变代码跑在 Standalone、[Yarn](/docs/CS/Framework/Hadoop/Yarn.md) 或 Kubernetes 上。

涉及的进程仍然是那三个：[Client](/docs/CS/Framework/Flink/Client.md) 提交、[JobManager](/docs/CS/Framework/Flink/JobManager.md) 调度协调、[TaskManager](/docs/CS/Framework/Flink/TaskManager.md) 执行。

## 三种部署模式

| 维度 | Session | Per-Job（Job 模式） | Application |
| ---- | ---- | ---- | ---- |
| 集群生命周期 | 预先启动、长期存在 | 每个作业独享集群，作业结束即释放 | 每个应用一个集群，应用内可跑多个作业 |
| `main()` 在哪执行 | Client | Client | **集群侧**（JobManager 的 cluster entrypoint） |
| JobManager | 多作业共享一个 | 每作业一个 | 每应用一个 |
| 资源隔离 | 差，一个作业拖垮 TaskManager 会连累同机作业 | 好 | 好（TaskManager 隔离，JobManager 按应用隔离） |
| Client 负载 | 重：要生成 JobGraph、上传依赖 | 重 | 轻：依赖由集群（如 HDFS）统一管理 |
| 适用 | 开发/测试、短小作业多 | 生产（成熟稳定） | 生产（社区主推，尤其容器化环境） |

演进脉络很清晰：Session → Per-Job 解决资源隔离，Per-Job → Application 解决 **Client 成为瓶颈**的问题（大量作业时 JobGraph 生成和依赖上传都压在提交机上）。Application 模式由 FLIP-85 引入，是容器化环境的自然选择。

```shell
# Application 模式（推荐）
./bin/flink run-application -t yarn-application ./MyJob.jar

# Session 模式：先起集群，再提交
./bin/start-cluster.sh
./bin/flink run ./MyJob.jar
```

## 三种资源提供者

### Standalone

- 最简单的部署方式：`start-cluster.sh` 拉起 JobManager 与若干 TaskManager；
- 资源**固定预分配**，ResourceManager 只能分配已注册的 Slot，无法弹性扩容；
- 仅支持 Session 模式提交；
- 适合本地验证、小规模固定负载。

### YARN

| 优点 | 注意事项 |
| ---- | ---- |
| 与 Hadoop 生态（[HDFS](/docs/CS/Framework/Hadoop/HDFS.md)、[Yarn](/docs/CS/Framework/Hadoop/Yarn.md)）天然集成 | 资源隔离（尤其网络）不够完善，离线与实时作业混布会互相干扰 |
| 按作业申请 container，资源弹性 | 需要关注 Kerberos 认证超期导致 checkpoint 无法持久化的问题 |
| 支持 Session / Per-Job / Application 三种模式 | 依赖上传与 classpath 管理较繁琐 |

### Kubernetes

- 云原生首选：JobManager Deployment + TaskManager Pod，ResourceManager 按需申请新 Pod；
- 两条路线：
  - **Native Kubernetes**：Flink 自己向 K8s API 申请资源；
  - **Flink Kubernetes Operator**：把作业声明成 CRD（`FlinkDeployment`），由 Operator 管理生命周期、升级、savepoint —— 生产更推荐这条路；
- 配合分离式状态后端（Flink 2.x）最契合：Pod 可以随时重建，状态不在本地盘。

```shell
kubectl create -f flink-configuration-configmap.yaml
kubectl create -f flink-deployment.yaml
```

## 资源模型：Slot 与并行度

- **Slot** 是 TaskManager 资源的最小切片，代表一份固定的内存/CPU。TaskManager 的 `numberOfTaskSlots` 决定能同时跑多少个 subtask；
- **SlotSharingGroup**：同一个共享组内的不同算子的 subtask 可以放进同一个 Slot，**默认全作业共享一个组**——这让"一个 Slot 恰好承载一条完整流水线"成为可能，所需 Slot 数 = 作业最大并行度，而不是算子数 × 并行度；
- **并行度**可在四个层级设置（优先级从低到高）：配置文件 → 提交参数 `-p` → `env.setParallelism()` → 算子 `.setParallelism()`；
- 估算所需资源：`总 Slot 数 ≈ 作业并行度`（默认共享组），再按每个 TaskManager 的 slot 数折算 TaskManager 个数，并预留一个用于失败恢复。

## 高可用

生产环境 JobManager 不能是单点（详见 [JobManager](/docs/CS/Framework/Flink/JobManager.md)）：

- 多个 JobManager 候选，通过 ZooKeeper 或 Kubernetes 的 leader election 选主；
- checkpoint 元数据、JobGraph 写入高可用存储（HDFS / S3 / OSS）；
- 主节点故障后 standby 接管，作业从最近一次 checkpoint 恢复。

## 版本与配置基线

> [!NOTE]
> Flink 2.x（首个版本 2.0.0 于 2025-03 发布，最新稳定版 2.3.0）相对 1.x 是**破坏性升级**：默认配置文件从 `flink-conf.yaml` 改为 `config.yaml`、移除大量废弃 API、1.x 与 2.x 之间**状态不兼容**、最低 Java 版本提升。升级前需评估 savepoint 迁移路径（通常要重放或双跑）。

## 选型建议

| 场景 | 推荐 |
| ---- | ---- |
| 本地开发 / 单元测试 | MiniCluster（standalone 本地模式） |
| 小规模固定作业、无弹性需求 | Standalone Session |
| Hadoop 集群已存在，作业批流混布 | YARN Application 模式 |
| 云原生、需要弹性与自动化运维 | Kubernetes + Flink Kubernetes Operator + Application 模式 |

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Client](/docs/CS/Framework/Flink/Client.md)
- [Spark Deploy](/docs/CS/Framework/Spark/Deploy.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)

## References

1. [Flink Docs - Deployment Overview](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/overview/)
2. [Flink Docs - Resource Provider（Standalone / Native Kubernetes / YARN）](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/resource-providers/standalone/overview/)
3. [Flink Docs - Flink Kubernetes Operator](https://nightlies.apache.org/flink/flink-kubernetes-operator-docs-stable/)
4. [FLIP-85: Flink Application Mode](https://cwiki.apache.org/confluence/display/FLINK/FLIP-85+Flink+Application+Mode)
