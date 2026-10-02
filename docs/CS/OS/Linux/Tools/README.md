## Introduction

本目录按**用途**收拢内核与系统的观测、追踪、调试工具。这些工具的共同点是：它们本身不是被观测对象，而是"看进去"的手段——所以笔记的重点不在命令手册，而在**它能看到什么、代价是什么、什么时候该换另一种**。

需要和 [Tools](/docs/CS/OS/Linux/Tools/Tools.md) 区分开：那一篇是**命令级速查**（vmstat / top / iostat / sar 等按 System / Process / Trace / Profiling 分类罗列，附选项说明）；本页是**笔记级导航**，回答"遇到某类问题该看哪一篇"。

一条经验放在开头：**先分清你要回答的是"发生了多少次"还是"为什么发生"**。前者用计数器（`/proc`、`vmstat`、`perf stat`），开销极低、可以常开；后者必须采样或插桩，必然带来开销，也必然是有选择地短期使用。混淆这两者，是性能问题排查里最常见的浪费。

## 第一层：看现象

出问题时的第一步永远是拿到现象，而不是立刻钻进内核。系统级的宏观指标来自 `/proc` 与 `/sys`——[proc](/docs/CS/OS/Linux/fs/proc.md) 文件系统是这一切的数据源，`vmstat`、`iostat`、`sar`、`mpstat` 本质上都是把它翻译成可读格式。CPU 利用率、负载均值这些概念本身的含义见 [performance](/docs/CS/OS/Linux/performance.md)——注意 load average 统计的是**可运行 + 不可中断睡眠**的线程数，把它当成"CPU 使用率"是最常见的误读。

[Tools](/docs/CS/OS/Linux/Tools/Tools.md) 与 [CMD](/docs/CS/OS/Linux/Tools/CMD.md) 覆盖这一层，前者是性能计数器，后者是日常命令与排错。

## 第二层：看系统调用与函数

现象指向某个进程之后，需要知道它在做什么。[strace](/docs/CS/OS/Linux/Tools/strace.md) 跟踪系统调用边界——它建立在 `ptrace` 之上（见 [ptrace](/docs/CS/OS/Linux/proc/ptrace.md)），所以开销很大，只适合短时使用。但它对"卡在哪个调用上"这类问题的判断力，是其他工具替代不了的。

真正做性能分析的主力是 [Perf](/docs/CS/OS/Linux/Tools/Perf.md)：它基于 PMU 硬件计数器做采样，`perf record` / `perf report` 能给出函数级的 CPU 占用排序，`perf stat` 则给出 IPC、cache miss 这类硬件事件计数。判断"是算得慢还是等得慢"时，`perf stat` 往往比任何日志都直接。

## 第三层：看内核内部

[ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) 是内核自带的追踪框架，通过 tracefs 暴露接口。它的价值在于**零依赖、无需编译、不需重启**——`function` tracer 记录函数调用，`function_graph` 画出调用耗时树，trace events 直接挂在内核预置的 tracepoint 上。定位"某个内核函数被调用得多不多、耗时多少"时，它是成本最低的选择。

FTrace 和 Perf 有重叠也有分工：**ftrace 强在函数级的确切调用关系与延迟分布，perf 强在硬件事件采样与全栈归因**。实践中常常先用 perf 找到热点，再用 ftrace 看清热点内部。

## 第四层：自定义观测

当已有 tracepoint 不够用时，就需要 [BPF](/docs/CS/OS/Linux/Tools/BPF.md) 与 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。这个方向值得放在最后看，因为它引入了前面的工具都没有的东西：**一个安全的内核内虚拟机**。

链路是清晰的：最初 cBPF 只是为 `tcpdump` 做包过滤的简单虚拟机；eBPF 把它扩展成通用指令集，加上 **verifier** 保证程序不会破坏内核、加上 **maps** 让内核侧与用户侧交换数据，才成为可编程的观测平台。`kprobe` / `tracepoint` / `fentry` 等 hook 点决定了你能插在哪里。掌握它的门槛高于前几层，但能力也完全不同——你可以写一个程序，只在"某个进程读某个文件且延迟超过 10ms"时才记录一条。

## 崩溃与调试

[Debug](/docs/CS/OS/Linux/Tools/Debug.md) 覆盖另一条线：内核编译、GDB、虚拟机调试环境的搭建。它与上面几层的区别是**需要有问题的现场可复现**——启动崩溃、panic、死锁这类问题无法靠采样发现，只能靠调试器停下来看。构建产物要选对：带符号的 `vmlinux` 用于调试，`bzImage` 用于引导（区别见 [boot](/docs/CS/OS/Linux/boot/README.md)）。

## 网络与日常环境

网络方向的工具单独成篇：[network](/docs/CS/OS/Linux/Tools/network.md) 按协议层组织（链路层 ethtool/tcpdump、网络层 ip/mtr、传输层 ss/nc/telnet），并给出排障路径速查；[curl](/docs/CS/OS/Linux/Tools/curl.md) 则专注 HTTP 客户端侧的诊断——`-w` 输出分段耗时、`-v` 看 TLS 握手、`--resolve` 绕过 DNS，这三招能覆盖大部分"接口慢/证书报错/解析不对"的问题。

剩下的属于环境搭建与日常操作：[shell](/docs/CS/OS/Linux/Tools/shell.md)（脚本）、[systemd](/docs/CS/OS/Linux/Tools/systemd.md)（服务管理）、[Nix](/docs/CS/OS/Linux/Tools/Nix.md)（声明式包管理）、[Termux](/docs/CS/OS/Linux/Tools/Termux.md)（Android 上的 Linux 环境）、[VNC](/docs/CS/OS/Linux/Tools/VNC.md)（远程桌面）。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [proc](/docs/CS/OS/Linux/fs/proc.md)
- [performance](/docs/CS/OS/Linux/performance.md)
