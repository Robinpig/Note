## Introduction

TDengine 的接入面分三层：**原生驱动**（taosc + 各语言连接器，性能路径）、**taosAdapter 协议适配层**（吃 InfluxDB/Prometheus 生态，零改造路径）、**运维与迁移工具**（taosTools、taosX、taosKeeper）。加上企业版的 Explorer 图形界面和 IDMP 无代码平台，构成了它"简单易用"主张的实际内容。

## Connectors

原生驱动是 `taosc`（C/C++），跑在应用进程内，被各语言连接器内嵌。README-CN 列出的连接器仓库：

| 语言 | 仓库 |
| :-- | :--- |
| Java（JDBC） | `taosdata/taos-connector-jdbc` |
| Go | `taosdata/driver-go` |
| Python | `taosdata/taos-connector-python` |
| Node.js | `taosdata/taos-connector-node` |
| C#/.NET | `taosdata/taos-connector-dotnet` |
| Rust | `taosdata/taos-connector-rust` |

写入侧除普通 SQL 外还有三条批量通道：**Stmt**（预编译绑定参数）、**Schemaless**（Line Protocol / JSON / Telnet 格式直接写，背后走自动建表）、**CSV 导入**。

## taosAdapter：协议适配层

`taosAdapter` 是独立进程（Go 实现，编译需 Go ≥ 1.23），把 TDengine 的查询/写入能力包装成业界标准协议，**不改内核对接主流生态**：

| 协议 | 用途 |
| :-- | :--- |
| **RESTful（HTTP）** | 全分布式 REST 接口，taosc 可与 taosAdapter 交互构成完整 HTTP 通道；客户端可用 `Accept-Encoding` 协商 gzip/deflate |
| **WebSocket** | 长连接查询，压缩走 RFC 7692 |
| **InfluxDB Line Protocol** | 存量采集端（Telegraf 类 agent）零改造写入 |
| **Prometheus** | remote read/write 对接 Prometheus 生态 |
| **OpenTSDB** | 老监控系统的 telnet/JSON 写入 |

压缩按行业标准协商（REST 用 `Content-Encoding`，WebSocket 用 RFC 7692  permessage-deflate），见 [Compression](/docs/CS/DB/TDengine/Compression.md)。

## taosTools

`taosTools` 包含两个工具，默认**不编译**，需 `cmake .. -DBUILD_TOOLS=true`：

- **taosBenchmark**（曾名 taosdemo）：压测与测试数据生成，模拟多设备多采集点写入。
- **taosdump**：数据备份/导出。

压测方法论与参数见 [Operations](/docs/CS/DB/TDengine/Operations.md)。

## taosX：数据迁移

`taosX` 负责异构数据源与 TDengine 之间的搬运（xnode + Agent 架构），通信可在 `agent.toml` 配 `compression = true`。3.4 起支持**多 xnode 部署实现 HA**（企业版）。有一条升级警告：**在用 taosX 的非数据源功能或 taosX-Agent 时不要升到 3.4**（官方称后续版本恢复），只使用数据源功能的必须在升级后删除并重建所有数据摄入任务。

## taosKeeper

`taosKeeper` 采集导出 taosd 自身的运行指标（独立进程，`-DBUILD_KEEPER=true` 编译），对接 Prometheus 抓取做集群监控。运行态观察的另一半在库内：`INFORMATION_SCHEMA` 系统表（如 `INS_LAST_CACHE_STATS`）直接 SQL 查 vgroup 级缓存状态，见 [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)。

## Explorer 与 IDMP

- **TDengine TSDB-Explorer**：图形化管理与查询工具（企业版向，3.4 起支持 OAuth 2.0 / OIDC 1.0 SSO）。
- **TDengine IDMP**：工业数据管理平台，无代码方式配置实时分析与流计算——不写 SQL、不关心底层语法即可搭分析面板。这是 TDengine 从"数据库"向"平台"延伸的产品线。

## TDengine Cloud

托管形态（cloud.taosdata.com），免安装部署，README 首推的体验入口。与本地集群功能基本对齐，差异在运维侧。

## Links

- [TDengine](/docs/CS/DB/TDengine.md)
- [Architecture](/docs/CS/DB/TDengine/Architecture.md)
- [Compression](/docs/CS/DB/TDengine/Compression.md)
- [Operations](/docs/CS/DB/TDengine/Operations.md)
- [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)

## References

1. [taosdata/TDengine README-CN（连接器与构建）](https://github.com/taosdata/TDengine/blob/main/README-CN.md)
2. [TDengine TSDB 3.4 Release Notes（taosX HA / Explorer SSO）](https://tdengine.com/?p=30263/)
3. [技术内幕：数据压缩（传输压缩）](https://docs.tdengine.com/internals/compress/)
