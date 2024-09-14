## Introduction

SchedulerX 是阿里巴巴自研的分布式任务调度平台（兼容开源 XXL-JOB/ElasticJob/Spring Schedule/K8s Job），支持 Cron 定时、一次性任务、工作流任务编排、分布式跑批，具有高可用、可视化、低延时等能力, 集成监控大盘、日志服务、短信报警等服务。

用户可以登录分布式任务调度平台管理定时调度任务、查询任务执行记录和运行日志，还可以通过工作流进行任务编排和数据传递。SchedulerX提供了简单、易用的分布式编程模型，通过几行代码就可以将海量数据分发到多台机器上执行





> 基于Akka?


## Architecture



server


configserver



高可用


安全防护

高性能


集成报警监控


可观测

支持eagleeye, skwaking



## 客户端接入

> https://www.alibabacloud.com/help/zh/schedulerx/getting-started/connect-an-agent-to-schedulerx/?spm=a2c63.p38356.0.0.38f57d87tuu7MI

编程模型

```java
// JavaProcessor
public void preProcess(JobContext context) throws Exception; （可选）
public ProcessResult process(JobContext context) throws Exception; (必选)
public void postProcess(JobContext context); （可选）
public void kill(JobContext context); （可选）

// MapJobProcessor
public ProcessResult process(JobContext context) throws Exception; (必选)
public void postProcess(JobContext context); （可选）
public void kill(JobContext context); （可选）
public ProcessResult map(List<? extends Object> taskList, String taskName); (必选

```



inject JobProcessor bean

```java
package com.aliyun.schedulerx.test.job;

import com.alibaba.schedulerx.worker.domain.JobContext;
import com.alibaba.schedulerx.worker.processor.JavaProcessor;
import com.alibaba.schedulerx.worker.processor.ProcessResult;

@Component
public class MyHelloJob extends JavaProcessor {

    @Override
    public ProcessResult process(JobContext context) throws Exception {
        System.out.println("hello schedulerx2.0");
        return new ProcessResult(true);
    }
}              
```
在应用管理页面查看实例总数。

如果实例总数为0，说明应用接入失败。请检查、修改本地应用。

如果实例总数不为0，显示接入的实例个数，说明应用接入成功。在操作列单击查看实例，即可在连接实例对话框中查看实例列表。


## 定时调度

- Crontab

支持Unix Crontab表达式，不支持秒级别调度。更多信息，请参见Cron。

- Fixed rate

Crontab必须被60整除，不支持其它数量级时间间隔的任务，例如cron不支持每隔40分钟运行一次的定时任务。Fixed rate专门用来做定期轮询，表达式简单，不支持秒级别调度。更多信息，请参见Fixed rate。

- Second delay

适用于对实时性要求比较高的业务，例如执行间隔为10秒的定时调度任务。Second delay支持秒级别调度。更多信息，请参见Second delay。

- One Time



日历

支持多种日历，您也可以自定义导入日历。常见的使用场景包括金融业务场景。例如，在每个交易日执行定时任务。

时区

适用于跨国业务，如需要在每个国家所在时区执行定时任务。

数据时间

SchedulerX可以处理具有数据状态的任务。创建任务时支持填写数据偏移。例如，某个任务是每天00:30运行，但实际上要处理上一天的数据，就可以向前偏移一个小时。运行时间不变，执行的时候通过context.getDataTime()获得的即为前一天23:30。
## 调度任务编排
支持可拖拽的工作流DAG（Directed Acyclic Graph）进行任务编排，操作简单，前端直接拖拽即可。详细的任务状态图能让您直观地查看并排查下游任务未执行的原因。



提供简单、易用的分布式编程模型，支持进行大数据批处理。

- 单机
  随机挑选一台机器执行。更多信息，请参见单机。
- 广播
  所有机器同时执行且等待全部结束。更多信息，请参见广播。

### MapReduce


MapReduce模型是SchedulerX自主研发的轻量级分布式跑批模型。通过MapJobProcessor或MapReduceJobProcessor接口将接入的Worker组成分布式计算引擎进行大数据跑批。相对于传统的大数据跑批（例如Hadoop、Spark等），MapReduce无需将数据导入大数据平台，且无额外存储及计算成本，即可实现秒级别海量数据处理，具有成本低、速度快、编程简单等特性。

MapReduce模型是Map模型的扩展，废弃了postProcess方法，新增了Reduce接口。所有子任务完成后会执行Reduce方法，可以在Reduce方法中返回该任务实例的执行结果或者回调业务。



**注意事项**

- 单个子任务的大小不能超过64 KB。
- ProcessResult的result返回值不能超过1000 Byte。
- 如果使用reduce，所有子任务结果会缓存在Master节点，该情况对Master节点内存压力较大，建议子任务个数和result返回值不要太大。如果没有reduce需求，使用MapJobProcessor接口即可。
- SchedulerX不保证子任务绝对执行一次。在特殊条件下会failover，可能导致子任务重复执行，需要业务方自行实现幂等。



所有Worker节点的子任务执行完成后，会回调reduce方法。reduce由Master节点执行，一般用于数据聚合或通知下游，也可以用于工作流的上下游数据传递。

reduce方法能处理所有子任务的结果。

1. 子任务通过`return ProcessResult(true, result)`返回结果（例如返回订单号）。
2. 执行reduce方法时，通过context获取所有子任务的状态（`context.getTaskStatuses()`）和结果（`context.getTaskResults()`），并进行相应的逻辑处理。

**分发策略**


- 轮询策略（默认）：每个Worker平均分配等量子任务，适用于每个子任务处理耗时基本一致的场景。
- WorkerLoad最优策略：由主节点自动感知Worker节点的负载情况，适用于子任务和Worker机器处理耗时有较大差异的场景。

子任务失败会自动重试，默认为0

**子任务分发方式**

- 推模型：每台机器平均分配子任务。
- 拉模型：每台机器主动拉取子任务，没有木桶效应，支持动态扩容拉取子任务。拉取过程中，所有子任务会缓存在Master节点，对内存有压力，建议子任务数不超过10,000。



cron、fix_rate不支持秒级别调度，您可以选择时间类型为second_delay，即上次跑完之后隔几秒再跑





分片运行

类似Elastic-Job模型，控制台配置分片参数，可以将分片平均分给多个客户端执行，支持多语言版本。更多信息，请参见多语言版本分片模型。

### 任务超时

不支持子任务级别的超时时间，只支持整个任务的超时，可以通过控制台动态修改

### 失败自动重试

- 实例失败自动重试

在任务管理的高级配置中，可以配置实例失败重试次数和重试间隔，例如，设置重试3次，每次间隔30秒。如果重试3次仍旧失败，该实例的状态才会变为失败，并发送报警。

- 子任务失败自动重试

如果是分布式任务（分片模型或MapReduce模型），子任务也支持失败自动重试和重试间隔，同样支持通过任务管理的高级配置进行配置。

### 限流

支持可抢占的任务优先级队列

多种流控手段

- 实例并发数

- 任务级别流控，表示一个任务同时最多运行多少个实例，默认为1，即上一次跑完才能跑下一次。

- 单机子任务并发数

分布式任务流控，可以控制每台机器同时运行子任务的数量。

全局子任务并发数

分布式任务流控，当机器数量较多时，单机子任务并发数流量比较大。分布式任务可以选择拉模型，所有计算节点向master节点拉取子任务，控制全局最多同时运行多少子任务。

任务优先级队列

应用级别的流控，一个应用同时最多运行多少个任务



## Log

schedulerx日志目录: `${user.home}/logs/schedulerx`

核心日志worker.log

## issues

某个时间点没有调度

可能原因:

- 某个单机任务有一个时间点没有调度运行时，您需要确认机器列表是否存在机器，并确认机器是否全部处于繁忙状态。如果不存在机器，请@机器人，按无可用机器或机器繁忙进行排查。
- 检查任务是否指定了机器，该机器已下线则无法调度.

如果是分钟级别的任务(间隔1分钟)没有执行, 很可能是SchedulerX服务端发布引起的, 一般这种场景对业务影响很小。



No worker available for
可能原因:

- 客户端配置导致
- 指定的worker下线

此时可登录worker查看scheduleX的worker.log



为什么实例停止之后还会执行

**问题现象：**

实例停止之后仍然执行。

**可能原因：**

- 任务实例停止后，SchedulerX会把Kill消息发送到客户端。
- 客户端接收到Kill消息后，会停止下发和停止执行未执行的子任务、销毁该实例的上下文、销毁实例所有的线程池。
- 对于已经在执行中的子任务不会被停止掉，只会中断对应的线程，所以子任务会继续运行直到结束。

**解决方案：**

- 一般情况下，您无需处理，等待子任务执行结束即可。
- 如果确实需要停止后立即结束所有运行中的任务，需要修改子任务处理逻辑，增加对当前线程Interrupt状态的处理。






one_time任务，跑完了在哪看历史记录

**说明:**

- **one_time任务，跑完会自动销毁，防止数据堆积，不保留任何历史记录。可以开启日志服务，可以保留最近2周所有任务的执行日志，方便排查问题。**


任务调度无法找到JobProcessor

**解决方案:**

1. 应用管理链接机器看启动方式，确保是spring或者springboot。
2. JobProcessor要注入为bean，比如加@Component注解。
3. 排查pom依赖如果依赖spring-boot-devtools 请排除掉。
4. 如果JobProcessor和process方法有aop注解，需要升级到最新版本SchedulerX客户端，低版本不支持aop。
5. 因为多加了一层代理，导致bean类型不匹配。可以把断点打到DefaultListableBeanFactory这个类，里面有个beanDefinitionNames成员变量，是spring注册的bean列表， 里面可以看到bean被什么切面代理了。比如有用户方间接引入一个巨坑的二方库导致，排除掉就好了。
6. 如果以上都不能解决，可以调试下ThreadContainer.start方法，如果是class.forName报错，class又确实存在，就是classLoader的问题，应该是业务方用了啥框架导致classLoader不一样。可以通过SchedulerxWorker.setClassLoader解决





Dispatcher.timeout submit appGroupId xxx

**原因:**

- 业务应用是有重启、fullgc、load偏高现象导致任务提交失败
- 客户端版本太低

**解决方案:**

- 配置任务失败重试
- 保证自己的应用实例正常
- 升级到最新版本



ClassNotFoundException

原因:

- Processor类路径不正确或者ClassLoader没有加载到

解决方案:

- 说明执行任务的worker上没有这个类，请确保java任务配置的Processor类名必须是**类的全路径**，
- 如果配置的jobProcessor类名正确，那就是worker上没这个类，一般是用户发错包了，或者这个应用还连了其他人的机器，可以自己登录worker机器，反编译看下



jobInstance=xxx don't update progress more than 60s

**可能原因:**

- worker的机器销毁、执行过程中产生bug, 导致worker长时间未同步任务执行状态到server

**解决方案:**

- 检查执行任务节点是否正常
- 升级到最新客户端版本

机器繁忙（all workers are busy）

可以通过应用管理->查看实例，看下是哪些worker繁忙了，然后点击“繁忙”，可以看到是哪个指标超过了阈值


jobInstance=xxx don't update progress more than 60s”

**可能原因:**

- worker的机器销毁、执行过程中产生bug, 导致worker长时间未同步任务执行状态到server

**解决方案:**

- 检查执行任务节点是否正常
- 升级到最新客户端版本


机器繁忙（all workers are busy）

可以通过应用管理->查看实例，看下是哪些worker繁忙了，然后点击“繁忙”，可以看到是哪个指标超过了阈值


java.lang.ExceptionInInitializerError

**原因**

- 在于icu4j这个包与当前jdk版本不匹配；

解决方案:（二选一）：

- 找到工程中icu4j.jar该jar包，确认其他第三方组件不需要该jar的话剔除它即可。
- 升级icu4j.jar到最新的版本。




task list is empty"

**原因:**

- map传入的任务列表为空

**解决方案:**

- 代码中判断子任务为空, 则正常结束job




force terminate instance by xx"

**说明:**

- 任务实例被强制停止. 可能是用户，也可能是系统。例如: 任务执行超时被强制停止。




result size more than 1000 bytes"

**原因:**

- ProcessResult中传入的result字符长度>1000

**解决方案:**

- 保证result字符长度<1000
- 升级到最新版本，字符长度超过1000时，会默认被截取




timeout dispatch return init error

**原因:**

- 子任务分发失败，并且重置任务状态也失败

**解决方案:**

- 升级client到最新版本(低版本bug较多)，重试任务




jobProcessor is null"

**原因:**

- 在spring context没有查找到class对应的bean(JobProcessor)

**解决方案:**

- 检查class是否存在该应用
- 集团内不推荐使用Spring Schdule任务类型






the response is not json object"

**说明:**

- HTTP请求后进行JSON反序列化失败

**原因:**

- HTTP url请求返回结果不是JSON格式数据。eg. 一些url访问需要鉴权 

**解决方案:**

- 通过curl验证url返回值是否符合预期




The returned value is different from the expected value"

**原因:**

- HTTP url请求返回结果和自定义结果不同

**解决方案:**

- 通过curl验证url返回值是否符合预期




A service call error occurred"

**原因:**

- HTTP url请求Reponse code和自定义response code不同

**解决方案:**

- 通过curl验证url返回值是否符合预期






worker not ready for running"

**原因:**

- server开始提交任务，但worker还未初始化成功

**解决方案:**

- 可配置任务失败重试


xx is still running!"

**原因:**

- server重复提交任务(eg.网络异常)

**解决方案:**

- 问题场景可忽略



**如何解决SchedulerX SDK日志文件输出**
正常情况下，SDK会输出上述章节描述的日志文件
**办法一：升级客户端版本（待发布）**
直接升级客户端版本至1.11.1，新的客户端版本已避免类似情况
**办法二：应用依赖排包**
在打包部署的模块搜索“log”关键词，进行排包处理
**●****Log4j2和Logback场景**
该场景是当前特别容易出现的情况，此时需要特别注意工程中是否存在log4j-to-slf4j这个jar包，如果它存在会出现日志文件无法输出问题
**排包方案（二选一）：**
1、继续保持两个日志组件同时存在，排除log4j-to-slf4j这个jar包
2、确定自己工程使用logback还是log4j2，仅保留一个组件排除另外的
排除logback：logback-classic、logback-core
排查log4j2: log4j-api 2.x.x 和 log4j-core 2.x.x

●仅log4j1场景
如果业务放采用了log4j1，且没有log4j2和logback，就要关注看下是否存在如下的log4j-over-slf4j这个jar包
**处理方案**：
1、继续使用log4j1，排除log4j-over-slf4j
2、添加一个log4j2或者logback



**办法三：添加日志配置**
该方法适合的冲突场景：Log4j2和Logback混合，且存在log4j-to-slf4j时。该场景下在业务应用的logback配置文件中添加如下配置信息



**如何排查任务失败的原因**
如果是单机任务，业务直接抛异常，可以在控制台上任务实例详情看到错误信息，如下图


如果没有抛异常，或者使用了分布式任务，专业版应用可以通过日志服务来排查（集团内暂不支持


## Links





## References

1. [阿里云 分布式任务调度](https://help.aliyun.com/zh/mse/user-guide/distributed-task-scheduling/?spm=a2c4g.11186623.0.0.32e1521b69TsR4)
