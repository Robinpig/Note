## Introduction

cgroup 是 Linux 的资源控制机制。v7.2 里它的核心实现在 **`kernel/cgroup/cgroup.c`**（7500 余行）—— 注意这个路径：`kernel/cgroup.c` 顶层文件在 v7.2 只有 41 行，真正的核心在 `kernel/cgroup/` 目录里。同目录下 `cgroup-v1.o` 单独编译，是为兼容 v1 而存在的历史包袱。

cgroup v2 提供的核心能力只有一句话：**在统一的层级树上，让每棵子树按各自的配置记账与调度。** 它替代了 v1 时代"每个控制器挂一棵独立树"的做法。

```shell
# v2 的挂载点是 /sys/fs/cgroup
mount -t cgroup2 none /sys/fs/cgroup
ls /sys/fs/cgroup
# cgroup.controllers  cpuset.cpus  cpuset.mems  io.pressure
# cpu.pressure  memory.pressure  misc.capacity  pids.pressure
```

v1 则是每控制器一个独立挂载点：`/sys/fs/cgroup/cpu`、`/sys/fs/cgroup/memory`、`/sys/fs/cgroup/pids` 等，各自是一棵完整树。

## 三类位掩码：理解 v2 的关键

源码里用三个位掩码刻画控制器的归属，全局定义在 `kernel/cgroup/cgroup.c`：

```c
/* some controllers are not supported in the default hierarchy */
static u32 cgrp_dfl_inhibit_ss_mask;

/* some controllers are implicitly enabled on the default hierarchy */
static u32 cgrp_dfl_implicit_ss_mask;

/* some controllers can be threaded on the default hierarchy */
static u32 cgrp_dfl_threaded_ss_mask;
```

| 掩码 | 含义 | 效果 |
| :-- | :-- | :-- |
| `cgrp_dfl_inhibit_ss_mask` | **不能在**默认层级（v2）上启用 | 这类控制器只在 v1 可用 |
| `cgrp_dfl_implicit_ss_mask` | 在 v2 上**隐式启用** | 无需写 `+cpu`，但仍占 `cgroup.controllers` |
| `cgrp_dfl_threaded_ss_mask` | **可以** threaded | 允许在 threaded 模式下给单线程组计费 |

判断某个 cgroup 是否在默认层级上，用 `cgroup_on_dfl()`：

```c
bool cgroup_on_dfl(const struct cgroup *cgrp)
{
	return cgrp->root == &cgrp_dfl_root;
}
```

默认层级只有一个 root —— `cgrp_dfl_root`，它**始终存在但默认不可见**：

```c
struct cgroup_root cgrp_dfl_root = {
	.cgrp.self.rstat_cpu = &root_rstat_cpu,
	.cgrp.rstat_base_cpu = &root_rstat_base_cpu,
};

/*
 * The default hierarchy always exists but is hidden until mounted for the
 * first time.  This is for backward compatibility.
 */
bool cgrp_dfl_visible;
```

`cgrp_dfl_visible` 在 `cgroup_get_tree()` 里才被置 `true` —— 也就是说**v2 层级在你第一次挂载它之前根本不在文件系统中出现**。这个设计是为了让 v1 时代的脚本继续看到旧的挂载布局。

## 统一层级：一棵树装所有控制器

v1 时代每个控制器各建一棵树，于是"CPU 限额"和"内存限额"在两个互不相干的树里，进程迁移、限额联动全都要额外处理。v2 把它们合并成**一棵 kernfs 树**，每个控制器在每个 cgroup 目录下有自己的一组文件。

`cgroup_setup_root()` 是建立层级的核心，它按固定顺序做六件事：

```c
	kf_sops = root == &cgrp_dfl_root ?
		&cgroup_kf_syscall_ops : &cgroup1_kf_syscall_ops;

	root->kf_root = kernfs_create_root(kf_sops,
					   KERNFS_ROOT_CREATE_DEACTIVATED |
					   KERNFS_ROOT_SUPPORT_EXPORTOP |
					   KERNFS_ROOT_SUPPORT_USER_XATTR |
					   KERNFS_ROOT_INVARIANT_PARENT,
					   root_cgrp);
	/* ... */
	ret = css_populate_dir(&root_cgrp->self);
	ret = css_rstat_init(&root_cgrp->self);
	ret = rebind_subsystems(root, ss_mask);
```

四个 kernfs 标志里有两个直接对应可观测性：`SUPPORT_EXPORTOP` 让 `CONFIG_CGROUP_EXPORT` 的设备能读控制器状态，`SUPPORT_USER_XATTR` 允许用户扩展属性。

`rebind_subsystems(root, ss_mask)` 是把控制器挂到这棵树上。**如果同一个控制器已经被 v1 的树占用，这里会失败**：

```c
		/*
		 * If @ss has non-root csses attached to it, can't move.
		 * If @ss is an implicit controller, it is exempt from this
		 * rule and can be stolen.
		 */
		if (css_next_child(NULL, cgroup_css(&ss->root->cgrp, ss)) &&
		    !ss->implicit_on_dfl)
			return -EBUSY;

		/* can't move between two non-dummy roots either */
		if (ss->root != &cgrp_dfl_root && dst_root != &cgrp_dfl_root)
			return -EBUSY;
```

这就是"**同一控制器不能同时在 v1 和 v2 启用**"的实现方式 —— 隐式控制器（`implicit_on_dfl`）是例外，可以被"抢走"。迁移路径就是先在 v1 卸载（`umount /sys/fs/cgroup/cpu` 之类），再在 v2 启用。

函数末尾有个值得一提的注释：

```c
	/*
	 * There must be no failure case after here, since rebinding takes
	 * care of subsystems' refcounts, which are explicitly dropped in the
	 * failure exit path.
	 */
	list_add_rcu(&root->root_list, &cgroup_roots);
```

即 `list_add_rcu()` 之后一旦出错，引用计数已经交出去了，**无法安全回滚**。

## no-internal-process：v2 最反直觉的规则

v2 有一条初学者必踩的规则：**一个非根 cgroup 上有进程时，不能在该 cgroup 上启用控制器**（不能写 `+cpu`）。源码：

```c
	/*
	 * Controllers can't be enabled for a cgroup with tasks to avoid
	 * child cgroups competing against tasks.
	 */
	if (cgroup_has_tasks(cgrp))
		return -EBUSY;
```

理由是**竞争**：如果 cgroup 自己有进程，又给它的子 cgroup 配了 CPU 权重/份额，那这个 cgroup 的进程和它子 cgroup 的进程就在竞争同一份资源，而记账规则不一致，容易出现"限额被绕过"的困惑。

所以典型的 v2 配置步骤是**先建子组、再放进程**：

```shell
# 正确：先创建子组，在父组上开控制器，最后才放进程
mkdir /sys/fs/cgroup/mygroup
echo "+cpu +memory" > /sys/fs/cgroup/cgroup.subtree_control
echo $$ > /sys/fs/cgroup/mygroup/cgroup.procs
```

### 三处豁免

`cgroup_migrate_add_task()` 里这条规则有两处豁免，都以 `cgroup_can_be_thread_root()` 为条件：

```c
	/*
	 * If @dst_cgrp is already or can become a thread root or is
	 * threaded, it doesn't matter.
	 */
	if (cgroup_can_be_thread_root(dst_cgrp) || cgroup_is_threaded(dst_cgrp))
		return 0;

	/* apply no-internal-process constraint */
	if (dst_cgrp->subtree_control)
		return -EBUSY;
```

第一处是目标 cgroup 已经是（或能成为）thread root；第二处是目标已开启 `subtree_control` —— 注意这两个判断是"或"关系：**只要有一个豁免成立就允许放进程**。

`cgroup_can_be_thread_root()` 的判定本身有四层：

```c
static bool cgroup_can_be_thread_root(struct cgroup *cgrp)
{
	/* mixables don't care */
	if (cgroup_is_mixable(cgrp))
		return true;

	/* domain roots can't be nested under threaded */
	if (cgroup_is_threaded(cgrp))
		return false;

	/* can only have either domain or threaded children */
	if (READ_ONCE(cgrp->nr_populated_domain_children))
		return false;

	/* and no domain controllers can be enabled */
	if (cgrp->subtree_control & ~cgrp_dfl_threaded_ss_mask)
		return false;

	return true;
}
```

而 `cgroup_is_mixable()` 只认根 cgroup：

```c
/* can @cgrp host both domain and threaded children? */
static bool cgroup_is_mixable(struct cgroup *cgrp)
{
	/*
	 * Root isn't under domain level resource control exempting it from
	 * the no-internal-process constraint, so it can serve as a thread
	 * root and a parent of resource domains at the same time.
	 */
	return !cgroup_parent(cgrp);
}
```

**根 cgroup 不受 no-internal-process 约束** —— 这就是为什么系统级限制（`/sys/fs/cgroup/cpu.max`）可以直接在根上设，而子组不行。

## threaded 模式：线程级计费

threaded 模式是 v2 特有的能力，用来解决"进程级记账 vs 线程级记账"的矛盾。在一个标了 `threaded` 的 cgroup 里，**进程被当作线程看待**，因此可以塞进进程（绕过 no-internal-process），同时每个线程单独计费。

判定一组 cgroup 是否 threaded 的判据极简：

```c
static bool cgroup_is_threaded(struct cgroup *cgrp)
{
	return cgrp->dom_cgrp != cgrp;
}
```

**`dom_cgrp != cgrp` 即为 threaded** —— 领域（domain）cgroup 指向自己，threaded cgroup 指向它的领域祖先。

配套的三个判定：

| 函数 | 含义 |
| :-- | :-- |
| `cgroup_is_mixable(cgrp)` | 能否同时容纳 domain 与 threaded 子节点（仅根 cgroup） |
| `cgroup_is_thread_root(cgrp)` | 是否为某 threaded 子树的根 |
| `cgroup_is_valid_domain(cgrp)` | 能否作为有效 domain（祖先链上不能有断裂） |

`cgroup_is_thread_root()` 的判定值得看，它揭示了 threaded 的两种进入方式：

```c
	/* a domain w/ threaded children is a thread root */
	if (cgrp->nr_threaded_children)
		return true;

	/*
	 * A domain which has tasks and explicit threaded controllers
	 * enabled is a thread root.
	 */
	if (cgroup_has_tasks(cgrp) &&
	    (cgrp->subtree_control & cgrp_dfl_threaded_ss_mask))
		return true;
```

一是**有 threaded 子节点**（自下而上成为 thread root），二是**自己有进程且启用了可 threaded 控制器**（自上而下）。第二条正是"线程级计费"的实际入口。

`cgroup_is_valid_domain()` 里的注释有个源码级 typo，可以作为"这段代码在 v7.2 确实这样写"的旁证：

```c
/* a domain which isn't connected to the root w/o brekage can't be used */
```

`brekage` 应为 `breakage`。

## 挂载选项

`cgroup2_parse_param()` 定义了 v2 挂载时**全部**可用的 mount options——数量比多数人预期的少：

```c
	switch (opt) {
	case Opt_nsdelegate:
		ctx->flags |= CGRP_ROOT_NS_DELEGATE;
	case Opt_favordynmods:
		ctx->flags |= CGRP_ROOT_FAVOR_DYNMODS;
	case Opt_memory_localevents:
		ctx->flags |= CGRP_ROOT_MEMORY_LOCAL_EVENTS;
	case Opt_memory_recursiveprot:
		ctx->flags |= CGRP_ROOT_MEMORY_RECURSIVE_PROT;
	case Opt_memory_hugetlb_accounting:
		ctx->flags |= CGRP_ROOT_MEMORY_HUGETLB_ACCOUNTING;
	case Opt_pids_localevents:
		ctx->flags |= CGRP_ROOT_PIDS_LOCAL_EVENTS;
	}
```

| 选项 | 作用 |
| :-- | :-- |
| `nsdelegate` | 在非 init cgroup namespace 里也委派控制器 |
| `favordynmods` | 偏好把模块放到非根 cgroup（内核对象归属） |
| `memory_localevents` | memory 压力事件只向本地层级上报 |
| `memory_recursiveprot` | memory 的 `min.low`/`min.high` 保护**递归**到后代 |
| `memory_hugetlb_accounting` | 把 hugetlb 页计入 memory 控制器 |
| `pids_localevents` | pids 压力事件只向本地层级上报 |

`memory_recursiveprot` 是个实用的例子：默认情况下 `memory.min` 只保护当前 cgroup 自己的页，开了这个选项后保护会递归应用到后代，让整棵子树的内存下限都得到保障。

`favordynmods` 与全局变量对应：

```c
static bool have_favordynmods __ro_after_init = IS_ENABLED(CONFIG_FAVOR_DYNMODS);
```

它还有编译期开关 `CONFIG_FAVOR_DYNMODS`，由 `cgroup_favor_dynmods()` 生效。

**所有这些选项只允许在 init cgroup namespace 里设置**：

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

这个判断是理解"容器里为什么改不了这些选项"的答案 —— 见 [委派与命名空间](#委派与命名空间)。

## 进程迁移

v2 的迁移接口是 `cgroup_migrate_execute()`，由 `cgroup_migrate_add_task()` 逐个添任务后统一执行。写入 `cgroup.procs`（按线程组）与 `cgroup.threads`（按线程）是两条不同路径。

内核用 `css_set` 优化迁移开销：一个 `css_set` 缓存了一个任务在各控制器中的 css 指针。迁移只在该集合不存在时新建（`link_css_set()`），否则直接复用。`cgroup_setup_root()` 里那句"allocate 2x"的注释解释了这个余量：

```c
	/*
	 * We're accessing css_set_count without locking css_set_lock here,
	 * but that's OK - it can only be increased by someone holding
	 * cgroup_lock, and that's us.  Later rebinding may disable
	 * controllers on the default hierarchy and thus create new csets,
	 * which can't be more than the existing ones.  Allocate 2x.
	 */
	ret = allocate_cgrp_cset_links(2 * css_set_count, &tmp_links);
```

因为后续 rebind 可能禁用控制器从而新建 css_set，但**新建数量不会超过现有 css_set 数量**，所以预分配 2 倍一定够。

## 委派与命名空间

`cgroup_do_get_tree()` 里有一段决定"这次挂载看到什么"的逻辑：

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

**在非 init cgroup namespace 里挂载 cgroup2，得到的树根不是真正的根，而是该 namespace 的 `root_cgrp`。** 这就是容器里 `docker exec` 后看到 `/sys/fs/cgroup` 顶着一层假根的原因 —— 配合 `nsdelegate`，容器内的子 cgroup 可以被委派出去。

这个机制的另一面就是 `apply_cgroup_root_flags()` 里的 `if (current->nsproxy->cgroup_ns == &init_cgroup_ns)` —— **在容器内 `mount -o memory_recursiveprot` 会静默无效**（flag 不被应用，但也不报错）。这类"静默失效"是容器场景下最难查的一类问题。

## 与其它子系统的接缝

- **内存**：cgroup memory 控制器的记账与回收走 [memcg](/docs/CS/OS/Linux/mm/memcg.md)，那是本 KB 里最详细的 cgroup 相关笔记。
- **调度器**：`cpu` 控制器的 cgroup 公平性由 fair 调度器的 vruntime 记账实现，见 [fair](/docs/CS/OS/Linux/proc/fair.md) 的 CFS 带宽控制。
- **冻结**：`cgroup.freeze` 与 `cgroup.kill` 是 cgroup 核心自带的两个文件（v2 无独立 freezer 控制器），语义与 v1 的 `freezer.state` 差异见 [控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md?id=freezer-冻结与终止)。
- **namespace**：cgroup namespace 与 pid/network namespace 的配合见 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **容器**：委派的实践侧（systemd `Delegate=`、`cgroups=private`）见 [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md)。
- **控制文件接口**：各控制器的文件与可调参数见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)。

## 排障速查

```shell
# 层级总览
cat /proc/self/cgroup              # 本进程在各 hierarchy 中的位置
mount | grep cgroup                # v2 是 cgroup2，v1 是 cgroup 各控制器
ls /sys/fs/cgroup/                # 顶层文件列表

# 某 cgroup 的能力与状态
cat /sys/fs/cgroup/mygroup/cgroup.controllers        # 本 cgroup 可启用的控制器
cat /sys/fs/cgroup/mygroup/cgroup.subtree_control    # 已启用于子组的控制器
cat /sys/fs/cgroup/mygroup/cgroup.procs              # 直接成员（进程视图）
cat /sys/fs/cgroup/mygroup/cgroup.threads            # 直接成员（线程视图）
cat /sys/fs/cgroup/mygroup/cgroup.type               # domain / domain threaded / threaded

# 启用失败排查（最常见）
# -EBUSY = 有进程时启控制器 → 先建子组再放进程
# -EBUSY = 控制器已在 v1 挂载 → 先 umount v1 那棵树
# -EINVAL = 该控制器不支持 v2（查 inhibit_ss_mask）

# 内存/IO 压力
cat /sys/fs/cgroup/mygroup/memory.pressure
cat /sys/fs/cgroup/mygroup/cpu.pressure
```

## Links

- [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)
- [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md)
- [cgroup memory 控制器 memcg](/docs/CS/OS/Linux/mm/memcg.md)
- [进程调度 fair](/docs/CS/OS/Linux/proc/fair.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [cgroup（旧笔记，v1 视角）](/docs/CS/OS/Linux/cgroup.md)

## References

1. [Linux Kernel Documentation — Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
2. [Linux Kernel Documentation — cgroup v1](https://docs.kernel.org/admin-guide/cgroup-v1/index.html)
3. [systemd — Control Group Interface](https://systemd.io/CGROUP_DELEGATION/)
