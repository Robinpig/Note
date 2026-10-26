## Introduction


TDDL(*Taobao Distributed Data Layer*) 是阿里巴巴开发的一款分布式数据库中间件，主要用于解决大规模数据访问和高并发场景下的数据库扩展问题
通过TDDL，可以实现数据库的读写分离、分表分库等高级功能，极大地提升了数据库的性能和稳定性

TDDL 作为中间件，其作用是根据路由规则，将 sql 路由到正确的分库、分表上去执行，再将结果进行汇总，返回给用户，对于用户，不需要了解 TDDL 的原理，可以像使用单库单表一样去使用分布式数据库。
在解析执行和封装这些类似于单库单表的 SQL 语句时，TDDL 有专门的组件来进行处理，这些组件就是核心的三层数据源，分别是 Matrix 层、Group 层以及 Atom 层
具体来说，从逻辑上来看：
- 最顶层是要进行分库分表才过渡到中间层的，分库分表所带来的问题是在 Matrix 层解决；
- 中间层是经过读写分离和主备切换处理，因此读写分离与主备切换的工作由 Group 层解决；
- 至于 Atom 层，它面对的是实实在在的每一个数据库，更多的工作在与对数据库的连接管理，比如说当数据库的 IP 地址发生改变时，Atom 层要动态感知，以免连接找不到地址


TDDL 的工作流程如下，client 发送一条 SQL 的执行语句，会优先传递给 Matrix 层。
由 Martix 解释 SQL 语句，优化，并根据查询条件路由到各个 group，转发 sql 进行查询，
各个 group 根据权重选择其中一个 Atom 进行查询，各个 Atom 再将结果返回给 Matrix，Matrix 将结果合并返回给 client。



TDDL、DRDS 和 PolarDB-X 是阿里巴巴集团及阿里云在分布式数据库领域逐步演进的三代技术产品，其关系可概括为 从中间件到云原生分布式数据库的技术升级路径

TDDL（内部中间件） → DRDS（云上中间件服务） → PolarDB-X（云原生分布式数据库）

| 产品	| 适用场景 |
| ---- | --- |
| TDDL	| 内部高并发简单查询，强规范约束的业务场景（如早期淘宝核心系统） |
| DRDS	| 云上分库分表需求明确、需灵活控制存储资源的业务（现逐步被 PolarDB-X 替代） |
| PolarDB-X	| 企业级分布式数据库需求，需强一致事务、透明扩展、混合负载支持的场景（如新零售、金融） |



## Links

- [Database Standards](/docs/CS/DB/MySQL/Database_Standards.md)
- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [TDDL repo](https://github.com/alibaba/tb_tddl)
