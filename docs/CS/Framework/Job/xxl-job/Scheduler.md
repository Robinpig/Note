## Introduction

调度中心是 XXL-JOB 的大脑：一个 Spring Boot Web 应用，管任务元数据、按秒推进触发时刻、把触发请求发给执行器、回收执行结果。它刻意**不引入 Quartz**，用自研的"秒级预读 + 60 槽时间轮"实现调度。本篇展开调度内核：启动装配、扫库线程、时间轮线程、下次触发时刻计算、misfire 处理与优雅停机。

源码基线 tag `3.5.0`，包路径 `com.xxl.job.admin.business.scheduler`。触发动作本身见 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)，执行器侧见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)。

## Boot

`XxlJobAdminBootstrap` 实现 `InitializingBean`，容器就绪即拉起全部后台线程：

```java
private void doStart() throws Exception {
    // trigger-pool start
    jobTriggerPoolHelper = new JobTriggerPoolHelper();
    jobTriggerPoolHelper.start();

    // registry monitor start
    jobRegistryHelper = new JobRegistryHelper();
    jobRegistryHelper.start();

    // fail-alarm monitor start
    jobFailAlarmMonitorHelper = new JobFailAlarmMonitorHelper();
    jobFailAlarmMonitorHelper.start();

    // job complate start  ( depend on JobTriggerPoolHelper ) for callback and result-lost
    jobCompleteHelper = new JobCompleteHelper();
    jobCompleteHelper.start();

    // log-report start
    jobLogReportHelper = new JobLogReportHelper();
    jobLogReportHelper.start();

    // job-schedule start  ( depend on JobTriggerPoolHelper )
    jobScheduleHelper = new JobScheduleHelper();
    jobScheduleHelper.start();
}
```

**依赖顺序即启动顺序，停止顺序严格逆序**：触发线程池最先起、最后停；时间轮（`JobScheduleHelper`）最后起、最先停。这保证任何时刻"有人要触发时触发池一定活着，时间轮停了之后不会再有新的触发请求"。

除 `JobTriggerPoolHelper` 是纯线程池外，其余 5 个 Helper 各持一条常驻线程（3.5.0 起统一封装为 `CyclicThread`），周期分别是 30s / 10s / 60s / 60s，加上 `JobScheduleHelper` 的两条 1s 线程，构成调度中心的全部后台负载。

## Schedule Thread

`JobScheduleHelper#scheduleThread` 每秒一轮扫库，是全局唯一的"推进者"。3.5.0 相较 2.x 有三处实现变化：事务改由 Spring `PlatformTransactionManager` 管理、锁与回写改走 Mapper、回写改分批。

```java
// pre-read count: treadpool-size * 10 (trigger-qps: 1000ms / 100ms each trigger cost)
int preReadCount = (XxlJobAdminBootstrap.getInstance().getTriggerPoolFastMax()
                  + XxlJobAdminBootstrap.getInstance().getTriggerPoolSlowMax()) * 10;

while (!scheduleThreadToStop) {
    long start = System.currentTimeMillis();
    boolean preReadSuc = true;

    TransactionStatus transactionStatus = null;
    try {
        transactionStatus = ...getTransactionManager().getTransaction(new DefaultTransactionDefinition());
        // 1、job lock
        String lockedRecord = ...getXxlJobLockMapper().scheduleLock();
        long nowTime = System.currentTimeMillis();

        // scan and process job
        List<XxlJobInfo> scheduleList = ...getXxlJobInfoMapper().scheduleJobQuery(nowTime + PRE_READ_MS, preReadCount);
        ...
    } finally {
        // avlid schedule repeat
        ...getTransactionManager().commit(transactionStatus);
    }
    long cost = System.currentTimeMillis()-start;

    // Wait seconds, align second
    if (cost < 1000) {  // scan-overtime, not wait
        TimeUnit.MILLISECONDS.sleep((preReadSuc?1000:PRE_READ_MS) - System.currentTimeMillis()%1000);
    }
}
```

### Lock and Transaction

集群互斥靠 `xxl_job_lock` 表的一行 `schedule_lock`：`select ... for update` 拿到行锁，事务提交时释放。**只有抢到锁的节点会真正扫库**，其余节点本次循环扫到空集、把 `preReadSuc` 置 false 后 sleep 5s 跳过这一轮——所以集群规模再大，扫库压力也不随节点数增长。

事务边界覆盖"读任务 → 计算下次触发时刻 → 回写"，源码注释写明目的 `avlid schedule repeat`：若不加事务，两个节点前后脚读到同一批任务会重复触发。

### Three Branches

对预读出的每一条任务按当前时刻与 `triggerNextTime` 的关系三分支处理：

| 分支 | 条件 | 动作 |
| :--- | :--- | :--- |
| 2.1 过期超 5s | `nowTime > triggerNextTime + PRE_READ_MS` | 交 `MisfireHandler` 处理，再从**当前时刻**重算下次 |
| 2.2 刚过期（5s 内） | `nowTime >= triggerNextTime` | 立即触发一次 → 重算下次 → 若下次仍在 5s 内，顺手入轮并再推进一次 |
| 2.3 未到期 | 其余 | 入时间轮 → 重算下次 |

分支 2.2 里的"顺手再推一次"值得注意：对于秒级间隔的高频任务（如每 2s 一次），一次扫描会连推两格时间轮，避免每轮只走一格跟不上节奏。

### Batch Write-back

```java
int batchSize = XxlJobAdminBootstrap.getInstance().getScheduleBatchSize();
List<List<XxlJobInfo>> scheduleListBatches = CollectionTool.split(scheduleList, batchSize);
for (List<XxlJobInfo> scheduleListBatch : scheduleListBatches) {
    int totalAffected = ...getXxlJobInfoMapper().scheduleBatchUpdate(scheduleListBatch);
}
```

2.x 是逐条 `scheduleUpdate`，3.5.0 改为按 `xxl.job.schedule.batchsize`（默认 100，合法区间 50~500）分批批量更新，减少大任务量下的往返与事务体积。

## Time Ring

`ringThread` 每秒跳一格，从 `Map<Integer, List<Integer>> ringData` 取槽位并触发：

```java
int nowSecond = Calendar.getInstance().get(Calendar.SECOND);
for (int i = 0; i <= 2; i++) {      // 避免调度遗漏：处理耗时太长、跨过刻度，除当前刻度外 + 向前校验2个刻度
    List<Integer> ringItemList = ringData.remove((nowSecond+60-i)%60);
    if (CollectionTool.isNotEmpty(ringItemList)) {
        // 避免调度重复：重复推送时间轮刻度，去重只保留一个
        List<Integer> ringItemListDistinct = ringItemList.stream().distinct().toList();
        if (ringItemListDistinct.size() < ringItemList.size()) {
            logger.warn(">>>>>>>>>>> xxl-job, time-ring found job repeat beat : " + nowSecond + " = " + ringItemData);
        }
        ringItemData.addAll(ringItemListDistinct);
    }
}
```

时间轮本身极简：`ringSecond = (int)((triggerNextTime/1000)%60)`，即**用绝对秒数对 60 取模当槽位**，一个 `ConcurrentHashMap` 就是全部数据结构。

两个防御性设计：

- **向前校验 3 个刻度**（`i <= 2`）：2.x 只回看 2 个刻度（当前秒 + 前一秒）。3.5.0 扩到 3 个，应对"本轮处理耗时跨过整秒导致漏读"。
- **同秒去重**：同一 jobId 被重复推入同一槽时只保留一个，避免重复触发。这正是分支 2.2 连续推两格可能带来的副作用。

对齐同样靠 sleep 补偿：`1000 - System.currentTimeMillis() % 1000`。扫描超时（cost ≥ 1000ms）则跳过本轮等待——宁可丢一拍也不叠延迟。

> [!WARNING]
>
> 时间轮是**纯内存**结构，没有持久化。调度中心进程被强杀时，已入轮但尚未触发的这一批任务会直接消失；重启后靠 `trigger_next_time` 的落库值 + misfire 策略补偿。这是"预读 + 时间轮"换取 DB 压力解耦所付的代价。

## Next Trigger Time

```java
private void refreshNextTriggerTime(XxlJobInfo jobInfo, Date fromTime) {
    ScheduleTypeEnum scheduleTypeEnum = ScheduleTypeEnum.match(jobInfo.getScheduleType(), ScheduleTypeEnum.NONE);
    Date nextTriggerTime = scheduleTypeEnum.getScheduleType().generateNextTriggerTime(jobInfo, fromTime);

    if (nextTriggerTime != null) {
        jobInfo.setTriggerStatus(-1);               // pass, may be Inaccurate
        jobInfo.setTriggerLastTime(jobInfo.getTriggerNextTime());
        jobInfo.setTriggerNextTime(nextTriggerTime.getTime());
    } else {
        // generate fail, stop job
        jobInfo.setTriggerStatus(TriggerStatus.STOPPED.getValue());
        jobInfo.setTriggerLastTime(0);
        jobInfo.setTriggerNextTime(0);
    }
}
```

三个实现（`ScheduleType` 抽象类的子类）：

| 类型 | 实现 | 说明 |
| :--- | :--- | :--- |
| `CRON` | `CronScheduleType` | 自研 `CronExpression.getNextValidTimeAfter()`，非 Quartz；支持 7 位（含秒） |
| `FIX_RATE` | `FixRateScheduleType` | `fromTime + conf × 1000`，再对齐到整秒 |
| `NONE` | `NoneScheduleType` | 返回 null，不自动调度 |

`FIX_RATE` 是"固定速率"而非"固定延时"：基准是 `fromTime`（上次计算出的触发时刻）而不是上次实际执行完成时刻，因此**任务执行耗时长于间隔时会积压**（由阻塞策略兜底）。

`triggerStatus = -1` 这个中间态容易被忽略：扫库 SQL 按 `trigger_next_time` 与运行态过滤，`-1` 表示"本轮已处理、本轮不再被扫到"，由后续 `scheduleBatchUpdate` 写回真实状态。

计算失败（Cron 表达式非法等）的后果是**任务被自动置为停止态**（`triggerLastTime = 0`、`triggerNextTime = 0`），日志打 error。这是配置错误的暴露方式，不是静默跳过。

## Misfire

3.5.0 把 misfire 抽成 `MisfireHandler` 抽象类 + 两个实现，由枚举持有实例：

```java
public enum MisfireStrategyEnum {
    DO_NOTHING(I18nUtil.getString("misfire_strategy_do_nothing"), new MisfireDoNothing()),
    FIRE_ONCE_NOW(I18nUtil.getString("misfire_strategy_fire_once_now"), new MisfireFireOnceNow());
    ...
}
```

```java
public class MisfireFireOnceNow extends MisfireHandler {
    @Override
    public void handle(int jobId) {
        // FIRE_ONCE_NOW 》 trigger
        XxlJobAdminBootstrap.getInstance().getJobTriggerPoolHelper()
            .trigger(jobId, TriggerTypeEnum.MISFIRE, -1, null, null, null);
    }
}
```

`MisfireDoNothing.handle()` 只打一条 warn。判定阈值就是预读窗口 `PRE_READ_MS = 5000`：过期超 5s 才进 misfire 分支，5s 内按"刚过期"直接触发。所以严格说**5s 内的迟到不算 misfire，只是补触发**。

## Elegant Shutdown

```java
public void stop(){
    // 1、stop schedule
    scheduleThreadToStop = true;
    ...
    // if has ring data, wait for elegent shutdown
    boolean hasRingData = false;
    if (MapTool.isNotEmpty(ringData)) { ... }
    if (hasRingData) {
        TimeUnit.SECONDS.sleep(ELEGANT_SHUTDOWN_WAITING_SECONDS);   // 10s
    }

    // 2、stop ring (wait job-in-memory stop)
    ringThreadToStop = true;
    ...
}
```

停机顺序：先停 `scheduleThread`（不再往轮里塞），检查轮里还有没有数据，有则等 `ELEGANT_SHUTDOWN_WAITING_SECONDS = 10s` 让 `ringThread` 把它发完，最后停 `ringThread`。这就是发布说明里的"调度中心停机，检测时间轮非空时主动等待调度完成"。

10s 是硬编码常量，不可配置；超过就强停，残留的这一批仍会丢。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Log And Alarm](/docs/CS/Framework/Job/xxl-job/Log_And_Alarm.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
