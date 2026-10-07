## Introduction

本目录是 [容器](/docs/CS/Container/Container.md) 与容器编排的知识地图：从共享内核的隔离原理（Namespace/Cgroup），到 Docker 的镜像与网络实现，再到 [Kubernetes](/docs/CS/Container/k8s/K8s.md) 的架构、组件源码与生态工具。

## Knowledge Map

```
容器基础 (Container.md)
 │  Namespace + Cgroup 隔离原理 / OCI 运行时对比 / 容器 ↔ 进程定位
 ├── locate.md —— 容器 ID ↔ 宿主机 PID 双向换算（inspect / cgroup / nsenter）
 ├── Docker (Docker/)
 │     ├── Docker.md —— 镜像、架构、常用命令
 │     └── net.md —— bridge/host/container/none 网络模式
 └── Kubernetes (k8s/)
       ├── K8s.md —— 主笔记：架构 / 资源模型 / Pod / Service
       ├── Architecture.md —— 四条主链路串联 + 三个贯穿契约
       ├── Deletion.md —— 删除与级联：两阶段删除、finalizer、GC、优雅终止
       ├── Eviction.md —— 驱逐：心跳判活、污点、taint eviction、压力驱逐
       ├── Storage.md —— 存储链路：PVC 绑定 → Attach → 两阶段挂载
       ├── WatchCache.md —— 读路径底座：watch cache、list 分流、流式 list
       ├── Identity.md —— 身份与证书：TLS bootstrap、CSR 审批签发、token 轮换
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
| 镜像与运行时 | [Docker](/docs/CS/Container/Docker/Docker.md) | 分层镜像、容器引擎架构 |
| 运行时链路 | [containerd](/docs/CS/Container/k8s/containerd.md) | CRI 之下：五大模块、shim、runc |
| 最小调度单元 | [Pod](/docs/CS/Container/k8s/Pod.md) | pause 容器、生命周期、QoS、优雅终止 |
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
