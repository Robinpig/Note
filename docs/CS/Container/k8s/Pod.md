## Introduction

Pod 是 Kubernetes 中最小的可部署调度单元。它不是直接管理 [容器](/docs/CS/Container/Container.md)，而是把一个或多个容器"打包"成一个逻辑主机：这些容器共享同一组 [Network Namespace](/docs/CS/OS/Linux/namespace.md)、IPC Namespace 和 UTS Namespace，可以互相通过 `localhost` 通信、共享 Volume，但 PID Namespace 在不同版本默认行为有差异（v1.24+ 默认开启 Pod 级 PID 共享，使用 Sidecar 时需要留意进程可见性）。

> Pod 的设计动机：容器本质上是一个单进程模型。进程 1（PID=1）承担 init 系统的职责，管理多个进程的能力非常弱。既然容器本身是"进程"的抽象，那么 Pod 就是"进程组"的抽象——它对应的是传统部署时代"一组同生共死的进程"（如日志收集进程 + 业务进程），而不是"一台虚拟机"。

### Pause 容器

Pod 内的多个容器如何共享 Namespace？答案是 **Infra（pause）容器**：它是 Pod 中第一个被创建的容器，只负责"hold"住 Network/IPC/UTS 等 Namespace，其他业务容器 `Join` 到 pause 容器的 Namespace 中——`Join` 的系统调用是 setns(2)，机制见 [namespace 的 setns](/docs/CS/OS/Linux/namespace.md?id=setns-加入已有-namespace)。

```
Pod
 ├── pause (Infra) 容器   ← 持有 Network / IPC / UTS Namespace
 ├── app 容器             ← join pause 的 Network Namespace
 └── sidecar 容器         ← join pause 的 Network Namespace
```

这个设计带来了两个重要推论：

1. **容器镜像不依赖宿主机环境**：pause 容器镜像（`registry.k8s.io/pause`）只需要在 Node 上存在一次，多个 Pod 复用同一镜像层。
2. **IP 归 Pod 而非容器**：Pod 内所有容器共享同一个 IP 和端口空间，容器间通信走 loopback，避免了端口冲突检测的复杂性。

### 生命周期与状态

Pod 的 `status.phase` 有五种：

| Phase | 含义 | 典型场景 |
|-------|------|---------|
| Pending | 已创建但未运行 | 调度不满足 / 镜像拉取中 |
| Running | 已绑定节点且至少一个容器在运行 | 正常工作 |
| Succeeded | 所有容器成功退出且不会重启 | Job 完成 |
| Failed | 所有容器已终止且至少一个失败退出 | Job 失败 |
| Unknown | 状态无法获取 | kubelet 与 apiserver 失联 |

注意 phase 之外的 `conditions`（如 `PodScheduled`、`Ready`、`ContainersReady`）才是判断可用性的关键——Service/Deployment 的 endpoint 管理依据是 `Ready` condition 而不是 phase。

Pod 重启策略 `restartPolicy`（`Always` / `OnFailure` / `Never`）作用于 Pod 内所有容器。容器反复崩溃时会进入**退避重启**（CrashLoopBackOff）：重启等待时间从 10s 开始按指数退避增长至 5min，重置条件是容器持续运行超过 10min。

### 三类容器

Pod 中主要包含三类容器：Init 容器、普通容器和临时容器，分别对应 `InitContainers`、`Containers`、`EphemeralContainers` 字段。每一类容器都是数组类型，支持多个元素。其中 Init 容器和普通容器的每个元素都是 `Container` 类型的，临时容器则使用特殊的 `EphemeralContainer` 类型。

- **Init 容器**：按定义顺序串行执行，前一个成功退出（exit 0）后才会启动下一个；全部完成后才启动业务容器。适合等待依赖（如等待数据库就绪）、初始化配置。
- **普通容器**：业务负载本体，长期运行。
- **临时容器**：v1.23+ GA，无法指定 ports / probes / resources，不能重启，用于故障注入和在线调试（`kubectl debug -it pod --image=busybox`），弥补了 `kubectl exec` 无法进入没有 shell 的容器的情况。

### 资源与 QoS

每个容器可以声明 `requests`（调度依据）与 `limits`（运行上限）：

| QoS 类别 | 条件 | OOM 时被杀优先级 |
|----------|------|-----------------|
| Guaranteed | 所有容器 requests == limits（CPU 与内存都设置） | 最低（最后被杀） |
| Burstable | 至少一个容器设置了 request | 中间 |
| BestEffort | 什么都没设置 | 最高（最先被杀） |

内存超 limit 会被 OOMKill（退出码 137）；CPU 超 limit 只会被 CFS 限流（throttle），不会被杀。这也是 [Cgroup](/docs/CS/OS/Linux/cgroup.md) 在 Pod 层面的直接体现，内核 OOM killer 如何按 `oom_score_adj`（QoS 的底层落点）挑 victim 见 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。

> [!TIP]
> 注意区分两件容易被混为一谈的事：**内核 OOM killer 确实按 QoS 挑 victim**（经 `oom_score_adj`），但 **kubelet 的节点压力驱逐排序不看 QoS**——它按"是否超过自己的 request → priority → 绝对用量"排序，QoS 只在准入阶段起有限作用。这是两个不同的"内存不足时杀谁"的机制，详见 [驱逐](/docs/CS/Container/k8s/Eviction.md)。

### 优雅终止

删除 Pod 时的时序：Pod 进入 `Terminating` → 并行执行：endpoint 摘除（异步）+ `preStop` hook 执行 + 向容器进程发送 `SIGTERM` → 超过 `terminationGracePeriodSeconds`（默认 30s）后发送 `SIGKILL`。

经典陷阱：endpoint 摘除与负载均衡器更新是异步的，若应用收到 SIGTERM 后立即退出，会有"宽限期内的存量流量打到已死 Pod"的问题。解法是 `preStop` 中 `sleep` 几秒再退出。

## 故障排查

Pod 出现 CrashLoopBackOff 状态，就想到大概率是 Pod 内服务自身的原因。

使用 kubectl describe 命令查看：

从 Event 日志可以看出，是 calico 的健康检查没通过导致的重启，出错原因也比较明显：`net/http: request canceled while waiting for connection (Client.Timeout exceeded while awaiting headers)`，这个错误的含义是建立连接超时，并且手动在控制台执行健康检查命令，发现确实响应慢（正常环境是毫秒级别）。

考虑到错误原因是建立连接超时，并且业务量比较大，先观察一下 TCP 连接的状态情况（大量 `SYN_RECV` 通常意味着握手排队）。

常见排查入口：

```shell
kubectl describe pod <pod>          # Events 是第一手线索
kubectl logs <pod> -c <container> --previous   # 上一次崩溃的日志
kubectl get pod <pod> -o yaml       # 完整 Spec 与 Status
kubectl exec -it <pod> -- /bin/sh   # 进入容器
kubectl debug -it <pod> --image=nicolaka/netshoot  # 临时容器调试
```

更多异常状态见 [常见问题排查](/docs/CS/Container/k8s/Issues.md)。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)
- [scheduler](/docs/CS/Container/k8s/scheduler.md)
