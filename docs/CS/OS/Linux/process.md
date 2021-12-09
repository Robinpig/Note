





### task struct

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

```c
/*
 * Set up the first task table, touch at your own risk!. Base=0,
 * limit=0x1fffff (=2MB)
 */
struct task_struct init_task
#ifdef CONFIG_ARCH_TASK_STRUCT_ON_STACK
       __init_task_data
#endif
       __aligned(L1_CACHE_BYTES)
= {
#ifdef CONFIG_THREAD_INFO_IN_TASK
       .thread_info   = INIT_THREAD_INFO(init_task),
       .stack_refcount        = REFCOUNT_INIT(1),
#endif
       .state        = 0,
       .stack        = init_stack,
       .usage        = REFCOUNT_INIT(2),
       .flags        = PF_KTHREAD,
       .prio         = MAX_PRIO - 20,
       .static_prio   = MAX_PRIO - 20,
       .normal_prio   = MAX_PRIO - 20,
       .policy               = SCHED_NORMAL,
       .cpus_ptr      = &init_task.cpus_mask,
       .cpus_mask     = CPU_MASK_ALL,
       .nr_cpus_allowed= NR_CPUS,
       .mm           = NULL,
       .active_mm     = &init_mm,
       .restart_block = {
              .fn = do_no_restart_syscall,
       },
       .se           = {
              .group_node    = LIST_HEAD_INIT(init_task.se.group_node),
       },
       .rt           = {
              .run_list      = LIST_HEAD_INIT(init_task.rt.run_list),
              .time_slice    = RR_TIMESLICE,
       },
       .tasks        = LIST_HEAD_INIT(init_task.tasks),
#ifdef CONFIG_SMP
       .pushable_tasks        = PLIST_NODE_INIT(init_task.pushable_tasks, MAX_PRIO),
#endif
#ifdef CONFIG_CGROUP_SCHED
       .sched_task_group = &root_task_group,
#endif
       .ptraced       = LIST_HEAD_INIT(init_task.ptraced),
       .ptrace_entry  = LIST_HEAD_INIT(init_task.ptrace_entry),
       .real_parent   = &init_task,
       .parent               = &init_task,
       .children      = LIST_HEAD_INIT(init_task.children),
       .sibling       = LIST_HEAD_INIT(init_task.sibling),
       .group_leader  = &init_task,
       RCU_POINTER_INITIALIZER(real_cred, &init_cred),
       RCU_POINTER_INITIALIZER(cred, &init_cred),
       .comm         = INIT_TASK_COMM,
       .thread               = INIT_THREAD,
       .fs           = &init_fs,
       .files        = &init_files,
#ifdef CONFIG_IO_URING
       .io_uring      = NULL,
#endif
       .signal               = &init_signals,
       .sighand       = &init_sighand,
       .nsproxy       = &init_nsproxy,
       .pending       = {
              .list = LIST_HEAD_INIT(init_task.pending.list),
              .signal = {{0}}
       },
       .blocked       = {{0}},
       .alloc_lock    = __SPIN_LOCK_UNLOCKED(init_task.alloc_lock),
       .journal_info  = NULL,
       INIT_CPU_TIMERS(init_task)
       .pi_lock       = __RAW_SPIN_LOCK_UNLOCKED(init_task.pi_lock),
       .timer_slack_ns = 50000, /* 50 usec default slack */
       .thread_pid    = &init_struct_pid,
       .thread_group  = LIST_HEAD_INIT(init_task.thread_group),
       .thread_node   = LIST_HEAD_INIT(init_signals.thread_head),
#ifdef CONFIG_AUDIT
       .loginuid      = INVALID_UID,
       .sessionid     = AUDIT_SID_UNSET,
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
       .pi_waiters    = RB_ROOT_CACHED,
       .pi_top_task   = NULL,
#endif
       INIT_PREV_CPUTIME(init_task)
#ifdef CONFIG_VIRT_CPU_ACCOUNTING_GEN
       .vtime.seqcount        = SEQCNT_ZERO(init_task.vtime_seqcount),
       .vtime.starttime = 0,
       .vtime.state   = VTIME_SYS,
#endif
#ifdef CONFIG_NUMA_BALANCING
       .numa_preferred_nid = NUMA_NO_NODE,
       .numa_group    = NULL,
       .numa_faults   = NULL,
#endif
#if defined(CONFIG_KASAN_GENERIC) || defined(CONFIG_KASAN_SW_TAGS)
       .kasan_depth   = 1,
#endif
#ifdef CONFIG_KCSAN
       .kcsan_ctx = {
              .disable_count        = 0,
              .atomic_next          = 0,
              .atomic_nest_count     = 0,
              .in_flat_atomic               = false,
              .access_mask          = 0,
              .scoped_accesses       = {LIST_POISON1, NULL},
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
       .ret_stack            = NULL,
       .tracing_graph_pause   = ATOMIC_INIT(0),
#endif
#if defined(CONFIG_TRACING) && defined(CONFIG_PREEMPTION)
       .trace_recursion = 0,
#endif
#ifdef CONFIG_LIVEPATCH
       .patch_state   = KLP_UNDEFINED,
#endif
#ifdef CONFIG_SECURITY
       .security      = NULL,
#endif
#ifdef CONFIG_SECCOMP_FILTER
       .seccomp       = { .filter_count = ATOMIC_INIT(0) },
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