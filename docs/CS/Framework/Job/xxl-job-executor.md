## Introduction

执行器（Executor）是 XXL-JOB 的任务执行端：一个内嵌在业务应用里的轻量进程，启动 Netty 服务监听调度中心的 HTTP 请求，把触发请求转成业务 JobHandler 的执行，并把结果回传。它与调度中心的全部契约就是 `/beat`、`/idleBeat`、`/run`、`/kill`、`/log` 五个 URI。本篇按启动链路逐层展开：`XxlJobSpringExecutor` → `XxlJobExecutor` → `EmbedServer`（Netty）→ 注册线程 → `EmbedHttpServerHandler` → `ExecutorBizImpl.run` → `JobThread` → `TriggerCallbackThread`。调度中心侧见 [xxl-job-scheduler](/docs/CS/Framework/Job/xxl-job-scheduler.md)。

源码基线为 2.x~3.x 通用的 `xxl-job-core`；3.5.0 起策略类移至 `xxl-job-admin/business/scheduler`，执行器侧核心类位置未变。

## Startup Chain

### XxlJobSpringExecutor

Spring 环境下执行器的入口，实现 `SmartInitializingSingleton`，在所有单例 bean 初始化完成后启动：

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

两件事值得注意：其一，`initJobHandlerMethodRepository` 扫描 Spring 上下文中带 `@XxlJob` 注解的方法注册成 handler（老的类级 `IJobHandler` 注册已注释）；其二，先刷新 `GlueFactory` 再启动，保证 GLUE 源码目录就绪。

### XxlJobExecutor.start

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

四步：初始化本地日志目录 → 构建调度中心客户端列表（`adminAddresses` 支持多地址，故障时逐个尝试）→ 启动日志文件清理线程（按 `logRetentionDays` 保留期滚动删除）→ 启动内嵌 Netty 服务。**回调线程在 Netty 服务之前启动**，确保第一波任务执行结果就有通道回传。

### initEmbedServer

启动 [Netty](/docs/CS/Framework/Netty/Netty.md)：

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
                            public Thread newThread(Thread r) {
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

几个设计细节：

- Pipeline 上 `IdleStateHandler(0, 0, 30 * 3, SECONDS)`：**90 秒无写即判定空闲**，与调度中心 30s 心跳周期（3N）对齐，连接僵死时由服务端主动关闭，避免半开连接占用。
- `HttpObjectAggregator(5 * 1024 * 1024)`：聚合 HTTP 分片，上限 5MB——GLUE 源码与大参数任务都走这条通道，超限直接拒绝。
- `bizThreadPool` 核心 0、最大 200、60s 空闲回收、队列 2000，拒绝策略是抛异常（**快速失败**，让调度中心感知重试而不是无限堆积）。
- 整个服务跑在 daemon 线程里：业务线程退出即 JVM 退出，不阻塞进程关闭。

### Registry

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

注册线程每 `BEAT_TIMEOUT`（30s）向所有调度中心地址发一次注册（保活），任一返回成功即 break；停机时发 `registryRemove` 摘除自己。这是执行器的"自动发现"机制——新机器上线下次调度即参与路由，与 ZK 临时节点方案殊途同归。

## Request Handling

### EmbedHttpServerHandler

Netty 层只做协议解析，按 URI 分发到 `ExecutorBizImpl`：

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

契约全集就五个 URI：`/beat` 探活、`/idleBeat` 问忙碌状态（BUSYOVER 路由依赖它）、`/run` 触发、`/kill` 终止、`/log` 拉日志。请求体是 JSON，经 Gson 反序列化为对应 Param；处理全部丢进 `bizThreadPool`，Netty IO 线程不执行业务。

### ExecutorBizImpl.run

`/run` 的处理是执行器的核心，按 GLUE 类型三路装载 handler，再套阻塞策略，最后入队：

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
        removeOldReason = "change script or glue type, and terminate the old job thread.";

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

三个关键设计：

1. **handler 热替换**：BEAN 模式比较新旧 handler 实例、GLUE/脚本模式比较 `glueUpdatetime`，任一变化就 kill 旧 `JobThread` 再建新的——GLUE 在线改代码因此即时生效。
2. **阻塞策略在入队前判定**：`DISCARD_LATER` 直接返回失败（调度中心记录本次丢弃），`COVER_EARLY` 置 `jobThread = null` 走重建，`SERIAL_EXECUTION` 什么都不做（继续排队）。
3. **每个 Job 一条专属 JobThread**：`registJobThread` 保证同一 `jobId` 只有一个线程在跑，天然串行。

### JobThread.pushTriggerQueue

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

`triggerLogIdSet` 做**触发请求去重**：调度中心重试、网络重发导致的同 `logId` 重复触发会被拒绝。`triggerQueue` 是无界队列，`JobThread.run()` 循环取任务执行；入队成功即返回，执行异步进行。

### TriggerCallbackThread

执行完成后，结果经回调线程送回调度中心：

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

所有调度中心地址都失败时，回调参数**落本地磁盘文件**（`appendFailCallbackFile`），由后台补偿线程重读重发——这是"调度中心整体宕机也不丢执行结果"的兜底，代价是执行器本地多了一份待同步状态。

### MethodJobHandler

BEAN 模式的最终执行点，反射调用业务方法：

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

注释里点明约束：方法参数不能是原始类型（反射 `new Object[paramTypes.length]` 无法为 `int` 等原始类型填值）。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [xxl-job-scheduler](/docs/CS/Framework/Job/xxl-job-scheduler.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
