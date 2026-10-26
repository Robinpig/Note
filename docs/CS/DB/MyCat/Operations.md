## Introduction

MyCAT 的运维要分两条线讲：**1.6-RELEASE** 是 tar.gz 解包即用的经典形态，配置在 XML；**MyCAT2 v1.22-release** 是 zip + JSON，运维面多出 Prometheus  exporter、连接回收、权限拦截这些现代设施。本页覆盖两条安装路径、监控入口、1.6 已知要避开的功能清单、以及两个绕不开的问题：1.x 怎么迁 2.x、MyCAT 怎么被换掉。

## Installing MyCAT 1.6

官方安装路径（Linux）：

```bash
# 1. 下载
wget http://dl.mycat.org.cn/1.6-RELEASE/Mycat-server-1.6-RELEASE-linux.tar.gz
# 2. 解包
tar -zxvf Mycat-server-1.6-RELEASE-linux.tar.gz -C /usr/local/
# 3. 环境变量
echo 'export MYCAT_HOME=/usr/local/mycat' >> /etc/profile
echo 'export PATH=$PATH:$MYCAT_HOME/bin' >> /etc/profile
# 4. 改配置：server.xml 用户密码 → schema.xml 数据节点
# 5. 启动与探活
./bin/mycat start
./bin/mycat status
tail -f logs/wrapper.log
```

连接测试走 MySQL 协议：`mysql -h127.0.0.1 -P8066 -uroot`。管理口 9066 与数据口 8066 分开，防火墙策略要按两个端口规划。

## Installing MyCAT2

MyCAT2 从 GitHub Releases 拿 zip（当前线 **v1.22-release**），配置是一组 JSON：

```bash
unzip mycat2-1.22-release.zip -d /usr/local/mycat2
# 配置数据源：vim conf/datasources/prototypeDs.datasource.json
./bin/startup_nowrap.sh
mysql -h127.0.0.1 -P8066 -uroot
```

前置条件只有一条但很硬：**只支持 Java 8**（README 原文）。另外注意 License 在 2023.8 从 GPL 换成了 Apache-2.0，商用合规按版本分开评估。

## Monitoring

1.6 的监控有两层，都是官方自带：

- **命令行**：MySQL 协议下执行管理命令查看后端状态，如数据节点、心跳、数据库状态等（`show @@` 系列；`reload @@config` 热加载配置）
- **Web / mycat-eye**：对 MyCAT 自身性能、JVM 内存、线程、OS 的 CPU/内存/磁盘/网络做监控。1.6 起还有服务降级、SQL 黑名单等运维开关

MyCAT2 在监控上的增强：**Prometheus exporter**（早期版本修过「exporter 信息缺失导致起不来」的问题）、内置 `mycat.sql_log` 表记录 SQL 日志（`sqlTime` 列为 bigint）、PHP-Admin 管理界面、连接泄露的 debug 日志。生产上至少把四项接进监控：后端连接数（各 dataHost）、心跳异常次数、慢 SQL、MyCAT 进程内存（归并都在堆内/堆外）。

## Known Landmines in 1.6

README 与 release notes 里点名的坑，接入前逐条对账：

| 项 | 后果 | 规避 |
| :--- | :--- | :--- |
| 一个连接多条语句 | 直接不支持 | 客户端逐条执行 |
| 批处理插入（JDBC batch） | 已知 bug | 拆成单条或走 MyCAT2 |
| 堆外合并 | 已知 bug | 关闭相关选项 |
| 回滚事务连接泄露 | 后端连接只增不减 | 监控连接数 + 及时升级 |
| 解析器与 MySQL 行为差异 | SQL 能跑但结果/路由意外 | 上线前全量 SQL 回归 |

## Scaling and Migration

### 扩充分片

中间件扩分片的本质是**数据搬家**：新 dataNode 加入后，按新算法的映射把历史数据从旧节点迁到新节点，切换期间双写或停写。1.675 那条 `PartitionByLong` 分布变更说明了一件事——**换算法 = 重分布**，一致性哈希（murmur / jump consistent hash）只能减少节点增减时的迁移量，不能免掉迁移工程。MyCAT2 仓库带 `migrate` 模块，迁移工具链比 1.x 完整。

### 1.x 到 2.x

不是配置格式迁移那么简单，是一次换引擎：

- schema.xml 的逻辑库/表/dataHost 模型 → JSON 元数据
- rule.xml 的算法 → 2.x 的可插拔算法声明（含 HTTP 实现的算法）
- 执行语义差异：BKAJOIN、全局二级索引、条件下推的覆盖范围都不同，**SQL 回归要重做**
- 客户端侧：C# 客户端、会话粘滞、结果集缓存这些 2.x 特性可以顺便用上

升级前用双跑对比查询结果，是唯一可信的验证方式。

### Leaving MyCAT

什么时候该换掉它：SQL 灵活度要求越来越高（路由层天花板）、跨分片 join 成为常态（该上 Calcite 级优化或 NewSQL）、或者团队愿意为客户端引 jar（性能与特性都更好的选择在 JDBC 层）。路径大致是 MyCAT → ShardingSphere-Proxy（同形态、更活跃）或 → ShardingSphere-JDBC（去代理、少一跳）或 → TiDB/OceanBase（换数据库而非换中间件）。1.x 的数据导出、双跑校验、灰度切流，每一步都与上面 1.x→2.x 的迁移同构。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Configuration](/docs/CS/DB/MyCat/Configuration.md)
- [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)
- [ShardingSphere](/docs/CS/DB/ShardingSphere.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [MyCAT 教程与案例（安装步骤、运维命令）](https://mycat.org.cn/docs/tutorial)
2. [MyCATApache/Mycat2 Releases（1.22 安装与 Prometheus、PHP-Admin）](https://github.com/MyCATApache/Mycat2/releases)
3. [MyCATApache/Mycat-Server README（1.6 已知缺陷清单）](https://github.com/MyCATApache/Mycat-Server)
