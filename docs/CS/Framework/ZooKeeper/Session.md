## Introduction

ZooKeeper 中 **Session 就是客户端与服务端之间的一条 TCP 长连接**，会话生命周期从首次建连开始。通过这条连接，客户端以心跳维持会话有效、收发请求与响应、并接收 watch 事件（见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 的架构全景）。会话是 ephemeral 节点与 watch 的存在前提（见 [Watches](/docs/CS/Framework/ZooKeeper/Watches.md)）。

本页聚焦 **session 的服务端追踪与生命周期深度**；客户端侧的建连 / 超时 / 重连用法见 [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)。

## 会话状态与恢复链路

一次连接的生命周期与三个服务端入口：

- **`createSession(cnxn, passwd, timeout)`** —— 首次建连。分配 `sessionId`、`SessionTrackerImpl.createSession` 生成 `passwd`（由 `sessionId ^ superSecret` 作种子的随机数，校验重连身份），并提交一条 `CreateSessionTxn`。
- **`reopenSession(cnxn, sessionId, passwd, timeout)`** —— 重连。`checkPasswd` 校验 `sessionId/passwd` 匹配后调 `revalidateSession`。
- **`touchSession(sessionId, timeout)`** —— 每次心跳/请求。校验会话存在且未 closing 后 `updateSessionExpiry` 把会话挪到新的过期桶；返回 false 则会话已失效。

> [!NOTE]
> `sessionId` 是 64 位，`passwd` 是 16 字节随机数（`Random r = new Random(sessionId ^ superSecret)` 生成）。二者构成会话凭证，重连必须携带；`superSecret` 每个进程不同且重启会变，因此**跨重启的历史会话无法恢复**（会走 `SESSION_EXPIRED`）。

## 生命周期与超时

- `sessionTimeout` 控制会话超时，但实际生效值被服务端**钳制**到 `[minSessionTimeout, maxSessionTimeout]`（默认 `2×tickTime` ~ `20×tickTime`，见 [cluster](/docs/CS/Framework/ZooKeeper/cluster.md)）；协商结果由 `ConnectResponse` 的 `negotiatedSessionTimeout` 返回，客户端须以此为准。
- 服务端压力大或网络抖动导致断开时，客户端按地址列表**逐一重连**（重试策略推荐用 [Curator](/docs/CS/Framework/ZooKeeper/Curator.md)）。
- 只要在 `sessionTimeout` 内重新连上集群任意节点，会话仍有效；超时外重连会得到 `SESSION_EXPIRED`，需业务自行恢复临时数据。
- 重连后若连接到数据较旧的节点，服务端会先追平 zxid 再恢复会话（见下节），避免看到陈旧视图。

## 重连的 zxid 对齐机制

会话恢复时，客户端携带**上次已见 zxid**。若新连接的服务器尚未追上该 zxid，服务端**不会**立即恢复会话，而是等追上后才 `finishSessionInit`——保证客户端"看到的最新 zxid"永不回退（Single System Image 保证）。这一设计依赖"客户端只会见到已复制到多数派的变更"这一前提，从而保证持久性。

## 服务端实现：SessionTrackerImpl 与 ExpiryQueue

`ZooKeeperServer`（单机与集群各角色共用）持有 `SessionTracker`，生产实现为 `SessionTrackerImpl`（`org.apache.zookeeper.server` 包）：

- `sessionsById`：`ConcurrentHashMap<sessionId, SessionImpl>`
- `sessionsWithTimeout`：会话 → 超时映射
- `ExpiryQueue<SessionImpl>`：按 tick 分桶，**批量过期**同一区间的会话（round-up 提供 grace period）

心跳由 `touchSession(id, timeout)` 更新过期桶；过期线程轮询 `sessionExpiryQueue`，到点则 `setSessionClosing` + `expirer.expire()`。`createSession` / `reopenSession` / `revalidateSession` 负责建连与会话恢复；**会话创建本身也是一条 `CreateSessionTxn` 事务**，必须经 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md) 提交，保证跨副本一致。

```java
// SessionTrackerImpl.touchSession：心跳续租的核心
public synchronized boolean touchSession(long sessionId, int timeout) {
    SessionImpl s = sessionsById.get(sessionId);
    if (s == null) return false;              // 会话不存在（已过期）
    if (s.isClosing()) return false;          // 正在关闭
    updateSessionExpiry(s, timeout);          // 挪到新的过期桶
    return true;
}
```

## SessionMovedException：历史坑

同一 `sessionId / sessionPasswd` 在旧节点因网络延迟晚到的写请求，可能覆盖新节点上重建会话后的数据。ZOOKEEPER-417 引入 `SessionMovedException` 让客户端感知"会话已漂移到别处"；但 ZOOKEEPER-2219 表明该问题至今未彻底解决——这也是为什么**会话过期后不要静默重试旧连接**，应重建会话。

## 与 ephemeral / watch 的耦合

- **ephemeral 节点**的存活完全绑定会话：会话结束即删除（用于选主 / 服务发现，见 [Recipes](/docs/CS/Framework/ZooKeeper/Recipes.md) 与 Curator 的 `LeaderSelector`）。`DataTree.ephemerals` 以 `sessionId → Set<path>` 维护，会话过期时统一清理。
- **watch 随会话失效**：会话过期或重连未恢复前，znode 变化不会通知（见 [Watches](/docs/CS/Framework/ZooKeeper/Watches.md)）。
- **ACL 身份随会话失效**：`addAuthInfo` 注入的身份绑会话，会话过期后需重新注入（见 [ACL](/docs/CS/Framework/ZooKeeper/ACL.md)）。

## Links

- [ZooKeeper 枢纽](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Watches（watch 随会话失效）](/docs/CS/Framework/ZooKeeper/Watches.md)
- [客户端 client（建连/超时/重连用法）](/docs/CS/Framework/ZooKeeper/client.md)
- [ACL（身份绑会话）](/docs/CS/Framework/ZooKeeper/ACL.md)
- [Zab（CreateSessionTxn 提交）](/docs/CS/Framework/ZooKeeper/Zab.md)
- [Curator（重试策略）](/docs/CS/Framework/ZooKeeper/Curator.md)
- [集群 cluster（超时参数）](/docs/CS/Framework/ZooKeeper/cluster.md)
- [Session 过期排查（troubleshooting）](/docs/CS/Framework/ZooKeeper/troubleshooting.md)

## References

1. [ZooKeeper Programmer's Guide — Sessions](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html#ch_zkSessions)
2. [ZOOKEEPER-417（SessionMovedException）](https://issues.apache.org/jira/browse/ZOOKEEPER-417)
3. [ZOOKEEPER-2219](https://issues.apache.org/jira/browse/ZOOKEEPER-2219)
