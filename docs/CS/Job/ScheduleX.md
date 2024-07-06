## Introduction

SchedulerX 是阿里巴巴自研的分布式任务调度平台（兼容开源 XXL-JOB/ElasticJob/Spring Schedule/K8s Job），支持 Cron 定时、一次性任务、工作流任务编排、分布式跑批，具有高可用、可视化、低延时等能力。
集成监控大盘、日志服务、短信报警等服务。

您可以登录分布式任务调度平台管理定时调度任务、查询任务执行记录和运行日志，还可以通过工作流进行任务编排和数据传递。SchedulerX提供了简单、易用的分布式编程模型，通过几行代码就可以将海量数据分发到多台机器上执行。您还可以选择通过钉钉、短信、电话等多种渠道接收任务的失败和超时报警。



> 基于Akka?

和其它开源产品对比

| **项目**     | **Quartz**                     | **Elastic-Job**                    | **XXL-JOB**                                | **SchedulerX**                                               |
| ------------ | ------------------------------ | ---------------------------------- | ------------------------------------------ | ------------------------------------------------------------ |
| 定时调度     | Cron                           | Cron                               | Cron                                       | Cron、Fixed_Delay、Fixed_Rate、One_Time、OpenAPI             |
| 任务编排     | 不支持                         | 不支持                             | 不支持                                     | 支持，可以通过图形化配置，并且任务间可传递数据               |
| 分布式跑批   | 不支持                         | 静态分片                           | 广播                                       | 广播、静态分片、MapReduce                                    |
| 多语言       | Java                           | Java、脚本任务                     | Java、Go、脚本任务                         | Java、Go、脚本任务、HTTP任务、K8s Job                        |
| 可观测       | 无                             | 弱，只能查看无法动态创建、修改任务 | 历史记录、运行日志（不支持搜索）、监控大盘 | 历史记录、运行日志（支持搜索）、监控大盘、操作记录、查看堆栈、链路追踪 |
| 可运维       | 无                             | 启用、禁用任务                     | 启用、禁用任务、手动运行任务、停止任务     | 启用、禁用任务、手动运行任务、停止任务、标记成功、重刷历史数据 |
| 报警监控     | 无                             | 邮件                               | 邮件                                       | 邮件、钉钉、飞书、企业微信、自定义WebHook、短信、电话        |
| 高可用及容灾 | 需要自己维护数据库的容灾       | 需要自己维护ZooKeeper的容灾        | 需要自己维护数据库和Server的容灾           | 默认支持同城多机房容灾                                       |
| 用户权限     | 无                             | 无                                 | 用户隔离，通过账号密码登录                 | 支持单点登录、主子账号、角色账号、RAM精细化权限管理          |
| 优雅下线     | 不支持                         | 不支持                             | 支持                                       | 支持                                                         |
| 灰度测试     | 不支持                         | 不支持                             | 不支持                                     | 支持                                                         |
| 性能         | 每次调度通过DB抢锁，对DB压力大 | ZooKeeper是性能瓶颈                | 由Master节点调度，Master节点压力大         | 可水平扩展，支持海量任务调度                                 |


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


### Java

```xml
<dependency>
  <groupId>com.aliyun.schedulerx</groupId>
  <artifactId>schedulerx2-spring-boot-starter</artifactId>
  <version>${schedulerx2.version}</version>
  <!--如果使用logback，需要将log4j和log4j2排除 -->
  <exclusions>
    <exclusion>
      <groupId>org.apache.logging.log4j</groupId>
      <artifactId>log4j-api</artifactId>
    </exclusion>
    <exclusion>
      <groupId>org.apache.logging.log4j</groupId>
      <artifactId>log4j-core</artifactId>
    </exclusion>
    <exclusion>
      <groupId>log4j</groupId>
      <artifactId>log4j</artifactId>
    </exclusion>
  </exclusions>
</dependency> 
```


```properties
spring.schedulerx2.endpoint=${endpoint}
spring.schedulerx2.namespace=${namespace}
spring.schedulerx2.groupId=${groupId}
# 1.2.1及以上版本设置appKey
spring.schedulerx2.appKey=${appKey}

# 1.2.1以下版本设置AK/SK，开启其他特殊配置（例如配置文件定义任务同步、Spring任务自动同步）也需要额外配置以下参数
#spring.schedulerx2.aliyunAccessKey=${aliyunAccessKey}
#spring.schedulerx2.aliyunSecretKey=${aliyunSecretKey}   
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
Crontab

支持Unix Crontab表达式，不支持秒级别调度。更多信息，请参见Cron。

Fixed rate

Crontab必须被60整除，不支持其它数量级时间间隔的任务，例如cron不支持每隔40分钟运行一次的定时任务。Fixed rate专门用来做定期轮询，表达式简单，不支持秒级别调度。更多信息，请参见Fixed rate。

Second delay

适用于对实时性要求比较高的业务，例如执行间隔为10秒的定时调度任务。Second delay支持秒级别调度。更多信息，请参见Second delay。

日历

支持多种日历，您也可以自定义导入日历。常见的使用场景包括金融业务场景。例如，在每个交易日执行定时任务。

时区

适用于跨国业务，如需要在每个国家所在时区执行定时任务。

数据时间

SchedulerX可以处理具有数据状态的任务。创建任务时支持填写数据偏移。例如，某个任务是每天00:30运行，但实际上要处理上一天的数据，就可以向前偏移一个小时。运行时间不变，执行的时候通过context.getDataTime()获得的即为前一天23:30。
## 调度任务编排
支持可拖拽的工作流DAG（Directed Acyclic Graph）进行任务编排，操作简单，前端直接拖拽即可。详细的任务状态图能让您直观地查看并排查下游任务未执行的原因。

## 分布式计算
提供简单、易用的分布式编程模型，支持进行大数据批处理。

单机

随机挑选一台机器执行。更多信息，请参见单机。

广播

所有机器同时执行且等待全部结束。更多信息，请参见广播。

Map模型

类似于Hadoop MapReduce里的Map。只要实现一个Map方法，简单几行代码就可以将海量数据分布式到多台机器上执行。更多信息，请参见Map模型。

MapReduce模型

MapReduce模型是Map模型的扩展，废弃了postProcess方法，新增了Reduce接口。所有子任务完成后会执行Reduce方法，可以在Reduce方法中返回该任务实例的执行结果或者回调业务。更多信息，请参见MapReduce模型。

分片运行

类似Elastic-Job模型，控制台配置分片参数，可以将分片平均分给多个客户端执行，支持多语言版本。更多信息，请参见多语言版本分片模型。

## 失败自动重试

实例失败自动重试

在任务管理的高级配置中，可以配置实例失败重试次数和重试间隔，例如，设置重试3次，每次间隔30秒。如果重试3次仍旧失败，该实例的状态才会变为失败，并发送报警。

子任务失败自动重试

如果是分布式任务（分片模型或MapReduce模型），子任务也支持失败自动重试和重试间隔，同样支持通过任务管理的高级配置进行配置。

多种流控手段
实例并发数

任务级别流控，表示一个任务同时最多运行多少个实例，默认为1，即上一次跑完才能跑下一次。

单机子任务并发数

分布式任务流控，可以控制每台机器同时运行子任务的数量。

全局子任务并发数

分布式任务流控，当机器数量较多时，单机子任务并发数流量比较大。分布式任务可以选择拉模型，所有计算节点向master节点拉取子任务，控制全局最多同时运行多少子任务。

任务优先级队列

应用级别的流控，一个应用同时最多运行多少个任务

## issues

no worker available for
可能原因
- 客户端配置导致
- 指定的worker下线

此时可登录worker查看scheduleX的log




## Links

