## Collection Cycle

### GC Triggering

ZGC 的回收周期触发时机与其他 GC 算法略有不同：VM 内部有一个线程（`ZDirector`）轮询定期检查是否满足开始回收的条件，如果满足则开始回收。ZGC 提供以下触发策略，其中一种满足条件即触发回收：

- **rule_timer**：定时策略，距离上次 GC 时间超过 interval 即触发 GC
- **rule_warmup**：VM 启动后，如果从来没有发生过 GC，则在堆内存使用超过 10%、20%、30% 时分别触发一次 GC，以收集 GC 数据
- **rule_allocation_rate**：根据对象分配速率决定是否 GC
- **rule_proactive**：主动控制策略，根据距离上次 GC 增长的堆空间和距离上次 GC 的时间判断是否触发 GC

如果对象分配过快，以至于以上四种策略均无法及时回收对象，则在到达阈值后，STW 并行回收。

### ZDirector

`ZDirector` 是轮询驱动线程，主循环 `wait_for_tick()` 等待 100 ms，然后抽样计算分配速率（`sample_allocation_rate`），判断是否触发 GC，如是则通过 Driver 执行 collect。

```cpp
void ZDirector::run_thread() {
  // Main loop
  while (wait_for_tick()) {
    ZDirectorStats stats = sample_stats();
    if (!start_gc(stats)) {
      adjust_gc(stats);
    }
  }
}

static bool start_gc(const ZDirectorStats& stats) {
  // Try start major collections first as they include a minor collection
  const GCCause::Cause major_cause = make_major_gc_decision(stats);
  if (major_cause != GCCause::_no_gc) {
    start_major_gc(stats, major_cause);
    return true;
  }

  const GCCause::Cause minor_cause = make_minor_gc_decision(stats);
  if (minor_cause != GCCause::_no_gc) {
    if (!ZDriver::major()->is_busy() && rule_major_allocation_rate(stats)) {
      // Merge minor GC into major GC
      start_major_gc(stats, GCCause::_z_allocation_rate);
    } else {
      start_minor_gc(stats, minor_cause);
    }

    return true;
  }

  return false;
}
```

Minor GC 决策优先级：timer → allocation_rate → high_usage。

```cpp
static GCCause::Cause make_minor_gc_decision(const ZDirectorStats& stats) {
  if (ZDriver::minor()->is_busy()) {
    return GCCause::_no_gc;
  }

  if (ZDriver::major()->is_busy() && !stats._old_stats._resize._is_active) {
    return GCCause::_no_gc;
  }

  if (rule_minor_timer(stats)) {
    return GCCause::_z_timer;
  }

  if (rule_minor_allocation_rate(stats)) {
    return GCCause::_z_allocation_rate;
  }

  if (rule_minor_high_usage(stats)) {
    return GCCause::_z_high_usage;
  }

  return GCCause::_no_gc;
}
```

`rule_minor_timer`：如果没有设置 JVM 参数 `-XX:ZCollectionInterval` 则返回，否则判断当前时间减上次 GC 时间是否大于 `ZCollectionInterval`，如是则触发 GC。

```cpp
static bool rule_minor_timer(const ZDirectorStats& stats) {
  if (ZCollectionIntervalMinor <= 0) {
    // Rule disabled
    return false;
  }

  // Perform GC if timer has expired.
  const double time_since_last_gc = stats._young_stats._cycle._time_since_last;
  const double time_until_gc = ZCollectionIntervalMinor - time_since_last_gc;

  log_debug(gc, director)("Rule Minor: Timer, Interval: %.3fs, TimeUntilGC: %.3fs",
                          ZCollectionIntervalMinor, time_until_gc);

  return time_until_gc <= 0;
}
```

### GC Cause Routing

根据传入的 `GCCause`，判断使用同步消息还是异步消息：ZGC 自身的触发策略都使用异步消息（rule_timer、rule_warmup、rule_allocation_rate、rule_proactive），metaspace GC 使用异步消息，其他情况使用同步消息。

```cpp
void ZCollectedHeap::collect(GCCause::Cause cause) {
  // Handle external collection requests
  switch (cause) {
  case GCCause::_wb_young_gc:
  case GCCause::_scavenge_alot:
    // Start urgent minor GC
    _driver_minor->collect(ZDriverRequest(cause, ZYoungGCThreads, 0));
    break;

  case GCCause::_heap_dump:
  case GCCause::_heap_inspection:
  case GCCause::_wb_full_gc:
  case GCCause::_wb_breakpoint:
  case GCCause::_dcmd_gc_run:
  case GCCause::_java_lang_system_gc:
  case GCCause::_full_gc_alot:
  case GCCause::_jvmti_force_gc:
  case GCCause::_metadata_GC_clear_soft_refs:
  case GCCause::_codecache_GC_aggressive:
    // Start urgent major GC
    _driver_major->collect(ZDriverRequest(cause, ZYoungGCThreads, ZOldGCThreads));
    break;

  case GCCause::_metadata_GC_threshold:
  case GCCause::_codecache_GC_threshold:
    // Start not urgent major GC
    _driver_major->collect(ZDriverRequest(cause, 1, 1));
    break;

  default:
    fatal("Unsupported GC cause (%s)", GCCause::to_string(cause));
    break;
  }
}
```

### ZDriver Threads

分代 ZGC 有两个 Driver：`ZDriverMinor` 负责回收 young generation，`ZDriverMajor` 先回收 young generation 再回收 old generation。

```cpp
void ZDriverMinor::run_thread() {
  // Main loop
  for (;;) {
    // Wait for GC request
    const ZDriverRequest request = _port.receive();

    ZDriverLocker locker;

    abortpoint();

    // Run GC
    gc(request);

    abortpoint();

    // Notify GC completed
    _port.ack();

    // Handle allocation stalls
    handle_alloc_stalls();

    // Good point to consider back-to-back GC
    ZDirector::evaluate_rules();
  }
}
```

```cpp
void ZDriverMajor::run_thread() {
  // Main loop
  for (;;) {
    // Wait for GC request
    const ZDriverRequest request = _port.receive();

    ZDriverLocker locker;

    ZBreakpoint::at_before_gc();

    abortpoint();

    // Set up soft reference policy
    const bool clear_soft_refs = should_clear_soft_references(request.cause());
    ZGeneration::old()->set_soft_reference_policy(clear_soft_refs);

    // Run GC
    gc(request);

    abortpoint();

    // Notify GC completed
    _port.ack();

    // Handle allocation stalls
    handle_alloc_stalls(clear_soft_refs);

    ZBreakpoint::at_after_gc();
  }
}

void ZDriverMajor::gc(const ZDriverRequest& request) {
  ZDriverScopeMajor scope(request, &_gc_timer);

  // Collect the young generation
  collect_young(request);

  abortpoint();

  // Collect the old generation
  collect_old();
}

void ZDriverMajor::collect_young(const ZDriverRequest& request) {
  ZGCIdMajor major_id(gc_id(), 'Y');
  if (should_preclean_young(request.cause())) {
    // Collect young generation and promote everything to old generation
    ZGeneration::young()->collect(ZYoungType::major_full_preclean, &_gc_timer);

    abortpoint();

    // Collect young generation and gather roots pointing into old generation
    ZGeneration::young()->collect(ZYoungType::major_full_roots, &_gc_timer);
  } else {
    // Collect young generation and gather roots pointing into old generation
    ZGeneration::young()->collect(ZYoungType::major_partial_roots, &_gc_timer);
  }

  abortpoint();

  // Handle allocations waiting for a young collection
  handle_alloc_stalling_for_young();
}

void ZDriverMajor::collect_old() {
  ZGCIdMajor major_id(gc_id(), 'O');
  ZGeneration::old()->collect(&_gc_timer);
}
```

## Links

- [ZGC Hub](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [Object Allocation](/docs/CS/Java/JDK/JVM/GC/ZGC/ObjectAllocation.md)
- [Generational ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC/Generational.md)

## References

1. [ZGC source: zDirector.cpp](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/z/zDirector.cpp)
2. [ZGC source: zDriver.cpp](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/z/zDriver.cpp)
3. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532)
