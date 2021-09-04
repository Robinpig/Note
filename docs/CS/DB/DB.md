# DB



Storage data layer

Cache Layer

Transport Layer

Execute Layer

Log Layer

Authority Layer

Tolerance  

concurrency 





# 一、基本概念

概念一：单库

![image.png](https://p6-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/77ad8039e17f4514a57c78f7321c7c36~tplv-k3u1fbpfcp-watermark.image)

概念二、分片

![image.png](https://p9-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/4c3c69165d094c8bb7fd664c8afa42a9~tplv-k3u1fbpfcp-watermark.image)

分片解决“数据量太大”这一问题，也就是通常说的“水平切分”。

一旦引入分片，势必面临“数据路由”的新问题，数据到底要访问哪个库。路由规则通常有3种方法：

**（1）范围：range**

优点：简单，容易扩展。

缺点：各库压力不均（新号段更活跃）。

**（2）哈希：hash**

优点：简单，数据均衡，负载均匀。

缺点：迁移麻烦（2库扩3库数据要迁移）。

**（3）统一路由服务：router-config-server**

优点：灵活性强，业务与路由算法解耦。

缺点：每次访问数据库前多一次查询。

大部分互联网公司采用的方案二：哈希路由。

**概念三、分组**

![image.png](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/ae8e3787bbb04083b8cb4a1e69995130~tplv-k3u1fbpfcp-watermark.image)

分组解决“可用性，性能提升”这一问题，分组通常通过主从复制的方式实现。

互联网公司数据库实际软件架构是“既分片，又分组”：

![image.png](https://p9-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/f529cc198bca41f6a88402ac55f727ff~tplv-k3u1fbpfcp-watermark.image)

数据库软件架构，究竟设计些什么呢，至少要考虑以下四点：

- 如何保证数据可用性
- 如何提高数据库读性能（大部分应用读多写少，读会先成为瓶颈）
- 如何保证一致性
- 如何提高扩展性

## 二、如何保证数据的可用性？

解决可用性问题的思路是：冗余。

如何保证站点的可用性？冗余站点。

如何保证服务的可用性？冗余服务。

如何保证数据的可用性？冗余数据。

数据的冗余，会带来一个副作用：一致性问题。

如何保证数据库“读”高可用？

冗余读库。

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

冗余读库带来什么副作用？

读写有延时，数据可能不一致。

上图是很多互联网公司mysql的架构，写仍然是单点，不能保证写高可用。

**如何保证数据库“写”高可用？**

冗余写库。

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

采用双主互备的方式，可以冗余写库。

冗余写库带来什么副作用？

双写同步，数据可能冲突（例如“自增id”同步冲突）。

如何解决同步冲突，有两种常见解决方案：

（1）两个写库使用不同的初始值，相同的步长来增加id：1写库的id为0,2,4,6...；2写库的id为1,3,5,7…；

（2）不使用数据的id，业务层自己生成唯一的id，保证数据不冲突；

阿里云的RDS服务号称写高可用，是如何实现的呢？

他们采用的就是类似于“双主同步”的方式（不再有从库了）。

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

仍是双主，但只有一个主提供读写服务，另一个主是“shadow-master”，只用来保证高可用，平时不提供服务。

master挂了，shadow-master顶上，虚IP漂移，对业务层透明，不需要人工介入。

这种方式的好处：

（1）读写没有延时，无一致性问题；

（2）读写高可用；

不足是：

（1）不能通过加从库的方式扩展读性能；

（2）资源利用率为50%，一台冗余主没有提供服务；

画外音：所以，高可用RDS还挺贵的。

三、如何扩展读性能？

提高读性能的方式大致有三种，第一种是增加索引。

这种方式不展开，要提到的一点是，不同的库可以建立不同的索引。

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

如上图：

（1）写库不建立索引；

（2）线上读库建立线上访问索引，例如uid；

（3）线下读库建立线下访问索引，例如time；

第二种扩充读性能的方式是，增加从库。

这种方法大家用的比较多，存在两个缺点：

（1）从库越多，同步越慢；

（2）同步越慢，数据不一致窗口越大；

第三种增加系统读性能的方式是，增加缓存。

常见的缓存架构如下：

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

（1）上游是业务应用；

（2）下游是主库，从库（读写分离），缓存；

如果系统架构实施了服务化：

（1）上游是业务应用；

（2）中间是服务；

（3）下游是主库，从库，缓存；

![image.png](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

业务层不直接面向db和cache，服务层屏蔽了底层db、cache的复杂性。

不管采用主从的方式扩展读性能，还是缓存的方式扩展读性能，数据都要复制多份（主+从，db+cache），一定会引发一致性问题。

四、如何保证一致性？

主从数据库的一致性，通常有两种解决方案：

![image.png](https://p9-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/721d670f2af74a45ab0717c10eb3d520~tplv-k3u1fbpfcp-watermark.image)

如果某一个key有写操作，在不一致时间窗口内，中间件会将这个key的读操作也路由到主库上。

![image.png](https://p1-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/e0465e3cd2a74348ab32d503f6984cfa~tplv-k3u1fbpfcp-watermark.image)

**（2）强制读主**

![image.png](https://p1-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/cd3569cec88d4c74a17b9f4597db9ee9~tplv-k3u1fbpfcp-watermark.image)

“双主高可用”的架构，主从一致性的问题能够大大缓解。

第二类不一致，是db与缓存间的不一致。

![image.png](https://p9-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/d6dcdc1b6d64429bb6d962504708421e~tplv-k3u1fbpfcp-watermark.image)

这一类不一致，《[缓存架构，一篇足够？](http://mp.weixin.qq.com/s?__biz=MjM5ODYxMDA5OQ==&mid=2651961368&idx=1&sn=82a59f41332e11a29c5759248bc1ba17&chksm=bd2d0dc48a5a84d293f5999760b994cee9b7e20e240c04d0ed442e139f84ebacf608d51f4342&scene=21#wechat_redirect)》里有非常详细的叙述，本文不再展开。

另外建议，所有允许cache miss的业务场景，缓存中的KEY都设置一个超时时间，这样即使出现不一致，有机会得到自修复。

**五、如何保障数据库的扩展性？**

秒级成倍数据库扩容：

《[亿级数据DB秒级平滑扩容](http://mp.weixin.qq.com/s?__biz=MjM5ODYxMDA5OQ==&mid=2651962231&idx=1&sn=1b51d042c243f0b3ce0b748ddbcff865&chksm=bd2d0eab8a5a87bdcbe7dd08fb4c969ad76fa0ea00b2c78645db8561fd2a78d813d7b8bef2ac&scene=21#wechat_redirect)》

如果不是成倍扩容：

《[100亿数据平滑数据迁移,不影响服务](http://mp.weixin.qq.com/s?__biz=MjM5ODYxMDA5OQ==&mid=2651962270&idx=1&sn=3131888f29d0d137d02703a6dc91fa56&chksm=bd2d0e428a5a87547dfc6a0a292a7746ad50b74a078e29b4b8024633fa42db6ccc5f47435063&scene=21#wechat_redirect)》

也可能，是要对字段进行扩展：

《[1万属性，100亿数据，架构设计？](http://mp.weixin.qq.com/s?__biz=MjM5ODYxMDA5OQ==&mid=2651962219&idx=1&sn=30545c7a9f46fa74a61cc09323a6a8c9&chksm=bd2d0eb78a5a87a1c16b1d10fbb688adb2848345b70fa2fbc161b3a566c7c3e02adaccd5981e&scene=21#wechat_redirect)》

这些方案，都有相关文章展开写过，本文不再赘述。

**数据库软件架构，到底要设计些什么？**

- 可用性
- 读性能
- 一致性
- 扩展性

希望对大家系统性理解数据库软件架构有帮助。

对于主键与唯一索引约束：

（1）执行insert和update时，会触发约束检查；

（2）**InnoDB**违反约束时，会回滚对应SQL；

（3）**MyISAM**违反约束时，会中断对应的SQL，可能造成不符合预期的结果集；

（4）可以使用 insert … on duplicate key 来指定触发约束时的动作；

（5）通常使用 show warnings; 来查看与调试违反约束的ERROR；


 互联网大数据量高并发量业务，**为了大家的身心健康，请使用InnoDB**。



### 数据库优化

*在现实的开发环境之中所谓的数据库优化是不存在的，实际上所谓数据库的优化有很多层次。*

**1.语句上的优化**：尽量不要使用多表查询，不要频繁地使用各种神奇的统计查询，如果需要，建议使用子查询来代替（子查询只是一种折中方案，不是最好的，只是相对的，当数据量大的时候，所有认知的规则全部都将改变）。

**2.数据库的优化只能够体现在查询上**，而这个查询还是在认知范围内的数据量，例如使用索引，一旦使用索引，就不能够进行频繁的修改，例如：在主键往往会设置索引，但是从另一个角度，数据不应该进行物理删除，而要进行逻辑删除，只是为了保证索引不被重新创建；
-空间换时间，时间换空间：你的数据是否需要进行同步处理操作。

**3.当存在有多个RPC业务端的时候，可以考虑进行垂直拆库的做法**，这个时候只能够按照功能进行拆分，这个是需要强大的接口技术支持的。

**4.当分库也无法解决问题的时候就需要考虑数据库的水平拆分问题。**（认知范围内的唯一可以使用的最后方案）

**5.如果需要保证强大的查询性能**，那么就需要再次引入搜索引擎的概念进行分词处理。





#### 连接池实现原理

------

如果想要实现一个连接池，本质的实现思想就是一个Connection的对象数组，这个对象数组并不是无限开辟的，是有上限的，最初的数据库手工连接池的实现可以采用Map集合完成。在进行处理的时候，Map集合里面保存有全部连接池的可用连接（最小维持数、最大可打开数，最大等待时间），实现思路：

**-** 所有的连接对象被Map集合所管理，但是这个Map集合受到最大连接数的控制，如果现在需要获取数据库连接，发现已经没有可用的连接了，这个时候应该开辟新的连接，同时需要保证连接池是有上限的。

**-** 在获取连接的时候如果发现连接已经满了，这个时候应该追加一个等待唤醒机制，对于连接池的控制，如果发现没有连接，则等待新的连接到来，就可以采用线程的等待与唤醒机制来完成。

**-** 连接池中的连接使用完成后一定要关闭，这个关闭并不是彻底关闭数据库的连接，而是说将这个连接的可用性重新放回到连接池中，也就是说为连接池里设置一个标记（标记为true，就表示该连接可用，如果没有true的连接了，就表示连接池满了，当把连接放回去之后将这个标记设置为false，就表示有空余连接了）。

**-** 如果现在要去考虑连接池的实现，最好的做法就是使用ConcurrentHashMap子类来实现，这个类考虑到了并发性，并且也可以有很好的同步处理效果。
