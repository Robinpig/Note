## Introduction

"下次什么时候触发"由 `TimingStrategyService` 按 `TimeExpressionType` 分派到具体 handler 计算。它的设计是**策略模式 + `EnumMap` 注入**：所有 handler 在构造时一次性注册，运行期按枚举 O(1) 查表。本文以 `powerjob-server/.../core/scheduler/TimingStrategyService.java` 与 `powerjob-common/.../enums/TimeExpressionType.java`（4.3.9）为据，并标出 5.x 才补齐的 `DAILY_TIME_INTERVAL` handler。

## TimeExpressionType

`TimeExpressionType` 是调度侧的统一枚举（`TimeExpressionType.java:20-28`）：

| 枚举 | 值 | 含义 |
| :--- | :--- | :--- |
| `API` | 1 | OpenAPI 自定义调度策略（如延迟执行） |
| `CRON` | 2 | CRON 表达式 |
| `FIXED_RATE` | 3 | 固定频率 |
| `FIXED_DELAY` | 4 | 固定延迟（上次执行结束后计时） |
| `WORKFLOW` | 5 | 工作流实例的 CRON 触发 |
| `DAILY_TIME_INTERVAL` | 11 | 每日时间段内按间隔触发（**5.x 策略 handler 补齐**） |

两个分组常量很关键：`FREQUENT_TYPES = [FIXED_RATE, FIXED_DELAY]`（`:32`，秒级任务扫描用）、`INSPECT_TYPES = [CRON, DAILY_TIME_INTERVAL]`（`:36`，首次计算必须算出有效触发时间，否则抛异常）。

## EnumMap Dispatch

`TimingStrategyService` 在构造时把全部 `TimingStrategyHandler` 装进一个 `EnumMap`（`TimingStrategyService.java:29-35`）：

```java
public TimingStrategyService(List<TimingStrategyHandler> timingStrategyHandlers) {
    strategyContainer = new EnumMap<>(TimeExpressionType.class);
    for (TimingStrategyHandler h : timingStrategyHandlers) {
        strategyContainer.put(h.supportType(), h);
    }
}
```

运行期 `getHandler(type)` 直接 `strategyContainer.get(type)`（`:114-120`），找不到对应 handler 抛 `PowerJobException`。本机 4.3.9 源码 (`.../scheduler/auxiliary/impl/`) 实存的 handler 有：`CronTimingStrategyHandler`、`FixedRateTimingStrategyHandler`、`FixedDelayTimingStrategyHandler`、`ApiTimingStrategyHandler`、`WorkflowTimingStrategyHandler`，外加抽象基类 `AbstractTimingStrategyHandler`。

## Next Trigger Calculation

UI 预览与持久化都走同一组方法：

- `calculateNextTriggerTimes(...)`（`:46-63`）循环 `NEXT_N_TIMES = 5`（`:22`）次，一次算接下来 5 个触发时间供前端展示；
- `calculateNextTriggerTime(...)`（`:75-80`）算单个下次时间，且 `preTriggerTime` 若小于当前时间则重置为 `now`——避免停机恢复后算出一堆过去的时间点。

注意源码注释（被 `PowerScheduleService` 引用）仍写作"忽略 5S 内的重复执行"，但常量 `SCHEDULE_RATE` 是 15000ms（15s）。**以常量为准**：CRON 模式下最小连续执行间隔是 15s，不是 5s。

## 5.x 待确认

- **`DailyTimeIntervalStrategyHandler`**：本机 4.3.9 的 `auxiliary` 目录里**完全没有 `DAILY` 字样**——既没有这个 handler 类，也没有任何文件引用 `DAILY_TIME_INTERVAL`。这说明 `DAILY_TIME_INTERVAL` 的专用策略 handler 是 **5.x 才补齐**的（早期版本它可能落到某个默认/兜底实现，或被 `CRON` 近似处理）。需回 v5.1.7 源码 (`.../auxiliary/impl/DailyTimeIntervalStrategyHandler.java`) 确认其真实存在与算法。
- **5.1.7 修复**：官方 changelog 记 "fixed DAILY_TIME_INTERVAL 首次触发不落在窗口边界"——这条修复的前提正是 5.x 已存在独立 handler，进一步佐证它是 5.x 新增能力。

## Links

- [PowerJob](/docs/CS/Framework/Job/PowerJob.md)
- [Scheduling](/docs/CS/Framework/Job/PowerJob/Scheduling.md)
- [Timing Wheel](/docs/CS/Framework/Job/PowerJob/Timing_Wheel.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [PowerJob GitHub](https://github.com/PowerJob/PowerJob)
- [PowerJob 官方文档](https://www.yuque.com/powerjob/guidence/intro)
