## Introduction

InfluxDB 是一个用 Rust 编写的开源时间序列数据库，使用 Apache Arrow、Apache Parquet 和 Apache DataFusion 作为其基础构建模块。
这个最新版本（3.x）的 InfluxDB 专注于为各类观测数据（指标、事件、日志、追踪等）提供实时缓冲，
可通过 SQL 或 InfluxQL 查询，并以 Parquet 文件形式批量持久化到对象存储中，供其他第三方系统使用。
它可以在启用写前日志或完全基于对象存储（如果禁用写前日志）的模式下运行
（在后一种操作模式下，任何尚未持久化到对象存储的缓冲数据都可能存在数据丢失的风险）。

## Links

- [DataBases](/docs/CS/DB/DB.md)

## References
1.[influxdata](https://www.influxdata.com/)
