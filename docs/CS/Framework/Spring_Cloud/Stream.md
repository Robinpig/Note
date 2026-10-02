## Introduction

Spring Cloud Stream 是构建消息驱动微服务的统一框架。它在应用与具体消息中间件之间加了一层抽象，让业务代码只面向“消息通道 / 绑定”编程，而底层到底是 Kafka、RabbitMQ、RocketMQ 还是 Kafka Streams，由可插拔的 **Binder** 决定，切换中间件通常只需换依赖和改配置，不必改业务代码。

它建立在 Spring Messaging（`Message`、`MessageChannel`、`@EnableBinding` 的现代函数式版本）之上，从 3.x 起主推 **Java 8 函数式模型**（`java.util.function` 中的 `Supplier` / `Function` / `Consumer`），老的 `@StreamListener`、`@EnableBinding` 注解已基本被取代。

## Binder

Binder 是 Stream 的核心 SPI，负责把应用层的抽象绑定到具体中间件：

- **Kafka Binder**：把 destination 映射为 Kafka topic，消费者组映射为 consumer group，分区映射为 partition。
- **RabbitMQ Binder**：destination 映射为 exchange / queue。
- **RocketMQ Binder**（Spring Cloud Alibaba 提供）：映射为 topic + consumer group。
- **Kafka Streams Binder**：特殊的 binder，直接对接 Kafka Streams 的拓扑（`KStream` / `KTable`）。

Binder 负责消费者组、分区、offset、重试、死信队列等中间件相关细节，业务层保持中立。

## Functional Model

3.x 推荐用函数 Bean 描述消息的生产、处理与消费，框架按 Bean 名 + `spring.cloud.function.definition` 自动绑定。

### Producer

等价于旧的 `MessageChannel#send`，现在用一个 `Supplier` 周期/按需产出消息：

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

也可以直接用 `StreamBridge` 在命令式代码里显式发送：

```java
streamBridge.send("output-out-0", "any payload");
```

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

对应旧版的 `@StreamListener(Sink.INPUT)`，现在函数名即绑定名。多个函数用管道符串接：`spring.cloud.function.definition=toUppercase|uppercase|logSink`。

### Binding 配置

```yaml
spring:
  cloud:
    function:
      definition: uppercase;logSink
    stream:
      bindings:
        uppercase-in-0:
          destination: orders           # 输入 topic/exchange
          group: order-service          # 消费者组
        uppercase-out-0:
          destination: orders-upper
      kafka:
        binder:
          brokers: localhost:9092
```

绑定名遵循 `<函数名>-<in|out>-<下标>` 的约定（如 `uppercase-in-0`），这是函数式模型找到对应 destination 的关键。

## Reliability

可靠性能力大多由 binder 落地，常见配置维度：

- **重试**：消费失败在本地按 `max-attempts`、退避策略重试（`consumer.retry-*`、`RetryTemplate`）。
- **死信队列 DLQ**：超过重试次数后投递到死信 topic/queue，避免毒消息无限阻塞分区。
- **幂等 / 手动 ack**：消息至少一次（at-least-once）语义下，业务侧需自行保证消费幂等。
- **分区与顺序**：同一 key 路由到同一 partition 以保证局部有序；Kafka binder 下 offset 提交模式（自动/手动）影响 at-least-once 行为。
- **错误处理**：可用自定义 `Consumer<ErrorMessage>` / error channel 接管失败消息。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Spring Reactive](/docs/CS/Framework/Spring/Reactive.md)

## References

1. [Spring Cloud Stream Reference](https://docs.spring.io/spring-cloud-stream/reference/)
2. [Spring Cloud Stream - Functional Programming Model](https://docs.spring.io/spring-cloud-stream/reference/spring-cloud-stream/functional-binding-names.htm)
3. [Spring Cloud Stream Kafka Binder](https://docs.spring.io/spring-cloud-stream-binder-kafka/reference/)
