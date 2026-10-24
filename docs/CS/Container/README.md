## Introduction

本目录是 [容器](/docs/CS/Container/Container.md) 与容器编排的知识地图：从共享内核的隔离原理（Namespace/Cgroup），到 Docker 的镜像与网络实现，再到 [Kubernetes](/docs/CS/Container/k8s/K8s.md) 的架构、组件源码与生态工具。

## Knowledge Map

```
容器基础 (Container.md)
 │  Namespace + Cgroup 隔离原理 / OCI 运行时对比 / 容器 ↔ 进程定位
 ├── locate.md —— 容器 ID ↔ 宿主机 PID 双向换算（inspect / cgroup / nsenter）
 ├── Docker (Docker/)
 │     ├── Docker.md —— 枢纽：定位、安装、架构、底层三机制与分册导航
 │     ├── 原理与运行时
 │     │     └── runtime.md —— OCI 规范、dockerd→containerd→shim→runc、rootless
 │     ├── 镜像与构建
 │     │     ├── image.md —— 分层与内容寻址、registry、体积优化、供应链
 │     │     ├── registry.md —— OCI Distribution Spec、私有 registry、鉴权、GC、加速器
 │     │     ├── Dockerfile.md —— 指令语义、多阶段、BuildKit 缓存与 secret
 │     │     └── buildx.md —— 多平台构建、builder 实例、缓存导出、Bake
 │     ├── 数据与网络
 │     │     ├── storage.md —— volume/bind/tmpfs、overlay2 与 containerd snapshotter
 │     │     └── net.md —— bridge/host/container/none、端口发布、内嵌 DNS
 │     ├── 使用与编排
 │     │     ├── compose.md —— project/service/container 三层与字段陷阱
 │     │     ├── lifecycle.md —— PID 1/僵尸、信号与优雅终止、重启策略、健康检查
 │     │     ├── swarm.md —— 内建集群编排：服务/栈、overlay+routing mesh
 │     │     └── cli.md —— 命令速查、inspect 模板、排查一条龙
 │     └── 质量与配套
 │           ├── logging.md —— 两层日志模型、driver 全目录、轮转、dual logging
 │           ├── security.md —— capabilities、非 root、seccomp/LSM、签名与 secret
 │           ├── performance.md —— cgroup v2 限额、OOM、IO 与观测
 │           └── tools.md —— runlike/whaler/dive：反推与审计
 └── Kubernetes (k8s/)
       ├── K8s.md —— 主笔记：架构 / 资源模型 / Pod / Service
       ├── Architecture.md —— 四条主链路串联 + 三个贯穿契约
       ├── Deletion.md —— 删除与级联：两阶段删除、finalizer、GC、优雅终止
       ├── Eviction.md —— 驱逐：心跳判活、污点、taint eviction、压力驱逐
       ├── Storage.md —— 存储链路：PVC 绑定 → Attach → 两阶段挂载
       ├── WatchCache.md —— 读路径底座：watch cache、list 分流、流式 list
       ├── Identity.md —— 身份与证书：TLS bootstrap、CSR 审批签发、token 轮换
       ├── Workloads.md —— 工作负载：Deployment / StatefulSet / DaemonSet / Job / CronJob
       ├── Extension.md —— 扩展机制：CRD、Operator、聚合 API、准入 Webhook
       ├── Observability.md —— 可观测性：metrics / logs / traces 三条链路
       ├── GitOps.md —— 持续交付：pull 模型、Kustomize、Argo CD / Flux
       ├── 架构组件
       │     ├── apiserver.md      kubelet.md
       │     ├── scheduler.md      kube-proxy.md
       │     └── controller-manager.md
       ├── 控制器与调度
       │     ├── ReplicaSetController.md   jobController.md
       │     └── GC.md（垃圾回收）
       ├── 机制与原理
       │     ├── etcd.md（存储分层）      acl.md（认证/授权/准入）
       │     ├── containerd.md（CRI 之下）  client-go.md（Informer）
       │     └── kubectl.md（CLI）
       ├── 网络与流量
       │     ├── net.md（Pod 网络建立 + 数据面全链路）
       │     ├── Service.md（服务发现与四种类型）
       │     └── Ingress.md（七层路由与金丝雀）
       ├── 弹性与部署
       │     ├── Scaling.md（HPA/VPA/CA）  kubeadm.md
       │     └── Helm.md  Issues.md（排障）
       └── Pod.md —— 最小调度单元详解
```

## Quick Index

| 主题 | 笔记 | 一句话 |
|------|------|--------|
| 容器隔离原理 | [Container](/docs/CS/Container/Container.md) | Namespace 边界 + Cgroup 限额，runc/Kata/gVisor 对比 |
| 容器进程定位 | [locate](/docs/CS/Container/locate.md) | 容器 ID ↔ 宿主机 PID：inspect / `NSpid` / `/proc/PID/cgroup` / nsenter |
| 镜像与运行时 | [Docker](/docs/CS/Container/Docker/Docker.md) | 枢纽页：定位、安装、架构、底层三机制 |
| 运行时链路 | [Docker 运行时](/docs/CS/Container/Docker/runtime.md) | OCI 三件套、dockerd→containerd→shim→runc、隔离四道防线 |
| 镜像格式 | [Docker 镜像](/docs/CS/Container/Docker/image.md) | 内容寻址、CoW、registry 交互、体积优化与签名 |
| 构建 | [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md) | 指令语义、CMD vs ENTRYPOINT、多阶段、BuildKit |
| 持久化 | [Docker 存储](/docs/CS/Container/Docker/storage.md) | volume/bind/tmpfs、overlay2 与 containerd snapshotter |
| 网络 | [Docker 网络](/docs/CS/Container/Docker/net.md) | 六种网络模式、端口发布、内嵌 DNS、排障 |
| 多容器编排 | [Docker Compose](/docs/CS/Container/Docker/compose.md) | project/service/container、depends_on 与字段陷阱 |
| 命令速查 | [Docker CLI](/docs/CS/Container/Docker/cli.md) | inspect 模板、exec/logs、排查一条龙 |
| 容器安全 | [Docker 安全](/docs/CS/Container/Docker/security.md) | capabilities、非 root、seccomp/LSM、供应链与 secret |
| 资源与性能 | [Docker 性能](/docs/CS/Container/Docker/performance.md) | cgroup v2 限额映射、两种 OOM、IO 与观测 |
| 反推工具 | [Docker 工具](/docs/CS/Container/Docker/tools.md) | runlike 还原 run 命令、whaler/dive 还原镜像 |
| 日志 | [Docker 日志](/docs/CS/Container/Docker/logging.md) | 两层日志模型、driver 全目录、轮转、dual logging |
| 多平台构建 | [Docker Buildx](/docs/CS/Container/Docker/buildx.md) | builder 实例、QEMU 多架构、缓存导出、Bake、云构建 |
| 生命周期 | [容器生命周期](/docs/CS/Container/Docker/lifecycle.md) | PID 1/僵尸、信号与优雅终止、重启策略、健康检查 |
| 镜像仓库 | [Docker Registry](/docs/CS/Container/Docker/registry.md) | OCI Distribution Spec、私有 registry、鉴权、GC、加速器 |
| 集群编排 | [Docker Swarm](/docs/CS/Container/Docker/swarm.md) | 服务/栈、overlay+routing mesh、与 K8s 对比 |
| 运行时链路 | [containerd](/docs/CS/Container/k8s/containerd.md) | CRI 之下：五大模块、shim、runc |
| 最小调度单元 | [Pod](/docs/CS/Container/k8s/Pod.md) | pause 容器、生命周期、QoS、优雅终止 |
| 工作负载 | [Workloads](/docs/CS/Container/k8s/Workloads.md) | 五个控制器的默认值、滚动更新算式、身份与顺序 |
| 扩展机制 | [Extension](/docs/CS/Container/k8s/Extension.md) | CRD、Operator、聚合 API、准入 Webhook 与 VAP |
| 可观测性 | [Observability](/docs/CS/Container/k8s/Observability.md) | kubelet 指标端点、metrics API、日志路径、OTLP 链路 |
| 持续交付 | [GitOps](/docs/CS/Container/k8s/GitOps.md) | pull 模型、Kustomize、Argo CD / Flux、漂移与渐进式发布 |
| 集群主笔记 | [K8s](/docs/CS/Container/k8s/K8s.md) | 架构、资源对象、CRI、探针 |
| 四条主链路 | [Architecture](/docs/CS/Container/k8s/Architecture.md) | 写请求 / 控制回路 / 调度 / 落地，及 RV、OwnerReference、水平触发 |
| 删除与级联 | [Deletion](/docs/CS/Container/k8s/Deletion.md) | deletionTimestamp + finalizer、三种级联、优雅终止与 force delete |
| 驱逐 | [Eviction](/docs/CS/Container/k8s/Eviction.md) | 两套 eviction 的分野、心跳 50s、tolerationSeconds 起点、压力阈值 |
| 网络 | [net](/docs/CS/Container/k8s/net.md) | IP-per-Pod、CNI 边界、kube-proxy 三模式数据面、conntrack |
| 服务发现 | [Service](/docs/CS/Container/k8s/Service.md) | 四种类型、Endpoints、kube-proxy 模式 |
| 七层入口 | [Ingress](/docs/CS/Container/k8s/Ingress.md) | Ingress vs Controller、pathType、金丝雀 |
| 弹性扩缩容 | [Scaling](/docs/CS/Container/k8s/Scaling.md) | HPA 公式与冷却期、VPA、Cluster Autoscaler |
| 持久化存储 | [Storage](/docs/CS/Container/k8s/Storage.md) | PV/PVC 绑定、VolumeAttachment、CSI 两阶段挂载 |
| etcd 存储 | [etcd](/docs/CS/Container/k8s/etcd.md) | K8s 的存储分层与 watch 机制 |
| 安全 | [acl](/docs/CS/Container/k8s/acl.md) | 认证 → 授权 → 准入三道关卡 |
| 身份与证书 | [Identity](/docs/CS/Container/k8s/Identity.md) | TLS bootstrap 鸡生蛋、CSR 审批与签发、证书 70%~90% 轮换、SA token |
| 排障 | [Issues](/docs/CS/Container/k8s/Issues.md) | CrashLoopBackOff / Pending / NotReady 速查 |
| 包管理 | [Helm](/docs/CS/Container/k8s/Helm.md) | Chart / Release / values |
| 编程接口 | [client-go](/docs/CS/Container/k8s/client-go.md) | Informer / ListAndWatch / workqueue |

## Relationship with Other Areas

- 容器隔离的根基在操作系统层：[Namespace](/docs/CS/OS/Linux/namespace.md)、[Cgroup](/docs/CS/OS/Linux/cgroup.md)、[LXC](/docs/CS/OS/Linux/LXC.md)
- 容器网络底层：[Linux 网络](/docs/CS/OS/Linux/net/network.md)
- K8s 的分布式系统设计思想可对照 [Borg](/docs/CS/Distributed/Borg.md)
- 服务网格（Istio）建立在 K8s 之上：[Istio](/docs/CS/Framework/Istio/Istio.md)

## Links

- [CS 总目录](/docs/CS/CS.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Cloud](/docs/CS/Cloud/Cloud.md)
