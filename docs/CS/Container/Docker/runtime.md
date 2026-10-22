## Introduction

`docker run` 看起来是一条命令，背后其实是**四层程序接力**：CLI 只是发 HTTP 请求，创建容器进程的活儿最终由 runc 完成。理解这条链路，才知道容器出问题时该去哪一层找答案——日志在 dockerd、状态在 containerd、进程树在 shim、隔离边界在内核。

```
docker CLI ──REST──> dockerd ──gRPC──> containerd ──fork/exec──> containerd-shim ──> runc ──> kernel
```

- **dockerd**：实现 Docker API，管镜像、网络、卷、swarm，把"创建容器"翻译成 containerd 的任务
- **[containerd](/docs/CS/Container/k8s/containerd.md)**：高级运行时，负责内容存储（content store）、快照（snapshotter）、生命周期
- **containerd-shim**：每个容器一个，是容器的父进程，负责回收僵尸进程、持有 stdio、在 daemon 重启时保持容器存活
- **runc**：低级运行时，读 OCI bundle 后调 `clone`/`pivot_root`/`exec`，创建完就退出

分层的意义在于**可替换**：换 runc 为 crun / youki / gVisor / Kata，或者换 containerd 为 CRI-O，上层都不用改——这正是 OCI 规范存在的理由。

## OCI 三件套

开放容器标准（Open Container Initiative）把接口切成三份，各自独立版本演进：

| 规范 | 定义什么 | 当前版本 |
| :-- | :-- | :-- |
| Runtime Spec | bundle 格式：`config.json`（进程、namespace、mount、cgroup、capabilities、hooks）+ rootfs 目录 | v1.3.0 |
| Image Spec | 镜像格式：index / manifest / config / layer tarball，全部按 digest 寻址 | v1.1.1 |
| Distribution Spec | registry 的 HTTP API：pull / push / referrers | v1.1.1 |

runc 1.5 实现 Runtime Spec v1.3.0，声明的兼容区间是 1.0.0 至 1.3.0。Image Spec 1.1 起才有的 `subject` 字段与 artifact manifest，是签名、SBOM、provenance 能挂在同一 registry 里的前提，见 [Docker 镜像](/docs/CS/Container/Docker/image.md)。

一个最小 bundle 长这样——`runc spec` 生成的模板就是"在六个新 namespace 里跑 sh，rootfs 只读"：

```shell
mkdir bundle && cd bundle && runc spec
jq -c '.ociVersion, .process.args, [.linux.namespaces[].type], .root' config.json
# ["1.3.0"]
# ["sh"]
# ["pid","network","ipc","uts","mount","cgroup"]
# {"path":"rootfs","readonly":true}
```

## 一条 docker run 的完整链路

以 `docker run -d -p 8080:80 --memory=512m nginx` 为例：

1. **CLI → dockerd**：`docker` 通过 `/var/run/docker.sock` 发 `POST /containers/create`
2. **解析镜像**：本地没有就按 [Distribution Spec](/docs/CS/Container/Docker/image.md) 从 registry 拉取，解开成层
3. **准备 rootfs**：由 snapshotter（或 graphdriver）把只读层 + 可写层联合挂载成容器 rootfs，见 [Docker 存储](/docs/CS/Container/Docker/storage.md)
4. **配置网络**：libnetwork 建 veth pair、接网桥、下发 NAT/DNAT 规则，见 [Docker 网络](/docs/CS/Container/Docker/net.md)
5. **生成 OCI spec**：把 `--memory`、`-p`、镜像 config 的 `Env`/`Cmd` 合并成 `config.json`
6. **containerd 创建 task**：写入 cgroup 限额、拉起 shim、fork/exec runc
7. **runc 组装容器**：`clone(CLONE_NEW*)` → 设置 capabilities/seccomp/LSM → `pivot_root` → `exec` 入口程序，随后 runc 自己退出
8. **shim 接管**：成为容器 PID 1 的父进程，转发 stdio、等待退出、上报 exit code

内核侧每一步的展开见 [namespace 的容器组装](/docs/CS/OS/Linux/namespace.md?id=how-containers-use-namespace)，CPU 限额如何传导到调度器见 [cgroup](/docs/CS/OS/Linux/cgroup.md?id=how-cpu-limit-reaches-the-scheduler)。

## 隔离的四道防线

Namespace 负责"看不见"，但只有它是不够的。真正的边界由四道机制叠加：

| 机制 | 拦住什么 | Docker 侧开关 |
| :-- | :-- | :-- |
| Namespace | 视图隔离：PID / NET / MNT / IPC / UTS / USER / cgroup | `docker run` 默认创建 |
| Capabilities | 把 root 拆成 40 多个细粒度权限 | `--cap-drop=ALL --cap-add=...` |
| seccomp | 系统调用黑名单（Docker 默认 profile 禁掉约 300 个 syscall） | `--security-opt seccomp=...` |
| LSM（AppArmor / SELinux） | 强制访问控制（MAC） | `--security-opt apparmor=...` |

cgroups 是第五道，但它拦的不是"能不能访问"，而是"能用多少"，见 [Docker 性能](/docs/CS/Container/Docker/performance.md)。

> [!WARNING]
> `--privileged` 会同时放开所有 capabilities、解除 seccomp、关闭设备限制——它基本等于"在宿主机上跑一个伪装成容器的 root 进程"。CI 里常见"加个 privileged 让 docker-in-docker 跑起来"，代价是把宿主内核暴露给容器，见 [Docker 安全](/docs/CS/Container/Docker/security.md)。

## shim 为什么存在

containerd 不直接当容器父进程，中间插一个 shim，是为了解耦：

- **daemon 可重启**：容器父进程是 shim 而不是 containerd，所以 dockerd / containerd 升级重启时容器不受影响
- **stdio 持久化**：容器的 stdout/stderr 由 shim 持有并通过 FIFO 落盘到日志驱动，daemon 挂了日志也不丢
- **僵尸进程回收**：容器内的孤儿进程被 shim 收养并 `wait`，避免 PID 1 不 reap 导致的僵尸堆积
- **运行时可插拔**：Kata、gVisor、Wasm 各自实现 shim（如 `io.containerd.kata.v2`），对 containerd 而言只是换了个 binary

所以 `ps` 里看到一堆 `containerd-shim-runc-v2` 是正常的，一个容器（或 Pod）对应一个。

## runc 与安全

runc 是参考实现，也是攻击面最集中的地方：它必须短暂地以宿主 root 身份操作文件系统，历史上出过多次逃逸：

- **CVE-2019-5736**：通过 `/proc/self/exe` 覆写宿主上的 runc 二进制
- **CVE-2024-21626**（Leaky Vessels）：泄漏的文件描述符让容器能拿到宿主目录句柄
- 2025 年 11 月一批 mount race 问题（CVE-2025-31133、CVE-2025-52565 等）

结论很朴素：**runc 必须跟着 Engine 打补丁**。runc 1.5 起默认启用 libpathrs 做安全的路径解析，1.2 及更早分支已 EOL，1.3 分支只修高危 CVE 且支持到 2026 年 10 月底。

替代实现各有取舍：

| 运行时 | 语言 | 特点 |
| :-- | :-- | :-- |
| runc | Go | OCI 参考实现，Docker / containerd / 多数 K8s 发行版默认 |
| crun | C | 启动更快、内存占用更小，Podman（Fedora/RHEL）默认，可跑 Wasm |
| youki | Rust | CNCF sandbox，用内存安全语言重写 |
| gVisor（runsc） | Go | 用户态内核，系统调用自己实现，隔离更强、性能有损 |
| Kata | Go + Rust | 每个容器一台轻量 VM，硬件级隔离 |

## Rootless 模式

默认 dockerd 以 root 运行，意味着"能调 Docker API = 能拿宿主 root"。Rootless 模式把 daemon 和容器都跑在普通用户下，靠 **user namespace** 把容器内的 root 映射成宿主上的普通 uid。

- 依赖 RootlessKit（Engine 29.9.1 打包 v3.3.0）构建网络与端口转发的非特权通道
- 代价：不能用低于 1024 的端口（默认）、部分存储/网络特性受限、需要 `newuidmap`/`newgidmap`
- Engine 29 仍在持续改进 rootless：29.8.0 起 `--net=host` 保留 cgroup 挂载，29.7+ 支持 CDI 设备

换句话说，rootless 提升的是"容器逃逸后的天花板"，不是"容器之间的隔离强度"。

## Engine 29 的运行时变化

- **containerd image store 成为新装默认**：镜像与层的管理从 graphdriver 迁到 containerd 的 content store + snapshotter，老存储驱动 deprecated，未来会移除。影响面主要是老镜像迁移与 `docker save/load` 的边界行为，细节见 [Docker 存储](/docs/CS/Container/Docker/storage.md)
- **embedded containerd**（29.7.0 实验）：把 containerd 跑进 daemon 进程，少一个常驻进程
- **cgroup v1 deprecated**（支持到 2029-05）：新装一律 cgroup v2，限额语义见 [Docker 性能](/docs/CS/Container/Docker/performance.md)
- **最小 API 版本 1.44**：v25 之前的客户端会被直接拒绝，必要时用 `DOCKER_MIN_API_VERSION` 或 `daemon.json` 的 `min-api-version` 覆盖

## Links

- [Container](/docs/CS/Container/Container.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [容器定位](/docs/CS/Container/locate.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [OCI Runtime Specification](https://github.com/opencontainers/runtime-spec)
2. [OCI Image Specification](https://github.com/opencontainers/image-spec)
3. [runc releases](https://github.com/opencontainers/runc/releases)
4. [Docker Engine release notes](https://docs.docker.com/engine/release-notes/)
