## Introduction

thundering herd

## Common

### wait

prepare_to_wait_exclusive

WQ_FLAG_EXCLUSIVE

```c
void
prepare_to_wait_exclusive(struct wait_queue_head *wq_head, struct wait_queue_entry *wq_entry, int state)
{
	unsigned long flags;

	wq_entry->flags |= WQ_FLAG_EXCLUSIVE;
	spin_lock_irqsave(&wq_head->lock, flags);
	if (list_empty(&wq_entry->entry))
		__add_wait_queue_entry_tail(wq_head, wq_entry);
	set_current_state(state);
	spin_unlock_irqrestore(&wq_head->lock, flags);
}
EXPORT_SYMBOL(prepare_to_wait_exclusive);
```

```c
/* wait_queue_entry::flags */
#define WQ_FLAG_EXCLUSIVE      0x01
#define WQ_FLAG_WOKEN         0x02
#define WQ_FLAG_BOOKMARK       0x04
#define WQ_FLAG_CUSTOM        0x08
#define WQ_FLAG_DONE          0x10
#define WQ_FLAG_PRIORITY       0x20
```

### wake

```c
/**
 * wake_up_process - Wake up a specific process
 * @p: The process to be woken up.
 *
 * Attempt to wake up the nominated process and move it to the set of runnable
 * processes.
 *
 * Return: 1 if the process was woken up, 0 if it was already running.
 *
 * This function executes a full memory barrier before accessing the task state.
 */
int wake_up_process(struct task_struct *p)
{
       return try_to_wake_up(p, TASK_NORMAL, 0);
}
EXPORT_SYMBOL(wake_up_process);
```

wake up threads blocked on a waitqueue.

```c

/**
 * __wake_up - 
 * @wq_head: the waitqueue
 * @mode: which threads
 * @nr_exclusive: how many wake-one or wake-many threads to wake up
 * @key: is directly passed to the wakeup function
 *
 * If this function wakes up a task, it executes a full memory barrier before
 * accessing the task state.
 */
void __wake_up(struct wait_queue_head *wq_head, unsigned int mode,
			int nr_exclusive, void *key)
{
	__wake_up_common_lock(wq_head, mode, nr_exclusive, 0, key);
}
```

#### wake_up_common

The core wakeup function.
Non-exclusive wakeups (nr_exclusive == 0) just wake everything up.
If it's an exclusive wakeup (nr_exclusive == small +ve number) then we wake that number of exclusive tasks, and potentially all the non-exclusive tasks.
Normally, exclusive tasks will be at the end of the list and any non-exclusive tasks will be woken first.
A priority task may be at the head of the list, and can consume the event without any other tasks being woken.

There are circumstances in which we can try to wake a task which has already started to run but is not in state TASK_RUNNING. `try_to_wake_up()` returns zero in this (rare) case, and we handle it by continuing to scan the queue.

call `wait_queue_entry.func`:

```c
// wait.c
static int __wake_up_common(struct wait_queue_head *wq_head, unsigned int mode,
                     int nr_exclusive, int wake_flags, void *key,
                     wait_queue_entry_t *bookmark)
{
       wait_queue_entry_t *curr, *next;
       int cnt = 0;


       if (bookmark && (bookmark->flags & WQ_FLAG_BOOKMARK)) {
              curr = list_next_entry(bookmark, entry);

              list_del(&bookmark->entry);
              bookmark->flags = 0;
       } else
              curr = list_first_entry(&wq_head->head, wait_queue_entry_t, entry);

       if (&curr->entry == &wq_head->head)
              return nr_exclusive;

       list_for_each_entry_safe_from(curr, next, &wq_head->head, entry) {
              unsigned flags = curr->flags;
              int ret;

              if (flags & WQ_FLAG_BOOKMARK)
                     continue;

              ret = curr->func(curr, mode, wake_flags, key);
              if (ret < 0)
                     break;
              if (ret && (flags & WQ_FLAG_EXCLUSIVE) && !--nr_exclusive)
                     break;

              if (bookmark && (++cnt > WAITQUEUE_WALK_BREAK_CNT) &&
                            (&next->entry != &wq_head->head)) {
                     bookmark->flags = WQ_FLAG_BOOKMARK;
                     list_add_tail(&bookmark->entry, &next->entry);
                     break;
              }
       }

       return nr_exclusive;
}
```

#### try_to_wake_up


 * Notes on Program-Order guarantees on SMP systems.
 *
 *  MIGRATION
 *
 * The basic program-order guarantee on SMP systems is that when a task [t]
 * migrates, all its activity on its old CPU [c0] happens-before any subsequent
 * execution on its new CPU [c1].
 *
 * For migration (of runnable tasks) this is provided by the following means:
 *
 *  A) UNLOCK of the rq(c0)->lock scheduling out task t
 *  B) migration for t is required to synchronize *both* rq(c0)->lock and
 *     rq(c1)->lock (if not at the same time, then in that order).
 *  C) LOCK of the rq(c1)->lock scheduling in task
 *
 * Release/acquire chaining guarantees that B happens after A and C after B.
 * Note: the CPU doing B need not be c0 or c1
 *
 * Example:
 *
 *   CPU0            CPU1            CPU2
 *
 *   LOCK rq(0)->lock
 *   sched-out X
 *   sched-in Y
 *   UNLOCK rq(0)->lock
 *
 *                                   LOCK rq(0)->lock // orders against CPU0
 *                                   dequeue X
 *                                   UNLOCK rq(0)->lock
 *
 *                                   LOCK rq(1)->lock
 *                                   enqueue X
 *                                   UNLOCK rq(1)->lock
 *
 *                   LOCK rq(1)->lock // orders against CPU2
 *                   sched-out Z
 *                   sched-in X
 *                   UNLOCK rq(1)->lock
 *
 *
 *  BLOCKING -- aka. SLEEP + WAKEUP
 *
 * For blocking we (obviously) need to provide the same guarantee as for
 * migration. However the means are completely different as there is no lock
 * chain to provide order. Instead we do:
 *
 *   1) smp_store_release(X->on_cpu, 0)   -- finish_task()
 *   2) smp_cond_load_acquire(!X->on_cpu) -- try_to_wake_up()
 *
 * Example:
 *
 *   CPU0 (schedule)  CPU1 (try_to_wake_up) CPU2 (schedule)
 *
 *   LOCK rq(0)->lock LOCK X->pi_lock
 *   dequeue X
 *   sched-out X
 *   smp_store_release(X->on_cpu, 0);
 *
 *                    smp_cond_load_acquire(&X->on_cpu, !VAL);
 *                    X->state = WAKING
 *                    set_task_cpu(X,2)
 *
 *                    LOCK rq(2)->lock
 *                    enqueue X
 *                    X->state = RUNNING
 *                    UNLOCK rq(2)->lock
 *
 *                                          LOCK rq(2)->lock // orders against CPU1
 *                                          sched-out Z
 *                                          sched-in X
 *                                          UNLOCK rq(2)->lock
 *
 *                    UNLOCK X->pi_lock
 *   UNLOCK rq(0)->lock
 *
 *
 * However, for wakeups there is a second guarantee we must provide, namely we
 * must ensure that CONDITION=1 done by the caller can not be reordered with
 * accesses to the task state; see try_to_wake_up() and set_current_state().
 */

/**
 * try_to_wake_up - wake up a thread
 * @p: the thread to be awakened
 * @state: the mask of task states that can be woken
 * @wake_flags: wake modifier flags (WF_*)
 *
 * Conceptually does:
 *
 *   If (@state & @p->state) @p->state = TASK_RUNNING.
 *
 * If the task was not queued/runnable, also place it back on a runqueue.
 *
 * This function is atomic against schedule() which would dequeue the task.
 *
 * It issues a full memory barrier before accessing @p->state, see the comment
 * with set_current_state().
 *
 * Uses p->pi_lock to serialize against concurrent wake-ups.
 *
 * Relies on p->pi_lock stabilizing:
 *  - p->sched_class
 *  - p->cpus_ptr
 *  - p->sched_task_group
 * in order to do migration, see its use of select_task_rq()/set_task_cpu().
 *
 * Tries really hard to only take one task_rq(p)->lock for performance.
 * Takes rq->lock in:
 *  - ttwu_runnable()    -- old rq, unavoidable, see comment there;
 *  - ttwu_queue()       -- new rq, for enqueue of the task;
 *  - psi_ttwu_dequeue() -- much sadness :-( accounting will kill us.
 *
 * As a consequence we race really badly with just about everything. See the
 * many memory barriers and their comments for details.





```c
static int
try_to_wake_up(struct task_struct *p, unsigned int state, int wake_flags)
{
       unsigned long flags;
       int cpu, success = 0;

       preempt_disable();
       if (p == current) {
              if (!(p->state & state))
                     goto out;

              success = 1;
              trace_sched_waking(p);
              p->state = TASK_RUNNING;
              trace_sched_wakeup(p);
              goto out;
       }

       raw_spin_lock_irqsave(&p->pi_lock, flags);
       smp_mb__after_spinlock();
       if (!(p->state & state))
              goto unlock;

       trace_sched_waking(p);

       /* We're going to change ->state: */
       success = 1;

       smp_rmb();
       if (READ_ONCE(p->on_rq) && ttwu_runnable(p, wake_flags))
              goto unlock;

#ifdef CONFIG_SMP

       smp_acquire__after_ctrl_dep();

       p->state = TASK_WAKING;

       if (smp_load_acquire(&p->on_cpu) &&
           ttwu_queue_wakelist(p, task_cpu(p), wake_flags | WF_ON_CPU))
              goto unlock;


       smp_cond_load_acquire(&p->on_cpu, !VAL);

       cpu = select_task_rq(p, p->wake_cpu, wake_flags | WF_TTWU);
       if (task_cpu(p) != cpu) {
              if (p->in_iowait) {
                     delayacct_blkio_end(p);
                     atomic_dec(&task_rq(p)->nr_iowait);
              }

              wake_flags |= WF_MIGRATED;
              psi_ttwu_dequeue(p);
              set_task_cpu(p, cpu);
       }
#else
       cpu = task_cpu(p);
#endif /* CONFIG_SMP */

       ttwu_queue(p, cpu, wake_flags);
unlock:
       raw_spin_unlock_irqrestore(&p->pi_lock, flags);
out:
       if (success)
              ttwu_stat(p, task_cpu(p), wake_flags);
       preempt_enable();

       return success;
}
```

这里调用到两个函数
- select_task_rq 选择一个适合的CPU
- set_task_cpu 为进程指定运行队列

##### select_task_rq

select_task_rq 函数中会优先尝试使用 wake_affine机制调度到自己睡眠前的CPU核或者当前核上
但不一定总会成功 有可能调度到其它核上

```c
static inline
int select_task_rq(struct task_struct *p, int cpu, int *wake_flags)
{
	lockdep_assert_held(&p->pi_lock);

	if (p->nr_cpus_allowed > 1 && !is_migration_disabled(p)) {
		cpu = p->sched_class->select_task_rq(p, cpu, *wake_flags);
		*wake_flags |= WF_RQ_SELECTED;
	} else {
		cpu = cpumask_any(p->cpus_ptr);
	}

	/*
	 * In order not to call set_task_cpu() on a blocking task we need
	 * to rely on ttwu() to place the task on a valid ->cpus_ptr
	 * CPU.
	 *
	 * Since this is common to all placement strategies, this lives here.
	 *
	 * [ this allows ->select_task() to simply return task_cpu(p) and
	 *   not worry about this generic constraint ]
	 */
	if (unlikely(!is_cpu_allowed(p, cpu)))
		cpu = select_fallback_rq(task_cpu(p), p);

	return cpu;
}
```

##### ttwu_queue
```c
static void ttwu_queue(struct task_struct *p, int cpu, int wake_flags)
{
	struct rq *rq = cpu_rq(cpu);
	struct rq_flags rf;

	if (ttwu_queue_wakelist(p, cpu, wake_flags))
		return;

	rq_lock(rq, &rf);
	update_rq_clock(rq);
	ttwu_do_activate(rq, p, wake_flags, &rf);
	rq_unlock(rq, &rf);
}
```

```c
static void
ttwu_do_activate(struct rq *rq, struct task_struct *p, int wake_flags,
		 struct rq_flags *rf)
{
	int en_flags = ENQUEUE_WAKEUP | ENQUEUE_NOCLOCK;

	lockdep_assert_rq_held(rq);

	if (p->sched_contributes_to_load)
		rq->nr_uninterruptible--;

#ifdef CONFIG_SMP
	if (wake_flags & WF_RQ_SELECTED)
		en_flags |= ENQUEUE_RQ_SELECTED;
	if (wake_flags & WF_MIGRATED)
		en_flags |= ENQUEUE_MIGRATED;
	else
#endif
	if (p->in_iowait) {
		delayacct_blkio_end(p);
		atomic_dec(&task_rq(p)->nr_iowait);
	}

	activate_task(rq, p, en_flags);
	wakeup_preempt(rq, p, wake_flags);

	ttwu_do_wakeup(p);

#ifdef CONFIG_SMP
	if (p->sched_class->task_woken) {
		/*
		 * Our task @p is fully woken up and running; so it's safe to
		 * drop the rq->lock, hereafter rq is only used for statistics.
		 */
		rq_unpin_lock(rq, rf);
		p->sched_class->task_woken(rq, p);
		rq_repin_lock(rq, rf);
	}

	if (rq->idle_stamp) {
		u64 delta = rq_clock(rq) - rq->idle_stamp;
		u64 max = 2*rq->max_idle_balance_cost;

		update_avg(&rq->avg_idle, delta);

		if (rq->avg_idle > max)
			rq->avg_idle = max;

		rq->idle_stamp = 0;
	}
#endif
}
```
activate_task 将进程添加到自己所属运行队列的红黑树中

```c
void activate_task(struct rq *rq, struct task_struct *p, int flags)
{
	if (task_on_rq_migrating(p))
		flags |= ENQUEUE_MIGRATED;
	if (flags & ENQUEUE_MIGRATED)
		sched_mm_cid_migrate_to(rq, p);

	enqueue_task(rq, p, flags);

	WRITE_ONCE(p->on_rq, TASK_ON_RQ_QUEUED);
	ASSERT_EXCLUSIVE_WRITER(p->on_rq);
}
```


### autoremove_wake_function

```c
// wait.h
#define DEFINE_WAIT_FUNC(name, function)                                   \
       struct wait_queue_entry name = {                                   \
              .private       = current,                                 \
              .func         = function,                                \
              .entry        = LIST_HEAD_INIT((name).entry),                      \
       }

// autoremove_wake_function
#define DEFINE_WAIT(name) DEFINE_WAIT_FUNC(name, autoremove_wake_function)

#define init_wait(wait)								\
	do {									\
		(wait)->private = current;					\
		(wait)->func = autoremove_wake_function;			\
		INIT_LIST_HEAD(&(wait)->entry);					\
		(wait)->flags = 0;						\
	} while (0)
```
autoremove_wake_function
```c
// wait.c
int autoremove_wake_function(struct wait_queue_entry *wq_entry, unsigned mode, int sync, void *key)
{
       int ret = default_wake_function(wq_entry, mode, sync, key);

       if (ret)
              list_del_init_careful(&wq_entry->entry);

       return ret;
}
EXPORT_SYMBOL(autoremove_wake_function);
```

```c
// core.c
int default_wake_function(wait_queue_entry_t *curr, unsigned mode, int wake_flags,
                       void *key)
{
       WARN_ON_ONCE(IS_ENABLED(CONFIG_SCHED_DEBUG) && wake_flags & ~WF_SYNC);
       return try_to_wake_up(curr->private, mode, wake_flags);
}
EXPORT_SYMBOL(default_wake_function);
```

## accept

### wait

#### inet_csk_accept

inet_csk_wait_for_connect

```c
// inet_connection_sock.c
// This will accept the next outstanding connection.
struct sock *inet_csk_accept(struct sock *sk, int flags, int *err, bool kern)
{
       struct inet_connection_sock *icsk = inet_csk(sk);
       struct request_sock_queue *queue = &icsk->icsk_accept_queue;
       struct request_sock *req;
       struct sock *newsk;
       int error;

       lock_sock(sk);

       /* We need to make sure that this socket is listening,
        * and that it has something pending.
        */
       error = -EINVAL;
       if (sk->sk_state != TCP_LISTEN)
              goto out_err;

       /* Find already established connection */
       if (reqsk_queue_empty(queue)) {
              long timeo = sock_rcvtimeo(sk, flags & O_NONBLOCK);

              /* If this is a non blocking socket don't sleep */
              error = -EAGAIN;
              if (!timeo)
                     goto out_err;

              error = inet_csk_wait_for_connect(sk, timeo);
              if (error)
                     goto out_err;
       }
       req = reqsk_queue_remove(queue, sk);
       newsk = req->sk;

       if (sk->sk_protocol == IPPROTO_TCP &&
           tcp_rsk(req)->tfo_listener) {
              spin_lock_bh(&queue->fastopenq.lock);
              if (tcp_rsk(req)->tfo_listener) {
                     /* We are still waiting for the final ACK from 3WHS
                      * so can't free req now. Instead, we set req->sk to
                      * NULL to signify that the child socket is taken
                      * so reqsk_fastopen_remove() will free the req
                      * when 3WHS finishes (or is aborted).
                      */
                     req->sk = NULL;
                     req = NULL;
              }
              spin_unlock_bh(&queue->fastopenq.lock);
       }

out:
       release_sock(sk);
       if (newsk && mem_cgroup_sockets_enabled) {
              int amt;

              /* atomically get the memory usage, set and charge the
               * newsk->sk_memcg.
               */
              lock_sock(newsk);

              /* The socket has not been accepted yet, no need to look at
               * newsk->sk_wmem_queued.
               */
              amt = sk_mem_pages(newsk->sk_forward_alloc +
                               atomic_read(&newsk->sk_rmem_alloc));
              mem_cgroup_sk_alloc(newsk);
              if (newsk->sk_memcg && amt)
                     mem_cgroup_charge_skmem(newsk->sk_memcg, amt);

              release_sock(newsk);
       }
       if (req)
              reqsk_put(req);
       return newsk;
out_err:
       newsk = NULL;
       req = NULL;
       *err = error;
       goto out;
}
EXPORT_SYMBOL(inet_csk_accept);
```

#### inet_csk_wait_for_connect

call prepare_to_wait_exclusive

```c
/*
 * Wait for an incoming connection, avoid race conditions. This must be called
 * with the socket locked.
 */
static int inet_csk_wait_for_connect(struct sock *sk, long timeo)
{
       struct inet_connection_sock *icsk = inet_csk(sk);
       DEFINE_WAIT(wait);
       int err;

       /*
        * True wake-one mechanism for incoming connections: only
        * one process gets woken up, not the 'whole herd'.
        * Since we do not 'race & poll' for established sockets
        * anymore, the common case will execute the loop only once.
        *
        * Subtle issue: "add_wait_queue_exclusive()" will be added
        * after any current non-exclusive waiters, and we know that
        * it will always _stay_ after any new non-exclusive waiters
        * because all non-exclusive waiters are added at the
        * beginning of the wait-queue. As such, it's ok to "drop"
        * our exclusiveness temporarily when we get woken up without
        * having to remove and re-insert us on the wait queue.
        */
       for (;;) {
              prepare_to_wait_exclusive(sk_sleep(sk), &wait,
                                     TASK_INTERRUPTIBLE);
              release_sock(sk);
              if (reqsk_queue_empty(&icsk->icsk_accept_queue))
                     timeo = schedule_timeout(timeo);
              sched_annotate_sleep();
              lock_sock(sk);
              err = 0;
              if (!reqsk_queue_empty(&icsk->icsk_accept_queue))
                     break;
              err = -EINVAL;
              if (sk->sk_state != TCP_LISTEN)
                     break;
              err = sock_intr_errno(timeo);
              if (signal_pending(current))
                     break;
              err = -EAGAIN;
              if (!timeo)
                     break;
       }
       finish_wait(sk_sleep(sk), &wait);
       return err;
}
```

### wake

tcp_v4_rcv->tcp_v4_do_rcv->tcp_child_process->sock_def_readable-> _wake_up_common

```c
//     From tcp_input.c
// tcp_ipv4.c
int tcp_v4_rcv(struct sk_buff *skb)
{
       struct net *net = dev_net(skb->dev);
       struct sk_buff *skb_to_free;
       int sdif = inet_sdif(skb);
       int dif = inet_iif(skb);
       const struct iphdr *iph;
       const struct tcphdr *th;
       bool refcounted;
       struct sock *sk;
       int ret;

       if (skb->pkt_type != PACKET_HOST)
              goto discard_it;

       /* Count it even if it's bad */
       __TCP_INC_STATS(net, TCP_MIB_INSEGS);

       if (!pskb_may_pull(skb, sizeof(struct tcphdr)))
              goto discard_it;

       th = (const struct tcphdr *)skb->data;

       if (unlikely(th->doff < sizeof(struct tcphdr) / 4))
              goto bad_packet;
       if (!pskb_may_pull(skb, th->doff * 4))
              goto discard_it;

       /* An explanation is required here, I think.
        * Packet length and doff are validated by header prediction,
        * provided case of th->doff==0 is eliminated.
        * So, we defer the checks. */

       if (skb_checksum_init(skb, IPPROTO_TCP, inet_compute_pseudo))
              goto csum_error;

       th = (const struct tcphdr *)skb->data;
       iph = ip_hdr(skb);
lookup:
       sk = __inet_lookup_skb(&tcp_hashinfo, skb, __tcp_hdrlen(th), th->source,
                            th->dest, sdif, &refcounted);
       if (!sk)
              goto no_tcp_socket;

process:
       if (sk->sk_state == TCP_TIME_WAIT)
              goto do_time_wait;

       if (sk->sk_state == TCP_NEW_SYN_RECV) {
              struct request_sock *req = inet_reqsk(sk);
              bool req_stolen = false;
              struct sock *nsk;

              sk = req->rsk_listener;
              if (unlikely(tcp_v4_inbound_md5_hash(sk, skb, dif, sdif))) {
                     sk_drops_add(sk, skb);
                     reqsk_put(req);
                     goto discard_it;
              }
              if (tcp_checksum_complete(skb)) {
                     reqsk_put(req);
                     goto csum_error;
              }
              if (unlikely(sk->sk_state != TCP_LISTEN)) {
                     inet_csk_reqsk_queue_drop_and_put(sk, req);
                     goto lookup;
              }
              /* We own a reference on the listener, increase it again
               * as we might lose it too soon.
               */
              sock_hold(sk);
              refcounted = true;
              nsk = NULL;
              if (!tcp_filter(sk, skb)) {
                     th = (const struct tcphdr *)skb->data;
                     iph = ip_hdr(skb);
                     tcp_v4_fill_cb(skb, iph, th);
                     nsk = tcp_check_req(sk, skb, req, false, &req_stolen);
              }
              if (!nsk) {
                     reqsk_put(req);
                     if (req_stolen) {
                            /* Another cpu got exclusive access to req
                             * and created a full blown socket.
                             * Try to feed this packet to this socket
                             * instead of discarding it.
                             */
                            tcp_v4_restore_cb(skb);
                            sock_put(sk);
                            goto lookup;
                     }
                     goto discard_and_relse;
              }
              if (nsk == sk) {
                     reqsk_put(req);
                     tcp_v4_restore_cb(skb);
              } else if (tcp_child_process(sk, nsk, skb)) {
                     tcp_v4_send_reset(nsk, skb);
                     goto discard_and_relse;
              } else {
                     sock_put(sk);
                     return 0;
              }
       }
       if (unlikely(iph->ttl < inet_sk(sk)->min_ttl)) {
              __NET_INC_STATS(net, LINUX_MIB_TCPMINTTLDROP);
              goto discard_and_relse;
       }

       if (!xfrm4_policy_check(sk, XFRM_POLICY_IN, skb))
              goto discard_and_relse;

       if (tcp_v4_inbound_md5_hash(sk, skb, dif, sdif))
              goto discard_and_relse;

       nf_reset_ct(skb);

       if (tcp_filter(sk, skb))
              goto discard_and_relse;
       th = (const struct tcphdr *)skb->data;
       iph = ip_hdr(skb);
       tcp_v4_fill_cb(skb, iph, th);

       skb->dev = NULL;

       if (sk->sk_state == TCP_LISTEN) {
              ret = tcp_v4_do_rcv(sk, skb);
              goto put_and_return;
       }

       sk_incoming_cpu_update(sk);

       bh_lock_sock_nested(sk);
       tcp_segs_in(tcp_sk(sk), skb);
       ret = 0;
       if (!sock_owned_by_user(sk)) {
              skb_to_free = sk->sk_rx_skb_cache;
              sk->sk_rx_skb_cache = NULL;
              ret = tcp_v4_do_rcv(sk, skb);
       } else {
              if (tcp_add_backlog(sk, skb))
                     goto discard_and_relse;
              skb_to_free = NULL;
       }
       bh_unlock_sock(sk);
       if (skb_to_free)
              __kfree_skb(skb_to_free);

put_and_return:
       if (refcounted)
              sock_put(sk);

       return ret;

no_tcp_socket:
       if (!xfrm4_policy_check(NULL, XFRM_POLICY_IN, skb))
              goto discard_it;

       tcp_v4_fill_cb(skb, iph, th);

       if (tcp_checksum_complete(skb)) {
csum_error:
              __TCP_INC_STATS(net, TCP_MIB_CSUMERRORS);
bad_packet:
              __TCP_INC_STATS(net, TCP_MIB_INERRS);
       } else {
              tcp_v4_send_reset(NULL, skb);
       }

discard_it:
       /* Discard frame. */
       kfree_skb(skb);
       return 0;

discard_and_relse:
       sk_drops_add(sk, skb);
       if (refcounted)
              sock_put(sk);
       goto discard_it;

do_time_wait:
       if (!xfrm4_policy_check(NULL, XFRM_POLICY_IN, skb)) {
              inet_twsk_put(inet_twsk(sk));
              goto discard_it;
       }

       tcp_v4_fill_cb(skb, iph, th);

       if (tcp_checksum_complete(skb)) {
              inet_twsk_put(inet_twsk(sk));
              goto csum_error;
       }
       switch (tcp_timewait_state_process(inet_twsk(sk), skb, th)) {
       case TCP_TW_SYN: {
              struct sock *sk2 = inet_lookup_listener(dev_net(skb->dev),
                                                 &tcp_hashinfo, skb,
                                                 __tcp_hdrlen(th),
                                                 iph->saddr, th->source,
                                                 iph->daddr, th->dest,
                                                 inet_iif(skb),
                                                 sdif);
              if (sk2) {
                     inet_twsk_deschedule_put(inet_twsk(sk));
                     sk = sk2;
                     tcp_v4_restore_cb(skb);
                     refcounted = false;
                     goto process;
              }
       }
              /* to ACK */
              fallthrough;
       case TCP_TW_ACK:
              tcp_v4_timewait_ack(sk, skb);
              break;
       case TCP_TW_RST:
              tcp_v4_send_reset(sk, skb);
              inet_twsk_deschedule_put(inet_twsk(sk));
              goto discard_it;
       case TCP_TW_SUCCESS:;
       }
       goto discard_it;
}
```

tcp_v4_do_rcv

```c
// tcp_ipv4.c
/* The socket must have it's spinlock held when we get
 * here, unless it is a TCP_LISTEN socket.
 *
 * We have a potential double-lock case here, so even when
 * doing backlog processing we use the BH locking scheme.
 * This is because we cannot sleep with the original spinlock
 * held.
 */
int tcp_v4_do_rcv(struct sock *sk, struct sk_buff *skb)
{
       struct sock *rsk;

       if (sk->sk_state == TCP_ESTABLISHED) { /* Fast path */
              struct dst_entry *dst = sk->sk_rx_dst;

              sock_rps_save_rxhash(sk, skb);
              sk_mark_napi_id(sk, skb);
              if (dst) {
                     if (inet_sk(sk)->rx_dst_ifindex != skb->skb_iif ||
                         !INDIRECT_CALL_1(dst->ops->check, ipv4_dst_check,
                                        dst, 0)) {
                            dst_release(dst);
                            sk->sk_rx_dst = NULL;
                     }
              }
              tcp_rcv_established(sk, skb);
              return 0;
       }

       if (tcp_checksum_complete(skb))
              goto csum_err;

       if (sk->sk_state == TCP_LISTEN) {
              struct sock *nsk = tcp_v4_cookie_check(sk, skb);

              if (!nsk)
                     goto discard;
              if (nsk != sk) {
                     if (tcp_child_process(sk, nsk, skb)) {
                            rsk = nsk;
                            goto reset;
                     }
                     return 0;
              }
       } else
              sock_rps_save_rxhash(sk, skb);

       if (tcp_rcv_state_process(sk, skb)) {
              rsk = sk;
              goto reset;
       }
       return 0;

reset:
       tcp_v4_send_reset(rsk, skb);
discard:
       kfree_skb(skb);
       /* Be careful here. If this function gets more complicated and
        * gcc suffers from register pressure on the x86, sk (in %ebx)
        * might be destroyed here. This current version compiles correctly,
        * but you have been warned.
        */
       return 0;

csum_err:
       TCP_INC_STATS(sock_net(sk), TCP_MIB_CSUMERRORS);
       TCP_INC_STATS(sock_net(sk), TCP_MIB_INERRS);
       goto discard;
}
EXPORT_SYMBOL(tcp_v4_do_rcv);
```

tcp_child_process

```c
/*
 * Queue segment on the new socket if the new socket is active,
 * otherwise we just shortcircuit this and continue with
 * the new socket.
 *
 * For the vast majority of cases child->sk_state will be TCP_SYN_RECV
 * when entering. But other states are possible due to a race condition
 * where after __inet_lookup_established() fails but before the listener
 * locked is obtained, other packets cause the same connection to
 * be created.
 */
// tcp_minisocks.c
int tcp_child_process(struct sock *parent, struct sock *child,
                    struct sk_buff *skb)
       __releases(&((child)->sk_lock.slock))
{
       int ret = 0;
       int state = child->sk_state;

       /* record NAPI ID of child */
       sk_mark_napi_id(child, skb);

       tcp_segs_in(tcp_sk(child), skb);
       if (!sock_owned_by_user(child)) {
              ret = tcp_rcv_state_process(child, skb);
              /* Wakeup parent, send SIGIO */
              if (state == TCP_SYN_RECV && child->sk_state != state)
                     parent->sk_data_ready(parent);
       } else {
              /* Alas, it is possible again, because we do lookup
               * in main socket hash table and lock on listening
               * socket does not protect us more.
               */
              __sk_add_backlog(child, skb);
       }

       bh_unlock_sock(child);
       sock_put(child);
       return ret;
}
EXPORT_SYMBOL(
```

#### wake up

```c
// wait.h
#define wake_up_interruptible_sync_poll(x, m)                               \
       __wake_up_sync_key((x), TASK_INTERRUPTIBLE, poll_to_key(m))
```

```c
// wait.c
/**
 * __wake_up_sync_key - wake up threads blocked on a waitqueue.
 * @wq_head: the waitqueue
 * @mode: which threads
 * @key: opaque value to be passed to wakeup targets
 *
 * The sync wakeup differs that the waker knows that it will schedule
 * away soon, so while the target thread will be woken up, it will not
 * be migrated to another CPU - ie. the two threads are 'synchronized'
 * with each other. This can prevent needless bouncing between CPUs.
 *
 * On UP it can prevent extra preemption.
 *
 * If this function wakes up a task, it executes a full memory barrier before
 * accessing the task state.
 */
void __wake_up_sync_key(struct wait_queue_head *wq_head, unsigned int mode,
                     void *key)
{
       if (unlikely(!wq_head))
              return;

       __wake_up_common_lock(wq_head, mode, 1, WF_SYNC, key); /* nr_exclusive = 1 */
}
EXPORT_SYMBOL_GPL(__wake_up_sync_key);

static void __wake_up_common_lock(struct wait_queue_head *wq_head, unsigned int mode,
                     int nr_exclusive, int wake_flags, void *key)
{
       do {
              spin_lock_irqsave(&wq_head->lock, flags);
              nr_exclusive = __wake_up_common(wq_head, mode, nr_exclusive,
                                          wake_flags, key, &bookmark);
              spin_unlock_irqrestore(&wq_head->lock, flags);
       } while (bookmark.flags & WQ_FLAG_BOOKMARK);
}
```

## epoll

See [epoll wait](/docs/CS/OS/Linux/epoll.md?id=add_wait_queue) and [wake up](/docs/CS/OS/Linux/epoll.md?id=ep_poll_callback)

#### wake_up_poll

finally call __wake_up_common

```c
// wait.h

#define wake_up_poll(x, m)							\
	__wake_up(x, TASK_NORMAL, 1, poll_to_key(m))

// wait.c
/**
 * __wake_up - wake up threads blocked on a waitqueue.
 * @wq_head: the waitqueue
 * @mode: which threads
 * @nr_exclusive: how many wake-one or wake-many threads to wake up
 * @key: is directly passed to the wakeup function
 *
 * If this function wakes up a task, it executes a full memory barrier before
 * accessing the task state.
 */
void __wake_up(struct wait_queue_head *wq_head, unsigned int mode,
                     int nr_exclusive, void *key)
{
       __wake_up_common_lock(wq_head, mode, nr_exclusive, 0, key);
}
EXPORT_SYMBOL(__wake_up);
```

## Nginx

multiple process

`ngx_event_accept` default disable

## Links

- [processes](/docs/CS/OS/Linux/process.md)
- [network](/docs/CS/OS/Linux/net/network.md)
