## Introduction

TDgpt 是 TDengine 内置的**时序数据分析智能体**：异常检测、预测、缺失补全这些计算密集型分析直接在数据库侧完成，对外只暴露 SQL 函数。它与"接个大语言模型"是两条路——官方明确说 TDgpt **不依赖大语言模型**，私有化部署下完整可用。

最容易被架构图误导的一点：**TDgpt 不在 `taosd` 进程里**。查询涉及时序高级分析时，vnode 把请求转发到独立组件 **Anode**，等待分析完成后把结果组装进查询执行流程。Anode 是 Python 类动态加载的运行时——部署 TDgpt 要单独装它，不是 taosd 的自带功能。

本页讲 Anode 架构、SQL 函数形态、内置算法与 TDtsfm 基础模型、自定义算法接入。版本锚点 **3.4.x**。

## Architecture

```
查询 ──▶ taosc ──▶ vnode ──(转发高级分析请求)──▶ Anode ──▶ 算法/模型
                │                                   │
                └────────(结果组装回查询流程)────────┘
```

- **Anode**：TDgpt 的分析执行体，启动时扫描约定目录下的 Python 代码文件，按类动态加载全部算法。也可以配 Adapter 请求 TimeGPT 这类云端时序 MaaS 服务。
- **SQL 即入口**：算法加载后用 SQL 调用，应用不做任何调整——`ANOMALY_WINDOW()`、`FORECAST()`、`FILL_HOLE()` 与普通函数同地位。
- **模型即服务**：预训练模型部署在数据库服务端，分析请求在库内完成推理，数据不出库。

## SQL Functions

| 函数 | 能力 | 形态 |
| :-- | :--- | :--- |
| **`FORECAST()`** | 时序预测：基于历史序列估算后续值 | `SELECT _rowts, FORECAST(i, 'algo=tdtsf,period=100') FROM meter WHERE ts >= '2024-01-01' AND ts < '2024-02-01'` |
| **`ANOMALY_WINDOW()`** | 异常检测：自动学习正常运行规律，标记偏离片段 | 异常窗口算子，`sensitivity` 参数控制敏感度 |
| **`FILL_HOLE()`** | 缺失补全：自动检测缺失时间点并按学到的规律补齐 | 查询内调用 |

**异常窗口**是 TDgpt 定义的一种特殊事件窗口：窗口起止由分析算法确定、而非用户表达式判定，用法与状态窗口/会话窗口一致，窗口内可用全部查询操作。与传统阈值告警的差别在于它**不依赖预设阈值**——读数仍在"正常范围"内但偏离历史规律的劣化信号（如冷水机能效系数的缓慢下滑）也能检出。

## Algorithms and Models

截至 3.3.6.0 官方列出的内置集合：

- **预测算法**：ARIMA、HoltWinters、LSTM、MLP，以及自研的 **TDtsfm（TDengine time series foundation model）v1**——Transformer 架构、在多样化工业数据上预训练，**历史数据不足时支持零样本启动**。
- **异常检测算法**（六种）：k-Sigma、IQR（四分位距）、Grubbs、SHESD、LOF（局部离群因子）、Autoencoder。
- 官方称覆盖"从经典统计模型到深度学习的完整算法库"，并可通过 Adapter 接入 TimeGPT 等云端 MaaS。

时序数据**分类**能力在 3.3.8 文档里标注为"研发测试中，2025 年 12 月发布"；**模型评估工具**（对多种算法做准确度/性能量化对比）是企业版能力。

## Custom Algorithms

TDgpt 是**可扩展**的：把自己的算法加进去后，应用照样用 SQL 调用，无需调整。接入方式：

1. 按算法开发者指南实现分析算法类（**仅支持 Python**）。
2. 把代码文件放进 Anode 约定的扫描目录。
3. 重启 Anode，用 SQL 命令更新算法缓存列表。
4. 刷新后即可在 SQL 中调用。

## Links

- [TDengine](/docs/CS/DB/TDengine/TDengine.md)
- [SQL](/docs/CS/DB/TDengine/SQL.md)
- [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)
- [Architecture](/docs/CS/DB/TDengine/Architecture.md)
- [Timeseries](/docs/CS/DB/Concept/Timeseries.md)

## References

1. [TDgpt：背景介绍](https://docs.taosdata.com/ai-and-advanced-analytics/tdgpt/introduction)
2. [基于 TDgpt 的运维异常检测（算法清单）](https://www.taosdata.com/tdengine-user-cases/28598.html)
3. [taosdata/TDengine tools/tdgpt](https://github.com/taosdata/TDengine/tree/main/tools/tdgpt)
