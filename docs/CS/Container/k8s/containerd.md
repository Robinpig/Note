## Introduction

[kubelet](/docs/CS/Container/k8s/kubelet.md) 通过 CRI 的 gRPC 请求把"创建 Pod"的意图发给了容器运行时。但请求发出之后呢？运行时自己干了什么，又交给了谁？

先纠正一个常见误解：**containerd 不是 Kubernetes 的组件**。它是一个独立的通用容器运行时（Container Daemon）——[Docker](/docs/CS/Container/Docker/Docker.md) 底层用的也是它，只是 Docker 在上面套了自己的 CLI 和 API。K8s 通过 CRI 接入 containerd，Docker 通过自己的 API 接入 containerd，入口不同，底层是同一个进程。

```shell
sudo systemctl status containerd     # 它是 systemd 服务，不是 K8s 管的
```

一个重要推论：**kubelet 挂了 containerd 不受影响，containerd 挂了 kubelet 就没法创建容器**。两者的生命周期是解耦的。

在这条链路里，各层的职责可以概括为：

| 组件 | 职责 |
|------|------|
| kubelet | 决定创建什么 |
| CRI | 把意图标准化成 gRPC 请求 |
| containerd | 执行容器生命周期管理 |
| containerd-shim | 隔离容器进程与 containerd 的进程树 |
| runc | 真正落地到 Linux 内核 |

```shell
# 确认运行时类型与 endpoint
crictl info | jq '.config.containerd.runtimes.runc.runtimeType'
# io.containerd.runc.v2
ls -l /run/containerd/containerd.sock
```

## containerd Internals Are Not Monolithic

containerd 不是"收到 CRI 请求就调 runc"的黑盒，内部有五个模块各管一摊：

| 模块 | 管什么 |
|------|-------|
| **CRI Plugin** | K8s 的入口。把 CRI 请求翻译成 containerd 内部对象与操作（如把 `CreateContainerRequest` 转成 containerd Container 对象） |
| **Container Service** | 容器元数据（配置对象，注意不是运行中的进程） |
| **Snapshotter** | 文件系统快照。把镜像层 + 可写层拼成容器 rootfs，底层多用 OverlayFS |
| **Content Store** | 镜像层存储。镜像是多层压缩包，每层存这里，Snapshotter 按需取用 |
| **Task Service** | 运行中的进程。把 Container 对象（配置）变成 Task（真跑着的进程），这一步才真正调 runc |

为什么做成插件化？因为 containerd 不只服务 Kubernetes：Docker 调它、`ctr` 命令行直接操作它、也可以写自己的 client。插件化让核心逻辑复用，只换不同"入口插件"。

## Pod Sandbox: Build the Stage Before the Show

Pod 不等于 Container。Pod 是多个容器共享的运行环境（同一套 Network/IPC/UTS Namespace），实现方式是先创建一个最小化的 **Pause 容器**（镜像 `registry.k8s.io/pause`），它只做一个 `pause()` 系统调用永远挂着，业务容器创建时加入它的 Namespace 实现共享——细节见 [Pod 的 Pause 容器](/docs/CS/Container/k8s/Pod.md?id=pause-container)。

containerd 收到 `RunPodSandbox` 后：创建 Sandbox 对象 → 拉 Pause 镜像 → 创建 Pause 容器 → 生成 Namespace 配置 → **调 CNI 插件分配网络**（建 veth pair、配路由、分 Pod IP）→ 把 Sandbox 作为后续容器的基础环境。

```shell
sudo crictl pods     # 每个 Sandbox 有独立 ID，后续 CreateContainer 必须带上它
```

Sandbox 是网络的锚点：Pod 的 IP 属于 Sandbox，业务容器只是"加入"它——这正是"IP 归 Pod 而非容器"的实现层解释。

## CreateContainer ≠ Container Is Running

这是全文最容易混淆的一点：**`CreateContainer` 执行完后容器还没跑**。它做的是准备工作：

- 通过 Snapshotter 基于镜像构建 rootfs（镜像层 + 可写层拼装）；
- 生成容器的 OCI 配置（进程入口、环境变量、挂载点、资源限制）；
- 关联到 Sandbox，创建 containerd 内部的 Container 对象。

此时没有 `clone()`、没有 `exec()`，进程压根没启动。containerd 中 **Container 与 Task 是两个不同概念**：

| 概念 | 是什么 | 类比 |
|------|--------|------|
| Container | 配置对象：元数据、运行时描述、rootfs 路径、OCI Spec | 设计图纸 |
| Task | 运行实例：有 PID、stdio、退出状态 | 按图纸造出来并跑起来的实物 |

`CreateContainer` 生成图纸，`StartContainer` 才开工制造。用 `ctr` 可以直接看到这个区分：

```shell
sudo ctr -n k8s.io containers ls   # Container 对象，STATUS=created
sudo ctr -n k8s.io tasks ls        # Task，有 PID 列，STATUS=running
```

`-n k8s.io` 是 containerd 的 namespace，用来隔离不同上层用户——K8s 的容器都在这个 namespace 下。对照 `crictl`：

- `crictl ps` / `crictl pods` 走 **CRI gRPC 接口**（kubelet 也走这个），把 Container 和 Task 合并展示成一个"容器"概念；
- `ctr` 走 **containerd 自己的 API**，更底层，能看到 Container 与 Task 的分层。

要拿到它在宿主机上的 PID：`ctr tasks ls` 的 PID 列，或 `crictl inspect -o json <container-id> | jq .info.pid`。有了宿主 PID 就能继续顺着 `/proc` 反查容器 PID / namespace / rootfs，完整链路见 [容器定位](/docs/CS/Container/locate.md)。

## Snapshotter: rootfs Does Not Appear Out of Thin Air

容器看到的 rootfs 不是镜像解压出来的，而是**多层叠加**的结果：镜像由多个只读层组成（base layer、runtime layer、app layer），Snapshotter 在其上叠加一个每个容器独占的**可写层**，用 OverlayFS 合成统一视图。

- 只读层所有容器共享：同一镜像拉一次，跑 100 个容器也只存一份；
- 可写层每容器独有：写文件落到可写层，不改只读层——这就是**写时复制（Copy-on-Write）**，内核侧由 [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md) 承担（只读层作 `lowerdir`、可写层作 `upperdir`，首次写入触发 copy-up）。

```shell
crictl inspect <container-id> | jq .info.runtimeSpec.mounts
# 位于 /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/
# Located at /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/
```

## containerd-shim: Why an Extra Layer

如果 containerd 直接把容器进程作为自己的子进程管理，会有一个致命问题：**containerd 重启或升级时，它的所有子进程（也就是所有容器）都会受影响**。生产环境 containerd 升级是常事，不能每次升级都干掉节点上所有 Pod。

containerd-shim 的角色是容器进程的"养父"：containerd 不直接 fork 容器进程，而是先 fork 一个 shim，由 shim 去 fork 容器进程。这样容器进程的父进程是 shim 而非 containerd。

```shell
ps -ef | grep containerd-shim     # 每个容器一个 containerd-shim-runc-v2 进程
```

一个容易记错的细节：shim 进程的 **PPID 通常是 1**（而非 containerd），它启动后脱离 containerd 的进程树，独立维护容器生命周期；而容器进程的父进程是各自对应的 shim PID。这就是"解耦"在进程树上的体现。

shim 还负责：收集容器退出状态（exit code）、管理容器 stdio、充当 containerd 与容器进程之间的通信代理。

生产意义：containerd 升级时旧进程退出，shim 与容器继续跑，新 containerd 启动后通过 shim 重新接管。**整个升级过程容器不停机**。

## runc: The One That Actually Does the Work

runc 是 [OCI 运行时](/docs/CS/Container/Container.md)的参考实现。它接收 OCI Spec（描述容器该怎么建的 JSON），调 Linux 系统调用把它变成现实，做三件事：

1. **创建 Namespace**：PID（进程号空间）、Network（独立网络栈）、Mount（独立文件系统视图）、UTS（独立 hostname）、IPC（独立消息队列与共享内存）——原理见 [Namespace](/docs/CS/OS/Linux/namespace.md)；
2. **设置 Cgroup**：限制 CPU、内存、IO、设备——见 [Cgroup](/docs/CS/OS/Linux/cgroup.md)；
3. **挂载 rootfs**：把 Snapshotter 准备好的 OverlayFS 挂到容器进程的根目录。

这三步做完，容器进程就跑起来了。

## Stringing Together the Entire Chain

```
kubelet
  └─ CRI gRPC 请求
       └─ containerd CRI Plugin（翻译请求）
            ├─ Container Service 创建 Container 对象（配置）
            ├─ Snapshotter 用 OverlayFS 拼装 rootfs
            └─ Task Service 创建 Task
                 └─ fork containerd-shim
                      └─ shim 调 runc
                           └─ runc 创建 Namespace + cgroup、挂载 rootfs
                                └─ 容器进程跑起来
```

调试入口（按层级从高到低）：`kubectl` → `crictl`（CRI 层）→ `ctr`（containerd 内部对象）→ `runc list`（OCI 层）。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [Container](/docs/CS/Container/Container.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)
- [容器定位](/docs/CS/Container/locate.md)

## References

1. [K8s containerd 拆解：kubelet 发完请求之后发生了什么](https://mp.weixin.qq.com/s/pz7N69Nyi2hvo2aKiPKE_A)
