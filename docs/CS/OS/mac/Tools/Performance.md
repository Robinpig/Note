## Introduction

macOS 上没有 `perf`，排查性能问题的工具链是另一套：底层是 Apple 自己暴露的计数器与采样接口，中层是一批命令行工具，上层是 Instruments 及其命令行版本 `xctrace`。它们不是 Linux 工具的移植，思路也不同——`perf` 以事件计数为核心，macOS 这套更强调**采样 + 功耗归因**（因为 Apple Silicon 上"性能"和"能耗"是同一个问题的两面）。

```shell
$ /usr/bin/xctrace version
xctrace version 16.0 (16A242d)
```

## Tiered Toolchain

按"从粗到细"排，实际排查顺序通常也是这样：

| 层次 | 工具 | 回答的问题 |
| :--- | :--- | :--- |
| 概览 | `top`、`vm_stat`、`iostat`、`memory_pressure` | 现在是谁在占资源 |
| 事件流 | `fs_usage`、`sc_usage`、`nettop` | 系统在持续做什么动作 |
| 采样 | `sample`、`spindump`、`xctrace record --template 'Time Profiler'` | 时间花在哪个函数 |
| 内存 | `leaks`、`malloc_history`、`heap` | 谁分配了没释放 |
| 功耗 | `powermetrics` | E/P 核驻留、C-state、各子系统耗电 |

## powermetrics

`powermetrics` 是 macOS 上最能体现 Apple Silicon 特点的工具。它读的是 SoC 内部的能量计数器，能分别给出 CPU、GPU、ANE（Apple Neural Engine）的估算功耗，以及 E 核与 P 核各自的频率分布与驻留比例：

```shell
sudo powermetrics --samplers tasks -i 1000 -n 5          # 按任务统计
sudo powermetrics --samplers cpu_power -i 1000           # CPU 功耗
sudo powermetrics --samplers tasks,cpu_power,gpu_power -i 5000
```

输出里几个字段值得单独记住：`E-Cluster` 与 `P-Cluster` 的 `active residency` 说明负载有没有跑到该跑的核上（一个后台任务长期占 P 核就是调度或 QoS 配置有问题），`package C-state` 的驻留比例反映空闲时的省电效率，`wakeups/sec` 则是耗电大户的经典指标——频繁唤醒比持续占用更费电。

它是少数**必须用 sudo** 的工具（读取能量计数器需要特权），而且输出信息密度很高，通常配合 `-i`（采样间隔）与 `-n`（次数）做短时抓取。

## fs_usage and sc_usage

`fs_usage` 打印实时的文件系统与 I/O 事件流，是"这个进程到底在读写什么"的最快答案：

```shell
sudo fs_usage                      # 全量事件流
sudo fs_usage -f filesys           # 只看文件系统
sudo fs_usage -f diskio            # 只看磁盘 I/O
sudo fs_usage -w -f filesys 1234   # 只跟某个进程
```

它不需要 DTrace 特权（走的是内核的 `kdebug` 通道），因此**在 SIP 开启的机器上仍然可用**——这是它相比 `iosnoop`、`iotop` 这类 DTrace 脚本的最大优势，见 [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)。

`sc_usage` 统计系统调用的次数与耗时，是 DTrace 不可用时的退路。

## Sampling: sample and spindump

`sample` 对进程做定时采样并给出调用树，适合"卡住了但不知道卡在哪"：

```shell
sample 1234                        # 采样 10 秒
sample 1234 30 -f result.txt       # 采样 30 秒并输出到文件
```

`spindump` 更偏系统级，常用于排查挂起与无响应（它也是系统在应用转圈时自动生成 spindump 报告的工具）：

```shell
sudo spindump 1234 -timelimit 30 -file /tmp/spin.txt
sudo spindump -noBinaryImages -timelimit 10
```

两者都需要目标进程的符号信息才能给出可读的函数名；自己的程序带上 dSYM，系统库的符号来自 `dyld` 共享缓存。

## Memory: leaks and malloc_history

```shell
leaks 1234                         # 扫描进程的泄漏
leaks --outputGraph=/tmp/memgraph 1234    # 生成内存图供 Xcode 打开
malloc_history 1234 -allBySize     # 按分配大小统计调用栈
```

`leaks` 的原理是扫描进程内存里"已分配但无指针引用"的块，所以它对循环引用无效（引用还在，只是逻辑上该释放了）——这类问题要靠 Instruments 的 Allocations 或 Xcode 的内存图调试器。堆内存口径的换算（16 KiB 页、`vm_stat` 与活动监视器对不上）见 [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)。

## xctrace

`xctrace` 是 Instruments 的命令行版本，能在无 GUI 的机器（或 CI）上跑同样的模板：

```shell
xctrace list templates             # 列出可用模板
xctrace list devices               # 列出可用设备
xctrace record --template 'Time Profiler' --attach 1234 --time-limit 10s -o out.trace
xctrace export --input out.trace --toc     # 导出目录结构
xctrace export --input out.trace --xpath '/trace-toc/run/data/table[@schema="time-profile"]'
```

本机实测有 **24 个模板**，其中排查通用性能问题最常用的是：

| 模板 | 用途 |
| :--- | :--- |
| `Time Profiler` | CPU 采样，找热点函数 |
| `Allocations` | 内存分配追踪 |
| `Leaks` | 泄漏检测 |
| `System Trace` | 系统调用、调度、虚拟内存事件的时序图 |
| `File Activity` | 文件读写 |
| `Network` | 网络请求 |
| `CPU Counters` | PMC 硬件计数器（Apple Silicon 上有限） |
| `App Launch` | 启动耗时分解 |

GUI 版的 Instruments 在 `/Applications/Xcode.app/Contents/Applications/Instruments.app`（随 Xcode 安装），`.trace` 文件可以在两端互通——命令行采集、GUI 分析是常见组合。

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)
- [Network](/docs/CS/OS/mac/Tools/Network.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [Development](/docs/CS/OS/mac/Development.md)

## References

1. [Instruments Help — Apple](https://help.apple.com/instruments/mac/current/)
2. [Improving your app's performance](https://developer.apple.com/documentation/xcode/improving-your-app-s-performance)
