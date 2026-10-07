## Introduction

**ptrace** 是 Linux 给"一个进程观测并控制另一个进程"提供的唯一系统调用入口。 tracer 通过它可以读写 tracee 的**内存**与**寄存器**、让 tracee 在指定事件上**停下来**、**单步**执行它、以及**拦截并改写**它的系统调用。[strace](/docs/CS/OS/Linux/Tools/strace.md) 打印系统调用序列、[GDB](/docs/CS/C/GDB.md) 下断点做单步，底层都是这一套接口。

ptrace 的实现横跨三层：

- **通用层** `kernel/ptrace.c` + `kernel/signal.c`：关系建立、停止通知、请求分发、安全校验，与架构无关；
- **进入层** `include/linux/entry-common.h`：系统调用入口处的 ptrace / seccomp 拦截点；
- **架构层** `arch/x86/kernel/ptrace.c`、`arch/x86/kernel/step.c`：寄存器布局、regset、单步与硬件断点。

本文按「关系如何建立 → 停止如何发生 → 事件如何上报 → 数据如何读写 → 架构层怎么做 → 安全边界在哪」的顺序展开，源码对照 Linux v7.2.7。

## Why Such a System Call Is Needed

一个调试器需要三件事，而这三件事都是"越过进程边界"的，普通系统调用一个都做不了：

1. **读改写另一个进程的完整状态**——地址空间里的任意字节、全部通用寄存器、浮点状态、调试寄存器；
2. **让它在指定时刻停下来，并且是"可恢复"地停**——不是杀死，而是冻结在原地等 tracer 检查完再继续；
3. **在系统调用边界上插入控制权**——入口处能看到参数并可以改，出口处能看到返回值并可以改。

ptrace 的答案是一个**二元关系 + 停止状态机**：先在两个 task 之间建立 tracer / tracee 关系（通过改写 `task_struct` 的父子指针复用进程模型的既有语义），之后由 tracee 在各种事件点上主动**陷入内核并睡眠**，tracer 用 `waitpid` 收事件、用 ptrace 请求读写状态、用 resume 类请求放行。

## System Call Entry

用户态看到的是四个参数：

```c
long ptrace(enum __ptrace_request request, pid_t pid,
            void *addr, void *data);
```

内核入口非常短，四步分流（`kernel/ptrace.c`）：

```c
SYSCALL_DEFINE4(ptrace, long, request, long, pid, unsigned long, addr,
		unsigned long, data)
{
	struct task_struct *child;
	long ret;

	if (request == PTRACE_TRACEME) {
		ret = ptrace_traceme();
		goto out;
	}

	child = find_get_task_by_vpid(pid);
	if (!child) {
		ret = -ESRCH;
		goto out;
	}

	if (request == PTRACE_ATTACH || request == PTRACE_SEIZE) {
		ret = ptrace_attach(child, request, addr, data);
		goto out_put_task_struct;
	}

	ret = ptrace_check_attach(child, request == PTRACE_KILL ||
				  request == PTRACE_INTERRUPT);
	if (ret < 0)
		goto out_put_task_struct;

	ret = arch_ptrace(child, request, addr, data);
	if (ret || request != PTRACE_DETACH)
		ptrace_unfreeze_traced(child);

 out_put_task_struct:
	put_task_struct(child);
 out:
	return ret;
}
```

要点有三个：

- **TRACEME 是"自己请求被跟踪"**，不经过 pid 查找，所以被单独放在最前面；
- **ATTACH / SEIZE 不需要 tracee 已经停止**，它们是唯一能在 tracee 任意状态下发出的请求；
- **其余所有请求都要先过 `ptrace_check_attach()`**：确认 tracee 确实被 current 跟踪、并且（除 KILL / INTERRUPT 外）确实停在 `__TASK_TRACED` 上。确认成功时顺带把 tracee **冻结**（下一节），请求处理完再解冻。

请求本身按功能可分成六类：

| 类别 | 请求 | 落点 |
| --- | --- | --- |
| 建立/解除关系 | `TRACEME` `ATTACH` `SEIZE` `DETACH` | `ptrace_traceme()` / `ptrace_attach()` / `ptrace_detach()` |
| 恢复执行 | `CONT` `SYSCALL` `SINGLESTEP` `SYSEMU` `KILL` `LISTEN` `INTERRUPT` | `ptrace_resume()` |
| 读写内存 | `PEEKTEXT/PEEKDATA` `POKETEXT/POKEDATA` | `ptrace_access_vm()` |
| 读写寄存器 | `GETREGS/SETREGS` `GETFPREGS` `PEEKUSR/POKEUSR` `GETREGSET/SETREGSET` | 架构层 `arch_ptrace()` |
| 选项与事件 | `SETOPTIONS` `GETEVENTMSG` `GETSIGINFO/SETSIGINFO` `PEEKSIGINFO` | `ptrace_request()` |
| 扩展接口 | `GET_SYSCALL_INFO/SET_SYSCALL_INFO` `SECCOMP_GET_FILTER` `GET_RSEQ_CONFIGURATION` `*_SYSCALL_USER_DISPATCH_CONFIG` | `ptrace_request()` |

注意分发顺序是**架构优先**：`arch_ptrace()` 先处理，不认识的请求才回落到通用的 `ptrace_request()`。所以 `PTRACE_GETREGS` 这类架构相关的由 x86 自己实现，而 `PTRACE_SETOPTIONS` 这类与架构无关的由通用层处理。

## Establishing the Relationship: TRACEME and ATTACH / SEIZE

### PTRACE_TRACEME: Let the Current Process Be Traced by Its Parent

最短的一条路，只是把自己标记上、把 parent 指向 real_parent：

```c
static int ptrace_traceme(void)
{
	int ret = -EPERM;

	write_lock_irq(&tasklist_lock);
	/* Are we already being traced? */
	if (!current->ptrace) {
		ret = security_ptrace_traceme(current->parent);
		/*
		 * Check PF_EXITING to ensure ->real_parent has not passed
		 * exit_ptrace(). Otherwise we don't report the error but
		 * pretend ->real_parent untraces us right after return.
		 */
		if (!ret && !(current->real_parent->flags & PF_EXITING)) {
			current->ptrace = PT_PTRACED;
			ptrace_link(current, current->real_parent);
		}
	}
	write_unlock_irq(&tasklist_lock);

	return ret;
}
```

典型用法是"fork + 子进程 TRACEME + exec"，这样 tracer 能保证从程序第一条指令起就在场。

### PTRACE_ATTACH / PTRACE_SEIZE: Attaching from Outside

```c
static int ptrace_attach(struct task_struct *task, long request,
			 unsigned long addr,
			 unsigned long flags)
{
	bool seize = (request == PTRACE_SEIZE);
	int retval;

	if (seize) {
		if (addr != 0)
			return -EIO;
		/*
		 * This duplicates the check in check_ptrace_options() because
		 * ptrace_attach() and ptrace_setoptions() have historically
		 * used different error codes for unknown ptrace options.
		 */
		if (flags & ~(unsigned long)PTRACE_O_MASK)
			return -EIO;

		retval = check_ptrace_options(flags);
		if (retval)
			return retval;
		flags = PT_PTRACED | PT_SEIZED | (flags << PT_OPT_FLAG_SHIFT);
	} else {
		flags = PT_PTRACED;
	}

	audit_ptrace(task);

	if (unlikely(task->flags & PF_KTHREAD))
		return -EPERM;
	if (same_thread_group(task, current))
		return -EPERM;

	/*
	 * Protect exec's credential calculations against our interference;
	 * SUID, SGID and LSM creds get determined differently
	 * under ptrace.
	 */
	scoped_cond_guard (mutex_intr, return -ERESTARTNOINTR,
			   &task->signal->cred_guard_mutex) {

		scoped_guard (task_lock, task) {
			retval = __ptrace_may_access(task, PTRACE_MODE_ATTACH_REALCREDS);
			if (retval)
				return retval;
		}

		scoped_guard (write_lock_irq, &tasklist_lock) {
			if (unlikely(task->exit_state))
				return -EPERM;
			if (task->ptrace)
				return -EPERM;

			task->ptrace = flags;
			ptrace_link(task, current);
			ptrace_set_stopped(task, seize);
		}
	}

	/*
	 * We do not bother to change retval or clear JOBCTL_TRAPPING
	 * if wait_on_bit() was interrupted by SIGKILL. The tracer will
	 * not return to user-mode, it will exit and clear this bit in
	 * __ptrace_unlink() if it wasn't already cleared by the tracee;
	 * and until then nobody can ptrace this task.
	 */
	wait_on_bit(&task->jobctl, JOBCTL_TRAPPING_BIT, TASK_KILLABLE);
	proc_ptrace_connector(task, PTRACE_ATTACH);

	return 0;
}
```

这段代码里有几条硬约束值得单独记住：

- **内核线程不能被跟踪**（`PF_KTHREAD` → `-EPERM`），ptrace 只面向用户态任务；
- **不能跟踪同线程组的任务**，否则 tracer 和 tracee 会互相等待；
- **一个 tracee 同时只有一个 tracer**（`task->ptrace` 非 0 直接拒绝）；
- **正在退出（`exit_state`）的任务不能附加**；
- **`cred_guard_mutex`** 把 attach 与 exec 的计算凭证阶段互斥开：被跟踪时 SUID/SGID 程序的凭证计算规则不同，若与 exec 交叠会算出错误结果；这里用可中断的 mutex 获取，被信号打断返回 `-ERESTARTNOINTR`。

### Representing the Relationship: parent Pointer and ptrace_entry

建立关系的核心动作是 `__ptrace_link()`——把 child 挂进 tracer 的 `ptraced` 链表，并把 `child->parent` 改成 tracer：

```c
void __ptrace_link(struct task_struct *child, struct task_struct *new_parent,
		   const struct cred *ptracer_cred)
{
	BUG_ON(!list_empty(&child->ptrace_entry));
	list_add(&child->ptrace_entry, &new_parent->ptraced);
	child->parent = new_parent;
	child->ptracer_cred = get_cred(ptracer_cred);
}
```

**为什么改的是 `parent` 而不是另开一个 `tracer` 字段？** 因为一旦 tracer 成为 parent，信号投递、wait 通知、僵尸回收、进程树关系这些"父子语义"全部自动生效，不需要在每条路径上都加一条 ptrace 分支。`real_parent` 保持不变，于是"是否被跟踪过继"可以用一个内联函数判断：

```c
static inline int ptrace_reparented(struct task_struct *child)
{
	return !same_thread_group(child->real_parent, child->parent);
}
```

`struct task_struct` 里与 ptrace 相关的字段：

| 字段 | 位置 | 含义 |
| --- | --- | --- |
| `ptrace` | `include/linux/sched.h:849` | 位图：`PT_PTRACED`/`PT_SEIZED` + 各事件开关 + `PT_EXITKILL` |
| `ptraced` | `sched.h:1103` | 链表头：本任务正在跟踪的所有 tracee |
| `ptrace_entry` | `sched.h:1104` | 本任务挂在 tracer 的 `ptraced` 链表上的节点 |
| `ptracer_cred` | `sched.h:1161` | attach 瞬间 tracer 的凭证快照，用于后续授权判断 |
| `ptrace_message` | `sched.h:1316` | `PTRACE_GETEVENTMSG` 读到的事件附加数据 |
| `last_siginfo` | `sched.h:1317` | 本次 stop 对应的 siginfo，非 NULL 即"处于 ptrace-stop" |
| `exit_code` | — | wait 侧读到的状态码，`(event << 8) | SIGTRAP` |
| `jobctl` | — | 停止/陷阱状态位，见下节 |

### ATTACH vs SEIZE: Whether to Send SIGSTOP

```c
static inline void ptrace_set_stopped(struct task_struct *task, bool seize)
{
	guard(spinlock)(&task->sighand->siglock);

	/* SEIZE doesn't trap tracee on attach */
	if (!seize)
		send_signal_locked(SIGSTOP, SEND_SIG_PRIV, task, PIDTYPE_PID);
	/*
	 * If the task is already STOPPED, set JOBCTL_TRAP_STOP and
	 * TRAPPING, and kick it so that it transits to TRACED.  TRAPPING
	 * will be cleared if the child completes the transition or any
	 * event which clears the group stop states happens.  We'll wait
	 * for the transition to complete before returning from this
	 * function.
	 *
	 * This hides STOPPED -> RUNNING -> TRACED transition from the
	 * attaching thread but a different thread in the same group can
	 * still observe the transient RUNNING state.  IOW, if another
	 * thread's WNOHANG wait(2) on the stopped tracee races against
	 * ATTACH, the wait(2) may fail due to the transient RUNNING.
	 *
	 * The following task_is_stopped() test is safe as both transitions
	 * in and out of STOPPED are protected by siglock.
	 */
	if (task_is_stopped(task) &&
	    task_set_jobctl_pending(task, JOBCTL_TRAP_STOP | JOBCTL_TRAPPING)) {
		task->jobctl &= ~JOBCTL_STOPPED;
		signal_wake_up_state(task, __TASK_STOPPED);
	}
}
```

- **ATTACH（legacy）**：附加后立刻给 tracee 发一个 SIGSTOP，把它拉进 **signal-delivery-stop**。副作用是它"污染"了 tracee 的信号语义——tracee 是真的收到了一个停止信号。
- **SEIZE**：不发信号，不改变 tracee 的信号与作业控制状态；后续的组停止通过 `PTRACE_EVENT_STOP` 上报，并且解锁了 `PTRACE_INTERRUPT` / `PTRACE_LISTEN` 两个额外请求。现代调试器（GDB 默认、CRIU）都用 SEIZE。

`JOBCTL_TRAPPING` 是 attach 的**握手位**：tracer 设置它之后 `wait_on_bit()`，直到 tracee 真正进入 `__TASK_TRACED` 才返回，这样 attach 返回时 tracee 一定已经停稳。

## Stopped State: jobctl Bitmap and TASK_TRACED

`task->jobctl` 的低 16 位是"最后一次组停止的信号号"，高位是一组标志（`include/linux/sched/jobctl.h`）：

| 位 | 名称 | 语义 |
| --- | --- | --- |
| 0-15 | `JOBCTL_STOP_SIGMASK` | 最后一次组停止的信号号 |
| 17 | `JOBCTL_STOP_PENDING` | 应当参与组停止 |
| 19 | `JOBCTL_TRAP_STOP` | 请求一次 STOP 陷阱（组停止事件） |
| 20 | `JOBCTL_TRAP_NOTIFY` | 有异步事件待通知（LISTEN 期间） |
| 21 | `JOBCTL_TRAPPING` | 正在切换到 `TASK_TRACED` 的过程中 |
| 22 | `JOBCTL_LISTENING` | tracer 处于 LISTEN 模式 |
| 23 | `JOBCTL_TRAP_FREEZE` | cgroup freezer 触发的陷阱 |
| 24 | `JOBCTL_PTRACE_FROZEN` | 因 ptrace 操作进行中而冻结 |
| 26 | `JOBCTL_STOPPED` | 处于组停止（`do_signal_stop()`） |
| 27 | `JOBCTL_TRACED` | 处于 ptrace 停止（`ptrace_stop()`） |

两个互斥的状态位值得注意：`JOBCTL_STOPPED` 由 `do_signal_stop()`（作业控制的 SIGSTOP/SIGTSTP）设置，`JOBCTL_TRACED` 由 `ptrace_stop()` 设置。ptrace 的很多复杂性就来自"**组停止与 ptrace 停止是两套状态，但一个任务可能同时参与两者**"。

## The Core of Stopping: ptrace_stop

所有 ptrace 停止最终都汇入 `ptrace_stop()`（`kernel/signal.c`），它被注释为"**This should be the path for all ptrace stops**"：

```c
static int ptrace_stop(int exit_code, int why, unsigned long message,
		       kernel_siginfo_t *info)
	__releases(&current->sighand->siglock)
	__acquires(&current->sighand->siglock)
{
	bool gstop_done = false;

	if (arch_ptrace_stop_needed()) {
		/*
		 * The arch code has something special to do before a
		 * ptrace stop.  This is allowed to block, e.g. for faults
		 * on user stack pages.  We can't keep the siglock while
		 * calling arch_ptrace_stop, so we must release it now.
		 * To preserve proper semantics, we must do this before
		 * any signal bookkeeping like checking group_stop_count.
		 */
		spin_unlock_irq(&current->sighand->siglock);
		arch_ptrace_stop();
		spin_lock_irq(&current->sighand->siglock);
	}

	/*
	 * After this point ptrace_signal_wake_up or signal_wake_up
	 * will clear TASK_TRACED if ptrace_unlink happens or a fatal
	 * signal comes in.  Handle previous ptrace_unlinks and fatal
	 * signals here to prevent ptrace_stop sleeping in schedule.
	 */
	if (!current->ptrace || __fatal_signal_pending(current))
		return exit_code;

	set_special_state(TASK_TRACED);
	current->jobctl |= JOBCTL_TRACED;
```

进入 `TASK_TRACED` 之后，tracer 与 tracee 之间有一段**内存屏障握手**，源码里直接画了时序图：

```c
	/*
	 * We're committing to trapping.  TRACED should be visible before
	 * TRAPPING is cleared; otherwise, the tracer might fail do_wait().
	 * Also, transition to TRACED and updates to ->jobctl should be
	 * atomic with respect to siglock and should be done after the arch
	 * hook as siglock is released and regrabbed across it.
	 *
	 *     TRACER				    TRACEE
	 *
	 *     ptrace_attach()
	 * [L]   wait_on_bit(JOBCTL_TRAPPING)	[S] set_special_state(TRACED)
	 *     do_wait()
	 *       set_current_state()                smp_wmb();
	 *       ptrace_do_wait()
	 *         wait_task_stopped()
	 *           task_stopped_code()
	 * [L]         task_is_traced()		[S] task_clear_jobctl_trapping();
	 */
	smp_wmb();

	current->ptrace_message = message;
	current->last_siginfo = info;
	current->exit_code = exit_code;
```

三个字段在这里一次性写定，tracer 稍后通过 `PTRACE_GETEVENTMSG` / `PTRACE_GETSIGINFO` / `waitpid` 读到它们。

随后是**通知双父**：被跟踪时任务有两个父——tracer（关心每一次 stop）和组 leader 的 real_parent（只关心组停止是否完成）：

```c
	spin_unlock_irq(&current->sighand->siglock);
	read_lock(&tasklist_lock);
	/*
	 * Notify parents of the stop.
	 *
	 * While ptraced, there are two parents - the ptracer and the
	 * real_parent of the group_leader.  The ptracer should
	 * know about every stop while the real parent is only
	 * interested in the completion of group stop.  The states
	 * for the two don't interact with each other.  Notify
	 * separately unless they're gonna be duplicates.
	 */
	if (current->ptrace)
		do_notify_parent_cldstop(current, true, why);
	if (gstop_done && (!current->ptrace || ptrace_reparented(current)))
		do_notify_parent_cldstop(current, false, why);
```

然后进入调度器睡眠。这里有一段关于 `preempt_disable()` 的细节注释：在抢占式内核上，如果不关抢占，本任务可能在通知完 tracer 之后、进入 `schedule()` 之前被抢占，tracer 会误判它还在运行队列里而白白多睡一个 tick：

```c
	if (!IS_ENABLED(CONFIG_PREEMPT_RT))
		preempt_disable();
	read_unlock(&tasklist_lock);
	cgroup_enter_frozen();
	if (!IS_ENABLED(CONFIG_PREEMPT_RT))
		preempt_enable_no_resched();
	schedule();
	cgroup_leave_frozen(true);
```

被 resume 唤醒后原路返回，清掉 stop 期的临时状态：

```c
	spin_lock_irq(&current->sighand->siglock);
	exit_code = current->exit_code;
	current->last_siginfo = NULL;
	current->ptrace_message = 0;
	current->exit_code = 0;

	/* LISTENING can be set only during STOP traps, clear it */
	current->jobctl &= ~(JOBCTL_LISTENING | JOBCTL_PTRACE_FROZEN);

	/*
	 * Queued signals ignored us while we were stopped for tracing.
	 * So check for any that we should take before resuming user mode.
	 * This sets TIF_SIGPENDING, but never clears it.
	 */
	recalc_sigpending_tsk(current);
	return exit_code;
```

`exit_code` 的返回值就是 tracer 注入的信号（0 表示不带信号继续）。

### External Entry Point: ptrace_notify

```c
int ptrace_notify(int exit_code, unsigned long message)
{
	int signr;

	BUG_ON((exit_code & (0x7f | ~0xffff)) != SIGTRAP);
	if (unlikely(task_work_pending(current)))
		task_work_run();

	spin_lock_irq(&current->sighand->siglock);
	signr = ptrace_do_notify(SIGTRAP, exit_code, CLD_TRAPPED, message);
	spin_unlock_irq(&current->sighand->siglock);
	return signr;
}
```

那个 `BUG_ON` 定下了一条 ABI 铁律：**ptrace 事件上报的等待状态码高 8 位是事件号、低 8 位必须是 SIGTRAP**，tracer 用 `status >> 8` 取出 `PTRACE_EVENT_*`。

## Freeze: PTRACE_FROZEN

tracer 读写 tracee 状态时，tracee 必须"绝对不动"。`ptrace_check_attach()` 负责这件事：

```c
static bool ptrace_freeze_traced(struct task_struct *task)
{
	bool ret = false;

	/* Lockless, nobody but us can set this flag */
	if (task->jobctl & JOBCTL_LISTENING)
		return ret;

	spin_lock_irq(&task->sighand->siglock);
	if (task_is_traced(task) && !looks_like_a_spurious_pid(task) &&
	    !__fatal_signal_pending(task)) {
		task->jobctl |= JOBCTL_PTRACE_FROZEN;
		ret = true;
	}
	spin_unlock_irq(&task->sighand->siglock);

	return ret;
}
```

配合的 `ptrace_check_attach()`：

```c
	read_lock(&tasklist_lock);
	if (child->ptrace && child->parent == current) {
		/*
		 * child->sighand can't be NULL, release_task()
		 * does ptrace_unlink() before __exit_signal().
		 */
		if (ignore_state || ptrace_freeze_traced(child))
			ret = 0;
	}
	read_unlock(&tasklist_lock);

	if (!ret && !ignore_state &&
	    WARN_ON_ONCE(!wait_task_inactive(child, __TASK_TRACED|TASK_FROZEN)))
		ret = -ESRCH;
```

`JOBCTL_PTRACE_FROZEN` 的效果在 `signal_wake_up()` 里体现——致命信号也清不掉它：

```c
static inline void signal_wake_up(struct task_struct *t, bool fatal)
{
	unsigned int state = 0;
	if (fatal && !(t->jobctl & JOBCTL_PTRACE_FROZEN)) {
		t->jobctl &= ~(JOBCTL_STOPPED | JOBCTL_TRACED);
		state = TASK_WAKEKILL | __TASK_TRACED;
	}
	signal_wake_up_state(t, state);
}
```

也就是说 **ptrace 操作进行中，连 SIGKILL 都叫不醒 tracee**；tracer 必须保证请求能返回，否则 tracee 会被永久挂住——这也是为什么所有 ptrace 请求都要尽快返回、不能无限阻塞。

`looks_like_a_spurious_pid()` 是一个针对 exec 竞态的补丁：exec 时 `de_thread()` 可能更换线程组 leader 的 pid，而 `PTRACE_EVENT_EXEC` 还没被 wait 走，此时按 pid 找回来的任务已经不是原来那个，应当拒绝操作。

## Event Reporting: PTRACE_EVENT_*

事件开关编码在 `task->ptrace` 的高位，每个 `PTRACE_EVENT_*` 对应一个 bit：

```c
#define PT_OPT_FLAG_SHIFT	3
/* PT_TRACE_* event enable flags */
#define PT_EVENT_FLAG(event)	(1 << (PT_OPT_FLAG_SHIFT + (event)))
#define PT_TRACESYSGOOD		PT_EVENT_FLAG(0)
#define PT_TRACE_FORK		PT_EVENT_FLAG(PTRACE_EVENT_FORK)
#define PT_TRACE_VFORK		PT_EVENT_FLAG(PTRACE_EVENT_VFORK)
#define PT_TRACE_CLONE		PT_EVENT_FLAG(PTRACE_EVENT_CLONE)
#define PT_TRACE_EXEC		PT_EVENT_FLAG(PTRACE_EVENT_EXEC)
#define PT_TRACE_VFORK_DONE	PT_EVENT_FLAG(PTRACE_EVENT_VFORK_DONE)
#define PT_TRACE_EXIT		PT_EVENT_FLAG(PTRACE_EVENT_EXIT)
#define PT_TRACE_SECCOMP	PT_EVENT_FLAG(PTRACE_EVENT_SECCOMP)

#define PT_EXITKILL		(PTRACE_O_EXITKILL << PT_OPT_FLAG_SHIFT)
#define PT_SUSPEND_SECCOMP	(PTRACE_O_SUSPEND_SECCOMP << PT_OPT_FLAG_SHIFT)
```

上报点的写法是一个内联函数，未开启时开销只有一个位测试：

```c
static inline void ptrace_event(int event, unsigned long message)
{
	if (unlikely(ptrace_event_enabled(current, event))) {
		ptrace_notify((event << 8) | SIGTRAP, message);
	} else if (event == PTRACE_EVENT_EXEC) {
		/* legacy EXEC report via SIGTRAP */
		if ((current->ptrace & (PT_PTRACED|PT_SEIZED)) == PT_PTRACED)
			send_sig(SIGTRAP, current, 0);
	}
}
```

末尾那个 `else if` 是历史包袱：在 SEIZE 之前，exec 通过给 tracee 发一个裸 SIGTRAP 来通知；只有"被 PT_PTRACED 但没被 SEIZED"的老式 tracer 才吃这一套。

事件清单（`include/uapi/linux/ptrace.h`）：

| 事件 | 值 | 触发点 | `ptrace_message` |
| --- | --- | --- | --- |
| `PTRACE_EVENT_FORK` | 1 | fork / clone（无 CLONE_VFORK、非线程） | 新任务 pid |
| `PTRACE_EVENT_VFORK` | 2 | `CLONE_VFORK` 的 clone | 新任务 pid |
| `PTRACE_EVENT_CLONE` | 3 | `CLONE_THREAD` 的 clone | 新任务 pid |
| `PTRACE_EVENT_EXEC` | 4 | exec 成功换映像 | 旧 pid |
| `PTRACE_EVENT_VFORK_DONE` | 5 | vfork 子进程 exec / 退出 | 子进程 pid |
| `PTRACE_EVENT_EXIT` | 6 | `do_exit()` 早段、exit_mm 之前 | 退出码 |
| `PTRACE_EVENT_SECCOMP` | 7 | seccomp 过滤器返回 `SECCOMP_RET_TRACE` | 过滤器给的 16 位数据 |
| `PTRACE_EVENT_STOP` | 128 | 组停止 / `PTRACE_INTERRUPT` / SEIZE 初始停止 | 见 `PTRACE_GETEVENTMSG` |

`PTRACE_EVENT_STOP` 的 128 是刻意挑的——它不在 `PTRACE_O_MASK`（0xff）里，因此**无法通过 `PTRACE_SETOPTIONS` 打开**，只能由内核在特定时机直接置位（SEIZE 附加时、组停止时、INTERRUPT 时）。这正是 SEIZE 能区分"组停止"与"信号投递停止"的机制。

## System Call Interception: syscall-stop

这是 strace 的全部工作原理。入口侧的顺序在 `include/linux/entry-common.h` 里写得非常明确：

```c
static __always_inline long syscall_trace_enter(struct pt_regs *regs, unsigned long work)
{
	long syscall, ret = 0;

	/*
	 * Handle Syscall User Dispatch.  This must comes first, since
	 * the ABI here can be something that doesn't make sense for
	 * other syscall_work features.
	 */
	if (work & SYSCALL_WORK_SYSCALL_USER_DISPATCH) {
		if (syscall_user_dispatch(regs))
			return -1L;
	}
	...
	/* Handle ptrace */
	if (work & (SYSCALL_WORK_SYSCALL_TRACE | SYSCALL_WORK_SYSCALL_EMU)) {
		ret = arch_ptrace_report_syscall_entry(regs);
		if (ret || (work & SYSCALL_WORK_SYSCALL_EMU))
			return -1L;

		/* ptrace might have changed work flags */
		work = READ_ONCE(current_thread_info()->syscall_work);
	}

	/* Do seccomp after ptrace, to catch any tracer changes. */
	if (work & SYSCALL_WORK_SECCOMP) {
		ret = __secure_computing();
		if (ret == -1L)
			return ret;
	}
```

"**Do seccomp after ptrace, to catch any tracer changes**" 这一行很重要：ptrace 在前，所以 tracer 可以在入口处**改掉系统调用号与参数**，随后 seccomp 检查的是被改后的值。安全模型上讲，这意味着 tracer 的优先级高于 seccomp 过滤器。

上报函数：

```c
static inline int ptrace_report_syscall(unsigned long message)
{
	int ptrace = current->ptrace;
	int signr;

	if (!(ptrace & PT_PTRACED))
		return 0;

	signr = ptrace_notify(SIGTRAP | ((ptrace & PT_TRACESYSGOOD) ? 0x80 : 0),
			      message);

	/*
	 * this isn't the same as continuing with a signal, but it will do
	 * for normal use.  strace only continues with a signal if the
	 * stopping signal is not SIGTRAP.  -brl
	 */
	if (signr)
		send_sig(signr, current, 1);

	return fatal_signal_pending(current);
}
```

`PTRACE_O_TRACESYSGOOD` 打开时状态码是 `SIGTRAP | 0x80`，让 tracer 能把"系统调用停止"和"真正的 SIGTRAP"区分开——strace 默认就设这个选项。

出口侧对称：

```c
static inline void ptrace_report_syscall_exit(struct pt_regs *regs, int step)
{
	if (step)
		user_single_step_report(regs);
	else
		ptrace_report_syscall(PTRACE_EVENTMSG_SYSCALL_EXIT);
}
```

`PTRACE_EVENTMSG_SYSCALL_ENTRY` / `_EXIT`（值 1 / 2）写进 `ptrace_message`，tracer 靠它判断当前停在入口还是出口：

```c
#define PTRACE_EVENTMSG_SYSCALL_ENTRY	1
#define PTRACE_EVENTMSG_SYSCALL_EXIT	2
```

### Getting Everything at Once: PTRACE_GET_SYSCALL_INFO

老式做法是多次 ptrace 调用（读 nr、读六个参数、读返回值），每个系统调用两次 stop，代价高。`PTRACE_GET_SYSCALL_INFO`（v5.3+）把这些打包成一次读取：

```c
struct ptrace_syscall_info {
	__u8 op;	/* PTRACE_SYSCALL_INFO_* */
	__u8 reserved;
	__u16 flags;
	__u32 arch;
	__u64 instruction_pointer;
	__u64 stack_pointer;
	union {
		struct {
			__u64 nr;
			__u64 args[6];
		} entry;
		struct {
			__s64 rval;
			__u8 is_error;
		} exit;
		struct {
			__u64 nr;
			__u64 args[6];
			__u32 ret_data;
			__u32 reserved2;
		} seccomp;
	};
};
```

内核侧用 `last_siginfo->si_code` 反推当前是哪种 stop：

```c
	switch (child->last_siginfo ? child->last_siginfo->si_code : 0) {
	case SIGTRAP | 0x80:
		switch (child->ptrace_message) {
		case PTRACE_EVENTMSG_SYSCALL_ENTRY:
			return PTRACE_SYSCALL_INFO_ENTRY;
		case PTRACE_EVENTMSG_SYSCALL_EXIT:
			return PTRACE_SYSCALL_INFO_EXIT;
		default:
			return PTRACE_SYSCALL_INFO_NONE;
		}
	case SIGTRAP | (PTRACE_EVENT_SECCOMP << 8):
		return PTRACE_SYSCALL_INFO_SECCOMP;
	default:
		return PTRACE_SYSCALL_INFO_NONE;
	}
```

对应的 `PTRACE_SET_SYSCALL_INFO`（v6.8+）更进一步，允许 tracer **一次性改写**系统调用号/参数或返回值，省掉多次 `POKEUSER`。注意约束：不能改变 stop 的类型（`ptrace_get_syscall_info_op(child) != info.op` → `-EINVAL`），且 `nr == -1` 时不写参数（避免在某些共享寄存器的架构上冲掉返回值）：

```c
	syscall_set_nr(child, regs, nr);
	/*
	 * If the syscall number is set to -1, setting syscall arguments is not
	 * just pointless, it would also clobber the syscall return value on
	 * those architectures that share the same register both for the first
	 * argument of syscall and its return value.
	 */
	if (nr != -1)
		syscall_set_arguments(child, regs, args);
```

### Cooperation with seccomp

seccomp 过滤器的返回值 `SECCOMP_RET_TRACE` 专门用来把决策交给 tracer：

```c
	case SECCOMP_RET_TRACE:
		/* We've been put in this state by the ptracer already. */
		if (recheck_after_trace)
			return 0;

		/* ENOSYS these calls if there is no tracer attached. */
		if (!ptrace_event_enabled(current, PTRACE_EVENT_SECCOMP)) {
			syscall_set_return_value(current,
						 current_pt_regs(),
						 -ENOSYS, 0);
			goto skip;
		}

		/* Allow the BPF to provide the event message */
		ptrace_event(PTRACE_EVENT_SECCOMP, data);
		/*
		 * The delivery of a fatal signal during event
		 * notification may silently skip tracer notification,
		 * which could leave us with a potentially unmodified
		 * syscall that the tracer would have liked to have
		 * changed. Since the process is about to die, we just
		 * force the syscall to be skipped and let the signal
		 * kill the process and correctly handle any tracer exit
		 * notifications.
		 */
		if (fatal_signal_pending(current))
			goto skip;
		/* Check if the tracer forced the syscall to be skipped. */
		this_syscall = syscall_get_nr(current, current_pt_regs());
		if (this_syscall < 0)
			goto skip;
```

三条规则由此确定：tracer 未开启 `PTRACE_O_TRACESECCOMP` 时该调用直接 `-ENOSYS`；tracer 可以把 nr 改成 -1 来**跳过**这个系统调用；tracer 死后 seccomp 过滤器会重新求值（`recheck_after_trace`）。

## Reading and Writing the tracee's Memory

`PTRACE_PEEKDATA` / `POKEDATA` 走的是通用层，最终落到 `access_remote_vm()`：

```c
int ptrace_access_vm(struct task_struct *tsk, unsigned long addr,
		     void *buf, int len, unsigned int gup_flags)
{
	struct mm_struct *mm;
	int ret = 0;

	mm = get_task_mm(tsk);
	if (!mm)
		return 0;

	if (ptracer_access_allowed(tsk))
		ret = access_remote_vm(mm, addr, buf, len, gup_flags);
	mmput(mm);

	return ret;
}
```

这里的关键点：

- **不直接 walk 页表**，而是 `get_task_mm()` 拿到 mm 引用后用 GUP（`FOLL_FORCE`）走正常缺页路径；注释明说 "Do not walk the page table directly, use get_user_pages"。这样对 `PROT_NONE`、未 fault 的页也能正确取到。
- **`FOLL_FORCE`** 是因为调试器常常要写只读映射（比如往 `.text` 里打断点）。
- 每次访问都要过一遍 `ptracer_access_allowed()`——v7.2.7 把它从 attach 时的一次性校验里独立出来：

```c
/**
 * ptracer_access_allowed - may current peek/poke @tsk's address space?
 * @tsk: tracee
 *
 * Per-access check used by ptrace_access_vm() and architecture-specific
 * tag/register accessors.  Returns true iff current is the registered
 * ptracer of @tsk and either @tsk is owner-dumpable or current holds
 * CAP_SYS_PTRACE in @tsk's exec namespace.  Lighter than
 * __ptrace_may_access(): it re-validates only dumpability and
 * capability on every access, without re-running LSM hooks or
 * cred_cap_issubset() checks performed at attach time.
 */
```

也就是说：attach 时做全套检查（uid/gid、能力、LSM），**每次读写只复查 dumpable 与能力**——因为 tracee 可能在跟踪期间执行了 setuid 程序导致 dumpable 变化。

`ptrace_readdata()` / `ptrace_writedata()` 是块读写版本，用栈上 128 字节缓冲分批处理，部分成功时返回已拷贝字节数（这也是为什么 ptrace 读写失败常常看到 `-EIO` 而不是 `-EFAULT`）。

## Registers: Two Paths

### Direct Architecture Access: PTRACE_GETREGS / PEEKUSR (x86)

```c
	case PTRACE_GETREGS:	/* Get all gp regs from the child. */
		return copy_regset_to_user(child,
					   regset_view,
					   REGSET_GENERAL,
					   0, sizeof(struct user_regs_struct),
					   datap);
```

`PTRACE_PEEKUSR` 用 `struct user` 的偏移来寻址，前段是通用寄存器、后段是调试寄存器：

```c
		if (addr < sizeof(struct user_regs_struct))
			tmp = getreg(child, addr);
		else if (addr >= offsetof(struct user, u_debugreg[0]) &&
			 addr <= offsetof(struct user, u_debugreg[7])) {
			addr -= offsetof(struct user, u_debugreg[0]);
			tmp = ptrace_get_debugreg(child, addr / sizeof(data));
		}
```

### Generic Abstraction: PTRACE_GETREGSET / SETREGSET

这条路按 **ELF core dump 的 note 类型**（`NT_PRSTATUS`、`NT_PRFPREG`、`NT_X86_XSTATE` 等）索引，好处是"**调试器读寄存器**"与"**core dump 写寄存器段**"共用同一套布局定义。抽象是 `struct user_regset_view`，按类型线性查找：

```c
static const struct user_regset *
find_regset(const struct user_regset_view *view, unsigned int type)
{
	const struct user_regset *regset;
	int n;

	for (n = 0; n < view->n; ++n) {
		regset = view->regsets + n;
		if (regset->core_note_type == type)
			return regset;
	}

	return NULL;
}
```

x86-64 的 view 由 `task_user_regset_view()` 根据任务是否 32 位来选（`user_x86_64_view` / `user_x86_32_view`），这就是 64 位调试器能正确解析 32 位 tracee 寄存器的原因。

## Single-Step and Breakpoints

### Single-Step: EFLAGS.TF

x86 的单步靠设置 EFLAGS 的 TF 位，`enable_step()` 分单指令步与分支步（block step）：

```c
static void enable_step(struct task_struct *child, bool block)
{
	/*
	 * Make sure block stepping (BTF) is not enabled unless it should be.
	 * Note that we don't try to worry about any is_setting_trap_flag()
	 * instructions after the first when using block stepping.
	 * So no one should try to use debugger block stepping in a program
	 * that uses user-mode single stepping itself.
	 */
	if (enable_single_step(child) && block)
		set_task_blockstep(child, true);
	else if (test_tsk_thread_flag(child, TIF_BLOCKSTEP))
		set_task_blockstep(child, false);
}
```

`enable_single_step()` 里有一段容易被忽略的处理：如果 tracee 当前正在执行的指令自己就要设置 TF（比如 `popf`），内核不该强行干预，于是用 `TIF_FORCED_TF` 标记"这是调试器设的 TF"以便之后正确清理：

```c
	if (is_setting_trap_flag(child, regs)) {
		clear_tsk_thread_flag(child, TIF_FORCED_TF);
		return 0;
	}

	/*
	 * If TF was already set, check whether it was us who set it.
	 * If not, we should never attempt a block step.
	 */
	if (oflags & X86_EFLAGS_TF)
		return test_tsk_thread_flag(child, TIF_FORCED_TF);

	set_tsk_thread_flag(child, TIF_FORCED_TF);
```

分支步走 MSR 的 BTF 位，只在 `set_task_blockstep()` 里改 `DEBUGCTLMSR`，并且注释强调"只有在任务不是 running 时才安全——依赖于 `ptrace_freeze_traced()`"。

### Hardware Breakpoints: DR0-DR3 via hw_breakpoint

调试寄存器不是直接写 MSR，而是注册成 perf 的硬件断点对象：

```c
static int ptrace_set_breakpoint_addr(struct task_struct *tsk, int nr,
				      unsigned long addr)
{
	struct thread_struct *t = &tsk->thread;
	struct perf_event *bp = t->ptrace_bps[nr];
	int err = 0;

	if (!bp) {
		/*
		 * Put stub len and type to create an inactive but correct bp.
		 * ...
		 */
		bp = ptrace_register_breakpoint(tsk,
				X86_BREAKPOINT_LEN_1, X86_BREAKPOINT_WRITE,
				addr, true);
		if (IS_ERR(bp))
			err = PTR_ERR(bp);
		else
			t->ptrace_bps[nr] = bp;
	} else {
		struct perf_event_attr attr = bp->attr;

		attr.bp_addr = addr;
		err = modify_user_hw_breakpoint(bp, &attr);
	}

	return err;
}
```

所以 **x86 只有 4 个硬件断点槽**（DR0-DR3），而且和 [perf](/docs/CS/OS/Linux/Tools/Perf.md) 抢同一组寄存器；exec 时内核会 `flush_ptrace_hw_breakpoint()` 清掉它们（见 [process](/docs/CS/OS/Linux/proc/process.md) 的 exec 部分）。

### Software Breakpoints: Kernel Does Not Participate

GDB 下的 `break *addr` 是调试器自己用 `PTRACE_POKEDATA` 把目标地址的一个字节替换成 `0xCC`（`int3`）实现的：命中断点后 CPU 产生 SIGTRAP、tracee 进入 signal-delivery-stop，调试器读完状态再把原字节写回、把 PC 回退一步。**内核里没有任何"设置断点"的 ptrace 请求**——这层完全是用户态的事，代价是需要可写映射（`FOLL_FORCE` 正是为此存在）。

## Recovery and Detach

### ptrace_resume

所有 resume 类请求（CONT / SYSCALL / SINGLESTEP / SYSEMU / SINGLEBLOCK）汇到一个函数：

```c
	if (request == PTRACE_SYSCALL)
		set_task_syscall_work(child, SYSCALL_TRACE);
	else
		clear_task_syscall_work(child, SYSCALL_TRACE);

#if defined(CONFIG_GENERIC_ENTRY) || defined(TIF_SYSCALL_EMU)
	if (request == PTRACE_SYSEMU || request == PTRACE_SYSEMU_SINGLESTEP)
		set_task_syscall_work(child, SYSCALL_EMU);
	else
		clear_task_syscall_work(child, SYSCALL_EMU);
#endif

	if (is_singleblock(request)) {
		if (unlikely(!arch_has_block_step()))
			return -EIO;
		user_enable_block_step(child);
	} else if (is_singlestep(request) || is_sysemu_singlestep(request)) {
		if (unlikely(!arch_has_single_step()))
			return -EIO;
		user_enable_single_step(child);
	} else {
		user_disable_single_step(child);
	}

	/*
	 * Change ->exit_code and ->state under siglock to avoid the race
	 * with wait_task_stopped() in between; a non-zero ->exit_code will
	 * wrongly look like another report from tracee.
	 *
	 * Note that we need siglock even if ->exit_code == data and/or this
	 * status was not reported yet, the new status must not be cleared by
	 * wait_task_stopped() after resume.
	 */
	spin_lock_irq(&child->sighand->siglock);
	child->exit_code = data;
	child->jobctl &= ~JOBCTL_TRACED;
	wake_up_state(child, __TASK_TRACED);
	spin_unlock_irq(&child->sighand->siglock);
```

`data` 非 0 且是有效信号时，它被当作"恢复时注入的信号"。`exit_code` 与 `JOBCTL_TRACED` 必须在同一把 siglock 下改，否则 tracer 的 `wait_task_stopped()` 可能把新状态码误认成又一次事件上报。

`PTRACE_SYSEMU` 是给用户态内核（UML）用的：它让系统调用**根本不执行**，只上报并让 tracee 以为得到了返回值。

### PTRACE_INTERRUPT and PTRACE_LISTEN

这两个是 SEIZE 专属（`if (unlikely(!seized ...)) break;`），用来在不干扰信号语义的前提下做"**暂停但不恢复**"与"**恢复但继续监听**"：

```c
	case PTRACE_INTERRUPT:
		/*
		 * Stop tracee without any side-effect on signal or job
		 * control.  At least one trap is guaranteed to happen
		 * after this request.  If @child is already trapped, the
		 * current trap is not disturbed and another trap will
		 * happen after the current trap is ended with PTRACE_CONT.
		 */
		if (unlikely(!seized || !lock_task_sighand(child, &flags)))
			break;

		if (likely(task_set_jobctl_pending(child, JOBCTL_TRAP_STOP)))
			ptrace_signal_wake_up(child, child->jobctl & JOBCTL_LISTENING);

		unlock_task_sighand(child, &flags);
		ret = 0;
		break;

	case PTRACE_LISTEN:
		/*
		 * Listen for events.  Tracee must be in STOP.  It's not
		 * resumed per-se but is not considered to be in TRACED by
		 * wait(2) or ptrace(2).  If an async event (e.g. group
		 * stop state change) happens, tracee will enter STOP trap
		 * again.  Alternatively, ptracer can issue INTERRUPT to
		 * finish listening and re-trap tracee into STOP.
		 */
```

LISTEN 的判定在 wait 侧生效——处于 LISTENING 的任务**不被视为 ptrace-stop**：

```c
static int *task_stopped_code(struct task_struct *p, bool ptrace)
{
	if (ptrace) {
		if (task_is_traced(p) && !(p->jobctl & JOBCTL_LISTENING))
			return &p->exit_code;
	} else {
		if (p->signal->flags & SIGNAL_STOP_STOPPED)
			return &p->signal->group_exit_code;
	}
	return NULL;
}
```

于是 tracer 可以"让 tracee 继续跑（在组停止意义上），同时仍然收得到它后续的事件"。

### Detach: ptrace_detach and __ptrace_unlink

```c
void __ptrace_unlink(struct task_struct *child)
{
	const struct cred *old_cred;
	BUG_ON(!child->ptrace);

	clear_task_syscall_work(child, SYSCALL_TRACE);
#if defined(CONFIG_GENERIC_ENTRY) || defined(TIF_SYSCALL_EMU)
	clear_task_syscall_work(child, SYSCALL_EMU);
#endif

	child->parent = child->real_parent;
	list_del_init(&child->ptrace_entry);
	old_cred = child->ptracer_cred;
	child->ptracer_cred = NULL;
	put_cred(old_cred);

	spin_lock(&child->sighand->siglock);
	child->ptrace = 0;
	/*
	 * Clear all pending traps and TRAPPING.  TRAPPING should be
	 * cleared regardless of JOBCTL_STOP_PENDING.  Do it explicitly.
	 */
	task_clear_jobctl_pending(child, JOBCTL_TRAP_MASK);
	task_clear_jobctl_trapping(child);
```

分离时最难的一段是**状态回落**：tracee 停在 `TASK_TRACED`，分离后它应该处于与组停止状态一致的状态。若组正在停止，它要转成 `TASK_STOPPED`：

```c
	/*
	 * Reinstate JOBCTL_STOP_PENDING if group stop is in effect and
	 * @child isn't dead.
	 */
	if (!(child->flags & PF_EXITING) &&
	    (child->signal->flags & SIGNAL_STOP_STOPPED ||
	     child->signal->group_stop_count))
		child->jobctl |= JOBCTL_STOP_PENDING;

	/*
	 * If transition to TASK_STOPPED is pending or in TASK_TRACED, kick
	 * @child in the butt.  Note that @resume should be used iff @child
	 * is in TASK_TRACED; otherwise, we might unduly disrupt
	 * TASK_KILLABLE sleeps.
	 */
	if (child->jobctl & JOBCTL_STOP_PENDING || task_is_traced(child))
		ptrace_signal_wake_up(child, true);
```

函数头注释还点明了一个可见的中间态：分离时 tracee 要经历 `TRACED → RUNNING → STOPPED`，**这个中间的 RUNNING 对 tracer 也是可见的**，若 tracer 立刻重新 attach 并发一个 `WNOHANG` 的 wait，可能失败。

### tracer Exit: exit_ptrace

```c
void exit_ptrace(struct task_struct *tracer, struct list_head *dead)
{
	struct task_struct *p, *n;

	list_for_each_entry_safe(p, n, &tracer->ptraced, ptrace_entry) {
		if (unlikely(p->ptrace & PT_EXITKILL))
			send_sig_info(SIGKILL, SEND_SIG_PRIV, p);

		if (__ptrace_detach(tracer, p))
			list_add(&p->ptrace_entry, dead);
	}
}
```

`PTRACE_O_EXITKILL` 是给"tracer 死了 tracee 也别活"的场景（如沙箱）用的；默认的语义是**静默分离，tracee 继续运行**。另外，被跟踪会阻止僵尸被正常回收（父通知被 tracer 截走），所以 `__ptrace_detach()` 里还要补发通知或直接标记 `EXIT_DEAD` 自回收。

## Security Boundary

### __ptrace_may_access

ptrace 的授权检查被 `/proc`、process_vm_readv 等复用，所以它不属于 ptrace 专有。判定顺序：

```c
	/* Don't let security modules deny introspection */
	if (same_thread_group(task, current))
		return 0;
	rcu_read_lock();
	if (mode & PTRACE_MODE_FSCREDS) {
		caller_uid = cred->fsuid;
		caller_gid = cred->fsgid;
	} else {
		/*
		 * Using the euid would make more sense here, but something
		 * in userland might rely on the old behavior, and this
		 * shouldn't be a security problem since
		 * PTRACE_MODE_REALCREDS implies that the caller explicitly
		 * used a syscall that requests access to another process
		 * (and not a filesystem syscall to procfs).
		 */
		caller_uid = cred->uid;
		caller_gid = cred->gid;
	}
	tcred = __task_cred(task);
	if (uid_eq(caller_uid, tcred->euid) &&
	    uid_eq(caller_uid, tcred->suid) &&
	    uid_eq(caller_uid, tcred->uid)  &&
	    gid_eq(caller_gid, tcred->egid) &&
	    gid_eq(caller_gid, tcred->sgid) &&
	    gid_eq(caller_gid, tcred->gid))
		goto ok;
	if (ptrace_has_cap(tcred->user_ns, mode))
		goto ok;
	rcu_read_unlock();
	return -EPERM;
```

通过后还有两道：**dumpable 复查**（带 `smp_rmb()` 与 `commit_creds()` 的写屏障配对，防止"降级但未变 non-dumpable"的窗口被利用）和 **LSM 钩子**：

```c
	/*
	 * If a task drops privileges and becomes nondumpable (through a syscall
	 * like setresuid()) while we are trying to access it, we must ensure
	 * that the dumpability is read after the credentials; otherwise,
	 * we may be able to attach to a task that we shouldn't be able to
	 * attach to (as if the task had dropped privileges without becoming
	 * nondumpable).
	 * Pairs with a write barrier in commit_creds().
	 */
	smp_rmb();
	if (!task_still_dumpable(task, mode))
		return -EPERM;

	return security_ptrace_access_check(task, mode);
```

`mode` 的两个维度：

| 维度 | 取值 | 含义 |
| --- | --- | --- |
| 用途 | `PTRACE_MODE_READ` / `PTRACE_MODE_ATTACH` | 只读取信息 / 要建立跟踪关系 |
| 凭证 | `PTRACE_MODE_FSCREDS` / `PTRACE_MODE_REALCREDS` | 经文件系统（用 fsuid/有效能力）/ 经显式系统调用（用 uid/真实能力） |

注意 `PTRACE_MODE_REALCREDS` 用的是 **uid 而不是 euid**，注释解释了原因：这必须是用户显式发起的系统调用（ptrace / process_vm_writev），而不是打开一个 procfs 文件，所以沿用历史行为无安全问题。

### Yama：ptrace_scope

主线内核里这道 LSM 钩子通常由 Yama 提供，四档策略（`security/yama/yama_lsm.c`）：

```c
	/* require ptrace target be a child of ptracer on attach */
	if (mode & PTRACE_MODE_ATTACH) {
		switch (ptrace_scope) {
		case YAMA_SCOPE_DISABLED:
			/* No additional restrictions. */
			break;
		case YAMA_SCOPE_RELATIONAL:
			rcu_read_lock();
			if (!pid_alive(child))
				rc = -EPERM;
			if (!rc && !task_is_descendant(current, child) &&
			    !ptracer_exception_found(current, child) &&
			    !ns_capable(__task_cred(child)->user_ns, CAP_SYS_PTRACE))
				rc = -EPERM;
			rcu_read_unlock();
			break;
		case YAMA_SCOPE_CAPABILITY:
			rcu_read_lock();
			if (!ns_capable(__task_cred(child)->user_ns, CAP_SYS_PTRACE))
				rc = -EPERM;
			rcu_read_unlock();
			break;
		case YAMA_SCOPE_NO_ATTACH:
		default:
			rc = -EPERM;
			break;
		}
	}
```

| scope | 值 | 语义 |
| --- | --- | --- |
| `DISABLED` | 0 | 只做经典 uid/capability 检查 |
| `RELATIONAL` | 1（默认） | 只能跟踪自己的后代，除非有 CAP_SYS_PTRACE 或显式例外（`PR_SET_PTRACER`） |
| `CAPABILITY` | 2 | 必须有 CAP_SYS_PTRACE |
| `NO_ATTACH` | 3 | 完全禁止 attach（已建立的关系不受影响） |

对应 sysctl `/proc/sys/kernel/yama/ptrace_scope`。容器环境里常见"宿主机能 ptrace 容器内进程"的越界风险，正是因为 CAP_SYS_PTRACE 在容器里往往被保留——这也是 [namespace](/docs/CS/OS/Linux/namespace.md) 隔离不住 ptrace 的原因之一。

## Users and Comparison

| 用户态工具 | 依赖的 ptrace 能力 |
| --- | --- |
| strace | `PTRACE_SYSCALL`（或 seccomp 加速）+ `PTRACE_GET_SYSCALL_INFO` + `PTRACE_O_TRACESYSGOOD` |
| GDB | `PEEK/POKEDATA`（软断点）、`GETREGSET`、单步、`GETREGSET NT_X86_XSTATE`、`PTRACE_EVENT_FORK/CLONE/EXEC/EXIT` |
| ltrace | 库函数层面，靠断点 + 单步 |
| CRIU | `PTRACE_SEIZE` + `PTRACE_INTERRUPT` + 寄生代码注入，做检查点/恢复 |
| 沙箱 | `PTRACE_SYSEMU` / seccomp `SECCOMP_RET_TRACE` + `PTRACE_O_EXITKILL` |

与观测型工具的取舍：

| 维度 | ptrace | [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) / [perf](/docs/CS/OS/Linux/Tools/Perf.md) |
| --- | --- | --- |
| 干扰方式 | **侵入式**：tracee 每次 stop 都要陷入内核、调度一次、被 tracer 唤醒 | 采样式 / 事件挂载，tracee 不停 |
| 开销 | 每个系统调用两次 stop，通常数十倍 slowdown | 微秒级，可常开 |
| 能力 | 能**改写**执行（改寄存器、改内存、跳过调用） | 只读（除非用 bpf_override_return 这类受限机制） |
| 权限 | 需要成为 tracer（ptrace_scope / CAP_SYS_PTRACE） | 需要 `CAP_BPF` / `CAP_PERFMON` 且加载受 verifier 约束 |

一句话概括：**ptrace 用于"控制和改写"，eBPF/perf 用于"观测"**。生产环境长期开着 strace 会显著拖慢业务，原因就写在 `ptrace_stop()` 里——每一次 stop 都是一次完整的调度往返。

## Links

- [signal](/docs/CS/OS/Linux/proc/signal.md) — signal-delivery-stop 的上游，ptrace 停止与信号投递共用 `get_signal()` 路径
- [process](/docs/CS/OS/Linux/proc/process.md) — fork/exec/exit 三处 ptrace 钩子与 `ptrace_init_task`
- [strace](/docs/CS/OS/Linux/Tools/strace.md) — ptrace 最直接的用户态使用者
- [GDB](/docs/CS/C/GDB.md) — 断点、单步与 regset 的调试器侧视角
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) — 非侵入式观测，与 ptrace 的取舍对照
- [namespace](/docs/CS/OS/Linux/namespace.md) — 为什么命名空间隔离挡不住 ptrace

## References

1. [ptrace(2) — Linux manual page](https://man7.org/linux/man-pages/man2/ptrace.2.html)
2. [Playing with ptrace, Part I](https://www.linuxjournal.com/article/6100)
3. [How debuggers work: Part 1 - Basics](https://eli.thegreenplace.net/2011/01/23/how-debuggers-work-part-1)
