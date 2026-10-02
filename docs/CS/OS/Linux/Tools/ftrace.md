## Introduction

**ftrace**（function tracer）是 Linux 内核**官方内置的追踪框架**，自 2.6.27（2008）合入。它不是单个工具，而是一套由内核提供、通过 **tracefs**（早期挂在 debugfs）暴露控制接口的追踪基础设施：既能追踪内核函数调用与耗时，也能消费静态 tracepoint、动态 kprobe/uprobe、调度/中断/块设备等事件。

与外部工具相比，ftrace 的特点是**内核原生、无第三方依赖、可在无 [perf](/docs/CS/OS/Linux/Tools/Perf.md) 权限或极简环境使用**。它也是其他技术的底座：[perf](/docs/CS/OS/Linux/Tools/Perf.md) 的 tracepoint、[eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) 的 `kprobe`/fentry 挂载、历史上的 kprobes 事件注册，底层都大量复用 ftrace 维护的 tracepoint、函数挂钩与 ring buffer 机制。

早期 ftrace 依赖 `debugfs`，控制目录是 `/sys/kernel/debug/tracing`；现代内核使用独立的 **tracefs**，标准挂载点为 `/sys/kernel/tracing`，旧路径通常仍以兼容符号链接存在。

## tracefs Interface

先确认 tracefs 已挂载：

```bash
mount -t tracefs nodev /sys/kernel/tracing 2>/dev/null || \
mount -t debugfs nodev /sys/kernel/debug

cd /sys/kernel/tracing
ls
```

常用控制文件：

| 文件 | 作用 |
| --- | --- |
| `available_tracers` | 当前内核编译支持的 tracer 列表 |
| `current_tracer` | 当前启用的 tracer，如 `nop`/`function`/`function_graph` |
| `tracing_on` | `1` 开启写入、`0` 暂停写入（不卸载挂钩） |
| `trace` | 读取/清空环形缓冲区快照（`echo > trace` 清空） |
| `trace_pipe` | 流式读取事件，读取即消费，会阻塞 |
| `set_ftrace_filter` | 只追踪匹配的内核函数 |
| `set_ftrace_notrace` | 排除匹配的内核函数 |
| `set_ftrace_pid` | 只追踪指定 PID |
| `set_event` / `events/` | 启用/管理静态 tracepoint 事件 |
| `kprobe_events` | 动态创建/销毁 kprobe 事件 |
| `uprobe_events` | 动态创建/销毁用户态 uprobe 事件 |
| `buffer_size_kb` | 每 CPU ring buffer 大小 |
| `snapshot` | 保留/读取某时刻的追踪快照 |

直接操作 tracefs 适合理解原理；日常分析通常使用 `trace-cmd` 和图形前端 **KernelShark**。

## Tracers

`available_tracers` 中的能力取决于内核配置，常见 tracer：

| tracer | 用途 |
| --- | --- |
| `nop` | 不启用函数追踪，仅记录显式打开的 tracepoint/kprobe 事件 |
| `function` | 记录被调用的内核函数，开销较高，必须配合 filter/PID |
| `function_graph` | 模拟函数调用图，输出入口/返回与每函数耗时，适合梳理调用链 |
| `blk` | 块设备请求映射与延迟分析（现代系统更多用 blktrace/事件） |
| `wakeup` / `wakeup_rt` | 测量最高优先级/RT 任务从被唤醒到获得 CPU 的延迟 |
| `irqsoff` / `preemptoff` / `preemptirqsoff` | 定位关中断、关抢占的最长临界区 |
| `hwlat` | 检测硬件/固件导致的运行延迟 |

### function tracer

追踪指定函数（如虚拟内存相关的 `do_page_fault`）：

```bash
cd /sys/kernel/tracing
echo nop > current_tracer
echo do_page_fault > set_ftrace_filter
echo function > current_tracer
echo 1 > tracing_on
cat trace_pipe
# Ctrl-C 后恢复
echo 0 > tracing_on
echo > set_ftrace_filter
echo nop > current_tracer
```

输出字段包含进程名、PID、CPU、时间戳，以及被追踪函数和调用者。function tracer 的挂钩点来自编译期插桩：传统是 `-pg` 生成的 `mcount`，新工具链/内核是 `fentry`（`-mfentry`，x86 上挂钩在函数栈帧建立之前，更适合 live patch）。未启用时挂钩点被替换为 `nop`，全局函数追踪才会打开，因此**务必使用 `set_ftrace_filter` 缩小范围**。

### function_graph tracer

梳理某模块的调用层次：

```bash
echo function_graph > current_tracer
echo 'tcp*' > set_ftrace_filter
echo 1 > tracing_on
cat trace_pipe
```

输出以缩进表示调用深度，并给出每个函数的持续时间（`us`/`ns`），适合回答"某个系统调用最终进了哪些内核函数、时间花在哪一层"。

## Trace Events

静态事件来自内核中用 `TRACE_EVENT()` 定义的 tracepoint，分类位于 `events/`：

```bash
# 查看所有事件分类
ls events/

# 查看 sched 分类下的事件
ls events/sched/

# 查看某个事件的字段格式，便于写过滤表达式
cat events/sched/sched_switch/format

# 启用事件，nop tracer 下即可记录
echo 1 > events/sched/sched_switch/enable
echo nop > current_tracer
cat trace_pipe
```

也可按字段设置过滤器：

```bash
# 只看 next_pid 为 1234 的调度切换
echo 'next_pid == 1234' > events/sched/sched_switch/filter
```

常见事件类别包括 `sched`（调度切换/唤醒）、`irq`（中断）、`syscalls`（系统调用进入/返回）、`block`（块 I/O）、`net`（网络）、`kmalloc` 等。静态 tracepoint 属于稳定 ABI，比直接挂钩任意内核函数更可靠。

## Dynamic Events: kprobe and uprobe

ftrace 可以在没有预定义 tracepoint 的位置动态挂探针：

```bash
# 在 do_unlinkat 入口记录，参数为文件名指针（具体参数解析需结合架构/函数签名）
cd /sys/kernel/tracing
echo 'p:myunlink do_unlinkat' > kprobe_events
echo 1 > events/kprobes/myunlink/enable
cat trace_pipe

# 清理
echo > kprobe_events
```

`p:` 表示 kprobe（入口），`r:` 表示 kretprobe（返回点，可取返回值）；`kprobe_events` 支持读取参数、栈、返回值。用户态函数则使用 `uprobe_events`，需要指定可执行文件路径和偏移，适合对没有 USDT 探针的程序做临时观测。

动态探针强大但依赖具体符号，可能因内核配置、内联或版本变化失效；稳定场景应优先使用静态 tracepoint 或基于 BTF 的 fentry/fexit（见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)）。

## trace-cmd

`trace-cmd` 把散落的 tracefs 操作封装成命令，是最常用前端：

```bash
# 记录函数图：只看 ext4 文件系统函数，3 秒后写入 trace.dat
sudo trace-cmd record -p function_graph -g ext4_writepages sleep 3

# 记录调度和系统调用事件
sudo trace-cmd record -e sched -e syscalls sleep 5

# 文本方式回放
trace-cmd report

# 图形化查看（需要 kernelshark）
kernelshark trace.dat
```

常用参数：`-p` 指定 tracer，`-l` 设置函数 filter，`-g` 设置 function_graph 入口，`-e` 启用事件，`-P` 限定 PID。

## Overhead and Safety

- `function` 全局追踪会挂钩大量函数，生产环境只用于短时间窗口，并用 filter/PID 限定；
- `tracing_on=0` 只停止写入，不等于卸载探针；恢复时应清空 filter 并切回 `nop`；
- ring buffer 会丢事件以避免拖垮系统，事件丢失计数可在输出/统计中观察；
- 生产环境优先使用静态事件、`function_graph` 小范围 filter，或 eBPF 的聚合 map（在内核态先聚合，减少事件导出量）。

## ftrace vs perf vs eBPF

| 维度 | ftrace | perf | [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) |
| --- | --- | --- | --- |
| 定位 | 内核原生 tracefs 追踪框架 | 性能计数 + tracepoint/采样工具 | 安全可编程内核虚拟机 |
| 使用方式 | tracefs 文件 / trace-cmd | `perf record/top/script` | C/Clang + libbpf、BCC、bpftrace |
| 擅长 | 函数调用图、关中断/唤醒延迟、无依赖排障 | PMU 计数、采样火焰图、CPU cache/分支事件 | 事件过滤/聚合、自定义策略、网络与安全 |
| 可编程性 | 弱（配置/过滤表达式） | 中（脚本/注入受限） | 强（map、helper、循环、CO-RE） |
| 稳定性 | tracepoint 稳定，函数过滤依赖符号 | 事件稳定，PMU 依赖硬件 | tracepoint/fentry 稳定，kprobe 依赖符号 |

三者并非替代关系：ftrace 提供底层挂钩与事件框架，perf 提供硬件计数器和采样体系，eBPF 在前两者之上提供可编程处理。

## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [BPF](/docs/CS/OS/Linux/Tools/BPF.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [perf](/docs/CS/OS/Linux/Tools/Perf.md)
- [strace](/docs/CS/OS/Linux/Tools/strace.md)
- [DTrace](/docs/CS/OS/DTrace.md)

## References

1. [Kernel Documentation: ftrace (Function Tracer Redirection)](https://docs.kernel.org/trace/ftrace.html)
2. [Kernel Documentation: tracefs](https://docs.kernel.org/trace/ftrace.html#the-tracefs)
3. [trace-cmd Documentation](https://trace-cmd.org/)
4. [Brendan Gregg — ftrace Tools](https://www.brendangregg.com/linuxperf.html)
5. [Using the Linux Kernel Tracepoints](https://docs.kernel.org/trace/tracepoints.html)
