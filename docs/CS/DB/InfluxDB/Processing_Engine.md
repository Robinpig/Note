## Introduction

Processing Engine 是 InfluxDB 3 最激进的创新：**数据库内嵌一个 Python VM**，用户写的 Python 脚本以插件形式在库内运行，替代 2.x 的 Flux + Task + Kapacitor 组合。插件是 1.x/2.x 时代 CQ、Task、Kapacitor、Telegraf 部分功能的正式继任者——计算直接发生在数据所在的地方，不用再部署外部管道。

## Trigger Types

插件不常驻，靠触发器调用。三种触发点：

| 触发点 | 时机 | 典型用途 |
| :-- | :-- | :--- |
| **WAL flush** | 每秒一次（可调），WAL 落盘时收到一批写入数据 | 实时变换、富化、写入侧过滤 |
| **Schedule** | 用户配置的定时器，毫秒到天 | 降采样、巡检、死信监控、定时报表 |
| **Request** | 绑定 HTTP 端点 `/api/v3/plugins/` | 自定义 API、按需计算、外部系统回调 |

创建触发器：

```shell
influxdb3 create trigger \
  --database mydb \
  --plugin-filename gh:influxdata/downsampler/downsampler.py \
  --trigger-spec "every:1h" \
  --trigger-arguments 'source_measurement=cpu,target_measurement=cpu_hourly,interval=1h' \
  cpu_hourly_downsample
```

`--trigger-spec` 三种写法对应三种触发点：`every:1h`（schedule）、`cron:...`、`request:downsample`（request）。`--plugin-filename` 支持 `gh:` 前缀直接从 GitHub 拉插件，也支持 `PLUGIN_DIR` 下的本地文件。

## Plugin API

插件就是普通 Python 文件，官方约定一个 handler 函数签名，典型能力：

- **写回数据库**：把处理结果直接写进任意 database / table；
- **查询数据库**：调用完整 SQL 引擎，含缓存 UDTF；
- **跨调用状态**：进程内 cache 在多次触发之间保持状态；
- **任意第三方库**：Python 生态的库都能用（HTTP、消息队列、ML 推理）；
- **打包管理**：`influxdb3 install package` 装依赖。

选 Python 而非自研 DSL 是明确的产品决策：普及度高，且 LLM 能可靠地写出短插件脚本——官方博客原话是把"LLM 生成的 Python 脚本做简单自动化"列为例行场景。

## Official Plugins

官方插件库（`gh:influxdata/...`）已覆盖常见时序计算：

| 插件 | 功能 | 关键参数 |
| :-- | :-- | :--- |
| **downsampler** | 按时间窗口聚合原始数据 | `interval` / `window` / `calculations`（支持 `field:func` 逐字段指定聚合函数）/ `tag_values` 过滤 |
| **resampler** | 抖动时间戳重采样到规则网格 | `interval` / `max_gap` / `mode=snap` |
| 通知类插件 | 告警外发 | 对接外部通道 |

downsampler 每条输出带 `record_count`、`time_from`、`time_to` 三个元数据列——压缩了多少、原数据覆盖哪个区间一目了然，回查 raw 时知道该查哪段。

## Operating Constraints

- **进程模型**：`process` 模式子进程承载插件。3.12 起 Processing Engine 可独立进程部署，自定义插件不会拖垮数据库主进程。
- **依赖安装**：插件声明的 Python 包在启动 `--plugin-dir` 后由 `influxdb3 install package` 安装；部分插件（如 resampler）依赖 scipy。
- **日志**：插件日志落在 `_internal` 数据库的 `system.processing_engine_logs` 表，按 `trigger_name` 过滤即可调试：

```sql
SELECT * FROM system.processing_engine_logs
WHERE trigger_name = 'cpu_hourly_downsample'
ORDER BY event_time DESC LIMIT 20;
```

- **可靠性（3.11 起）**：异步触发器并发上限、失败重试有界、WAL 触发器跳过空 flush。

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [Query](/docs/CS/DB/InfluxDB/Query.md)
- [Architecture](/docs/CS/DB/InfluxDB/Architecture.md)
- [Deployment](/docs/CS/DB/InfluxDB/Deployment.md)

## References

1. [InfluxDB 3 Processing Engine Documentation](https://docs.influxdata.com/influxdb3/core/plugins/)
2. [InfluxDB 3 Core and Enterprise GA](https://www.influxdata.com/blog/influxdb-3-oss-ga)
3. [Downsampler Plugin](https://docs.influxdata.com/influxdb3/enterprise/plugins/library/official/downsampler)
4. [Resampler Plugin](https://docs.influxdata.com/influxdb3/core/plugins/library/official/resampler)
