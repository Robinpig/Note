## Introduction

容器不是一个内核认得的对象。内核里只有**进程**、**namespace 成员身份**和 **cgroup 归属**这三样东西；所谓"找到这个容器"，落到操作上就是这三者之间的双向换算：

```
容器 ID ──► 宿主机 PID ──► /proc/PID/{status,cgroup,ns,root,fd,...}
宿主机 PID ──► /proc/PID/cgroup ──► 容器 ID / Pod UID ──► 容器名
```

这套换算在两种场景下最值钱：**镜像里没有 shell（distroless/scratch，`exec` 用不了）**，以及 **daemon 自己就是坏掉的那个**。两者都需要绕开上层工具，直接从 `/proc` 读答案。原理见 [namespace 的 setns](/docs/CS/OS/Linux/namespace.md?id=setns-加入已有-namespace) 与 [cgroup](/docs/CS/OS/Linux/cgroup.md)。

## 同一进程的两套 PID

PID namespace 是**层级嵌套**的，因此同一个进程在每一级 PID namespace 里都有一个编号。容器里的 PID 1，在宿主机上往往是一个普通的四位数：

```shell
PID=$(docker inspect <容器名> --format '{{.State.Pid}}')
grep -E '^NStgid|^NSpid' /proc/$PID/status
```

```
NSpid:	2192	1
```

`NSpid` 自左向右是**由外到内**：最左是该进程在最外层（宿主机）PID namespace 里的号，向右依次是每一层嵌套 namespace 里的号。

- 两列 = 一层嵌套（宿主机 → 容器），这是最常见的情形；
- 三列及以上 = 嵌套容器（docker-in-docker）或 rootless 那一层额外的 namespace；
- 反过来，一列 = 这个进程就在当前所在的 PID namespace 顶层，即宿主机进程。

`NStgid` 的排序含义相同，但表示的是线程组 ID（TGID）；要看某个线程的视图用 `/proc/$PID/task/$TID/status`。

这行输出解释了一整类困惑：容器日志里那句 "killing pid 1"，在宿主机上对应的其实是 2192；在容器内 `kill 1` 与在宿主机上 `kill 2192` 是同一个动作；宿主机 `top` 里永远找不到这个容器的 "PID 1"。

## 由容器查宿主 PID

### Docker

```shell
docker inspect -f '{{.State.Pid}}' <容器>          # 主进程在宿主机的 PID
docker inspect -f '{{.State.Pid}} {{.Id}}' <容器>  # 顺带拿完整 64 位容器 ID
docker top <容器>                                   # 容器内进程树（列出来的全是宿主机 PID）
docker stats <容器> --no-stream                     # 资源视角
```

注意 `docker top` 底层就是读 `/proc`，所以它的 PID 列天然是宿主机编号；只有进到容器里（`docker exec`）看到的才是容器内编号。

### containerd 与 nerdctl

```shell
sudo ctr -n k8s.io  tasks ls          # Kubernetes 用的 containerd namespace，PID 列即宿主 PID
sudo ctr -n moby    tasks ls          # Docker Engine 托管的容器
sudo ctr -n default tasks ls          # 裸 containerd / nerdctl 默认分组
```

一个高频踩坑点：`ctr -n` 的 namespace 是 **containerd 自己的逻辑分组**，跟内核 namespace 毫无关系（`namespace.md` 里的 ns 才是内核的）。找不到容器时十有八九是 `-n` 给错了；运行时链路见 [containerd](/docs/CS/Container/k8s/containerd.md)。

如果机器上只有 `nerdctl`（或装了 `docker` 兼容 shim），直接按 Docker 的用法用即可。

### Kubernetes

从 Pod 名一路走到节点的宿主机 PID：

```shell
# 1) 控制面：确定节点 + 取容器 ID（带运行时前缀）
kubectl get pod <pod> -n <ns> -o wide
# → nginx   containerd://3f9a1b...（也可能是 docker://）

# 2) 到该节点上（ssh，或没有 ssh 时 kubectl debug node/<node> -it --image=alpine）
CID=$(kubectl get pod <pod> -n <ns> -o jsonpath='{.status.containerStatuses[0].containerID}' \
      | sed 's|.*://||')
sudo crictl inspect -o json $CID | jq -r '.info.pid'             # 容器在宿主机的 PID
sudo crictl inspect -o json $CID | jq -r '.status.metadata.name' # 容器名
```

`kubectl debug node/<node> -it --image=alpine` 起出来的调试 Pod 直接使用宿主机的 PID/Network/IPC namespace，宿主机根文件系统挂在 `/host`，没有 ssh 权限时用它最省事。

pause（沙箱）容器也是普通容器，要看 Pod 共享的那张网络栈，先 `crictl pods --name <pod>` 拿到沙箱 ID，再用 `crictl ps --pod <沙箱ID>` 找到 pause 容器本身，最后同样 inspect 取 `.info.pid`。pause 持有 net/ipc/uts ns 的机制见 [pause 容器](/docs/CS/Container/k8s/Pod.md?id=pause-容器)。

## 由宿主 PID 反查容器

线上最常见的起手式其实是反过来的：`top` 里发现某个进程吃掉 12 个核，要回答"它是哪个容器"。

### 走 cgroup 路径

这是唯一**一定存在**的映射：任何 OCI 运行时在创建容器时都会把容器主进程写进 `cgroup.procs`。

```shell
cat /proc/$PID/cgroup
```

不同组合下的形态：

| 环境 | `/proc/PID/cgroup` 形态 |
|------|------------------------|
| cgroup v2 + Docker（systemd driver） | `0::/system.slice/docker-<64位ID>.scope` |
| cgroup v2 + K8s + containerd | `0::/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<PodUID，其中 - 已被替换成 _>.slice/cri-containerd-<64位ID>.scope` |
| cgroup v1 + Docker（cgroupfs driver） | 每个 controller 一行，`<controller>:/docker/<ID>` |
| 宿主机原生进程 | `0::/` 或 `/init.scope`、`/system.slice/sshd.service` 等，**不含容器 ID** |

最后一种正是区分"这个进程到底在不在容器里"的判据。

提取容器 ID 并翻译回容器名：

```shell
CID=$(awk -F/ '{print $NF}' /proc/$PID/cgroup | grep -oE '[0-9a-f]{64}')
docker ps --no-trunc --filter id=$CID --format '{{.Names}}\t{{.Image}}'   # Docker 路线
sudo crictl inspect -o json $CID | jq -r '.status.metadata.name'          # containerd 路线
```

注意 ID 长度：cgroup/systemd 路径里是**完整 64 位** ID，而 `docker ps` 默认只显示前 12 位，匹配时必须 `--no-trunc`。

反向也可以：`sudo ctr -n k8s.io containers info $CID` 能看到容器对应的 OCI spec（含 rootfs 路径、env、资源限额）。

### 走 namespace inode

当 cgroup 路径被某些运行时改写、或想确认"这两个进程是否在同一容器/同一网络栈"时，比对 namespace inode 最直接：

```shell
lsns -p $PID                                      # 列出该进程所属的各 namespace
readlink /proc/$PID/ns/pid                        # pid:[4026532186]
readlink /proc/$PID/ns/net
ls -l /proc/<疑似容器主进程>/ns/{pid,net,mnt}       # inode 相同 ⇒ 共享该 namespace
```

同一个 Pod 内两个业务容器的 `net` inode 必然相同（都 setns 进了 pause 的网络栈），但 `pid` inode 不同（除非开了 `shareProcessNamespace`）——这条规律很好用来验证 Sandbox 的理解是否正确。原理见 [ls -l /proc/$$/ns 的观察方法](/docs/CS/OS/Linux/namespace.md?id=setns-加入已有-namespace)。

如果手里只有 IP 没有 PID，也能从名字跳过去：

```shell
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{"\n"}}{{end}}' <容器>
```

反过来从连接找进程则用 `ss -tnp` 得到 PID，再走上面的 cgroup 反查。

### 在容器内部自查

站在容器里没有宿主视角时，仍然能拿到自己的标识：

```shell
cat /proc/self/cgroup      # 能读出自己的 scope 名，里面含完整容器 ID（需 cgroup ns 未进一步隔离）
hostname                   # Docker 默认把短容器 ID 作为 hostname
cat /proc/1/cmdline | tr '\0' ' '   # 入口进程命令行
```

不过容器内**无从得知**自己的宿主机 PID——这正是"边界"的意义，必须回到宿主机上用上面的方法。

## 拿到 PID 之后

宿主 PID 是通往 `/proc` 全部细节的句柄，以下都**不需要进容器，也不需要 daemon**：

```shell
# 文件系统：不 exec 也能读容器 rootfs
ls -l /proc/$PID/root                 # 容器看到的 /
cat /proc/$PID/mountinfo              # 容器实际挂载表
cat /proc/$PID/environ | tr '\0' '\n' # K8s 注入的变量、业务环境变量
ls -l /proc/$PID/cwd /proc/$PID/exe

# 连接与 fd
sudo ls -l /proc/$PID/fd              # 打开的 socket / 管道
sudo nsenter -t $PID -n ss -lntup     # 借容器的网络栈，用宿主机的 ss

# 状态与性能
cat /proc/$PID/status                 # Threads / 上下文切换次数 / NSpid
cat /proc/$PID/stack                  # 内核栈（进程卡在 D 状态时最有价值）
cat /proc/$PID/wchan
cat /proc/$PID/limits
sudo perf top -p $PID
sudo perf record -ag -p $PID -- sleep 30    # 火焰图

# 抢占 / 调度视角
cat /proc/$PID/sched                  # se.statistics / avg per cpu
```

进容器执行命令用 `nsenter`，它跟 `docker exec` 的底层都是 setns(2)，但有两点不同——**不经过 daemon**（daemon 挂了照样能用），**可以选择只借某几个 namespace**：

```shell
sudo nsenter -t $PID -a /bin/sh                          # 全量：uts/ipc/net/pid/mnt 全进
sudo nsenter -t $PID -n ss -lntup                        # 只借网络栈，跑宿主二进制
sudo nsenter -t $PID -p ps aux                           # 只借 PID 视图
sudo nsenter -t $PID -r -w /bin/sh                       # root/cwd 也切过去（-r/-w 默认就是 /proc/$PID/{root,cwd}）
```

对 distroless / scratch 这类没有 shell 的镜像，`nsenter -a /bin/sh` 必然失败（PATH 里根本没有 `/bin/sh`）。正确姿势是**不要进 mount namespace**，只借需要的那一个 ns，用宿主机上的二进制去观察容器视图——这也是 `-n` / `-p` 单独使用的实际价值。

## 速查表

| 想做的事 | 命令 |
|----------|------|
| 容器主进程在宿主机的 PID | `docker inspect -f '{{.State.Pid}}' <容器>` |
| 容器内所有进程（宿主编号） | `docker top <容器>` |
| containerd / CRI 侧取 PID | `ctr -n k8s.io tasks ls`、`crictl inspect -o json <cid> \| jq .info.pid` |
| Pod → 容器 ID | `kubectl get pod -o jsonpath='{.status.containerStatuses[*].containerID}'` |
| PID → 是否容器化 / 容器 ID | `cat /proc/<pid>/cgroup`（看最后一段有无 64 位 hex） |
| 容器 ID → 容器名 | `docker ps --no-trunc --filter id=<cid>` |
| PID → 所属 namespace | `lsns -p <pid>`、`readlink /proc/<pid>/ns/*` |
| 判断两个进程是否同一容器 | 比对 `/proc/<pid>/ns/{pid,mnt,net}` 的 inode |
| 免 exec 读容器文件 | `ls /proc/<pid>/root/<path>` |
| 免 exec 看容器端口 | `nsenter -t <pid> -n ss -lntup` |
| 进容器排障（daemon 已挂） | `nsenter -t <pid> -a /bin/sh` |
| 区分是/不是容器进程 | `/proc/<pid>/cgroup` 末尾是否含 `<cid>.scope` 或 `docker/<cid>` |

## 例外与坑

- **Docker Desktop（macOS / Windows）**：容器跑在 Linux VM 里，`docker inspect` 给的 PID 是 VM 内部的编号，在 macOS 上 `ps`/`nsenter` 全都对不上号。要进 VM 得先跳进去：
  ```shell
  docker run -it --rm --privileged --pid=host alpine nsenter -t 1 -m -u -n -i sh
  ```
- **多进程容器**：`docker inspect` 只给主进程（容器内 PID 1）。nginx 的 worker、Java 的线程池、sidecar 拉起的脚本都在别处，要看全用 `docker top` 或 `pstree -p $PID`。主进程 PID 稳定不代表业务进程稳定。
- **PID 1 的收尸职责**：容器内 PID 1 若不处理 `SIGCHLD`（业务直接以 shell 脚本/应用二进制作为入口），僵尸进程会堆在 `docker top` 里显示为 `<defunct>`。用 `docker run --init` 或 tini / dumb-init 兜底。
- **`hostPID: true` 的 Pod**：共享宿主机 PID namespace，容器内 `ps` 能看到并 `kill` 宿主机全部进程（等价于拿到了半个节点的管理权），但 cgroup 仍在原地，所以 `/proc/$PID/cgroup` 反查照旧有效。要动网络还得再加上 `hostNetwork`。
- **`shareProcessNamespace: true`**：Pod 内所有容器共享 PID namespace，跨容器能看到彼此的进程（但仍看不到 Pod 之外）。此时同一个 Pod 里两个容器的 `net` 与 `pid` inode 都相同。
- **rootless Docker / Podman / nerdctl**：多一层 user namespace 与 rootlesskit / slirp4netns，从"宿主"看到的其实是中间那一层 namespace 的编号，`NSpid` 会多出若干列；往上再追一层才是真正的宿主机 PID。
- **PID 数耗尽**：容器内进程/线程数达到 `pids_limit`（cgroup `pids.max`）后 `fork` 报 `resource temporarily unavailable`。看 `pids.current` 与 `/proc/$PID/status` 的 `Threads`。
- **容器已退出**：进程死了 `/proc/$PID` 随之消失，`nsenter` 无从下手，只剩 `crictl inspect` 里的 `status.reason` / `exitCode` 与节点上的 `/var/log/pods/<ns>_<pod>_<uid>/<container>/`。
- **`top` 在容器里不准**：`/proc` 感知不到 cgroup 限额，容器内 `top` 显示的是宿主机总量，生产上用 lxcfs 兜一层 fuse 版 `/proc`（现象与根因见 [Container](/docs/CS/Container/Container.md)）。

## Links

- [Container](/docs/CS/Container/Container.md)
- [Namespace](/docs/CS/OS/Linux/namespace.md)
- [Cgroup](/docs/CS/OS/Linux/cgroup.md)
- [containerd](/docs/CS/Container/k8s/containerd.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [K8s 排障](/docs/CS/Container/k8s/Issues.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [crictl](https://linuxcommandlibrary.com/man/crictl)
2. [How to Use crictl to Debug Container Runtime Issues on Kubernetes Nodes](https://oneuptime.com/blog/post/2026-02-09-crictl-debug-container-runtime/view)
3. [Building containers by hand: The PID namespace](https://www.redhat.com/en/blog/pid-namespace)
4. [proc_pid_status(5) — Linux manual page](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html)
5. [Inspecting a container from the host — PIDs, namespaces, cgroups](https://runbook.academy/courses/docker/lessons/docker-inspecting-namespaces-and-cgroups-from-the-host)
