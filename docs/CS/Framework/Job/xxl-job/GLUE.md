## Introduction

GLUE 是 XXL-JOB 的"在线代码"能力：任务逻辑以源码形式存在调度中心（`xxl_job_info.glue_source`），触发时随请求下发到执行器，由执行器编译装载（Groovy）或落盘执行（脚本类）。业务代码迭代不再需要发版执行器。

本篇展开 GLUE 的两个分支（Groovy 与脚本）、版本比对与热替换机制、3.5.0 新增的执行器维度开关。任务执行载体 `JobThread` 见 [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)，请求分发见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)。

源码基线 tag `3.5.0`，核心类 `com.xxl.job.core.glue.GlueFactory`、`com.xxl.job.core.glue.GlueTypeEnum`、`com.xxl.job.core.handler.impl.ScriptJobHandler`。

## Glue Types

```java
public enum GlueTypeEnum {
    BEAN("BEAN", false, null, null),
    GLUE_GROOVY("GLUE(Java)", false, null, null),
    GLUE_SHELL("GLUE(Shell)", true, "bash", ".sh"),
    GLUE_PYTHON("GLUE(Python3)", true, "python3", ".py"),
    GLUE_PYTHON2("GLUE(Python2)", true, "python", ".py"),
    GLUE_NODEJS("GLUE(Nodejs)", true, "node", ".js"),
    GLUE_POWERSHELL("GLUE(PowerShell)", true, "pwsh", ".ps1"),
    GLUE_PHP("GLUE(PHP)", true, "php", ".php");
    ...
}
```

四个字段分别是 `desc`（展示名）、`isScript`（是否脚本类）、`cmd`（解释器命令）、`suffix`（落盘文件后缀）。`BEAN` 与 `GLUE_GROOVY` 的 `isScript = false`——前者是执行器本地方法，后者是 JVM 内装载。

> [!NOTE]
>
> `GLUE_POWERSHELL` 的命令是 **`pwsh`** 而非 `powershell`：3.4.2 起改用 PowerShell 7，执行器所在机器必须安装 PS 7.0+ 才能跑这类任务。3.4.2 之前用的是 `powershell`。

## Version Comparison and Hot Swap

GLUE 能否"改完立即生效"，取决于 `ExecutorBizImpl.trigger()` 里的版本比对。三种模式各有一套判据：

```java
// BEAN：比较 handler 实例引用
if (GlueTypeEnum.BEAN == glueTypeEnum) {
    IJobHandler newJobHandler = XxlJobExecutor.getInstance().loadJobHandler(triggerRequest.getExecutorHandler());
    if (jobThread != null && jobHandler != newJobHandler) {
        removeOldReason = "change jobhandler or glue type, and terminate the old job thread.";
        jobThread = null; jobHandler = null;
    }
}

// GLUE_GROOVY：比较 handler 类型 + glueUpdatetime
else if (GlueTypeEnum.GLUE_GROOVY == glueTypeEnum) {
    if (jobThread != null &&
            !(jobThread.getHandler() instanceof GlueJobHandler
                    && ((GlueJobHandler) jobThread.getHandler()).getGlueUpdatetime() == triggerRequest.getGlueUpdatetime())) {
        removeOldReason = "change job source or glue type, and terminate the old job thread.";
        jobThread = null; jobHandler = null;
    }
    if (jobHandler == null) {
        IJobHandler originJobHandler = GlueFactory.getInstance().loadNewInstance(triggerRequest.getGlueSource());
        jobHandler = new GlueJobHandler(originJobHandler, triggerRequest.getGlueUpdatetime());
    }
}

// 脚本类：比较 handler 类型 + glueUpdatetime
else if (glueTypeEnum != null && glueTypeEnum.isScript()) {
    if (jobThread != null &&
            !(jobThread.getHandler() instanceof ScriptJobHandler
                    && ((ScriptJobHandler) jobThread.getHandler()).getGlueUpdatetime() == triggerRequest.getGlueUpdatetime())) {
        removeOldReason = "change script or glue type, and terminate the old job thread.";
        jobThread = null; jobHandler = null;
    }
    if (jobHandler == null) {
        jobHandler = new ScriptJobHandler(jobId, glueUpdatetime, glueSource, glueType);
    }
}
```

统一结论：**`glueUpdatetime` 变了就 kill 旧 `JobThread` 重建**。这个时间戳由调度中心在保存 GLUE 源码时刷新，随 `TriggerRequest` 下发。

代价是热替换会中断正在跑的任务（旧线程被 `interrupt`，队列里未跑的触发回调失败 `[job not executed, in the job queue, killed.]`）。所以 GLUE 任务应当短小、可重入。

## Groovy Loading

```java
public class GlueFactory {
    private static GlueFactory glueFactory = new GlueFactory();

    public static void refreshInstance(int type){
        if (type == 0)      { glueFactory = new GlueFactory(); }
        else if (type == 1) { glueFactory = new SpringGlueFactory(); }
    }

    private final GroovyClassLoader groovyClassLoader = new GroovyClassLoader();
    private final ConcurrentMap<String, Class<?>> CLASS_CACHE = new ConcurrentHashMap<>();

    public IJobHandler loadNewInstance(String codeSource) throws Exception{
        if (StringTool.isNotBlank(codeSource)) {
            Class<?> clazz = getCodeSourceClass(codeSource);
            if (clazz != null) {
                Object instance = clazz.newInstance();
                if (instance instanceof IJobHandler) {
                    this.injectService(instance);
                    return (IJobHandler) instance;
                } else {
                    throw new IllegalArgumentException("... cannot convert from instance[" + instance.getClass() + "] to IJobHandler");
                }
            }
        }
        throw new IllegalArgumentException("... instance is null");
    }

    private Class<?> getCodeSourceClass(String codeSource){
        try {
            byte[] md5 = MessageDigest.getInstance("MD5").digest(codeSource.getBytes());
            String md5Str = new BigInteger(1, md5).toString(16);

            Class<?> clazz = CLASS_CACHE.get(md5Str);
            if (clazz == null) {
                clazz = groovyClassLoader.parseClass(codeSource);
                CLASS_CACHE.putIfAbsent(md5Str, clazz);
            }
            return clazz;
        } catch (Exception e) {
            return groovyClassLoader.parseClass(codeSource);
        }
    }
}
```

三个要点：

- **按源码 MD5 缓存 Class**：同一份代码只编译一次。缓存 key 是内容哈希而非 jobId，多任务共用同一份源码也只编译一次。
- **每次 `loadNewInstance` 都 `newInstance()`**，即**原型而非单例**：每次热替换都是全新实例。
- `SpringGlueFactory` 覆写 `injectService`，把 Spring 容器里的 bean 按 `@Resource` / `@Autowired` 注入到 GLUE 实例——所以 **GLUE(Java) 代码里能用业务 Spring bean**。`XxlJobSpringExecutor.afterSingletonsInstantiated()` 里的 `GlueFactory.refreshInstance(1)` 就是在切到 Spring 模式。

> [!WARNING]
>
> `GroovyClassLoader` 与 `CLASS_CACHE` 都是 `GlueFactory` 实例的成员，而 `glueFactory` 是静态字段。每次 GLUE 源码变更都会 `parseClass` 产生新 Class，**旧 Class 不会被卸载**——长期频繁修改 GLUE 代码会持续占用 Metaspace。生产环境高频改 GLUE 需关注 PermGen/Metaspace 增长。

## Script Execution

脚本类任务走"落盘 + fork 进程"：

```java
public ScriptJobHandler(int jobId, long glueUpdatetime, String gluesource, GlueTypeEnum glueType){
    ...
    // clean old script file
    File glueSrcPath = new File(XxlJobFileAppender.getGlueSrcPath());
    if (glueSrcPath.exists()) {
        for (File item : glueSrcPath.listFiles()) {
            if (item.getName().startsWith(jobId + "_")) {
                item.delete();      // 同 jobId 的旧脚本文件
            }
        }
    }
}

@Override
public void execute() throws Exception {
    // make script file
    String scriptFileName = XxlJobFileAppender.getGlueSrcPath()
            .concat(File.separator).concat(String.valueOf(jobId))
            .concat("_").concat(String.valueOf(glueUpdatetime))
            .concat(glueType.getSuffix());
    File scriptFile = new File(scriptFileName);
    if (!scriptFile.exists()) {
        ScriptUtil.markScriptFile(scriptFileName, gluesource);
    }

    // script params：0=param、1=分片序号、2=分片总数
    String[] scriptParams = new String[3];
    scriptParams[0] = jobParam != null ? jobParam : "";
    scriptParams[1] = String.valueOf(XxlJobContext.getXxlJobContext().getShardIndex());
    scriptParams[2] = String.valueOf(XxlJobContext.getXxlJobContext().getShardTotal());

    int exitValue = ScriptUtil.execToFile(cmd, scriptFileName, logFileName, scriptParams);

    if (exitValue == 0) { XxlJobHelper.handleSuccess(); }
    else { XxlJobHelper.handleFail("script exit value("+exitValue+") is failed"); }
}
```

- 脚本文件命名 `{jobId}_{glueUpdatetime}{suffix}`，落在 `logPath/gluesource/`；构造时先清掉同 jobId 的旧版本文件。
- 传给脚本的三个位置参数：**任务参数、分片序号、分片总数**。脚本里用 `$1` / `$2` / `$3`（或对应语言的 argv）取用，这是脚本任务支持分片广播的方式。
- 脚本的 stdout/stderr 直接追加到该次执行的日志文件，所以后台看到的"执行日志"就是脚本输出。
- 成功与否只看 **exit code**：`0` 成功，非 0 失败并带上退出码。

> [!NOTE]
>
> 脚本以执行器进程的子进程运行，用的是执行器的 OS 用户权限与环境 PATH。执行器机器缺 `python3` / `node` / `pwsh` 时，失败信息会体现为命令找不到（exit code 非 0），而不是调度或框架层面的报错。

## Glue Enabled Switch

3.5.0 新增执行器维度开关 `xxl.job.executor.glueenabled`（默认 true）。关闭后：

```java
// valid glue (non-BEAN) enabled
if (glueTypeEnum != null && GlueTypeEnum.BEAN != glueTypeEnum) {
    boolean glueEnabled = XxlJobExecutor.getInstance().getGlueEnabled();
    if (!glueEnabled) {
        logger.warn(">>>>>>>>>>> xxl-job executor not support current glue type[{}], please check executor configuration.", glueTypeEnum.getDesc());
        return Response.of(XxlJobContext.HANDLE_CODE_FAIL, "fail, current glue type ["+ glueTypeEnum.getDesc() +"] not supported.");
    }
}
```

判定在 handler 装载**之前**，即非 BEAN 类型的触发请求会被直接拒绝，连 `JobThread` 都不会建。用途是在安全敏感环境禁止执行器跑动态下发的代码——GLUE 本质是"远程代码执行"能力，这个开关是它的总闸。

## Version History

`xxl_job_logglue` 保存每次保存动作的历史版本（源码 + 备注 + 时间），当前版本在 `xxl_job_info.glue_source` + `glue_updatetime`。后台可回滚到任意历史版本，回滚动作同样是刷新 `glue_source` 与 `glue_updatetime`，从而触发执行器侧热替换。见 [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)。

## Comparison

| 维度 | BEAN | GLUE(Java) | 脚本类 |
| :--- | :--- | :--- | :--- |
| 代码存放 | 执行器 jar 内 | 调度中心 DB | 调度中心 DB |
| 修改是否需要发版 | 是 | 否 | 否 |
| 装载方式 | Spring 扫描 + 反射 | Groovy 编译 + 注入 | 落盘 + fork 进程 |
| 能否用 Spring bean | 能（本身就是 bean） | 能（`SpringGlueFactory` 注入） | 不能 |
| 分片参数获取 | `XxlJobHelper` | `XxlJobHelper` | 脚本 argv 第 2、3 位 |
| 每次触发开销 | 无 | 首次编译（之后走 MD5 缓存） | 每次 fork 进程 |
| 受 `glueenabled` 限制 | 否 | 是 | 是 |
| 适合场景 | 常规业务 | 需频繁调整的胶水逻辑 | 运维脚本、跨语言任务 |

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Log And Alarm](/docs/CS/Framework/Job/xxl-job/Log_And_Alarm.md)
- [OpenAPI](/docs/CS/Framework/Job/xxl-job/OpenAPI.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
