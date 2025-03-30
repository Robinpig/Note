## Introduction



InnoDB 事务执行过程中，加表锁或者行锁之后，释放锁最常见的时机是事务提交或者回滚即将完成时。

因为事务的生命周期结束，它加的锁的生命周期也随之结束。

有一种情况，加锁只是权宜之计，临时为之。如果这种锁也要等到事务提交或者回滚即将完成时才释放，阻塞其它事务的时间也可能更长，这就有点不合理了。所以，这种锁会在事务运行过程中及时释放。

还有一种情况，虽然是在事务提交过程中释放锁，但是并不会等到提交即将完成时才释放，而是在二阶段提交的 prepare 阶段就提前释放。

最后，有点特殊的就是 AUTO-INC 锁了




我们先来看看只是权宜之计的加锁场景。

select、update、delete 语句执行过程中，不管 where 条件是否命中索引，也不管是等值查询还是范围查询，只要扫描过的记录，都会加行锁。

> 和 update、delete 不一样，select 只在需要加锁时，才会按照上面的逻辑加锁。




## Deadlock

两个事务分别持有对方需要的锁，并等待对方释放锁（事务1持有a锁、请求b锁，事务2持有b锁、请求a锁），导致程序无法继续进行

MySQL自动监测死锁并回滚其中一个事务：

- MySQL默认开启死锁检测（innodb_deadlock_detect默认为on），发现死锁后主动回滚死锁链条中的某一个事务，让其他事务得以继续执行
- 如果死锁监测被关闭，InnoDB依赖innodb_lock_wait_timeout 进行事务回滚以避免死锁，请求锁的默认最长等待时间是50s
- 如果要查看InnoDB用户事务中的最后一个死锁，可以使用 SHOW ENGINE INNODB STATUS
- 如果频繁的出现死锁，可以启用innodb_print_all_deadlocks将所有死锁的有关信息打印到mysqld错误日志中

数据库死锁常见原因：
多个事务通过uptade或者select..for share / update锁定了多个表中的行记录，但锁定的顺序相反



ERROR 40001: Deadlock found when trying to get lock; try restarting transaction

show engine innodb status查看到最近的一次死锁日志



MySQL官方提供了InnoDB引擎下，事务死锁的主动检测与丢弃机制，官方允许通过innodb_deadlock_detect这个参数进行控制，默认开启。
同时如果禁用此选项，依旧可以通过锁超时参数innodb_lock_wait_timeout来进行控制
innodb死锁检测只能针对innodb引擎级别死锁，innodb死锁检测不能检测到应用层级别死锁


在8.0.18以前，InnoDB的死锁检测机制是最常见的深度优先搜索（DFS）算法来搜索等待关系图
如果开启了死锁检测，那么在每次上锁之前，都会进行一次死锁检测，我们会持有lock_sys->mutex，然后对整个等待关系图进行DFS遍历，当发现等待关系图成环的时候，
说明有死锁存在，我们根据事务优先级/undo大小/锁数量等因素选择一个事务进行回滚。 详细代码可参考 MySQL 8.0 DeadlockChecker类中相关实现

```c++
static MYSQL_SYSVAR_BOOL(
    deadlock_detect, innobase_deadlock_detect, PLUGIN_VAR_NOCMDARG,
    "Enable/disable InnoDB deadlock detector (default ON)."
    " if set to OFF, deadlock detection is skipped,"
    " and we rely on innodb_lock_wait_timeout in case of deadlock.",
    nullptr, innobase_deadlock_detect_update, true);
```


```c++
static void innobase_deadlock_detect_update(THD *, SYS_VAR *, void *,
                                            const void *save) {
  innobase_deadlock_detect = *(bool *)save;
  /* In case deadlock detection was disabled for a long time it could happen
  that all clients have deadlocked with each other and thus they stopped
  changing the wait-for graph, which in turn causes deadlock detection to not
  observe any action and thus it will not search for deadlocks. So if we now
  change from OFF to ON we need to "kick-start" the process. It never hurts to
  do so, so we do it even if we check from ON to OFF */
  lock_wait_request_check_for_cycles();
}
```


```c++
// lock0wait.cc
void lock_wait_request_check_for_cycles() { lock_set_timeout_event(); }

// lock0lock.c
void lock_set_timeout_event() { os_event_set(lock_sys->timeout_event); }
```
老的死锁检测机制主要存在的问题是性能问题。 在DFS搜索等待关系图的时候，是会持有lock_sys->mutex这把大锁的，在lock_sys->mutex持有期间所有的新加行锁和释放全部会被阻塞。
当出现大量锁等待的时候（例如电商热点行场景等），等待关系图会变的特别的大，导致每一次加锁DFS遍历整个等待关系图的时间变得非常的长，从而导致lock_sys->mutex竞争过于剧烈，
引发大量线程等待lock_sys->mutex，从而导致数据库在此场景下雪崩



RecLock::add_to_waitq -> RecLock::create ->  RecLock::lock_alloc ->  RecLock::lock_add

新的死锁检测机制变的比较轻量：
1. 在持有lock_sys->wait_mutex的情况下，构造稀疏等待关系图，lock_wait_snapshot_waiting_threads
   a. 其实 lock_sys->wait_mutex 也不需要全程持有，只需要分段持有即可，其正确性我们在下一章讨论
2. 对稀疏等待关系图进行DFS扫描，得到成环的子图，lock_wait_find_and_handle_deadlocks
3. 对成环的子图进行有效性检测，lock_wait_check_candidate_cycle
   a. 确保其版本号是一致的
   b. 确保其还在继续等待
4. 选择牺牲事务，并进行死锁处理（回滚）
   a. lock_wait_choose_victim / lock_wait_handle_deadlock

```c++
static uint64_t lock_wait_snapshot_waiting_threads(
    ut::vector<waiting_trx_info_t> &infos) {
  ut_ad(!lock_wait_mutex_own());
  infos.clear();
  lock_wait_mutex_enter();
  /*
  We own lock_wait_mutex, which protects lock_wait_table_reservations and
  reservation_no.
  We want to make a snapshot of the wait-for graph as quick as possible to not
  keep the lock_wait_mutex too long.
  Anything more fancy than push_back seems to impact performance.

  Note: one should be able to prove that we don't really need a "consistent"
  snapshot - the algorithm should still work if we split the loop into several
  smaller "chunks" snapshotted independently and stitch them together. Care must
  be taken to "merge" duplicates keeping the freshest version (reservation_no)
  of slot for each trx.
  So, if (in future) this loop turns out to be a bottleneck (say, by increasing
  congestion on lock_wait_mutex), one can try to release and require the lock
  every X iterations and modify the lock_wait_build_wait_for_graph() to handle
  duplicates in a smart way.
  */
  const auto table_reservations = lock_wait_table_reservations;
  for (auto slot = lock_sys->waiting_threads; slot < lock_sys->last_slot;
       ++slot) {
    if (slot->in_use) {
      auto from = thr_get_trx(slot->thr);
      auto to = from->lock.blocking_trx.load();
      if (to != nullptr) {
        infos.push_back({from, to, slot, slot->reservation_no});
      }
    }
  }
  lock_wait_mutex_exit();
  return table_reservations;
}
```

Assuming that `infos` contains information about all waiting transactions, and `outgoing[i]` is the endpoint of wait-for edge going out of infos[i].trx,
or -1 if the transaction is not waiting, it identifies and handles all cycles in the wait-for graph

```c++
static void lock_wait_find_and_handle_deadlocks(
    const ut::vector<waiting_trx_info_t> &infos,
    const ut::vector<int> &outgoing,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  ut_ad(infos.size() == new_weights.size());
  ut_ad(infos.size() == outgoing.size());
  /** We are going to use int and uint to store positions within infos */
  ut_ad(infos.size() < std::numeric_limits<uint>::max());
  const auto n = static_cast<uint>(infos.size());
  ut_ad(n < static_cast<uint>(std::numeric_limits<int>::max()));
  ut::vector<uint> cycle_ids;
  cycle_ids.clear();
  ut::vector<uint> colors;
  colors.clear();
  colors.resize(n, 0);
  uint current_color = 0;
  for (uint start = 0; start < n; ++start) {
    if (colors[start] != 0) {
      /* This node was already fully processed*/
      continue;
    }
    ++current_color;
    for (int id = start; 0 <= id; id = outgoing[id]) {
      /* We don't expect transaction to deadlock with itself only
      and we do not handle cycles of length=1 correctly */
      ut_ad(id != outgoing[id]);
      if (colors[id] == 0) {
        /* This node was never visited yet */
        colors[id] = current_color;
        continue;
      }
      /* This node was already visited:
      - either it has current_color which means we've visited it during current
        DFS descend, which means we have found a cycle, which we need to verify,
      - or, it has a color used in a previous DFS which means that current DFS
        path merges into an already processed portion of wait-for graph, so we
        can stop now */
      if (colors[id] == current_color) {
        /* found a candidate cycle! */
        lock_wait_extract_cycle_ids(cycle_ids, id, outgoing);
        if (lock_wait_check_candidate_cycle(cycle_ids, infos, new_weights)) {
          MONITOR_INC(MONITOR_DEADLOCK);
        } else {
          MONITOR_INC(MONITOR_DEADLOCK_FALSE_POSITIVES);
        }
      }
      break;
    }
  }
  MONITOR_INC(MONITOR_DEADLOCK_ROUNDS);
  MONITOR_SET(MONITOR_LOCK_THREADS_WAITING, n);
}
```

Given an array with information about all waiting transactions and indexes in it which form a deadlock cycle,
checks if the transactions allegedly forming the deadlock cycle, indeed are still waiting, and if so, chooses a victim and handles the deadlock.


```c++
static bool lock_wait_check_candidate_cycle(
    ut::vector<uint> &cycle_ids, const ut::vector<waiting_trx_info_t> &infos,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  ut_ad(!lock_wait_mutex_own());
  ut_ad(!locksys::owns_exclusive_global_latch());
  lock_wait_mutex_enter();
  /*
  We have released all mutexes after we have built the `infos` snapshot and
  before we've got here. So, while it is true that the edges form a cycle, it
  may also be true that some of these transactions were already rolled back, and
  memory pointed by infos[i].trx or infos[i].waits_for is no longer the trx it
  used to be (as we reuse trx_t objects). It may even segfault if we try to
  access it (because trx_t object could be freed). So we need to somehow verify
  that the pointer is still valid without accessing it. We do that by checking
  if slot->reservation_no has changed since taking a snapshot.
  If it has not changed, then we know that the trx's pointer still points to the
  same trx as the trx is sleeping, and thus has not finished and wasn't freed.
  So, we start by first checking that the slots still contain the trxs we are
  interested in. This requires lock_wait_mutex, but does not require the
  exclusive global latch. */
  if (!lock_wait_trxs_are_still_in_slots(cycle_ids, infos)) {
    lock_wait_mutex_exit();
    return false;
  }
  /*
  At this point we are sure that we can access memory pointed by infos[i].trx
  and that transactions are still in their slots. (And, as `cycle_ids` is a
  cycle, we also know that infos[cycle_ids[i]].wait_for is equal to
  infos[cycle_ids[i+1]].trx, so infos[cycle_ids[i]].wait_for can also be safely
  accessed).
  This however does not mean necessarily that they are still waiting.
  They might have been already notified that they should wake up (by calling
  lock_wait_release_thread_if_suspended()), but they had not yet chance to act
  upon it (it is the trx being woken up who is responsible for cleaning up the
  `slot` it used).
  So, the slot can be still in use and contain a transaction, which was already
  decided to be rolled back for example. However, we can recognize this
  situation by looking at trx->lock.wait_lock, as each call to
  lock_wait_release_thread_if_suspended() is performed only after
  lock_reset_lock_and_trx_wait() resets trx->lock.wait_lock to NULL.
  Checking trx->lock.wait_lock in reliable way requires global exclusive latch.
  */
  locksys::Global_exclusive_latch_guard gurad{UT_LOCATION_HERE};
  if (!lock_wait_trxs_are_still_waiting(cycle_ids, infos)) {
    lock_wait_mutex_exit();
    return false;
  }

  /*
  We can now release lock_wait_mutex, because:

  1. we have verified that trx->lock.wait_lock is not NULL for cycle_ids
  2. we hold exclusive global lock_sys latch
  3. lock_sys latch is required to change trx->lock.wait_lock to NULL
  4. only after changing trx->lock.wait_lock to NULL a trx can finish

  So as long as we hold exclusive global lock_sys latch we can access trxs.
  */

  lock_wait_mutex_exit();

  trx_t *const chosen_victim = lock_wait_choose_victim(cycle_ids, infos);
  ut_a(chosen_victim);

  lock_wait_handle_deadlock(chosen_victim, cycle_ids, infos, new_weights);

  return true;
}
```



```c++
static trx_t *lock_wait_choose_victim(
    const ut::vector<uint> &cycle_ids,
    const ut::vector<waiting_trx_info_t> &infos) {
  /* We are iterating over various transactions comparing their trx_weight_ge,
  which is computed based on number of locks held thus we need exclusive latch
  on the whole lock_sys. In theory number of locks should not change while the
  transaction is waiting, but instead of proving that they can not wake up, it
  is easier to assert that we hold the mutex */
  ut_ad(locksys::owns_exclusive_global_latch());
  ut_ad(!cycle_ids.empty());
  trx_t *chosen_victim = nullptr;
  auto sorted_trxs = lock_wait_order_for_choosing_victim(cycle_ids, infos);

  for (auto *trx : sorted_trxs) {
    if (chosen_victim == nullptr) {
      chosen_victim = trx;
      continue;
    }

    if (trx_is_high_priority(chosen_victim) || trx_is_high_priority(trx)) {
      auto victim = trx_arbitrate(trx, chosen_victim);

      if (victim != nullptr) {
        if (victim == trx) {
          chosen_victim = trx;
        } else {
          ut_a(victim == chosen_victim);
        }
        continue;
      }
    }

    if (trx_weight_ge(chosen_victim, trx)) {
      /* The joining transaction is 'smaller',
      choose it as the victim and roll it back. */
      chosen_victim = trx;
    }
  }

  ut_a(chosen_victim);
  return chosen_victim;
}
```
Handles a deadlock found, by notifying about it, rolling back the chosen victim and updating schedule weights of transactions on the deadlock cycle.


```c++
static void lock_wait_handle_deadlock(
    trx_t *chosen_victim, const ut::vector<uint> &cycle_ids,
    const ut::vector<waiting_trx_info_t> &infos,
    ut::vector<trx_schedule_weight_t> &new_weights) {
  /*  We now update the `schedule_weight`s on the cycle taking into account that
  chosen_victim will be rolled back.
  This is mostly for "correctness" as the impact on performance is negligible
  (actually it looks like it is slowing us down). */
  lock_wait_update_weights_on_cycle(chosen_victim, cycle_ids, infos,
                                    new_weights);

  lock_notify_about_deadlock(
      lock_wait_trxs_rotated_for_notification(cycle_ids, infos), chosen_victim);

  lock_wait_rollback_deadlock_victim(chosen_victim);
}
```


```c++
void lock_wait_timeout_thread() {
  int64_t sig_count = 0;
  os_event_t event = lock_sys->timeout_event;

  ut_ad(!srv_read_only_mode);

  /** The last time we've checked for timeouts. */
  auto last_checked_for_timeouts_at = std::chrono::steady_clock::now();
  do {
    auto current_time = std::chrono::steady_clock::now(); /* Calling this more
    often than once a second isn't needed, as lock timeouts are specified with
    one second resolution, so probably nobody cares if we wake up after T or
    T+0.99, when T itself can't be precise. */
    if (std::chrono::seconds(1) <=
        current_time - last_checked_for_timeouts_at) {
      last_checked_for_timeouts_at = current_time;
      lock_wait_check_slots_for_timeouts();
    }

    lock_wait_update_schedule_and_check_for_deadlocks();

    /* When someone is waiting for a lock, we wake up every second (at worst)
    and check if a timeout has passed for a lock wait */
    os_event_wait_time_low(event, std::chrono::seconds{1}, sig_count);
    sig_count = os_event_reset(event);

  } while (srv_shutdown_state.load() < SRV_SHUTDOWN_CLEANUP);
}
```
Note: I was tempted to declare `infos` as `static`, or at least declare it in lock_wait_timeout_thread() 
and reuse the same instance over and over again to avoid allocator calls caused by push_back() calls inside lock_wait_snapshot_waiting_threads() while we hold lock_sys->lock_wait_mutex.
I was afraid, that allocator might need to block on some internal mutex in order to synchronize with other threads using allocator, and this could in turn cause contention on lock_wait_mutex. 
I hoped, that since vectors never shrink, and only grow, then keeping a single instance of `infos` alive for the whole lifetime of the thread should increase performance,
because after some initial period of growing, the allocations will never have to occur again.
But, I've run many many various experiments, with/without static, with infos declared outside, with reserve(n) using various values of n (128, srv_max_n_threads, even a simple ML predictor), and nothing, 
NOTHING was faster than just using local vector as we do here (at least on tetra01, tetra02, when comparing ~70 runs of each algorithm on uniform, pareto, 128 and 1024 usrs).



```c++
static void lock_wait_update_schedule_and_check_for_deadlocks() {
  ut::vector<waiting_trx_info_t> infos;
  ut::vector<int> outgoing;
  ut::vector<trx_schedule_weight_t> new_weights;

  auto table_reservations = lock_wait_snapshot_waiting_threads(infos);
  lock_wait_build_wait_for_graph(infos, outgoing);

  /* We don't update trx->lock.schedule_weight for trxs on cycles. */
  lock_wait_compute_and_publish_weights_except_cycles(infos, table_reservations,
                                                      outgoing, new_weights);

  if (innobase_deadlock_detect) {
    /* This will also update trx->lock.schedule_weight for trxs on cycles. */
    lock_wait_find_and_handle_deadlocks(infos, outgoing, new_weights);
  }
}
```


如何减少死锁：
- 当不同的事务同时访问数据资源时，尽量采用相同的操作顺序
- 如果能确定幻读和不可重复读对应用的影响不大，可以考虑将隔离级别从默认的RR改成 RC，可以避免 Gap 锁导致的死锁；
  - 为表添加合理的索引，如果不走索引，将会为表的每一行记录加锁，死锁的概率就会大大增大；
  - 避免大事务，尽量将大事务拆成多个小事务来处理；因为大事务占用资源多，耗时长，与其他事务冲突的概率也会变高；




## Links




## References

1. [MySQL 死锁检测源码分析](https://leviathan.vip/2020/02/02/mysql-deadlock-check/)




