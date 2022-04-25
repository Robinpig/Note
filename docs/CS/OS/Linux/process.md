## Introduction





### task struct

The Linux kernel internally represents processes as tasks, via the structure `task struct`.
Unlike other OS approaches (which make a distinction between a process, lightweight process, and thread), Linux uses the task structure to represent any execution context. 
Therefore, a single-threaded process will be represented with one task structure and a multithreaded process will have one task structure for each of the user-level threads. 
Finally, the kernel itself is multithreaded, and has kernel-level threads which are not associated with any user process and are executing kernel code.

For compatibility with other UNIX systems, Linux identifies processes via the PID. The kernel organizes all processes in a doubly linked list of task structures.
In addition to accessing process descriptors by traversing the linked lists, the PID can be mapped to the address of the task structure, and the process information can be accessed immediately.


```c
// include/linux/sched.h
struct task_struct {
#ifdef CONFIG_THREAD_INFO_IN_TASK
       /*
        * For reasons of header soup (see current_thread_info()), this
        * must be the first element of task_struct.
        */
       struct thread_info            thread_info;
#endif
       /* -1 unrunnable, 0 runnable, >0 stopped: */
       volatile long                state;

       /*
        * This begins the randomizable portion of task_struct. Only
        * scheduling-critical items should be added above here.
        */
       randomized_struct_fields_start

       void                        *stack;
       refcount_t                   usage;
       /* Per task flags (PF_*), defined further below: */
       unsigned int                 flags;
       unsigned int                 ptrace;

#ifdef CONFIG_SMP
       int                         on_cpu;
       struct __call_single_node      wake_entry;
#ifdef CONFIG_THREAD_INFO_IN_TASK
       /* Current CPU: */
       unsigned int                 cpu;
#endif
       unsigned int                 wakee_flips;
       unsigned long                wakee_flip_decay_ts;
       struct task_struct            *last_wakee;

       /*
        * recent_used_cpu is initially set as the last CPU used by a task
        * that wakes affine another task. Waker/wakee relationships can
        * push tasks around a CPU where each wakeup moves to the next one.
        * Tracking a recently used CPU allows a quick search for a recently
        * used CPU that may be idle.
        */
       int                         recent_used_cpu;
       int                         wake_cpu;
#endif
       int                         on_rq;

       int                         prio;
       int                         static_prio;
       int                         normal_prio;
       unsigned int                 rt_priority;

       const struct sched_class       *sched_class;
       struct sched_entity           se;
       struct sched_rt_entity        rt;
#ifdef CONFIG_CGROUP_SCHED
       struct task_group             *sched_task_group;
#endif
       struct sched_dl_entity        dl;

#ifdef CONFIG_UCLAMP_TASK
       /*
        * Clamp values requested for a scheduling entity.
        * Must be updated with task_rq_lock() held.
        */
       struct uclamp_se              uclamp_req[UCLAMP_CNT];
       /*
        * Effective clamp values used for a scheduling entity.
        * Must be updated with task_rq_lock() held.
        */
       struct uclamp_se              uclamp[UCLAMP_CNT];
#endif

#ifdef CONFIG_PREEMPT_NOTIFIERS
       /* List of struct preempt_notifier: */
       struct hlist_head             preempt_notifiers;
#endif

#ifdef CONFIG_BLK_DEV_IO_TRACE
       unsigned int                 btrace_seq;
#endif

       unsigned int                 policy;
       int                         nr_cpus_allowed;
       const cpumask_t                      *cpus_ptr;
       cpumask_t                    cpus_mask;
       void                        *migration_pending;
#ifdef CONFIG_SMP
       unsigned short               migration_disabled;
#endif
       unsigned short               migration_flags;

#ifdef CONFIG_PREEMPT_RCU
       int                         rcu_read_lock_nesting;
       union rcu_special             rcu_read_unlock_special;
       struct list_head              rcu_node_entry;
       struct rcu_node                      *rcu_blocked_node;
#endif /* #ifdef CONFIG_PREEMPT_RCU */

#ifdef CONFIG_TASKS_RCU
       unsigned long                rcu_tasks_nvcsw;
       u8                          rcu_tasks_holdout;
       u8                          rcu_tasks_idx;
       int                         rcu_tasks_idle_cpu;
       struct list_head              rcu_tasks_holdout_list;
#endif /* #ifdef CONFIG_TASKS_RCU */

#ifdef CONFIG_TASKS_TRACE_RCU
       int                         trc_reader_nesting;
       int                         trc_ipi_to_cpu;
       union rcu_special             trc_reader_special;
       bool                        trc_reader_checked;
       struct list_head              trc_holdout_list;
#endif /* #ifdef CONFIG_TASKS_TRACE_RCU */

       struct sched_info             sched_info;

       struct list_head              tasks;
#ifdef CONFIG_SMP
       struct plist_node             pushable_tasks;
       struct rb_node               pushable_dl_tasks;
#endif

       struct mm_struct              *mm;
       struct mm_struct              *active_mm;

       /* Per-thread vma caching: */
       struct vmacache                      vmacache;

#ifdef SPLIT_RSS_COUNTING
       struct task_rss_stat          rss_stat;
#endif
       int                         exit_state;
       int                         exit_code;
       int                         exit_signal;
       /* The signal sent when the parent dies: */
       int                         pdeath_signal;
       /* JOBCTL_*, siglock protected: */
       unsigned long                jobctl;

       /* Used for emulating ABI behavior of previous Linux versions: */
       unsigned int                 personality;

       /* Scheduler bits, serialized by scheduler locks: */
       unsigned                     sched_reset_on_fork:1;
       unsigned                     sched_contributes_to_load:1;
       unsigned                     sched_migrated:1;
#ifdef CONFIG_PSI
       unsigned                     sched_psi_wake_requeue:1;
#endif

       /* Force alignment to the next boundary: */
       unsigned                     :0;

       /* Unserialized, strictly 'current' */

       /*
        * This field must not be in the scheduler word above due to wakelist
        * queueing no longer being serialized by p->on_cpu. However:
        *
        * p->XXX = X;               ttwu()
        * schedule()                  if (p->on_rq && ..) // false
        *   smp_mb__after_spinlock();   if (smp_load_acquire(&p->on_cpu) && //true
        *   deactivate_task()              ttwu_queue_wakelist())
        *     p->on_rq = 0;                 p->sched_remote_wakeup = Y;
        *
        * guarantees all stores of 'current' are visible before
        * ->sched_remote_wakeup gets used, so it can be in this word.
        */
       unsigned                     sched_remote_wakeup:1;

       /* Bit to tell LSMs we're in execve(): */
       unsigned                     in_execve:1;
       unsigned                     in_iowait:1;
#ifndef TIF_RESTORE_SIGMASK
       unsigned                     restore_sigmask:1;
#endif
#ifdef CONFIG_MEMCG
       unsigned                     in_user_fault:1;
#endif
#ifdef CONFIG_COMPAT_BRK
       unsigned                     brk_randomized:1;
#endif
#ifdef CONFIG_CGROUPS
       /* disallow userland-initiated cgroup migration */
       unsigned                     no_cgroup_migration:1;
       /* task is frozen/stopped (used by the cgroup freezer) */
       unsigned                     frozen:1;
#endif
#ifdef CONFIG_BLK_CGROUP
       unsigned                     use_memdelay:1;
#endif
#ifdef CONFIG_PSI
       /* Stalled due to lack of memory */
       unsigned                     in_memstall:1;
#endif
#ifdef CONFIG_PAGE_OWNER
       /* Used by page_owner=on to detect recursion in page tracking. */
       unsigned                     in_page_owner:1;
#endif

       unsigned long                atomic_flags; /* Flags requiring atomic access. */

       struct restart_block          restart_block;

       pid_t                       pid;
       pid_t                       tgid;

#ifdef CONFIG_STACKPROTECTOR
       /* Canary value for the -fstack-protector GCC feature: */
       unsigned long                stack_canary;
#endif
       /*
        * Pointers to the (original) parent process, youngest child, younger sibling,
        * older sibling, respectively.  (p->father can be replaced with
        * p->real_parent->pid)
        */

       /* Real parent process: */
       struct task_struct __rcu       *real_parent;

       /* Recipient of SIGCHLD, wait4() reports: */
       struct task_struct __rcu       *parent;

       /*
        * Children/sibling form the list of natural children:
        */
       struct list_head              children;
       struct list_head              sibling;
       struct task_struct            *group_leader;

       /*
        * 'ptraced' is the list of tasks this task is using ptrace() on.
        *
        * This includes both natural children and PTRACE_ATTACH targets.
        * 'ptrace_entry' is this task's link on the p->parent->ptraced list.
        */
       struct list_head              ptraced;
       struct list_head              ptrace_entry;

       /* PID/PID hash table linkage. */
       struct pid                   *thread_pid;
       struct hlist_node             pid_links[PIDTYPE_MAX];
       struct list_head              thread_group;
       struct list_head              thread_node;

       struct completion             *vfork_done;

       /* CLONE_CHILD_SETTID: */
       int __user                   *set_child_tid;

       /* CLONE_CHILD_CLEARTID: */
       int __user                   *clear_child_tid;

       /* PF_IO_WORKER */
       void                        *pf_io_worker;

       u64                         utime;
       u64                         stime;
#ifdef CONFIG_ARCH_HAS_SCALED_CPUTIME
       u64                         utimescaled;
       u64                         stimescaled;
#endif
       u64                         gtime;
       struct prev_cputime           prev_cputime;
#ifdef CONFIG_VIRT_CPU_ACCOUNTING_GEN
       struct vtime                 vtime;
#endif

#ifdef CONFIG_NO_HZ_FULL
       atomic_t                     tick_dep_mask;
#endif
       /* Context switch counts: */
       unsigned long                nvcsw;
       unsigned long                nivcsw;

       /* Monotonic time in nsecs: */
       u64                         start_time;

       /* Boot based time in nsecs: */
       u64                         start_boottime;

       /* MM fault and swap info: this can arguably be seen as either mm-specific or thread-specific: */
       unsigned long                min_flt;
       unsigned long                maj_flt;

       /* Empty if CONFIG_POSIX_CPUTIMERS=n */
       struct posix_cputimers        posix_cputimers;

#ifdef CONFIG_POSIX_CPU_TIMERS_TASK_WORK
       struct posix_cputimers_work    posix_cputimers_work;
#endif

       /* Process credentials: */

       /* Tracer's credentials at attach: */
       const struct cred __rcu               *ptracer_cred;

       /* Objective and real subjective task credentials (COW): */
       const struct cred __rcu               *real_cred;

       /* Effective (overridable) subjective task credentials (COW): */
       const struct cred __rcu               *cred;

#ifdef CONFIG_KEYS
       /* Cached requested key. */
       struct key                   *cached_requested_key;
#endif

       /*
        * executable name, excluding path.
        *
        * - normally initialized setup_new_exec()
        * - access it with [gs]et_task_comm()
        * - lock it with task_lock()
        */
       char                        comm[TASK_COMM_LEN];

       struct nameidata              *nameidata;

#ifdef CONFIG_SYSVIPC
       struct sysv_sem                      sysvsem;
       struct sysv_shm                      sysvshm;
#endif
#ifdef CONFIG_DETECT_HUNG_TASK
       unsigned long                last_switch_count;
       unsigned long                last_switch_time;
#endif
       /* Filesystem information: */
       struct fs_struct              *fs;

       /* Open file information: */
       struct files_struct           *files;

#ifdef CONFIG_IO_URING
       struct io_uring_task          *io_uring;
#endif

       /* Namespaces: */
       struct nsproxy               *nsproxy;

       /* Signal handlers: */
       struct signal_struct          *signal;
       struct sighand_struct __rcu           *sighand;
       sigset_t                     blocked;
       sigset_t                     real_blocked;
       /* Restored if set_restore_sigmask() was used: */
       sigset_t                     saved_sigmask;
       struct sigpending             pending;
       unsigned long                sas_ss_sp;
       size_t                      sas_ss_size;
       unsigned int                 sas_ss_flags;

       struct callback_head          *task_works;

#ifdef CONFIG_AUDIT
#ifdef CONFIG_AUDITSYSCALL
       struct audit_context          *audit_context;
#endif
       kuid_t                      loginuid;
       unsigned int                 sessionid;
#endif
       struct seccomp               seccomp;
       struct syscall_user_dispatch   syscall_dispatch;

       /* Thread group tracking: */
       u64                         parent_exec_id;
       u64                         self_exec_id;

       /* Protection against (de-)allocation: mm, files, fs, tty, keyrings, mems_allowed, mempolicy: */
       spinlock_t                   alloc_lock;

       /* Protection of the PI data structures: */
       raw_spinlock_t               pi_lock;

       struct wake_q_node            wake_q;

#ifdef CONFIG_RT_MUTEXES
       /* PI waiters blocked on a rt_mutex held by this task: */
       struct rb_root_cached         pi_waiters;
       /* Updated under owner's pi_lock and rq lock */
       struct task_struct            *pi_top_task;
       /* Deadlock detection and priority inheritance handling: */
       struct rt_mutex_waiter        *pi_blocked_on;
#endif

#ifdef CONFIG_DEBUG_MUTEXES
       /* Mutex deadlock detection: */
       struct mutex_waiter           *blocked_on;
#endif

#ifdef CONFIG_DEBUG_ATOMIC_SLEEP
       int                         non_block_count;
#endif

#ifdef CONFIG_TRACE_IRQFLAGS
       struct irqtrace_events        irqtrace;
       unsigned int                 hardirq_threaded;
       u64                         hardirq_chain_key;
       int                         softirqs_enabled;
       int                         softirq_context;
       int                         irq_config;
#endif
#ifdef CONFIG_PREEMPT_RT
       int                         softirq_disable_cnt;
#endif

#ifdef CONFIG_LOCKDEP
# define MAX_LOCK_DEPTH                      48UL
       u64                         curr_chain_key;
       int                         lockdep_depth;
       unsigned int                 lockdep_recursion;
       struct held_lock              held_locks[MAX_LOCK_DEPTH];
#endif

#if defined(CONFIG_UBSAN) && !defined(CONFIG_UBSAN_TRAP)
       unsigned int                 in_ubsan;
#endif

       /* Journalling filesystem info: */
       void                        *journal_info;

       /* Stacked block device info: */
       struct bio_list                      *bio_list;

#ifdef CONFIG_BLOCK
       /* Stack plugging: */
       struct blk_plug                      *plug;
#endif

       /* VM state: */
       struct reclaim_state          *reclaim_state;

       struct backing_dev_info               *backing_dev_info;

       struct io_context             *io_context;

#ifdef CONFIG_COMPACTION
       struct capture_control        *capture_control;
#endif
       /* Ptrace state: */
       unsigned long                ptrace_message;
       kernel_siginfo_t              *last_siginfo;

       struct task_io_accounting      ioac;
#ifdef CONFIG_PSI
       /* Pressure stall state */
       unsigned int                 psi_flags;
#endif
#ifdef CONFIG_TASK_XACCT
       /* Accumulated RSS usage: */
       u64                         acct_rss_mem1;
       /* Accumulated virtual memory usage: */
       u64                         acct_vm_mem1;
       /* stime + utime since last update: */
       u64                         acct_timexpd;
#endif
#ifdef CONFIG_CPUSETS
       /* Protected by ->alloc_lock: */
       nodemask_t                   mems_allowed;
       /* Sequence number to catch updates: */
       seqcount_spinlock_t           mems_allowed_seq;
       int                         cpuset_mem_spread_rotor;
       int                         cpuset_slab_spread_rotor;
#endif
#ifdef CONFIG_CGROUPS
       /* Control Group info protected by css_set_lock: */
       struct css_set __rcu          *cgroups;
       /* cg_list protected by css_set_lock and tsk->alloc_lock: */
       struct list_head              cg_list;
#endif
#ifdef CONFIG_X86_CPU_RESCTRL
       u32                         closid;
       u32                         rmid;
#endif
#ifdef CONFIG_FUTEX
       struct robust_list_head __user *robust_list;
#ifdef CONFIG_COMPAT
       struct compat_robust_list_head __user *compat_robust_list;
#endif
       struct list_head              pi_state_list;
       struct futex_pi_state         *pi_state_cache;
       struct mutex                 futex_exit_mutex;
       unsigned int                 futex_state;
#endif
#ifdef CONFIG_PERF_EVENTS
       struct perf_event_context      *perf_event_ctxp[perf_nr_task_contexts];
       struct mutex                 perf_event_mutex;
       struct list_head              perf_event_list;
#endif
#ifdef CONFIG_DEBUG_PREEMPT
       unsigned long                preempt_disable_ip;
#endif
#ifdef CONFIG_NUMA
       /* Protected by alloc_lock: */
       struct mempolicy              *mempolicy;
       short                       il_prev;
       short                       pref_node_fork;
#endif
#ifdef CONFIG_NUMA_BALANCING
       int                         numa_scan_seq;
       unsigned int                 numa_scan_period;
       unsigned int                 numa_scan_period_max;
       int                         numa_preferred_nid;
       unsigned long                numa_migrate_retry;
       /* Migration stamp: */
       u64                         node_stamp;
       u64                         last_task_numa_placement;
       u64                         last_sum_exec_runtime;
       struct callback_head          numa_work;

       /*
        * This pointer is only modified for current in syscall and
        * pagefault context (and for tasks being destroyed), so it can be read
        * from any of the following contexts:
        *  - RCU read-side critical section
        *  - current->numa_group from everywhere
        *  - task's runqueue locked, task not running
        */
       struct numa_group __rcu               *numa_group;

       /*
        * numa_faults is an array split into four regions:
        * faults_memory, faults_cpu, faults_memory_buffer, faults_cpu_buffer
        * in this precise order.
        *
        * faults_memory: Exponential decaying average of faults on a per-node
        * basis. Scheduling placement decisions are made based on these
        * counts. The values remain static for the duration of a PTE scan.
        * faults_cpu: Track the nodes the process was running on when a NUMA
        * hinting fault was incurred.
        * faults_memory_buffer and faults_cpu_buffer: Record faults per node
        * during the current scan window. When the scan completes, the counts
        * in faults_memory and faults_cpu decay and these values are copied.
        */
       unsigned long                *numa_faults;
       unsigned long                total_numa_faults;

       /*
        * numa_faults_locality tracks if faults recorded during the last
        * scan window were remote/local or failed to migrate. The task scan
        * period is adapted based on the locality of the faults with different
        * weights depending on whether they were shared or private faults
        */
       unsigned long                numa_faults_locality[3];

       unsigned long                numa_pages_migrated;
#endif /* CONFIG_NUMA_BALANCING */

#ifdef CONFIG_RSEQ
       struct rseq __user *rseq;
       u32 rseq_sig;
       /*
        * RmW on rseq_event_mask must be performed atomically
        * with respect to preemption.
        */
       unsigned long rseq_event_mask;
#endif

       struct tlbflush_unmap_batch    tlb_ubc;

       union {
              refcount_t            rcu_users;
              struct rcu_head               rcu;
       };

       /* Cache last used pipe for splice(): */
       struct pipe_inode_info        *splice_pipe;

       struct page_frag              task_frag;

#ifdef CONFIG_TASK_DELAY_ACCT
       struct task_delay_info        *delays;
#endif

#ifdef CONFIG_FAULT_INJECTION
       int                         make_it_fail;
       unsigned int                 fail_nth;
#endif
       /*
        * When (nr_dirtied >= nr_dirtied_pause), it's time to call
        * balance_dirty_pages() for a dirty throttling pause:
        */
       int                         nr_dirtied;
       int                         nr_dirtied_pause;
       /* Start of a write-and-pause period: */
       unsigned long                dirty_paused_when;

#ifdef CONFIG_LATENCYTOP
       int                         latency_record_count;
       struct latency_record         latency_record[LT_SAVECOUNT];
#endif
       /*
        * Time slack values; these are used to round up poll() and
        * select() etc timeout values. These are in nanoseconds.
        */
       u64                         timer_slack_ns;
       u64                         default_timer_slack_ns;

#if defined(CONFIG_KASAN_GENERIC) || defined(CONFIG_KASAN_SW_TAGS)
       unsigned int                 kasan_depth;
#endif

#ifdef CONFIG_KCSAN
       struct kcsan_ctx              kcsan_ctx;
#ifdef CONFIG_TRACE_IRQFLAGS
       struct irqtrace_events        kcsan_save_irqtrace;
#endif
#endif

#if IS_ENABLED(CONFIG_KUNIT)
       struct kunit                 *kunit_test;
#endif

#ifdef CONFIG_FUNCTION_GRAPH_TRACER
       /* Index of current stored address in ret_stack: */
       int                         curr_ret_stack;
       int                         curr_ret_depth;

       /* Stack of return addresses for return function tracing: */
       struct ftrace_ret_stack               *ret_stack;

       /* Timestamp for last schedule: */
       unsigned long long            ftrace_timestamp;

       /*
        * Number of functions that haven't been traced
        * because of depth overrun:
        */
       atomic_t                     trace_overrun;

       /* Pause tracing: */
       atomic_t                     tracing_graph_pause;
#endif

#ifdef CONFIG_TRACING
       /* State flags for use by tracers: */
       unsigned long                trace;

       /* Bitmask and counter of trace recursion: */
       unsigned long                trace_recursion;
#endif /* CONFIG_TRACING */

#ifdef CONFIG_KCOV
       /* See kernel/kcov.c for more details. */

       /* Coverage collection mode enabled for this task (0 if disabled): */
       unsigned int                 kcov_mode;

       /* Size of the kcov_area: */
       unsigned int                 kcov_size;

       /* Buffer for coverage collection: */
       void                        *kcov_area;

       /* KCOV descriptor wired with this task or NULL: */
       struct kcov                  *kcov;

       /* KCOV common handle for remote coverage collection: */
       u64                         kcov_handle;

       /* KCOV sequence number: */
       int                         kcov_sequence;

       /* Collect coverage from softirq context: */
       unsigned int                 kcov_softirq;
#endif

#ifdef CONFIG_MEMCG
       struct mem_cgroup             *memcg_in_oom;
       gfp_t                       memcg_oom_gfp_mask;
       int                         memcg_oom_order;

       /* Number of pages to reclaim on returning to userland: */
       unsigned int                 memcg_nr_pages_over_high;

       /* Used by memcontrol for targeted memcg charge: */
       struct mem_cgroup             *active_memcg;
#endif

#ifdef CONFIG_BLK_CGROUP
       struct request_queue          *throttle_queue;
#endif

#ifdef CONFIG_UPROBES
       struct uprobe_task            *utask;
#endif
#if defined(CONFIG_BCACHE) || defined(CONFIG_BCACHE_MODULE)
       unsigned int                 sequential_io;
       unsigned int                 sequential_io_avg;
#endif
       struct kmap_ctrl              kmap_ctrl;
#ifdef CONFIG_DEBUG_ATOMIC_SLEEP
       unsigned long                task_state_change;
#endif
       int                         pagefault_disabled;
#ifdef CONFIG_MMU
       struct task_struct            *oom_reaper_list;
#endif
#ifdef CONFIG_VMAP_STACK
       struct vm_struct              *stack_vm_area;
#endif
#ifdef CONFIG_THREAD_INFO_IN_TASK
       /* A live task holds one reference: */
       refcount_t                   stack_refcount;
#endif
#ifdef CONFIG_LIVEPATCH
       int patch_state;
#endif
#ifdef CONFIG_SECURITY
       /* Used by LSM modules for access restriction: */
       void                        *security;
#endif
#ifdef CONFIG_BPF_SYSCALL
       /* Used by BPF task local storage */
       struct bpf_local_storage __rcu *bpf_storage;
#endif

#ifdef CONFIG_GCC_PLUGIN_STACKLEAK
       unsigned long                lowest_stack;
       unsigned long                prev_lowest_stack;
#endif

#ifdef CONFIG_X86_MCE
       void __user                  *mce_vaddr;
       __u64                       mce_kflags;
       u64                         mce_addr;
       __u64                       mce_ripv : 1,
                                   mce_whole_page : 1,
                                   __mce_reserved : 62;
       struct callback_head          mce_kill_me;
#endif

#ifdef CONFIG_KRETPROBES
       struct llist_head               kretprobe_instances;
#endif

       /*
        * New fields for task_struct should be added above here, so that
        * they are included in the randomized portion of task_struct.
        */
       randomized_struct_fields_end

       /* CPU-specific state of this task: */
       struct thread_struct          thread;

       /*
        * WARNING: on x86, 'thread_struct' contains a variable-sized
        * structure.  It *MUST* be at the end of 'task_struct'.
        *
        * Do not put anything below here!
        */
};
```



`get_current()` implement by different arch


#### state
Task state bitmask. NOTE! These bits are also
encoded in fs/proc/array.c: get_task_state().

We have two separate sets of flags: task->state
is about runnability, while task->exit_state are
about the task exiting. Confusing, but this way
modifying one set can't modify the other one by
mistake.

```c
// 
/* Used in tsk->state: */
#define TASK_RUNNING			0x0000
#define TASK_INTERRUPTIBLE		0x0001
#define TASK_UNINTERRUPTIBLE		0x0002
#define __TASK_STOPPED			0x0004
#define __TASK_TRACED			0x0008
/* Used in tsk->exit_state: */
#define EXIT_DEAD			0x0010
#define EXIT_ZOMBIE			0x0020
#define EXIT_TRACE			(EXIT_ZOMBIE | EXIT_DEAD)
/* Used in tsk->state again: */
#define TASK_PARKED			0x0040
#define TASK_DEAD			0x0080
#define TASK_WAKEKILL			0x0100
#define TASK_WAKING			0x0200
#define TASK_NOLOAD			0x0400
#define TASK_NEW			0x0800
#define TASK_STATE_MAX			0x1000

/* Convenience macros for the sake of set_current_state: */
#define TASK_KILLABLE			(TASK_WAKEKILL | TASK_UNINTERRUPTIBLE)
#define TASK_STOPPED			(TASK_WAKEKILL | __TASK_STOPPED)
#define TASK_TRACED			(TASK_WAKEKILL | __TASK_TRACED)

#define TASK_IDLE			(TASK_UNINTERRUPTIBLE | TASK_NOLOAD)

/* Convenience macros for the sake of wake_up(): */
#define TASK_NORMAL			(TASK_INTERRUPTIBLE | TASK_UNINTERRUPTIBLE)

/* get_task_state(): */
#define TASK_REPORT			(TASK_RUNNING | TASK_INTERRUPTIBLE | \
					 TASK_UNINTERRUPTIBLE | __TASK_STOPPED | \
					 __TASK_TRACED | EXIT_DEAD | EXIT_ZOMBIE | \
					 TASK_PARKED)

```


### init task

Set up the first task table, touch at your own risk!. Base=0,
**limit=0x1fffff (=2MB)**

```c
// init/init_task.c
struct task_struct init_task
#ifdef CONFIG_ARCH_TASK_STRUCT_ON_STACK
	__init_task_data
#endif
	__aligned(L1_CACHE_BYTES)
= {
#ifdef CONFIG_THREAD_INFO_IN_TASK
	.thread_info	= INIT_THREAD_INFO(init_task),
	.stack_refcount	= REFCOUNT_INIT(1),
#endif
	.__state	= 0,
```
fix up initial thread stack pointer vs thread_info confusion  
The task ->stack pointer only incidentally ends up having the same value as the thread_info, and in fact that will change.  
So fix the initial task struct initializer to point to 'init_stack' instead of 'init_thread_info', and make sure the ia64 definition for that exists.  
This actually makes the ia64 tsk->stack pointer be sensible for the initial task, but not for any other task.

```c
	.stack		= init_stack,
	.usage		= REFCOUNT_INIT(2),
	.flags		= PF_KTHREAD,
	.prio		= MAX_PRIO - 20,
	.static_prio	= MAX_PRIO - 20,
	.normal_prio	= MAX_PRIO - 20,
	.policy		= SCHED_NORMAL,
	.cpus_ptr	= &init_task.cpus_mask,
	.user_cpus_ptr	= NULL,
	.cpus_mask	= CPU_MASK_ALL,
	.nr_cpus_allowed= NR_CPUS,
	.mm		= NULL,
	.active_mm	= &init_mm,
	.restart_block	= {
		.fn = do_no_restart_syscall,
	},
	.se		= {
		.group_node 	= LIST_HEAD_INIT(init_task.se.group_node),
	},
	.rt		= {
		.run_list	= LIST_HEAD_INIT(init_task.rt.run_list),
		.time_slice	= RR_TIMESLICE,
	},
	.tasks		= LIST_HEAD_INIT(init_task.tasks),
#ifdef CONFIG_SMP
	.pushable_tasks	= PLIST_NODE_INIT(init_task.pushable_tasks, MAX_PRIO),
#endif
#ifdef CONFIG_CGROUP_SCHED
	.sched_task_group = &root_task_group,
#endif
	.ptraced	= LIST_HEAD_INIT(init_task.ptraced),
	.ptrace_entry	= LIST_HEAD_INIT(init_task.ptrace_entry),
	.real_parent	= &init_task,
	.parent		= &init_task,
	.children	= LIST_HEAD_INIT(init_task.children),
	.sibling	= LIST_HEAD_INIT(init_task.sibling),
	.group_leader	= &init_task,
	RCU_POINTER_INITIALIZER(real_cred, &init_cred),
	RCU_POINTER_INITIALIZER(cred, &init_cred),
	.comm		= INIT_TASK_COMM,
	.thread		= INIT_THREAD,
	.fs		= &init_fs,
	.files		= &init_files,
#ifdef CONFIG_IO_URING
	.io_uring	= NULL,
#endif
	.signal		= &init_signals,
	.sighand	= &init_sighand,
	.nsproxy	= &init_nsproxy,
	.pending	= {
		.list = LIST_HEAD_INIT(init_task.pending.list),
		.signal = {{0}}
	},
	.blocked	= {{0}},
	.alloc_lock	= __SPIN_LOCK_UNLOCKED(init_task.alloc_lock),
	.journal_info	= NULL,
	INIT_CPU_TIMERS(init_task)
	.pi_lock	= __RAW_SPIN_LOCK_UNLOCKED(init_task.pi_lock),
	.timer_slack_ns = 50000, /* 50 usec default slack */
	.thread_pid	= &init_struct_pid,
	.thread_group	= LIST_HEAD_INIT(init_task.thread_group),
	.thread_node	= LIST_HEAD_INIT(init_signals.thread_head),
#ifdef CONFIG_AUDIT
	.loginuid	= INVALID_UID,
	.sessionid	= AUDIT_SID_UNSET,
#endif
#ifdef CONFIG_PERF_EVENTS
	.perf_event_mutex = __MUTEX_INITIALIZER(init_task.perf_event_mutex),
	.perf_event_list = LIST_HEAD_INIT(init_task.perf_event_list),
#endif
#ifdef CONFIG_PREEMPT_RCU
	.rcu_read_lock_nesting = 0,
	.rcu_read_unlock_special.s = 0,
	.rcu_node_entry = LIST_HEAD_INIT(init_task.rcu_node_entry),
	.rcu_blocked_node = NULL,
#endif
#ifdef CONFIG_TASKS_RCU
	.rcu_tasks_holdout = false,
	.rcu_tasks_holdout_list = LIST_HEAD_INIT(init_task.rcu_tasks_holdout_list),
	.rcu_tasks_idle_cpu = -1,
#endif
#ifdef CONFIG_TASKS_TRACE_RCU
	.trc_reader_nesting = 0,
	.trc_reader_special.s = 0,
	.trc_holdout_list = LIST_HEAD_INIT(init_task.trc_holdout_list),
#endif
#ifdef CONFIG_CPUSETS
	.mems_allowed_seq = SEQCNT_SPINLOCK_ZERO(init_task.mems_allowed_seq,
						 &init_task.alloc_lock),
#endif
#ifdef CONFIG_RT_MUTEXES
	.pi_waiters	= RB_ROOT_CACHED,
	.pi_top_task	= NULL,
#endif
	INIT_PREV_CPUTIME(init_task)
#ifdef CONFIG_VIRT_CPU_ACCOUNTING_GEN
	.vtime.seqcount	= SEQCNT_ZERO(init_task.vtime_seqcount),
	.vtime.starttime = 0,
	.vtime.state	= VTIME_SYS,
#endif
#ifdef CONFIG_NUMA_BALANCING
	.numa_preferred_nid = NUMA_NO_NODE,
	.numa_group	= NULL,
	.numa_faults	= NULL,
#endif
#if defined(CONFIG_KASAN_GENERIC) || defined(CONFIG_KASAN_SW_TAGS)
	.kasan_depth	= 1,
#endif
#ifdef CONFIG_KCSAN
	.kcsan_ctx = {
		.disable_count		= 0,
		.atomic_next		= 0,
		.atomic_nest_count	= 0,
		.in_flat_atomic		= false,
		.access_mask		= 0,
		.scoped_accesses	= {LIST_POISON1, NULL},
	},
#endif
#ifdef CONFIG_TRACE_IRQFLAGS
	.softirqs_enabled = 1,
#endif
#ifdef CONFIG_LOCKDEP
	.lockdep_depth = 0, /* no locks held yet */
	.curr_chain_key = INITIAL_CHAIN_KEY,
	.lockdep_recursion = 0,
#endif
#ifdef CONFIG_FUNCTION_GRAPH_TRACER
	.ret_stack		= NULL,
	.tracing_graph_pause	= ATOMIC_INIT(0),
#endif
#if defined(CONFIG_TRACING) && defined(CONFIG_PREEMPTION)
	.trace_recursion = 0,
#endif
#ifdef CONFIG_LIVEPATCH
	.patch_state	= KLP_UNDEFINED,
#endif
#ifdef CONFIG_SECURITY
	.security	= NULL,
#endif
#ifdef CONFIG_SECCOMP_FILTER
	.seccomp	= { .filter_count = ATOMIC_INIT(0) },
#endif
};
EXPORT_SYMBOL(init_task);
```


#### thread_info


```c
// arch/x86/include/asm/thread_info.h
struct thread_info {
	unsigned long		flags;		/* low level flags */
	unsigned long		syscall_work;	/* SYSCALL_WORK_ flags */
	u32			status;		/* thread synchronous flags */
#ifdef CONFIG_SMP
	u32			cpu;		/* current CPU */
#endif
}
```


#### exit
```c
// kernel/exit.c

void __noreturn do_exit(long code)
{
	struct task_struct *tsk = current;
	int group_dead;

	/*
	 * We can get here from a kernel oops, sometimes with preemption off.
	 * Start by checking for critical errors.
	 * Then fix up important state like USER_DS and preemption.
	 * Then do everything else.
	 */

	WARN_ON(blk_needs_flush_plug(tsk));

	if (unlikely(in_interrupt()))
		panic("Aiee, killing interrupt handler!");
	if (unlikely(!tsk->pid))
		panic("Attempted to kill the idle task!");

	/*
	 * If do_exit is called because this processes oopsed, it's possible
	 * that get_fs() was left as KERNEL_DS, so reset it to USER_DS before
	 * continuing. Amongst other possible reasons, this is to prevent
	 * mm_release()->clear_child_tid() from writing to a user-controlled
	 * kernel address.
	 */
	force_uaccess_begin();

	if (unlikely(in_atomic())) {
		pr_info("note: %s[%d] exited with preempt_count %d\n",
			current->comm, task_pid_nr(current),
			preempt_count());
		preempt_count_set(PREEMPT_ENABLED);
	}

	profile_task_exit(tsk);
	kcov_task_exit(tsk);

	ptrace_event(PTRACE_EVENT_EXIT, code);

	validate_creds_for_do_exit(tsk);

	/*
	 * We're taking recursive faults here in do_exit. Safest is to just
	 * leave this task alone and wait for reboot.
	 */
	if (unlikely(tsk->flags & PF_EXITING)) {
		pr_alert("Fixing recursive fault but reboot is needed!\n");
		futex_exit_recursive(tsk);
		set_current_state(TASK_UNINTERRUPTIBLE);
		schedule();
	}

	io_uring_files_cancel(tsk->files);
	exit_signals(tsk);  /* sets PF_EXITING */

	/* sync mm's RSS info before statistics gathering */
	if (tsk->mm)
		sync_mm_rss(tsk->mm);
	acct_update_integrals(tsk);
	group_dead = atomic_dec_and_test(&tsk->signal->live);
	if (group_dead) {
		/*
		 * If the last thread of global init has exited, panic
		 * immediately to get a useable coredump.
		 */
		if (unlikely(is_global_init(tsk)))
			panic("Attempted to kill init! exitcode=0x%08x\n",
				tsk->signal->group_exit_code ?: (int)code);

#ifdef CONFIG_POSIX_TIMERS
		hrtimer_cancel(&tsk->signal->real_timer);
		exit_itimers(tsk->signal);
#endif
		if (tsk->mm)
			setmax_mm_hiwater_rss(&tsk->signal->maxrss, tsk->mm);
	}
	acct_collect(code, group_dead);
	if (group_dead)
		tty_audit_exit();
	audit_free(tsk);

	tsk->exit_code = code;
	taskstats_exit(tsk, group_dead);

	exit_mm();

	if (group_dead)
		acct_process();
	trace_sched_process_exit(tsk);

	exit_sem(tsk);
	exit_shm(tsk);
	exit_files(tsk);
	exit_fs(tsk);
	if (group_dead)
		disassociate_ctty(1);
	exit_task_namespaces(tsk);
	exit_task_work(tsk);
	exit_thread(tsk);

	/*
	 * Flush inherited counters to the parent - before the parent
	 * gets woken up by child-exit notifications.
	 *
	 * because of cgroup mode, must be called before cgroup_exit()
	 */
	perf_event_exit_task(tsk);

	sched_autogroup_exit_task(tsk);
	cgroup_exit(tsk);

	/*
	 * FIXME: do that only when needed, using sched_exit tracepoint
	 */
	flush_ptrace_hw_breakpoint(tsk);

	exit_tasks_rcu_start();
	exit_notify(tsk, group_dead);
	proc_exit_connector(tsk);
	mpol_put_task_policy(tsk);
#ifdef CONFIG_FUTEX
	if (unlikely(current->pi_state_cache))
		kfree(current->pi_state_cache);
#endif
	/*
	 * Make sure we are holding no locks:
	 */
	debug_check_no_locks_held();

	if (tsk->io_context)
		exit_io_context(tsk);

	if (tsk->splice_pipe)
		free_pipe_info(tsk->splice_pipe);

	if (tsk->task_frag.page)
		put_page(tsk->task_frag.page);

	validate_creds_for_do_exit(tsk);

	check_stack_usage();
	preempt_disable();
	if (tsk->nr_dirtied)
		__this_cpu_add(dirty_throttle_leaks, tsk->nr_dirtied);
	exit_rcu();
	exit_tasks_rcu_finish();

	lockdep_free_task(tsk);
	do_task_dead();
}
```

## fork

Processes are created in Linux in an especially simple manner. The fork system call creates an exact copy of the original process. 
The forking process is called the *parent process*. The new process is called the *child process*. The parent and child each have their own, private memory images. 
If the parent subsequently changes any of its variables, the changes are not visible to the child, and vice versa.

The fork system call returns a 0 to the child and a nonzero value, the child’s **PID** (*Process Identifier*), to the parent. Both processes normally check the return value and act accordingly.
The child doesn’t start running at main() like you might expect; rather, it just comes into life as if it had called fork() itself.

```c
void main(int argc, char *argv[])
{
    pid = fork( ); /* if the fork succeeds, pid > 0 in the parent */
    if (pid < 0) {
        handle error( ); /* fork failed (e.g., memory or some table is full) */
    } else if (pid > 0) {
        /* parent code goes here. /*/
    } else {
        /* child code goes here. /*/
    }
}
```

When the child process is created, there are now two active processes in the system.
The CPU scheduler determines which process runs at a given moment in time; because the scheduler is complex, we cannot usually make strong assumptions about what it will choose to do, and hence which process will run first. 
This nondeterminism, as it turns out, leads to some interesting problems, particularly in multi-threaded programs.



Linux systems give the child its own page tables, but have them point to the parent’s pages, only marked read only.
Whenever either process (the child or the parent) tries to write on a page, it gets a protection fault.
The kernel sees this and then allocates a new copy of the page to the faulting process and marks it read/write.
In this way, only pages that are actually written have to be copied.
This mechanism is called *copy on write*.
It has the additional benefit of not requiring two copies of the program in memory, thus saving RAM.


The `wait()` system call allows a parent to wait for its child to complete execution.

The `exec()` family of system calls allows a child to break free from its similarity to its parent and execute an entirely new program.
The exec merely replaces the current process — its text, data, heap, and stack segments — with a brand-new program from disk.
A successful call to `exec()` never returns.

The separation of fork() and exec() is essential in building a UNIX shell, because it lets the shell run code after the call to fork() but before the call to exec(); 
this code can alter the environment of the about-to-be-run program, and thus enables a variety of interesting features to be readily built.

> [!TIP]
> 
> GETTING IT RIGHT (LAMPSON’S LAW)
> 
> As Lampson states in his well-regarded “Hints for Computer Systems Design”, “Get it right. 
> Neither abstraction nor simplicity is a substitute for getting it right.” Sometimes, you just have to do the right thing, and when you do, it is way better than the alternatives. 
> 
> There are lots of ways to design APIs for process creation; however, the combination of fork() and exec() are simple and immensely powerful.

The shell is just a user program. 
It shows you a prompt and then waits for you to type something into it. You then type a command (i.e., the name of an executable program, plus any arguments) into it; 
in most cases, the shell then figures out where in the file system the executable resides, calls fork() to create a new child process to run the command, 
calls some variant of exec() to run the command, and then waits for the command to complete by calling wait(). 
When the child completes, the shell returns from wait() and prints out a prompt again, ready for your next command.

> [!NOTE]
> 
> Link: [fork: introduce kernel_clone()](https://lore.kernel.org/all/20200819104655.436656-2-christian.brauner@ubuntu.com/)
> 
> The old _do_fork() helper doesn't follow naming conventions of in-kernel helpers for syscalls.
> The process creation cleanup in [1] didn't change the name to something more reasonable mainly because _do_fork() was used in quite a few places.
> So sending this as a separate series seemed the better strategy. 
> 
> This commit does two things:
>   1. renames _do_fork() to kernel_clone() but keeps _do_fork() as a simple static inline wrapper around kernel_clone().
>   2. Changes the return type from long to pid_t. This aligns kernel_thread() and kernel_clone().
>
> Also, the return value from kernel_clone that is surfaced in fork(), vfork(), clone(), and clone3() is taken from pid_vrn() which returns a pid_t too.  
> Follow-up patches will switch each caller of _do_fork() and each place where it is referenced over to kernel_clone().
> After all these changes are done, we can remove _do_fork() completely and will only be left with kernel_clone().


#### clone flags

cloning flags:

```c
#define CSIGNAL		0x000000ff	/* signal mask to be sent at exit */
#define CLONE_VM	0x00000100	/* set if VM shared between processes */
#define CLONE_FS	0x00000200	/* set if fs info shared between processes */
#define CLONE_FILES	0x00000400	/* set if open files shared between processes */
#define CLONE_SIGHAND	0x00000800	/* set if signal handlers and blocked signals shared */
#define CLONE_PIDFD	0x00001000	/* set if a pidfd should be placed in parent */
#define CLONE_PTRACE	0x00002000	/* set if we want to let tracing continue on the child too */
#define CLONE_VFORK	0x00004000	/* set if the parent wants the child to wake it up on mm_release */
#define CLONE_PARENT	0x00008000	/* set if we want to have the same parent as the cloner */
#define CLONE_THREAD	0x00010000	/* Same thread group? */
#define CLONE_NEWNS	0x00020000	/* New mount namespace group */
#define CLONE_SYSVSEM	0x00040000	/* share system V SEM_UNDO semantics */
#define CLONE_SETTLS	0x00080000	/* create a new TLS for the child */
#define CLONE_PARENT_SETTID	0x00100000	/* set the TID in the parent */
#define CLONE_CHILD_CLEARTID	0x00200000	/* clear the TID in the child */
#define CLONE_DETACHED		0x00400000	/* Unused, ignored */
#define CLONE_UNTRACED		0x00800000	/* set if the tracing process can't force CLONE_PTRACE on this clone */
#define CLONE_CHILD_SETTID	0x01000000	/* set the TID in the child */
#define CLONE_NEWCGROUP		0x02000000	/* New cgroup namespace */
#define CLONE_NEWUTS		0x04000000	/* New utsname namespace */
#define CLONE_NEWIPC		0x08000000	/* New ipc namespace */
#define CLONE_NEWUSER		0x10000000	/* New user namespace */
#define CLONE_NEWPID		0x20000000	/* New pid namespace */
#define CLONE_NEWNET		0x40000000	/* New network namespace */
#define CLONE_IO		0x80000000	/* Clone io context */

/* Flags for the clone3() syscall. */
#define CLONE_CLEAR_SIGHAND 0x100000000ULL /* Clear any signal handler and reset to SIG_DFL. */
#define CLONE_INTO_CGROUP 0x200000000ULL /* Clone into a specific cgroup given the right permissions. */

/*
 * cloning flags intersect with CSIGNAL so can be used with unshare and clone3
 * syscalls only:
 */
#define CLONE_NEWTIME	0x00000080	/* New time namespace */

```


### system calls

fork
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
```
vfork
```c
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
Create a kernel thread.
```c
pid_t kernel_thread(int (*fn)(void *), void *arg, unsigned long flags)
{
	struct kernel_clone_args args = {
		.flags		= ((lower_32_bits(flags) | CLONE_VM |
				    CLONE_UNTRACED) & ~CSIGNAL),
		.exit_signal	= (lower_32_bits(flags) & CSIGNAL),
		.stack		= (unsigned long)fn,
		.stack_size	= (unsigned long)arg,
	};

	return kernel_clone(&args);
}
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
```
For legacy clone() calls, CLONE_PIDFD uses the parent_tid argument
to return the pidfd. Hence, CLONE_PIDFD and CLONE_PARENT_SETTID are
mutually exclusive. With clone3() CLONE_PIDFD has grown a separate
field in struct clone_args and it still doesn't make sense to have
them both point at the same memory location. Performing this check
here has the advantage that we don't need to have a separate helper
to check for legacy clone().
```c
       if ((args->flags & CLONE_PIDFD) &&
           (args->flags & CLONE_PARENT_SETTID) &&
           (args->pidfd == args->parent_tid))
              return -EINVAL;
```
Determine whether and which event to report to ptracer.  When
called from kernel_thread or CLONE_UNTRACED is explicitly
requested, no event is reported; otherwise, report if the event
for the type of forking is enabled.
```c
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
```
copy_process
```c
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


This creates a new process as a copy of the old one,
but does not actually start it yet.

It copies the registers, and all the appropriate
parts of the process environment (as per the clone
flags). The actual kick-off is left to the caller.
```c
//
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
```

If multiple threads are within copy_process(), then this check triggers too late. This doesn't hurt, the check is only there to stop root fork bombs.
```c
       retval = -EAGAIN;
       if (data_race(nr_threads >= max_threads))
              goto bad_fork_cleanup_count;
```

```c
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

```
Perform scheduler related setup. Assign this task to a CPU.
```
       retval = sched_fork(clone_flags, p);
       if (retval)
              goto bad_fork_cleanup_policy;
```


```c
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


#### dup_task_struct
```c
// kernel/fork.c

static struct task_struct *dup_task_struct(struct task_struct *orig, int node)
{
	struct task_struct *tsk;
	unsigned long *stack;
	struct vm_struct *stack_vm_area __maybe_unused;
	int err;

	if (node == NUMA_NO_NODE)
		node = tsk_fork_get_node(orig);
	tsk = alloc_task_struct_node(node);
	if (!tsk)
		return NULL;

	stack = alloc_thread_stack_node(tsk, node);
	if (!stack)
		goto free_tsk;

	if (memcg_charge_kernel_stack(tsk))
		goto free_stack;

	stack_vm_area = task_stack_vm_area(tsk);

	err = arch_dup_task_struct(tsk, orig);

	/*
	 * arch_dup_task_struct() clobbers the stack-related fields.  Make
	 * sure they're properly initialized before using any stack-related
	 * functions again.
	 */
	tsk->stack = stack;
#ifdef CONFIG_VMAP_STACK
	tsk->stack_vm_area = stack_vm_area;
#endif
#ifdef CONFIG_THREAD_INFO_IN_TASK
	refcount_set(&tsk->stack_refcount, 1);
#endif

	if (err)
		goto free_stack;

	err = scs_prepare(tsk, node);
	if (err)
		goto free_stack;

#ifdef CONFIG_SECCOMP
	/*
	 * We must handle setting up seccomp filters once we're under
	 * the sighand lock in case orig has changed between now and
	 * then. Until then, filter must be NULL to avoid messing up
	 * the usage counts on the error path calling free_task.
	 */
	tsk->seccomp.filter = NULL;
#endif
```
setup_thread_stack: set pointers between task_struct and thread_info
```
	setup_thread_stack(tsk, orig);
	clear_user_return_notifier(tsk);
	clear_tsk_need_resched(tsk);
	set_task_stack_end_magic(tsk);
	clear_syscall_work_syscall_user_dispatch(tsk);

#ifdef CONFIG_STACKPROTECTOR
	tsk->stack_canary = get_random_canary();
#endif
	if (orig->cpus_ptr == &orig->cpus_mask)
		tsk->cpus_ptr = &tsk->cpus_mask;
	dup_user_cpus_ptr(tsk, orig, node);

	/*
	 * One for the user space visible state that goes away when reaped.
	 * One for the scheduler.
	 */
	refcount_set(&tsk->rcu_users, 2);
	/* One for the rcu users */
	refcount_set(&tsk->usage, 1);
#ifdef CONFIG_BLK_DEV_IO_TRACE
	tsk->btrace_seq = 0;
#endif
	tsk->splice_pipe = NULL;
	tsk->task_frag.page = NULL;
	tsk->wake_q.next = NULL;
	tsk->pf_io_worker = NULL;

	account_kernel_stack(tsk, 1);

	kcov_task_init(tsk);
	kmap_local_fork(tsk);

#ifdef CONFIG_FAULT_INJECTION
	tsk->fail_nth = 0;
#endif

#ifdef CONFIG_BLK_CGROUP
	tsk->throttle_queue = NULL;
	tsk->use_memdelay = 0;
#endif

#ifdef CONFIG_MEMCG
	tsk->active_memcg = NULL;
#endif
	return tsk;

free_stack:
	free_thread_stack(tsk);
free_tsk:
	free_task_struct(tsk);
	return NULL;
}
```
implements by different arches

```c
// arch/x86/kernel/process.c
/*
 * this gets called so that we can store lazy state into memory and copy the
 * current task into the new thread.
 */
int arch_dup_task_struct(struct task_struct *dst, struct task_struct *src)
{
	memcpy(dst, src, arch_task_struct_size);
#ifdef CONFIG_VM86
	dst->thread.vm86 = NULL;
#endif
	/* Drop the copied pointer to current's fpstate */
	dst->thread.fpu.fpstate = NULL;

	return 0;
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



max threads

```c

/*
 * Protected counters by write_lock_irq(&tasklist_lock)
 */
unsigned long total_forks;	/* Handle normal Linux uptimes. */
int nr_threads;			/* The idle threads do not count.. */

static int max_threads;		/* tunable limit on nr_threads */
```

### sched_fork
fork()/clone()-time setup:
```c
// kernel/sched/core.c
int sched_fork(unsigned long clone_flags, struct task_struct *p)
{
	__sched_fork(clone_flags, p);
	/*
	 * We mark the process as NEW here. This guarantees that
	 * nobody will actually run it, and a signal or other external
	 * event cannot wake it up and insert it on the runqueue either.
	 */
	p->__state = TASK_NEW;

	/*
	 * Make sure we do not leak PI boosting priority to the child.
	 */
	p->prio = current->normal_prio;

	uclamp_fork(p);

	/*
	 * Revert to default priority/policy on fork if requested.
	 */
	if (unlikely(p->sched_reset_on_fork)) {
		if (task_has_dl_policy(p) || task_has_rt_policy(p)) {
			p->policy = SCHED_NORMAL;
			p->static_prio = NICE_TO_PRIO(0);
			p->rt_priority = 0;
		} else if (PRIO_TO_NICE(p->static_prio) < 0)
			p->static_prio = NICE_TO_PRIO(0);

		p->prio = p->normal_prio = p->static_prio;
		set_load_weight(p, false);

		/*
		 * We don't need the reset flag anymore after the fork. It has
		 * fulfilled its duty:
		 */
		p->sched_reset_on_fork = 0;
	}

	if (dl_prio(p->prio))
		return -EAGAIN;
	else if (rt_prio(p->prio))
		p->sched_class = &rt_sched_class;
	else
		p->sched_class = &fair_sched_class;

	init_entity_runnable_average(&p->se);

#ifdef CONFIG_SCHED_INFO
	if (likely(sched_info_on()))
		memset(&p->sched_info, 0, sizeof(p->sched_info));
#endif
#if defined(CONFIG_SMP)
	p->on_cpu = 0;
#endif
	init_task_preempt_count(p);
#ifdef CONFIG_SMP
	plist_node_init(&p->pushable_tasks, MAX_PRIO);
	RB_CLEAR_NODE(&p->pushable_dl_tasks);
#endif
	return 0;
}
```

## exec

Now the new address space must be created and filled in. 
If the system supports mapped files, as Linux and virtually all other UNIX-based systems do, the new page tables are set up to indicate that no pages are in memory, 
except perhaps one stack page, but that the address space is backed by the executable file on disk.
When the new process starts running, it will immediately get a page fault, which will cause the first page of code to be paged in from the executable file. 
In this way, nothing has to be loaded in advance, so programs can start quickly and fault in just those pages they need and no more.
Finally, the arguments and environment strings are copied to the new stack, the signals are reset, and the registers are initialized to all zeros. 
At this point, the new command can start running.


## Threads

Linux introduced a powerful new system call, clone, that blurred the distinction between processes and threads and possibly even inverted the primacy of the two concepts.
It is called as follows:
```c
pid = clone(function, stack ptr, sharing flags, arg);
```
The call creates a new thread, either in the current process or in a new process, depending on sharing flags. 
If the new thread is in the current process, it shares the address space with the existing threads, and every subsequent write to any byte in the address space by any thread is immediately visible to all the other threads in the process.

UNIX systems associate a
single PID with a process, independent of whether it is single- or multithreaded. 
In order to be compatible with other UNIX systems, Linux distinguishes between a *process identifier*(**PID**) and a *task identifier*(**TID**). Both fields are stored in the task structure. 
When clone is used to create a new process that shares nothing with its creator, PID is set to a new value; otherwise, the task receives a new TID, but inherits the PID. 
In this manner all threads in a process will receive the same PID as the first thread in the process.


## IPC

Processes in Linux can communicate with each other using a form of message passing. 
It is possible to create a channel between two processes into which one process can write a stream of bytes for the other to read. These channels are called **pipes**. 
Synchronization is possible because when a process tries to read from an empty pipe it is blocked until data are available.

Shell pipelines are implemented with pipes. When the shell sees a line like

```shell
sort <f | head
```

Processes can also communicate in another way besides pipes: software interrupts.

### Message Passing

Pipes and FIFOs

Pipes are the original form of Unix IPC.
FIFOs, sometimes called **named pipes**. 
Both pipes and FIFOs are accessed using the normal read and w r i t e functions.

#### Pipes
Pipes are provided with all flavors of Unix. A pipe is created by the pipe function and provides a one-way (unidirectional)flow of data.
Pipes have no names, and their biggest disadvantage is that they can be used only between processesthat have a parent process in common. 
Two unrelated processes cannot create a pipe between them and use it for IPC (ignoring descriptor passing).

```c
#include <unistd.h>
int pipe (int fd121);
```

Although a pipe is created by one process, it is rarely used within a single process.
Pipes are typically used to communicate between two different processes (a parent and child) in the following way. 
First, a process (which will be the parent)creates a pipe and then forks to create a copy of itself.
Next, the parent process closes the read end of one pipe, and the child process closes the write end of that same pipe. This provides a one-wayflow of data between the two proecesses.

All the pipes shown so far have been half-duplexor unidirectional, providing a oneway flow of data only. When a two-way flow of data is desired, we must create two pipes and use one foreach direction.

##### Full-Duplex Pipes
Some systems provide full-duplex pipes: SVR4's pipe function and the socketpair function provided by many kernels.

#### FIFOs

FIFO stands for first in,first out, and a Unix FIFO is similar to a pipe. It is a one-way(half-duplex)flow of data. 
But unlike pipes, a FIFO has a pathname associated with it, allowing unrelated processes to access a single FIFO. FIFOs are also called named pipes.

```c
#include <sys/types.h>
#include <sys/stat.h>

int mkf if o (const char *pathname, mode-t mode);
```

Posix Message Queues

System V Message Queues

### Synchronization

Mutexes and Condition Variables
Read-Write Locks
Record Locking
Posix Semaphores
System V Semaphores

### Shared Memory

Shared Memory Introduction

#### Posix Shared Memory

mmap

#### System V Shared Memory

shmget


### Remote Procedure Calls








## Scheduling

Linux threads are kernel threads, so scheduling is based on threads, not processes.
Linux distinguishes three classes of threads for scheduling purposes:
1. Real-time FIFO.
2. Real-time round robin.
3. Timesharing

Real-time FIFO threads are the highest priority and are not preemptable except by a newly readied real-time FIFO thread with even higher priority. 
Real-time roundrobin threads are the same as real-time FIFO threads except that they hav e time quanta associated with them, and are preemptable by the clock. 
If multiple realtime round-robin threads are ready, each one is run for its quantum, after which it goes to the end of the list of real-time round-robin threads. 
Neither of these classes is actually real time in any sense. Deadlines cannot be specified and guarantees are not given. 
These classes are simply higher priority than threads in the standard timesharing class. 
The reason Linux calls them real time is that Linux is conformant to the P1003.4 standard (‘‘real-time’’ extensions to UNIX) which uses those names. 
The real-time threads are internally represented with priority levels from 0 to 99, 0 being the highest and 99 the lowest real-time priority level.

The conventional, non-real-time threads form a separate class and are scheduled by a separate algorithm so they do not compete with the real-time threads. 
Internally, these threads are associated with priority levels from 100 to 139, that is, Linux internally distinguishes among 140 priority levels (for real-time and nonreal-time tasks). 
As for the real-time round-robin threads, Linux allocates CPU time to the non-real-time tasks based on their requirements and their priority levels.

In Linux, time is measured as the number of clock ticks. In older Linux versions, the clock ran at 1000Hz and each tick was 1ms, called a jiffy. In newer versions, the tick frequency can be configured to 500, 250 or even 1Hz. In order to
avoid wasting CPU cycles for servicing the timer interrupt, the kernel can even be
configured in ‘‘tickless’’ mode. This is useful when there is only one process running in the system, or when the CPU is idle and needs to go into power-saving
mode. Finally, on newer systems, high-resolution timers allow the kernel to keep
track of time in sub-jiffy granularity.


### Scheduler

Besides the basic scheduling alogirithm, the Linux scheduler includes special features particularly useful for multiprocessor or multicore platforms. 
First, the runqueue structure is associated with each CPU in the multiprocessing platform.
- The scheduler tries to maintain benefits from **affinity scheduling**, and to schedule tasks on the CPU on which they were previously executing. 
- Second, a set of system calls is available to further specify or modify the affinity requirements of a select thread. 
- Finally, the scheduler performs periodic load balancing across runqueues of different CPUs to ensure that the system load is well balanced, while still meeting certain performance or affinity requirements.

The scheduler considers only runnable tasks, which are placed on the appropriate runqueue. 
Tasks which are not runnable and are waiting on various I/O operations or other kernel events are placed on another data structure, waitqueue. A waitqueue is associated with each event that tasks may wait on. 
The head of the waitqueue includes a pointer to a linked list of tasks and a spinlock. 
The spinlock is necessary so as to ensure that the waitqueue can be concurrently manipulated through both the main kernel code and interrupt handlers or other asynchronous invocations.

#### O(1)

Historically, a popular Linux scheduler was the Linux O(1) scheduler. 
It received its name because it was able to perform task-management operations, such as selecting a task or enqueueing a task on the runqueue, in constant time, independent of the total number of tasks in the system. 
In the O(1) scheduler, the runqueue is organized in two arrays, active and expired. 
Each of these is an array of 140 list heads, each corresponding to a different priority. Each list head points to a doubly linked list of processes at a given priority.
The basic operation of the scheduler can be described as follows.

The scheduler selects a task from the highest-priority list in the active array. 
If that task’s timeslice (quantum) expires, it is moved to the expired list (potentially at a different priority level). 
If the task blocks, for instance to wait on an I/O event, before its timeslice expires, once the event occurs and its execution can resume, it is placed back on the original active array, and its timeslice is decremented to reflect the CPU time it already used. 
Once its timeslice is fully exhausted, it, too, will be placed on the expired array. 
When there are no more tasks in the active array, the scheduler simply swaps the pointers, so the expired arrays now become active, and vice versa. 
This method ensures that low-priority tasks will not starve(except when real-time FIFO threads completely hog the CPU, which is unlikely).

Different priority levels are assigned different timeslice values, with higher quanta assigned to higher-priority processes.

The idea behind this scheme is to get processes out of the kernel fast. 
If a process was blocked waiting for keyboard input, it is clearly an interactive process, and as such should be given a high priority as soon as it is ready in order to ensure that interactive processes get good service.




Since Linux (or any other OS) does not know a priori whether a task is I/O- or CPU-bound, it relies on continuously maintaining interactivity heuristics. 
In this manner, Linux distinguishes between static and dynamic priority. 
The threads’ dynamic priority is continuously recalculated, so as to (1) reward interactive threads, and (2) punish CPU-hogging threads. 
In the O(1) scheduler, the maximum priority bonus is −5, since lower-priority values correspond to higher priority received by the scheduler. The maximum priority penalty is +5.
The scheduler maintains a sleep avg variable associated with each task. Whenever a task is awakened, this variable is incremented. 
Whenever a task is preempted or when its quantum expires, this variable is decremented by the corresponding value. 
This value is used to dynamically map the task’s bonus to values from −5 to +5. 
The scheduler recalculates the new priority level as a thread is moved from the active to the expired list.

However, in spite of the desirable property of constant-time operation, the O(1) scheduler had significant shortcomings. 
Most notably, the heuristics used to determine the interactivity of a task, and therefore its priority level, were complex and imperfect, and resulted in poor performance for interactive tasks.


#### CFS

CFS was based on ideas originally developed by Con Kolivas for an earlier scheduler, and was first integrated into the 2.6.23 release of the kernel. It is still the default scheduler for the non-real-time tasks.

The main idea behind CFS is to use a red-black tree as the runqueue data structure. Tasks are ordered in the tree based on the amount of time they spend running on the CPU, called vruntime. 
CFS accounts for the tasks’ running time with nanosecond granularity.
Each internal node in the tree corresponds to a task. 
The children to the left correspond to tasks which had less time on the CPU, and therefore will be scheduled sooner, and the children to the right on the node are those that have consumed more CPU time thus far. 
The leaves in the tree do not play any role in the scheduler.

CFS always schedules the task which has had least amount of time on the CPU, typically the leftmost node in the tree. Periodically, 
CFS increments the task’s vruntime value based on the time it has already run, and compares this to the current leftmost node in the tree. 
If the running task still has smaller vruntime, it will continue to run. 
Otherwise, it will be inserted at the appropriate place in the red-black tree, and the CPU will be given to task corresponding to the new leftmost node.

To account for differences in task priorities and ‘‘niceness,’’ CFS changes the effective rate at which a task’s virtual time passes when it is running on the CPU.
For lower-priority tasks, time passes more quickly, their vruntime value will increase more rapidly, and, depending on other tasks in the system, they will lose the CPU and be reinserted in the tree sooner than if they had a higher priority value. 
In this manner, CFS avoids using separate runqueue structures for different priority levels.

In summary, selecting a node to run can be done in constant time, whereas inserting a task in the runqueue is done in O(log(N)) time, where N is the number of tasks in the system. 
Given the levels of load in current systems, this continues to be acceptable.








## Links
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [OS Process](/docs/CS/OS/process.md)