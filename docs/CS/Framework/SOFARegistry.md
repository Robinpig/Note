## Introduction





## Architecture


SOFARegistry 采用四层分层设计，核心解决海量客户端连接与服务数据高可用问题：

| 层级	| 角色定位 |	核心职责 |
| --- | --- | --- |
| Client	| 客户端接入层	| 提供服务发布/订阅 API，应用通过 JAR 包接入
| SessionServer	| 会话代理层（关键）	| 直接承接客户端连接，收敛单客户端连接数为1，转发写请求到 DataServer，屏蔽客户端连接风暴 |
| DataServer	| 数据存储层	| 按 dataInfoId 一致性 Hash 分片存储服务数据，多副本备份保证高可用 |
| MetaServer	| 元数据管理层	| 维护 SessionServer/DataServer 集群一致列表，处理集群节点变更通知 |

核心设计考量：客户端不直连 DataServer，通过 SessionServer 中间层隔离，解决海量客户端并发压垮数据层的问题。







## Storage



SessionServer 数据存储设计
SessionServer 作为客户端连接的“第一道关口”，需存储三类核心数据：

数据类型概览
数据类型	存储实现	用途
  SessionCacheService	Guava Cache	缓存服务提供者列表，避免每次客户端变化都查询 DataServer，减轻数据层压力
  正排索引（会话主数据）	SlotStore/SimpleStore	按服务维度存储发布/订阅会话，结构为 Map<dataInfoId, Map<registerId, 会话数据>>
  倒排索引（连接→会话映射）	DataIndexer	按 ConnectId(ip:port) 维度快速索引该连接下的所有会话，用于断连清理



### Index

核心数据结构详解
（1）正排索引：按服务维度组织数据
  外层 Key：dataInfoId，服务唯一标识，格式如：  
  com.alipay.test.demo.service:1.0@DEFAULT#@#DEFAULT_INSTANCE_ID#@#TEST_GROUP
  内层 Key：registerId，单次发布/订阅请求的唯一 ID（客户端启动时随机生成 UUID）
  结构：Map<dataInfoId, Map<registerId, 会话数据>>
  （2）倒排索引：按连接维度快速定位
  设计动机：客户端断连时，若仅靠正排索引需遍历所有服务→所有会话检查 connectId，时间复杂度 O(N)，频繁断连时 CPU 消耗极高。
  结构：Map<ConnectId, Set<DataPos>>  
  ConnectId：客户端连接标识（ip:port）
  DataPos：封装定位会话的两个关键 ID（dataInfoId + registerId），通过它可直接在正排索引中找到对应会话。

核心实现类：DataIndexer，内部维护双索引 + 版本控制机制。



SessionServer 同时维护正排（主数据）和倒排（索引）两份数据，如何保证一致性？

写入时的一致性：索引先写，主数据后写
```java
public <R> R add(K key, V val, UnThrowableCallable<R> dataStoreCaller) {
Term term = lastTerm;
term.start.incrementAndGet(); // 写入开始计数
try {
    if (doubleWrite) insert(tempIndex, key, val); // 双写临时索引（后台重建时用）
    insert(index, key, val);          // 先写倒排索引
    return dataStoreCaller.call();    // 再写正排主数据
} finally {
    term.done.incrementAndGet(); // 写入完成计数
}
  }
```




设计考量：索引先写失败则整个操作失败，不会丢失数据；索引多写一条冗余数据不影响正确性（查询时回查主数据过滤）



删除时的巧妙权衡：只删主数据，不删索引
  断连清理逻辑（AbstractDataManager#deleteByConnectId）：
  通过倒排索引找到该 ConnectId 下的所有 DataPos；
  逐个回查正排索引，删除匹配的会话数据；
  不删除倒排索引中的对应记录。

为什么不删索引？
 若删除索引时，会话因网络波动快速重连并重新写入，可能导致新写入的索引被误删，最终主数据残留但无索引引用，形成内存泄漏。

最终一致性：后台定时重建索引
 允许索引暂时冗余，但不能无限膨胀，SOFARegistry 通过 双写 + Term 版本控制 实现无锁索引重建。

重建核心逻辑（DataIndexer#refresh）

```java
  private void refresh() {
   tempIndex = new ConcurrentHashMap<>(this.index.size());
   Term prevTerm = lastTerm;
   doubleWrite = true;              // 1. 开启双写：新写入同时到主索引和临时索引
   try {
       lastTerm = new Term();       // 2. 切换新版本 Term，后续写入用新 Term
       prevTerm.waitAllDone();      // 3. 等待旧 Term 所有进行中的写入完成
       dataStoreForEach((key, val) -> insert(tempIndex, key, val)); // 4. 从主数据全量回放重建临时索引
       index = tempIndex;           // 5. 原子替换主索引
   } finally {
       doubleWrite = false;         // 6. 关闭双写
   }
  }
```

Term 的关键作用
  每个 Term 维护两个原子计数器：
  start：写入开始次数
  done：写入完成次数
  通过 prevTerm.waitAllDone() 保证：切换版本前，所有旧版本的写入都已完成，避免重建过程中丢失并发写入的数据。
  举例说明：若线程1正在写入（旧 Term，start=1, done=0），后台重建开启双写后，需等待 done 计数追上 start，再从主数据回放——此时旧 Term 的所有写入已落到主数据中，回放不会丢失。


 五、技术亮点总结
性能优化：倒排索引解决断连清理瓶颈
  断连清理从 O(N) 遍历降至 O(1) 索引查询，支撑海量客户端高频断连场景。
一致性权衡：最终一致性替代强一致
  允许索引暂时冗余，通过后台修正达成最终一致，避免加锁阻塞写入；
  查询时始终回查主数据，以主数据为准，保证正确性。
无锁设计：版本控制协调并发
  全程无锁，通过 volatile 保证可见性、原子引用替换主索引、Term 协调重建与并发写入，最大化吞吐。

可迁移的设计模式
  双写 + 版本控制：适用于在线数据重建/迁移，无锁保证业务无感知；
  索引延迟删除 + 后台修正：适用于并发删除场景，避免竞态导致的数据残留。


  倒排索引核心类：com.alipay.sofa.registry.server.session.store.DataIndexer
  断连删除逻辑：com.alipay.sofa.registry.server.session.store.AbstractDataManager#deleteByConnectId
  Session 启动入口：SessionServerInitializer → SessionServerBootstrap#start





## Links

