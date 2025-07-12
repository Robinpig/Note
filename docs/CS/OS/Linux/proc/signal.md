## Introduction


信号可以理解为进程通信的一种方式，只不过通信的内容有限


`signal_struct` 和 `sighand_struct` ,分别对应task _stmct的si gnal和sighand 字段（都是指针），二者都被同一个线程组中的线程共享

signal_struct表示进程（线程组） 当前的信号信息（状态）， 主要字段见表

| 字段              | 类型                   | 描述          |
|-----------------|----------------------|-------------|
| shared_pending  | sigpending           | 待处理的信号      |
| group_exit_code | int                  |  退出码        |
| group_exit_task | task_struct*         | 等待线程组退出的进程  |
| rlim            | rlimit[ RUM_NLIMJTS] | 资源限制        |
| flags           | unsigned int         | SIGNAL_XXX 标志 |


shared_pending是线程组共享的信号队列，task_struct的pending 字段也是sigpending结构体类
型，表示线程独有的信号队列。

rlim表示进程当前对资源使用的限制(I是resource的缩写），是山mit结构体数组类型，可
以通过getrlimit和setrlimit系统调用获取或者设置某一项限制。rlimit结构体只有山lll_CUI 和山m_
max两个字段，表示当前值和最大值，使用setrlimit可以更改它们，增加山m_max需要CAP_SYS
_RESOURCE权限，也可能会受到一些逻辑限制，比如RLlMlT_NOFlLE (number of open files) 对
应的山m_max不能超过sysctl_nr_open。

> 需要强渊的是，`signal_struct` 在线程组内是共享的， 这怼味着以上字段的更改会影响到组内所有线程

sighand_struct结构体表示进程对信号的处理方式， 最重要的字段是action, 它是k_sigaction
结构体数组，数组元素个数等于＿NSIG (64, 系统当前可以支持的信号的最大值）。k_sigaction结
构体的最重要的字段是sa.sa_handler, 表示用户空间传递的处理信号的函数，函数原型为void
(*) (int)。

sigpending结构体的signal 字段是一个位图，表示当前待处理(pending) 的信号，该位图的
位数也等于＿NSlG

signal、sigaction和rt_sigaction 系统调用可以更改进程处理信号的方式，其中后两个的可移植性更好，用户可以直接使用glibc包装的signal
它一般调用rt_ sigaction 实现。自定义处理信号的函数，信号产生时函数被调用，被称为捕捉信号。

函数原型
```c
int sigaction(int n, struct sigaction *sa, const struct sigaction *old);
```


sigaction有一个sa _ restore1宇段，是信号处理返回使用的回调函数，有定义的情况下， sa_flags字段的SA_RESTORER标志也会被置位
3个系统调用最终都调用 `do_sigaction` 函数实现，区别仅在于传递给函数的act参数的值不同 （集中在act->sa.sa_flags 字段），

## do_sigaction


```c
int do_sigaction(int sig, struct k_sigaction *act, struct k_sigaction *oact)
{
	struct task_struct *p = current, *t;
	struct k_sigaction *k;
	sigset_t mask;

	if (!valid_signal(sig) || sig < 1 || (act && sig_kernel_only(sig)))
		return -EINVAL;

	k = &p->sighand->action[sig-1];

	spin_lock_irq(&p->sighand->siglock);
	if (k->sa.sa_flags & SA_IMMUTABLE) {
		spin_unlock_irq(&p->sighand->siglock);
		return -EINVAL;
	}
	if (oact)
		*oact = *k;

	/*
	 * Make sure that we never accidentally claim to support SA_UNSUPPORTED,
	 * e.g. by having an architecture use the bit in their uapi.
	 */
	BUILD_BUG_ON(UAPI_SA_FLAGS & SA_UNSUPPORTED);

	/*
	 * Clear unknown flag bits in order to allow userspace to detect missing
	 * support for flag bits and to allow the kernel to use non-uapi bits
	 * internally.
	 */
	if (act)
		act->sa.sa_flags &= UAPI_SA_FLAGS;
	if (oact)
		oact->sa.sa_flags &= UAPI_SA_FLAGS;

	sigaction_compat_abi(act, oact);

	if (act) {
		bool was_ignored = k->sa.sa_handler == SIG_IGN;

		sigdelsetmask(&act->sa.sa_mask,
			      sigmask(SIGKILL) | sigmask(SIGSTOP));
		*k = *act;
		/*
		 * POSIX 3.3.1.3:
		 *  "Setting a signal action to SIG_IGN for a signal that is
		 *   pending shall cause the pending signal to be discarded,
		 *   whether or not it is blocked."
		 *
		 *  "Setting a signal action to SIG_DFL for a signal that is
		 *   pending and whose default action is to ignore the signal
		 *   (for example, SIGCHLD), shall cause the pending signal to
		 *   be discarded, whether or not it is blocked"
		 */
		if (sig_handler_ignored(sig_handler(p, sig), sig)) {
			sigemptyset(&mask);
			sigaddset(&mask, sig);
			flush_sigqueue_mask(p, &mask, &p->signal->shared_pending);
			for_each_thread(p, t)
				flush_sigqueue_mask(p, &mask, &t->pending);
		} else if (was_ignored) {
			posixtimer_sig_unignore(p, sig);
		}
	}

	spin_unlock_irq(&p->sighand->siglock);
	return 0;
}
```

## Links

- [processes](/docs/CS/OS/Linux/proc/process.md)
