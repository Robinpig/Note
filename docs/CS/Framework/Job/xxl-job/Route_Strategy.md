## Introduction

路由策略决定"这一次触发发给哪台执行器"。它是一个标准策略模式：`ExecutorRouteStrategyEnum` 每个枚举常量持有一个 `ExecutorRouter` 实现实例，`JobTrigger.processTrigger` 只调 `getRouter().route(triggerParam, group)`。

源码基线 tag `3.5.0`，包路径 `com.xxl.job.admin.business.scheduler.route`。策略在触发链路中的位置见 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)，地址列表从哪来见 [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)。

```java
public enum ExecutorRouteStrategyEnum {
    FIRST(I18nUtil.getString("jobconf_route_first"), new ExecutorRouteFirst()),
    LAST(I18nUtil.getString("jobconf_route_last"), new ExecutorRouteLast()),
    ROUND(I18nUtil.getString("jobconf_route_round"), new ExecutorRouteRound()),
    RANDOM(I18nUtil.getString("jobconf_route_random"), new ExecutorRouteRandom()),
    CONSISTENT_HASH(I18nUtil.getString("jobconf_route_consistenthash"), new ExecutorRouteConsistentHash()),
    LEAST_FREQUENTLY_USED(I18nUtil.getString("jobconf_route_lfu"), new ExecutorRouteLFU()),
    LEAST_RECENTLY_USED(I18nUtil.getString("jobconf_route_lru"), new ExecutorRouteLRU()),
    FAILOVER(I18nUtil.getString("jobconf_route_failover"), new ExecutorRouteFailover()),
    BUSYOVER(I18nUtil.getString("jobconf_route_busyover"), new ExecutorRouteBusyover()),
    SHARDING_BROADCAST(I18nUtil.getString("jobconf_route_shard"), null);
    ...
}
```

注意最后一行的 `null`：**分片广播没有 router 实现**，它由 `JobTrigger` 在展开阶段直接按下标取地址（见 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)），根本不走 `route()`。

按是否需要网络探测，十种策略分成两类：

| 类别 | 策略 | 单次触发的额外 HTTP 往返 |
| :--- | :--- | :--- |
| 纯计算型 | FIRST / LAST / ROUND / RANDOM / CONSISTENT_HASH / LFU / LRU | 0 |
| 探测型 | FAILOVER / BUSYOVER | 最坏 N 次（N = 在线机器数） |
| 特殊 | SHARDING_BROADCAST | N 次触发（每台一次） |

## Stateless Compute Strategies

### FIRST / LAST

```java
public Response<String> route(TriggerRequest triggerParam, XxlJobGroup jobGroup){
    return Response.ofSuccess(jobGroup.getRegistryList().get(0));
}
```

一行实现。因为地址列表在回写时已 `Collections.sort()` 过（见 [Registry](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)），"第一个"在集群各节点间是**稳定一致**的——这是"固定选第一台"能成立的前提。

适用场景：任务必须在固定机器跑（依赖本地文件、本地缓存）。风险是该机器下线后任务整体失败，需配 `FAILOVER` 或告警。

### ROUND

```java
private static ConcurrentMap<Integer, AtomicInteger> routeCountEachJob = new ConcurrentHashMap<>();
private static long CACHE_VALID_TIME = 0;

private static int count(int jobId) {
    // cache clear
    if (System.currentTimeMillis() > CACHE_VALID_TIME) {
        routeCountEachJob.clear();
        CACHE_VALID_TIME = System.currentTimeMillis() + 1000*60*60*24;
    }

    AtomicInteger count = routeCountEachJob.get(jobId);
    if (count == null || count.get() > 1000000) {
        count = new AtomicInteger(new Random().nextInt(100));   // 初始化时主动Random一次，缓解首次压力
    } else {
        count.addAndGet(1);
    }
    routeCountEachJob.put(jobId, count);
    return count.get();
}
```

三个细节：

- **计数按 jobId 独立**（`routeCountEachJob` 是 `Map<jobId, AtomicInteger>`），不同任务各自轮转；
- **初值是随机**（`Random().nextInt(100)`），避免大量任务同时启动时全部打到第 0 台；
- **整张 map 每 24 小时清空一次**，且计数超 100 万重置。

`routeCountEachJob` 是 `static` 的，即**同一 JVM 内所有 job 共享一张表、调度中心集群各节点各自计数**。这意味着严格来说集群下并不是全局轮询，而是"每个调度节点各自轮询"——多节点同时扫库时会重复选到同一台。实际影响有限（同一时刻只有一个节点抢到锁在扫），但值得知道。

### RANDOM

```java
private static Random localRandom = new Random();

public Response<String> route(TriggerRequest triggerParam, XxlJobGroup jobGroup) {
    List<String> addressList = jobGroup.getRegistryList();
    String address = addressList.get(localRandom.nextInt(addressList.size()));
    return Response.ofSuccess(address);
}
```

`java.util.Random` 而非 `ThreadLocalRandom`，多线程下靠 `Random` 内部的 CAS 保证。够用，不是瓶颈。

### CONSISTENT_HASH

```java
private static final int VIRTUAL_NODE_NUM = 100;

private static long hash(String key) {
    // md5 byte
    MessageDigest md5 = MessageDigest.getInstance("MD5");
    md5.reset();
    byte[] keyBytes = key.getBytes(StandardCharsets.UTF_8);
    md5.update(keyBytes);
    byte[] digest = md5.digest();

    // hash code, Truncate to 32-bits
    long hashCode = ((long) (digest[3] & 0xFF) << 24)
            | ((long) (digest[2] & 0xFF) << 16)
            | ((long) (digest[1] & 0xFF) << 8)
            | (digest[0] & 0xFF);
    return hashCode & 0xffffffffL;
}

public String hashJob(int jobId, List<String> addressList) {
    TreeMap<Long, String> addressRing = new TreeMap<>();
    for (String address: addressList) {
        for (int i = 0; i < VIRTUAL_NODE_NUM; i++) {
            long addressHash = hash("SHARD-" + address + "-NODE-" + i);
            addressRing.put(addressHash, address);
        }
    }

    long jobHash = hash(String.valueOf(jobId));

    Map.Entry<Long, String> ceilingEntry = addressRing.ceilingEntry(jobHash);
    if (ceilingEntry != null) { return ceilingEntry.getValue(); }

    // default first node
    return addressRing.firstEntry().getValue();
}
```

每地址 100 个虚拟节点，哈希函数用 **MD5 前 4 字节截断成 32 位**（注释解释：不用 `String.hashCode()` 是因为取值域太小、易碰撞），`TreeMap.ceilingEntry` 找第一个 ≥ jobHash 的槽，没找到就绕回第一个。

> [!WARNING]
>
> 传入的键是 **`jobId` 而不是任务参数**（`route()` 里 `hashJob(triggerParam.getJobId(), addressList)`）。语义是"同一任务固定落到同一台机器"，不是流传甚广的"同参数落到同机"。改机器列表时，受影响的是 jobId 落点变化的那些任务，与任务参数无关。

### LFU

```java
private static ConcurrentMap<Integer, HashMap<String, Integer>> jobLfuMap = new ConcurrentHashMap<>();
private static long CACHE_VALID_TIME = 0;

public String route(int jobId, List<String> addressList) {
    // cache clear（24h）
    ...
    // lfu item init
    HashMap<String, Integer> lfuItemMap = jobLfuMap.get(jobId);
    if (lfuItemMap == null) {
        lfuItemMap = new HashMap<>();
        jobLfuMap.putIfAbsent(jobId, lfuItemMap);
    }

    // put new
    for (String address: addressList) {
        if (!lfuItemMap.containsKey(address) || lfuItemMap.get(address) > 1000000 ) {
            lfuItemMap.put(address, new Random().nextInt(addressList.size()));  // 初始化时主动Random一次
        }
    }
    // remove old（机器下线）
    ...

    List<Map.Entry<String, Integer>> lfuItemList = new ArrayList<>(lfuItemMap.entrySet());
    lfuItemList.sort(Map.Entry.comparingByValue());     // 升序取最小
    Map.Entry<String, Integer> addressItem = lfuItemList.get(0);
    addressItem.setValue(addressItem.getValue() + 1);
    return addressItem.getKey();
}
```

按 jobId 维护 `<address, count>`，选计数最小者并 +1。新机器入列时初值 `Random().nextInt(addressList.size())`——**故意给个随机初值**，避免新机器计数为 0 时被所有任务一拥而上。计数超 100 万会重置，防止长期运行溢出。

### LRU

```java
private static ConcurrentMap<Integer, LinkedHashMap<String, String>> jobLRUMap = new ConcurrentHashMap<>();

// LinkedHashMap: accessOrder=true（get/put 时重排序）
lruItem = new LinkedHashMap<>(16, 0.75f, true);
...
// load first elment, eldest entry
String eldestKey = lruItem.entrySet().iterator().next().getKey();
return lruItem.get(eldestKey);
```

用 `LinkedHashMap(16, 0.75f, true)` 的访问顺序模式：迭代器的第一个元素就是最久未用的。注意 `route()` 里只读不写（`lruItem.get(eldestKey)` 会触发访问序重排，把它挪到末尾），所以"选中即刷新"。

> [!NOTE]
>
> LFU / LRU 的计数表都是 `static` 字段，存在于**单个调度中心 JVM 内**，不跨节点共享、也不持久化。调度中心集群多活时，两台节点各自维护各自的计数，严格语义上的"最不经常使用"只在单节点内成立。调度中心重启后计数清零。

## Probing Strategies

### FAILOVER

```java
for (String address : addressList) {
    Response<String> beatResult = null;
    try {
        ExecutorBiz executorBiz = XxlJobAdminBootstrap.getExecutorBiz(address, jobGroup);
        beatResult = executorBiz.beat();
    } catch (Exception e) {
        beatResult = Response.ofFail(e.getMessage());
    }
    beatResultSB.append(...).append("<br>address：").append(address)...;

    if (beatResult.isSuccess()) {
        beatResult.setData(address);
        return beatResult;
    }
}
return Response.ofFail(beatResultSB.toString());
```

顺序遍历，对每台发 `/beat`，第一个返回成功的当选。失败时把**逐台探测的完整过程**拼进失败原因（地址、code、msg），方便在调度日志里直接看到"这几台都不通"。

### BUSYOVER

```java
for (String address : addressList) {
    ExecutorBiz executorBiz = XxlJobAdminBootstrap.getExecutorBiz(address, jobGroup);
    idleBeatResult = executorBiz.idleBeat(new IdleBeatRequest(triggerParam.getJobId()));
    ...
    if (idleBeatResult.isSuccess()) {
        idleBeatResult.setData(address);
        return idleBeatResult;
    }
}
```

结构与 FAILOVER 完全同构，差别只在调 `/idleBeat` 且带 `jobId`——问的是"这台机器上这个 job 现在忙不忙"。执行器侧判定见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md) 的 `isRunningOrHasQueue()`。

两者合起来覆盖执行端不稳定的两类场景：**FAILOVER 探死活、BUSYOVER 探空闲**。

> [!WARNING]
>
> 探测型路由每次触发最多要发 N 次 HTTP（N = 在线机器数），且这 N 次是**串行**的。执行器规模上百台时，单次触发可能耗掉几百毫秒，这会直接触发 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md) 里 500ms 的慢任务判定、把任务降级进 slow 池。大规模执行器集群下慎用这两种策略。

## Sharding Broadcast

分片广播没有 `ExecutorRouter`，由 `JobTrigger` 展开：

```java
if (SHARDING_BROADCAST == ... && registryList 非空 && shardingParam == null) {
    for (int i = 0; i < registryList.size(); i++) {
        processTrigger(group, jobInfo, finalFailRetryCount, triggerType, triggerTime, i, registryList.size());
    }
}
```

每台机器收到自己的 `broadcastIndex / broadcastTotal`，业务代码用这两个值切分数据：

```java
@XxlJob("shardingJobHandler")
public void shardingJobHandler() throws Exception {
    int shardIndex = XxlJobHelper.getShardIndex();
    int shardTotal = XxlJobHelper.getShardTotal();
    // 按 shardIndex 取自己那份数据
}
```

分片参数现在统一从 `XxlJobHelper` 读；旧的 `ShardingUtil` 已移到 `com.xxl.job.core.util.deprecated` 包，不再推荐使用。

两个使用要点：

- **分片总数 = 触发时刻的在线机器数**，不是配置值。机器上下线会改变总数，业务逻辑必须能容忍总数变化（用取模而不是固定映射）。
- **失败重试只补失败的那一片**：重试时 `executorShardingParam` 传的是原分片下标，不会重新广播全部。

## Selection Guide

| 策略 | 适用场景 | 主要风险 |
| :--- | :--- | :--- |
| `FIRST` / `LAST` | 必须固定机器（本地文件/缓存依赖） | 该机宕机即整体失败 |
| `ROUND` / `RANDOM` | 无状态任务的默认选择 | 不感知机器负载差异 |
| `CONSISTENT_HASH` | 希望同一任务长期落到同一台（利用本地缓存） | 机器列表变动会重分布 |
| `LEAST_FREQUENTLY_USED` / `LEAST_RECENTLY_USED` | 机器性能不均、需要按实际使用摊平 | 计数不跨调度节点、重启清零 |
| `FAILOVER` | 执行器稳定性差，需要自动避让死机器 | 串行探测，机器多时延迟高 |
| `BUSYOVER` | 任务耗时长、希望避开正在跑的机器 | 同上，且需要执行器有该 job 的线程记录 |
| `SHARDING_BROADCAST` | 需要并行处理大数据集 | 任一分片失败整体算失败；业务必须能按片切分 |

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
