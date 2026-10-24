## Introduction

MongoDB 的事务能力分两层：**单文档原子性**是引擎天然保证的，从 1.x 就有；**多文档 ACID 事务**是 4.0（副本集）与 4.2（分片集群）才补齐的。理解这两层的边界，才能判断某个业务到底需要事务，还是改一下文档边界就够了。

## Single-Document Atomicity

对一篇文档的更新（包括用 `$set`、`$inc`、`$push`、`$addToSet` 等操作符修改多个字段）是原子的：要么全部生效，要么全部不生效。`findOneAndUpdate` 还能原子地"读改写并返回"。

```javascript
// 账户扣款 + 流水号递增在同一文档内，天然原子
db.accounts.updateOne(
  { _id: "A", balance: { $gte: 100 } },
  { $inc: { balance: -100, version: 1 }, $push: { ledger: { amount: -100, ts: new Date() } } }
)
```

这就是文档建模强调"把需要一起变更的数据放进同一文档"的原因：**能收敛到单文档的一致性，不需要分布式事务**。

## Multi-Document Transactions

```javascript
const session = client.startSession();
try {
  await session.withTransaction(async () => {
    await accounts.updateOne(
      { _id: "A", balance: { $gte: 100 } },
      { $inc: { balance: -100 } },
      { session }
    );
    await accounts.updateOne(
      { _id: "B" },
      { $inc: { balance: 100 } },
      { session }
    );
    await transfers.insertOne(
      { from: "A", to: "B", amount: 100, ts: new Date() },
      { session }
    );
  }, {
    readConcern: { level: "snapshot" },
    writeConcern: { w: "majority" }
  });
} finally {
  await session.endSession();
}
```

所有操作必须显式带上 `session`；`withTransaction` 封装了提交、回滚与可重试错误的自动重试。

## Isolation

- 默认提供 **snapshot isolation**：事务内看到的是开始时刻的一致性快照，不会出现脏读、不可重复读。
- 快照隔离**不防止写偏斜（write skew）**：两个事务读同一组数据、各自写不同文档，可能都通过校验。需要串行化语义时，业务层要加显式冲突检测（如版本号或唯一约束）。
- 分片集群事务若需要跨 shard 的同一快照，必须使用 `readConcern: "snapshot"`；`local` 与 `majority` 在分片事务中不保证跨 shard 同一视图。

## Conflicts and Retry

并发更新同一文档时，后提交者收到 `WriteConflict`，被包装为 `TransientTransactionError`，事务整体回滚。`withTransaction` 会重试整个回调，因此回调必须是**幂等**的（不要在事务外产生副作用，如发消息、调用外部接口）。

提交阶段可能返回 `UnknownTransactionCommitResult`（网络中断，提交结果未知）：此时应使用相同的 `txnNumber` 重试 `commitTransaction`，而不是重新执行整个事务。

几个版本细节：

- 6.2 起，`TransactionTooLargeForCache` 错误不再自动重试；
- 8.1 起，事务内 `upsert` 遇到唯一键冲突不再重试；
- 9.0 起，服务端限制并发打开的多文档事务数，由 `maxConcurrentMultiDocumentTransactions` 控制，默认 10000，超限返回 `TooManyOpenTransactions`。

## Limits

| 限制 | 值 / 说明 |
| :--- | :--- |
| 默认运行时长 | 小于 60 秒（`transactionLifetimeLimitSeconds`），超时被后台清理线程中止 |
| 单条 oplog 条目 | ≤ 16MB |
| 事务总写入量 | 4.2 起不再受 16MB 总上限约束（拆成多条 oplog 条目） |
| 读偏好 | 事务内必须读 primary |
| 不支持的操作 | 写入 capped collection、部分管理命令 |
| DDL | 4.4 起可在事务内建集合/索引，但限制多，生产慎用 |

长时间事务会持有快照，阻碍 WT 回收旧版本，导致缓存压力上升；官方建议事务"短小、少量文档、快进快出"。

## Read Concern and Write Concern

| 选项 | 事务中的含义 |
| :--- | :--- |
| `readConcern: "snapshot"` | 事务内一致性快照；分片事务需要它 |
| `readConcern: "majority"` | 只读多数派已确认的数据；分片事务不保证跨 shard 同一快照 |
| `readConcern: "local"` | 读本节点最新数据；可能被回滚 |
| `writeConcern: { w: "majority", j: true }` | 提交需多数派持久化，宕机不丢 |

事务的 `writeConcern` 在提交时生效，而不是每条语句。生产环境通常用 `w: "majority"`，并与副本集的 majority commit point 配合。

## When Not to Use

- **长事务**：跨多个业务步骤、等待外部回调，必然超时并放大锁冲突。
- **热点账户/库存**：高并发下事务冲突率极高，重试风暴比单文档原子更新更糟；应改用原子操作符或单文档建模。
- **跨分片大批量写入**：两阶段提交开销大，考虑按业务键共置（colocation）或异步补偿。
- **可以最终一致的场景**：用 outbox / saga / 幂等消息替代分布式事务。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Data Model](/docs/CS/DB/MongoDB/DataModel.md)

## References

- [MongoDB Transactions](https://www.mongodb.com/docs/manual/core/transactions/)
- [Transactions Production Considerations](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/)
- [Read Concern](https://www.mongodb.com/docs/manual/reference/read-concern/)
- [Write Concern](https://www.mongodb.com/docs/manual/reference/write-concern/)
