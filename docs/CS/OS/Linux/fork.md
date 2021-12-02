## call

### fork
```c
// kernel/fork.c
/*
 * Create a kernel thread.
 */
pid_t kernel_thread(int (*fn)(void *), void *arg, unsigned long flags)
{
       struct kernel_clone_args args = {
              .flags        = ((lower_32_bits(flags) | CLONE_VM |
                                CLONE_UNTRACED) & ~CSIGNAL),
              .exit_signal   = (lower_32_bits(flags) & CSIGNAL),
              .stack        = (unsigned long)fn,
              .stack_size    = (unsigned long)arg,
       };

       return kernel_clone(&args);
}

```


```c
#ifdef __ARCH_WANT_SYS_FORK
SYSCALL_DEFINE0(fork)
{
#ifdef CONFIG_MMU
       struct kernel_clone_args args = {
              .exit_signal = SIGCHLD,
       };

       return kernel_clone(&args);
#else
       /* can not support in nommu mode */
       return -EINVAL;
#endif
}
#endif

#ifdef __ARCH_WANT_SYS_VFORK
SYSCALL_DEFINE0(vfork)
{
       struct kernel_clone_args args = {
              .flags        = CLONE_VFORK | CLONE_VM,
              .exit_signal   = SIGCHLD,
       };

       return kernel_clone(&args);
}
#endif
```



### kernel_clone
Ok, this is the main fork-routine.
It copies the process, and if successful kick-starts
it and waits for it to finish using the VM if required.
args->exit_signal is expected to be checked for sanity by the caller.

1. copy_process
2. trace_sched_process_fork
3. wake_up_new_task
4. ptrace_event_pid
5. wait_for_vfork_done if **vfork** -- avoid dirty data and deadlock

```c
// kernel/fork.c
pid_t kernel_clone(struct kernel_clone_args *args)
{
       u64 clone_flags = args->flags;
       struct completion vfork;
       struct pid *pid;
       struct task_struct *p;
       int trace = 0;
       pid_t nr;

       /*
        * For legacy clone() calls, CLONE_PIDFD uses the parent_tid argument
        * to return the pidfd. Hence, CLONE_PIDFD and CLONE_PARENT_SETTID are
        * mutually exclusive. With clone3() CLONE_PIDFD has grown a separate
        * field in struct clone_args and it still doesn't make sense to have
        * them both point at the same memory location. Performing this check
        * here has the advantage that we don't need to have a separate helper
        * to check for legacy clone().
        */
       if ((args->flags & CLONE_PIDFD) &&
           (args->flags & CLONE_PARENT_SETTID) &&
           (args->pidfd == args->parent_tid))
              return -EINVAL;

       /*
        * Determine whether and which event to report to ptracer.  When
        * called from kernel_thread or CLONE_UNTRACED is explicitly
        * requested, no event is reported; otherwise, report if the event
        * for the type of forking is enabled.
        */
       if (!(clone_flags & CLONE_UNTRACED)) {
              if (clone_flags & CLONE_VFORK)
                     trace = PTRACE_EVENT_VFORK;
              else if (args->exit_signal != SIGCHLD)
                     trace = PTRACE_EVENT_CLONE;
              else
                     trace = PTRACE_EVENT_FORK;

              if (likely(!ptrace_event_enabled(current, trace)))
                     trace = 0;
       }

       p = copy_process(NULL, trace, NUMA_NO_NODE, args);
       add_latent_entropy();

       if (IS_ERR(p))
              return PTR_ERR(p);

       /*
        * Do this prior waking up the new thread - the thread pointer
        * might get invalid after that point, if the thread exits quickly.
        */
       trace_sched_process_fork(current, p);

       pid = get_task_pid(p, PIDTYPE_PID);
       nr = pid_vnr(pid);

       if (clone_flags & CLONE_PARENT_SETTID)
              put_user(nr, args->parent_tid);

       if (clone_flags & CLONE_VFORK) {
              p->vfork_done = &vfork;
              init_completion(&vfork);
              get_task_struct(p);
       }

       wake_up_new_task(p);

       /* forking complete and child started to run, tell ptracer */
       if (unlikely(trace))
              ptrace_event_pid(trace, pid);

       if (clone_flags & CLONE_VFORK) {
              if (!wait_for_vfork_done(p, &vfork))
                     ptrace_event_pid(PTRACE_EVENT_VFORK_DONE, pid);
       }

       put_pid(pid);
       return nr;
}
```



### copy_process

1. dup_task_struct
2. 

```c
/*
 * This creates a new process as a copy of the old one,
 * but does not actually start it yet.
 *
 * It copies the registers, and all the appropriate
 * parts of the process environment (as per the clone
 * flags). The actual kick-off is left to the caller.
 */
static __latent_entropy struct task_struct *copy_process(
                                   struct pid *pid,
                                   int trace,
                                   int node,
                                   struct kernel_clone_args *args)
{
       int pidfd = -1, retval;
       struct task_struct *p;
       struct multiprocess_signals delayed;
       struct file *pidfile = NULL;
       u64 clone_flags = args->flags;
       struct nsproxy *nsp = current->nsproxy;

       /*
        * Don't allow sharing the root directory with processes in a different
        * namespace
        */
       if ((clone_flags & (CLONE_NEWNS|CLONE_FS)) == (CLONE_NEWNS|CLONE_FS))
              return ERR_PTR(-EINVAL);

       if ((clone_flags & (CLONE_NEWUSER|CLONE_FS)) == (CLONE_NEWUSER|CLONE_FS))
              return ERR_PTR(-EINVAL);

       /*
        * Thread groups must share signals as well, and detached threads
        * can only be started up within the thread group.
        */
       if ((clone_flags & CLONE_THREAD) && !(clone_flags & CLONE_SIGHAND))
              return ERR_PTR(-EINVAL);

       /*
        * Shared signal handlers imply shared VM. By way of the above,
        * thread groups also imply shared VM. Blocking this case allows
        * for various simplifications in other code.
        */
       if ((clone_flags & CLONE_SIGHAND) && !(clone_flags & CLONE_VM))
              return ERR_PTR(-EINVAL);

       /*
        * Siblings of global init remain as zombies on exit since they are
        * not reaped by their parent (swapper). To solve this and to avoid
        * multi-rooted process trees, prevent global and container-inits
        * from creating siblings.
        */
       if ((clone_flags & CLONE_PARENT) &&
                            current->signal->flags & SIGNAL_UNKILLABLE)
              return ERR_PTR(-EINVAL);

       /*
        * If the new process will be in a different pid or user namespace
        * do not allow it to share a thread group with the forking task.
        */
       if (clone_flags & CLONE_THREAD) {
              if ((clone_flags & (CLONE_NEWUSER | CLONE_NEWPID)) ||
                  (task_active_pid_ns(current) != nsp->pid_ns_for_children))
                     return ERR_PTR(-EINVAL);
       }

       /*
        * If the new process will be in a different time namespace
        * do not allow it to share VM or a thread group with the forking task.
        */
       if (clone_flags & (CLONE_THREAD | CLONE_VM)) {
              if (nsp->time_ns != nsp->time_ns_for_children)
                     return ERR_PTR(-EINVAL);
       }

       if (clone_flags & CLONE_PIDFD) {
              /*
               * - CLONE_DETACHED is blocked so that we can potentially
               *   reuse it later for CLONE_PIDFD.
               * - CLONE_THREAD is blocked until someone really needs it.
               */
              if (clone_flags & (CLONE_DETACHED | CLONE_THREAD))
                     return ERR_PTR(-EINVAL);
       }

       /*
        * Force any signals received before this point to be delivered
        * before the fork happens.  Collect up signals sent to multiple
        * processes that happen during the fork and delay them so that
        * they appear to happen after the fork.
        */
       sigemptyset(&delayed.signal);
       INIT_HLIST_NODE(&delayed.node);

       spin_lock_irq(&current->sighand->siglock);
       if (!(clone_flags & CLONE_THREAD))
              hlist_add_head(&delayed.node, &current->signal->multiprocess);
       recalc_sigpending();
       spin_unlock_irq(&current->sighand->siglock);
       retval = -ERESTARTNOINTR;
       if (task_sigpending(current))
              goto fork_out;

       retval = -ENOMEM;
       p = dup_task_struct(current, node);
       if (!p)
              goto fork_out;
       if (args->io_thread) {
              /*
               * Mark us an IO worker, and block any signal that isn't
               * fatal or STOP
               */
              p->flags |= PF_IO_WORKER;
              siginitsetinv(&p->blocked, sigmask(SIGKILL)|sigmask(SIGSTOP));
       }

       /*
        * This _must_ happen before we call free_task(), i.e. before we jump
        * to any of the bad_fork_* labels. This is to avoid freeing
        * p->set_child_tid which is (ab)used as a kthread's data pointer for
        * kernel threads (PF_KTHREAD).
        */
       p->set_child_tid = (clone_flags & CLONE_CHILD_SETTID) ? args->child_tid : NULL;
       /*
        * Clear TID on mm_release()?
        */
       p->clear_child_tid = (clone_flags & CLONE_CHILD_CLEARTID) ? args->child_tid : NULL;

       ftrace_graph_init_task(p);

       rt_mutex_init_task(p);

       lockdep_assert_irqs_enabled();
#ifdef CONFIG_PROVE_LOCKING
       DEBUG_LOCKS_WARN_ON(!p->softirqs_enabled);
#endif
       retval = -EAGAIN;
       if (atomic_read(&p->real_cred->user->processes) >=
                     task_rlimit(p, RLIMIT_NPROC)) {
              if (p->real_cred->user != INIT_USER &&
                  !capable(CAP_SYS_RESOURCE) && !capable(CAP_SYS_ADMIN))
                     goto bad_fork_free;
       }
       current->flags &= ~PF_NPROC_EXCEEDED;

       retval = copy_creds(p, clone_flags);
       if (retval < 0)
              goto bad_fork_free;

       /*
        * If multiple threads are within copy_process(), then this check
        * triggers too late. This doesn't hurt, the check is only there
        * to stop root fork bombs.
        */
       retval = -EAGAIN;
       if (data_race(nr_threads >= max_threads))
              goto bad_fork_cleanup_count;

       delayacct_tsk_init(p); /* Must remain after dup_task_struct() */
       p->flags &= ~(PF_SUPERPRIV | PF_WQ_WORKER | PF_IDLE);
       p->flags |= PF_FORKNOEXEC;
       INIT_LIST_HEAD(&p->children);
       INIT_LIST_HEAD(&p->sibling);
       rcu_copy_process(p);
       p->vfork_done = NULL;
       spin_lock_init(&p->alloc_lock);

       init_sigpending(&p->pending);

       p->utime = p->stime = p->gtime = 0;
#ifdef CONFIG_ARCH_HAS_SCALED_CPUTIME
       p->utimescaled = p->stimescaled = 0;
#endif
       prev_cputime_init(&p->prev_cputime);

#ifdef CONFIG_VIRT_CPU_ACCOUNTING_GEN
       seqcount_init(&p->vtime.seqcount);
       p->vtime.starttime = 0;
       p->vtime.state = VTIME_INACTIVE;
#endif

#ifdef CONFIG_IO_URING
       p->io_uring = NULL;
#endif

#if defined(SPLIT_RSS_COUNTING)
       memset(&p->rss_stat, 0, sizeof(p->rss_stat));
#endif

       p->default_timer_slack_ns = current->timer_slack_ns;

#ifdef CONFIG_PSI
       p->psi_flags = 0;
#endif

       task_io_accounting_init(&p->ioac);
       acct_clear_integrals(p);

       posix_cputimers_init(&p->posix_cputimers);

       p->io_context = NULL;
       audit_set_context(p, NULL);
       cgroup_fork(p);
#ifdef CONFIG_NUMA
       p->mempolicy = mpol_dup(p->mempolicy);
       if (IS_ERR(p->mempolicy)) {
              retval = PTR_ERR(p->mempolicy);
              p->mempolicy = NULL;
              goto bad_fork_cleanup_threadgroup_lock;
       }
#endif
#ifdef CONFIG_CPUSETS
       p->cpuset_mem_spread_rotor = NUMA_NO_NODE;
       p->cpuset_slab_spread_rotor = NUMA_NO_NODE;
       seqcount_spinlock_init(&p->mems_allowed_seq, &p->alloc_lock);
#endif
#ifdef CONFIG_TRACE_IRQFLAGS
       memset(&p->irqtrace, 0, sizeof(p->irqtrace));
       p->irqtrace.hardirq_disable_ip = _THIS_IP_;
       p->irqtrace.softirq_enable_ip  = _THIS_IP_;
       p->softirqs_enabled           = 1;
       p->softirq_context            = 0;
#endif

       p->pagefault_disabled = 0;

#ifdef CONFIG_LOCKDEP
       lockdep_init_task(p);
#endif

#ifdef CONFIG_DEBUG_MUTEXES
       p->blocked_on = NULL; /* not blocked yet */
#endif
#ifdef CONFIG_BCACHE
       p->sequential_io       = 0;
       p->sequential_io_avg   = 0;
#endif
#ifdef CONFIG_BPF_SYSCALL
       RCU_INIT_POINTER(p->bpf_storage, NULL);
#endif

       /* Perform scheduler related setup. Assign this task to a CPU. */
       retval = sched_fork(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_policy;

       retval = perf_event_init_task(p, clone_flags);
       if (retval)
              goto bad_fork_cleanup_policy;
       retval = audit_alloc(p);
       if (retval)
              goto bad_fork_cleanup_perf;
       /* copy all the process information */
       shm_init_task(p);
       retval = security_task_alloc(p, clone_flags);
       if (retval)
              goto bad_fork_cleanup_audit;
       retval = copy_semundo(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_security;
       retval = copy_files(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_semundo;
       retval = copy_fs(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_files;
       retval = copy_sighand(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_fs;
       retval = copy_signal(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_sighand;
       retval = copy_mm(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_signal;
       retval = copy_namespaces(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_mm;
       retval = copy_io(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_namespaces;
       retval = copy_thread(clone_flags, args->stack, args->stack_size, p, args->tls);
       if (retval)
              goto bad_fork_cleanup_io;

       stackleak_task_init(p);

       if (pid != &init_struct_pid) {
              pid = alloc_pid(p->nsproxy->pid_ns_for_children, args->set_tid,
                            args->set_tid_size);
              if (IS_ERR(pid)) {
                     retval = PTR_ERR(pid);
                     goto bad_fork_cleanup_thread;
              }
       }

       /*
        * This has to happen after we've potentially unshared the file
        * descriptor table (so that the pidfd doesn't leak into the child
        * if the fd table isn't shared).
        */
       if (clone_flags & CLONE_PIDFD) {
              retval = get_unused_fd_flags(O_RDWR | O_CLOEXEC);
              if (retval < 0)
                     goto bad_fork_free_pid;

              pidfd = retval;

              pidfile = anon_inode_getfile("[pidfd]", &pidfd_fops, pid,
                                         O_RDWR | O_CLOEXEC);
              if (IS_ERR(pidfile)) {
                     put_unused_fd(pidfd);
                     retval = PTR_ERR(pidfile);
                     goto bad_fork_free_pid;
              }
              get_pid(pid);  /* held by pidfile now */

              retval = put_user(pidfd, args->pidfd);
              if (retval)
                     goto bad_fork_put_pidfd;
       }

#ifdef CONFIG_BLOCK
       p->plug = NULL;
#endif
       futex_init_task(p);

       /*
        * sigaltstack should be cleared when sharing the same VM
        */
       if ((clone_flags & (CLONE_VM|CLONE_VFORK)) == CLONE_VM)
              sas_ss_reset(p);

       /*
        * Syscall tracing and stepping should be turned off in the
        * child regardless of CLONE_PTRACE.
        */
       user_disable_single_step(p);
       clear_task_syscall_work(p, SYSCALL_TRACE);
#if defined(CONFIG_GENERIC_ENTRY) || defined(TIF_SYSCALL_EMU)
       clear_task_syscall_work(p, SYSCALL_EMU);
#endif
       clear_tsk_latency_tracing(p);

       /* ok, now we should be set up.. */
       p->pid = pid_nr(pid);
       if (clone_flags & CLONE_THREAD) {
              p->group_leader = current->group_leader;
              p->tgid = current->tgid;
       } else {
              p->group_leader = p;
              p->tgid = p->pid;
       }

       p->nr_dirtied = 0;
       p->nr_dirtied_pause = 128 >> (PAGE_SHIFT - 10);
       p->dirty_paused_when = 0;

       p->pdeath_signal = 0;
       INIT_LIST_HEAD(&p->thread_group);
       p->task_works = NULL;

#ifdef CONFIG_KRETPROBES
       p->kretprobe_instances.first = NULL;
#endif

       /*
        * Ensure that the cgroup subsystem policies allow the new process to be
        * forked. It should be noted that the new process's css_set can be changed
        * between here and cgroup_post_fork() if an organisation operation is in
        * progress.
        */
       retval = cgroup_can_fork(p, args);
       if (retval)
              goto bad_fork_put_pidfd;

       /*
        * From this point on we must avoid any synchronous user-space
        * communication until we take the tasklist-lock. In particular, we do
        * not want user-space to be able to predict the process start-time by
        * stalling fork(2) after we recorded the start_time but before it is
        * visible to the system.
        */

       p->start_time = ktime_get_ns();
       p->start_boottime = ktime_get_boottime_ns();

       /*
        * Make it visible to the rest of the system, but dont wake it up yet.
        * Need tasklist lock for parent etc handling!
        */
       write_lock_irq(&tasklist_lock);

       /* CLONE_PARENT re-uses the old parent */
       if (clone_flags & (CLONE_PARENT|CLONE_THREAD)) {
              p->real_parent = current->real_parent;
              p->parent_exec_id = current->parent_exec_id;
              if (clone_flags & CLONE_THREAD)
                     p->exit_signal = -1;
              else
                     p->exit_signal = current->group_leader->exit_signal;
       } else {
              p->real_parent = current;
              p->parent_exec_id = current->self_exec_id;
              p->exit_signal = args->exit_signal;
       }

       klp_copy_process(p);

       spin_lock(&current->sighand->siglock);

       /*
        * Copy seccomp details explicitly here, in case they were changed
        * before holding sighand lock.
        */
       copy_seccomp(p);

       rseq_fork(p, clone_flags);

       /* Don't start children in a dying pid namespace */
       if (unlikely(!(ns_of_pid(pid)->pid_allocated & PIDNS_ADDING))) {
              retval = -ENOMEM;
              goto bad_fork_cancel_cgroup;
       }

       /* Let kill terminate clone/fork in the middle */
       if (fatal_signal_pending(current)) {
              retval = -EINTR;
              goto bad_fork_cancel_cgroup;
       }

       /* past the last point of failure */
       if (pidfile)
              fd_install(pidfd, pidfile);

       init_task_pid_links(p);
       if (likely(p->pid)) {
              ptrace_init_task(p, (clone_flags & CLONE_PTRACE) || trace);

              init_task_pid(p, PIDTYPE_PID, pid);
              if (thread_group_leader(p)) {
                     init_task_pid(p, PIDTYPE_TGID, pid);
                     init_task_pid(p, PIDTYPE_PGID, task_pgrp(current));
                     init_task_pid(p, PIDTYPE_SID, task_session(current));

                     if (is_child_reaper(pid)) {
                            ns_of_pid(pid)->child_reaper = p;
                            p->signal->flags |= SIGNAL_UNKILLABLE;
                     }
                     p->signal->shared_pending.signal = delayed.signal;
                     p->signal->tty = tty_kref_get(current->signal->tty);
                     /*
                      * Inherit has_child_subreaper flag under the same
                      * tasklist_lock with adding child to the process tree
                      * for propagate_has_child_subreaper optimization.
                      */
                     p->signal->has_child_subreaper = p->real_parent->signal->has_child_subreaper ||
                                                  p->real_parent->signal->is_child_subreaper;
                     list_add_tail(&p->sibling, &p->real_parent->children);
                     list_add_tail_rcu(&p->tasks, &init_task.tasks);
                     attach_pid(p, PIDTYPE_TGID);
                     attach_pid(p, PIDTYPE_PGID);
                     attach_pid(p, PIDTYPE_SID);
                     __this_cpu_inc(process_counts);
              } else {
                     current->signal->nr_threads++;
                     atomic_inc(&current->signal->live);
                     refcount_inc(&current->signal->sigcnt);
                     task_join_group_stop(p);
                     list_add_tail_rcu(&p->thread_group,
                                     &p->group_leader->thread_group);
                     list_add_tail_rcu(&p->thread_node,
                                     &p->signal->thread_head);
              }
              attach_pid(p, PIDTYPE_PID);
              nr_threads++;
       }
       total_forks++;
       hlist_del_init(&delayed.node);
       spin_unlock(&current->sighand->siglock);
       syscall_tracepoint_update(p);
       write_unlock_irq(&tasklist_lock);

       proc_fork_connector(p);
       sched_post_fork(p);
       cgroup_post_fork(p, args);
       perf_event_fork(p);

       trace_task_newtask(p, clone_flags);
       uprobe_copy_process(p, clone_flags);

       copy_oom_score_adj(clone_flags, p);

       return p;

bad_fork_cancel_cgroup:
       spin_unlock(&current->sighand->siglock);
       write_unlock_irq(&tasklist_lock);
       cgroup_cancel_fork(p, args);
bad_fork_put_pidfd:
       if (clone_flags & CLONE_PIDFD) {
              fput(pidfile);
              put_unused_fd(pidfd);
       }
bad_fork_free_pid:
       if (pid != &init_struct_pid)
              free_pid(pid);
bad_fork_cleanup_thread:
       exit_thread(p);
bad_fork_cleanup_io:
       if (p->io_context)
              exit_io_context(p);
bad_fork_cleanup_namespaces:
       exit_task_namespaces(p);
bad_fork_cleanup_mm:
       if (p->mm) {
              mm_clear_owner(p->mm, p);
              mmput(p->mm);
       }
bad_fork_cleanup_signal:
       if (!(clone_flags & CLONE_THREAD))
              free_signal_struct(p->signal);
bad_fork_cleanup_sighand:
       __cleanup_sighand(p->sighand);
bad_fork_cleanup_fs:
       exit_fs(p); /* blocking */
bad_fork_cleanup_files:
       exit_files(p); /* blocking */
bad_fork_cleanup_semundo:
       exit_sem(p);
bad_fork_cleanup_security:
       security_task_free(p);
bad_fork_cleanup_audit:
       audit_free(p);
bad_fork_cleanup_perf:
       perf_event_free_task(p);
bad_fork_cleanup_policy:
       lockdep_free_task(p);
#ifdef CONFIG_NUMA
       mpol_put(p->mempolicy);
bad_fork_cleanup_threadgroup_lock:
#endif
       delayacct_tsk_free(p);
bad_fork_cleanup_count:
       atomic_dec(&p->cred->user->processes);
       exit_creds(p);
bad_fork_free:
       p->state = TASK_DEAD;
       put_task_stack(p);
       delayed_free_task(p);
fork_out:
       spin_lock_irq(&current->sighand->siglock);
       hlist_del_init(&delayed.node);
       spin_unlock_irq(&current->sighand->siglock);
       return ERR_PTR(retval);
}
```



### copy_mm

if not **vfork**, dup_mm

```c
if (clone_flags & CLONE_VM) {
       mmget(oldmm);
       mm = oldmm;
} else {
       mm = dup_mm(tsk, current->mm);
       if (!mm)
              return -ENOMEM;
}
```



## schedule

__schedule() is the main scheduler function.

The main means of driving the scheduler and thus entering this function are:
1. Explicit blocking: mutex, semaphore, waitqueue, etc.
2. TIF_NEED_RESCHED flag is checked on interrupt and userspace return
   paths. For example, see arch/x86/entry_64.S.
   To drive preemption between tasks, the scheduler sets the flag in timer
   interrupt handler scheduler_tick().
3. Wakeups don't really cause entry into schedule(). They add a
   task to the run-queue and that's it.

Now, if the new task added to the run-queue preempts the current
task, then the wakeup sets TIF_NEED_RESCHED and schedule() gets
called on the nearest possible occasion:
- If the kernel is preemptible (CONFIG_PREEMPTION=y):
    - in syscall or exception context, at the next outmost
      preempt_enable(). (this might be as soon as the wake_up()'s
      spin_unlock()!)
    - in IRQ context, return from interrupt-handler to
      preemptible context
- If the kernel is not preemptible (CONFIG_PREEMPTION is not set)
  then at the next:
    - cond_resched() call
    - explicit schedule() call
    - return from syscall or exception to user-space
    - return from interrupt-handler to user-space

WARNING: must be called with preemption disabled!
```c
// kernel/sched/core.c
static void __sched notrace __schedule(bool preempt)
{
	struct task_struct *prev, *next;
	unsigned long *switch_count;
	unsigned long prev_state;
	struct rq_flags rf;
	struct rq *rq;
	int cpu;

	cpu = smp_processor_id();
	rq = cpu_rq(cpu);
	prev = rq->curr;

	schedule_debug(prev, preempt);

	if (sched_feat(HRTICK) || sched_feat(HRTICK_DL))
		hrtick_clear(rq);

	local_irq_disable();
	rcu_note_context_switch(preempt);

	/*
	 * Make sure that signal_pending_state()->signal_pending() below
	 * can't be reordered with __set_current_state(TASK_INTERRUPTIBLE)
	 * done by the caller to avoid the race with signal_wake_up():
	 *
	 * __set_current_state(@state)		signal_wake_up()
	 * schedule()				  set_tsk_thread_flag(p, TIF_SIGPENDING)
	 *					  wake_up_state(p, state)
	 *   LOCK rq->lock			    LOCK p->pi_state
	 *   smp_mb__after_spinlock()		    smp_mb__after_spinlock()
	 *     if (signal_pending_state())	    if (p->state & @state)
	 *
	 * Also, the membarrier system call requires a full memory barrier
	 * after coming from user-space, before storing to rq->curr.
	 */
	rq_lock(rq, &rf);
	smp_mb__after_spinlock();

	/* Promote REQ to ACT */
	rq->clock_update_flags <<= 1;
	update_rq_clock(rq);

	switch_count = &prev->nivcsw;

	/*
	 * We must load prev->state once (task_struct::state is volatile), such
	 * that:
	 *
	 *  - we form a control dependency vs deactivate_task() below.
	 *  - ptrace_{,un}freeze_traced() can change ->state underneath us.
	 */
	prev_state = prev->state;
	if (!preempt && prev_state) {
		if (signal_pending_state(prev_state, prev)) {
			prev->state = TASK_RUNNING;
		} else {
			prev->sched_contributes_to_load =
				(prev_state & TASK_UNINTERRUPTIBLE) &&
				!(prev_state & TASK_NOLOAD) &&
				!(prev->flags & PF_FROZEN);

			if (prev->sched_contributes_to_load)
				rq->nr_uninterruptible++;

			/*
			 * __schedule()			ttwu()
			 *   prev_state = prev->state;    if (p->on_rq && ...)
			 *   if (prev_state)		    goto out;
			 *     p->on_rq = 0;		  smp_acquire__after_ctrl_dep();
			 *				  p->state = TASK_WAKING
			 *
			 * Where __schedule() and ttwu() have matching control dependencies.
			 *
			 * After this, schedule() must not care about p->state any more.
			 */
			deactivate_task(rq, prev, DEQUEUE_SLEEP | DEQUEUE_NOCLOCK);

			if (prev->in_iowait) {
				atomic_inc(&rq->nr_iowait);
				delayacct_blkio_start();
			}
		}
		switch_count = &prev->nvcsw;
	}
```

pick next task
```c

	next = pick_next_task(rq, prev, &rf);
	clear_tsk_need_resched(prev);
	clear_preempt_need_resched();
#ifdef CONFIG_SCHED_DEBUG
	rq->last_seen_need_resched_ns = 0;
#endif

	if (likely(prev != next)) {
		rq->nr_switches++;
		/*
		 * RCU users of rcu_dereference(rq->curr) may not see
		 * changes to task_struct made by pick_next_task().
		 */
		RCU_INIT_POINTER(rq->curr, next);
		/*
		 * The membarrier system call requires each architecture
		 * to have a full memory barrier after updating
		 * rq->curr, before returning to user-space.
		 *
		 * Here are the schemes providing that barrier on the
		 * various architectures:
		 * - mm ? switch_mm() : mmdrop() for x86, s390, sparc, PowerPC.
		 *   switch_mm() rely on membarrier_arch_switch_mm() on PowerPC.
		 * - finish_lock_switch() for weakly-ordered
		 *   architectures where spin_unlock is a full barrier,
		 * - switch_to() for arm64 (weakly-ordered, spin_unlock
		 *   is a RELEASE barrier),
		 */
		++*switch_count;

		migrate_disable_switch(rq, prev);
		psi_sched_switch(prev, next, !task_on_rq_queued(prev));

		trace_sched_switch(preempt, prev, next);

		/* Also unlocks the rq: */
		rq = context_switch(rq, prev, next, &rf);
	} else {
		rq->clock_update_flags &= ~(RQCF_ACT_SKIP|RQCF_REQ_SKIP);

		rq_unpin_lock(rq, &rf);
		__balance_callbacks(rq);
		raw_spin_unlock_irq(&rq->lock);
	}
}

```


### context switch
context_switch - switch to the new MM and the new thread's register state.
```c
// kernel/linux/core.c
static __always_inline struct rq *
context_switch(struct rq *rq, struct task_struct *prev,
	       struct task_struct *next, struct rq_flags *rf)
{
	prepare_task_switch(rq, prev, next);

	/*
	 * For paravirt, this is coupled with an exit in switch_to to
	 * combine the page table reload and the switch backend into
	 * one hypercall.
	 */
	arch_start_context_switch(prev);

	/*
	 * kernel -> kernel   lazy + transfer active
	 *   user -> kernel   lazy + mmgrab() active
	 *
	 * kernel ->   user   switch + mmdrop() active
	 *   user ->   user   switch
	 */
	if (!next->mm) {                                // to kernel
		enter_lazy_tlb(prev->active_mm, next);

		next->active_mm = prev->active_mm;
		if (prev->mm)                           // from user
			mmgrab(prev->active_mm);
		else
			prev->active_mm = NULL;
	} else {                                        // to user
		membarrier_switch_mm(rq, prev->active_mm, next->mm);
		/*
		 * sys_membarrier() requires an smp_mb() between setting
		 * rq->curr / membarrier_switch_mm() and returning to userspace.
		 *
		 * The below provides this either through switch_mm(), or in
		 * case 'prev->active_mm == next->mm' through
		 * finish_task_switch()'s mmdrop().
		 */
		switch_mm_irqs_off(prev->active_mm, next->mm, next);

		if (!prev->mm) {                        // from kernel
			/* will mmdrop() in finish_task_switch(). */
			rq->prev_mm = prev->active_mm;
			prev->active_mm = NULL;
		}
	}

	rq->clock_update_flags &= ~(RQCF_ACT_SKIP|RQCF_REQ_SKIP);

	prepare_lock_switch(rq, next, rf);

	/* Here we just switch the register state and the stack. */
	switch_to(prev, next, prev);
	barrier();

	return finish_task_switch(prev);
}
```