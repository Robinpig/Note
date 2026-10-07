## Introduction

定时任务（scheduled task）看起来是工程里最简单的一件事——"到点跑一下"——但它恰好是本库横跨领域最广的一条线：往下要落到内核的 tick 与高精度定时器，中间要落到语言运行时的线程模型，往上还要解决"整个集群到点只触发一次、跑不完要能补"的一致性问题。

本篇只做**纵向串联与选型判断**，具体机制一律指向已有专文，不重复叙述。三条主线：

- 语言与运行时怎么"等一个时刻"——Java、Go、Node.js，以及它们最终都要落到的内核定时器；
- 中间件怎么扛**海量**定时器——时间轮、MQ 的延时投递、用 DB/Redis 自建；
- 分布式调度框架怎么把"一次触发"变成"可运维的一整套能力"——Quartz、ElasticJob、xxl-job、PowerJob、ScheduleX。

与 [定时任务总览（Java 视角）](/docs/CS/Java/JDK/sche.md) 的分工：那篇是 Java 侧的源码解析主文（`Timer`、`ScheduledThreadPoolExecutor` 逐段拆），本篇是跨语言、跨层的总览；两者不互抄实现细节。

## Why Scheduling Gets Hard

"到点触发"的复杂度随规模分三段跳级，每跳一级就多出一类必须解决的问题：

**第一级：单机。** 至少要有一条线程在等。等待方式直接决定精度和成本——阻塞在最小堆顶（`DelayQueue`）、按固定 tick 推进（时间轮）、还是交给内核（`timerfd`）。任务模型只有四种：Cron、Fixed Rate、Fixed Delay、One Time（见 [任务模型](/docs/CS/Java/JDK/sche.md?id=task-model)），但语义差异很值钱：Fixed Rate 会"追赶"错过的触发，Fixed Delay 会"跳过"，一个慢任务在单线程 `Timer` 上能把后面所有任务全部拖死，甚至一个未捕获异常直接终止调度线程——这正是 JDK 官方弃用 `Timer` 的原因。

**第二级：海量定时器。** 网络连接心跳、请求超时、失败重试这类场景的特点是**任务海量、逻辑极简、执行极短、对及时性要求低**（晚 100ms 无所谓，见 [中间件场景定时任务](/docs/CS/Java/JDK/sche.md?id=middleware-scenario-scheduled-tasks)）。这时"每个任务一条线程"或"每个任务一个堆节点"都不成立，需要把插入和取消降到 O(1)，也就是时间轮。

**第三级：集群。** 多实例部署把问题从"怎么等"变成"谁等"：同一时刻只能有一台触发（否则重复扣款），于是要选主、要分片、要故障转移；同时必须补上失败重试与告警、错过触发的补偿、任务堆积的限流、执行日志与可视化。**这一级是"语言 API"与"调度框架"的分界线**——单机 API 再健壮也不解决"只跑一次"和"跑不完"。

## Single Process Timers in Java

Java 的演进路径是"单线程 + 小顶堆 → 线程池 + 延迟队列"：

`Timer` 由 `TimerThread` 与 `TaskQueue`（小顶堆）组成，所有任务串行执行、异常不做隔离。它的价值在于是最直观的样本——看清它的四个缺陷，才明白 `ScheduledThreadPoolExecutor` 为什么要改造成"可配置线程池 + `DelayedWorkQueue`"（逐段源码见 [Timer 源码解析](/docs/CS/Java/JDK/sche.md?id=timer-source-code-analysis)）。

`ScheduledThreadPoolExecutor`（STPE）实现了完整的 `ExecutorService` 生命周期，任务异常会被捕获且该任务不再入队，Fixed Rate 模式只补跑错过的最后一次而不是全部堆积重跑。它是 Java 侧事实上的单机定时底座（源码见 [ScheduledThreadPoolExecutor 源码解析](/docs/CS/Java/JDK/sche.md?id=scheduledthreadpoolexecutor-source-code-analysis)）。

Spring 的 `@Scheduled` 只是 STPE 之上的一层声明式包装，抽象是 `TaskScheduler` + `Trigger`（`CronTrigger` / `PeriodicTrigger`）。默认单线程调度器意味着**多个 cron 任务互相排队**，这是线上最常见的"任务没准点跑"根因；虚拟线程与 `ScheduledExecutorService` 的关系、以及 `@Scheduled` 线程池怎么换，见 [Spring Task](/docs/CS/Framework/Spring/Task.md?id=schedule)。

一次性任务（One Time）在这层有个务实的替代判据：任务量很大时不要用调度器逐个挂（每个 Job 都占资源），改成**MQ 定时消息**或**秒级 Map 任务扫库**，把"等待"外包出去。

## Other Language Runtimes

不同语言把"等待"下沉到同一个地方，但暴露的 API 形态差别很大：

Go 的 `time.Timer` / `Ticker` 背后是 `runtime.timer`：`when` + `period` + 回调 `f`，以及"channel timer"这一特殊形态——`After`/`NewTimer` 的到期时间是**惰性投递**到 channel 的（没人读就一直不投，读的时候再倒推），并用 `seq` 序号丢弃过期投递（结构体逐字段注释见 [Go timer](/docs/CS/Go/timer.md)）。理解这一点才能解释为什么 `for { select { case <-time.After(...) } }` 的行为与直觉不符。

Node.js 的定时器不是独立线程，而是事件循环的一个阶段：`setTimeout`/`setInterval` 回调在 **timers phase** 执行，排在 poll 之前，`setImmediate` 在 check 阶段，微任务（`process.nextTick`、Promise）在每次阶段切换之间清空。所以定时回调的实际触发时间受**上一阶段阻塞**影响，精度天然不可靠（见 [运行模型：事件循环](/docs/CS/front-end/Nodejs.md?id=execution-model-event-loop)）。

Linux 用户态提供四种"睡眠到某时刻"的接口（`nanosleep`、`clock_nanosleep`、POSIX timer、`timerfd`），C/C++/Rust/Go 的定时能力最终都要挑其中一个（见 [四种定时唤醒接口](/docs/CS/OS/Linux/timer.md?id=four-timer-wakeup-interfaces)）。这也是"为什么 `sleep` 会漂、为什么定时器会晚触发"这类问题唯一正确的答案来源。

## Kernel Timers Under Everything

所有用户态定时最终都落在内核的两套机制上：**低精度定时器**用分级时间轮（同一时刻的海量普通 timer 挂在按有效期位数分级的槽里，避免逐个扫描），**高精度定时器 hrtimer** 用红黑树按到期时间排序（需要 ns 级精度的场景，以及 tick 停掉之后模拟 tick）。两者取舍与用户态完全同构：**海量短超时用轮，少量精确到点用树/堆**（对照表见 [Comparison with Other Timer Schemes](/docs/CS/Algorithms/TimingWheel.md?id=comparison-with-other-timer-schemes)）。

内核侧还有两件直接影响"定时准不准"的事：`NO_HZ` 会在系统空闲时停掉节拍中断，深睡的 CPU 醒来后靠 **tick broadcast** 补定时；定时任务在 CPU 间迁移时还要搬定时器。做容器化调度时，被 cgroup 限流的进程其定时器精度还会受调度延迟影响。整条链路的机制与排障见 [Linux 时间子系统](/docs/CS/OS/Linux/timer.md)。

## Timing Wheels in Middleware

时间轮的数据结构本身只有一页纸（[Timing Wheel](/docs/CS/Algorithms/TimingWheel.md)），值得单独强调的是**各家选型上的分歧点**：

Netty 的 `HashedWheelTimer` 是**单层**轮，默认 tick 100ms、wheel 512 槽，实例化即起一个 worker 线程，因此必须全应用共享一个实例——为每个连接 new 一个是最典型的误用。它和 EventLoop 自带的 `schedule()`（最小堆）适用范围不同：海量近似超时用轮，少量精确任务用堆（见 [Tick Duration](/docs/CS/Framework/Netty/HashedWheelTimer.md?id=tick-duration) 与 [compare schedule](/docs/CS/Framework/Netty/HashedWheelTimer.md?id=compare-schedule)）。

Kafka 用**层级**时间轮 + `DelayQueue` + 一个 Reaper 线程推动指针，解决单层轮"跨度不够"和"空推进"两个问题，服务端的延迟操作（Purgatory）就挂在这上面（见 [Kafka Timer](/docs/CS/MQ/Kafka/Timer.md)）。

Dubbo 的超时检测是时间轮的另一个典型用法：`DefaultFuture` 每个请求注册一个 timeout，30ms 是**时间轮 tick 精度**而不是"每 30ms 扫全表"——把它理解成扫描会得出完全错误的容量规划结论（见 [超时机制：时间轮定时器，不是扫描线程](/docs/CS/Framework/Dubbo/Protocol.md?id=timeout-mechanism-time-wheel-timer-not-a-scanning-thread)）。

调度框架内部也用时间轮收敛"扫库"开销：PowerJob Server 先按 15s 窗口批量捞 `nextTriggerTime`，再放进**秒/分/时三级时间轮**做精确投递，避免为每个任务轮询数据库（见 [时间轮](/docs/CS/Framework/Job/PowerJob.md?id=timing-wheel)）。

同一招在缓存过期上同样成立：Caffeine 用层级时间轮组织过期条目而不是给每个 entry 挂定时器，且清理是惰性的（见 [Caffeine](/docs/CS/SE/Caffeine.md)）；Pulsar broker 的事务超时同样直接复用 Netty 的 `HashedWheelTimer`（见 [Pulsar Broker](/docs/CS/MQ/Pulsar/Broker.md)）。

## Delayed Delivery in Message Queues

把"等待"外包给 MQ 的形态是**延时消息**：消息先落盘，到点才对消费者可见。四家的支持度差异本身就是一张判据表（见 [Comparison](/docs/CS/MQ/MQ.md?id=comparison)）：

RocketMQ 有两条实现路径，理解它们能看清"固定级别"与"任意时间点"的代价差别。固定延迟（18 级）把 topic 改写成 `SCHEDULE_TOPIC_XXXX` 并按级别分队列，每一级一个定时器线程顺序扫该队列、到期后搬回原 topic；任意时间点投递则用 `rmq_sys_wheel_timer` + `TimerMessageStore`，槽位粒度 1 秒、指针每秒推进一格（见 [固定延迟](/docs/CS/MQ/RocketMQ/Broker.md?id=fixed-delay) 与 [指定时间点](/docs/CS/MQ/RocketMQ/Broker.md?id=specify-point-in-time)）。

RabbitMQ 没有原生延时队列，靠 **TTL + 死信交换机**拼：消息（或队列）设 TTL，过期后被投到 DLX。致命细节是**过期消息只在到达队首时才被丢弃**，所以"队列深度一直涨但里面的消息早该过期"是正常行为而非泄漏，需要即时释放就得换队列级 TTL（见 [两种 TTL 方式](/docs/CS/MQ/RabbitMQ.md?id=two-types-of-ttl-approaches)）。4.3 quorum queue 的 `x-delayed-retry-*` 是消费失败退避重试，不要当成定时投递。

ActiveMQ/Artemis 用消息属性 `_AMQ_SCHED_DELIVERY`（未来毫秒时间戳）实现 Scheduled Messages；Kafka **原生不支持**，只能自建"延迟 topic + 时间轮"或引入外部调度（见 [ActiveMQ](/docs/CS/MQ/ActiveMQ.md)）。

选型判据：延时消息换来的是"到点必达 + 重试与死信由 broker 承担"，代价是精度受限（RocketMQ 固定级别只有 18 档）、以及"任意延时"往往要额外一套存储。业务侧只需要关心"到点收到一条消息"，不要在自己进程里再挂一层定时器。

## DIY Scheduling on Databases

没有调度框架、也不想引入 MQ 时的两种土办法，各自能撑到什么规模要说清楚：

**Redis ZSet 当延迟队列**：score 存触发时间戳，轮询取 `score <= now` 的成员。相比 JDK `DelayQueue`，它天然有序、可持久化、跨进程可见（利用 ZSet 做延迟队列的场景与优缺点见 [zset](/docs/CS/DB/Redis/struct/zset.md)）。但**多消费者必须解决"取走的原子性"**，否则同一任务被并发处理多次——用 `ZPOPMIN`/Lua 或按 score 抢占式删除，并配合幂等键。Redis 作为消息组件的整体定位与牺牲见 [Redis as MQ](/docs/CS/DB/Redis/MQ.md)，Keyspace Notifications 触发的被动式玩法见 [PubSub](/docs/CS/DB/Redis/PubSub.md)。

**定时扫表**：`SELECT ... WHERE status = ? AND next_time <= now() LIMIT n`，简单、可靠、有依赖（DB 压力、延迟下限、扫出即执行的重复执行风险），适合任务量小且本来就落在 DB 的场景（订单超时、对账）。它的正式形态是"主动查询补偿"：回调没来就按 10s/20s/30s 递增轮询直到上限，配合"支付中"这类中间状态避免重复处理（见 [掉单机制](/docs/CS/SE/掉单机制.md)）。

这两种做法共同缺的是分片、失败告警、错过补偿和可视化管理——一旦任务数上百或需要"哪台跑"的编排，就该换成下一节的框架。

## Distributed Scheduling Frameworks

任何分布式定时任务都由三个角色组成：**任务**（业务逻辑）、**调度器**（决定何时、派给谁）、**执行器**（接收并执行）。角色是否分离，是这些框架的第一条分水岭（角色模型见 [分布式定时任务](/docs/CS/Java/JDK/sche.md?id=distributed-scheduled-tasks)）。

Quartz 是 Java 侧的事实标准，抽象出 `JobDetail` / `Trigger` / `Scheduler` + JDBC JobStore。它的"分布式"是在**数据库层用行锁抢占**：谁抢到 trigger 谁执行。代价写在它的四条不满里——API 侵入、业务 Job 要持久化进它的表、调度逻辑与业务同进程（任务一多就互相拖累）、抢占式导致节点负载悬殊；集群还依赖 DB 且节点数超过 3 个左右调度吞吐反而下降（见 [Cluster](/docs/CS/Framework/Job/Quartz/Quartz.md?id=cluster)）。

ElasticJob 是"Quartz + ZooKeeper 协调"的无中心化 jar 形态：靠 ZK 做节点注册与分片重排（resharding），弹性扩缩容时自动把分片重分一遍。它把 Quartz 的负载不均换成了 ZK 的运维与性能负担（见 [Architecture](/docs/CS/Framework/Job/ElasticJob.md?id=architecture)）。

xxl-job 把调度器与执行器彻底拆开：调度中心用 `select ... from xxl_job_lock where lock_name = 'schedule_lock' for update` 抢数据库行锁，保证多实例下只有一个调度线程在推进，`JobScheduleHelper` 每次**预读未来 5 秒**（`PRE_READ_MS = 5000`）的触发放进触发线程池（`JobTriggerPoolHelper` 快慢两级池）。执行器注册上来后由调度中心按**路由策略**挑选（故障转移会按顺序探活、选中第一个存活的实例），并支持分片广播、失败重试与告警、可视化与手动触发；执行侧还有**阻塞处理策略**（单机串行 / 丢弃后续 / 覆盖之前）来兜住"上一轮还没跑完"的情况；错过触发的补偿由 `MisfireStrategyEnum`（`FIRE_ONCE_NOW` / `DO_NOTHING`）决定，调度线程本身还有一条硬编码兜底——**过期 5s 内立即补一次、过期超过 5s 则忽略本次并从现在重算下次时间**（见 [Scheduler](/docs/CS/Framework/Job/xxl-job.md?id=scheduler)、[过期处理策略](/docs/CS/Framework/Job/xxl-job.md?id=expiration-handling-strategy) 与 [调度 FailOver](/docs/CS/Framework/Job/xxl-job.md?id=scheduling-failover)）。瓶颈仍在调度中心的 Master。

PowerJob（原 OhMyScheduler）在调度之外补了**计算模型**：MapReduce 任务能把一个大任务拆成子任务分发到多个 Worker，适合"定时 + 分布式跑批"合一的场景。ScheduleX 是云托管形态，把调度器可用性、多机房容灾、任务编排（图形化且任务间可传递数据）、OpenAPI、灰度验证都算进产品能力（见 [定时调度](/docs/CS/Framework/Job/ScheduleX.md?id=timer-scheduling)）。

六家的逐项对比（定时调度方式、任务编排、分布式跑批、多语言、可观测、报警、容灾、性能瓶颈）已经是一张现成的表，见 [分布式定时任务的对比表](/docs/CS/Java/JDK/sche.md?id=distributed-scheduled-tasks)，本篇不再抄一份。三句话判据：

- 只是单机 cron，别上框架——`@Scheduled` / STPE 足够，引入调度中心只会多一个要维护的组件；
- Java 栈自建、要可视化 + 分片 + 失败告警，选 xxl-job；同时还要"一次触发算完一张大表"，选 PowerJob 的 MapReduce；
- 不想自己维护调度器与 DB/ZK 的容灾，用云托管（ScheduleX）；任务之间是依赖关系而不是时间点，那是工作流，不是定时任务。

## Recurring Pitfalls

调度框架换不掉的问题，全部集中在这一节——它们是选型表里看不出来、上线后一定会遇到的。

**错过触发（misfire）**：调度器宕机 10 分钟，这期间的触发是补跑、跳过还是只跑最后一次？必须有显式策略（xxl-job 的 `FIRE_ONCE_NOW` / `DO_NOTHING`、Quartz 的 misfire instruction），而默认值往往不是你想要的答案。补跑还要防"雪崩式追赶"：一次性把 10 分钟的实例全并发拉起会打爆下游——xxl-job 用"过期超过 5s 就忽略本次"把追赶窗口压成一个宽限期，正是为此。

**重复触发**：选主脑裂、DB 锁提前释放、网络分区后的双调度器都可能导致同一任务在两台机器上同时跑。框架只能"尽量保证一次"，**业务侧必须幂等**：唯一业务键 + 状态机 + 数据库唯一约束，用中间状态（如"处理中"）把"检查"和"占位"合并成一步（做法见 [掉单机制](/docs/CS/SE/掉单机制.md)）。

**任务堆积**：与 MQ 堆积同构，需要限流与分片。关键约束是"单次执行时间 > 触发周期"——Fixed Delay 会自动拉开间隔，Fixed Rate 会追赶，两者在堆积时行为完全不同；调度框架下的分片（把 key 空间切成 N 片广播）才是根治办法，框架提供的单机阻塞策略（xxl-job 的串行 / 丢弃后续 / 覆盖之前）只是在三者之间选一种损失。

**任务超时与重试**：超时杀线程并不等于业务没做一半，重试只有在幂等成立时才安全，且要配退避。框架侧一般提供超时告警 + 失败重试次数（见 [任务超时](/docs/CS/Framework/Job/ScheduleX.md?id=task-timeout)），但"杀掉后下游的挂起请求怎么办"要自己收口。

**时钟问题**：跨节点的 cron 语义依赖 NTP 同步（Quartz 明确要求集群节点时钟在 1 秒内）；容器里的 `TZ` 与宿主机不一致会导致"每天 0 点"跑到别的时区；夏令时会让 2 点这一小时不存在或重复；`clock_nanosleep` 用单调时钟还是墙上时钟，决定改系统时间时定时任务会不会被"提前触发"。

**线程与隔离**：所有 `@Scheduled` 共用默认单线程调度器，一个慢任务能拖死全部定时任务；重任务应放独立线程池并由定时器只做派发。反过来，虚拟线程降低了阻塞代价，但没有改变"同一 cron 实例不该并发重入"的要求。

**可观测下限**：任何调度都要能看到三件事——下次触发时间、上次执行耗时与结果、失败告警到人。缺一件就别上线。

## Not Scheduled Tasks

相邻但不同，划清边界可以避免把这几类笔记当成本篇的重复内容：

**集群资源调度**（Mesos、Omega、Firmament）解决的是"哪个应用拿到多少 CPU/内存"，不是"到点触发什么"（见 [Cluster Scheduler](/docs/CS/Distributed/Cluster_Scheduler.md)）。操作系统的进程调度同理，是时间片分配（见 [CPU 调度](/docs/CS/OS/scheduling.md)）。

**工作流与 DAG 编排**是**依赖驱动**（上游完成才触发下游），定时只是入口之一；BPMN/Flowable 这类业务流程编排同理（见 [Workflow](/docs/CS/SE/Workflow.md)、[工作流](/docs/CS/Framework/Job/DolphinScheduler.md?id=workflow)）。判据：如果需要的是"到点跑一段代码"，用调度框架；如果需要的是"一堆任务的先后与条件分支"，用工作流引擎。

**批处理执行侧**（Spring Batch）只负责"怎么跑"（分块、跳过策略、重启），"什么时候跑"要交给 cron、调度框架或 K8s CronJob（见 [Spring Batch](/docs/CS/Framework/Spring/Batch.md)）。

**云原生形态**：K8s `CronJob` 由控制面按 schedule 创建 `Job` 对象、再由 Job 控制器拉起 Pod 跑完即走，等于把"调度器"变成集群里的一个控制器（见 [K8s 工作负载](/docs/CS/Container/k8s/K8s.md)）；Serverless 则把定时触发做成平台的事件源，函数只留业务逻辑（见 [Serverless](/docs/CS/SE/Serverless.md)）。这条线的源码级笔记目前还是缺的。

## Open Gaps

- **Python** 侧的事件循环定时器已补：`loop.call_later` / `call_at` 用 `heapq` 最小堆实现、与 fd 就绪合流进同一个 `_ready` 队列、以及"承诺不早于某时刻而非准时"的精度语义，见 [Asyncio](/docs/CS/Python/Asyncio.md?id=timer-heap-call_later-and-call_at)。**APScheduler 与 Celery beat 仍无笔记**（后者只在 [消息队列](/docs/CS/MQ/MQ.md) 的调度语义里被顺带提到）。
- **Rust / C++** 侧没有任何定时任务笔记：tokio 的 `time` driver（内部也是层级轮/堆混合），POSIX `timer_create` 与 `timerfd` 的选择。
- **Go** 侧只摘录了 `runtime.timer` 结构体，缺四叉堆的调度循环、`netpoll` 与 timer 的关系，以及 `time.After` 在 `for-select` 中堆积的实践结论（见 [Go timer](/docs/CS/Go/timer.md)）。
- **K8s CronJob / Job 控制器**无专文（`jobController.md` 只讲 Job 一侧），`Job` 与 `CronJob` 的并发策略（`concurrencyPolicy`、`startingDeadlineSeconds`、misfire 语义）未覆盖。
- **服务器层定时**（`crontab`、`systemd` timer unit、anacron 对错过执行的补偿）全库零覆盖，而它恰是"最小可用分布式调度"的对照组。
- [定时任务总览](/docs/CS/Java/JDK/sche.md) 末尾 Tuning 一节的五个子标题里只有"任务堆积"留了一句话，本篇 [Recurring Pitfalls](/docs/CS/SE/Scheduled_Task.md?id=recurring-pitfalls) 已就近补写要点，长期应回填到那篇对应位置。

## Links

- [软件工程](/docs/CS/SE/Engineering.md)
- [分布式](/docs/CS/Distributed/Distributed.md)
- [操作系统](/docs/CS/OS/OS.md)
- [消息队列](/docs/CS/MQ/MQ.md)
- [System Design](/docs/CS/SE/SystemDesign.md)
- [Rate Limiter](/docs/CS/SE/RateLimiter.md)

## References

1. [Hashed and Hierarchical Timing Wheels: Data Structures for the Efficient Implementation of a Timer Facility](https://dl.acm.org/doi/pdf/10.1145/41457.37504)
2. [ScheduledExecutorService (Java SE API)](https://docs.oracle.com/javase/8/docs/api/java/util/concurrent/ScheduledExecutorService.html)
3. [Quartz Scheduler Documentation](https://www.quartz-scheduler.org/documentation/)
4. [XXL-JOB 官方文档](https://www.xuxueli.com/xxl-job/)
5. [Apache RocketMQ Documentation](https://rocketmq.apache.org/docs/)
6. [Node.js Event Loop, Timers, and process.nextTick](https://nodejs.org/en/learn/asynchronous-work/event-loop-timers-and-nexttick)
