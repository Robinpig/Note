## Introduction

shell 是用户态程序，但它的行为几乎完全由内核机制决定：进程创建靠 `clone`、管道靠 `pipe`、作业控制靠 tty 与进程组、信号处理靠 `signal`、脚本执行靠 `execve`。不理解这些，"Ctrl-C 为什么杀掉整个管道""`&` 到底做了什么"这类问题就答不上来。

本页分两层：先看有哪些 shell、脚本怎么写（用户态），再看 shell 依赖的内核机制（这部分是理解行为的根本）。所有内核机制在 **v7.2** 核实。

## Common Shells

| shell | 说明 |
| :-- | :-- |
| **bash** | GNU 项目开发，几乎所有发行版的默认 shell。Bourne shell 的替代品，名称本身就是文字游戏（Bourne again shell） |
| **ash** | 内存受限环境用的轻量 shell，**与 bash 兼容**（BusyBox 里就是它） |
| **dash** | Debian/Ubuntu 的 `/bin/sh` 实际实现，比 bash 小得多且更快，但**不支持**数组、`[[ ]]` 等 bash 扩展 |
| **ksh** | Bourne 兼容的编程 shell，支持关联数组、浮点运算等高级特性 |
| **tcsh** | 把 C 语言元素引入脚本的 shell |
| **zsh** | 结合 Bourne 兼容、ksh 特性与 csh 风格，交互体验好，支持**通配符**与**拼写纠错** |
| **fish** | 用户友好优先，语法与 bash 差异大（不是 POSIX shell） |
| **nushell** | 结构化数据优先，把表当一等公民 |

> [!TIP]
>
> 写可移植脚本时注意 `/bin/sh` 在不同发行版指向不同实现：Debian/Ubuntu 指向 dash（POSIX 严格），RHEL/Fedora 指向 bash。所以 `#!/bin/sh` 的脚本在 RHEL 上可能"意外能用" bash 语法，到 Debian 上就报错。**要 bash 特性就显式写 `#!/bin/bash`**，别依赖默认值。

## Scripting Basics

```shell
#!/bin/bash      # 第一行必须是 shebang，指定解释器
```

shebang 由内核识别：`execve()` 读文件前两字节若是 `#!`，就按路径启动对应解释器。**内核只认这一种机制**，所以 python/go 脚本同样靠 shebang。

```shell
#!/usr/bin/env bash   # 更可移植的解释器定位方式
```

用 `env` 代替绝对路径，在 PATH 不同的环境里更可靠。

### Common Quick Reference

| 用途 | 语法 |
| :-- | :-- |
| 变量 | `x=1` / `"$x"`（引用）/ `'$x'`（不展开） |
| 命令替换 | `` `cmd` `` 或 `$(cmd)`（**推荐后者**，可嵌套、可读性好） |
| 条件 | `if [ cond ]` / `[[ cond ]]`（bash 扩展，支持 `<` `&&`） |
| 循环 | `for x in ...` / `while` / `until` |
| 函数 | `f() { ... }` |
| 参数 | `$1` / `$@` / `"$*"` / `$?`（上一条退出码）/ `$$`（PID） |
| 重定向 | `>` / `>>` / `<` / `2>` / `&>` / `2>&1` |
| 管道 | `cmd1 \| cmd2`（**两侧都 fork**） |
| 后台 | `cmd &` |
| 分组 | `{ ...; }` / `( ... )`（后者会 fork 子 shell） |
| 退出 | `exit N` |

**引号是最容易出错的地方**：`"$x"` 展开变量但不做分词，`$x` 还会做 glob 展开。路径操作永远用 `"$path"`。

## Kernel Mechanism: Pipe

shell 管道（`cmd1 | cmd2`）是内核 `pipe()` 系统调用提供的。**v7.2 已经没有 `sys_pipe()`，只有 `pipe2()`**（`fs/pipe.c:1152`）。源码注释解释了为什么：

> `sys_pipe()` is the normal C calling standard for creating a pipe. It's not the way Unix traditionally does this, though.

即 **`pipe()` 是 libc 的封装，系统调用层面只有 `pipe2()`**。glibc 的 `pipe()` 就是 `pipe2(fildes, 0)`。

### Three Key Default Values

| 常量 | 值 | 位置 | 含义 |
| :-- | :-- | :-- | :-- |
| `PIPE_DEF_BUFFERS` | **16** 页 | `include/linux/pipe_fs_i.h:5` | 默认缓冲 16 页 = **64 KiB** |
| `PIPE_MIN_DEF_BUFFERS` | **2** 页 | `fs/pipe.c:49` | 非特权用户超配额时的下限 |
| `pipe_max_size` | **1048576**（1 MB） | `fs/pipe.c:55` | 非 root 用户可增长的上限 |

`PIPE_MIN_DEF_BUFFERS` 为什么是 2 而不是 1？源码注释给了理由：低于 2 时非满管道也可能阻塞，**影响 GNU make jobserver 把管道当信号量的用法** —— 管道若只有 1 页，write 就可能阻塞在"尚未被读走"的槽位上。2 页保证至少有 1 页能空出来承载信号。

`/proc/sys/fs/pipe-max-size` 可调这个 1 MB 上限；超过需 `CAP_SYS_RESOURCE`（`pipe.c:1484`）。

> **注意区分**：`pipe_max_size`（内核，1 MB）与 `ulimit -p`（shell 的 pipe 缓冲上限）是**两套独立限制**，取更小者生效。

### O_NONBLOCK Semantics

```c
	/* 读端，pipe.c:466 附近 */
	if (filp->f_flags & O_NONBLOCK)
		return -EAGAIN;      /* 空管道立即返回，不阻塞 */
	/* 否则 */
	wait_event_interruptible_exclusive(pipe->rd_wait, pipe_readable(pipe));
```

| 端 | 满/空时 + `O_NONBLOCK` |
| :-- | :-- |
| 读空 | 返回 `-EAGAIN`（`pipe.c:466`） |
| 写满 | 返回 `-EAGAIN`（`pipe.c:646`） |

**`O_NONBLOCK` 是在 `pipe2()` 创建时传的，会同时作用于两端**。传统上要用 `fcntl()` 单独设置某个 fd 的 `O_NONBLOCK`，`pipe2()` 把它做进了创建接口。

### Evolution of the Ring Buffer

`pipe.c:63-68` 的注释标注了这段代码的来源（David Howells, 2019-09-23）：

```c
	/* head/tail 不掩码，自然回绕；ring 必须 2 的幂且 ≤ 2^31 */
```

现代实现用**自然回绕的 head/tail 计数**（不取模），只在访问数组时掩码：

```c
static inline struct pipe_buffer *pipe_buf(struct pipe_inode_info *pipe, unsigned int slot)
{
	return &pipe->bufs[slot & (pipe->ring_size - 1)];
}
```

这消除了"缓冲区大小必须是 2 的幂"之外的所有除法。缓冲区数量按需分配而非固定 16，所以 pipe 才需要配额机制（`account_pipe_buffers()`）——非特权用户超配额时会被压到 `PIPE_MIN_DEF_BUFFERS`。

## Kernel Mechanism: The Boundary Between User Mode and Kernel Mode

### copy_to_user / access_ok

shell 脚本的每个变量读写，本质上都是**从用户地址空间拷数据**。v7.2 里 `copy_to_user()` / `copy_from_user()` **已完全内联进 `include/linux/uaccess.h`**（`mm/memory.c` 里没有定义）：

```c
static __always_inline unsigned long copy_from_user(void *to, const void __user *from,
						   unsigned long n)
{
	if (likely(check_copy_size(to, n, false)))
		return _copy_from_user(to, from, n);
	return n;
}
```

而 `_inline_copy_from_user()` 里的顺序很有讲究：

```c
	if (!might_fault()) { ... }
	if (should_fail_usercopy(...))      /* USERCOPY_FAULT 测试 */
		...
	/* can_do_masked_user_access() 为真 → 走 mask_user_address() */
	if (!access_ok(from, n))
		goto fail;
	barrier_nospec();
```

**`barrier_nospec()` 的位置是关键** —— 注释说明它防止"错误的 `access_ok()` 预测在拷贝之后才产生副作用"。这与内核在用户空间缓解 Spectre 上的努力同源。

`access_ok()` 在 v7.2 已成可选内联（`user_access_begin()` 直接展开成 `access_ok()`）。

### execve and shebang

`execve()` 读文件头，若为 `#!` 则解析解释器路径并 exec 那一行指定的程序（最多再传一个参数）。**这是内核唯一支持的脚本机制** —— 没有 `#!` 就没有脚本。

## Kernel Mechanism: Signals (Why Ctrl-C Works)

在交互式 shell 里按 Ctrl-C，终端驱动生成一个 `SIGINT` 字符，**行规程（line discipline）** 转成信号发给前台进程组：

```
硬件中断 → tty 接收字符 → ldisc N_TTY 判断是 VINTR (^C)
  → 发送 SIGINT 给 tty->ctrl.pgrp 的所有成员
  → 目标进程被唤醒，走 get_signal() 投递
```

信号投递链（`kernel/signal.c` + 架构侧）：

| 环节 | 位置 |
| :-- | :-- |
| 判断是否需要投递 | `get_signal()` — `signal.c:2810` |
| 架构入口 | `arch_do_signal_or_restart()` — `arch/x86/kernel/signal.c:333` |
| 构栈帧并跳到 handler | `handle_signal()` — `arch/x86/kernel/signal.c:255` |
| 恢复信号掩码 | `signal_delivered()` — `signal.c:3069` |
| 分发包装 | `signal_setup_done()` — `signal.c:3089` |

`signal_delivered()` 的注释说明了投递后必须做的事：

```c
	clear_restore_sigmask();
	sigorsets(&blocked, &current->blocked, &ksig->ka.sa.sa_mask);
	/* 非 SA_NODEFER 则把本信号加回 blocked */
	if (!sig_ignored(ksig, &blocked))
		sigaddset(&blocked, ksig->sig);
	set_current_blocked();
```

**默认行为是把当前信号重新加回阻塞掩码**（除非 `SA_NODEFER`）—— 这就是"Ctrl-C 之后进程还能继续"的原因：处理完 handler 后该信号仍被阻塞，不会立刻再次触发。

> ⚠️ 旧资料里的 `signal_deliver()` 在 v7.2 **不存在**。

### Why Ctrl-C Only Kills One Process Group

`^C` 发送给 **前台进程组**（`tty->ctrl.pgrp`）的**所有**成员。这是设计如此：`cmd1 | cmd2` 两个进程同属一个前台进程组，按一次 Ctrl-C 两个都死。

而 `tty->pgrp` 在 v7.2 已移入 **`tty->ctrl.pgrp`**（`include/linux/tty.h`）—— 前面多了 `ctrl` 一层，因为前台/后台/会话相关的进程组信息现在归在一起管。

## Kernel Mechanism: Job Control

| 概念 | 机制 |
| :-- | :-- |
| 进程组 | `setpgid()` / `getpgid()`（`kernel/sys.c:1114`/`1215`） |
| 会话 | `setsid()`（`ksys_setsid` 在 `sys.c:1268`） |
| 前台进程组 | ioctl `TIOCSPGRP` / `TIOCGPGRP`（`tty_io.c:2897`/`2896`） |
| 孤儿进程组 | `is_current_pgrp_orphaned()`（`include/linux/tty.h:419`） |

> ⚠️ **`tcsetpgrp()` / `tcgetpgrp()` 是 ioctl 不是系统调用**（libc 才包装成函数）。v7.2 的 tty 作业控制状态机在 **`drivers/tty/tty_jobctrl.c`**（593 行）—— `kernel/tty.c` 在 v7.2 **已不存在**，拆成了 `tty_io.c` / `tty_ioctl.c` / `tty_jobctrl.c` / `tty_buffer.c` 等多个文件。

`setsid()` 做了四件事，其中一件容易忽略：

```c
	proc_clear_tty(group_leader);            /* 解除旧终端关联 */
	proc_sid_connector();                    /* 关联新会话 */
	sched_autogroup_create_attach();          /* 调度 autogroup */
```

**`sched_autogroup_create_attach()`** 说明 `setsid()` 会顺带把进程挂进调度器的 **autogroup** —— 见 [fair](/docs/CS/OS/Linux/proc/fair.md) 里 autogroup 对 build 进程做交互性判断的机制。

## Kernel Mechanism: Pseudo-terminal

终端模拟器（xterm、tmux、screen）与被运行的程序之间靠 **pty** 通信。`drivers/tty/pty.c`（923 行）的分工：

| 函数 | 作用 |
| :-- | :-- |
| `ptmx_open()` | 打开 `/dev/ptmx`，分配从设备号 |
| `unix98_pty_init()` | 注册 master/slave 两个驱动 |
| `tty_init_dev()` | 真正创建设备（**在 `tty_io.c:1384`，不在 pty.c**） |

`ptmx_open()` 里有个安全相关的细节：

```c
	file_set_fsnotify_mode(filp, FMODE_NONOTIFY);   /* 拒绝 fsnotify */
```

注释说 ptmx 是**共享资源**，所以不允许被 inotify 监控。

master 与 slave 的 `init_termios` 初值不同：**master 侧全零**（`c_iflag`/`c_oflag`/`c_lflag` = 0，38400 波特），因为它不面向终端设备。

> `ptsname` / `grantpt` / `unlockpt` **是 glibc 用户态函数，内核不实现**。内核只提供 ioctl：`TIOCGPTN`（拿从设备号）与 `TIOCSPTLCK`（加解锁）。

## Kernel Mechanism: dup and fd Sharing

shell 的 `cmd > file 2>&1` 靠 `dup2()`。v7.2 的实现**在 `fs/file.c`**（`kernel/fcntl.c` 已不存在）：

| 函数 | 位置 |
| :-- | :-- |
| `do_dup2()` | `fs/file.c:1292` |
| `ksys_dup3()` | `fs/file.c:1423` |
| `SYSCALL_DEFINE3(dup3, ...)` | `fs/file.c:1457` |
| `SYSCALL_DEFINE2(dup2, ...)` | `fs/file.c:1462` → `ksys_dup3(oldfd, newfd, 0)` |
| `SYSCALL_DEFINE1(dup, ...)` | `fs/file.c:1481` |

**三个系统调用共用一个内部实现** `ksys_dup3()` —— `dup2` 就是 `dup3(oldfd, newfd, 0)`（不带 `O_CLOEXEC`）。

`dup2` 与 `dup` 的关键差别是**幂等性**：`dup2` 若 `newfd == oldfd` 直接返回（不关闭也不分配），`dup` 总是找最低空闲 fd。这个差别让 `dup2(a, b)` 可以安全地用于 shell 重定向而不必先判断 b 是否已开。

## Kernel Mechanism: System Call Boundary

v7.2 的 `SYSCALL_DEFINE` 与内部 `ksys_*` 分离已成模式（`kernel/sys.c:1268` 的 `ksys_setsid()` → `1303` 的 `SYSCALL_DEFINE0(setsid)`）。分工是：**`ksys_*` 放实现、外面包一层系统调用定义**，便于 seccomp、tracepoint、ptrace 挂在系统调用边界上。

注意 `kernel/sys.c` 是 uid/gid/pid/uname/rlimit/prctl 等的实现（3000+ 行），`kernel/ksys.c` **不存在**。

## Troubleshooting Quick Reference

```shell
# 脚本调试
bash -x script.sh              # 打印每条命令（最常用）
bash -n script.sh              # 只做语法检查，不执行
bash -v script.sh              # 打印读入的每行
set -x / set +x                # 脚本内切换
PS4='+ ${LINENO}: '            # 自定义 trace 前缀显示行号

# 追踪
strace -f -e trace=execve,openat,read,write ./script.sh
strace -c ./script.sh          # 统计各调用耗时（定位瓶颈）

# 进程组与作业
ps -o pid,pgid,ppid,sid,tty,stat,comm -p $$
ps -eo pid,pgid,sid,tty,cmd | head
jobs -l                        # 当前 shell 的后台作业
set -m                         # 打开作业控制（脚本里）
disown %1                      # 脱离作业控制

# 管道
cat /proc/sys/fs/pipe-max-size # 内核上限（1MB）
ulimit -a | grep -i pipe       # shell 层限制（与内核独立，取小）

# 终端
stty -a                        # 查 VINTR 等控制字符
tty                            # 当前终端名
ps -t $(tty | sed 's#/dev/##') # 该终端上的进程

# 复现环境问题
bash --noprofile --norc        # 不读任何配置文件（干净 shell）
env -i bash                    # 清空环境变量
```

## Interfaces with Other Subsystems

- **信号**：Ctrl-C 到 handler 的完整链路，handler 侧见 [signal](/docs/CS/OS/Linux/proc/signal.md)。
- **进程与作业**：`fork`/`clone`/`exit` 与僵尸回收见 [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)。
- **ptrace**：`strace` 的内核底座与 syscall-stop，见 [ptrace](/docs/CS/OS/Linux/proc/ptrace.md) 与 [strace](/docs/CS/OS/Linux/Tools/strace.md)。
- **命名空间**：容器里的 shell 看到受限的 `/proc`、`/dev`，见 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **调度**：`setsid` 触发的 autogroup 见 [fair](/docs/CS/OS/Linux/proc/fair.md)。

## Links

- [strace](/docs/CS/OS/Linux/Tools/strace.md)
- [signal](/docs/CS/OS/Linux/proc/signal.md)
- [process](/docs/CS/OS/Linux/proc/process.md)
- [ptrace](/docs/CS/OS/Linux/proc/ptrace.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [Tools 首页](/docs/CS/OS/Linux/Tools/README.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [GNU Bash 手册](https://www.gnu.org/software/bash/manual/bash.html)
2. [Linux 手册页 — bash(1)](https://man7.org/linux/man-pages/man1/bash.1.html)
3. [Bash 官方 Wiki](https://www.bash-hd.org/wiki)
