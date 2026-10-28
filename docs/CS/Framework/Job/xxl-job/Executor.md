## Introduction

执行器（Executor）是 XXL-JOB 的任务执行端：一个内嵌在业务应用里的轻量组件，启动 Netty 服务监听调度中心的 HTTP 请求，把触发请求转成业务 JobHandler 的执行，并把结果回传。它与调度中心的下行契约就是 `/beat`、`/idleBeat`、`/trigger`、`/kill`、`/log` 五个 URI（3.5.0 起原 `/run` 更名为 `/trigger`）。

本篇按启动链路逐层展开：`XxlJobSpringExecutor` → `XxlJobExecutor.start` → `EmbedServer`（Netty）→ `EmbedHttpServerHandler`（分发）→ `ExecutorBizImpl.trigger` → `JobThread` → `TriggerCallbackThreadHelper`（回调）。任务怎么被调度见 [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)，请求进来后怎么排队见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)，注册与保活见 [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)。

源码基线 tag `3.5.0`，包路径 `com.xxl.job.core`。

## Handler Scan

Spring 环境下入口是 `XxlJobSpringExecutor`，实现 `SmartInitializingSingleton`，在所有单例 bean 初始化完成后启动：

```java
@Override
public void afterSingletonsInstantiated() {
    // scan JobHandler method
    scanJobHandlerMethod(applicationContext);

    // refresh GlueFactory
    GlueFactory.refreshInstance(1);

    // super start
    try {
        super.start();
    } catch (Exception e) {
        throw new RuntimeException(e);
    }
}
```

扫描逻辑（`scanJobHandlerMethod`）有三层剪枝，值得照抄到自研框架里：

```java
// 2.1、skip by BeanDefinition:
//      - skip excluded-package bean
//      - skip lazy-init bean
if (applicationContext instanceof BeanDefinitionRegistry beanDefinitionRegistry) {
    if (!beanDefinitionRegistry.containsBeanDefinition(beanName)) { continue; }
    BeanDefinition beanDefinition = beanDefinitionRegistry.getBeanDefinition(beanName);
    String beanClassName = beanDefinition.getBeanClassName();
    if (isExcluded(excludedPackageList, beanClassName)) { continue; }
    if (beanDefinition.isLazyInit()) { continue; }
}

// 2.2、skip by BeanDefinition Class
Class<?> beanClass = applicationContext.getType(beanName, false);
if (beanClass == null) { continue; }
Map<Method, XxlJob> annotatedMethods = MethodIntrospector.selectMethods(beanClass, ...);
if (annotatedMethods==null || annotatedMethods.isEmpty()) { continue; }

// 2.3、scan + registry Jobhandler
Object jobBean = applicationContext.getBean(beanName);
for (Map.Entry<Method, XxlJob> jobMethodEntry : annotatedMethods.entrySet()) {
    registryJobHandler(jobMethodEntry.getValue(), jobBean, jobMethodEntry.getKey());
}
```

- 默认排除 `org.springframework.`、`spring.` 两个包前缀，可用 `excludedPackage` 覆盖；
- 跳过 lazy-init bean（避免为找 handler 而提前触发初始化）；
- 用 `MethodIntrospector` + `AnnotatedElementUtils.findMergedAnnotation` 而非简单反射，因此支持注解的元注解与组合注解。

注册时还会解析 `@XxlJob(init = "...")` 与 `@XxlJob(destroy = "...")` 两个方法名，绑定到 `MethodJobHandler`：

```java
if (StringTool.isNotBlank(xxlJob.init())) {
    initMethod = clazz.getDeclaredMethod(xxlJob.init());
    initMethod.setAccessible(true);
}
if (StringTool.isNotBlank(xxlJob.destroy())) { ... }
registryJobHandler(name, new MethodJobHandler(bean, executeMethod, initMethod, destroyMethod));
```

handler 名冲突会**直接抛异常**（`jobhandler[xxx] naming conflicts.`），不是覆盖。BEAN 模式下被注释掉的旧校验（参数必须是 `String`、返回必须是 `ReturnT`）在 3.5.0 已完全放开，任意无参方法均可。

## Startup Chain

```java
public void start() throws Exception {

    // valid enabled
    if (!enabled) { return; }

    // valid param
    if (StringTool.isBlank(adminAddresses)) { throw new RuntimeException("xxl-job executor adminAddresses empty."); }
    if (StringTool.isBlank(appname))        { throw new RuntimeException("xxl-job executor appname empty."); }
    if (StringTool.isBlank(accessToken))    { throw new RuntimeException("xxl-job executor accessToken empty."); }

    // bind instance
    xxlJobExecutor = this;

    // init logpath
    XxlJobFileAppender.initLogPath(logPath);

    // init invoker, admin-client
    initAdminBizList();

    // 1、init JobLogFileCleanThread
    jobLogFileCleanThreadHelper = new JobLogFileCleanThreadHelper();
    jobLogFileCleanThreadHelper.start(logRetentionDays);

    // 2、init TriggerCallbackThread
    triggerCallbackThreadHelper = new TriggerCallbackThreadHelper();
    triggerCallbackThreadHelper.start(this);

    // 3、EmbedServer + ExecutorRegistryThreadHelper
    executorRegistryThreadHelper = new ExecutorRegistryThreadHelper();
    startEmbedServer();
}
```

顺序上两处值得注意：

- **`accessToken` 从 3.5.0 起是必填项**，空值直接抛异常启动失败（旧版只在 `startEmbedServer` 里打 warn）。这是"AccessToken 执行器维度隔离"带来的强约束。
- **回调线程在 Netty 服务之前启动**，确保第一波任务执行结果就有通道回传，不会因时序丢回调。

`initAdminBizList` 把 `adminAddresses`（逗号分隔）逐个构造成声明式 HTTP 客户端：

```java
String finalAddress = address.trim();
finalAddress = finalAddress.endsWith("/") ? (finalAddress + "api") : (finalAddress + "/api");
int finalTimeout = (timeout >=1 && timeout <= 10) ? timeout : 3;

AdminBiz adminBiz = HttpTool.createClient()
        .url(finalAddress)
        .connectTimeout(finalTimeout * 1000)
        .readTimeout(finalTimeout * 1000)
        .header(Const.XXL_JOB_ACCESS_TOKEN, accessToken)
        .header(Const.XXL_JOB_APPNAME, appname)
        .proxy(AdminBiz.class);
```

3.5.0 已不再使用自研 xxl-rpc，改为 `xxl-tool` 的 `HttpTool` 动态代理：接口 + 注解即客户端，`AdminBiz` / `AdminJobBiz` / `ExecutorBiz` 三端共用同一套机制。超时合法区间 1~10s，越界回落 3s。

### Port and Address

```java
this.port = this.port>0?this.port: IPTool.getAvailablePort(9999);
this.ip = StringTool.isNotBlank(this.ip) ? this.ip : IPTool.getIp();

if (StringTool.isBlank(this.address)) {
    String ip_port_address = IPTool.toAddressString(ip, port);
    this.address = "http://{ip_port}/".replace("{ip_port}", ip_port_address);
}
```

端口默认 9999，**被占用时自动向后探测可用端口**（`getAvailablePort`），因此同一台机器跑多个执行器不需要手工改端口。注册地址默认是 `http://ip:port/`，可显式指定 `address` 覆盖（容器/NAT 场景常用）。

## Embed Server

```java
EventLoopGroup bossGroup = new NioEventLoopGroup();
EventLoopGroup workerGroup = new NioEventLoopGroup();
ThreadPoolExecutor bizThreadPool = new ThreadPoolExecutor(
        0, 200, 60L, TimeUnit.SECONDS,
        new LinkedBlockingQueue<Runnable>(2000),
        new ThreadFactory() { ... },
        new RejectedExecutionHandler() {
            public void rejectedExecution(Runnable r, ThreadPoolExecutor executor) {
                throw new RuntimeException("xxl-job, EmbedServer bizThreadPool is EXHAUSTED!");
            }
        });

ServerBootstrap bootstrap = new ServerBootstrap();
bootstrap.group(bossGroup, workerGroup)
        .channel(NioServerSocketChannel.class)
        .childHandler(new ChannelInitializer<SocketChannel>() {
            public void initChannel(SocketChannel channel) throws Exception {
                channel.pipeline()
                        .addLast(new IdleStateHandler(0, 0, 30 * 3, TimeUnit.SECONDS))  // beat 3N, close if idle
                        .addLast(new HttpServerCodec())
                        .addLast(new HttpObjectAggregator(5 * 1024 * 1024))             // merge request & reponse to FULL
                        .addLast(new EmbedHttpServerHandler(executorBiz, xxlJobExecutor, bizThreadPool));
            }
        })
        .childOption(ChannelOption.SO_KEEPALIVE, true);

ChannelFuture future = bootstrap.bind(xxlJobExecutor.getPort()).sync();
// start registry
xxlJobExecutor.getExecutorRegistryThreadHelper().start(xxlJobExecutor);
// wait util stop
future.channel().closeFuture().sync();
```

四个设计细节：

- `IdleStateHandler(0, 0, 30 * 3, SECONDS)`：**90 秒无读写即判空闲**，与 `DEAD_TIMEOUT` 对齐，`userEventTriggered` 里直接 `ctx.channel().close()`，避免半开连接堆积。
- `HttpObjectAggregator(5 * 1024 * 1024)`：聚合上限 5MB。GLUE 源码与大参数任务都走这条通道，超限直接拒绝。
- `bizThreadPool` 核心 0、最大 200、60s 回收、队列 2000，**拒绝策略是抛异常**（与调度中心的"记日志丢弃"相反）——执行器侧宁可让调度中心感知失败去重试，也不在本地无限堆积。
- 整个服务跑在 **daemon 线程**里：业务线程退出即 JVM 退出，不阻塞进程关闭。

注意注册线程是在 `bind` 成功之后才启动的——先保证端口真的监听了再对外宣称自己在线。

## Request Dispatch

```java
private Object dispatchRequest(HttpMethod httpMethod, String uri, String requestData, String accessToken, String appname) {
    // valid
    if (HttpMethod.POST != httpMethod) {
        return Response.ofFail("invalid request, HttpMethod not support.");
    }
    if (uri == null || uri.trim().isEmpty()) { ... }

    // valid access token
    if (StringTool.isBlank(accessToken) || StringTool.isBlank(appname)) {
        return Response.ofFail("invalid request, accessToken or appname is empty.");
    }
    if (!(accessToken.equals(xxlJobExecutor.getAccessToken())
            && appname.equals(xxlJobExecutor.getAppname()))) {
        return Response.ofFail("invalid request, accessToken or appname invalid.");
    }

    // services mapping
    switch (uri) {
        case "/beat":     return executorBiz.beat();
        case "/idleBeat": return executorBiz.idleBeat(GsonTool.fromJson(requestData, IdleBeatRequest.class));
        case "/trigger":  return executorBiz.trigger(GsonTool.fromJson(requestData, TriggerRequest.class));
        case "/kill":     return executorBiz.kill(GsonTool.fromJson(requestData, KillRequest.class));
        case "/log":      return executorBiz.log(GsonTool.fromJson(requestData, LogRequest.class));
        default:          return Response.ofFail("invalid request, uri-mapping(" + uri + ") not found.");
    }
}
```

3.5.0 的两处加固：只接受 **POST**；鉴权要求 **token 与 appname 同时匹配**（旧版只校验 token，任一执行器拿到 token 就能冒充同集群其它 appname）。鉴权失败返回的是业务失败码而非 HTTP 401，错误原因写在响应体里。

处理全部丢进 `bizThreadPool`，Netty IO 线程不执行业务。

## ExecutorBizImpl

三个简单接口：

```java
@Override
public Response<String> beat() {
    return Response.ofSuccess();
}

@Override
public Response<String> idleBeat(IdleBeatRequest idleBeatRequest) {
    boolean isRunningOrHasQueue = false;
    JobThread jobThread = XxlJobExecutor.getInstance().loadJobThread(idleBeatRequest.getJobId());
    if (jobThread != null && jobThread.isRunningOrHasQueue()) { isRunningOrHasQueue = true; }
    return isRunningOrHasQueue
            ? Response.ofFail("job thread is running or has trigger queue.")
            : Response.ofSuccess();
}

@Override
public Response<String> kill(KillRequest killRequest) {
    JobThread jobThread = XxlJobExecutor.getInstance().loadJobThread(killRequest.getJobId());
    if (jobThread != null) {
        XxlJobExecutor.getInstance().removeJobThread(killRequest.getJobId(), "scheduling center kill job.");
        return Response.ofSuccess();
    }
    return Response.ofSuccess("job thread already killed.");
}
```

`idleBeat` 是 `BUSYOVER` 路由的数据源，判定条件是"正在跑 **或** 队列非空"（`running || !triggerQueue.isEmpty()`）——只要还有活没干完就算忙。`kill` 是移除整条 `JobThread`（不是中断单次执行），队列里未跑的触发会被标记失败回调，细节见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)。

`/log` 从本地磁盘按行读取日志文件：

```java
public Response<LogData> log(LogRequest logRequest) {
    String logFileName = XxlJobFileAppender.makeLogFileName(new Date(logRequest.getLogDateTime()), logRequest.getLogId());
    LogData logResult = XxlJobFileAppender.readLog(logFileName, logRequest.getFromLineNum());
    return Response.ofSuccess(logResult);
}
```

日志文件名是 `logPath/yyyy-MM-dd/{logId}.log`，由 `logDateTime` 与 `logId` 共同决定——这也是为什么 `TriggerRequest` 必须带 `logDateTime`（而不是只用 logId）。

`trigger()` 的 handler 装载与阻塞判定见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)，GLUE 分支见 [GLUE](/docs/CS/Framework/Job/xxl-job/GLUE.md)，此处不重复。

## Callback

执行结果经 `TriggerCallbackThreadHelper` 异步回传：

```java
callbackMessageQueue = new MessageQueue<CallbackData>(
        "TriggerCallbackThreadHelper#callbackMessageQueue",
        messages -> doCallback(messages, xxlJobExecutor),
        1,      // 1s
        50);    // 50 条
```

3.5.0 把原来无界阻塞队列换成 `MessageQueue`：**攒够 50 条或满 1s 触发一次批量回调**，把 N 次 HTTP 压成 1 次。队列满时 `pushCallBack` 降级为同步直发：

```java
public void pushCallBack(CallbackData callback){
    if (!callbackMessageQueue.produce(callback)) {
        doCallback(new ArrayList<>(Collections.singletonList(callback)), XxlJobExecutor.getInstance());
    }
}
```

### Failover to Disk

```java
private void doCallback(List<CallbackData> callbackDataList, final XxlJobExecutor xxlJobExecutor){
    boolean callbackRet = false;
    for (AdminBiz adminBiz: xxlJobExecutor.getAdminBizList()) {
        try {
            Response<String> callbackResult = adminBiz.callback(new CallbackRequest(callbackDataList));
            if (callbackResult!=null && callbackResult.isSuccess()) {
                appendCallbackResult(callbackDataList, "<br>----------- xxl-job job callback finish.");
                callbackRet = true;
                break;
            }
        } catch (Throwable e) { ... }
    }
    // write callback-file, will retry later
    if (!callbackRet) {
        writeCallbackLog(callbackDataList);
    }
}
```

所有调度中心地址都失败时，回调参数**落本地磁盘**（`logPath/callbacklogs/xxl-job-callback-{md5}.log`，文件名带内容 MD5 天然去重），由 `retryCallbackThread` 每 30s 扫目录重读重发，成功后删除文件。这是"调度中心整体宕机也不丢执行结果"的兜底，代价是执行器本地多了一份待同步状态、且要求日志目录可写。

## Shutdown

```java
public void destroy(){
    // 1、destroy executor-server
    stopEmbedServer();

    if (MapTool.isNotEmpty(jobThreadRepository)) {
        // 1.1、elegant shutdown wait job finish
        TimeUnit.SECONDS.sleep(Const.ELEGANT_SHUTDOWN_WAITING_SECONDS);   // 5s

        // 1.2、interupt all job-thread
        for (Map.Entry<Integer, JobThread> item: jobThreadRepository.entrySet()) {
            JobThread oldJobThread = removeJobThread(item.getKey(), "web container destroy and kill the job.");
            if (oldJobThread != null) {
                oldJobThread.join();    // wait for job thread push result to callback queue
            }
        }
        jobThreadRepository.clear();
    }
    jobHandlerRepository.clear();

    // 2、destroy TriggerCallbackThread
    triggerCallbackThreadHelper.stop();
    // 3、destroy JobLogFileCleanThread
    jobLogFileCleanThreadHelper.stop();
}
```

停机顺序是"先停止接收新任务（`stopEmbedServer` 同时会 `registryRemove` 摘除自己）→ 等 5s（`ELEGANT_SHUTDOWN_WAITING_SECONDS`）→ 逐条 `join` 等已收任务跑完并把结果推入回调队列 → 关闭回调线程"。

注意 `join()` 之后才停回调线程，保证已完成任务的结果有机会发出去；但 `join` 无超时，长任务仍可能卡住 JVM 退出。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)
- [OpenAPI](/docs/CS/Framework/Job/xxl-job/OpenAPI.md)
- [Log And Alarm](/docs/CS/Framework/Job/xxl-job/Log_And_Alarm.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
