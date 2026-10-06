## Introduction

strace 用 **ptrace** 拦截系统调用：被跟踪进程每次进出内核都停下，由 tracer 读取寄存器与内存、决定是否修改、然后放行。理解它的开销与局限，都得从 ptrace 的机制说起。

与 macOS 的对应工具是 dtruss（见 [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)），Windows 上是 API Monitor / Procmon。

> [!WARNING]
>
> **ptrace 的开销是结构性的，不是配置问题。** 每个被跟踪的线程在系统调用边界都要走一次 trap（软中断 + 上下文保存），并把 tracer 唤醒一次。跟踪一个高频 I/O 的服务，响应时间可能劣化一个数量级。生产环境请优先用 [BPF](/docs/CS/OS/Linux/Tools/eBPF.md) 这类无侵入方案。

内核机制部分在 **v7.2** 核实。

## 安装与基本用法

```shell
sudo apt-get install strace        # Debian/Ubuntu
sudo dnf install strace            # Fedora/RHEL
```

```shell
strace ./program                   # 跟踪子进程
strace -p PID                      # 附加到已有进程
strace -f ./program                # 跟踪 fork 出的所有子进程
strace -ff -o out ./program        # 每个进程写各自的输出文件
```

## 常用参数

| 参数 | 作用 |
| :-- | :-- |
| `-c` | 统计每个系统调用的次数、耗时、错误率（**排查性能问题最有用**） |
| `-T` | 显示每个调用耗时 |
| `-t` / `-tt` / `-ttt` | 时间戳：相对秒 / 秒.微秒 / 秒.微秒.纳秒 |
| `-e trace=set` | 只跟踪指定调用，如 `-e trace=openat,read,write` |
| `-e trace=%file` | 跟踪所有与文件描述符相关的调用 |
| `-e trace=!set` | 排除某集合 |
| `-e signal=set` | 只跟踪指定信号 |
| `-f` | 跟踪子进程（新子进程自动 attach） |
| `-ff` | 与 `-f` 配合，每个进程独立输出文件 |
| `-o file` | 输出到文件（**强烈建议**，避免刷屏） |
| `-p PID` | 附加到已有进程（可多个 `-p`） |
| `-s SIZE` | 打印字符串的最大长度（默认 32，截断时给 `...`） |
| `-v` | 完整打印结构体与内存内容 |
| `-y` | 打印路径引用的 fd 对应的文件名 |
| `-yy` | 同时打印 fd 的所有路径（local + remote socket） |
| `-e inject=` | 注入错误或返回值做故障测试 |
| `-Z` | 被跟踪进程的 setuid/setgid 权限下运行（**有安全风险**） |
| `--seccomp-bpf` | 用 seccomp-BPF 过滤，**比 ptrace 快得多** |

> 原文里的 `-e trace=open,close` 应为 `openat,close`：`open` 在 x86-64 上是旧接口，现代程序用的是 `openat`。

### -c 的输出怎么读

```
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 99.99    0.001234           3      400           0 futex
  0.00    0.000000           0      300           0 mmap
```

**前几行占 80% 才是有意义的优化方向**。`errors` 列非 0 的行往往是真 bug —— `openat` 报 `ENOENT` 说明路径不对、`write` 报 `EPIPE` 说明对端已关闭。

## 内核机制：ptrace 的请求模型

`kernel/ptrace.c` 的 `ptrace_request()`（`ptrace.c:1162`）是所有请求的分派点。关键请求：

| 请求 | 作用 |
| :-- | :-- |
| `PTRACE_TRACEME` | 进程声明"请跟踪我"（子进程用） |
| `PTRACE_ATTACH` | tracer 附加到已有进程 |
| `PTRACE_SEIZE` | attach 的新方式（**不立即停**，与 attach 的关键区别） |
| `PTRACE_INTERRUPT` | 打断正在运行的被跟踪进程（配 SEIZE） |
| `PTRACE_SYSCALL` | 放到下一个系统调用停下 |
| `PTRACE_CONT` | 继续运行 |
| `PTRACE_GETREGS` / `SETREGS` | 读写通用寄存器 |
| `PTRACE_GET_SYSCALL_INFO` | **v7.x 的关键改进**（见下） |
| `PTRACE_PEEKDATA` / `POKEDATA` | 读写被跟踪进程内存 |

`ptrace_check_attach()`（`ptrace.c:257`）是所有请求的前置检查：

```c
/*
 * ptrace_check_attach - check whether ptracee is ready for ptrace operation
 */
```

**它检查"被跟踪者当前是否处于可 ptrace 状态"** —— 只有停在 ptrace-stop（而非 running 或普通 stop）才能操作。这是"为什么 strace 附加后要等一下才能开始输出"的原因。

### PTRACE_SEIZE 与 ATTACH 的区别

`ptrace_attach()` 的注释（`ptrace.c:320`）说明了限制：

```c
	 * ptrace_attach denies several cases that /proc allows
```

**`PTRACE_ATTACH` 会立即把目标停下**（发 SIGSTOP），而 `PTRACE_SEIZE` 不停 —— 它只建立关系，等 `PTRACE_INTERRUPT` 才停。实际差异：

- attach 一个正在处理请求的服务进程会**立刻打断它**（生产环境危险）；
- seize 不打断，但需要显式 interrupt；
- GDB 新版本默认用 seize。

### PTRACE_GET_SYSCALL_INFO：v7.x 的改进

这个接口一次性返回进入/退出的完整信息：

```
struct ptrace_syscall_info {
	__u8 op;          /* PTRACE_SYSCALL_INFO_ENTRY / EXIT / SECCOMP / NONE */
	__u8 pad[3];
	__u32 arch;
	__u64 instruction_pointer;
	__u64 stack_pointer;
	union {
		struct { __u64 nr; __u64 args[6]; } entry;
		struct { __s64 rval; __u8 is_error; } exit;
		struct { __u64 nr; __u64 args[6]; __u32 ret_data; } seccomp;
	};
};
```

**为什么它重要**：旧接口要拿系统调用号得先 `PTRACE_GETREGS` 读 `orig_rax`，参数要从 `rdi/rsi/rdx/r10/r8/r9` 里按序号猜着读；返回值的错误判定要读 `rax` 再比对 `-ERESTARTSYS` 那一堆宏。**这个接口把这些都填好了**，且明确区分"进入"和"退出"。

`PTRACE_SYSCALL_INFO_SECCOMP` 更是把 [seccomp-BPF](/docs/CS/OS/Linux/Tools/eBPF.md) 事件与 ptrace 打通了 —— seccomp 过滤器可以在特定系统调用上让进程停下交给 ptrace 决策。`strace --seccomp-bpf` 用的就是这条路。

## 内核机制：seccomp-BPF 过滤（比 ptrace 快得多）

`kernel/seccomp.c`（2569 行）。seccomp 的核心是一个 BPF 程序，系统调用前先跑一遍：

```c
	filter_ret = seccomp_run_filters(&sd, &match);
```

`seccomp_run_filters()`（`seccomp.c:404`）遍历当前线程的所有过滤器，命中即返回对应动作：

| 返回值 | 行为 |
| :-- | :-- |
| `SECCOMP_RET_ALLOW` | 放行 |
| `SECCOMP_RET_ERRNO` | 返回错误码（`SECCOMP_RET_DATA` 位可带 16 位数据） |
| `SECCOMP_RET_KILL` | 立即杀掉线程（内核） |
| `SECCOMP_RET_KILL_PROCESS` | 杀掉整个进程 |
| `SECCOMP_RET_TRAP` | 发送 SIGSYS |
| **`SECCOMP_RET_TRACE`** | **交给 ptrace 决策**（`strace --seccomp-bpf` 走这条） |
| `SECCOMP_RET_LOG` | 记录后放行 |

**`SECCOMP_RET_TRACE` 是 strace 与 seccomp 的接口** —— seccomp-BPF 在被关注的系统调用上让进程停下，tracer 通过 `PTRACE_EVENT_SECCOMP` 事件收到通知。这样**未命中的系统调用完全不进 ptrace 路径**，开销比传统 ptrace 低一到两个数量级。

```c
	case SECCOMP_RET_TRACE:
		...
```

这是 strace 值得记住的一个现代用法：

```shell
strace --seccomp-bpf -e trace=openat,read,write ./program
```

代价是**看不到系统调用之间的 ptrace 语义差异**（如 restart 行为），且需要内核启用 `CONFIG_SECCOMP_FILTER`。

## 内核机制：strace 看到的"重启"

`strace` 输出里偶尔出现这样的行：

```c
read(3, "abc", 3)                    = 3
read(3, ""..., 512)                  = ? ERESTARTSYS
read(3, "de", 2)                     = 2
```

**中间那行不是真的出错**。它表示：系统调用被信号打断准备返回时，内核在检查是否有 handler 带 `SA_RESTART` —— 如果带，就重启该系统调用。`strace` 显示 `ERESTARTSYS` 是因为此刻在内核里还没到"决定重启"那一步。

这个机制由 `signal.c:3185` 的 `SYSCALL_DEFINE0(restart_syscall)` 与 `do_no_restart_syscall()`（`signal.c:3191`）配合完成。**无 handler 或 handler 未设 `SA_RESTART` 时**，strace 显示的就是真实的 `EINTR`。

## 注意事项与实践建议

- **开销是结构性的**：每个系统调用边界都有 trap + 唤醒 tracer。跟踪高频 I/O 服务会明显劣化响应时间，且 tracer 与目标跑在**不同 CPU** 上时影响更小（可绑核：`taskset -c 0 strace -p PID`）。
- **反检测**：部分程序（含不少反调试/加固的商业软件）会检测 ptrace（查 `/proc/self/status` 的 `TracerPid`、主动 `ptrace(PTRACE_TRACEME)` 占位）。表现为行为改变或直接退出 —— 遇到"加上 strace 就跑不起来"应先想到这条。
- **`-o` 输出到文件**是好习惯，避免输出量导致终端刷屏拖慢 trace 本身。
- **`-f` 的代价**：`fork` 之后每个子进程都要 attach，进程数多的程序开销陡增。
- **权限**：附加到别人的进程需要同 uid 或 `CAP_SYS_PTRACE`；`/proc/sys/kernel/yama/ptrace_scope` 为 1 时只允许跟踪后代。
- **生产环境首选 bpftrace / eBPF**：无侵入、开销低，工具见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)；确实需要完整 syscall 序列时再考虑 strace，或用 sysdig（syscall 过滤 + 环形缓冲）替代。

## 与其它子系统的接缝

- **ptrace**：本文的机制底座，tracer/tracee 关系与 syscall-stop 见 [ptrace](/docs/CS/OS/Linux/proc/ptrace.md)。
- **seccomp-BPF**：更快的 syscall 过滤路径，见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。
- **信号**：ERESTARTSYS 与 `SA_RESTART` 的关系见 [signal](/docs/CS/OS/Linux/proc/signal.md) 与 [shell](/docs/CS/OS/Linux/Tools/shell.md)。
- **进程状态**：被跟踪进程停在 `TASK_TRACED`，见 [process](/docs/CS/OS/Linux/proc/process.md)。
- **gdb**：另一个 ptrace 的大用户，见 [Debug](/docs/CS/OS/Linux/Tools/Debug.md)。

## 排障速查

```shell
# 基础
strace -f -tt -o trace.log ./program
strace -c ./program                    # 统计模式，找性能瓶颈
strace -c -p PID                       # 对运行中进程用统计模式（开销小得多）

# 过滤（减少噪音与开销）
strace -e trace=openat,read,write ./prog
strace -e trace=%file ./prog            # 所有 fd 相关
strace -e trace=openat -e read=fd ./prog
strace -e trace=all -e signal=none ./prog

# 快速模式（seccomp-BPF）
strace --seccomp-bpf -e trace=openat ./prog

# 输出增强
strace -s 200 ./prog                   # 打印更长字符串
strace -y ./prog                       # fd 显示为文件名
strace -yy ./prog                      # socket fd 显示为两端地址
strace -v ./prog                       # 完整结构体

# 故障注入
strace -e inject=openat:error=ENOENT ./prog
strace -e inject=read:retval=0:when=2 ./prog

# 绑定 CPU 减少影响
taskset -c 0 strace -p PID

# 检查是否被 ptrace
cat /proc/self/status | grep TracerPid
```

## Links

- [ptrace（内核机制详解）](/docs/CS/OS/Linux/proc/ptrace.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)
- [signal](/docs/CS/OS/Linux/proc/signal.md)
- [Debug](/docs/CS/OS/Linux/Tools/Debug.md)
- [shell](/docs/CS/OS/Linux/Tools/shell.md)

## References

1. [strace(1) — Linux manual page](https://man7.org/linux/man-pages/man1/strace.1.html)
2. [ptrace(2) — Linux manual page](https://man7.org/linux/man-pages/man2/ptrace.2.html)
3. [seccomp(2) — Linux manual page](https://man7.org/linux/man-pages/man2/seccomp.2.html)
4. [dtruss（macOS 对应工具）](/docs/CS/OS/mac/Tools/dtruss.md)
