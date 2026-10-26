## Introduction

TDengine 官方对压缩效果的表述是"压缩率通常在 10% 以内，某些场景更高"——这是它敢说"存储空间不及通用数据库 1/10"的底气来源。压缩分两个阶段：**一阶段**按列类型选专用编码，**二阶段**把一阶段输出当无差别二进制再过一遍通用压缩算法。此外还有浮点**有损压缩 TSZ**、传输压缩和硬件加速库替换三条支线。

本页把每条编码的适用类型、二阶段算法清单、有损开关和加速机制讲清楚。版本锚点 **3.4.x**，来源为官方技术内幕「数据压缩」。

## Two-Stage Compression

一阶段的前提是**列式存储 + 块以子表为单位**：每个数据块只含一个子表的数据，压缩按块进行、按列分别进行。一阶段针对时序数据"相邻值相近"的稳定性做差分类重编码，二阶段再用通用算法消除块间信息冗余——官方对两者分工的概括是"一阶段管局部数据简化，二阶段管整体重叠消除"。

## Primary Compression

按数据类型选编码：

| 类型 | 一阶段编码 | 原理 |
| :-- | :-- | :--- |
| **timestamp** | 相邻差分 | 采集频率固定，相邻时间戳差值小且稳定，存差值比存原值省 |
| **boolean** | 位紧致 | 一个布尔 1 bit，一字节存 8 个 |
| **数值（整数）** | **ZigZag** | 有符号整数映到无符号：符号位移到低位、负数取反、正数不变，把有效位聚拢、增加前导零，利好后一阶段压缩 |
| **float / double** | **delta-delta（二阶差分）** | 注意：不是广泛流传的 Gorilla XOR——官方文档明确浮点用 delta-delta |
| **string** | 字典压缩 | 高频长字符串替换为短标识 |

## Secondary Compression

一阶段之后按无差别二进制再过一层通用压缩，可选 **LZ4、ZLIB、ZSTD、XZ** 等，按压缩率与写速度的权衡选。建库参数 `COMP` 控制：**默认 2 = 两阶段压缩**，1 = 只做一阶段，0 = 不压缩。

## Lossy Compression：TSZ

浮点数据提供有损模式，算法名 **TSZ**：基于预测模型，用前序数据点的趋势预测后续点，压缩率远超无损。适用前提是"采集精度高、业务关心的精度低"——传感器报 6 位小数、应用只看 2 位的场景。开有损前要确认下游是否依赖原始精度。

## Hardware-Accelerated Libraries

二阶段默认链接 TDengine **自带的静态** zlib/zstd/lz4 实现。Linux 下允许在启动时把默认实现替换成硬件加速版本（如 Intel QAT/IAA 加速的 zlib、ISA-L 的 libz、ARM SVE 优化的 zstd），**不需要改任何 SQL**：

| 环境变量 | 作用 |
| :-- | :--- |
| `TAOS_COMPRESS_ACCEL` | 加速库所在目录 |
| `TAOS_COMPRESS_ACCEL_ZLIB` | `libz.so` 全路径 |
| `TAOS_COMPRESS_ACCEL_ZSTD` | `libzstd.so` 全路径 |
| `TAOS_COMPRESS_ACCEL_LZ4` | `liblz4.so` 全路径 |

优先级：某个库配了全路径就只按全路径加载；只有全路径未配、配了目录时才从目录找。加载失败自动回退自带静态实现。BRIN（head 文件）记录本身也是列式压缩的，这部分不吃这个开关。

## Transmission Compression

传输侧压缩是独立的一层，`taos.cfg` 的 `compressMsgSize` 控制原生连接（taosc → 服务端）：

- `0`：关闭。
- `1`：开启，只压缩 > 1 KB 的数据包（常用档）。
- `2`：所有数据包都压缩。

走 taosAdapter 的 RESTful/WebSocket 则按行业标准协议协商：REST 客户端发 `Accept-Encoding`，服务端回 `Content-Encoding`；WebSocket 按 RFC 7692。taosX / taosX Agent 的通信在 `agent.toml` 里配 `compression = true` 开启。

## Links

- [TDengine](/docs/CS/DB/TDengine/TDengine.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [Data_Model](/docs/CS/DB/TDengine/Data_Model.md)
- [Storage Format](/docs/CS/BigData/Storage_Format.md)

## References

1. [技术内幕：数据压缩](https://docs.tdengine.com/internals/compress/)
2. [TDengine SQL：CREATE DATABASE 参数](https://docs.taosdata.com/reference/taos-sql/database/)
