## Introduction

MyCAT 1.x 的全部行为由三个 XML 文件决定：**server.xml**（我是谁、监听什么）、**schema.xml**（数据在哪、怎么分）、**rule.xml**（按什么算法分）。三者用 DTD 约束（rule.xml 引用 `rule.dtd`），改动后大多可以热加载而不重启。MyCAT2 把这三件套换成了 JSON（datasource.json、user.json 等），本页以 1.6 为主线、末尾给出 2.x 的对照。出厂默认文件就在源码树里，是最好的一手参考：`Mycat-Server/src/main/resources/` 下的 `server.xml`、`schema.xml`、`rule.xml`（另有一份 `zkconf/` 是 ZooKeeper 化配置的变体）。

## server.xml: Identity and Kernel Knobs

server.xml 只有两类元素：`<system>`（MyCAT 自身参数）与 `<user>`（逻辑用户）。

```xml
<system>
    <property name="defaultSqlParser">druidparser</property>
</system>
<user name="mycat">
    <property name="password">mycat</property>
    <property name="schemas">user,pay</property>
</user>
```

- `<system>` 里的 `defaultSqlParser` 决定 SQL 解析器，出厂默认 **druidparser**（基于 Druid）。这个值直接影响哪些 SQL 能被正确解析——解析失败的路由退化是很多「莫名其妙全库扫描」的根因。
- `<user>` 定义客户端能看到的逻辑库集合（`schemas`）与密码。多租户方案的做法就是给不同 user 挂不同 schemas。

1.6 的 `<system>` 还承载一批内核旋钮（端口、处理器数、缓冲区、事务一致性级别、序列处理器类型等），不同小版本间有增减；**排查行为差异时以所部署版本的 DTD 与实际文件为准**，不要照抄网上升级帖。

## schema.xml: Where the Data Lives

schema.xml 回答四个层次的问题：逻辑库有哪些表、表落在哪些节点、节点指向哪个物理库、物理库的主从长什么样。

```xml
<schema name="TESTDB">
    <table name="customer" dataNode="dn1,dn2,dn3" rule="rule1"/>
    <table name="orders" dataNode="dn1,dn2,dn3" rule="rule2"
           primaryKey="id" autoIncrement="true"/>
    <table name="global_dict" dataNode="dn1,dn2,dn3" type="global"/>
    <table name="order_items" dataNode="dn1,dn2,dn3" rule="rule2">
        <childTable name="order_items" joinKey="order_id" parentKey="id"/>
    </table>
</schema>

<dataNode name="dn1" dataHost="localhost1" database="db1"/>
<dataNode name="dn2" dataHost="localhost1" database="db2"/>
<dataNode name="dn3" dataHost="localhost1" database="db3"/>

<dataHost name="localhost1" maxCon="1000" minCon="10" balance="0"
          writeType="0" dbType="mysql" dbDriver="jdbc" switchType="1">
    <heartbeat select="select user()"/>
    <writeHost host="master" url="jdbc:mysql://127.0.0.1:3306" user="root" password="xxx"/>
    <readHost host="slave1" url="jdbc:mysql://127.0.0.1:3307" user="root" password="xxx"/>
</dataHost>
```

### table 的四种形态

| 形态 | 配置 | 行为 |
| :--- | :--- | :--- |
| 分片表 | `rule="ruleX"` + dataNode 列表 | 按算法路由，跨分片查询要归并 |
| 全局表 | `type="global"` | 每个节点存全量，改一个地方要广播到所有节点 |
| ER 子表 | 内嵌 `<childTable joinKey parentKey>` | 与父表落同一分片，把跨库 join 变成库内 join |
| 单表（非分片） | 单个 dataNode、无 rule | 只落一个节点，退化为普通代理 |

`<childTable>` 的语义值得单独说：`joinKey` 是子表上的关联列，`parentKey` 是父表主键。路由父表时，MyCAT 用父表的分片结果反推子表所在分片——**子表不需要自己的分片算法**，这是 ER 分片的核心，也是「让 join 不跨库」最常用的手段。

### dataHost 的连接与主从

`<dataHost>` 是物理集群的抽象，属性分三组：

- **连接池**：`maxCon` / `minCon` 控制后端 JDBC 连接上下限
- **读写行为**：`balance` / `writeType`——语义见 [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)
- **切换行为**：`switchType`（-1 不自动切换 / 1 自动 / 2 基于主从同步状态 / 3 基于主从 + 半同步状态）、`dbType`、`dbDriver`（native 或 jdbc）

`<heartbeat select="select user()">` 是故障检测语句；`<writeHost>` / `<readHost>` 声明主从，1.6 起 readHost 支持权重。**心跳只证明「MySQL 进程活着」**；switchType 2/3 才会进一步看复制状态。

## rule.xml: Sharding Algorithms

rule.xml 由两类元素构成：`<tableRule>`（列 → 算法的绑定）与 `<function>`（算法本体，含 class 与属性）。出厂文件自带 10 个 function 与 11 条 tableRule，下面是从源码树逐字核对的映射表：

| tableRule | 分片列 | algorithm → class | 关键属性（出厂值） |
| :--- | :--- | :--- | :--- |
| rule1 / rule2 | id / user_id | func1 → `PartitionByLong` | `partitionCount=8`、`partitionLength=128` |
| sharding-by-intfile | sharding_id | hash-int → `PartitionByFileMap` | `mapFile=partition-hash-int.txt` |
| auto-sharding-long | id | rang-long → `AutoPartitionByLong` | `mapFile=autopartition-long.txt` |
| mod-long | id | mod-long → `PartitionByMod` | `count=3` |
| sharding-by-murmur | id | murmur → `PartitionByMurmurHash` | `seed=0`、`count=2`、`virtualBucketTimes=160` |
| crc32slot | id | crc32slot → `PartitionByCRC32PreSlot` | `count=2` |
| sharding-by-month | create_time | partbymonth → `PartitionByMonth` | `dateFormat=yyyy-MM-dd`、`sBeginDate=2015-01-01` |
| latest-month-calldate | calldate | latestMonth → `LatestMonthPartion` | `splitOneDay=24` |
| auto-sharding-rang-mod | id | rang-mod → `PartitionByRangeMod` | `mapFile=partition-range-mod.txt` |
| jch | id | jump-consistent-hash → `PartitionByJumpConsistentHash` | `totalBuckets=3` |

`virtualBucketTimes=160` 的注释写明了机制：**一个物理节点被映射为 160 个虚拟节点**，这是一致性哈希扩容时不全局重排的关键。`murmur` 还支持两个可选属性：`weightMapFile`（节点权重，缺省权重 1）与 `bucketMapPath`（把虚拟节点映射 dump 到文件，仅调试用）。

源码 `io/mycat/route/function/` 目录下还有一批未进出厂 rule.xml 的算法类（`PartitionByDate`、`PartitionByHotDate`、`PartitionByRangeDateHash`、`PartitionByPattern`、`PartitionByPrefixPattern`、`PartitionByString`、`PartitionDirectBySubString`、`SlotFunction` 等），共 18 个分片算法类——完整语义与选型在 [Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md)。

自定义算法继承 `AbstractPartitionAlgorithm` 即可被 rule.xml 引用，这是官方宣称「分片规则丰富，插件化开发」的落地方式。

## sequence: Global ID Generation

分库分表后自增主键不再全局唯一，MyCAT 的方案是全局序列号，用法是 SQL 内嵌语法：

```sql
INSERT INTO `travelrecord` (`id`, user_id) VALUES ('next value for MYCATSEQ_GLOBAL', "xxx");
```

序列的供给方式（文件、数据库表、ZooKeeper、本地时间戳等）在 1.6 起可配置，`zk 序列`是 1.6 新增——用 ZooKeeper 保证多 MyCAT 实例拿到不重复的号段。ORM 的默认主键策略（AUTO_INCREMENT / 序列对象）都生成不了这个字符串，**接入时必须改成 MyCAT 的 next value 语法或应用层 ID 方案**。

## Hot Reload and ZooKeeper

1.6 支持配置 ZooKeeper 化（zkconf）：主从切换、zk 序列、配置本身都走 ZK，多实例共享一份配置。未上 ZK 的部署用命令行热加载（`reload @@config` 重新读取三件套），热加载的边界以所部署版本为准——**涉及连接池与 dataHost 拓扑的变更，保守做法是重启**。

## MyCAT2: JSON Configuration

MyCAT2 把配置拆成一组 JSON 文件，分布在 `conf/` 下，启动脚本 `bin/startup_nowrap.sh`（Windows 对应 `.bat`），默认端口 8066：

```json
{
  "dbType": "mysql",
  "type": "JDBC",
  "url": "jdbc:mysql://192.168.28.128:3306"
}
```

- 数据源是一个个 `*.datasource.json`（如上 `prototypeDs.datasource.json`），后端类型用 `dbType` 声明；ClickHouse 后端用 `ru.yandex.clickhouse` 驱动，仅支持 select/insert 且无自增值返回。
- 用户与权限在 `user.json`，支持 RSA 加密（后续版本加入）；权限拦截细化到 SQL 类型。
- 连接回收用 `removeAbandonedTimeoutSecond` 控制，**默认 180 秒**——不活动（无 SQL 操作）的后端连接自动回收，这是 1.x 没有的兜底。
- 分片算法在 MyCAT2 里也是可插拔的（与序列算法、负载均衡算法并列），甚至提供了基于 HTTP 调用的分片算法实现。

从 1.x 迁到 2.x 不是改配置格式那么简单：schema.xml 的逻辑库/表模型要重建成 JSON 元数据，rule.xml 的算法多数要重新声明，迁移路径见 [Operations](/docs/CS/DB/MyCat/Operations.md)。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Architecture](/docs/CS/DB/MyCat/Architecture.md)
- [Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md)
- [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)
- [Transactions](/docs/CS/DB/MyCat/Transactions.md)

## References

1. [Mycat-Server: src/main/resources/rule.xml](https://github.com/MyCATApache/Mycat-Server/blob/master/src/main/resources/rule.xml)
2. [Mycat-Server: src/main/resources/schema.xml](https://github.com/MyCATApache/Mycat-Server/blob/master/src/main/resources/schema.xml)
3. [Mycat-Server: src/main/resources/server.xml](https://github.com/MyCATApache/Mycat-Server/blob/master/src/main/resources/server.xml)
4. [MyCAT 官方网站](https://www.mycat.org.cn)
5. [MyCATApache/Mycat2（JSON 配置与 datasource）](https://github.com/MyCATApache/Mycat2)
