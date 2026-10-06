## Introduction

Spring Cloud Stream 是构建消息驱动微服务的统一框架。它在应用与具体消息中间件之间加了一层抽象，让业务代码只面向"消息通道 / 绑定"编程，而底层到底是 Kafka、RabbitMQ、RocketMQ 还是 Kafka Streams，由可插拔的 **Binder** 决定，切换中间件通常只需换依赖和改配置，不必改业务代码。

它建立在 Spring Messaging（`Message`、`MessageChannel`）之上，从 3.x 起主推**函数式模型**（`java.util.function` 中的 `Supplier` / `Function` / `Consumer`），老的 `@StreamListener`、`@EnableBinding` 注解已被取代。

> [!NOTE]
> Spring Cloud Stream 5.0（2025.1 Oakwood）已迁移到 **Jackson 3**。同时，基于 Reactor Kafka 的 `spring-cloud-stream-binder-kafka-reactive` 因 Reactor Kafka 停止维护而被**移除**，需要响应式消费时改走 Kafka 原生 API 或 `spring-kafka` 自身的响应式支持。

## Binder

Binder 是 Stream 的核心 SPI，负责把应用层的抽象绑定到具体中间件：

- **Kafka Binder**：destination 映射为 Kafka topic，消费者组映射为 consumer group，分区映射为 partition。
- **RabbitMQ Binder**：destination 映射为 exchange / queue。
- **RocketMQ Binder**（[Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md) 提供）：映射为 topic 加 consumer group。
- **Kafka Streams Binder**：特殊的 binder，直接对接 Kafka Streams 的拓扑（`KStream` / `KTable`）。

Binder 负责消费者组、分区、offset、重试、死信队列等中间件相关细节，业务层保持中立。

需要多个中间件共存时（迁移期、桥接应用），可定义多个 binder 实例并按需指派：

```yaml
spring:
  cloud:
    stream:
      binders:
        kafka-binder:
          type: kafka
          environment:
            spring.cloud.stream.kafka.binder.brokers: kafka:9092
        rabbit-binder:
          type: rabbit
          environment:
            spring.rabbitmq.host: rabbit
      bindings:
        bridge-in-0:
          binder: kafka-binder
          destination: orders
        bridge-out-0:
          binder: rabbit-binder
          destination: orders-exchange
```

## Functional Model

框架按函数 Bean 的名字加上输入输出方向自动生成绑定，无需注解即可完成装配。

### Producer

等价于旧的 `MessageChannel#send`，用一个 `Supplier` 周期或按需产出消息：

```java
@Configuration
public class ProducerConfig {

    // 每 ~1s 发送一条消息，由 spring.cloud.stream.poller 控制频率
    @Bean
    public Supplier<Message<String>> toUppercase() {
        return () -> MessageBuilder.withPayload("hello").build();
    }
}
```

`Supplier` 是**轮询驱动**的，适合定时产出（如心跳、周期快照）。要在 HTTP 请求、定时任务等命令式代码里显式发送，用 `StreamBridge`：

```java
@Service
public class OrderService {

    private final StreamBridge streamBridge;

    public void placeOrder(Order order) {
        orderRepository.save(order);
        streamBridge.send("orderPlaced-out-0", new OrderPlacedEvent(order.getId()));
    }
}
```

`StreamBridge.send()` 的第一个参数可以是**绑定名**也可以是**目标名**（未注册的会按 destination 处理），返回 `boolean` 表示是否发送成功。

### Processor / Consumer

用 `Function`（一进一出，可链式组合）或 `Consumer`（只进不出）：

```java
@Bean
public Function<String, String> uppercase() {
    return s -> s.toUpperCase();
}

@Bean
public Consumer<String> logSink() {
    return s -> System.out.println("received: " + s);
}
```

多个函数用管道符串接：`spring.cloud.function.definition=toUppercase|uppercase|logSink`。

### 绑定命名规则

绑定名遵循 `<函数名>-<in|out>-<下标>`，下标从 0 起，多个输入输出依次递增：

| 函数形态 | 生成的绑定 |
| :-- | :-- |
| `Supplier<T>` | `<name>-out-0` |
| `Consumer<T>` | `<name>-in-0` |
| `Function<T,R>` | `<name>-in-0`、`<name>-out-0` |
| `Function<Tuple2<A,B>, Tuple2<C,D>>` | `<name>-in-0`、`-in-1`、`-out-0`、`-out-1` |

函数名由 Bean 名决定，可用 `@Bean("orderProcessor")` 显式指定。这是纯约定，**拼错一个字符不会报错，只会静默地绑定到一个新 destination 上**（通常表现为"消息发了但没人收"）。

### Binding 配置

```yaml
spring:
  cloud:
    function:
      definition: uppercase;logSink
    stream:
      bindings:
        uppercase-in-0:
          destination: orders
          group: order-service        # 消费者组
          content-type: application/json
          consumer:
            concurrency: 3
            max-attempts: 3
        uppercase-out-0:
          destination: orders-upper
          producer:
            partition-key-expression: headers['partitionKey']
            partition-count: 6
      kafka:
        binder:
          brokers: localhost:9092
```

`group` 是生产环境必配项。不配时框架每次启动创建**匿名消费者组**，从 `latest` 开始读——**服务停机期间的事件会永久丢失**，且 Kafka binder 下匿名组无法启用 DLQ。显式配了 group 后，新建组默认从 `earliest` 开始。

## 分区与顺序

Kafka 只保证分区内有序。要让同一订单的事件按序处理，必须让它们落到同一分区——通过消息键实现：

```java
Message<OrderPlacedEvent> msg = MessageBuilder
        .withPayload(event)
        .setHeader(KafkaHeaders.MESSAGE_KEY, event.orderId().getBytes())
        .build();
streamBridge.send("orderPlaced-out-0", msg);
```

生产者侧也可用 `partition-key-expression`（SpEL）从消息中提取分区键，配合 `partition-count` 声明分区数。注意 `partition-count` 只是**创建 topic 时的提示**：若 topic 已存在且分区数更小，而 `autoAddPartitions` 默认关闭，则**启动直接失败**。

## Reliability

### 重试与 max-attempts 的陷阱

这是 Kafka binder 下最容易踩的空转配置：

> **未启用 DLQ 时，`max-attempts` 完全不起作用。** 重试会回落到 spring-kafka 容器的默认行为，即 10 次重试。并且此时把 `max-attempts` 设为 1 **也不能**关闭重试。

也就是说，很多人以为配了 `max-attempts: 1` 就是"不重试"，实际仍会重试 10 次。真正要禁用重试必须走容器定制：

```java
@Bean
ListenerContainerCustomizer<AbstractMessageListenerContainer<?, ?>> customizer() {
    return (container, destinationName, group) ->
        container.setCommonErrorHandler(new DefaultErrorHandler(new FixedBackOff(0L, 0L)));
}
```

只有启用了 DLQ，binder 的 `max-attempts` / `back-off-*` 才会生效并覆盖容器默认值。

### 死信队列

```yaml
spring:
  cloud:
    stream:
      kafka:
        bindings:
          uppercase-in-0:
            consumer:
              enable-dlq: true
              dlq-name: orders-dlq
```

要点：

- `enable-dlq` 默认 **false**，且**必须已配置 `group`**，匿名组无法启用。
- 默认 DLQ 主题名是 `error.<destination>.<group>`，与 spring-kafka 原生的 `{topic}-DLT` 命名**不同**——两者混用时别按错名字找。
- 框架**不提供**任何死信消费机制：原因可能是暂时的（该回灌）也可能是永久的（回灌会造成无限循环）。官方示例的做法是回灌最多三次，之后转入 parking lot 主题。
- 回灌应用最好在主应用停止时运行，否则瞬时错误会很快耗尽重试次数。

### 手动提交

`autoCommitOffset: false` 时 binder 会把 `AckMode` 设为 `MANUAL`，并在入站消息里放入 `kafka_acknowledgment` 头，业务处理完自行确认：

```java
@Bean
public Consumer<Message<String>> manual() {
    return msg -> {
        service.process(msg.getPayload());
        msg.getHeaders().get(KafkaHeaders.ACKNOWLEDGMENT, Acknowledgment.class).acknowledge();
    };
}
```

### 错误处理原则

**不要用 try-catch 吞掉消费异常**。catch 住并正常返回会让位点前进，事件永久丢失——这比抛异常更糟。让异常传播出去，交给重试与 DLQ 机制处理，同时对 DLQ 深度建监控：那里堆积的未处理事件意味着有 bug 或数据契约不匹配。

### 幂等

消息语义是 at-least-once，重试、重平衡、手动提交失败都会导致重复投递。**消费端幂等由业务保证**，框架不提供。参见 [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)。

## 何时不该用 Stream

Stream 的价值在于**中间件可替换**与**配置化装配**。代价是：中间件的特有能力被抽象层挡住，出问题时要同时懂 Stream 和底层客户端两层。

| 场景 | 建议 |
| :-- | :-- |
| 需要在多个中间件间迁移或同时接入 | Stream |
| 只用 Kafka，且要用事务、Share Consumer、精确的位点控制、批量监听 | 直接用 [spring-kafka](/docs/CS/Framework/Spring/Kafka.md) |
| 要精细控制错误处理（`@RetryableTopic`、`ErrorHandlingDeserializer`） | 直接用 spring-kafka，抽象层会把配置项挡掉一层 |
| 需要 Kafka Streams 的有状态计算 | Kafka Streams Binder，或直接写 Kafka Streams |

一个经验判断：**排查问题时如果发现自己在给 binder 的配置项做翻译**（"Stream 的这个属性对应 Kafka 的哪个"），就说明抽象已经不划算了。

## Links

- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## References

1. [Spring Cloud Stream Reference](https://docs.spring.io/spring-cloud-stream/reference/)
2. [Spring Cloud Stream - Functional Binding Names](https://docs.spring.io/spring-cloud-stream/reference/spring-cloud-stream/functional-binding-names.html)
3. [Apache Kafka Binder - Dead-Letter Topic Processing](https://docs.spring.io/spring-cloud-stream/reference/kafka/kafka-binder/dlq.html)
4. [Apache Kafka Binder Reference](https://docs.spring.io/spring-cloud-stream/reference/kafka/kafka-binder/kafka-binder.html)
