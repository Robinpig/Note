## Introduction

SchedulerX 的一个任务由**两个正交维度**决定：任务类型（用哪种语言/载体实现）与执行模式（这一次的触发怎么摊到机器上）。控制台创建任务时它们是两个下拉框，OpenAPI `CreateJob` 里是 `JobType` 与 `ExecuteMode` 两个字段。本页拆开这两个维度，并给出分布式模型（Map / MapReduce / 分片）的编程模型与硬限制。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

## Job Types

OpenAPI `CreateJob` 的 `JobType` 枚举即官方语言覆盖清单：

| JobType | 说明 | 备注 |
| :--- | :--- | :--- |
| `java` | 用户进程内执行，或上传 JAR 动态加载 | 必须填 `ClassName`（JobProcessor 全路径）；**只有 Java 任务支持工作流数据传递** |
| `shell` | 控制台直接写 Shell 脚本 | 脚本任务，1.14.x 支持子进程强制终止 |
| `python` | 控制台直接写 Python 脚本 | 需要 Worker 机器有 Python 环境 |
| `go` / `golang` | 控制台直接写 Go 脚本；或用 Go SDK 以任务名注册 | 控制台创建时任务类型选 `golang`，任务名须与代码注册名一致 |
| `http` | Serverless HTTP 任务，GET/POST 两种 | **不依赖 Client**，控制台配完即生效 |
| `k8s` | K8s 任务 | 支持脚本版本管理；1.13.4 起 CPU 采集支持 cgroup v2 |
| `xxljob` | 兼容开源 XXL-JOB 的任务类型 | 对应 `schedulerx2-plugin-xxljob` / `schedulerx3-plugin-xxljob` |
| `springschedule` | 接管 Spring `@Scheduled` 的任务 | 配合 `@SchedulerX` 注解（1.12.1+） |
| `dataworks` | DataWorks 任务 | 与阿里大数据开发治理平台联动 |

控制台的任务类型下拉框表述为"Java、XXL-JOB、SpringSchedule、Golang、脚本任务、Http 和 DataWorks"，选脚本任务时再选脚本语言（shell / python / go）。

## Execute Modes

`ExecuteMode` 枚举与控制台表述的对应关系：

| ExecuteMode | 控制台名称 | 语义 |
| :--- | :--- | :--- |
| `standalone` | 单机运行 | 随机挑选一台机器执行 |
| `broadcast` | 广播运行 | 所有机器同时执行，等待全部结束 |
| `parallel` | 可视化 MapReduce（并行计算） | Map 模型，**子任务 300 以下**有子任务列表；专业版支持到 1000 以下且支持业务关键字查询 |
| `grid` | 内存网格 | 网格计算家族，需开启 `enableBatchWork` |
| `batch` | MapReduce（网格计算） | 支持超大数量子任务并行，仅可查子任务汇总信息，**建议子任务 100 万以下** |
| `sharding` | 分片运行 | 类似 ElasticJob：控制台配置分片参数，平均分给多个客户端，支持多语言版本 |

选 `parallel` / `grid` / `batch` 都属于"非单机任务"，会直接影响计费：任务托管 CU 中非单机任务按 × Worker 数计算。

## Programming Models

### Standalone and Broadcast

单机模式只需实现 `JavaProcessor`：

```java
@Component
public class MyHelloJob extends JavaProcessor {
    @Override
    public ProcessResult process(JobContext context) throws Exception {
        System.out.println("hello schedulerx2.0");
        return new ProcessResult(true);
    }
}
```

`JavaProcessor` 的四个钩子里只有 `process` 必选：`preProcess`（可选前置）、`process`（必选）、`postProcess`（可选后置）、`kill`（可选，收到停止指令时回调）。

广播模式在同一批 Worker 上各跑一份；Go SDK 的 `BroadcastProcessor` 把它拆得更细：`PreProcess` 由 master 在所有 worker 的 `Process` 前执行一次，`Process` 每个 worker 都跑并可返回结果，`PostProcess` 由 master 在所有 `Process` 结束后执行一次，可通过 `ctx.TaskResults()` / `ctx.TaskStatuses()` 拿全部节点结果。

### Map and MapReduce

Map 模型是"几行代码做分布式跑批"的核心。`MapJobProcessor` 在 `process` 里通过 `context.isRootTask()` 判断自己是不是根任务：根任务负责切分数据并调用 `map()`，非根任务执行单个子任务。

```java
public class TestMapJob extends MapJobProcessor {
    @Override
    public ProcessResult process(JobContext context) throws Exception {
        if (context.isRootTask()) {
            // 1. 根任务：构造子任务列表并分发
            List<Object> taskList = loadIds();
            return map(taskList, "OrderTask");
        }
        // 2. 子任务：处理单个分片数据
        return new ProcessResult(true, "handled " + context.getTask());
    }

    @Override
    public ProcessResult reduce(JobContext context) throws Exception {
        // MapReduceJobProcessor 才有：所有子任务完成后由 Master 执行一次
        return new ProcessResult(true, "done");
    }
}
```

要点：

- `MapJobProcessor` 保留 `postProcess`；`MapReduceJobProcessor` **废弃 `postProcess`、新增 `reduce`**——所有子任务完成后回调 `reduce`，由 **Master 节点**执行，一般用于数据聚合或通知下游，也可用于工作流上下游数据传递。
- `reduce` 里通过 `context.getTaskStatuses()` 与 `context.getTaskResults()` 取全部子任务状态与结果；子任务通过 `return new ProcessResult(true, result)` 返回结果。

### Sharding

分片运行类似 ElasticJob：控制台配置分片参数，框架把分片平均分给多个客户端执行，业务侧从 `JobContext` 取 `ShardingNum` / `ShardingId`（Go SDK 里是 `ctx.ShardingNum()` / `ctx.ShardingId()`）。它**支持多语言版本**，是脚本任务、Go 任务做水平扩展的主要手段。

## Subtask Distribution

分布式模型下子任务怎么分到各台机器，由两个独立开关决定。

**分发策略（master 侧）**：

- 轮询策略（默认）：每个 Worker 平均分配等量子任务，适用于子任务耗时基本一致的场景。
- WorkerLoad 最优策略：主节点自动感知 Worker 负载，适用于子任务或机器处理耗时差异大的场景。

**子任务分发方式（slave 侧）**：

- 推模型：每台机器平均分配子任务。
- 拉模型：每台机器主动拉取子任务，**没有木桶效应**，支持动态扩容拉取。代价是所有子任务会缓存在 Master 节点，对内存有压力，**建议子任务数不超过 10,000**。

拉模型有三个配套参数（默认值）：子任务单次拉取数 **5**、子任务队列容量 **10**、子任务全局并发数 **1,000**（分布式拉模型用它做全局限流）。

## Hard Limits

三条限制是硬性约束，踩了不会报错在编译期，而是运行期失败：

- **单个子任务的大小不能超过 64 KB**（指 `map()` 传入的单个 task 对象）。
- **`ProcessResult` 的 result 不能超过 1000 Byte**——注意是**字节数不是字符数**，含中文时很容易超限，超限任务会失败；较新版本会自动截断而不是直接失败，但依赖截断是坏习惯。
- **SchedulerX 不保证子任务绝对执行一次**：特殊条件下会 failover，**可能导致子任务重复执行**，业务方必须自行实现幂等。

内存侧的隐含约束：`reduce` 会把所有子任务结果缓存在 Master 节点，子任务个数与 result 返回值都不要太大；没有 reduce 需求就用 `MapJobProcessor`，别上 `MapReduceJobProcessor`。

## Timeout and Kill

- **超时只支持任务级别，不支持子任务级别**，且可通过控制台动态修改。
- 实例被停止后，Server 发 Kill 消息到客户端；客户端收到后停止下发、停止执行未执行的子任务、销毁实例上下文与线程池，但**已经在执行中的子任务不会被强杀，只会中断对应线程**，因此子任务会继续运行直到结束。若要求"停止后立即结束"，必须在子任务逻辑里处理线程 interrupt 状态。
- 脚本任务自 **1.14.0** 起支持**子进程强制终止**——这是脚本类任务唯一能真正杀掉子进程的手段。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Architecture](/docs/CS/Framework/Job/ScheduleX/Architecture.md)
- [Workflow](/docs/CS/Framework/Job/ScheduleX/Workflow.md)
- [Client Access](/docs/CS/Framework/Job/ScheduleX/Client_Access.md)
- [Operations](/docs/CS/Framework/Job/ScheduleX/Operations.md)

## References

- [CreateJob - 创建任务并返回任务ID（JobType / ExecuteMode 枚举）](https://help.aliyun.com/zh/schedulerx/api-task-id)
- [任务管理（执行模式与高级配置说明）](https://help.aliyun.com/zh/document_detail/2673709.html)
- [分布式调度任务功能全面解析（EDAS）](https://helpcdn.aliyun.com/zh/edas/function)
- [schedulerx-worker-go（Go Processor 接口定义）](https://github.com/alibaba/schedulerx-worker-go)
