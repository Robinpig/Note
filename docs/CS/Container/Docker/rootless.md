## Introduction

普通 Docker 以 root 运行 daemon（dockerd），一旦被攻破就等于拿到宿主机 root——因为容器共享宿主机内核，逃逸即提权。**[Rootless Docker](https://docs.docker.com/engine/security/rootless/)** 让 dockerd 与 containerd 以**普通用户**身份运行，借助 **user namespace（用户命名空间）** 把容器内的 `uid 0`（root）映射到宿主机上一个**非特权**的 uid 范围，从而把"容器内 root"关在宿主机普通用户的笼子里。

> [!TIP]
> 一句话区分：普通 Docker 是"宿主机 root 跑容器"；Rootless 是"宿主机普通用户 + userns 映射"跑容器。前者逃逸即宿主机 root，后者逃逸最多是那个普通用户的权限。

## How It Works

Rootless 的核心是三层映射与两个用户态组件：

```
容器进程 uid 0
   │  user namespace 映射（/etc/subuid）
   ▼
宿主机 uid 100000（普通用户，无特权）
   │  slirp4netns / pasta（用户态网络栈）
   ▼
宿主机的网络（无需 CAP_NET_ADMIN）
   │  fuse-overlayfs / native overlay-in-userns（用户态存储）
   ▼
宿主机文件系统（无需 root 挂载权限）
```

- **uid/gid 映射**：`/etc/subuid`、`/etc/subgid` 给每个用户分配一段可映射的从属 ID（如 `user:100000:65536`），容器内的 root 被映射成这段里的某个非特权 ID。需要 `newuidmap` / `newgidmap`（来自 `uidmap`/`shadow-utils` 包）做 setuid 辅助。
- **网络**：没有 root 不能建 veth/桥，改用 **slirp4netns** 或 **pasta** 在用户态做 NAT，性能比 bridge 略低但无需特权。
- **存储**：overlay 默认需要 mount 特权，改用 **fuse-overlayfs**；内核 ≥ 5.11 也支持 native overlay in userns（无需 FUSE）。

## Running Rootless Docker

Docker 用 `rootlesskit`（一个 userns 沙箱）包裹 dockerd：

```shell
# 一键安装并启动（会拉起 dockerd-rootless 实例，监听 $XDG_RUNTIME_DIR/docker.sock）
dockerd-rootless-setuptool.sh install

# 之后用环境变量切到 rootless socket
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker run hello-world
```

关键环境变量：`DOCKER_HOST` 指向 rootless socket；`XDG_RUNTIME_DIR` 放 socket 与状态。rootless 实例与系统 Docker 完全隔离，可并存。

## Limitations

| 限制 | 原因 | 影响 |
| :--- | :--- | :--- |
| 不能用特权端口（<1024）直接绑定 | 非特权用户无 `CAP_NET_BIND_SERVICE` | 需 `sysctl net.ipv4.ip_unprivileged_port_start=80` 或映射到高位端口 |
| 部分存储驱动受限 | overlay 需特权 | 用 fuse-overlayfs / native userns overlay |
| cgroup v1 需 delegation | 非 root 不能建 cgroup 子树 | 配 `systemd` 的 `Delegate=yes`，或直接用 **cgroup v2**（rootless 推荐） |
| GPU / `--privileged` / 部分设备 | 需要宿主特权 | 受限或不可用 |
| 网络性能略低 | slirp4netns/pasta 用户态转发 | 高吞吐场景需评估 |

> [!WARNING]
> rootless 降低了"容器逃逸→宿主机提权"的爆炸半径，但**不是安全银弹**：共享内核的事实没变（见 [Container](/docs/CS/Container/Container.md)），内核漏洞仍可能击穿 userns。它解决的是"daemon 自身以 root 运行"这道最显眼的攻击面。

## Docker Desktop and WSL2

在 **Mac / Windows** 上，Docker 本来就不跑在宿主机内核——**Docker Desktop** 在后台起一个轻量 Linux VM（Mac 用 `vz`/HyperKit，Win 用 WSL2 或 Hyper-V），Docker Engine 实际运行在那个 VM 里。因此 Mac/Win 的 Docker 天然是"虚拟机隔离"，与 Linux rootless 解决的是不同层面的问题：

- **Linux rootless**：同一台 Linux 上，把 Engine 从宿主机 root 降为普通用户。
- **Docker Desktop (Mac/Win)**：Engine 本来就在一个独立 VM 里，和宿主机（macOS/Windows）是两层不同内核，隔离来自虚拟化而非 userns。

**WSL2 后端**（Windows）：Docker Desktop 把 Engine 跑在 WSL2 的 Linux 发行版里，Windows 侧通过 `docker` CLI 经 named pipe / socket 通信。WSL2 自带内核支持 cgroup v2 与 userns，理论上也能叠加 rootless，但 Docker Desktop 默认已用 VM 隔离，一般不再额外 rootless。

## Rootless in Kubernetes

Kubernetes 侧的对应物是 **user namespace 运行时 / Pod 级 `runAsNonRoot` + `USERNS`**：

- kubelet 自 v1.25 起支持把 Pod 跑在 user namespace（`PodSecurityContext` 相关特性，由运行时如 containerd 配合 userns 映射），思路与 Docker rootless 一致——容器 root 映射到节点非特权 uid。
- 日常更常见的是镜像内 `USER` 非 root + `securityContext.runAsNonRoot: true`，配合 [Docker 安全](/docs/CS/Container/Docker/security.md) 的 capabilities 收敛，与 rootless 是互补的两层。

## Links

- [Docker 运行时链路](/docs/CS/Container/Docker/runtime.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [容器隔离原理](/docs/CS/Container/Container.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)

## References

1. [Run the Docker daemon as a non-root user (Rootless)](https://docs.docker.com/engine/security/rootless/)
2. [RootlessKit](https://github.com/rootless-containers/rootlesskit)
3. [slirp4netns](https://github.com/rootless-containers/slirp4netns)
4. [Kubernetes User Namespaces (alpha)](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
