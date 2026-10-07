## Introduction

[Spring AMQP](https://spring.io/projects/spring-amqp) 是把 AMQP 协议（实践中几乎总是 [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)）接入 Spring 编程模型的整合层，核心项目 `spring-amqp` 加上 RabbitMQ 特化的 `spring-rabbit`。

它做的事可以概括成三点：把连接管理交给容器、把消息收发抽象成模板与注解、把拓扑（交换机/队列/绑定）声明纳入 Bean 生命周期。

> [!NOTE]
> **分工**：本文讲 Spring 侧的编程模型；AMQP 协议本身、RabbitMQ 的交换机类型、集群、镜像队列、Quorum Queue 等 broker 侧知识见 [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)。若要做"多系统之间的路由编排"（转换、聚合、拆分），则应看 [Spring Integration](/docs/CS/Framework/Spring/Integration.md)——它的 AMQP 适配器就建立在本文这套 API 之上。

### Version Baseline

Spring AMQP **4.0.0**（2025-11-19 GA）是 Boot 4 / Framework 7 一代的配套版本，改动集中在：支持 Jackson 3（并弃用所有 Jackson 2 组件）、JSpecify 空安全、迁移到 Spring Core Retry、新增面向 AMQP 1.0 协议的客户端模块。

## Three-Layer Abstraction

Spring AMQP 的整个 API 围绕三个角色展开：

| 角色 | 实现 | 职责 |
| ---- | ---- | ---- |
| 连接 | `ConnectionFactory`（通常是 `CachingConnectionFactory`） | 管理 TCP 连接与 channel，带池化语义 |
| 管理 | `RabbitAdmin` | 在容器启动时**声明**交换机、队列、绑定 |
| 发送 | `RabbitTemplate` | 把 Java 对象转成 `Message` 并发出 |
| 接收 | `MessageListenerContainer` + `@RabbitListener` | 拉取消息、反转换、调用业务方法、决定 ack |

引入 `spring-boot-starter-amqp` 后这几样都会被自动装配，业务代码通常只需要写 `@RabbitListener` 方法与发消息的调用。

## Declarative Topology

不需要在管理台手搓队列，也不需要往应用里塞执行 DDL 的启动脚本——把拓扑声明成 Bean，`RabbitAdmin` 会在连接建立后自动比对并创建缺失的部分：

```java
@Configuration
class OrderTopology {

    @Bean
    Queue orderQueue() {
        return QueueBuilder.durable("order.created")
            .deadLetterExchange("order.dlx")
            .ttl(60_000)
            .build();
    }

    @Bean
    TopicExchange orderExchange() {
        return ExchangeBuilder.topicExchange("order.exchange").durable(true).build();
    }

    @Bean
    Binding orderBinding(Queue orderQueue, TopicExchange orderExchange) {
        return BindingBuilder.bind(orderQueue).to(orderExchange).with("order.created.#");
    }
}
```

这带来两个好处：**幂等**（重复部署不会报错，只会跳过已存在的部分）与**版本化**（拓扑随代码走，环境间不会漂移）。

> [!WARNING]
> 自动声明只在队列**不存在**时生效。已存在的队列若参数不同（如多了 TTL、换了 DLX），RabbitMQ 会报 `PRECONDITION_FAILED`，而 Spring AMQP 不会自动改名重建（那等于丢消息）。改队列参数需要走手工迁移或新建队列 + 灰度切换。

## Sending

```java
@Service
class OrderPublisher {

    private final RabbitTemplate rabbitTemplate;

    OrderPublisher(RabbitTemplate rabbitTemplate) {
        this.rabbitTemplate = rabbitTemplate;
    }

    void publish(OrderCreated event) {
        rabbitTemplate.convertAndSend("order.exchange", "order.created.v1", event, m -> {
            m.getMessageProperties().setHeader("traceId", TraceContext.current());
            m.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
            return m;
        });
    }
}
```

`convertAndSend` 会自动套用 `MessageConverter`（默认 `SimpleMessageConverter`）。返回发出后 Broker 的确认见「可靠性」节。

## Receiving

```java
@Component
class OrderListener {

    @RabbitListener(queues = "order.created", concurrency = "3-10")
    void handle(OrderCreated event, @Header("amqp_receivedRoutingKey") String routingKey) {
        orderService.apply(event);
    }
}
```

`@RabbitListener` 背后的机制是：Spring 扫描到注解 → `RabbitListenerContainerFactory`（默认 `SimpleRabbitListenerContainerFactory`）创建一个 `MessageListenerContainer` → 容器按配置的并发数拉取消息 → 用 `MessageConverter` 把 payload 转成方法参数类型 → 调用方法 → 根据是否抛异常决定 ack。

方法签名可以自由组合 `@Payload`、`@Header`（含 `AmqpHeaders` 常量）、`Channel`（MANUAL ack 用）、`Message` 本身。返回值若不为空且原消息带了 `replyTo`，会被自动当作 RPC reply 发回去。

## Message Conversion

默认 `SimpleMessageConverter` 只处理 `String`、`Serializable`、byte[]——跨语言、可读性、兼容性都不好。生产几乎总是换成 JSON。

> [!WARNING]
> **Jackson 3 迁移使这套类名在 4.0 全部改名**（遵循整个 Spring 组合房的统一约定：去掉中间那个 `2`）。旧的 Jackson 2 类仍可用但已标记 `for removal`：

| Jackson 2（4.0 弃用） | Jackson 3（4.0 起） |
| ---- | ---- |
| `Jackson2JsonMessageConverter` | `JacksonJsonMessageConverter` |
| `Jackson2XmlMessageConverter` | `JacksonXmlMessageConverter` |
| `AbstractJackson2MessageConverter` | `AbstractJacksonMessageConverter` |
| `Jackson2JavaTypeMapper` | `JacksonJavaTypeMapper` |
| `DefaultJackson2JavaTypeMapper` | `DefaultJacksonJavaTypeMapper` |
| `JacksonUtils` | 直接用 Jackson 3 的 `JsonMapper.builder()` |
| `ProjectingMessageConverter` | `JacksonProjectingMessageConverter` |

```java
@Bean
MessageConverter jsonMessageConverter() {
    return new JacksonJsonMessageConverter();
}
```

### Pitfalls of Type Mapping

JSON 本身不携带目标类型，JSON 转换器靠消息头里的 `__TypeId__` 判断要反序列化成哪个类。这意味着**只要发送方被诱导带上一个 `__TypeId__`，接收方就可能去实例化任意类**——一条可利用的反序列化链。

因此生产环境务必配 allowed list：

```java
@Bean
MessageConverter jsonMessageConverter() {
    JacksonJsonMessageConverter converter = new JacksonJsonMessageConverter();
    DefaultJacksonJavaTypeMapper mapper = new DefaultJacksonJavaTypeMapper();
    mapper.setIdClassMapping(Map.of("orderCreated", OrderCreated.class));
    converter.setJavaTypeMapper(mapper);
    return converter;
}
```

> [!NOTE]
> **跨服务升级的兼容风险**：Jackson 3 的默认行为与 Jackson 2 不同（日期输出 ISO-8601 字符串、属性按字母序、转义策略调整），且包名从 `com.fasterxml.jackson` 变为 `tools.jackson`。**生产者与消费者往往不会同时升级**：若生产者先升级而消费者还是 Jackson 2，落在 broker 里的报文就已经是新格式。灰度期建议在消息契约里显式约定日期格式与数值精度，或让契约字段用字符串 / epoch 毫秒而非依赖 `Date`、`Instant` 的默认序列化结果。

## Reliability

### Producer Side

光调 `convertAndSend` 只能确认"写进了 socket"，不能确认 broker 收到。开启确认需要：

```yaml
spring:
  rabbitmq:
    publisher-confirm-type: correlated   # 确认到达 exchange
    publisher-returns: true              # 确认被路由到队列
    template:
      mandatory: true                    # 无法路由时退回而非静默丢弃
```

- **confirm**：消息是否抵达 exchange（不保证进队列）；
- **return**：消息从 exchange 无法路由到任何队列时回调；未开 `mandatory` 的不可路由消息会被**静默丢弃**——这是消息队列丢消息的经典原因之一。

### Consumer Side

`AcknowledgeMode` 决定处理失败时的行为：

| 模式 | 语义 | 适用 |
| ---- | ---- | ---- |
| `AUTO`（默认） | 方法正常返回则 ack；抛异常则 nack 并 requeue | 大多数场景 |
| `MANUAL` | 业务代码显式调用 `basicAck` / `basicNack` | 需要把 ack 与业务事务绑在一起、或批量 ack |
| `NONE` | 投递即视为已消费 | 允许丢消息的统计类场景 |

### Retry and Dead Letter

`AUTO` 模式下抛异常会导致 requeue，若业务异常是确定性的（如参数非法、下游记录不存在），结果就是**无限 requeue 死循环**，把整个队列堵住。标准做法是：有限重试耗尽后不再回队，让消息转入死信队列。

```java
@RabbitListener(queues = "order.created")
void handle(OrderCreated event) {
    try {
        orderService.apply(event);
    } catch (TransientException e) {
        throw e;                                        // 偶发失败：requeue 重试
    } catch (Exception e) {
        log.error("poison message", e);
        throw new AmqpRejectAndDontRequeueException(e); // 确定性失败：不回队，进 DLX
    }
}
```

`AmqpRejectAndDontRequeueException` 是 Spring AMQP 用来表达"别再给我了"的信号；队列预先配好 `x-dead-letter-exchange` 后，消息就会落到死信队列等待人工排查。

> [!TIP]
> 4.0 起重试相关的 API 已从 `spring-retry` 迁到 **Spring Core Retry**（`org.springframework.core.retry`），与 Integration 7、Kafka 4 保持一致。自定义 `RetryOperationsInterceptor` 时需要改 import。

## Concurrency and Batching

```yaml
spring:
  rabbitmq:
    listener:
      simple:
        concurrency: 3            # 起始消费者数
        max-concurrency: 10       # 上限
        prefetch: 50              # 每个消费者未 ack 的最大条数
        batch-size: 100           # 批量投递
```

- `prefetch` 是防止单个消费者囤积过多消息的关键参数；不设的话 broker 会一次性把所有消息推给第一个连上的消费者，造成严重的**消费倾斜**。
- 批量监听（`@RabbitListener` 方法接收 `List<X>`）能显著提升吞吐，但要留意：**批量 ack 意味着整批共用成功/失败结果**，需要业务能容忍重放。

## Transactions

`RabbitTransactionManager` 可以让发送/消费参与 Spring 的事务管理。但必须清楚它的边界：

> [!WARNING]
> Rabbit 事务与数据库事务**不构成真正的分布式事务**。二者组合时是 best-effort 1PC——先提交一个再提交另一个，中间的崩溃窗口会导致数据不一致（典型的"数据库回滚了但消息已发出"）。
> 正确解法不是找 2PC，而是改用**本地消息表 / outbox 模式**：业务数据与待发消息在同一个数据库事务里落库，由独立的投递任务取出发送，消费端则靠幂等去重。这类"至少一次 + 幂等"的组合才是实践中唯一可行的形态。事务本身见 [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)。

## Changes in 4.x

| 变更 | 说明 |
| ---- | ---- |
| Jackson 3 | 转换器与类型映射器全部改名（见上文对照表），Jackson 2 组件标记 `for removal` |
| `spring-rabbitmq-client` 模块（4.0 新增） | 基于 ProtonJ 支持 **AMQP 1.0 协议**与 RabbitMQ 交互，面向非 0-9-1 的场景 |
| `spring-amqp-client` 模块（4.1 新增） | 泛化的 AMQP 1.0 客户端，无任何 RabbitMQ 依赖，可与其它 broker 互通 |
| 空安全 | JSpecify 注解取代零散的 JSR-305 |
| 重试 | `spring-retry` → Spring Core Retry |
| 节点定位 | `RestTemplateNodeLocator` 在 4.2 被 `RestClientNodeLocator` 取代（因 `RestTemplate` 在 Framework 7.1 弃用） |
| 包迁移 | 4.1 起 `listener.adapter` 等组件迁至 Spring AMQP 自身的对应包 |

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)
- [Spring Integration](/docs/CS/Framework/Spring/Integration.md)
- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [MQ](/docs/CS/MQ/MQ.md)

## References

1. [Spring AMQP 4.0.0 Available（发布公告）](https://spring.io/blog/2025/11/19/spring-amqp-4-0-0-available)
2. [Spring AMQP Reference - What's New](https://docs.spring.io/spring-amqp/reference/whats-new.html)
3. [Spring AMQP 4.0 API — converter 包](https://docs.spring.io/spring-amqp/docs/4.0.2/api/org/springframework/amqp/support/converter/package-summary.html)
4. [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
