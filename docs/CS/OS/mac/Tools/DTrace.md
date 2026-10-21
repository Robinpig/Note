## Introduction

DTrace 是 macOS 从 Solaris 继承来的动态追踪框架，也是它相比 Linux 早期工具链最大的一项优势：内核里预置了稳定的探针点，无需重新编译内核、无需加载模块，就能在系统运行时安全地观测系统调用、调度、I/O、内存分配与任意用户态函数。

```shell
$ /usr/sbin/dtrace -V
dtrace: Sun D 1.19
```

它和 Linux 生态的对应关系大致是：`dtrace` ≈ `bpftrace` + `perf probe`，`dtruss` ≈ `strace`，`iosnoop` ≈ `biosnoop`，`opensnoop` ≈ `bpftrace` 的 `tracepoint:syscalls:sys_enter_openat`。eBPF 崛起后 Linux 侧的能力已经追上甚至超出，但 DTrace 在 macOS 上仍然是唯一的内建方案。

## Privilege and SIP

**这是使用 DTrace 的第一道门槛，也是最容易浪费时间的地方。** 系统完整性保护（SIP）开启时，DTrace 无法初始化：

```shell
$ /usr/sbin/dtrace -n 'BEGIN{trace("hi");exit(0);}'
dtrace: system integrity protection is on, some features will not be available
dtrace: failed to initialize dtrace: DTrace requires additional privileges
```

注意这两行的措辞差别：第一行说"部分功能不可用"，第二行才是致命错误。也就是说，**即使用 `sudo` 也无法绕过 SIP**——它保护的是"内核不能被动态修改"这件事本身，与权限级别无关。

> [!WARNING]
>
> 关闭 SIP 才能完整使用 DTrace，而关闭它需要进入恢复模式执行 `csrutil disable`，这会让整机的保护机制失效。**日常开发不要为此关 SIP**，更合理的做法是：先在 SIP 开启状态下尝试（部分用户态探针仍可用），确有必要再在专用的调试机上关掉，用完立刻开回来。`csrutil enable` 同样需要在恢复模式下执行。详见 [Security](/docs/CS/OS/mac/Security.md) 与 [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)。

## Tool Inventory

`/usr/bin` 下自带的 DTrace 工具比多数人知道的多，分三层：

**第一层是包装脚本**，它们本身是 POSIX shell 脚本，内部拼出 D 脚本再调用 `/usr/sbin/dtrace`（本机实测均为 DTrace 实现）：

| 命令 | 作用 |
| :--- | :--- |
| `dtruss` | 跟踪系统调用，strace 的替代 |
| `iosnoop` | 按进程显示磁盘 I/O 事件 |
| `opensnoop` | 跟踪 `open` 调用，含失败返回 |
| `execsnoop` | 跟踪新进程创建 |
| `rwsnoop` | 跟踪 `read`/`write` |
| `errinfo` | 统计系统调用的错误返回 |
| `iotop` | 按进程排名的磁盘 I/O（**常被误认为 Linux 的 iotop，实为 DTrace 脚本**） |
| `dapptrace` / `dappprof` | 跟踪单进程的用户态函数调用 / 采样其调用栈 |
| `imptrace` / `fddist` / `iopattern` | 库调用跟踪 / fd 分布 / I/O 模式 |

**第二层是 D 脚本本体**，共 **25 个**（本机实测 `/usr/bin/*.d`），直接改它或抄走当模板都很方便：

```
bitesize.d  cpu_profiler.d  cpuwalk.d    creatbyproc.d  dispqlen.d
filebyproc.d  hotspot.d     iofile.d     iofileb.d      kill.d
loads.d     newproc.d       pathopens.d  pidpersec.d    priclass.d
pridist.d   rwbypid.d       rwbytype.d   seeksize.d     setuids.d
sigdist.d   syscallbypid.d  syscallbyproc.d  syscallbysysc.d  timer_analyser.d
```

**第三层是 DTrace 库**，放在 `/usr/lib/dtrace/`：`darwin.d`、`errno.d`、`io.d`、`ip.d`、`sched.d`、`signal.d`、`socket.d`、`tcp.d`、`unistd.d`，外加 `arm`、`arm64`、`x86_64` 三个架构目录。写 D 脚本时 `errno.d` 能把错误码翻译成名字，`io.d` 提供 I/O 相关的结构体定义。

## D Language Structure

D 是 DTrace 的专用语言，语法刻意做成 awk 的近亲。一条探针声明由四段构成，任一留空表示匹配全部：

```d
provider:module:function:name
/predicate/                // 可选，过滤条件
{
    action;                // 命中时执行
}
```

一个跟踪某个进程所有 `open` 调用、并打印返回值的例子：

```shell
sudo dtrace -n 'syscall::open*:entry /pid == $target/ { printf("%s", copyinstr(arg0)); }' -p 1234
```

常用聚合函数的语义要记牢，它们决定了输出是什么形状：

| 函数 | 作用 |
| :--- | :--- |
| `count()` | 计数 |
| `sum(x)` | 求和 |
| `avg(x)` / `quantize(x)` | 均值 / 2 的幂直方图分布 |
| `lquantize(x, min, max, step)` | 线性直方图 |
| `trace(x)` / `printf(...)` | 输出 |
| `ustack()` / `stack()` | 用户态 / 内核态调用栈 |

## Practical One-Liners

```shell
# 系统调用计数，按进程聚合
sudo dtrace -n 'syscall:::entry { @num[pid, execname] = count(); }'

# 哪个文件被写得最多
sudo dtrace -n 'syscall::write*:entry { @[execname] = count(); }'

# 文件打开失败（看不到 errno 时用它定位"文件明明存在却打不开"）
sudo /usr/bin/opensnoop -e

# 新进程创建（排查"是谁拉起的这个进程"）
sudo /usr/bin/execsnoop

# 单进程的函数调用采样
sudo /usr/bin/dappprof -p 1234
```

`opensnoop -e` 在排查"配置文件到底读的哪一份"时特别有效：它直接给出路径与 errno，比在代码里加日志快得多。

## Limits

DTrace 在 macOS 上有几个硬边界：

- **受保护的进程无法追踪。** 系统进程（带 `P_LNOATTACH` 或受 SIP 保护的二进制）即使关了 SIP 也可能追踪失败，Apple 自己签名的部分进程会禁用用户态探针。
- **`copyinstr()` 有长度限制**，长路径会被截断；需要完整路径时加大 `strsize` 或用 `stringof`。
- **探针开销与事件频率成正比**，对高频系统调用（如 `read`）不加谓词地全量跟踪会显著拖慢系统，务必先用 `/pid == $target/` 之类的谓词收窄。
- **内核 panic 风险**：D 脚本本身有安全检查（不允许循环、不允许随意写内存），但错误的 `stringof`/指针解引用仍可能触发崩溃，生产环境谨慎。

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)
- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Performance](/docs/CS/OS/mac/Tools/Performance.md)
- [Security](/docs/CS/OS/mac/Security.md)

## References

1. [apple-oss-distributions/dtrace — macOS 上的 DTrace 源码](https://github.com/apple-oss-distributions/dtrace)
2. [DTrace Guide — Oracle](https://docs.oracle.com/en/operating-systems/solaris/oracle-solaris/11.4/dtrace-guide/)
3. [DTrace 动态追踪指南 — illumos](https://illumos.org/books/dtrace/)
