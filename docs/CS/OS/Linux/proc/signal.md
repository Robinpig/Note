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

## send_signal

kill、tgkill 和tkill等系统调用可以用来给进程发送信号， 用户空间可以直接使用以下两个函数
> 屈l 不能发送信号至指定线程，但pthreacl_kill可以，它是通过tgkill系统调用实现的，和kill 不同的是它调用 do_send_sig_info 时传递的type参数等千PlDTYPE_PlD
```c
SYSCALL_DEFINE2(kill, pid_t, pid, int, sig)
{
	struct kernel_siginfo info;

	prepare_kill_siginfo(sig, &info, PIDTYPE_TGID);

	return kill_something_info(sig, &info, pid);
}
```


分如下3种情况
- 如果pid > 0, 信号传递给pid 指定的进程。
- 如果picl等千－ 1' 信号会传递给当前进程有权限的所有进程，idle进程和同线程组的进程除外
- 如果pid等于0, 传递信号至当前进程组的每一个进程，如果picl小于－ 1' 传递至 -picl指定的进程组的匈一个进

```c
static int kill_something_info(int sig, struct kernel_siginfo *info, pid_t pid)
{
	int ret;

	if (pid > 0)
		return kill_proc_info(sig, info, pid);

	/* -INT_MIN is undefined.  Exclude this case to avoid a UBSAN warning */
	if (pid == INT_MIN)
		return -ESRCH;

	read_lock(&tasklist_lock);
	if (pid != -1) {
		ret = __kill_pgrp_info(sig, info,
				pid ? find_vpid(-pid) : task_pgrp(current));
	} else {
		int retval = 0, count = 0;
		struct task_struct * p;

		for_each_process(p) {
			if (task_pid_vnr(p) > 1 &&
					!same_thread_group(p, current)) {
				int err = group_send_sig_info(sig, info, p,
							      PIDTYPE_MAX);
				++count;
				if (err != -EPERM)
					retval = err;
			}
		}
		ret = count ? retval : -ESRCH;
	}
	read_unlock(&tasklist_lock);

	return ret;
}
```


灼ll_picl_info和卫l_pgrp_inl'o最终都是通过调用group_send_sig_info实现的(_kill_pgrp_i咖
对进程组中每一个进程循环调用它），group_sencl_sig_i咖又调用clo_sencl_sig_info。
do_sencl_sig_i！如函数最终会调用—send_signal_lockecl发送信号，后者集中了发送信号的主要逻辑

### __send_signal_locked

执行流程
- 调用prepare_signal判断是否应该发送信号
- 根据type参数选择信号队列，t->signal->sharecl_pencling是线程组共享的，t->pending 是线程（进程）独有的， 只有type参数等于PlDTYPE_PlD时才会选择后者。
  使用kill系统调用发送信号时type等于PIDTY P E_MAX, 所以它最终将信号挂载到线程组共享的信号队列中， 也就是说我们无法使用它给一个特定的线程发送信号
- 如果信号不是实时信号， 且已经在信号队列中， 则直接返回
- 申请一个sigqueue对象， 由它保存信号的信息，将它插入pending-> list链表中，链表中沮然可以存在相同的信号
- 将信号在位图中对应的位置1' 然后间用complete_signal查找一个处理信号的进程（线程）

```c
static int __send_signal_locked(int sig, struct kernel_siginfo *info,
				struct task_struct *t, enum pid_type type, bool force)
{
	struct sigpending *pending;
	struct sigqueue *q;
	int override_rlimit;
	int ret = 0, result;

	lockdep_assert_held(&t->sighand->siglock);

	result = TRACE_SIGNAL_IGNORED;
	if (!prepare_signal(sig, t, force))
		goto ret;

	pending = (type != PIDTYPE_PID) ? &t->signal->shared_pending : &t->pending;

	result = TRACE_SIGNAL_ALREADY_PENDING;
	if (legacy_queue(pending, sig))
		goto ret;

	result = TRACE_SIGNAL_DELIVERED;

	if ((sig == SIGKILL) || (t->flags & PF_KTHREAD))
		goto out_set;

	if (sig < SIGRTMIN)
		override_rlimit = (is_si_special(info) || info->si_code >= 0);
	else
		override_rlimit = 0;

	q = sigqueue_alloc(sig, t, GFP_ATOMIC, override_rlimit);

	if (q) {
		list_add_tail(&q->list, &pending->list);
		switch ((unsigned long) info) {
		case (unsigned long) SEND_SIG_NOINFO:
			clear_siginfo(&q->info);
			q->info.si_signo = sig;
			q->info.si_errno = 0;
			q->info.si_code = SI_USER;
			q->info.si_pid = task_tgid_nr_ns(current,
							task_active_pid_ns(t));
			rcu_read_lock();
			q->info.si_uid =
				from_kuid_munged(task_cred_xxx(t, user_ns),
						 current_uid());
			rcu_read_unlock();
			break;
		case (unsigned long) SEND_SIG_PRIV:
			clear_siginfo(&q->info);
			q->info.si_signo = sig;
			q->info.si_errno = 0;
			q->info.si_code = SI_KERNEL;
			q->info.si_pid = 0;
			q->info.si_uid = 0;
			break;
		default:
			copy_siginfo(&q->info, info);
			break;
		}
	} else if (!is_si_special(info) &&
		   sig >= SIGRTMIN && info->si_code != SI_USER) {
		result = TRACE_SIGNAL_OVERFLOW_FAIL;
		ret = -EAGAIN;
		goto ret;
	} else {
		result = TRACE_SIGNAL_LOSE_INFO;
	}

out_set:
	signalfd_notify(t, sig);
	sigaddset(&pending->signal, sig);

	/* Let multiprocess signals appear after on-going forks */
	if (type > PIDTYPE_TGID) {
		struct multiprocess_signals *delayed;
		hlist_for_each_entry(delayed, &t->signal->multiprocess, node) {
			sigset_t *signal = &delayed->signal;
			/* Can't queue both a stop and a continue signal */
			if (sig == SIGCONT)
				sigdelsetmask(signal, SIG_KERNEL_STOP_MASK);
			else if (sig_kernel_stop(sig))
				sigdelset(signal, SIGCONT);
			sigaddset(signal, sig);
		}
	}

	complete_signal(sig, t, type);
ret:
	trace_signal_generate(sig, info, t, type != PIDTYPE_PID, result);
	return ret;
}
```
#### complete_signal

wantssignal判断一个进程是否可
以处理信号，依据如下。
l)如果信号被进程block (p->blocked), 不处理。
2) 如果进程正在退出(PF_EXlTlNG), 不处理。
3) 信号等于SlGKILL,必须处理。
4) 处于＿TASK_STOPPED I—TASK_TRACED状态的进程，不处理。＿TASK_STOPPED状态的进程正在等待SIGCONT,prepare_signal巳经处理了这种情况。
5) 进程正在执行(task_curr),或者进程没有待处理的信号(! signal_pending),则需处理

```c
static void complete_signal(int sig, struct task_struct *p, enum pid_type type)
{
	struct signal_struct *signal = p->signal;
	struct task_struct *t;

	if (wants_signal(sig, p))
		t = p;
	else if ((type == PIDTYPE_PID) || thread_group_empty(p))
		return;
	else {
		/*
		 * Otherwise try to find a suitable thread.
		 */
		t = signal->curr_target;
		while (!wants_signal(sig, t)) {
			t = next_thread(t);
			if (t == signal->curr_target)
				/*
				 * No thread needs to be woken.
				 * Any eligible threads will see
				 * the signal in the queue soon.
				 */
				return;
		}
		signal->curr_target = t;
	}

	/*
	 * Found a killable thread.  If the signal will be fatal,
	 * then start taking the whole group down immediately.
	 */
	if (sig_fatal(p, sig) &&
	    (signal->core_state || !(signal->flags & SIGNAL_GROUP_EXIT)) &&
	    !sigismember(&t->real_blocked, sig) &&
	    (sig == SIGKILL || !p->ptrace)) {
		/*
		 * This signal will be fatal to the whole group.
		 */
		if (!sig_kernel_coredump(sig)) {

			signal->flags = SIGNAL_GROUP_EXIT;
			signal->group_exit_code = sig;
			signal->group_stop_count = 0;
			__for_each_thread(signal, t) {
				task_clear_jobctl_pending(t, JOBCTL_PENDING_MASK);
				sigaddset(&t->pending.signal, SIGKILL);
				signal_wake_up(t, 1);
			}
			return;
		}
	}

	/*
	 * The signal is already in the shared-pending queue.
	 * Tell the chosen thread to wake up and dequeue it.
	 */
	signal_wake_up(t, sig == SIGKILL);
	return;
}
```

## do_sigaction

sigaction有一个sa _ restore1宇段，是信号处理返回使用的回调函数，有定义的情况下， sa_flags字段的SA_RESTORER标志也会被置位
3个系统调用最终都调用 `do_sigaction` 函数实现，区别仅在于传递给函数的act参数的值不同 （集中在act->sa.sa_flags 字段），

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

首先是合法性检查，用户传递的sig必须在［ 1, 64] 范围内，而且不能更改sig_kernel_ only 的信号处理方式。sig_kernel_only包含SIGKILL和SlGSTOP两种信号，用户不可以自定义它们的处理方式

设置p->sighand->action[ sig-1], 更改进程对信号的处理方式

### get_signal

get_signal 的核心是一个循环
```c
bool get_signal(struct ksignal *ksig)
{
	struct sighand_struct *sighand = current->sighand;
	struct signal_struct *signal = current->signal;
	int signr;

	clear_notify_signal();
	if (unlikely(task_work_pending(current)))
		task_work_run();

	if (!task_sigpending(current))
		return false;

	if (unlikely(uprobe_deny_signal()))
		return false;

	/*
	 * Do this once, we can't return to user-mode if freezing() == T.
	 * do_signal_stop() and ptrace_stop() do freezable_schedule() and
	 * thus do not need another check after return.
	 */
	try_to_freeze();

relock:
	spin_lock_irq(&sighand->siglock);

	/*
	 * Every stopped thread goes here after wakeup. Check to see if
	 * we should notify the parent, prepare_signal(SIGCONT) encodes
	 * the CLD_ si_code into SIGNAL_CLD_MASK bits.
	 */
	if (unlikely(signal->flags & SIGNAL_CLD_MASK)) {
		int why;

		if (signal->flags & SIGNAL_CLD_CONTINUED)
			why = CLD_CONTINUED;
		else
			why = CLD_STOPPED;

		signal->flags &= ~SIGNAL_CLD_MASK;

		spin_unlock_irq(&sighand->siglock);

		/*
		 * Notify the parent that we're continuing.  This event is
		 * always per-process and doesn't make whole lot of sense
		 * for ptracers, who shouldn't consume the state via
		 * wait(2) either, but, for backward compatibility, notify
		 * the ptracer of the group leader too unless it's gonna be
		 * a duplicate.
		 */
		read_lock(&tasklist_lock);
		do_notify_parent_cldstop(current, false, why);

		if (ptrace_reparented(current->group_leader))
			do_notify_parent_cldstop(current->group_leader,
						true, why);
		read_unlock(&tasklist_lock);

		goto relock;
	}

	for (;;) {
		struct k_sigaction *ka;
		enum pid_type type;

		/* Has this task already been marked for death? */
		if ((signal->flags & SIGNAL_GROUP_EXIT) ||
		     signal->group_exec_task) {
			signr = SIGKILL;
			sigdelset(&current->pending.signal, SIGKILL);
			trace_signal_deliver(SIGKILL, SEND_SIG_NOINFO,
					     &sighand->action[SIGKILL-1]);
			recalc_sigpending();
			goto fatal;
		}

		if (unlikely(current->jobctl & JOBCTL_STOP_PENDING) &&
		    do_signal_stop(0))
			goto relock;

		if (unlikely(current->jobctl &
			     (JOBCTL_TRAP_MASK | JOBCTL_TRAP_FREEZE))) {
			if (current->jobctl & JOBCTL_TRAP_MASK) {
				do_jobctl_trap();
				spin_unlock_irq(&sighand->siglock);
			} else if (current->jobctl & JOBCTL_TRAP_FREEZE)
				do_freezer_trap();

			goto relock;
		}

		if (unlikely(cgroup_task_frozen(current))) {
			spin_unlock_irq(&sighand->siglock);
			cgroup_leave_frozen(false);
			goto relock;
		}

		type = PIDTYPE_PID;
		signr = dequeue_synchronous_signal(&ksig->info);
		if (!signr)
			signr = dequeue_signal(&current->blocked, &ksig->info, &type);

		if (!signr)
			break; /* will return 0 */

		if (unlikely(current->ptrace) && (signr != SIGKILL) &&
		    !(sighand->action[signr -1].sa.sa_flags & SA_IMMUTABLE)) {
			signr = ptrace_signal(signr, &ksig->info, type);
			if (!signr)
				continue;
		}

		ka = &sighand->action[signr-1];

		/* Trace actually delivered signals. */
		trace_signal_deliver(signr, &ksig->info, ka);

		if (ka->sa.sa_handler == SIG_IGN) /* Do nothing.  */
			continue;
		if (ka->sa.sa_handler != SIG_DFL) {
			/* Run the handler.  */
			ksig->ka = *ka;

			if (ka->sa.sa_flags & SA_ONESHOT)
				ka->sa.sa_handler = SIG_DFL;

			break; /* will return non-zero "signr" value */
		}

		if (sig_kernel_ignore(signr)) /* Default is nothing. */
			continue;

		if (unlikely(signal->flags & SIGNAL_UNKILLABLE) &&
				!sig_kernel_only(signr))
			continue;

		if (sig_kernel_stop(signr)) {
			if (signr != SIGSTOP) {
				spin_unlock_irq(&sighand->siglock);

				/* signals can be posted during this window */

				if (is_current_pgrp_orphaned())
					goto relock;

				spin_lock_irq(&sighand->siglock);
			}

			if (likely(do_signal_stop(signr))) {
				/* It released the siglock.  */
				goto relock;
			}

			/*
			 * We didn't actually stop, due to a race
			 * with SIGCONT or something like that.
			 */
			continue;
		}

	fatal:
		spin_unlock_irq(&sighand->siglock);
		if (unlikely(cgroup_task_frozen(current)))
			cgroup_leave_frozen(true);

		/*
		 * Anything else is fatal, maybe with a core dump.
		 */
		current->flags |= PF_SIGNALED;

		if (sig_kernel_coredump(signr)) {
			if (print_fatal_signals)
				print_fatal_signal(signr);
			proc_coredump_connector(current);

			do_coredump(&ksig->info);
		}

		if (current->flags & PF_USER_WORKER)
			goto out;

		/*
		 * Death signals, no core dump.
		 */
		do_group_exit(signr);
		/* NOTREACHED */
	}
	spin_unlock_irq(&sighand->siglock);

	ksig->sig = signr;

	if (signr && !(ksig->ka.sa.sa_flags & SA_EXPOSE_TAGBITS))
		hide_si_addr_tag_bits(ksig);
out:
	return signr > 0;
}
```

优先处理优先级高的信号(synchronous信号）， 没有则调用clequeue_signal查找其他
待处理的信号，p->pending 信号队列优先，信号值小的优先，如果在该队列找不到，再查找p->
signal->shar ecl_pending队列。 也就是说仇先外即友凶给I I L 1_$ 1,I勹{I I ＼丿， 纵丿I I，处，I[[!久，凶给纹扒＇夕11 (1勺们
1，丿， 达山，心11木／｝1及达给钱札望lI I I勺f11 1，)俄哪个纨札I. 处即）、l[小(1)'(1人1~1 1勺

clequeue_signal找到信号后，也会填充它的信息( info), 查看sigpending.list 链表上是否有与
它对应的sigqueue对象(q->info.si_signo = = sig), 如果没有，说明—send_signal的时候跳过了申
请sigqueue或者申请失败，从sigpending.signal 位图删除信号(sigdelse t(&pending-> signal ,
sig)), 初始化info然后返回；如果只有1个，从位图删除信号，将sigqueue对象从链表删除，
复制q->info 的信息然后返回；如果多千l个（实时信号），将sigqueue对象从链表删除，复制
q->info的信息然后返回，此时信号还存在， 不能从位图中删除


如果用户自定义了处理信号的方式，返回信号交由handle_signal处理。如果sa_flags
的标志SA_ONESHOT置位，表示用户的更改仅生效一次，恢复处理方式为SIG_DFL。

第3 步，采取信号的默认处理方式，sig_kern el_ ignor e 的信号被忽略，sig_kernel_stop的信号
触发do_signal_stop, sig_kemel_coredump的信号触发do_coreclump, 以上都不属于的信号会触发
clo_group_exit导致线程组退出



```c
static void
handle_signal(struct ksignal *ksig, struct pt_regs *regs)
{
	bool stepping, failed;
	struct fpu *fpu = &current->thread.fpu;

	if (v8086_mode(regs))
		save_v86_state((struct kernel_vm86_regs *) regs, VM86_SIGNAL);

	/* Are we from a system call? */
	if (syscall_get_nr(current, regs) != -1) {
		/* If so, check system call restarting.. */
		switch (syscall_get_error(current, regs)) {
		case -ERESTART_RESTARTBLOCK:
		case -ERESTARTNOHAND:
			regs->ax = -EINTR;
			break;

		case -ERESTARTSYS:
			if (!(ksig->ka.sa.sa_flags & SA_RESTART)) {
				regs->ax = -EINTR;
				break;
			}
			fallthrough;
		case -ERESTARTNOINTR:
			regs->ax = regs->orig_ax;
			regs->ip -= 2;
			break;
		}
	}

	/*
	 * If TF is set due to a debugger (TIF_FORCED_TF), clear TF now
	 * so that register information in the sigcontext is correct and
	 * then notify the tracer before entering the signal handler.
	 */
	stepping = test_thread_flag(TIF_SINGLESTEP);
	if (stepping)
		user_disable_single_step(current);

	failed = (setup_rt_frame(ksig, regs) < 0);
	if (!failed) {
		/*
		 * Clear the direction flag as per the ABI for function entry.
		 *
		 * Clear RF when entering the signal handler, because
		 * it might disable possible debug exception from the
		 * signal handler.
		 *
		 * Clear TF for the case when it wasn't set by debugger to
		 * avoid the recursive send_sigtrap() in SIGTRAP handler.
		 */
		regs->flags &= ~(X86_EFLAGS_DF|X86_EFLAGS_RF|X86_EFLAGS_TF);
		/*
		 * Ensure the signal handler starts with the new fpu state.
		 */
		fpu__clear_user_states(fpu);
	}
	signal_setup_done(failed, ksig, stepping);
}

```

handle_signal 的核心是 setup_rt_frame

#### setup_rt_frame


```c
static int
setup_rt_frame(struct ksignal *ksig, struct pt_regs *regs)
{
	/* Perform fixup for the pre-signal frame. */
	rseq_signal_deliver(ksig, regs);

	/* Set up the stack frame */
	if (is_ia32_frame(ksig)) {
		if (ksig->ka.sa.sa_flags & SA_SIGINFO)
			return ia32_setup_rt_frame(ksig, regs);
		else
			return ia32_setup_frame(ksig, regs);
	} else if (is_x32_frame(ksig)) {
		return x32_setup_rt_frame(ksig, regs);
	} else {
		return x64_setup_rt_frame(ksig, regs);
	}
}
```

x64实现

函数的第2个参数regs就是保持在内核栈高端， 进程返回用户空间使用的pt_regs
```c

int x64_setup_rt_frame(struct ksignal *ksig, struct pt_regs *regs)
{
	sigset_t *set = sigmask_to_save();
	struct rt_sigframe __user *frame;
	void __user *fp = NULL;
	unsigned long uc_flags;

	/* x86-64 should always use SA_RESTORER. */
	if (!(ksig->ka.sa.sa_flags & SA_RESTORER))
		return -EFAULT;

	frame = get_sigframe(ksig, regs, sizeof(struct rt_sigframe), &fp);
	uc_flags = frame_uc_flags(regs);

	if (!user_access_begin(frame, sizeof(*frame)))
		return -EFAULT;

	/* Create the ucontext.  */
	unsafe_put_user(uc_flags, &frame->uc.uc_flags, Efault);
	unsafe_put_user(0, &frame->uc.uc_link, Efault);
	unsafe_save_altstack(&frame->uc.uc_stack, regs->sp, Efault);

	/* Set up to return from userspace.  If provided, use a stub
	   already in userspace.  */
	unsafe_put_user(ksig->ka.sa.sa_restorer, &frame->pretcode, Efault);
	unsafe_put_sigcontext(&frame->uc.uc_mcontext, fp, regs, set, Efault);
	unsafe_put_sigmask(set, frame, Efault);
	user_access_end();

	if (ksig->ka.sa.sa_flags & SA_SIGINFO) {
		if (copy_siginfo_to_user(&frame->info, &ksig->info))
			return -EFAULT;
	}

	if (setup_signal_shadow_stack(ksig))
		return -EFAULT;

	/* Set up registers for signal handler */
	regs->di = ksig->sig;
	/* In case the signal handler was declared without prototypes */
	regs->ax = 0;

	/* This also works for non SA_SIGINFO handlers because they expect the
	   next argument after the signal number on the stack. */
	regs->si = (unsigned long)&frame->info;
	regs->dx = (unsigned long)&frame->uc;
	regs->ip = (unsigned long) ksig->ka.sa.sa_handler;

	regs->sp = (unsigned long)frame;

	regs->cs = __USER_CS;

	if (unlikely(regs->ss != __USER_DS))
		force_valid_ss(regs);

	return 0;

Efault:
	user_access_end();
	return -EFAULT;
}

```


#### rt_sigreturn
```c

/*
 * Do a signal return; undo the signal stack.
 */
SYSCALL_DEFINE0(rt_sigreturn)
{
	struct pt_regs *regs = current_pt_regs();
	struct rt_sigframe __user *frame;
	sigset_t set;
	unsigned long uc_flags;

	prevent_single_step_upon_eretu(regs);

	frame = (struct rt_sigframe __user *)(regs->sp - sizeof(long));
	if (!access_ok(frame, sizeof(*frame)))
		goto badframe;
	if (__get_user(*(__u64 *)&set, (__u64 __user *)&frame->uc.uc_sigmask))
		goto badframe;
	if (__get_user(uc_flags, &frame->uc.uc_flags))
		goto badframe;

	set_current_blocked(&set);

	if (restore_altstack(&frame->uc.uc_stack))
		goto badframe;

	if (!restore_sigcontext(regs, &frame->uc.uc_mcontext, uc_flags))
		goto badframe;

	if (restore_signal_shadow_stack())
		goto badframe;

	return regs->ax;

badframe:
	signal_fault(regs, frame, "rt_sigreturn");
	return 0;
}
```


## Links

- [processes](/docs/CS/OS/Linux/proc/process.md)
