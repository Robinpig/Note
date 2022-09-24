## Introduction

适用互联网高并发，高性能场景，解决mysql磁盘慢问题



虽然目前CPU缓存数据 但使用局部变量代替全局变量能拥有较小的提升(特别是在多线程环境下,使用volatile可以比较每次从内存中取和缓存中取的差别)





## 物理缓存

CPU 

L1缓存分为指令缓存和数据缓存

- L1和L2缓存在每一个CPU核中，L3则是所有CPU核心共享的内存。
- L1、L2、L3的越离CPU近就越小，速度也越快，越离CPU远，速度也越慢。
- 再往后面就是内存，内存的后面就是硬盘



L0和L4

cache line

**Tag :** 每条Cache line 前都会有一个独立分配的24bits=3Bytes来存的tag，也就是内存地址的前24bits.

**Index** : 内存地址的后面的6bits=3/4Bytes存的是这一路（way）Cache line的索引，通过6bits我们可以索引2^6=64条Cache line。

**Offset** : 在索引后面的6bits存的事Cache line的偏移量。

寻址流程

1. 用索引定位到相应的缓存块。
2. 用标签尝试匹配该缓存块的对应标签值。其结果为命中或未命中。
3. 如命中，用块内偏移定位此块内的目标字。然后直接改写这个字。
4. 如未命中，依系统设计不同可有两种处理策略，分别称为按写分配（Write allocate）和不按写分配（No-write allocate）。如果是按写分配，则先如处理读未命中一样，**将未命中数据读入缓\**\**存**，然后再将数据**写到被读入的字单元**。如果是不按写分配，则直接将数据**写回内存**。





## 在项目中缓存是如何使用的？

- 客户端缓存
- 网络缓存
- 服务应用缓存
- 数据库缓存

- 走springboot @CacheConfig

查询：先查缓存，有返回，没有查数据库，set到缓存返回。 修改：先删db，后删redis

- 单独业务使用

db，缓存一致性问题，缓存竞争后面讨论解决方案

## Database Cache


A database cache supplements your primary database by removing unnecessary pressure on it, typically in the form of frequently-accessed read data. 
The cache itself can live in several areas, including in your database, in the application, or as a standalone layer.
The following are the three most common types of database caches:
- Database-integrated caches
  Some databases, such as Amazon Aurora, offer an integrated cache that is managed within the database engine and has built-in write-through capabilities. 
  The database updates its cache automatically when the underlying data changes. Nothing in the application tier is required to use this cache.
The downside of integrated caches is their size and capabilities. Integrated caches are typically limited to the available memory that is allocated to the cache by the database instance and can’t be used for other purposes, such as sharing data with other instances.
- Local caches
  A local cache stores your frequently-used data within your application. 
  This makes data retrieval faster than with other caching architectures because it removes network traffic that is associated with retrieving data.
  A major disadvantage is that among your applications, each node has its own resident cache working
in a disconnected manner. 
  The information that is stored in an individual cache node (whether it’s cached database rows, web content, or session data) can’t be shared with other local caches. 
  This creates challenges in a distributed environment where information sharing is critical to support scalable dynamic environments.
  Because most applications use multiple application servers, coordinating the values across them becomes a major challenge if each server has its own cache. 
  In addition, when outages occur, the data in the local cache is lost and must be rehydrated, which effectively negates the cache. 
  The majority of these disadvantages are mitigated with remote caches.
- Remote caches
  A remote cache (or side cache) is a separate instance (or separate instances) dedicated for storing the cached data in-memory. 
  Remote caches are stored on dedicated servers and are typically built on key/ value NoSQL stores, such as Redis and Memcached. 
  They provide hundreds of thousands of requests (and up to a million) per second per cache node. 
  Many solutions, such as Amazon ElastiCache for Redis, also provide the high availability needed for critical workloads.
  The average latency of a request to a remote cache is on the sub-millisecond timescale, which, in the order of magnitude, is faster than a request to a disk-based database. 
  At these speeds, local caches are seldom necessary. 
  Remote caches are ideal for distributed environments because they work as a connected cluster that all your disparate systems can utilize. 
  However, when network latency is a concern, you can apply a two-tier caching strategy that uses a local and remote cache together. 
  It’s typically used only when needed because of the complexity it adds.
  With remote caches, the orchestration between caching the data and managing the validity of the data is managed by your applications and/or processes that use it. 
  The cache itself is not directly connected to the database but is used adjacently to it.

### Caching patterns

When you are caching data from your database, there are caching patterns for Redis and Memcached that you can implement, including proactive and reactive approaches. 
The patterns you choose to implement should be directly related to your caching and application objectives.

Two common approaches are cache-aside or lazy loading (a reactive approach) and write-through (a proactive approach).
A cache-aside cache is updated after the data is requested. A write-through cache is updated immediately when the primary database is updated. 
With both approaches, the application is essentially managing what data is being cached and for how long.

A proper caching strategy includes effective use of both write-through and lazy loading of your data and setting an appropriate expiration for the data to keep it relevant and lean.

#### Cache-Aside (Lazy Loading)

A cache-aside cache is the most common caching strategy available. The fundamental data retrieval logic can be summarized as follows:
1. When your application needs to read data from the database, it checks the cache first to determine whether the data is available.
2. If the data is available (a cache hit), the cached data is returned, and the response is issued to the caller.
3. If the data isn’t available (a cache miss), the database is queried for the data. 
   The cache is then populated with the data that is retrieved from the database, and the data is returned to the caller.


This approach has a couple of advantages:
- The cache contains only data that the application actually requests,whichhelpskeepthecache size cost-effective.
- Implementing this approach is straightforward and produces immediate performance gains, whether you use an application framework that encapsulates lazy caching or your own custom application logic.

A disadvantage when using cache-aside as the only caching pattern is that because the data is loaded into the cache only after a cache miss, some overhead is added to the initial response time because additional roundtrips to the cache and database are needed.
    
    
    
#### Write-Through

A write-through cache reverses the order of how the cache is populated. Instead of lazy-loading the data in the cache after a cache miss, the cache is proactively updated immediately following the primary database update. The fundamental data retrieval logic can be summarized as follows:

1. The application, batch, or backend process updates the primary database.
2. Immediately afterward, the data is also updated in the cache.


The write-through pattern is almost always implemented along with lazy loading. If the application gets a cache miss because the data is not present or has expired, the lazy loading pattern is performed to update the cache.
The write-through approach has a couple of advantages:

- Because the cache is up-to-date with the primary database,there is a much greater likelihood that the data will be found in the cache. 
  This, in turn, results in better overall application performance and user experience.
- The performance of your database is optimal because fewer database reads are performed.

A disadvantage of the write-through approach is that infrequently-requested data is also written to the cache, resulting in a larger and more expensive cache.

## Cache Validity

  
You can control the freshness of your cached data by applying a time to live (TTL) or expiration to your cached keys. 
After the set time has passed, the key is deleted from the cache, and access to the origin data store is required along with reaching the updated data.

Two principles can help you determine the appropriate TTLs to apply and the types of caching patterns to implement. 
First, it’s important that you understand the rate of change of the underlying data. 
Second, it’s important that you evaluate the risk of outdated data being returned back to your application instead of its updated counterpart.

For example, it might make sense to keep static or reference data (that is, data that is seldom updated) valid for longer periods of time with write-throughs to the cache when the underlying data gets updated.
With dynamic data that changes often, you might want to apply lower TTLs that expire the data at a rate of change that matches that of the primary database. 
This lowers the risk of returning outdated data while still providing a buffer to offload database requests.

It’s also important to recognize that, even if you are only caching data for minutes or seconds versus longer durations, appropriately applying TTLs to your cached keys can result in a huge performance boost and an overall better user experience with your application.

Another best practice when applying TTLs to your cache keys is to add some time jitter to your TTLs. 
This reduces the possibility of heavy database load occurring when your cached data expires. 
Take, for example, the scenario of caching product information. 
If all your product data expires at the same time and your application is under heavy load, then your backend database has to fulfill all the product requests. 
Depending on the load, that could generate too much pressure on your database, resulting in poor performance. 
By adding slight jitter to your TTLs, a randomly-generated time value (for example, TTL = your initial TTL value in seconds + jitter) would reduce the pressure on your backend database and also reduce the CPU use on your cache engine as a result of deleting expired keys.


### Evictions


Evictions occur when cache memory is overfilled or is greater than the maxmemory setting for the cache, causing the engine selecting keys to evict in order to manage its memory. The keys that are chosen are based on the eviction policy you select.

By default, Amazon ElastiCache for Redis sets the volatile-lru eviction policy to your Redis cluster. 
When this policy is selected, the least recently used keys that have an expiration (TTL) value set are evicted. 
Other eviction policies are available and can be applied in the configurable maxmemory-policy parameter.
The following table summarizes eviction policies:

| Eviction Policy | Description |
| ——- | ——— |
|  allkeys-lru | The cache evicts the least recently used (LRU) keys regardless of TTL set. |
| allkeys-lfu  | The cache evicts the least frequently used (LFU) keys regardless of TTL set. |
| volatile-lru | The cache evicts the least recently used (LRU) keys from those that have a TTL set. |
| volatile-lfu | The cache evicts the least frequently used (LFU) keys from those that have a TTL set. |
| volatile-ttl | The cache evicts the keys with the shortest TTL set. |
| volatile-random  | The cache randomly evicts keys with a TTL set. |
| allkeys-random | The cache randomly evicts keys regardless of TTL set. |
| no-eviction | The cache doesn’t evict keys at all. This blocks future writes until memory frees up. |


A good strategy in selecting an appropriate eviction policy is to consider the data stored in your cluster and the outcome of keys being evicted.
Generally, least recently used (LRU)-based policies are more common for basic caching use cases. 
However, depending on your objectives, you might want to use a TTL or random-based eviction policy that better suits your requirements.

Also, if you are experiencing evictions with your cluster, it is usually a sign that you should scale up (that is, use a node with a larger memory footprint) or scale out (that is, add more nodes to your cluster) to accommodate the additional data. 
An exception to this rule is if you are purposefully relying on the cache engine to manage your keys by means of eviction, also referred to an LRU cache.



The basic paradigm when you query data from a relational database includes executing SQL statements and iterating over the returned ResultSet object cursor to retrieve the database rows. There are several techniques you can apply when you want to cache the returned data. However, it’s best to choose a method that simplifies your data access pattern and/or optimizes the architectural goals that you have for your application.

Iterating over the ResultSet cursor lets you retrieve the fields and values from the database rows. From that point, the application can choose where and how to use that data.


Cache a serialized ResultSet object that contains the fetched database row.

- Advantage:Whendataretrievallogicisabstracted(forexample,asinaDataAccessObjectorDAO layer), the consuming code expects only a ResultSet object and does not need to be made aware of its origination. 
- A ResultSet object can be iterated over, regardless of whether it originated from the database or was deserialized from the cache, which greatly reduces integration logic. 
- This pattern can be applied to any relational database.
- Disadvantage:DataretrievalstillrequiresextractingvaluesfromtheResultSetobjectcursoranddoes not further simplify data access; it only reduces data retrieval latency.

Note: When you cache the row, it’s important that it’s serializable. The following example uses a CachedRowSet implementation for this purpose. When you are using Redis, this is stored as a byte array value.

The following code converts the CachedRowSet object into a byte array and then stores that byte array as a Redis byte array value. The actual SQL statement is stored as the key and converted into bytes.


One advantage of storing the SQL statement as the key is that it enables a transparent caching abstraction layer that hides the implementation details. The other added benefit is that you don’t need to create any additional mappings between a custom key ID and the executed SQL statement.
At the time of setting data in the Redis, you are applying the expiry time, which is specified in milliseconds.
For lazy caching/cache aside, you would initially query the cache before executing the query against the database. To hide the implementation details, use the DAO pattern and expose a generic method for your application to retrieve the data.



Assuming that your application framework can’t be used to abstract your caching implementation, how do you best cache the returned database data?





缓存介质

1. 内存
2. 磁盘
3. 数据库

## Type

### Local Cache



#### Simple Map



#### Ehcache



#### Guava Cache



#### Spring Cache

### Distribution Cache

#### Memcached

#### Redis



## Cache Issues

### 缓存雪崩

A lot of keys expire at the same time or cache server down abnormally during numerous concurrent requests.

是指缓存中数据大批量到过期时间，而查询数据量巨大，引起数据库压力过大甚至宕机

#### How to fix it
**Circular Breaker:**

Avoid too many requests accessing DataBases.


**Prevent Beforehand:**

Using random expire timestamps(or never expire).

Using cluster cache servers.







### 缓存穿透

是指缓存和数据库中都没有的数据，而用户不断发起请求，缓存没有起到压力缓冲的作用

> 解决方案：
>
> - 接口层增加校验，如用户鉴权校验，id做基础校验，id<=0的直接拦截；
> - 从缓存取不到的数据，在数据库中也没有取到，这时也可以将key-value对写为key-null，缓存有效时间可以设置短点，如30秒（设置太长会导致正常情况也没法使用）。这样可以- 防止攻击用户反复用同一个id暴力攻击
> - 针对key做布隆过滤器
> - 采用灰度发布的方式，先接入少量请求，再逐步增加系统的请求数量，直到全部请求都切换完成
> - 提前缓存预热或定时预热

- assert illegal requests
- BloomFilter
- cache Null/Default values




### 缓存击穿

是指缓存中没有但数据库中有的数据（一般是缓存时间到期），这时由于并发用户特别多，同时读缓存没读到数据，又同时去数据库去取数据（sql又慢），引起数据库压力瞬间增大，造成过大压力。缓存失效时瞬时的并发打到数据库

> 解决方案：
>
> - 设置热点数据永远不过期
> - 针对key做加互斥锁  解决-第一次缓存大并发问题 单jvm级别加双重锁double-check， （使用分布式锁会限制并发能力，所以使用单jvm级别限制，特殊场景支付除外）

### 全量缓存

在处理超大规模并发的场景时，由于并发请求的数量非常大，即使少量的缓存穿透，也有可能打死数据库引发雪崩效应。

> 解决方案：
>
> - 对于这种情况，我们可以缓存全量数据来彻底避免缓存穿透问题
>
> canal订阅binlog异步更新缓存

### 缓存并发竞争

多客户端同时并发写一个key，可能本来应该先到的数据后到了，导致数据版本错了；或者是多客户端同时获取一个 key，修改值之后再写回去，只要顺序错了，数据就错了

- 如果对这个key操作，不要求顺序

这种情况下，准备一个分布式锁，大家去抢锁，抢到锁就做set操作即可，比较简单。

- 如果对这个key操作，要求顺序

假设有一个key1,系统A需要将key1设置为valueA,系统B需要将key1设置为valueB,系统C需要将key1设置为valueC. 期望按照key1的value值按照 valueA-->valueB-->valueC的顺序变化。这种时候我们在数据写入数据库的时候，需要保存一个时间戳。假设时间戳如下

```
系统A key 1 {valueA  3:00}
系统B key 1 {valueB  3:05}
系统C key 1 {valueC  3:10}
复制代码
```

那么，假设这会系统B先抢到锁，将key1设置为{valueB 3:05}。接下来系统A抢到锁，发现自己的valueA的时间戳早于缓存中的时间戳，那就不做set操作了。以此类推。

- 利用队列，将set方法变成串行访问也可以



## Consistency

### Cache Aside Pattern

- Read：先读缓存，如果没有命中，读数据库，再set回缓存
- Write：update DB, then delete Cache

### 为什么建议淘汰缓存，不修改缓存

Delete 幂等

在1和2两个并发写发生时，由于无法保证时序，此时不管先操作缓存还是先操作数据库，都可能出现：

- 请求1先操作数据库，请求2后操作数据库
- 请求2先set了缓存，请求1后set了缓存

导致，数据库与缓存之间的数据不一致。

### Cache Aside Pattern问题

Cache Aside 在高并发场景下也会出现数据不一致。 读操作A，没有命中缓存，就会到数据库中取数据v1。 此时来了一个写操作B，将v2写入数据库，让缓存失效； 读操作A在把v1放入缓存，这样就会造成脏数据。因为缓存中是v1，数据库中是v2

> 解决方案：
>
> - b线程：读缓存->未命中->上写锁>从db读数据到缓存->释放锁；a线程：上写锁->写db->删除缓存/改缓存->释放锁；
> - 看业务方能接受多长时间的脏数据，然后缓存就设置多久的过期时间。
> - 或者数据库更新成功后，用MQ去通知刷新缓存

> - canal订阅binlog，终极方案-还可以解决主从库同步问题



> - 降级或补偿方案或兜底方案



`Read Through`，其实就是让你对读操作感知不到缓存层的存在。通常情况下，你会手动实现缓存的载入，但`Read Through`可能就有代理层给你捎带着做了。

再比如，`Write Through`，你不用再考虑数据库和缓存是不是同步了，代理层都给你做了，你只管往里塞数据就行。

`Read Through`和`Write Through`是不冲突的，它们可以同时存在，这样业务层的代码里就没有同步这个概念了。爽歪歪。

至于`Write Behind Caching`，意思就是先落地到缓存，然后有异步线程缓慢的将缓存中的数据落地到DB中。要用这个东西，你得评估一下你的数据是否可以丢失，以及你的缓存容量是否能够经得起业务高峰的考验。现在的操作系统、DB、甚至消息队列如Kafaka等，都会在一定程度上践行这个模式。





## Reference

1. [Wiki - Cache (computing)](https://en.wikipedia.org/wiki/Cache_(computing))
2. [A Guide To Caching in Spring](https://www.baeldung.com/spring-cache-tutorial)
3. [缓存那些事 - 美团技术团队](https://tech.meituan.com/2017/03/17/cache-about.html)
4. [Thundering Herds & Promises](https://instagram-engineering.com/thundering-herds-promises-82191c8af57d)