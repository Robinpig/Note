## Introduction

**BPF**（Berkeley Packet Filter）最早是 1992 年 Steven McCanne 与 Van Jacobson 在论文 *The BSD Packet Filter* 中提出的、运行在内核里的一个**小型寄存器虚拟机 + 包捕获过滤架构**。用户态用一个表达式描述"只收我关心的包"（如 `tcp port 80 and host 10.0.0.1`），经 libpcap 编译成一段字节码下推到内核；内核对每个经过 socket 的数据包执行这段程序，只有命中的包才被拷贝到用户态。

这一"**把过滤逻辑下推到事件源、在内核里安全执行**"的设计是 BPF 的核心思想。它后来被 Linux 吸收并极大扩展：2014 年 Alexei Starovoitov 引入 **extended BPF（eBPF）**，把这个虚拟机从网络包过滤推广到可挂到内核几乎任意事件点的通用可编程引擎。今天说的"BPF"通常泛指这一整套技术，而原始的包过滤字节码被称为 **classic BPF（cBPF）**。

本笔记聚焦 cBPF 的原始模型与 cBPF→eBPF 的演进；eBPF 的指令集、map、verifier、CO-RE、各类 hook 与工具链见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。

## Classic BPF Architecture

cBPF 的目标是用最小代价在内核里做包过滤，两大设计要点：

### Packet Filter VM

一个极简的、无副作用的寄存器虚拟机：

- 1 个 32 位累加寄存器 `A`、1 个索引寄存器 `X`；
- 一块临时 scratch memory（`M[0..15]`，每个 32 位）；
- 程序是定长 64 位指令 `struct sock_filter`（`op/jt/jf/k`）：操作码 + 两个跳转偏移（true/false）+ 通用字段 `k`；
- 只能**读**包数据（通过包起始相对偏移），不能写、不能循环、指令条数有上限，保证终止与安全；
- 返回值是"放行多少字节"（`return 0xffffffff` 放行整个包，`return 0` 丢弃）。

这种"受限指令集 + 保证终止 + 只读取证数据"的沙箱模型，正是后来 eBPF verifier 安全模型的雏形。

### Memory-mapped Filter

论文的另一贡献是包捕获的数据通路：内核把抓包缓冲通过 mmap 暴露给用户态，命中的包直接写入共享环形缓冲，**避免每个包两次系统调用与两次拷贝**。这是 libpcap/[tcpdump](/docs/CS/CN/Tools/tcpdump.md) 高效抓包的基础。

## From cBPF to eBPF

| 维度 | classic BPF (cBPF) | extended BPF (eBPF) |
| --- | --- | --- |
| 年代 | 1992，BSD；Linux 1997（socket filter） | 2014 合入 Linux 3.18 |
| 寄存器 | A + X（2 个） | 10 个 64 位通用寄存器 R0–R9 + 栈 |
| 用途 | 网络包过滤 | tracing、网络、安全、可观测性、调度等通用编程 |
| 附加点 | `SO_ATTACH_FILTER`（socket） | kprobe、tracepoint、perf event、XDP、TC、cgroup、LSM、struct_ops 等 |
| 状态 | 无（纯过滤） | **map** 在程序/内核/用户态间共享状态 |
| 数据 | 只读包 | 可读上下文，部分 hook 可改写/重定向 |
| 安全 | 指令数上限、无循环 | verifier 做可达性/边界/类型检查，有界循环（5.3+） |
| 编译 | libpcap 表达式 → 字节码 | C/BTF，Clang/LLVM → 字节码，CO-RE 可移植 |

在内核里，挂到 socket 的 cBPF 程序会在加载时被**透明翻译成 eBPF**（`bpf_migrate_filter`），因此现代内核实际只有一个 eBPF 执行引擎，cBPF 主要作为兼容接口存在。

## Hook Points

从"只能挂 socket"到"无处不在"是 eBPF 的关键扩展，常见事件源：

- **网络**：XDP（驱动层最早处理点）、TC ingress/egress、socket、cgroup sock_ops；
- **tracing**：kprobe/kretprobe（动态函数）、tracepoint（静态稳定点）、fentry/fexit（基于 BTF、低开销）、perf event、USDT（用户态静态探针）；
- **安全 / 控制**：LSM 钩子、cgroup 设备/网络策略、`sched_ext` 调度类（可向 [调度器](/docs/CS/OS/Linux/proc/sche.md)挂载自定义 BPF 调度策略）。

这使得 eBPF 与传统追踪工具高度重叠又彼此协作：

- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) 提供 tracepoint/函数钩子基础设施，eBPF 可挂在其上（`bpf_trace_*`）；
- [perf](/docs/CS/OS/Linux/Tools/Perf.md) 的 `perf_event` 是 eBPF 程序的重要触发载体，map 与 sample 通过 perf ring buffer 输出；
- [strace](/docs/CS/OS/Linux/Tools/strace.md) 跟踪系统调用，等价能力可用 eBPF 在 tracepoint:raw_syscalls 上更低开销实现；
- 旧的 DTrace/SystemTap 脚本化内核观测场景，在 Linux 上越来越多被 BCC/bpftrace 取代。

## Toolchain

| 层 | 代表 |
| --- | --- |
| 内核接口 | `bpf(2)` 系统调用、`bpf()` helper、BTF（BPF Type Format） |
| 编译 | Clang/LLVM（`-target bpf`）、libbpf、CO-RE |
| 开发框架 | BCC（Python/Lua 前端）、libbpf-bootstrap |
| 高阶脚本 | bpftrace（awk 风格的一行式追踪） |
| 产品化工具 | BPFtrace、bcc tools、Cilium（网络/安全）、Pixie、Falco 等 |

典型的 cBPF 用法（tcpdump 背后）：

```bash
# libpcap 把表达式编译为 cBPF 字节码，挂到抓包 socket
tcpdump -d 'tcp port 80'      # -d 打印汇编形态的过滤程序
tcpdump -dd 'tcp port 80'     # -dd 打印 C 数组形态的 sock_filter
```

## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)
- [perf](/docs/CS/OS/Linux/Tools/Perf.md)
- [strace](/docs/CS/OS/Linux/Tools/strace.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [DTrace](/docs/CS/OS/DTrace.md)

## References

1. [The BSD Packet Filter: A New Architecture for User-level Packet Capture](https://www.tcpdump.org/papers/bpf-usenix93.pdf)
2. [Kernel Documentation: BPF Design Q&A](https://docs.kernel.org/bpf/qa.html)
3. [A thorough introduction to eBPF (LWN)](https://lwn.net/Articles/740157/)
4. [Classic BPF (libpcap filter) to extended BPF — kernel docs](https://docs.kernel.org/bpf/classic_vs_extended.html)
