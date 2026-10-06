## Introduction

前两篇讲机制（[知识地图](/docs/CS/OS/Linux/cgroup/README.md) / [控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)），本文讲**这些机制在容器里怎么落地** —— 为什么你的容器里 `memory.max` 改不了、为什么 `nsdelegate` 必须在挂载时给、以及 systemd 的 `Delegate=` 到底委派了什么。

委派的本质是**权限边界的划定**：把 cgroup 子树的一部分所有权交给一个受限的进程（容器内的 init、systemd 服务），让它能在自己的子树里配置资源，而不能越界影响全局。

## 三种隔离层次

cgroup 委派要同时配合 namespace 才能形成完整隔离。三者职责不同：

| 机制 | 隔离什么 | 谁提供 |
| :-- | :-- | :-- |
| **cgroup namespace** | 看到的 cgroup 树范围（视图） | `CLONE_NEWCGROUP` |
| **cgroup 委派** | 子树内的配置权限（能力） | `CFTYPE_NS_DELEGATABLE` + `nsdelegate` |
| **cgroup v2 统一层级** | 树的结构本身 | 单一 kernfs 树 |

namespace 管"能看到什么"，委派管"能改什么"。**两者独立**：可以看到但改不了，也可以（理论上）改得了但看不到更多。

## nsdelegate：委派的开关

v2 挂载时的 `nsdelegate` 选项是委派的**总开关**。它标记在 root 上：

```c
	case Opt_nsdelegate:
		ctx->flags |= CGRP_ROOT_NS_DELEGATE;
```

`cgroup_do_get_tree()` 里的这段逻辑是"非 init cgroup namespace 看到假根"的实现：

```c
	/*
	 * In non-init cgroup namespace, instead of root cgroup's dentry,
	 * we return the dentry corresponding to the cgroupns->root_cgrp.
	 */
	if (!ret && ctx->ns != &init_cgroup_ns) {
		...
		cgrp = cset_cgroup_from_root(ctx->ns->root_cset, ctx->root);
		...
		nsdentry = kernfs_node_dentry(cgrp->kn, sb);
		dput(fc->root);
		...
		fc->root = nsdentry;
	}
```

**在非 init cgroup namespace 里挂载 cgroup2，树的根不是你以为的根，而是该 namespace 的 `root_cgrp`。** 容器内 `ls /sys/fs/cgroup` 看到的那一层"假根"就是这么来的。

### 静默失效：容器内改不了 mount options

v7.2 把所有 root flags 的应用都限制在 init namespace：

```c
static void apply_cgroup_root_flags(unsigned int root_flags)
{
	if (current->nsproxy->cgroup_ns == &init_cgroup_ns) {
		if (root_flags & CGRP_ROOT_NS_DELEGATE)
			cgrp_dfl_root.flags |= CGRP_ROOT_NS_DELEGATE;
		...
	}
}
```

这个 `if` 意味着：**在容器内 `mount -o nsdelegate,...` 或 `mount -o remount,memory_recursiveprot` 会静默无效** —— 不报错，flag 也不生效。

这是容器场景下最难查的一类问题。排查方法很简单：看 `/proc/self/cgroup` 的相对路径深度。如果进程在 `init_cgroup_ns` 里看到的是 `/`（单个 0），在容器里通常看到 `/some/path`（有层级）—— 层级深度就是"你已经离开根了"的证据。

## CFTYPE_NS_DELEGATABLE：哪些文件能跨边界写

委派边界不是"全部允许"或"全部禁止"，而是**逐文件**的。标志位：

```c
	CFTYPE_NS_DELEGATABLE	= (1 << 2),	/* writeable beyond delegation boundaries */
```

带这个标志的 cgroup 文件，即使写操作跨越了委派边界也会被放行。v7.2 里带此标志的只有少数几个：

| 文件 | 控制器 | 意义 |
| :-- | :-- | :-- |
| `memory.oom.group` | memory | 整组 OOM kill 的开关，允许上层容器决定 |
| `memory.reclaim` | memory | 主动回收，容器自己触发（配合 freezer） |
| `memory.swap.*` 部分 | memory | swap 限制 |

而绝大多数文件（`cpu.max`、`memory.max`、`cgroup.subtree_control`…）**没有**这个标志，因此写在委派边界外会返回 `-EACCES` / `EPERM`。

这解释了一个常见的容器内失败：

```shell
# 容器内
echo "max 1000000" > /sys/fs/cgroup/cpu.max
# bash: /sys/fs/cgroup/cpu.max: Read-only file system
```

不是文件不存在，是**跨越了委派边界**。要改必须在容器自己的 cgroup 目录里改（即 `cgroup.procs` 指向的那个）。

## systemd 的 Delegate=

systemd 服务级的资源控制靠 `Delegate=yes`。它做两件事：

1. 为该服务创建独立的 cgroup 子树；
2. 授予该子树内的配置权限（等价于 `CFTYPE_NS_DELEGATABLE` + `nsdelegate` 的效果）。

```ini
[Service]
Delegate=yes
MemoryMax=512M
CPUQuota=50%
TasksMax=64
```

一个容易误解的点：**`Delegate=yes` 是"允许服务自己往下配"，不是"systemd 不再管你"**。`MemoryMax=` 这类 systemd 指令仍然生效，写在服务的 cgroup 根上；`Delegate=yes` 让服务内部的进程能在这个子树里**继续创建子组并配置**。

反过来，**不写 `Delegate=yes` 但服务内自己 `mkdir` cgroup 目录会失败** —— 没有委派权限，`mkdir` 返回 `-EPERM`。这是"我的服务在容器里建不了 cgroup"这类问题的根因。

systemd 的 `MemoryMax` / `CPUQuota` 恰好是 `Delegate=yes` 时最容易验证的观测点：进服务内部读 `memory.max` / `cpu.max`，值应该与 unit 文件里写的一致。

## 容器运行时的默认行为

现代运行时（Docker 20.10+ / containerd 1.6+ / K8s 1.25+）默认 v2，并且**默认不给完整委派**：

| 运行时选项 | cgroup 视图 | 委派程度 |
| :-- | :-- | :-- |
| 默认 | 容器看到自己的 cgroup 作根 | 容器内通常**只读**或无法越界配置 |
| `--cgroupns=private` | 独立 cgroup namespace（看到假根） | 与上面配合使用 |
| `--cgroupns=host` | 宿主 cgroup namespace（看到全树） | 能看到全部，但仍受权限限制 |
| `--cgroup-parent` | 指定挂到宿主哪棵子树下 | 影响宿主侧限额归属 |

`--cgroupns=private` 与 `host` 的选择影响很大：private 模式下容器内 `ls /sys/fs/cgroup` 顶着那层假根，宿主 `docker top` / `kubectl top` 仍能正常定位；host 模式下容器内能看到整棵树，更便于排查但隔离性弱一些。

## 排查路径

遇到"容器里改不了 cgroup 配置"时，按这个顺序查：

**① 确认视图位置**

```shell
# 我在哪个 cgroup？
cat /proc/self/cgroup
# 输出若是 /kubepods.slice/.../cri-containerd-xxx.scope，说明已离开根
```

**② 确认能否创建子组**

```shell
mkdir /sys/fs/cgroup/test 2>&1   # 失败即无委派权限
```

**③ 确认单个文件权限**

```shell
ls -l /sys/fs/cgroup/cpu.max
cat /sys/sys/fs/cgroup/cpu.max
# 改动被拒 → -EACCES（越界）或 EROFS（挂载只读）
```

**④ 确认 v1 还是 v2**

```shell
stat -fc %T /sys/fs/cgroup
# cgroup2fs = v2；tmpfs 通常意味着你看到的是 v1 的某个控制器挂载
```

v1 时代"改不了"的常见原因是**控制器挂载错** —— 例如宿主没挂 `/sys/fs/cgroup/cpu` 层级，容器里自然无处可改。v2 统一层级后这个问题消失，但换成了委派边界问题。

**⑤ 宿主侧交叉验证**

```shell
# 宿主上看容器的实际限制
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current
docker inspect --format '{{.HostConfig.Memory}}' <container>
```

如果容器内读到 `max`（无限）而宿主侧有限额，说明限额打在了另一个层级（常见于 cgroupfs driver 与 systemd driver 混用）。

## 一个易错点：memory.max 生效时机

`memory.max` 写小之后，**不是立刻杀掉超额进程**。v7.2 的 `memory_max_write()` 会同步做一轮回收：

```c
	try_to_free_mem_cgroup_pages(..., MEMCG_RECLAIM_MAY_SWAP, NULL);
```

有 `MAX_RECLAIM_RETRIES` 次重试，每次之间调 `drain_all_stock`。只有回收不出来才触发 OOM。所以"设了 memory.max 但进程没马上死"是正常行为 —— 还在回收。

反过来，想**主动**让某组立刻释放内存，用 `memory.reclaim`（单位是**页数**，不是字节）：

```shell
echo "1048576" > memory.reclaim   # 尝试回收 1M 页（4 GiB）
```

## 冻结与终止在容器里的用法

`cgroup.freeze` 在容器场景下有两个实际用途：

1. **在线备份/快照**：冻结 cgroup 后所有进程进入不可中断状态，磁盘上的数据一致，读 `/proc/<pid>/*` 拿到的是一致状态。
2. **金丝雀发布**：冻结旧组 → 起新组 → 流量切走 → 解冻旧组回滚。

`cgroup.kill` 则是"整组终止"的原子操作，比逐个 kill 干净。它的实现是 `kill_seq++` 而非遍历，在进程迁移/退出时对比序号决定是否发信号，因此**大组也是 O(1)**。

需要注意 `cgroup.kill` 在 threaded cgroup 上返回 `-EOPNOTSUPP` —— 容器内如果用了线程级计费的配置，会发现 kill 不可用。

## 与其它子系统的接缝

- **memcg**：容器内存账单的完整机制见 [memcg](/docs/CS/OS/Linux/mm/memcg.md)。
- **namespace**：cgroup namespace 与其他 namespace 的配合见 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **LXC**：最完整的委派实践（非特权容器强依赖 cgroup 委派）见 [LXC](/docs/CS/OS/Linux/LXC.md)。
- **Docker/K8s 侧**：容器如何配置这些参数见 [Container](/docs/CS/Container/Container.md)。
- **v1 遗留**：见 [cgroup（旧笔记，v1 视角）](/docs/CS/OS/Linux/cgroup.md)。

## 排障速查

```shell
# 我在哪棵树、什么视角
cat /proc/self/cgroup
cat /proc/mounts | grep cgroup

# 委派能力自查
mkdir /sys/fs/cgroup/probe && rmdir /sys/fs/cgroup/probe && echo "有委派权限" || echo "无委派权限"
touch /sys/fs/cgroup/probe_file 2>&1 | head -1

# 单文件是否可写（区分 EACCES 与 EROFS）
for f in cpu.max memory.max cgroup.subtree_control; do
  echo "${f}: $(test -w /sys/fs/cgroup/$f && echo writable || echo readonly)"
done

# 快速定位限额（容器内）
cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current
cat /sys/fs/cgroup/cpu.max

# 冻结与终止
echo 1 > /sys/fs/cgroup/cgroup.freeze
grep frozen /sys/fs/cgroup/cgroup.events
echo 1 > /sys/fs/cgroup/cgroup.kill
```

## Links

- [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)
- [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)
- [cgroup（旧笔记，v1 视角）](/docs/CS/OS/Linux/cgroup.md)
- [cgroup memory 控制器 memcg](/docs/CS/OS/Linux/mm/memcg.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [LXC](/docs/CS/OS/Linux/LXC.md)
- [Container](/docs/CS/Container/Container.md)

## References

1. [systemd — Control Group Interface](https://systemd.io/CGROUP_DELEGATION/)
2. [systemd.resource-control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html)
3. [Linux Kernel Documentation — Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
4. [Docker — cgroup namespace](https://docs.docker.com/engine/reference/run/#cgroupns)
