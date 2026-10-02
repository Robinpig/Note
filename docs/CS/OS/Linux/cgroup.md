## Introduction

从 2.6.24 版本开始，linux 内核提供了一个叫做 cgroups的特性
cgroup 和 namespace 类似，也是将进程进行分组，但它的目的和 namespace 不一样，namespace 是为了隔离进程组之间的资源，而 cgroup 是为了对一组进程进行统一的资源监控和限制

`cgroup` 是 "control group" 的缩写，**不首字母大写**。单数形式指整个特性本身，也作限定语用（如 "cgroup controllers"）；明确指多个独立控制组时用复数 "cgroups"。

cgroup 是一种把进程**按层级组织**起来、并沿这条层级**受控且可配置地**分配系统资源的机制。

cgroup 大体由两部分组成——**core** 与 **controller**：core 负责把进程按层级组织起来；controller 负责沿层级分配某一类具体资源（也有不用于资源分配的辅助型 controller）。

cgroup 构成一棵**树**，系统中的每个进程**有且仅属于一个** cgroup；一个进程的所有线程同属一个 cgroup。进程创建时进入其父进程当时所在的 cgroup，之后可被迁移到别的 cgroup，且迁移**不影响**它已有的后代进程。

在结构约束下，controller 可以在某个 cgroup 上有选择地启用或关闭。**所有 controller 的行为都是层级化的**——在某 cgroup 上启用一个 controller，会作用于该 cgroup 及其整个子树内的所有进程；在嵌套 cgroup 上启用只会**进一步收紧**资源分配；越靠近根的层级所设的限制，越不能被更远的层级覆盖。

因此，cgroup 是内核内置的一套设施，让管理员能给系统中的任意进程设置资源使用限制。总的来说，cgroup 控制：

- 每个进程的 CPU 份额（shares）；
- 每个进程的内存限制；
- 每个进程的块设备 I/O；
- 哪些网络报文被识别为同一类型，以便其他应用实施流量规则。

```shell
cd /sys/fs/cgroup/cpu,cpuacct
mkdir test
cd test
echo 100000 > cpu.cfs_period_us // 100ms 
echo 100000 > cpu.cfs_quota_us //200ms 
echo {$pid} > cgroup.procs
```

所有 `cgroup_subsys_state`（如 cpu、cpuset、memory）都继承自各自不同的祖先节点。

| cgroup_subsys_state type | ancestor |
| --- | --- |
| cpu |  task_group |
| memory | mem_cgroup |
| dev | dev_cgroup |


```c
struct cgroup {
	/* Private pointers for each registered subsystem */
	struct cgroup_subsys_state __rcu *subsys[CGROUP_SUBSYS_COUNT];
};  
```


一个进程是通过 task_struct 结构体下的 *cgroups 指向自己关联的task_group、mem_cgroup 等

```c
struct task_struct {
  #ifdef CONFIG_CGROUPS
	/* Control Group info protected by css_set_lock: */
	struct css_set __rcu		*cgroups;
	/* cg_list protected by css_set_lock and tsk->alloc_lock: */
	struct list_head		cg_list;
#endif
}
```

`css_set` 是持有一组 `cgroup_subsys_state` 指针的结构体。
它节省了 task 结构体的空间，并加速 `fork()` / `exit()`——因为一次 inc/dec 加一次 `list_add()` / `del()`，就能为任务调整整个 cgroup 集合的引用计数。

```c
struct css_set {
	/*
	 * Set of subsystem states, one for each subsystem. This array is
	 * immutable after creation apart from the init_css_set during
	 * subsystem registration (at boot time).
	 */
	struct cgroup_subsys_state *subsys[CGROUP_SUBSYS_COUNT];
}    
```

对于容器下所有进程的CPU资源限制是通过 task_group 实现的， 内存资源是通过 mem_cgroup 实现的





## CPU 限制如何落到调度器

容器 CPU 限额（`docker --cpus=1.5` / K8s `resources.limits.cpu: "1500m"`）最终换算为 quota/period 写进 cgroup；内核侧由 **task_group** 承接——cpu 子系统的 `cgroup_subsys_state` 对应一个 task_group，其下每个 CPU 各有一个受配额约束的 cfs_rq。每个周期内配额耗尽即触发 throttle，整个 cfs_rq 被摘出调度，组内进程全部暂停到下个周期补足配额——这就是容器被 **CPU throttling** 的根源（实现细节见 [CFS 带宽控制](/docs/CS/OS/Linux/proc/fair.md?id=cfs-带宽控制)）。

注意与实时任务区分：RT 任务受 [RT throttling](/docs/CS/OS/Linux/proc/rt.md?id=rt-throttling) 约束（默认 95%），与 CFS 配额是两套独立机制。

## 内存限制与 OOM

内存的资源分配由 **memory controller**（内核里的 **memcg**）承担：它把内存用量沿 cgroup 层级记账，并提供一组限额（v2 `memory.max` / `memory.high`，v1 `memory.limit_in_bytes`）。超限的处理分三档——越过 `memory.high` 只**节流**、不杀进程；越过 `memory.max` 先在**本组内**做局部回收；回收不出来才在**该 memcg 的进程集合里**挑 victim 做 OOM kill。

memcg 的内核机制（`struct mem_cgroup`、per-memcg lruvec、页与内核对象两条记账路径、全部接口语义与层级保护、K8s QoS 映射与排障口径）已独立成篇，见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)。本节只留在 cgroup 通用机制里的那一层关系：**memcg 只是挂在 cgroup 层级上的一个 controller**，因此它的限额同样受"越靠近根越不可被覆盖"这条层级规则约束（见 [Introduction](#introduction)）。容器被 OOM kill、退出码 137（OOMKilled）这一现象层记录见 [Issues](/docs/CS/Container/k8s/Issues.md)。

## cgroup v1 与 v2

| | v1 | v2 |
| :-- | :-- | :-- |
| 挂载 | 每个 controller 独立层级（`/sys/fs/cgroup/cpu`、`memory`…） | 统一层级（`/sys/fs/cgroup` 一棵树） |
| CPU 限额 | `cpu.cfs_quota_us` / `cpu.cfs_period_us` | `cpu.max`（"quota period"） |
| CPU 权重 | `cpu.shares`（2~262144） | `cpu.weight`（1~10000） |
| 内存 | `memory.limit_in_bytes` | `memory.max` + `memory.high`（软限先回收） |
| 结构约束 | controller 各自为政，一个进程可属不同层级 | no-internal-process：有进程的 cgroup 不能再启用 controller |

容器运行时趋势：Docker 20.10+ / containerd 1.6+（K8s 1.25+）默认 v2。上文 shell 示例是 v1 写法；v2 等价操作同样是 mkdir + echo，只是文件名换成了 `cpu.max`、`memory.max`。

`/proc` 不感知 cgroup 的问题（容器内 top 显示宿主机数据）在 v2 也没有根治，生产常用 lxcfs 在容器内挂载 fuse 版 `/proc` 修正（现象与原因见 [Container](/docs/CS/Container/Container.md)）。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Container](/docs/CS/Container/Container.md)
- [CFS 带宽控制](/docs/CS/OS/Linux/proc/fair.md?id=cfs-带宽控制)
- [RT throttling](/docs/CS/OS/Linux/proc/rt.md?id=rt-throttling)
- [容器知识地图](/docs/CS/Container/README.md)
