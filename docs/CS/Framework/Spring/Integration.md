## Introduction

[Spring Integration](https://spring.io/projects/spring-integration) 是 Spring 家族里的**企业集成（EIP，Enterprise Integration Patterns）实现**。它要解决的问题是：当一个应用需要与外部系统打交道（消息队列、文件系统、数据库、邮件、FTP/SMB、HTTP 回调、物联网协议），同时又要在这些交互之间做过滤、转换、路由、拆分、聚合时，代码极易退化成一堆互相耦合的胶水。

Spring Integration 提供一套统一的消息模型，把上述一切抽象成同一条流水线上的三类构件：**消息（Message）**、**通道（Channel）**、**端点（Endpoint）**。所有外部系统的差异被压缩在流水线两端的"适配器"里，中间的处理逻辑因此得以复用、测试和重排。

它经常与两个邻居被混淆，先划清边界：

| 项目 | 关注点 | 触发方式 | 数据形态 |
| ---- | ---- | ---- | ---- |
| Spring Integration | 系统之间的**连接与编排** | 事件/消息到达即触发 | 流式的、持续的 |
| [Spring Batch](/docs/CS/Framework/Spring/Batch.md) | 大批量数据的**分块处理** | 调度触发，有明确的起止 | 成批的、可枚举的 |
| Spring Cloud Stream | 微服务间的消息收发 | 监听 binder | 消息，但配置重于编排 |

一个常见的组合是：**外部文件到达 → Integration 的 file inbound adapter 感知 → 触发 Batch 的 Job → 处理结果经 Integration 的发件适配器投递出去**。二者是协作而非替代关系。

### 版本基线

Spring Integration **7.0.0**（2025-11-19 GA）是 Boot 4 / Framework 7 一代的配套版本。它建立在 Java 17 基线、Jakarta EE 11、Jackson 3 之上，并随整个 Spring 产品组合做了几处统一升级——其中 `spring-retry` → Spring Core Retry 的替换是**编译期breaking change**，见文末迁移表。

## 消息模型

一切的基础是 `Message<T>`，一个不可变的信封：

```java
public interface Message<T> {
    T getPayload();
    MessageHeaders getHeaders();
}
```

真正让集成变简单的是 **header 机制**：路由键、原始文件名、重试次数、关联 ID（correlationId）、序列号（sequenceNumber）等元数据全部挂在 header 上，**不污染业务 payload**。这样下游处理器可以只关心业务类型，而路由、聚合、幂等这些"环境信息"由框架沿着消息传递链一路携带。

> [!TIP]
> Message 是不可变的。任何"修改"消息的操作（如 `MessageBuilder.withPayload(...).copyHeaders(...).build()`）实际都是构造新实例，header 由 `MessageBuilder` 显式继承。这个约束让消息在多线程通道间传递时无需额外同步。

## 消息通道

通道是生产者与消费者之间的解耦点，类型决定了投递语义：

| 通道 | 语义 | 典型用途 |
| ---- | ---- | ---- |
| `DirectChannel` | **同一线程**内直接调用订阅者，默认通道类型 | 要求端到端在一个事务里、失败直接向上抛 |
| `QueueChannel` | 内部队列**缓冲**，消费端轮询拉取 | 削峰、解耦生产与消费速率 |
| `PublishSubscribeChannel` | 广播给**所有**订阅者 | 一条消息触发多个后续处理 |
| `ExecutorChannel` | 投递到线程池异步执行 | 提升吞吐；注意事务边界在此处断开 |
| `PriorityChannel` | 按优先级投递 | 消息有轻重缓急 |
| `RendezvousChannel` | 生产者阻塞直到有消费者接收 | 需要同步确认的场景 |

选错通道是集成代码最常见的性能与一致性问题。特别是：**把 `ExecutorChannel` 放进原本依赖 `DirectChannel` 单线程语义的链路，会静默丢掉事务边界**——前半段提交的事务不会因为后半段失败而回滚。

## 端点与 EIP 模式

端点负责把某个 EIP 模式接到通道上。核心组件：

| 组件 | 作用 | 失败时的典型行为 |
| ---- | ---- | ---- |
| `Transformer` | 转换 payload 或 header 的类型/形态 | 抛异常，消息进 error channel |
| `Filter` | 按条件丢弃消息；配 `discardChannel` 可保留被丢弃的 | 静默丢弃（默认） |
| `Router` | 按条件把消息分发到不同通道 | 无匹配通道时抛异常（可配 `defaultOutputChannel`） |
| `Splitter` | 把一条消息拆成多条 | — |
| `Aggregator` | 把多条消息聚合成一条（依赖 correlation + release strategy） | 超时未凑齐则超时分组 |
| `ServiceActivator` | 调用某个 Java 方法并把返回值作为输出消息 | 抛异常 |
| `Bridge` | 连接两条通道 | — |
| `ScatterGather` | 广播到多个下游并聚合结果 | 7.0 起完整支持 async（返回 `Mono`） |
| `Gateway` | 把消息交互暴露成普通 Java 接口调用 | — |

## IntegrationFlow DSL

老式 XML/注解配置已被 Java DSL 全面取代，现代写法是声明一个 `IntegrationFlow` Bean：

```java
@Configuration
class OrderIntegrationConfig {

    @Bean
    IntegrationFlow orderFlow() {
        return IntegrationFlow
            .from(FileInboundChannelAdapterSpec.inboundAdapter(new File("/data/inbox"))
                    .patternFilter("*.csv"),
                  p -> p.poller(Pollers.fixedDelay(5_000)))
            .<File, Order>transform(FileOrderTransformer::parse)
            .filter(Order::isValid, f -> f.discardChannel("discardChannel"))
            .split(Order::getItems)
            .handle(orderProcessor())          // ServiceActivator
            .aggregate()
            .handle(Amqp.outboundAdapter(rabbitTemplate).routingKey("orders"))
            .get();
    }
}
```

DSL 的价值在于：整条链路在一次链式调用里可见，重排、插入新处理环节、替换通道类型都只改一处。

## 与外部系统的连接

真正"接触到外界"的是通道适配器（Channel Adapter），按方向分两类：

- **inbound / inbound channel gateway**：从外部系统接收数据，送入 Messaging（如 `AmqpInboundChannelAdapter`、`FileReadingMessageSource`、`JdbcPollingChannelAdapter`、`MqttPahoInboundChannelAdapter`）；
- **outbound / outbound channel gateway**：把消息写出去（如 `AmqpOutboundEndpoint`、`FileWritingMessageHandler`、`MailSendingMessageHandler`）。

模块按外部技术拆分，需要哪个引哪个：`spring-integration-amqp`、`-jms`、`-kafka`、`-jdbc`、`-file`、`-ftp`、`-sftp`、`-smb`、`-http`、`-ws`、`-mqtt`、`-mail`、`-mongodb`、`-redis`、`-r2dbc`、`-zeromq` 等。

> [!NOTE]
> 7.0 起所有 Integration 模块统一了包结构：组件按其用途迁到 `input` 或 `output` 包下。升级时按编译报错逐个调整 import 即可。

## 错误处理

每条流程都有一个隐式的 **error channel**。流程内任何未被捕获的异常会被包装成 `ErrorMessage`（payload 是 `MessagingException`，原始消息藏在 header 里）投递进去。因此处理方式有两种：

```java
// 方式一：给错误通道挂一个订阅者，统一处理
@Bean
IntegrationFlow errorHandling() {
    return IntegrationFlow.from("errorChannel")
        .handle(m -> log.error("flow failed", m.getPayload()))
        .get();
}

// 方式二：在端点上直接指定错误通道
.handle(orderProcessor(), e -> e.advice(retryAdvice()))
```

### 重试

7.0 把重试实现从 `spring-retry` 迁移到了 **Spring Framework Core 的 retry API**（整个 Spring 组合房的统一演进）。常用mapping：

| 迁移前（spring-retry） | 迁移后 |
| ---- | ---- |
| `org.springframework.retry.support.RetryTemplate` | `org.springframework.core.retry.RetryTemplate` |
| `org.springframework.retry.RetryPolicy` | `org.springframework.core.retry.RetryPolicy` |
| `org.springframework.retry.backoff.BackOffPolicy` | `org.springframework.util.backoff.BackOff` |
| `org.springframework.retry.RecoveryCallback` | `org.springframework.integration.core.RecoveryCallback` |

有趣的是最后一项：Spring Framework Core 里没有 `RecoveryCallback` 抽象（官方认为在 `RetryException` 上用标准 try/catch 就够了），但 Integration 作为一个 DSL 编排框架，重试耗尽后的"后续动作"是一个需要显式占位的位置，因此自己保留了这个抽象。

配合重试的一等公民还有：

- **幂等接收器（Idempotent Receiver）**：按 messageId 去重，避免"处理成功但 ack 失败"导致的重复消费；
- **死信通道**：重试耗尽后投递到专门的通道而非丢弃，便于事后人工干预；
- **Claim Check**：payload 过大时先存进 `MessageStore`，链路上只传递引用。

## 消息存储

需要跨步骤持久化消息时用 `MessageStore`（JDBC、Redis、MongoDB 等实现），聚合器等待分组、队列持久化、Claim Check 都依赖它。

> [!WARNING]
> 7.0 把消息存储表的 `MESSAGE_BYTES` 列更名为 **`MESSAGE_CONTENT`**——因为某些实现的序列化结果并不总是 byte[]。存量库升级时这是一处必须手工执行的 DDL，否则聚合器/持久化队列会直接报列不存在。

## 分布式锁

7.0 新增 `DistributedLock` 抽象并支持 **TTL 选项**用途很直接：多个实例同时轮询同一个 FTP 目录或同一张待处理表时，谁先拿到锁谁处理，避免重复捞取。TTL 是这类锁的救命配置——没有 TTL，拿到锁的实例崩溃后锁会永久悬挂，整个任务再也不会被处理。

## 空安全

与 Framework 7 一致，7.0 用 **JSpecify** 注解（`org.jspecify.annotations`）暴露空安全 API，取代原先零散的 JSR-305 注解。构建期用 NullAway 校验这些声明的一致性。Kotlin 用户可以据此获得原生可空类型推断，不必再手动加 `!!`。

## 从 6.x 迁移到 7

| 变更 | 说明 |
| ---- | ---- |
| 依赖基线 | Spring Framework 7、Jackson 3、Java 17 |
| 重试实现 | `spring-retry` → Spring Core Retry（见上文映射表），需改 import |
| 空安全 | JSR-305 → JSpecify 注解 |
| 消息存储列 | `MESSAGE_BYTES` → `MESSAGE_CONTENT`（需手工 DDL） |
| 包结构 | 各模块组件按用途迁入 `input` / `output` 包 |
| AMQP 适配器 | 新增基于 Spring AMQP 4.0 的 **AMQP 1.0** 通道适配器 |
| 文件扫描目录 | `FileReadingMessageSource` 的待扫描目录可配为表达式，**每次扫描时实时求值**（原先需编程改Bean） |
| JDBC 适配器 | 新增 Java DSL 实现 |
| Scatter-Gather | 补齐 async 模式，返回结果可用 `Mono` |
| 分布式锁 | 新增 TTL 支持 |
| SMB 模块 | 升级到 JCIFS 3.0.0 |
| JUnit 4 | 相关支持组件已弃用 |

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Batch](/docs/CS/Framework/Spring/Batch.md)
- [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md)
- [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)
- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)

## References

1. [Spring Integration 7.0.0 Available（发布公告）](https://spring.io/blog/2025/11/19/spring-integration-7-0-0-released)
2. [Spring Integration Reference - What's New](https://docs.spring.io/spring-integration/reference/whats-new.html)
3. [Spring Integration 项目主页](https://spring.io/projects/spring-integration)
4. [Enterprise Integration Patterns](https://www.enterpriseintegrationpatterns.com/)
