## Introduction

时间轮（Timing Wheel）是高效管理**大量定时器/超时**的数据结构，用「以空间换时间」的思路把 O(n) 的定时器扫描降到接近 O(1) 的插入/取消、O(1) 的到期推进。代表作是 Varghese & Lauck 1987 年的论文 *Hashed and Hierarchical Timing Wheels*，后被 Netty、Kafka、ZooKeeper、Linux 内核（底层 timer）等广泛采用。

## 基本时间轮（Simple / Hashed Wheel）

把时间切成固定长度的槽（slot），所有落到同一时间窗的定时器挂到同一槽的链表上，一个指针按 tick 转动，转到某槽就触发该槽全部定时器。

- 单轮容量 = `槽数 × tick 周期`；超时超过一轮的需要额外处理（重复入槽 / 圈数计数）。
- **Hashed Wheel**：用哈希把超时映射到槽，内存占用与定时器数量近似线性相关，插入/取消均摊 O(1)。

```
         tick ↑
   ┌───┬───┬───┬───┬───┐
   │ 0 │ 1 │ 2 │ 3 │ 4 │  每个槽挂一个超时链表
   └───┴───┴───┴───┴───┘
```

## 层级时间轮（Hierarchical Wheel）

单轮时间跨度有限，于是借鉴「钟表时分秒」做多级滚轮：低精度轮转一圈，向高精度轮进位一格，像秒针走 60 格进位到分针。这样能用有限槽位表达极大时间跨度，且只需在进位时搬迁少量定时器。

- **Netty `HashedWheelTimer`**：经典 Hashed Wheel 实现，用于连接空闲检测、写超时、请求 timeout。
- **Kafka Purgatory（炼狱）**：用**层级时间轮**管理 produce/scroll/fetch 的 acks 等待、延迟操作，避免为每个请求起一个 `Timer` 线程导致线程爆炸与上下文切换。

## 与其他定时器方案对比

| 方案 | 插入/取消 | 到期扫描 | 适用 |
|---|---|---|---|
| 最小堆（java Timer/DelayQueue） | O(log n) | O(1) 取最小 | 定时器少、需最早到期优先 |
| 时间轮 | 均摊 O(1) | O(1) 推进 | 海量短超时（网络/IO） |
| 红黑树（Linux timerfd） | O(log n) | O(1) 游标 | 内核级精确计时 |

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Kafka Streams](/docs/CS/MQ/Kafka/Streams.md)
- [Netty EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [Hashed and Hierarchical Timing Wheels: Data Structures for the Efficient Implementation of a Timer Facility](https://dl.acm.org/doi/pdf/10.1145/41457.37504)
- [Apache Kafka, Purgatory, and Hierarchical Timing Wheels](https://www.confluent.io/blog/apache-kafka-purgatory-hierarchical-timing-wheels/)
