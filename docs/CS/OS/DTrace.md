## Introduction

**DTrace**（Dynamic Tracing）是一个跨内核态与用户态的**动态追踪框架**，由 Sun 的 Bryan Cantrill、Mike Shapiro、Adam Leventhal 设计，2003 年随 Solaris 10 发布，后移植到 FreeBSD、macOS（多年内置，后被移除）、NetBSD 等。它最大的创新是：**生产环境零风险的动态插桩**——探针（probe）默认关闭、开启时才被动态打补丁（live patch）挂上，关闭后恢复原指令，因此未使用时没有任何开销；用一种叫 **D** 的安全脚本语言描述"在哪个点、满足什么条件、采集什么"。

DTrace 的设计深刻影响了 Linux 的追踪体系：[ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) 提供内核函数/tracepoint 插桩底座，[eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) + BCC/bpftrace 则在思想与表达力上对标 DTrace（bpftrace 语言本身大量借鉴 D 语言），Linux 上的 BPF Compiler Collection 常被视为 DTrace 的对位实现。

## Probe and Provider

DTrace 的观测点统一抽象为 **probe**，命名为四段式：

```
provider:module:function:name
   提供者   模块    函数     探针名
```

| provider | 覆盖 |
| --- | --- |
| `syscall` | 系统调用入口/返回（`syscall::read:entry`） |
| `fbt`（Function Boundary Tracing） | 任意**内核函数**的入口/返回（动态插桩，最强大也最依赖具体内核） |
| `sdt` | 内核里静态埋点（对应 Linux 的 tracepoint 概念） |
| `profile` | 按固定频率采样，做 CPU profiling/on-CPU 火焰图 |
| `proc` | 进程/线程创建、exec、信号 |
| `io` | 块设备 I/O 起止、大小、时延 |
| `sched` | 调度切换、唤醒、排队 |
| `pid` | **用户态**任意函数/指令的动态插桩（`pid$target:::entry`） |
| `tcp/udp/ip` | 网络协议栈分层事件 |

`provider` 提供 probe 的实现机制；`module:function` 定位插桩位置；`name` 是具体事件（entry/return 或具名事件）。

## D Language

D 语言是一种受 awk/C 启发的、受限的安全语言：程序由若干 **probe 子句（clause）**组成，每个子句在探针命中时执行动作。

```c
/* 统计每个程序调用 read(2) 的次数 */
syscall::read:entry
{
    @[execname] = count();
}

/* 打印 read 的返回字节数分布（直方图聚合） */
syscall::read:return
/ arg1 > 0 /                  /* 谓词(predicate)：只看成功的 read */
{
    @bytes = quantize(arg1);  /* 内核侧聚合，2 的幂直方图 */
}

/* 谁在给进程 1234 发信号 */
proc:::signal-send
/ args[1]->pr_pid == 1234 /
{
    printf("signal %d from %s\n", args[2], execname);
}
```

关键安全设计（后来被 eBPF verifier 继承的思想源头）：

- **谓词（`/.../`）**：在探针上做条件过滤，避免无谓采集；
- **内核侧聚合（aggregation `@`）**：`count()`、`sum()`、`avg()`、`quantize()` 等在内核里先聚合计数，只在导出时把结果刷到用户态，避免逐事件拷贝——这正是 eBPF map 聚合的前身；
- **无循环、有限操作、不允许任意写内核内存**：保证脚本不会挂死或破坏系统，退出时自动卸载所有插桩。

内置变量如 `pid`、`tid`、`execname`、`timestamp`、`arg0..arg9`、`curthread`、`curpsinfo`、`probeprov/mod/func/name` 等。

## Dynamic Instrumentation

DTrace 能在运行时定位任意**未导出、未埋点**的函数（`fbt`、`pid` provider），通过动态改写指令（在函数入口/返回放跳转或断点）插桩，结束后还原。这带来：

- 优点：覆盖几乎一切内核/用户函数，无需重编译、无需重启、观测点可以即席指定；
- 代价：`fbt`/`pid` 探针依赖具体二进制的符号与版本，不稳定，跨版本脚本易失效——因此工程实践优先用稳定 provider（syscall/sdt/io/sched），把 `fbt` 当临时深挖手段。

这与 Linux 上"**优先 tracepoint/fentry，kprobe 动态挂钩作为补充**"的取舍完全一致，见 [eBPF hook 选择](/docs/CS/OS/Linux/Tools/eBPF.md)。

## Userspace Tracing

DTrace 的 `pid` provider 与 USDT（User-level Statically Defined Tracing）允许观测用户态：

- `pid$target::function:entry` 动态插桩任意用户函数；
- 应用可用 D 探针宏在代码里埋**静态 USDT 点**，编译后供 DTrace（或在 Linux 上由 eBPF 的 USDT 支持）消费。
- Linux 对位能力：eBPF 的 uprobes（动态，对应 pid provider）与 USDT（静态），见 [ftrace 动态事件](/docs/CS/OS/Linux/Tools/ftrace.md)。

## DTrace vs Linux ftrace/eBPF

| 维度 | DTrace | [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) | [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) |
| --- | --- | --- | --- |
| 起源 | Solaris（2003） | Linux 2.6.27（2008） | Linux 3.18（2014） |
| 交互语言 | D（clause + predicate + aggregation） | tracefs 配置 / trace-cmd | C/Clang；bpftrace（类 D） |
| 内核/用户探针 | fbt + pid + USDT | 函数追踪 + kprobe/uprobe | kprobe/uprobe/fentry/USDT |
| 安全模型 | 受限 D 语言 + 无循环 | 配置式、过滤表达式 | verifier 静态证明 + helper |
| 内核侧聚合 | aggregation `@` | 无（事件流） | map/percpu 聚合 |
| 数据面能力 | 以观测为主 | 观测 | 观测 + 可改写网络包/安全策略/调度 |
| 平台 | Solaris/BSD/macOS(历史) | Linux | Linux（也扩展到 Windows 等） |

DTrace 解决了"如何在生产系统安全、低开销、即席地回答任意内核问题"，其动态插桩 + 安全语言 + 内核侧聚合的三位一体，是现代 Linux BPF/bpftrace 工具链的直接思想来源。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [BPF](/docs/CS/OS/Linux/Tools/BPF.md)
- [perf](/docs/CS/OS/Linux/Tools/Perf.md)

## References

1. [Dynamic Instrumentation of Production Systems (Cantrill, Shapiro, Leventhal; USENIX ATC 2004)](https://dl.acm.org/doi/10.5555/1247394)
2. [Solaris Dynamic Tracing Guide](https://docs.oracle.com/cd/E19253-01/817-6223/index.html)
3. [The D Programming Language — reference](https://docs.oracle.com/cd/E19253-01/817-6223/chp-d/index.html)
4. [Brendan Gregg — DTrace Tools](https://www.brendangregg.com/dtrace.html)
