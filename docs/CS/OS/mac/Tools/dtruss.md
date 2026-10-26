## Introduction

`dtruss` 是 macOS 上最接近 [strace in Linux](/docs/CS/OS/Linux/Tools/strace.md) 的工具，但它不是 strace 的移植——它是一个 shell 脚本，内部生成 D 脚本交给 `/usr/sbin/dtrace` 执行。这个实现决定了它的两个特性：能力来自 DTrace 的 `syscall` 探针，限制也来自 DTrace（见 [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)）。

```shell
$ file /usr/bin/dtruss
/usr/bin/dtruss: POSIX shell script text executable
```

### enable

must disable SIP

check status

```shell
csrutil status
```

if enable

1. shutdown mac and press power button until recovery mode
2. turn to `options` and login
3. select terminal at top tabs
4. use `csrutil disable`

> [!WARNING]
>
> 关 SIP 会让整机失去保护，**用完记得用同样方式开回来**（`csrutil enable`）。只在专用调试机上做，日常机器不要长期关闭。SIP 的背景见 [Security](/docs/CS/OS/mac/Security.md)。

## Usage

跟踪新启动的命令：

```shell
sudo dtruss ls -la          # 跟踪整条命令
sudo dtruss -f ls -la       # -f 表示跟随子进程（fork/exec 出来的也算）
```

跟踪已经在跑的进程：

```shell
sudo dtruss -p 1234
```

只看某类系统调用，用 `-t` 过滤（这是降低开销的关键，全量跟踪高频调用会明显拖慢系统）：

```shell
sudo dtruss -t open ls      # 只看 open
sudo dtruss -t open_nocancel ls
```

按调用耗时排序，找慢在哪一步：

```shell
sudo dtruss -d ls -la       # -d 显示每次调用的耗时
sudo dtruss -e ls -la       # -e 显示 errno
```

## strace Mapping

| strace（Linux） | dtruss（macOS） | 说明 |
| :--- | :--- | :--- |
| `strace cmd` | `dtruss cmd` | 基本等价 |
| `strace -f` | `dtruss -f` | 跟随子进程 |
| `strace -p PID` | `dtruss -p PID` | 附加到已运行进程 |
| `strace -e trace=open` | `dtruss -t open` | 按名字过滤 |
| `strace -T` | `dtruss -d` | 显示耗时 |
| `strace -c` | 无直接等价 | 需要自己写 D 脚本用 `count()`/`sum()` 聚合 |

`-c` 的缺失是实际使用中最常碰到的落差：Linux 上 `strace -c` 直接给出"系统调用耗时占比"汇总，macOS 上要自己写聚合，例如：

```shell
sudo dtrace -n 'syscall:::entry /pid == $target/ { self->ts = timestamp; }
                syscall:::return /self->ts/ { @[probefunc] = sum(timestamp - self->ts); self->ts = 0; }' -p 1234
```

## Failure Modes

SIP 未关闭时，`dtruss` 不会给出"SIP 未关闭"这样的直白提示，而是透传 dtrace 的报错：

```shell
dtrace: system integrity protection is on, some features will not be available
dtrace: failed to initialize dtrace: DTrace requires additional privileges
```

看到第二行就说明是权限/保护问题，不是命令写错了。另一种常见情况是目标进程受保护（Apple 签名的系统进程），即使关了 SIP 也可能拿不到探针，这时只能换用 `fs_usage` 这类粗粒度工具，见 [Performance](/docs/CS/OS/mac/Tools/Performance.md)。

## Links

- [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Performance](/docs/CS/OS/mac/Tools/Performance.md)

## References

1. [apple-oss-distributions/dtrace — macOS 上的 DTrace 源码](https://github.com/apple-oss-distributions/dtrace)
2. [DTrace 动态追踪指南 — illumos](https://illumos.org/books/dtrace/)
