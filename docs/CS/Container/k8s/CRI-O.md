## Introduction

CRI-O 是**专为 Kubernetes 设计的轻量 CRI 运行时**，由 Red Hat / Intel / SUSE / IBM 等维护。它实现 K8s 的 **CRI (Container Runtime Interface)**，让 kubelet 通过标准接口跑任意 OCI 兼容运行时（默认 runc，可选 crun / Kata）。定位与 containerd 类似，但更"K8s-only"、更小、攻击面更窄。

与 Docker 的关系：Docker 作为 K8s 运行时已在 1.24 移除 dockershim（见 [containerd](/docs/CS/Container/k8s/containerd.md)）；CRI-O 是 Docker 之后的两条主流 CRI 运行时之一。

## Version Lockstep

CRI-O 的**主.次版本与 Kubernetes 锁定**：CRI-O 1.36 配 K8s 1.36、1.37 配 1.37，以此类推（patch 不锁）。这意味着"看版本号就知道配套测过哪版 K8s"，升级 CRI-O 与集群锁步，兼容判断极简。

> [!TIP]
> 与 containerd 对比：containerd 走**独立时间线**（2.x 系列，2026 年 2.3 起四月一版），一个 containerd 版本支持多个 K8s 版本，升级两者解耦、更灵活但要自己查支持矩阵。当前（K8s 1.36）kubelet 要求 containerd 2.0+；两者都**要求 cgroup v2**。

## Architecture

```
kubelet → CRI → crio → conmon(每容器一个，管 pty/日志/退出码) → runc/crun
                  │
                  ├─ 镜像：containers/image（拉任意 OCI registry）
                  ├─ 存储：containers/storage（COW，overlay 驱动）
                  └─ 网络：CNI（任意 CNI 插件，见 [CNI](/docs/CS/Container/k8s/CNI.md)）
```

每个容器由一个独立的 **conmon** 进程监控（持有容器 PID1 的 pty、处理日志、记录退出码）——类似 containerd 的 shim。

## OCI Runtime

默认 runc；可选 **crun**（更轻、支持 rootless/gvisor），通过配置切换。crun 与 gVisor (runsc) 配合可做更强隔离，见 [Container](/docs/CS/Container/Container.md) 运行时对比。

## When To Use

- **OpenShift / RHEL 系**：默认 CRI-O。
- 想要**最小运行时、最小攻击面**、版本与 K8s 锁步的安全敏感环境。
- 不需要非 K8s 容器场景（如本地 docker build、nerdctl 调试）——那是 containerd 更顺手。

> [!NOTE]
> 从 kubelet / 工作负载视角，运行时选择是透明的——Pod 在 containerd 和 CRI-O 上跑得一模一样。选型往往由发行版决定：云托管（GKE/EKS/AKS）默认 containerd，OpenShift 默认 CRI-O。

## Links

- [容器运行时 containerd](/docs/CS/Container/k8s/containerd.md)
- [CNI 插件对比](/docs/CS/Container/k8s/CNI.md)
- [容器隔离原理](/docs/CS/Container/Container.md)
- [CRI 之下链路](/docs/CS/Container/k8s/containerd.md)

## References

1. [CRI-O](https://cri-o.io/)
2. [Container Runtime Interface](https://kubernetes.io/docs/setup/production-environment/container-runtimes/)
