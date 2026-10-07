## Introduction

Spring for Apache Kafka（spring-kafka）把 Spring 的编程模型套在 Kafka 客户端之上：用 `KafkaTemplate` 做高层发送抽象，用 `@KafkaListener` 声明式消费，用**监听器容器**管理 poll、位点提交、错误处理和生命周期。它与 [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md) 的设计高度同构，读过一篇另一篇很容易迁移。

> [!NOTE]
> 当前基线为 **Spring for Apache Kafka 4.1**（随 Boot 4.1 发布）。三个会影响写法的变更：
>
> 1. **移除 `spring-retry` 依赖**，重试改用 Spring Framework 7 内建于 `spring-core` 的 retry API。这带来一个极易踩的坑：`@RetryableTopic` 里的退避注解是 **`org.springframework.kafka.annotation.BackOff`**（属性名 `backOff`），不是 `org.springframework.retry.annotation.Backoff`。编译器会报 `package org.springframework.retry.annotation does not exist`，看着像缺依赖，于是有人把 `spring-retry` 加回来——**结果是编译通过了但注解完全不生效**，因为框架读的是自家注解。
> 2. **新增 Share Consumer**（Kafka Queues，KIP-932），打破"一个分区只能被一个消费者独占"的约束，见 [Share Consumer](?id=share-consumer)。
> 3. Jackson 3 迁移：`JsonSerializer` / `JsonDeserializer` 的默认输出格式与类型映射行为有变化。

## Quick Start

```java
// 生产
kafkaTemplate.send("orders", order.getKey(), order);

// 消费
@KafkaListener(topics = "orders", groupId = "order-service")
public void handle(Order order) {
    orderService.process(order);
}
```

Boot 自动装配 `ConsumerFactory` / `ProducerFactory` / `KafkaTemplate` / `ConcurrentKafkaListenerContainerFactory`。但要注意：**自动装配只覆盖"你没有自己定义"的部分**。一旦你手动声明了某个 `ConcurrentKafkaListenerContainerFactory` Bean，就要自己把错误处理器、序列化器等接到**你正在用的那个工厂**上——这是"配了却不生效"最常见的成因。

## KafkaTemplate

`KafkaTemplate` 包装了 `Producer`，提供 `send()`（返回 `CompletableFuture`）与 `sendDefault()`（发到 `spring.kafka.template.default-topic`）。

```java
CompletableFuture<SendResult<String, Order>> future = template.send("orders", key, order);
future.whenComplete((result, ex) -> {
    if (ex != null) {
        log.error("send failed", ex);
        return;
    }
    RecordMetadata meta = result.getRecordMetadata();
    log.info("sent to {}-{}@{}", meta.topic(), meta.partition(), meta.offset());
});
```

`send()` 立即返回不代表已落盘。要拿到 `RecordMetadata` 必须处理返回的 future——**忽略返回值是生产端丢消息最典型的写法**（不报错，只是消息偶尔不见）。

### Transactions

Kafka 事务有两种粒度：

| 方式 | 边界 | 用途 |
| :-- | :-- | :-- |
| `template.executeInTransaction(...)` | 包裹一段代码里的多次 send | 纯 Kafka 的原子多写 |
| `KafkaTransactionManager` + `@Transactional` | Spring 事务边界 | 消费-处理-生产（consume-transform-produce） |

消费端开启事务后，位点提交会一并纳入事务，从而实现"处理结果与位点同生共死"。但必须清醒：**Kafka 事务不等于跨库事务**。Kafka 与数据库之间没有真正的 2PC，`@Transactional` 只能做到 best-effort 1PC——DB 提交成功、Kafka 提交失败（或反之）的窗口客观存在，最终要靠幂等消费加对账兜底，而不是指望框架给出分布式原子性。参见 [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)。

## @KafkaListener

### Method Signature

框架按参数类型自动注入，常用组合：

```java
// 只要载荷
@KafkaListener(topics = "orders", groupId = "g1")
void a(Order order) { }

// 拿元数据
@KafkaListener(topics = "orders", groupId = "g1")
void b(ConsumerRecord<String, Order> rec) {
    rec.topic(); rec.partition(); rec.offset(); rec.headers();
}

// 批量
@KafkaListener(topics = "orders", groupId = "g1")
void c(List<ConsumerRecord<String, Order>> records) { }

// 手动提交
@KafkaListener(topics = "orders", groupId = "g1")
void d(Order order, Acknowledgment ack) {
    service.process(order);
    ack.acknowledge();
}

// 注解式取头部
@KafkaListener(topics = "orders", groupId = "g1")
void e(@Payload Order order,
       @Header(KafkaHeaders.RECEIVED_KEY) String key,
       @Header(KafkaHeaders.RECEIVED_PARTITION) int partition) { }
```

### Container and Concurrency

`@KafkaListener` 背后是 `ConcurrentKafkaListenerContainerFactory`，它创建 `ConcurrentMessageListenerContainer`，后者按 `concurrency` 起多个 `KafkaMessageListenerContainer`（每个一个 consumer 线程）：

```java
@Override
protected void doStart() {
    if (!isRunning()) {
       checkTopics();
       ContainerProperties containerProperties = getContainerProperties();
       TopicPartitionOffset[] topicPartitions = containerProperties.getTopicPartitions();
       if (topicPartitions != null && this.concurrency > topicPartitions.length) {
          this.logger.warn(() -> "When specific partitions are provided, the concurrency must be less than or "
                + "equal to the number of partitions; reduced from " + this.concurrency + " to "
                + topicPartitions.length);
          this.concurrency = topicPartitions.length;
       }
       setRunning(true);

       for (int i = 0; i < this.concurrency; i++) {
          KafkaMessageListenerContainer<K, V> container =
                constructContainer(containerProperties, topicPartitions, i);
          configureChildContainer(i, container);
          if (isPaused()) {
             container.pause();
          }
          container.start();
          this.containers.add(container);
       }
    }
}
```

由此得到 Kafka 消费并发的第一原则：**`concurrency` 的上限是分区数**。超过分区数的线程拿不到分区，全程空转。想提高吞吐必须先扩分区——这也是分区数成为并发天花板的原因（Share Consumer 正是为打破这一点而来）。

反过来，并发度也不能只顾着往上调：**同一分区只会被一个线程消费**，因此"按 key 分区 + 单线程"就能拿到 per-key 顺序；一旦让同一 key 落到不同分区，顺序保证就没了。

### Offset Commit

容器的 `AckMode` 决定何时提交位点。前提：`enable.auto.commit` 自 2.3 起若无显式配置，框架**无条件设为 false**，由容器接管。

| AckMode | 语义 |
| :-- | :-- |
| `RECORD` | 每处理完一条就提交 |
| `BATCH`（**默认**） | 本次 poll 的一批全部处理完后提交 |
| `TIME` | 一批处理完且距上次提交超过 `ackTime` |
| `COUNT` | 一批处理完且累计超过 `ackCount` 条 |
| `COUNT_TIME` | 上面两个条件任一满足 |
| `MANUAL` | 监听器调 `ack.acknowledge()`，但**实际提交时机同 BATCH**（等这批处理完一起提交） |
| `MANUAL_IMMEDIATE` | 调用 `acknowledge()` 时**立即**提交 |

`MANUAL` 与 `MANUAL_IMMEDIATE` 的差别既是高频考点，也是线上事故来源：许多人以为配了 `MANUAL` 就是"我 ack 了就提交"，实际上它只是把"是否标记"交给你，**提交动作仍要等整批处理完**。于是单条消息处理很慢时，前面已 ack 的消息会因为最后一条失败而被一起重投。需要精准控制时用 `MANUAL_IMMEDIATE`。

默认的 `BATCH` 是 at-least-once：一批 10 条处理到第 9 条崩溃，重启后这 10 条全部重来。因此**消费端幂等不是可选项**。

`Acknowledgment` 还提供了 `nack(long sleep)`（记录监听器）与 `nack(int index, long sleep)`（批量监听器）：提交前面的位点、把失败的及后续记录 seek 回去重投。`nack()` 只能在调用监听器的那个 consumer 线程上使用，用错监听器类型会抛 `IllegalStateException`；其 sleep 参数加上前一批的处理时间必须小于 `max.poll.interval.ms`，否则会被判定为消费超时而触发 rebalance。

## Container Polling Main Loop

每个 consumer 线程的核心循环如下，位点提交、seek、rebalance、暂停与恢复、空闲检测都集中在这里：

```java
protected void pollAndInvoke() {
    doProcessCommits();
    fixTxOffsetsIfNeeded();
    idleBetweenPollIfNecessary();
    if (!this.seeks.isEmpty()) {
       processSeeks();
    }
    enforceRebalanceIfNecessary();
    pauseConsumerIfNecessary();
    pausePartitionsIfNecessary();
    this.lastPoll = System.currentTimeMillis();
    if (!isRunning()) {
       return;
    }
    this.polling.set(true);
    ConsumerRecords<K, V> records = doPoll();
    if (!this.polling.compareAndSet(true, false) && records != null) {
       /*
        * There is a small race condition where wakeIfNecessaryForStop was called between
        * exiting the poll and before we reset the boolean.
        */
       if (records.count() > 0) {
          this.logger.debug(() -> "Discarding polled records, container stopped: " + records.count());
       }
       return;
    }
    if (!this.firstPoll && this.definedPartitions != null && this.consumerSeekAwareListener != null) {
       this.firstPoll = true;
       this.consumerSeekAwareListener.onFirstPoll();
    }
    if (records != null && records.count() == 0 && this.isCountAck && this.count > 0) {
       commitIfNecessary();
       this.count = 0;
    }
    debugRecords(records);

    invokeIfHaveRecords(records);
    if (this.remainingRecords == null) {
       resumeConsumerIfNeccessary();
       if (!this.consumerPaused) {
          resumePartitionsIfNecessary();
       }
    }
}


private void invokeIfHaveRecords(@Nullable ConsumerRecords<K, V> records) {
    if (records != null && records.count() > 0) {
       this.receivedSome = true;
       savePositionsIfNeeded(records);
       notIdle();
       notIdlePartitions(records.partitions());
       invokeListener(records);
    }
    else {
       checkIdle();
    }
    if (records == null || records.count() == 0
          || records.partitions().size() < this.consumer.assignment().size()) {
       checkIdlePartitions();
    }
}

private void doInvokeWithRecords(final ConsumerRecords<K, V> records) {
    Iterator<ConsumerRecord<K, V>> iterator = records.iterator();
    while (iterator.hasNext()) {
       if (this.stopImmediate && !isRunning()) {
          break;
       }
       final ConsumerRecord<K, V> cRecord = checkEarlyIntercept(iterator.next());
       if (cRecord == null) {
          continue;
       }
       this.logger.trace(() -> "Processing " + KafkaUtils.format(cRecord));
       doInvokeRecordListener(cRecord, iterator);
       if (this.commonRecordInterceptor !=  null) {
          this.commonRecordInterceptor.afterRecord(cRecord, this.consumer);
       }
       if (this.nackSleepDurationMillis >= 0) {
          handleNack(records, cRecord);
          break;
       }
       if (checkImmediatePause(iterator)) {
          break;
       }
    }
}

@Nullable
private RuntimeException doInvokeRecordListener(final ConsumerRecord<K, V> cRecord, // NOSONAR
       Iterator<ConsumerRecord<K, V>> iterator) {

    Object sample = startMicrometerSample();
    Observation observation = KafkaListenerObservation.LISTENER_OBSERVATION.observation(
          this.containerProperties.getObservationConvention(),
          DefaultKafkaListenerObservationConvention.INSTANCE,
          () -> new KafkaRecordReceiverContext(cRecord, getListenerId(), this::clusterId),
          this.observationRegistry);
    return observation.observe(() -> {
       try {
          invokeOnMessage(cRecord);
          successTimer(sample, cRecord);
          recordInterceptAfter(cRecord, null);
       }
       catch (RuntimeException e) {
          failureTimer(sample, cRecord);
          recordInterceptAfter(cRecord, e);
          if (this.commonErrorHandler == null) {
             throw e;
          }
          observation.error(e);
          try {
             invokeErrorHandler(cRecord, iterator, e);
             commitOffsetsIfNeededAfterHandlingError(cRecord);
          }
          catch (KafkaException ke) {
             ke.selfLog(ERROR_HANDLER_THREW_AN_EXCEPTION, this.logger);
             return ke;
          }
          catch (RuntimeException ee) {
             this.logger.error(ee, ERROR_HANDLER_THREW_AN_EXCEPTION);
             return ee;
          }
          catch (Error er) { // NOSONAR
             this.logger.error(er, "Error handler threw an error");
             throw er;
          }
       }
       return null;
    });
}
```

注意最里层的分支：**没有配置 `CommonErrorHandler` 时异常直接向上抛**，容器只记录日志并继续。这就是"消费失败后消息不见了"的默认行为。

## Error Handling

### Three Categories of Failure Boundaries

排障的第一步是分清消息在哪一步失败，因为各阶段的处理机制完全不同：

| 失败阶段 | 症状 | 处理机制 |
| :-- | :-- | :-- |
| Kafka 反序列化 | 字节根本转不出对象，监听器都进不去 | `ErrorHandlingDeserializer`、失败头、隔离或 DLT |
| Spring 消息转换 | 记录有了，但转不成监听器参数类型 | 消息转换器、`DefaultErrorHandler` |
| 监听器或业务代码 | 拿到对象后抛异常 | `DefaultErrorHandler` + 退避 + 恢复器 |
| 事务处理 | 提交前失败 | 回滚、重投或补偿 |

把它们统称"JSON 报错"会丢掉选择恢复策略所需的全部信息。

### ErrorHandlingDeserializer

毒消息（无法反序列化的记录）会让监听器反复失败，若不做处理会**彻底卡死整个分区**。用包装式反序列化器把它拦下来：

```java
@Bean
public ConsumerFactory<String, Order> cf(KafkaProperties props) {
    Map<String, Object> config = props.buildConsumerProperties();
    ErrorHandlingDeserializer<Order> deser =
        new ErrorHandlingDeserializer<>(new JsonDeserializer<>(Order.class));
    return new DefaultKafkaConsumerFactory<>(
        config, new StringDeserializer(), deser);
}
```

它不抛异常，而是把原始字节和失败原因塞进记录头部，让监听器或错误处理器能拿到并转投 DLT。**这是唯一能防止分区被单条坏消息卡死的机制**，成本只有两行配置，应当作为默认项。

与之配套的是反序列化安全：`JsonDeserializer` 支持 `spring.json.trusted.packages`，未列入的包不会被反序列化。这与 [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md) 里 `__TypeId__` 的利用面是同一类问题，**不要图省事设成 `*`**。

### DefaultErrorHandler

`DefaultErrorHandler` 是当前通用的记录级错误处理入口，取代了已移除的 `SeekToCurrentErrorHandler` 与 `SeekToCurrentBatchErrorHandler`。它把"退避重试"和"最终恢复"组合起来：

```java
@Bean
DefaultErrorHandler errorHandler(KafkaTemplate<Object, Object> template) {
    DeadLetterPublishingRecoverer recoverer =
        new DeadLetterPublishingRecoverer(template);
    return new DefaultErrorHandler(recoverer, new FixedBackOff(1000L, 3L));
}
```

要点：

- 默认恢复器只是**记录日志**，10 次失败后跳过。不配 `DeadLetterPublishingRecoverer` 的话，失败消息是被丢弃而不是进死信。
- `DeadLetterPublishingRecoverer` 默认投递到 `{原 topic}-DLT`，且**该 topic 需已存在或开启自动创建**——否则恢复动作本身失败。
- 某些异常被默认归类为 fatal（`DeserializationException`、`MessageConversionException`、`ClassCastException` 等），**跳过重试直接恢复**，因为重试注定失败。想让它重试需显式 `removeClassification(...)`。
- 批量监听器要精确指定失败位置，需抛 `BatchListenerFailedException` 并带上失败记录；否则整个批次重投。
- 这就是**阻塞重试**：重试发生在同一个 consumer 线程上，期间该分区不再前进。

### Blocking and Non-Blocking Retry

`@RetryableTopic` 提供非阻塞重试：失败记录被转发到带延迟的重试 topic，主消费者继续前进。

```java
@RetryableTopic(attempts = "4",
                backOff = @Backoff(delay = 1000, multiplier = 2.0),
                include = { RemoteServiceException.class },
                exclude = { ValidationException.class })
@KafkaListener(topics = "orders", groupId = "order-service")
public void handle(Order order) { ... }

@DltHandler
public void onDlt(ConsumerRecord<String, Order> rec,
                  @Header(KafkaHeaders.RECEIVED_TOPIC) String topic) {
    log.error("permanently failed: {}", rec.value());
}
```

两者的取舍不是新旧之分，而是**能否接受失败时的顺序丢失**：

| 维度 | 阻塞（`DefaultErrorHandler`） | 非阻塞（`@RetryableTopic`） |
| :-- | :-- | :-- |
| 失败时的 per-key 顺序 | 保持 | **丢失**（这是机制本身，不是副作用） |
| 失败时分区吞吐 | 停滞 | 不受影响 |
| 需预建的 topic | 1 个加 DLT | 1 个加每个不同延迟各一个，再加 DLT |
| 长退避 | 受 `max.poll.interval.ms` 限制 | 无限制 |

顺序丢失的原因很直白：`invoice-7` 失败了，而它后面的事件会正常通过并先被处理完，没有任何配置能阻止这一点。所以**做状态流转、按 key 有序的消费端应当用阻塞重试；通知、索引、缓存预热这类幂等且对顺序不敏感的消费者才适合重试 topic**。

命名规则上还有个运维陷阱：默认按**延迟值**而非尝试序号命名（`orders-retry-500`、`-1000`、`-2000`）。这意味着**改 backoff 的 multiplier 会重命名重试 topic，把还留在旧 topic 里的消息孤立掉**——改退避策略要当成一次改名来发布。4.1 起 `RetryTopicConfigurationBuilder` 的 `sameIntervalTopicReuseStrategy` 默认改为 `SINGLE_TOPIC`，相同间隔复用单个 topic，缓解了这个问题。

最后：没有 `@DltHandler` 时框架照样创建并填充 DLT，只是**记录日志然后继续，应用里没有任何东西看过这条记录**。没人盯着的 DLT 是一个会一直涨到磁盘告警的队列。

### Practice Checklist

按投入产出排序：

1. `ErrorHandlingDeserializer` —— 两行配置，唯一能防止分区卡死。
2. 一个恢复器，让失败有去处；预先创建 `-dlt` topic。
3. 异常分类（`include` 与 `exclude`）—— 收益高于任何退避调参。
4. 对 DLT 深度和恢复器的 WARN 建告警。

最不该做的是留着默认值上线，然后在事故中发现"Spring Kafka 处理错误"的意思是：瞬间重试十次，然后静默丢弃。

## Share Consumer

Kafka 4.0 的 Share Group（KIP-932）把消费模型从"分配分区"改为"broker 逐条分发记录"，等于给 Kafka 补上了 RabbitMQ 式的队列语义。spring-kafka 4.0 起提供 `ShareConsumerFactory` 与 `ShareKafkaListenerContainerFactory`：

```java
@Bean
ShareConsumerFactory<String, String> shareConsumerFactory(KafkaProperties props) {
    Map<String, Object> cfg = props.buildConsumerProperties();
    cfg.remove("isolation.level");      // 由 broker 管理投递，这两项不支持
    cfg.remove("auto.offset.reset");
    return new DefaultShareConsumerFactory<>(cfg);
}

@Bean
ShareKafkaListenerContainerFactory<?> shareFactory(ShareConsumerFactory<?, ?> f) {
    return new ShareKafkaListenerContainerFactory<>(f);
}
```

消费端与普通监听器写法一致，只是 `groupId` 指的是 share group：

```java
@KafkaListener(topics = "image-processing", groupId = "image-processors",
               containerFactory = "shareKafkaListenerContainerFactory")
public void processImage(String imageUrl) {
    imageService.process(imageUrl);
}
```

### Three Confirmation Actions

这是与 RabbitMQ 差异最大、最容易踩的地方：

| 动作 | 含义 |
| :-- | :-- |
| `acknowledge()` | ACCEPT，处理成功 |
| `release()` | 释放，交给**其他消费者**重投 |
| `reject()` | REJECT，永久失败，不再投递 |

而**默认的 `EXPLICIT` 模式下由容器代管：方法正常返回即 ACCEPT，抛异常即 REJECT**。也就是说，习惯了 RabbitMQ 的人会以为抛异常会 requeue，实际 Kafka 这边是**永久失败**。想让可恢复的失败重试，必须开启显式确认并调用 `release()`：

```java
@KafkaListener(topics = "payment-processing", groupId = "payment-processors",
               containerFactory = "explicitShareFactory")
public void processPayment(PaymentEvent event, ShareAcknowledgment ack) {
    try {
        if (!isValid(event)) { ack.reject(); return; }   // 毒消息，永久失败
        paymentService.process(event);
        ack.acknowledge();
    } catch (TransientException e) {
        ack.release();                                    // 可恢复，重投
    } catch (Exception e) {
        ack.reject();
    }
}
```

三种确认模式：`EXPLICIT`（默认，容器代管）、`MANUAL`（监听器自行确认，且上一次 poll 的记录全部确认前会阻塞后续 poll）、`IMPLICIT`（broker 无条件接受，不关心处理结果）。

### Constraints and Concurrency Semantics

Share Consumer **不支持**：显式分区分配（`TopicPartitionOffset`）、topic 模式订阅、手动位点管理。

并发的含义也变了。`concurrency` 在这里是**叠加的 share group 成员数**，与分区数无关：

- 实例 A 配 `concurrency=3`、实例 B 配 `concurrency=3` → broker 眼里是 6 个成员
- 单容器 `concurrency=5` 等价于 5 个各跑 `concurrency=1` 的实例

每个线程有独立的 `ShareConsumer`，各自独立确认，一个线程未确认的记录不阻塞其他线程。

**何时不用**：需要严格顺序（交易流水、会话事件）、有状态流处理与聚合、Kafka Streams 或依赖分区本地状态的场景，都应继续用传统消费者。Share Group 是补充而非替代。

## Serialization and Type Conversion

序列化（Kafka 层的 `Serializer` / `Deserializer`）与 Spring 消息转换（`MessageConverter`）是**两个独立阶段**，把它们各自的输入输出类型配错是 JSON 类故障的常见成因。

- `JsonSerializer` / `JsonDeserializer` 处理字节与对象之间的转换；
- `MessageConverter`（如 `JsonMessageConverter`）负责把记录的值转成监听器参数类型。

Jackson 3 迁移时，日期格式、属性顺序、null 处理的默认行为都有变化，灰度期尤其要显式指定契约而非依赖默认值。这个问题与 [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md) 中的情形同构，两边规律一致。

## Observability

spring-kafka 通过 Micrometer Observation 埋点（`KafkaListenerObservation`，见上面 `doInvokeRecordListener` 源码），监听器耗时、成功与失败计数可直接接入 [链路追踪](/docs/CS/Framework/Spring_Cloud/Sleuth.md)。容器自身的指标按 `client-id` 分组，可经 `container.metrics()` 获取。

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Spring Cloud Stream](/docs/CS/Framework/Spring_Cloud/Stream.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)

## References

1. [Spring for Apache Kafka Reference](https://docs.spring.io/spring-kafka/reference/)
2. [Spring for Apache Kafka - Kafka Queues (Share Consumer)](https://docs.spring.io/spring-kafka/reference/kafka/kafka-queues.html)
3. [Introducing Share Consumer Support in Spring for Apache Kafka](https://spring.io/blog/2025/10/14/introducing-spring-kafka-share-consumer)
4. [Spring for Apache Kafka - Retry Topic Naming](https://docs.spring.io/spring-kafka/reference/retrytopic/topic-naming.html)
