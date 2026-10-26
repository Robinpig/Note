## Introduction

MyCAT 的读写分离不是一个开关，而是 dataHost 上三组枚举值（`balance`、`writeType`、`switchType`）加一个心跳语句的组合。配错的常见后果不是报错，而是**读流量打进了主库、或者主库挂了不切换**——静默地错。本页把三组值的语义、心跳检测的原理、Galera 集群的支持，以及 MyCAT2 在连接管理上的补丁逐条讲清。配置骨架见 [Configuration](/docs/CS/DB/MyCat/Configuration.md)。

## The Three Switches

### balance: Who Serves Reads

`balance` 决定读请求的分发策略（1.x 语义）：

| 值 | 行为 |
| :--- | :--- |
| 0 | 不开启读写分离，读和写都走当前可用的 writeHost |
| 1 | 全部 readHost 与 stand by writeHost 参与 select 的负载均衡 |
| 2 | 所有读操作随机分发到 writeHost 和 readHost |
| 3 | 所有读请求随机分发到 writeHost 下的多个 readHost（不含写主机自身） |

0 是「先不分离」的过渡态——同一条 schema.xml 里，可以先 balance=0 单主跑，再把读切出去。2 与 3 的差别只在**主库是否承担读**：2 是主从一起随机，3 是只读从库。对写后有强读一致性要求的业务（写入后立刻要读到），2 和 3 都有主从延迟导致的读旧风险，需要在业务层规避（写后读强制走主或接受最终一致）。

### writeType: Which Master Serves Writes

| 值 | 行为 |
| :--- | :--- |
| 0 | 所有写操作发送到配置的第一台 writeHost；第一台故障时切换到第二台，恢复后再切回 |
| 1 | 写操作随机发送到配置的多个 writeHost（多主架构） |

双主多从（互为主从）的 MySQL 架构下才用得上 1；常规一主多从就是 0。

### switchType: Failover Policy

| 值 | 行为 |
| :--- | :--- |
| -1 | 不自动切换（写主机故障 = 服务中断，等人工） |
| 1 | 自动切换（默认）——只判断「实例是否活着」 |
| 2 | 基于 MySQL 主从同步状态决定是否切换（看复制延迟/状态） |
| 3 | 基于主从同步状态 + 半同步复制状态决定是否切换 |

-1 是故意留的人工闸门：切换本身有数据风险（旧主带着孤立数据回来），对数据一致性敏感的场景宁可不自动切。2 和 3 把切换决策从「MySQL 活着吗」升级为「这台从库的数据跟得上吗」——**活着的从库不等于可用的从库**，复制断了它还活着。

## Heartbeat: The Detection Mechanism

dataHost 下的 `<heartbeat select="select user()">` 是 MyCAT 对后端实例的存活探测语句——轻量、无副作用、任何 MySQL 都能答。探测失败触发摘除与（按 switchType）切换。

必须想清楚的两点：

1. **心跳只证明进程活着**：`select user()` 永远成功不能说明复制健康、负载健康。switchType 2/3 正是在此之上追加复制状态检查。
2. **心跳是 MyCAT 单方面的判断**：后端 MySQL 对自己的状态（read_only、复制延迟）没有话语权。MyCAT2 的修复记录里反复出现「heartbeat query read_only」「忽略主从心跳异常导致主从切换失败」「MHA/MGR replica 无法切换主」——这些都是检测与真实状态不一致的教训。1.x 部署里，**心跳间隔与切换阈值要和 DBA 的 MHA/MGR 体系对齐**，否则两套系统可能同时判故障、切换方向却不同。

## Galera and Multi-Master Clusters

官方特性清单明确支持 **Galera for MySQL 集群、Percona Cluster、MariaDB Cluster**——这类多主同步复制集群没有「一主多从」的拓扑，MyCAT 的用法是把多个 writeHost 都配上（writeType=1 随机写），读也在集群内分发。 Galera 的价值是**任一节点可写、无延迟**，恰好补上「balance=2/3 + 主从延迟」的读旧问题；代价是集群自身的写入冲突处理与节点数上限。

## MyCAT2: Connection Lifecycle

MyCAT2 在连接与会话管理上补了 1.x 没有的机制（均出自其 release notes）：

- **后端连接自动回收**：`removeAbandonedTimeoutSecond` 控制，**默认 180 秒**——不活动（无 SQL 操作）的后端连接自动回收，防「MySQL 侧已关、MyCAT 侧旧连接无响应」的幽灵连接。
- **会话粘滞**：支持设置会话粘滞时间，同一会话的后续请求倾向落到同一后端——读写分离下缓解主从延迟的另一种思路（与业务层「写后读走主」互补）。
- **连接泄露检查**：数据源配置项 + debug 级日志，用于排查「后端连接只增不减」。
- **JDBC 查询超时可配**（早期版本默认 0 即不超时）。
- **修复项即风险清单**：「XA 事务不跨库时升级成了 XA 事务」「不跨库事务保留后端连接导致读写分离失败」「主从心跳异常导致切换失败」——这些都是 1.x 时代会静默踩中的坑，2.x 逐个修掉。

## Operational Checklist

把本页压缩成上线前的检查项：

1. `balance` 与业务读写模型匹配（写后读有强一致要求的，想清楚 2/3 的延迟风险）
2. `writeType` 与 MySQL 拓扑匹配（双主才用 1）
3. `switchType` 是 -1 还是 1/2/3，与 DBA 的故障预案一致
4. 心跳语句是 `select user()`，探测间隔与切换阈值经过演练
5. readHost 有多个时，确认它们复制健康（活 ≠ 可读）
6. MyCAT2 部署确认 `removeAbandonedTimeoutSecond` 与业务长事务时长的关系

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Configuration](/docs/CS/DB/MyCat/Configuration.md)
- [SQL_Routing](/docs/CS/DB/MyCat/SQL_Routing.md)
- [Transactions](/docs/CS/DB/MyCat/Transactions.md)

## References

1. [MyCAT 官方网站 · 关键特性（心跳切换、读写分离、Galera）](https://www.mycat.org.cn)
2. [MyCATApache/Mycat2 Releases（连接回收、会话粘滞、主从切换修复）](https://github.com/MyCATApache/Mycat2/releases)
3. [MyCATApache/Mycat-Server（schema.xml 默认配置）](https://github.com/MyCATApache/Mycat-Server)
