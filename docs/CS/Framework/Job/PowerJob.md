## Introduction

[PowerJob](http://www.powerjob.tech/)（原OhMyScheduler）是全新一代分布式任务调度与计算框架






@Slf4j
@EnableScheduling
@SpringBootApplication
public class PowerJobServerApplication {
    public static void main(String[] args) {

        pre();

        // Start SpringBoot application.
        try {
            SpringApplication.run(PowerJobServerApplication.class, args);
        } catch (Throwable t) {
            throw t;
        }
    }

    private static void pre() {
        log.info(TIPS);
        PropertyUtils.init();
    }

}


## 任务调度

1. Server 启动 → 开启多个 LoopRunnable 线程（调度间隔 15 秒）
2. scheduleNormalJob: 查询 nextTriggerTime ≤ now+30s 的待调度任务
3. 批量创建 Instance 记录（任务执行实例）
4. 推入 InstanceTimeWheelService 等待精确触发
5. 时间轮到期 → 调用 dispatchService 通过 akka-remote 派发任务
6. Worker 接收 → 执行任务 → 上报状态 → Server 更新 Instance 状态



### 时间轮

PowerJob 的时间轮设计是其核心特性之一，采用分层设计，通过多级时间轮实现精确的任务调度


• 第一层（秒级）：60 个槽位，管理 0~60 秒内任务
• 第二层（分钟级）：60 个槽位，管理 1~60 分钟内任务  
• 第三层（小时级）：24 个槽位，管理 1~24 小时内任务
• 任务到期时逐级降级，最终由秒级轮触发执行
• 优势：避免全量扫描数据库，调度精度 ±1 秒，内存占用可控





## Links


## References

1. [分布式 Java 任务调度平台 PowerJob](https://github.com/HelloGitHub-Team/Article/blob/master/contents/Java/PowerJob/catalog.md)