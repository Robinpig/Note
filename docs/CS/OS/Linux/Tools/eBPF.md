## Introduction

> eBPF does to Linux what JavaScript does to HTML. —— Brendan Gregg

**eBPF**（extended BPF）是一个**内嵌于 Linux 内核的安全可编程虚拟机**：无需重新编译内核、无需加载内核模块，就可以在事件发生时（系统调用、内核函数出入、网络包到达、tracepoint……）运行一小段经过校验的字节码，对内核行为进行观测、修改甚至注入策略。它是 [classic BPF](/docs/CS/OS/Linux/Tools/BPF.md)（包过滤虚拟机）的通用化扩展，二者在内核里共享同一套执行引擎与 `bpf(2)` 接口。

eBPF 的根本价值是把"**内核可编程**"变得安全可控：程序在加载时由 verifier 静态证明其安全性（不越界、不崩溃、必然终止），运行时 JIT 成原生指令，因此既有接近内核原生代码的性能，又不会把系统搞挂。它已覆盖可观测性、网络、安全、调度四大方向（Cilium、Falco、Pixie、各类 BCC 工具、`sched_ext` 调度器均构建其上）。

## Architecture

一次 eBPF 观测/控制的数据流：

```
用户态 (Clang/LLVM 编译 C -> eBPF .o)
   │  bpf(BPF_PROG_LOAD) / BPF_MAP_CREATE
   ▼
内核 verifier ── JIT ── 附加到 hook 点 (kprobe/tracepoint/XDP/...)
   │  事件触发时执行程序，通过 helper 读上下文、写 map
   ▼
eBPF map (perf buffer / ringbuf / hash / array ...)
   │  用户态通过 bpf(BPF_MAP_LOOKUP/...) 或 ringbuf 读取
   ▼
前端展示 (bpftool / BCC / bpftrace / 自定义 Go-Rust agent)
```

关键特征是**程序与状态分离**：程序是无状态的事件处理逻辑，跨事件、跨 CPU、与用户态共享的数据都放在 **map** 里。

## Instruction Set

eBPF 是一个 64 位 RISC 虚拟机：

- **11 个寄存器**：`R0–R10`。R0 是返回值；R1–R5 用于调用 helper 时传参；R6–R9 跨函数调用保留（callee-saved）；R10 是只读栈指针；
- **栈**：默认 512 字节（可配置更大），寄存器字长 64 位，也支持 32 位子寄存器写；
- **指令**：定长 64 位，字段含 opcode、目的/源寄存器、偏移、立即数；类别有 ALU64/ALU32、jump、load/store、atomic；
- **终止性**：早期不允许循环，5.3 起支持**有界循环**（verifier 能证明迭代次数有上限）；
- JIT 后在 x86-64/arm64 等架构上接近原生 C 的执行效率。

## Maps

map 是 eBPF 的通用数据结构，既是程序内部的持久/聚合存储，也是内核态↔用户态、程序↔程序之间的通信通道。常见类型：

| 类型 | 用途 |
| --- | --- |
| **HASH / PERCPU_HASH** | 任意 key→value 聚合（如按 pid 统计）；per-CPU 版避免锁竞争 |
| **ARRAY / PERCPU_ARRAY** | 定长下标数组，常做配置/计数器 |
| **PERF_EVENT_ARRAY / RINGBUF** | 向用户态推送事件；ringbuf 是更高效的共享环形缓冲（BCC→libbpf 时代的首选） |
| **LRU_HASH** | 带 LRU 淘汰的哈希，适合容量受限的追踪 |
| **TRACEPOINT_ARRAY / PERF_ARRAY** | 关联 perf event、kprobe 等 |
| **LPM_TRIE** | 最长前缀匹配，用于路由/CIDR 匹配 |
| **STRUCT_OPS / INODE_STORAGE / TASK_STORAGE** | 挂到内核对象上的私有存储 |

## Verifier

verifier 是 eBPF 安全性的核心，在程序加载（`BPF_PROG_LOAD`）时做静态分析，不通过则拒绝加载：

1. **控制流检查**：构建 CFG，确保无不可达危险路径、有界循环、程序必然走到合法的出口（返回合法值）；
2. **范围分析（range / tnum）**：对每个寄存器在每条指令处的值范围与"已知位/未知位"做抽象解释，证明所有内存访问的下标都在边界内，杜绝越界读写；
3. **指针类型追踪**：区分栈指针、map value 指针、上下文指针等，禁止非法转型与解引用；
4. **helper 白名单**：只允许调用该程序类型可用的 helper；
5. **复杂度上限**：指令数、指令总路径数有上限（早期 4096 条，后放宽到百万条级并引入有界循环）。

这套"加载期证明 + 运行期无额外检查开销"的设计，使 eBPF 能在生产环境以微秒级开销运行。

## Helpers and BTF

- **Helper functions**：内核提供的稳定 API，如 `bpf_map_lookup_elem`、`bpf_probe_read_kernel`、`bpf_get_current_pid_tgid`、`bpf_ktime_get_ns`、`bpf_perf_event_output`、`bpf_ringbuf_output`。不同程序类型（tracing / XDP / cgroup …）可用的 helper 集合不同。
- **BTF（BPF Type Format）**：把内核的 C 类型信息（struct 布局、字段偏移）以紧凑元数据随内核发布。有了 BTF 才有：
  - **CO-RE（Compile Once - Run Everywhere）**：编译一次即可在不同内核版本运行，借助 `libbpf` 在加载期根据 BTF 对字段偏移做重定位，解决了 BCC 时代"每台机器现场编译、依赖内核头文件"的痛点；
  - **fentry/fexit**：类似函数级的 entry/return 探针，基于 BTF 直接拿到类型化的参数和返回值，比 kprobe 更稳、更快；
  - **BTF 化的输出**：`bpftool` 能直接以结构体字段名打印 map 内容。

## Program Types and Hooks

eBPF 通过不同 program type 挂到不同事件源：

| 类别 | 典型 hook | 用途 |
| --- | --- | --- |
| tracing | kprobe/kretprobe、tracepoint、fentry/fexit、perf event、USDT | 性能分析、函数级观测 |
| 网络 | XDP（驱动层收包最早点）、TC ingress/egress、socket、cgroup skb | 高性能包处理、负载均衡、防火墙 |
| 安全 | LSM 钩子（BPF LSM）、seccomp | 强制访问控制、运行时威胁检测 |
| 容器/cgroup | cgroup device、sockops、sysctl | 容器网络与资源策略 |
| 调度 | `sched_ext`、struct_ops | 用 BPF 实现自定义 CPU 调度类，见[调度器](/docs/CS/OS/Linux/proc/sche.md) |

静态的 **tracepoint** 稳定但数量固定；动态的 **kprobe** 可挂任意内核函数但依赖具体版本（可能被内联或重命名）；BTF 加持的 **fentry/fexit** 兼顾稳定与表达力。与传统追踪设施的协作见 [BPF 总览的 hook 章节](/docs/CS/OS/Linux/Tools/BPF.md?id=hook-points)，内核侧 tracepoint/函数钩子基础设施由 [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) 提供。

## Toolchain

| 层 | 代表 |
| --- | --- |
| 编译 | Clang/LLVM（`-target bpf -g -O2`，生成带 BTF 的 `.o`） |
| 加载库 | libbpf（C）、libbpfgo、cilium/ebpf（Go）、Aya（Rust） |
| 脚手架 | libbpf-bootstrap（`bootstrap`/`minimal`/`uprobe` 范例） |
| 脚本式 | bpftrace（AWK 风格，适合一行式追踪）、BCC（Python 前端） |
| 工具集 | bcc-tools、bpftrace-tools、`bpftool`、`bps` 等 |
| 大型项目 | Cilium（网络/可观测/安全）、Tetragon、Falco、Pixie |

bpftrace 一行式示例（统计每个进程发起 `read` 的次数）：

```bpftrace
tracepoint:syscalls:sys_enter_read { @[comm] = count(); }
```

追踪类程序更常见的形态是 `SEC("tracepoint/...")` / `SEC("kprobe/...")` + 通过 ringbuf 把事件推给用户态，参考 libbpf-bootstrap 的 `bootstrap`。

## XDP

XDP（eXpress Data Path）是 eBPF 在**网络数据面**的杀手级用法：把 BPF 程序挂到网卡驱动**收包最早的点**——此时 SKB 尚未分配、协议栈尚未介入，程序直接拿到包的原始字节。因为没有 `sk_buff` 分配开销，XDP 能做到每核千万级 PPS，常被用来做 DDoS 过滤、负载均衡（Cilium、Katran）、自定义转发。它在 Linux 内核框架内逼近 [DPDK](/docs/CS/OS/Linux/IO/DPDK.md) 的性能，又不必把整颗 CPU 交给忙轮询。

程序通过返回值决定包的去向（`enum xdp_action`）：

| action | 值 | 含义 |
| :-- | :-- | :-- |
| `XDP_ABORTED` | 0 | 异常丢弃，计入 `xdp:xdp_exception`，用于指示程序错误 |
| `XDP_DROP` | 1 | 直接在驱动层丢弃（DDoS 过滤，性能最高） |
| `XDP_PASS` | 2 | 放行，照常分配 SKB 进入协议栈 |
| `XDP_TX` | 3 | 从收到该包的同一块网卡**原路反弹**出去 |
| `XDP_REDIRECT` | 4 | 重定向到另一块网卡（`bpf_redirect`）或 CPU（`bpf_redirect_map`、AF_XDP） |

上下文是 `struct xdp_md`，用 `data`/`data_end` 圈出包的可读字节范围，`data_meta` 传元数据，另有入接口/接收队列索引。verifier 会强制所有对 `[data, data_end)` 的访问都先做边界检查。

三种挂载模式（硬件 / 驱动支持程度递减）：

- **Native（驱动原生）**：网卡驱动显式支持，程序在驱动 NAPI 收包路径中执行，是 XDP 的正常形态；
- **Offloaded**：由智能网卡（SmartNIC）在硬件上执行，连 CPU 都不占用，如部分 Netronome/NVIDIA 网卡；
- **Generic（XDP 测试用）**：在普通协议栈里模拟 XDP，无需驱动支持，但性能与时机都不真实，仅用于开发调试，不能上生产。

加载 / 卸载（iproute2 或 xdp-tools）：

```bash
# 挂到网卡 eth0 的驱动层收包点（native）
ip link set dev eth0 xdp obj drop.o sec .text
# 强制 generic 模式（调试）：ip -force link set dev eth0 xdpgeneric obj drop.o sec .text
ip link set dev eth0 xdp off        # 卸载
```

配套的 **AF_XDP** 是一种 socket：XDP 程序用 `XDP_REDIRECT` 把选中的包重定向进 AF_XDP 的零拷贝环形队列，用户态程序直接从队列收包，绕开协议栈——兼顾内核可编程与用户态高性能处理。

最小 XDP 程序（丢弃全部包，仅演示返回动作；实际过滤需配合 map 做白名单）：

```c
// drop.c  -- clang -O2 -target bpf -c drop.c -o drop.o
#include <linux/bpf.h>

int xdp_drop(struct xdp_md *ctx) {
    return XDP_DROP;   // 1
}
```

## Limitations

- 程序必须通过 verifier，写复杂逻辑（长循环、深层间接、大栈）时容易被拒，需要用有界循环与 map 规避；
- 内核版本差异：helper、字段、hook 可用性随版本变化，CO-RE 解决了字段偏移但解决不了"某函数/某 tracepoint 不存在"；
- kprobe 依赖具体内核符号，可能因内联/重命名失效，生产环境优先 tracepoint/fentry；
- 调试困难：程序在内核态运行，常依赖 `bpf_printk`（trace_pipe）与 verifier 日志排错。

## Links

- [BPF](/docs/CS/OS/Linux/Tools/BPF.md)
- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)
- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [Scheduler](/docs/CS/OS/Linux/proc/sche.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [DTrace](/docs/CS/OS/DTrace.md)

## References

1. [eBPF Documentation](https://docs.ebpf.io/)
2. [Kernel BPF Documentation](https://docs.kernel.org/bpf/)
3. [BPF Verifier Design](https://docs.kernel.org/bpf/verifier.html)
4. [BPF and XDP Reference Guide (Cilium)](https://docs.cilium.io/en/stable/bpf/)
5. [Brendan Gregg — eBPF Tools](https://www.brendangregg.com/ebpf.html)
6. [What is eBPF, anyway, and why should Kubernetes admins care?](https://www.groundcover.com/blog/what-is-ebpf)
