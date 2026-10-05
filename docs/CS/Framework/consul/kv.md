## Introduction

Consul 的 **KV 存储**是基于 Raft 的强一致键值，命令 `consul kv` / HTTP `/v1/kv/<key>`。它和 etcd 的 KV 看起来相似，但语义有明显差异：**Consul KV 不保留历史版本**（每次写直接覆盖），而 etcd 的 MVCC 保留多 revision（见 [etcd MVCC](/docs/CS/Framework/etcd/MVCC.md)）。Consul KV 的"协调"能力主要靠 **session**（类似 etcd 的 lease，见 [etcd lease](/docs/CS/Framework/etcd/lease.md)）来实现锁、leader 选举、临时键。

## 基本语义

- **无历史版本**：写操作整体替换 value，不留存旧 revision；无法像 etcd 那样"从某 revision 读历史"或"watch 某 key 的全部变更轨迹"。
- **层级键**：以 `/` 分隔的任意字符串键，`consul kv get -recurse` 可递归列举前缀。
- **单值上限 512KB**：官方文档限制 value 不超过 512KB；大对象应外置到对象存储、KV 只存指针。
- **CAS（Check-And-Set）**：写请求带 `cas=<ModifyIndex>`——仅当 KV 当前的 `ModifyIndex` 等于该值时才成功，用于无锁乐观并发。`ModifyIndex` 每次写自增，是 Consul KV 唯一的"版本号"概念（非连续 revision）。
- **原子化整个树**：递归删除/写以单条 Raft 日志提交，保证子树一致。

## Session：临时键与锁的基础

session 把一组 key 与一个**持有者身份**绑定：当 session 失效（持有者宕机 / TTL 过期 / 显式销毁），绑定的 key 自动被释放或删除。

| 字段 | 取值 / 默认 | 说明 |
| :--- | :--- | :--- |
| `LockDelay` | 默认 **15s** | 锁释放后的一段"冷静期"，期间该 key 不可被立即重新 acquire，防止客户端缓存未刷新导致的脑裂 |
| `TTL` | 区间 **10s – 86400s**（24h）；不指定则无 TTL | session 的存活心跳上限；无 TTL 时 session 持久直到显式销毁或 leader 切换清理 |
| `Behavior` | `release`（默认）/ `delete` | session 失效时，绑定的 key 是"释放"（保留 key，仅解绑）还是"删除"（删除 key 本身） |

> [!NOTE]
> session 的 `TTL` 不是"过期即删"的硬保证——它只是检测死客户端的手段。leader 在超过 TTL 未收到心跳后才回收 session；网络分区时可能略晚，因此锁的"安全"依赖 `LockDelay` 而非 TTL 精确性。

### 分布式锁

- `consul kv put -acquire=<session>` 在 key 上**获取锁**（需该 key 当前未被其他 session 持有，或 `cas=0` 新建）；
- 持有者用 `-release=<session>` 释放；session 失效自动释放；
- 配合 `LockDelay` 避免"持有者刚死、新客户端立刻抢到锁但旧客户端请求还在飞"的竞态。

### 信号量（Semaphore）

Consul 还提供 [Semaphore](https://developer.hashicorp.com/consul/api-docs/semaphore) 原语（基于 session + 一组含序号的 key），实现"至多 N 个持有者"的并发控制。注意：它**没有 etcd concurrency 包里的 STM（软件事务内存）**——Consul 的协调原语比 etcd 薄，复杂事务要业务自己编排。

## 阻塞查询（Blocking Query）

HTTP 带 `index=<ModifyIndex>` + `wait=<duration>`（默认最长 5m，Consul 2.0 起 HTTP 读超时提到 15min 以容纳长轮询）做长轮询：服务端在 `ModifyIndex` 变更或超时前挂起返回。语义比 etcd watch 灵活（任意索引点阻塞），但**不支持按历史 revision 回溯**——想要"全量变更流"得客户端自己维护游标。

## 与 etcd 对照

| 维度 | Consul KV | etcd KV |
| :--- | :--- | :--- |
| 历史版本 | 无（仅 ModifyIndex 单值） | MVCC 多 revision |
| 临时键/锁 | session（LockDelay 15s） | lease（TTL） |
| CAS | `cas=<ModifyIndex>` | `prevIndex` / 事务 |
| 单值上限 | 512KB | 默认 1.5MB（可配） |
| 监听变更 | 阻塞查询（无历史） | watch（按 revision，可回溯） |
| 事务 | 不支持 STM | concurrency.STM |

Consul KV 的定位是"配合服务发现与配置的小型强一致存储"，不是 etcd 那种面向海量协调事件的 MVCC 引擎。若需要历史回溯、事务或大规模监听，etcd 更合适；若只是存配置、做leader 选举、加分布式锁，Consul KV + session 足够且 API 友好。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Client（客户端）](/docs/CS/Framework/consul/client.md)
- [etcd MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [etcd lease](/docs/CS/Framework/etcd/lease.md)

## References

1. [Consul KV Store](https://developer.hashicorp.com/consul/docs/concepts/key-value-store)
2. [Consul Sessions](https://developer.hashicorp.com/consul/api-docs/sessions)
3. [Consul Semaphore](https://developer.hashicorp.com/consul/api-docs/semaphore)
