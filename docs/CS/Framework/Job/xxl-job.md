## Introduction

XXL-JOB是一个分布式任务调度平台，其核心设计目标是开发迅速、学习简单、轻量级、易扩展

存储只支持MySQL
调度中心支持集群部署，集群情况下各节点务必连接同一个mysql实例
如果mysql做主从,调度中心集群节点务必强制走主库
建表sql位置
```
/xxl-job/doc/db/tables_xxl_job.sql
```

```xml
<!-- http://repo1.maven.org/maven2/com/xuxueli/xxl-job-core/ -->
<dependency>
    <groupId>com.xuxueli</groupId>
    <artifactId>xxl-job-core</artifactId>
    <version>${最新稳定版本}</version>
</dependency>
```

## Architecture

参考官方文档:

![](https://www.xuxueli.com/doc/static/xxl-job/images/img_Qohm.png)

将调度行为抽象形成“调度中心”公共平台，而平台自身并不承担业务逻辑，“调度中心”负责发起调度请求。

将任务抽象成分散的JobHandler，交由“执行器”统一管理，“执行器”负责接收调度请求并执行对应的JobHandler中业务逻辑。

“调度”和“任务”两部分可以相互解耦，提高系统整体稳定性和扩展性；

- **调度模块（调度中心）**：
  负责管理调度信息，按照调度配置发出调度请求，自身不承担业务代码。调度系统与任务解耦，提高了系统可用性和稳定性，同时调度系统性能不再受限于任务模块；
  支持可视化、简单且动态的管理调度信息，包括任务新建，更新，删除，GLUE开发和任务报警等，所有上述操作都会实时生效，同时支持监控调度结果以及执行日志，支持执行器Failover。
- **执行模块（执行器）**：
  负责接收调度请求并执行任务逻辑。任务模块专注于任务的执行等操作，开发和维护更加简单和高效；
  接收“调度中心”的执行请求、终止请求和日志请求等。

## start

```java
public class XxlJobSpringExecutor extends XxlJobExecutor implements ApplicationContextAware, SmartInitializingSingleton, DisposableBean {
    private static final Logger logger = LoggerFactory.getLogger(XxlJobSpringExecutor.class);


    // start
    @Override
    public void afterSingletonsInstantiated() {

        // init JobHandler Repository
        /*initJobHandlerRepository(applicationContext);*/

        // init JobHandler Repository (for method)
        initJobHandlerMethodRepository(applicationContext);

        // refresh GlueFactory
        GlueFactory.refreshInstance(1);

        // super start
        try {
            super.start();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
```

XxlJobExecutor
```java
public class XxlJobExecutor {
    public void start() throws Exception {

        // init logpath
        XxlJobFileAppender.initLogPath(logPath);

        // init invoker, admin-client
        initAdminBizList(adminAddresses, accessToken);


        // init JobLogFileCleanThread
        JobLogFileCleanThread.getInstance().start(logRetentionDays);

        // init TriggerCallbackThread
        TriggerCallbackThread.getInstance().start();

        // init executor-server
        initEmbedServer(address, ip, port, appname, accessToken);
    }
}
```


### initEmbedServer

启动[Netty](/docs/CS/Framework/Netty/Netty.md)

这里initEmbedServer负责处理请求

```java
public class EmbedServer {
    private static final Logger logger = LoggerFactory.getLogger(EmbedServer.class);

    private ExecutorBiz executorBiz;
    private Thread thread;

    public void start(final String address, final int port, final String appname, final String accessToken) {
        executorBiz = new ExecutorBizImpl();
        thread = new Thread(new Runnable() {
            @Override
            public void run() {
                // param
                EventLoopGroup bossGroup = new NioEventLoopGroup();
                EventLoopGroup workerGroup = new NioEventLoopGroup();
                ThreadPoolExecutor bizThreadPool = new ThreadPoolExecutor(
                        0,
                        200,
                        60L,
                        TimeUnit.SECONDS,
                        new LinkedBlockingQueue<Runnable>(2000),
                        new ThreadFactory() {
                            @Override
                            public Thread newThread(Runnable r) {
                                return new Thread(r, "xxl-job, EmbedServer bizThreadPool-" + r.hashCode());
                            }
                        },
                        new RejectedExecutionHandler() {
                            @Override
                            public void rejectedExecution(Runnable r, ThreadPoolExecutor executor) {
                                throw new RuntimeException("xxl-job, EmbedServer bizThreadPool is EXHAUSTED!");
                            }
                        });
                try {
                    // start server
                    ServerBootstrap bootstrap = new ServerBootstrap();
                    bootstrap.group(bossGroup, workerGroup)
                            .channel(NioServerSocketChannel.class)
                            .childHandler(new ChannelInitializer<SocketChannel>() {
                                @Override
                                public void initChannel(SocketChannel channel) throws Exception {
                                    channel.pipeline()
                                            .addLast(new IdleStateHandler(0, 0, 30 * 3, TimeUnit.SECONDS))  // beat 3N, close if idle
                                            .addLast(new HttpServerCodec())
                                            .addLast(new HttpObjectAggregator(5 * 1024 * 1024))  // merge request & reponse to FULL
                                            .addLast(new EmbedHttpServerHandler(executorBiz, accessToken, bizThreadPool));
                                }
                            })
                            .childOption(ChannelOption.SO_KEEPALIVE, true);

                    // bind
                    ChannelFuture future = bootstrap.bind(port).sync();

                    logger.info(">>>>>>>>>>> xxl-job remoting server start success, nettype = {}, port = {}", EmbedServer.class, port);

                    // start registry
                    startRegistry(appname, address);

                    // wait util stop
                    future.channel().closeFuture().sync();

                } catch (InterruptedException e) {
                    logger.info(">>>>>>>>>>> xxl-job remoting server stop.");
                } catch (Exception e) {
                    logger.error(">>>>>>>>>>> xxl-job remoting server error.", e);
                } finally {
                    // stop
                    try {
                        workerGroup.shutdownGracefully();
                        bossGroup.shutdownGracefully();
                    } catch (Exception e) {
                        logger.error(e.getMessage(), e);
                    }
                }
            }
        });
        thread.setDaemon(true);    // daemon, service jvm, user thread leave >>> daemon leave >>> jvm leave
        thread.start();
    }
}
```
#### registry

```java
public class ExecutorRegistryThread {
  private static ExecutorRegistryThread instance = new ExecutorRegistryThread();
  public static ExecutorRegistryThread getInstance(){
    return instance;
  }

  private Thread registryThread;
  private volatile boolean toStop = false;
  public void start(final String appname, final String address){
    // valid

    registryThread = new Thread(new Runnable() {
      @Override
      public void run() {

        // registry
        while (!toStop) {
          try {
            RegistryParam registryParam = new RegistryParam(RegistryConfig.RegistType.EXECUTOR.name(), appname, address);
            for (AdminBiz adminBiz: XxlJobExecutor.getAdminBizList()) {
              try {
                ReturnT<String> registryResult = adminBiz.registry(registryParam);
                if (registryResult!=null && ReturnT.SUCCESS_CODE == registryResult.getCode()) {
                  registryResult = ReturnT.SUCCESS;
                  logger.debug(">>>>>>>>>>> xxl-job registry success, registryParam:{}, registryResult:{}", new Object[]{registryParam, registryResult});
                  break;
                } else {
                  logger.info(">>>>>>>>>>> xxl-job registry fail, registryParam:{}, registryResult:{}", new Object[]{registryParam, registryResult});
                }
              } catch (Exception e) {
                logger.info(">>>>>>>>>>> xxl-job registry error, registryParam:{}", registryParam, e);
              }

            }
          } catch (Exception e) {
            if (!toStop) {
              logger.error(e.getMessage(), e);
            }

          }

          try {
            if (!toStop) {
              TimeUnit.SECONDS.sleep(RegistryConfig.BEAT_TIMEOUT);
            }
          } catch (InterruptedException e) {
            if (!toStop) {
              logger.warn(">>>>>>>>>>> xxl-job, executor registry thread interrupted, error msg:{}", e.getMessage());
            }
          }
        }

        // registry remove
        try {
          RegistryParam registryParam = new RegistryParam(RegistryConfig.RegistType.EXECUTOR.name(), appname, address);
          for (AdminBiz adminBiz: XxlJobExecutor.getAdminBizList()) {
            try {
              ReturnT<String> registryResult = adminBiz.registryRemove(registryParam);
              if (registryResult!=null && ReturnT.SUCCESS_CODE == registryResult.getCode()) {
                registryResult = ReturnT.SUCCESS;
                logger.info(">>>>>>>>>>> xxl-job registry-remove success, registryParam:{}, registryResult:{}", new Object[]{registryParam, registryResult});
                break;
              } else {
                logger.info(">>>>>>>>>>> xxl-job registry-remove fail, registryParam:{}, registryResult:{}", new Object[]{registryParam, registryResult});
              }
            } catch (Exception e) {
              if (!toStop) {
                logger.info(">>>>>>>>>>> xxl-job registry-remove error, registryParam:{}", registryParam, e);
              }

            }

          }
        } catch (Exception e) {
          if (!toStop) {
            logger.error(e.getMessage(), e);
          }
        }
        logger.info(">>>>>>>>>>> xxl-job, executor registry thread destroy.");

      }
    });
    registryThread.setDaemon(true);
    registryThread.setName("xxl-job, executor ExecutorRegistryThread");
    registryThread.start();
  }
}
```


EmbedHttpServerHandler
```java
public static class EmbedHttpServerHandler extends SimpleChannelInboundHandler<FullHttpRequest> {
    private static final Logger logger = LoggerFactory.getLogger(EmbedHttpServerHandler.class);

    private ExecutorBiz executorBiz;
    private String accessToken;
    private ThreadPoolExecutor bizThreadPool;

    @Override
    protected void channelRead0(final ChannelHandlerContext ctx, FullHttpRequest msg) throws Exception {
        // request parse
        //final byte[] requestBytes = ByteBufUtil.getBytes(msg.content());    // byteBuf.toString(io.netty.util.CharsetUtil.UTF_8);
        String requestData = msg.content().toString(CharsetUtil.UTF_8);
        String uri = msg.uri();
        HttpMethod httpMethod = msg.method();
        boolean keepAlive = HttpUtil.isKeepAlive(msg);
        String accessTokenReq = msg.headers().get(XxlJobRemotingUtil.XXL_JOB_ACCESS_TOKEN);

        // invoke
        bizThreadPool.execute(new Runnable() {
            @Override
            public void run() {
                // do invoke
                Object responseObj = process(httpMethod, uri, requestData, accessTokenReq);

                // to json
                String responseJson = GsonTool.toJson(responseObj);

                // write response
                writeResponse(ctx, keepAlive, responseJson);
            }
        });
    }

  private Object process(HttpMethod httpMethod, String uri, String requestData, String accessTokenReq) {
    // valid ...
    
    // services mapping
    try {
      switch (uri) {
        case "/beat":
          return executorBiz.beat();
        case "/idleBeat":
          IdleBeatParam idleBeatParam = GsonTool.fromJson(requestData, IdleBeatParam.class);
          return executorBiz.idleBeat(idleBeatParam);
        case "/run":
          TriggerParam triggerParam = GsonTool.fromJson(requestData, TriggerParam.class);
          return executorBiz.run(triggerParam);
        case "/kill":
          KillParam killParam = GsonTool.fromJson(requestData, KillParam.class);
          return executorBiz.kill(killParam);
        case "/log":
          LogParam logParam = GsonTool.fromJson(requestData, LogParam.class);
          return executorBiz.log(logParam);
        default:
          return new ReturnT<String>(ReturnT.FAIL_CODE, "invalid request, uri-mapping(" + uri + ") not found.");
      }
    } catch (Exception e) {
      logger.error(e.getMessage(), e);
      return new ReturnT<String>(ReturnT.FAIL_CODE, "request error:" + ThrowableUtil.toString(e));
    }
  }
}
```

看一下run对应的处理
```java
public class ExecutorBizImpl implements ExecutorBiz {
  @Override
  public ReturnT<String> run(TriggerParam triggerParam) {
    // load old：jobHandler + jobThread
    JobThread jobThread = XxlJobExecutor.loadJobThread(triggerParam.getJobId());
    IJobHandler jobHandler = jobThread!=null?jobThread.getHandler():null;
    String removeOldReason = null;

    // valid：jobHandler + jobThread
    GlueTypeEnum glueTypeEnum = GlueTypeEnum.match(triggerParam.getGlueType());
    if (GlueTypeEnum.BEAN == glueTypeEnum) {

      // new jobhandler
      IJobHandler newJobHandler = XxlJobExecutor.loadJobHandler(triggerParam.getExecutorHandler());

      // valid old jobThread
      if (jobThread!=null && jobHandler != newJobHandler) {
        // change handler, need kill old thread
        removeOldReason = "change jobhandler or glue type, and terminate the old job thread.";

        jobThread = null;
        jobHandler = null;
      }

      // valid handler
      if (jobHandler == null) {
        jobHandler = newJobHandler;
        if (jobHandler == null) {
          return new ReturnT<String>(ReturnT.FAIL_CODE, "job handler [" + triggerParam.getExecutorHandler() + "] not found.");
        }
      }

    } else if (GlueTypeEnum.GLUE_GROOVY == glueTypeEnum) {

      // valid old jobThread
      if (jobThread != null &&
              !(jobThread.getHandler() instanceof GlueJobHandler
                      && ((GlueJobHandler) jobThread.getHandler()).getGlueUpdatetime()==triggerParam.getGlueUpdatetime() )) {
        // change handler or gluesource updated, need kill old thread
        removeOldReason = "change job source or glue type, and terminate the old job thread.";

        jobThread = null;
        jobHandler = null;
      }

      // valid handler
      if (jobHandler == null) {
        try {
          IJobHandler originJobHandler = GlueFactory.getInstance().loadNewInstance(triggerParam.getGlueSource());
          jobHandler = new GlueJobHandler(originJobHandler, triggerParam.getGlueUpdatetime());
        } catch (Exception e) {
          logger.error(e.getMessage(), e);
          return new ReturnT<String>(ReturnT.FAIL_CODE, e.getMessage());
        }
      }
    } else if (glueTypeEnum!=null && glueTypeEnum.isScript()) {

      // valid old jobThread
      if (jobThread != null &&
              !(jobThread.getHandler() instanceof ScriptJobHandler
                      && ((ScriptJobHandler) jobThread.getHandler()).getGlueUpdatetime()==triggerParam.getGlueUpdatetime() )) {
        // change script or gluesource updated, need kill old thread
        removeOldReason = "change job source or glue type, and terminate the old job thread.";

        jobThread = null;
        jobHandler = null;
      }

      // valid handler
      if (jobHandler == null) {
        jobHandler = new ScriptJobHandler(triggerParam.getJobId(), triggerParam.getGlueUpdatetime(), triggerParam.getGlueSource(), GlueTypeEnum.match(triggerParam.getGlueType()));
      }
    } else {
      return new ReturnT<String>(ReturnT.FAIL_CODE, "glueType[" + triggerParam.getGlueType() + "] is not valid.");
    }

    // executor block strategy
    if (jobThread != null) {
      ExecutorBlockStrategyEnum blockStrategy = ExecutorBlockStrategyEnum.match(triggerParam.getExecutorBlockStrategy(), null);
      if (ExecutorBlockStrategyEnum.DISCARD_LATER == blockStrategy) {
        // discard when running
        if (jobThread.isRunningOrHasQueue()) {
          return new ReturnT<String>(ReturnT.FAIL_CODE, "block strategy effect："+ExecutorBlockStrategyEnum.DISCARD_LATER.getTitle());
        }
      } else if (ExecutorBlockStrategyEnum.COVER_EARLY == blockStrategy) {
        // kill running jobThread
        if (jobThread.isRunningOrHasQueue()) {
          removeOldReason = "block strategy effect：" + ExecutorBlockStrategyEnum.COVER_EARLY.getTitle();

          jobThread = null;
        }
      } else {
        // just queue trigger
      }
    }

    // replace thread (new or exists invalid)
    if (jobThread == null) {
      jobThread = XxlJobExecutor.registJobThread(triggerParam.getJobId(), jobHandler, removeOldReason);
    }

    // push data to queue
    ReturnT<String> pushResult = jobThread.pushTriggerQueue(triggerParam);
    return pushResult;
  }
}

```


主要是这两处
```java
        // replace thread (new or exists invalid)
        if (jobThread == null) {
            jobThread = XxlJobExecutor.registJobThread(triggerParam.getJobId(), jobHandler, removeOldReason);
        }

        // push data to queue
        ReturnT<String> pushResult = jobThread.pushTriggerQueue(triggerParam);
```

#### pushTriggerQueue

```java
public class JobThread extends Thread {
    public ReturnT<String> pushTriggerQueue(TriggerParam triggerParam) {
        // avoid repeat
        if (triggerLogIdSet.contains(triggerParam.getLogId())) {
            logger.info(">>>>>>>>>>> repeate trigger job, logId:{}", triggerParam.getLogId());
            return new ReturnT<String>(ReturnT.FAIL_CODE, "repeate trigger job, logId:" + triggerParam.getLogId());
        }

        triggerLogIdSet.add(triggerParam.getLogId());
        triggerQueue.add(triggerParam);
        return ReturnT.SUCCESS;
    }
}
```




```java
public class TriggerCallbackThread {
  public static void pushCallBack(HandleCallbackParam callback){
    getInstance().callBackQueue.add(callback);
  }

  private void doCallback(List<HandleCallbackParam> callbackParamList){
    boolean callbackRet = false;
    // callback, will retry if error
    for (AdminBiz adminBiz: XxlJobExecutor.getAdminBizList()) {
      try {
        ReturnT<String> callbackResult = adminBiz.callback(callbackParamList);
        if (callbackResult!=null && ReturnT.SUCCESS_CODE == callbackResult.getCode()) {
          callbackLog(callbackParamList, "<br>----------- xxl-job job callback finish.");
          callbackRet = true;
          break;
        } else {
          callbackLog(callbackParamList, "<br>----------- xxl-job job callback fail, callbackResult:" + callbackResult);
        }
      } catch (Exception e) {
        callbackLog(callbackParamList, "<br>----------- xxl-job job callback error, errorMsg:" + e.getMessage());
      }
    }
    if (!callbackRet) {
      appendFailCallbackFile(callbackParamList);
    }
  }
}
```




```java
public class MethodJobHandler extends IJobHandler {
    @Override
    public void execute() throws Exception {
        Class<?>[] paramTypes = method.getParameterTypes();
        if (paramTypes.length > 0) {
            method.invoke(target, new Object[paramTypes.length]);       // method-param can not be primitive-types
        } else {
            method.invoke(target);
        }
    }
}
```



## Scheduler



XXL-Job基于Spring Boot
```java
@SpringBootApplication
public class XxlJobAdminApplication {
	public static void main(String[] args) {
        SpringApplication.run(XxlJobAdminApplication.class, args);
	}
}

@Component
public class XxlJobAdminConfig implements InitializingBean, DisposableBean {

    private static XxlJobAdminConfig adminConfig = null;
    private XxlJobScheduler xxlJobScheduler;

    @Override
    public void afterPropertiesSet() throws Exception {
        adminConfig = this;

        xxlJobScheduler = new XxlJobScheduler();
        xxlJobScheduler.init();
    }

    @Override
    public void destroy() throws Exception {
        xxlJobScheduler.destroy();
    }
}
```



scheduler


```java

public class XxlJobScheduler {
    public void init() throws Exception {
        // init i18n
        initI18n();

        // admin trigger pool start
        JobTriggerPoolHelper.toStart();

        // admin registry monitor run
        JobRegistryHelper.getInstance().start();

        // admin fail-monitor run
        JobFailMonitorHelper.getInstance().start();

        // admin lose-monitor run ( depend on JobTriggerPoolHelper )
        JobCompleteHelper.getInstance().start();

        // admin log report start
        JobLogReportHelper.getInstance().start();

        // start-schedule  ( depend on JobTriggerPoolHelper )
        JobScheduleHelper.getInstance().start();
    }
}
```

### JobTriggerPoolHelper
移除Quartz依赖 使用自定义 "XxlJobThreadPool"，降低线程切换、内存占用带来的消耗，提高调度性能；

调度线程池隔离，拆分为"Fast"和"Slow"两个线程池，1分钟窗口期内任务耗时达500ms超过10次，
该窗口期内判定为慢任务，慢任务自动降级进入"Slow"线程池，避免耗尽调度线程，提高系统稳定性


```java
public class JobTriggerPoolHelper {
    // fast/slow thread pool
    private ThreadPoolExecutor fastTriggerPool = null;
    private ThreadPoolExecutor slowTriggerPool = null;

    public void start() {
        fastTriggerPool = new ThreadPoolExecutor(
                10,
                XxlJobAdminConfig.getAdminConfig().getTriggerPoolFastMax(),
                60L,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<Runnable>(1000),
                new ThreadFactory() {
                    @Override
                    public Thread newThread(Runnable r) {
                        return new Thread(r, "xxl-job, admin JobTriggerPoolHelper-fastTriggerPool-" + r.hashCode());
                    }
                });

        slowTriggerPool = new ThreadPoolExecutor(
                10,
                XxlJobAdminConfig.getAdminConfig().getTriggerPoolSlowMax(),
                60L,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<Runnable>(2000),
                new ThreadFactory() {
                    @Override
                    public Thread newThread(Runnable r) {
                        return new Thread(r, "xxl-job, admin JobTriggerPoolHelper-slowTriggerPool-" + r.hashCode());
                    }
                });
    }
}
```
#### trigger

```java
public static void trigger(int jobId, TriggerTypeEnum triggerType, int failRetryCount, String executorShardingParam, String executorParam, String addressList) {
  helper.addTrigger(jobId, triggerType, failRetryCount, executorShardingParam, executorParam, addressList);
}

public void addTrigger(final int jobId,
                       final TriggerTypeEnum triggerType,
                       final int failRetryCount,
                       final String executorShardingParam,
                       final String executorParam,
                       final String addressList) {

    // choose thread pool
    ThreadPoolExecutor triggerPool_ = fastTriggerPool;
    AtomicInteger jobTimeoutCount = jobTimeoutCountMap.get(jobId);
    if (jobTimeoutCount!=null && jobTimeoutCount.get() > 10) {      // job-timeout 10 times in 1 min
        triggerPool_ = slowTriggerPool;
    }

    // trigger
    triggerPool_.execute(new Runnable() {
        @Override
        public void run() {

            long start = System.currentTimeMillis();

            try {
                // do trigger
                XxlJobTrigger.trigger(jobId, triggerType, failRetryCount, executorShardingParam, executorParam, addressList);
            } catch (Exception e) {
                logger.error(e.getMessage(), e);
            } finally {

                // check timeout-count-map
                long minTim_now = System.currentTimeMillis()/60000;
                if (minTim != minTim_now) {
                    minTim = minTim_now;
                    jobTimeoutCountMap.clear();
                }

                // incr timeout-count-map
                long cost = System.currentTimeMillis()-start;
                if (cost > 500) {       // ob-timeout threshold 500ms
                    AtomicInteger timeoutCount = jobTimeoutCountMap.putIfAbsent(jobId, new AtomicInteger(1));
                    if (timeoutCount != null) {
                        timeoutCount.incrementAndGet();
                    }
                }

            }

        }
    });
}
```




### JobScheduleHelper


```java
public class JobScheduleHelper {
    private static JobScheduleHelper instance = new JobScheduleHelper();

    public static JobScheduleHelper getInstance() {
        return instance;
    }

    public static final long PRE_READ_MS = 5000;    // pre read

    private Thread scheduleThread;
    private Thread ringThread;
    private volatile boolean scheduleThreadToStop = false;
    private volatile boolean ringThreadToStop = false;
    private volatile static Map<Integer, List<Integer>> ringData = new ConcurrentHashMap<>();

    public void start() {

        // schedule thread
        scheduleThread = new Thread(new Runnable() {
            @Override
            public void run() {

                try {
                    TimeUnit.MILLISECONDS.sleep(5000 - System.currentTimeMillis() % 1000);
                } catch (InterruptedException e) {
                    if (!scheduleThreadToStop) {
                        logger.error(e.getMessage(), e);
                    }
                }
                logger.info(">>>>>>>>> init xxl-job admin scheduler success.");

                // pre-read count: treadpool-size * trigger-qps (each trigger cost 50ms, qps = 1000/50 = 20)
                int preReadCount = (XxlJobAdminConfig.getAdminConfig().getTriggerPoolFastMax() + XxlJobAdminConfig.getAdminConfig().getTriggerPoolSlowMax()) * 20;

                while (!scheduleThreadToStop) {

                    // Scan Job
                    long start = System.currentTimeMillis();

                    Connection conn = null;
                    Boolean connAutoCommit = null;
                    PreparedStatement preparedStatement = null;

                    boolean preReadSuc = true;
                    try {

                        conn = XxlJobAdminConfig.getAdminConfig().getDataSource().getConnection();
                        connAutoCommit = conn.getAutoCommit();
                        conn.setAutoCommit(false);

                        preparedStatement = conn.prepareStatement("select * from xxl_job_lock where lock_name = 'schedule_lock' for update");
                        preparedStatement.execute();

                        // tx start

                        // 1、pre read
                        long nowTime = System.currentTimeMillis();
                        List<XxlJobInfo> scheduleList = XxlJobAdminConfig.getAdminConfig().getXxlJobInfoDao().scheduleJobQuery(nowTime + PRE_READ_MS, preReadCount);
                        if (scheduleList != null && scheduleList.size() > 0) {
                            // 2、push time-ring
                            for (XxlJobInfo jobInfo : scheduleList) {

                                // time-ring jump
                                if (nowTime > jobInfo.getTriggerNextTime() + PRE_READ_MS) {
                                    // 2.1、trigger-expire > 5s：pass && make next-trigger-time
                                    logger.warn(">>>>>>>>>>> xxl-job, schedule misfire, jobId = " + jobInfo.getId());

                                    // 1、misfire match
                                    MisfireStrategyEnum misfireStrategyEnum = MisfireStrategyEnum.match(jobInfo.getMisfireStrategy(), MisfireStrategyEnum.DO_NOTHING);
                                    if (MisfireStrategyEnum.FIRE_ONCE_NOW == misfireStrategyEnum) {
                                        // FIRE_ONCE_NOW 》 trigger
                                        JobTriggerPoolHelper.trigger(jobInfo.getId(), TriggerTypeEnum.MISFIRE, -1, null, null, null);
                                        logger.debug(">>>>>>>>>>> xxl-job, schedule push trigger : jobId = " + jobInfo.getId());
                                    }

                                    // 2、fresh next
                                    refreshNextValidTime(jobInfo, new Date());

                                } else if (nowTime > jobInfo.getTriggerNextTime()) {
                                    // 2.2、trigger-expire < 5s：direct-trigger && make next-trigger-time

                                    // 1、trigger
                                    JobTriggerPoolHelper.trigger(jobInfo.getId(), TriggerTypeEnum.CRON, -1, null, null, null);
                                    logger.debug(">>>>>>>>>>> xxl-job, schedule push trigger : jobId = " + jobInfo.getId());

                                    // 2、fresh next
                                    refreshNextValidTime(jobInfo, new Date());

                                    // next-trigger-time in 5s, pre-read again
                                    if (jobInfo.getTriggerStatus() == 1 && nowTime + PRE_READ_MS > jobInfo.getTriggerNextTime()) {

                                        // 1、make ring second
                                        int ringSecond = (int) ((jobInfo.getTriggerNextTime() / 1000) % 60);

                                        // 2、push time ring
                                        pushTimeRing(ringSecond, jobInfo.getId());

                                        // 3、fresh next
                                        refreshNextValidTime(jobInfo, new Date(jobInfo.getTriggerNextTime()));

                                    }

                                } else {
                                    // 2.3、trigger-pre-read：time-ring trigger && make next-trigger-time

                                    // 1、make ring second
                                    int ringSecond = (int) ((jobInfo.getTriggerNextTime() / 1000) % 60);

                                    // 2、push time ring
                                    pushTimeRing(ringSecond, jobInfo.getId());

                                    // 3、fresh next
                                    refreshNextValidTime(jobInfo, new Date(jobInfo.getTriggerNextTime()));

                                }

                            }

                            // 3、update trigger info
                            for (XxlJobInfo jobInfo : scheduleList) {
                                XxlJobAdminConfig.getAdminConfig().getXxlJobInfoDao().scheduleUpdate(jobInfo);
                            }

                        } else {
                            preReadSuc = false;
                        }

                        // tx stop


                    } catch (Exception e) {
                        if (!scheduleThreadToStop) {
                            logger.error(">>>>>>>>>>> xxl-job, JobScheduleHelper#scheduleThread error:{}", e);
                        }
                    } finally {

                        // commit
                        if (conn != null) {
                            try {
                                conn.commit();
                            } catch (SQLException e) {
                                if (!scheduleThreadToStop) {
                                    logger.error(e.getMessage(), e);
                                }
                            }
                            try {
                                conn.setAutoCommit(connAutoCommit);
                            } catch (SQLException e) {
                                if (!scheduleThreadToStop) {
                                    logger.error(e.getMessage(), e);
                                }
                            }
                            try {
                                conn.close();
                            } catch (SQLException e) {
                                if (!scheduleThreadToStop) {
                                    logger.error(e.getMessage(), e);
                                }
                            }
                        }

                        // close PreparedStatement
                        if (null != preparedStatement) {
                            try {
                                preparedStatement.close();
                            } catch (SQLException e) {
                                if (!scheduleThreadToStop) {
                                    logger.error(e.getMessage(), e);
                                }
                            }
                        }
                    }
                    long cost = System.currentTimeMillis() - start;


                    // Wait seconds, align second
                    if (cost < 1000) {  // scan-overtime, not wait
                        try {
                            // pre-read period: success > scan each second; fail > skip this period;
                            TimeUnit.MILLISECONDS.sleep((preReadSuc ? 1000 : PRE_READ_MS) - System.currentTimeMillis() % 1000);
                        } catch (InterruptedException e) {
                            if (!scheduleThreadToStop) {
                                logger.error(e.getMessage(), e);
                            }
                        }
                    }

                }

                logger.info(">>>>>>>>>>> xxl-job, JobScheduleHelper#scheduleThread stop");
            }
        });
        scheduleThread.setDaemon(true);
        scheduleThread.setName("xxl-job, admin JobScheduleHelper#scheduleThread");
        scheduleThread.start();


        // ring thread
        ringThread = new Thread(new Runnable() {
            @Override
            public void run() {

                while (!ringThreadToStop) {

                    // align second
                    try {
                        TimeUnit.MILLISECONDS.sleep(1000 - System.currentTimeMillis() % 1000);
                    } catch (InterruptedException e) {
                        if (!ringThreadToStop) {
                            logger.error(e.getMessage(), e);
                        }
                    }

                    try {
                        // second data
                        List<Integer> ringItemData = new ArrayList<>();
                        int nowSecond = Calendar.getInstance().get(Calendar.SECOND);   // 避免处理耗时太长，跨过刻度，向前校验一个刻度；
                        for (int i = 0; i < 2; i++) {
                            List<Integer> tmpData = ringData.remove((nowSecond + 60 - i) % 60);
                            if (tmpData != null) {
                                ringItemData.addAll(tmpData);
                            }
                        }

                        // ring trigger
                        logger.debug(">>>>>>>>>>> xxl-job, time-ring beat : " + nowSecond + " = " + Arrays.asList(ringItemData));
                        if (ringItemData.size() > 0) {
                            // do trigger
                            for (int jobId : ringItemData) {
                                // do trigger
                                JobTriggerPoolHelper.trigger(jobId, TriggerTypeEnum.CRON, -1, null, null, null);
                            }
                            // clear
                            ringItemData.clear();
                        }
                    } catch (Exception e) {
                        if (!ringThreadToStop) {
                            logger.error(">>>>>>>>>>> xxl-job, JobScheduleHelper#ringThread error:{}", e);
                        }
                    }
                }
                logger.info(">>>>>>>>>>> xxl-job, JobScheduleHelper#ringThread stop");
            }
        });
        ringThread.setDaemon(true);
        ringThread.setName("xxl-job, admin JobScheduleHelper#ringThread");
        ringThread.start();
    }
}
```

#### ringthread




### 过期处理策略

任务调度错过触发时间时的处理策略：

- 可能原因：服务重启；调度线程被阻塞，线程被耗尽；上次调度持续阻塞，下次调度被错过；
- 处理策略：
  - 过期超5s：本次忽略，当前时间开始计算下次触发时间
  - 过期5s内：立即触发一次，当前时间开始计算下次触发时间



### 日志回调

```java
// JobCompleteHelper
public ReturnT<String> callback(List<HandleCallbackParam> callbackParamList) {

		callbackThreadPool.execute(new Runnable() {
			@Override
			public void run() {
				for (HandleCallbackParam handleCallbackParam: callbackParamList) {
					ReturnT<String> callbackResult = callback(handleCallbackParam);
					logger.debug(">>>>>>>>> JobApiController.callback {}, handleCallbackParam={}, callbackResult={}",
							(callbackResult.getCode()== ReturnT.SUCCESS_CODE?"success":"fail"), handleCallbackParam, callbackResult);
				}
			}
		});

		return ReturnT.SUCCESS;
	}

private ReturnT<String> callback(HandleCallbackParam handleCallbackParam) {
		// valid log item
		XxlJobLog log = XxlJobAdminConfig.getAdminConfig().getXxlJobLogDao().load(handleCallbackParam.getLogId());
		if (log == null) {
			return new ReturnT<String>(ReturnT.FAIL_CODE, "log item not found.");
		}
		if (log.getHandleCode() > 0) {
			return new ReturnT<String>(ReturnT.FAIL_CODE, "log repeate callback.");     // avoid repeat callback, trigger child job etc
		}

		// handle msg
		StringBuffer handleMsg = new StringBuffer();
		if (log.getHandleMsg()!=null) {
			handleMsg.append(log.getHandleMsg()).append("<br>");
		}
		if (handleCallbackParam.getHandleMsg() != null) {
			handleMsg.append(handleCallbackParam.getHandleMsg());
		}

		// success, save log
		log.setHandleTime(new Date());
		log.setHandleCode(handleCallbackParam.getHandleCode());
		log.setHandleMsg(handleMsg.toString());
		XxlJobCompleter.updateHandleInfoAndFinish(log);

		return ReturnT.SUCCESS;
}

```

### 调度FailOver

执行器如若集群部署，调度中心将会感知到在线的所有执行器，如“127.0.0.1:9997, 127.0.0.1:9998, 127.0.0.1:9999”。当任务”路由策略”选择”故障转移(FAILOVER)”时，当调度中心每次发起调度请求时，会按照顺序对执行器发出心跳检测请求，第一个检测为存活状态的执行器将会被选定并发送调度请求


## Executor



## Client




## Links

- [SchedulerX](/docs/CS/Job/ScheduleX.md)
- [ElasticJob](/docs/CS/Job/ElasticJob.md)

