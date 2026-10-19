# Wormhole

Wormhole 是 Google 在 NSDI 2015 公开的**跨地域可靠发布订阅（geo-replicated pub-sub）**系统，是 Google 内部多个全球化服务（搜索索引、广告、YouTube 等）的**消息骨干**。它的定位是：在不要求强一致的前提下，把事件以低延迟、可靠地从生产者所在的 region 复制到所有订阅 region，让上层应用在自己的 region 内就近消费。

Wormhole 与 [PNUTS](/docs/CS/Distributed/PNUTS.md)（跨 region 数据服务）、[Databus](/docs/CS/Distributed/Databus.md)（单集群 CDC）一起，构成"数据如何在地理分布下流动"的三种典型机制；也呼应 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 中"跨 region 复制"这一运维现实。

## Architecture

- **逻辑 topic 全局命名，物理 region 本地副本**：一个 Wormhole topic 在逻辑上全局唯一，但每个 region 都维护自己的一份副本。生产者把消息写入**本地 region**，随后 Wormhole 通过跨 region 的**复制 pipeline** 把消息异步推送到所有订阅 region；消费者从**本地 region** 读取，从而避免跨大洲的读延迟。
- **生产者 / 消费者解耦**：生产者只关心本地写入成功；消费者只关心本地可读。中间复制对两者透明，这正是发布订阅的本质——与 [Dynamo](/docs/CS/Distributed/Dynamo.md) 的"写入本地 coordinator、异步 gossip 扩散"在"本地写 + 异步扩散"思路上一致。
- **复制 pipeline 与流控**：跨区域链路用多级 pipeline 串联，逐级转发并做**flow control**，防止热门 topic 把下游 region 压垮；复制过程对每条消息打全局唯一 id 并记录 checkpoint，便于断点续传与重放。

## Delivery Guarantees

- **At-least-once + 去重**：Wormhole 保证消息至少投递一次（复制链路可能重发），消费侧依据消息 id 做**幂等去重**。这是最终一致系统常见的取舍——把"恰好一次"的难题下推到消费者，而非在消息层强保证。
- **有序性与位点**：每个 topic 内消息有序，消费者通过 checkpoint 维护消费位点，可重放历史（故障恢复、回溯重算）。
- **与存储层区别**：Wormhole 是**消息层**，不持久化全量业务状态，只保证事件流的可靠流动；这与 [Spanner](/docs/CS/Distributed/Spanner.md) / [F1](/docs/CS/Distributed/F1.md) 那种"强一致、可查询"的存储层形成对照——前者提供"最终一致的事件"，后者提供"某一时刻一致的数据"。

## Why Not a Strongly Consistent Store

很多 Google 服务需要的是"让全球各 region 都能尽快看到某个事件"（如索引更新、配置下发），而非"跨 region 的 ACID 事务"。强一致跨 region 存储（如 Spanner 的 TrueTime commit wait）要付出可观的延迟与协调成本；Wormhole 选择**最终一致 + 低延迟**，把一致性边界交给上层业务按需在消费端处理。这与 [Consensus/Consensus.md](/docs/CS/Distributed/Consensus/Consensus.md) 里"CAP 下 AP 系统用 quorum + 异步复制换可用性"的路线同源。

## Links

- [PNUTS](/docs/CS/Distributed/PNUTS.md)
- [Databus](/docs/CS/Distributed/Databus.md)
- [Dynamo](/docs/CS/Distributed/Dynamo.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)

## References

- Wormhole: Reliable Pub-Sub to Support Geo-replicated Internet Services (Sharma et al., NSDI 2015)
- Paper: https://www.usenix.org/system/files/conference/nsdi15/nsdi15-paper-sharma.pdf
