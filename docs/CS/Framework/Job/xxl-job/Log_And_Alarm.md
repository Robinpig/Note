## Introduction

XXL-JOB 的任务日志是"两段式"的：**执行日志存在执行器本地磁盘文件里，调度与结果元数据存在 MySQL `xxl_job_log` 表里**。调度中心要查看某次执行的完整输出时，是反过来调执行器的 `/log` 接口按行读取。这个设计让 DB 不承担日志正文，代价是执行日志与执行器机器绑定——机器没了、文件清了，日志就没了。

本篇覆盖结果回收链路：回调落账、结果丢失补偿、失败重试、邮件告警、日志清理与运行报表。

源码基线 tag `3.5.0`。回调的发起方见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)，日志文件的写入见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)。

## Callback Landing

执行器回调 `/api/callback`，调度中心侧由 `JobCompleteHelper` 落账：

```java
public Response<String> callback(List<CallbackData> callbackParamList) {
    callbackThreadPool.execute(new Runnable() {
        public void run() {
            for (CallbackData callbackRequest: callbackParamList) {
                Response<String> callbackResult = doCallback(callbackRequest);
            }
        }
    });
    return Response.ofSuccess();
}

private Response<String> doCallback(CallbackData handleCallbackParam) {
    // valid log item
    XxlJobLog log = ...getXxlJobLogMapper().load(handleCallbackParam.getLogId());
    if (log == null) {
        return Response.ofFail("log item not found.");
    }
    if (log.getHandleCode() > 0) {
        return Response.ofFail("log repeate callback.");     // avoid repeat callback, trigger child job etc
    }

    // handle msg
    StringBuffer handleMsg = new StringBuffer();
    if (log.getHandleMsg()!=null) { handleMsg.append(log.getHandleMsg()).append("<br>"); }
    if (handleCallbackParam.getHandleMsg() != null) { handleMsg.append(handleCallbackParam.getHandleMsg()); }

    // success, save log
    log.setHandleTime(new Date());
    log.setHandleCode(handleCallbackParam.getHandleCode());
    log.setHandleMsg(handleMsg.toString());
    ...getJobCompleter().complete(log);

    return Response.ofSuccess();
}
```

三点设计：

- **入口立即返回 SUCCESS，落账异步**（`callbackThreadPool`：核心 2、最大 20、队列 3000，拒绝时降级为调用方线程执行）。执行器不等 DB 写入。
- **`handleCode > 0` 判重**：这是幂等闸门，防止重复回调重复触发子任务。所以 `jobLog` 的 `handleCode` 初值必须是 0。
- `handleMsg` 是**追加**语义（旧内容 + `<br>` + 新内容），多次回调会累积。

### JobCompleter

落账的真正收口在 `JobCompleter.complete()`：

```java
public int complete(XxlJobLog xxlJobLog) {
    // 1、process child-job
    processChildJob(xxlJobLog);

    // text最大64kb 避免长度过长
    if (xxlJobLog.getHandleMsg().length() > 15000) {
        xxlJobLog.setHandleMsg(xxlJobLog.getHandleMsg().substring(0, 15000));
    }

    // 2、fix_delay trigger next
    // on the way

    // 3、update job handle-info
    return xxlJobLogMapper.updateHandleInfo(xxlJobLog);
}
```

`processChildJob` 只在 `handleCode == 200`（成功）时触发子任务：

```java
if (XxlJobContext.HANDLE_CODE_SUCCESS == xxlJobLog.getHandleCode()) {
    XxlJobInfo xxlJobInfo = xxlJobInfoMapper.loadById(xxlJobLog.getJobId());
    if (xxlJobInfo!=null && StringTool.isNotBlank(xxlJobInfo.getChildJobId())) {
        String[] childJobIds = xxlJobInfo.getChildJobId().split(",");
        for (int i = 0; i < childJobIds.length; i++) {
            int childJobId = (isNotBlank && isNumeric) ? Integer.parseInt(childJobIds[i]) : -1;
            if (childJobId > 0) {
                if (childJobId == xxlJobLog.getJobId()) { continue; }   // 防自引用
                ...getJobTriggerPoolHelper().trigger(childJobId, TriggerTypeEnum.PARENT, -1, null, null, null);
            }
        }
    }
}
```

子任务触发的 `TriggerTypeEnum` 是 `PARENT`，且**只在父任务执行成功时触发**（不是触发成功）。子任务 ID 配置在 `xxl_job_info.child_jobid`，逗号分隔，自引用会被跳过。

`handleMsg` 截断阈值 15000（注释写 64kb 是旧文案，实际按字符数截断）。

## Result Lost Monitor

```java
jobMonitorThread = new CyclicThread("JobCompleteHelper#jobMonitorThread", true, new Runnable() {
    public void run() {
        // 任务结果丢失处理：调度记录停留在 "运行中" 状态超过10min，且对应执行器心跳注册失败不在线，则将本地调度主动标记失败；
        Date losedTime = DateTool.addMinutes(new Date(), -10);
        List<Long> losedJobIds = ...getXxlJobLogMapper().findLostJobIds(losedTime);

        if (losedJobIds!=null && losedJobIds.size()>0) {
            for (Long logId: losedJobIds) {
                XxlJobLog jobLog = new XxlJobLog();
                jobLog.setId(logId);
                jobLog.setHandleTime(new Date());
                jobLog.setHandleCode(XxlJobContext.HANDLE_CODE_FAIL);
                jobLog.setHandleMsg(I18nUtil.getString("joblog_lost_fail"));
                ...getJobCompleter().complete(jobLog);
            }
        }
    }
}, 60 * 1000L, true);
```

判定条件是 SQL 里写死的四条（见 `findLostJobIds`）：

```sql
SELECT t.id
FROM xxl_job_log t
LEFT JOIN xxl_job_registry t2 ON t.executor_address = t2.registry_value
WHERE t.trigger_code = 200                      -- 触发成功
  AND t.handle_code = 0                         -- 但一直没结果
  AND t.trigger_time <= #{losedTime}            -- 且超过 10 分钟
  AND t2.id IS NULL;                            -- 且执行器已不在注册表
```

**第四个条件（执行器已下线）常被忽略**：它让补偿只针对"执行器真没了"的情况，避免误杀"执行器还在、只是任务跑得慢"的长任务。这正是"结果丢失"与"任务慢"的分界线。

补偿走的是 `JobCompleter.complete()` 而非直接 update，所以**也会触发子任务**——这点有争议（父任务其实没成功），使用时需注意。

## Fail Retry and Alarm

```java
monitorThread = new CyclicThread("JobFailAlarmMonitorHelper#monitorThread", true, new Runnable() {
    public void run() {
        List<Long> failLogIds = ...getXxlJobLogMapper().findFailJobLogIds(1000);
        if (failLogIds!=null && !failLogIds.isEmpty()) {
            for (long failLogId: failLogIds) {

                // lock log
                int lockRet = ...getXxlJobLogMapper().updateAlarmStatus(failLogId, 0, -1);
                if (lockRet < 1) { continue; }
                XxlJobLog log = ...load(failLogId);
                XxlJobInfo info = ...loadById(log.getJobId());

                // 1、fail retry monitor
                if (log.getExecutorFailRetryCount() > 0) {
                    ...trigger(log.getJobId(), TriggerTypeEnum.RETRY,
                            (log.getExecutorFailRetryCount()-1),
                            log.getExecutorShardingParam(), log.getExecutorParam(), null);
                    ...updateTriggerInfo(log);
                }

                // 2、fail alarm monitor
                int newAlarmStatus = 0;
                if (info != null) {
                    boolean alarmResult = ...getJobAlarmer().alarm(info, log);
                    newAlarmStatus = alarmResult?2:3;
                } else {
                    newAlarmStatus = 1;
                }
                ...updateAlarmStatus(failLogId, -1, newAlarmStatus);
            }
        }
    }
}, 10 * 1000L, true);
```

每 10s 扫一次，单批上限 1000 条。

### Alarm Status State Machine

`alarm_status` 字段是这套机制的核心，五个状态：

| 值 | 含义 | 谁写 |
| :--- | :--- | :--- |
| 0 | 默认（待处理） | 日志创建时 |
| -1 | 锁定中 | 监控线程抢锁（`updateAlarmStatus(failLogId, 0, -1)`） |
| 1 | 无需告警（任务已删除） | 监控线程 |
| 2 | 告警成功 | 监控线程 |
| 3 | 告警失败 | 监控线程 |

`updateAlarmStatus` 的 SQL 带 `AND alarm_status = #{oldAlarmStatus}` 条件，是标准的 **CAS 乐观锁**——调度中心集群多节点同时扫到同一条失败日志时，只有一个能抢到，避免重复重试与重复发邮件。

3.5.0 专门给这个字段加了 `i_alarm_status` 索引（"提升失败告警巡检查询性能"），因为扫描条件就是 `alarm_status = 0`。

### Fail Scope

被扫出来的"失败"包括两类（`findFailJobLogIds`）：

```sql
WHERE `alarm_status` = 0
  AND `handle_code` != 200
  AND (`handle_code` != 0 OR `trigger_code` NOT IN (0, 200))
```

即：**执行失败**（`handle_code` 非 200 非 0），**或触发失败**（`handle_code` 还是 0 但 `trigger_code` 不是 0/200）。所以"执行器连不上"这种触发阶段失败也会被重试与告警。

### Retry Semantics

```java
trigger(log.getJobId(), TriggerTypeEnum.RETRY,
        (log.getExecutorFailRetryCount()-1),      // 传入剩余次数-1
        log.getExecutorShardingParam(),           // 保留原分片
        log.getExecutorParam(), null);
```

- 重试是**重新触发**，不是续跑：业务必须幂等；
- 剩余次数存在日志行上，每次重试 -1，递减到 0 就不再重试；
- 分片参数原样带回，所以分片广播的失败重试只补那一片；
- 重试与告警在同一次循环里完成：**先重试、再告警**，无论重试是否发起都会告警。

### Email Alarm

告警目前只有邮件一种实现（`EmailJobAlarm implements JobAlarm`），收件人取任务的 `alarm_email`（逗号分隔）：

```java
String alarmContent = "Alarm Job LogId=" + jobLog.getId();
if (jobLog.getTriggerCode() != XxlJobContext.HANDLE_CODE_SUCCESS) {
    alarmContent += "<br>TriggerMsg=<br>" + jobLog.getTriggerMsg();
}
if (jobLog.getHandleCode()>0 && jobLog.getHandleCode() != XxlJobContext.HANDLE_CODE_SUCCESS) {
    alarmContent += "<br>HandleCode=" + jobLog.getHandleMsg();
}
```

`JobAlarmer` 是组合入口（持 `List<JobAlarm>`），想接企业微信/钉钉只需实现 `JobAlarm` 并注册成 Spring bean。注意 3.5.0 的 `application.properties` 里把 `management.health.mail.enabled` 关掉了——邮件不可用不会让健康检查失败。

## Log Files

执行器侧的文件布局（`XxlJobFileAppender.initLogPath`）：

```
logPath/
├── gluesource/                      10_1514171108000.js        脚本类 GLUE 落盘
├── callbacklogs/                    xxl-job-callback-{md5}.log 回调失败兜底文件
└── 2017-12-25/                      639.log                    按触发日期 + logId 命名
```

日志文件名 `makeLogFileName(triggerDate, logId)` = `logPath/yyyy-MM-dd/{logId}.log`。这个路径由调度中心传下来的 `logDateTime` 与 `logId` 共同决定，所以调度中心查看日志时能算出文件名，再调 `/log?logDateTime=...&logId=...&fromLineNum=...` 读取。

两个清理机制：

| 位置 | 线程 | 周期 | 清理对象 |
| :--- | :--- | :--- | :--- |
| 执行器 | `JobLogFileCleanThreadHelper` | 1 天 | 本地日志文件，按 `logRetentionDays`（默认 30）保留 |
| 调度中心 | `JobLogReportHelper` | 1 天 | `xxl_job_log` 记录，按 `xxl.job.logretentiondays`（默认 30，< 3 则关闭）保留 |

调度中心侧的清理是分页循环删除，每批 1000 条：

```java
List<Long> logIds = null;
do {
    logIds = ...findClearLogIds(0, 0, clearBeforeTime, 0, 1000);
    if (logIds!=null && !logIds.isEmpty()) {
        ...clearLog(logIds);
    }
} while (logIds!=null && !logIds.isEmpty());
```

> [!WARNING]
>
> 两侧是**独立**清理的：调度中心删了 DB 记录不代表执行器上的日志文件还在（反之亦然）。常见现象是"调度日志页面显示已清理，但执行器磁盘上还占着空间"或"DB 还有记录，但点开执行日志为空（文件已清）"。排查时要两边都看。

## Log Report

`JobLogReportHelper` 每 60s 刷新**近 3 天**的运行报表（`xxl_job_log_report`），按天统计成功/失败/运行中数量：

```java
for (int i = 0; i < 3; i++) {
    // today / yesterday / the day before
    ...
    Map<String, Object> triggerCountMap = ...findLogReport(todayFrom, todayTo);
    int triggerDayCount = ...;
    int triggerDayCountRunning = ...;
    int triggerDayCountSuc = ...;
    int triggerDayCountFail = triggerDayCount - triggerDayCountRunning - triggerDayCountSuc;   // 倒推
    ...saveOrUpdate(xxlJobLogReport);
}
```

失败数是**倒推**出来的（总数 - 运行中 - 成功），要求 `handle_code` 的取值集合完备。表上有 `i_trigger_day` 唯一索引，`saveOrUpdate` 用 upsert。

只滚 3 天是刻意的性能约束：报表刷新每分钟全量重算，天数多了 DB 聚合压力大。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
