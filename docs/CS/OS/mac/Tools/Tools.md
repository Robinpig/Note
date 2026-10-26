## Introduction

macOS 的工具生态有一个容易被忽略的前提：**它自带的是 BSD 系命令行，不是 GNU coreutils**。你在 Linux 上写熟的 `sed -i`、`date -d`、`ps aux` 组合在这里要么报错、要么静默给出不同结果。所以这里的工具箱分两半——系统自带的 BSD 工具与 Apple 专有的诊断命令，以及 Homebrew 补上来的 GNU 生态。判断"这个命令为什么行为不对"之前，先确认它是 `/usr/bin` 里的 BSD 版本还是 `/opt/homebrew` 里的 GNU 版本。

```shell
$ /usr/bin/sed -i 's/hello/world/' t.txt
sed: 1: "t.txt": undefined label 't.txt'     # 不是"缺少参数"，是 BSD 把 -i 的第一个值当备份后缀吃了
$ /usr/bin/sed -i '' 's/hello/world/' t.txt  # 正确写法：空后缀表示不备份
```

这一节按"你要解决什么问题"来组织，而不是按命令名字母序。

## Map of This Section

**先解决"命令行为不对"这类最常见的困惑。** BSD 与 GNU 在 `sed -i`、`date -d/-v`、`stat -c/-f`、`xargs -I`、`readlink -f`、`tar --exclude` 上都有分歧，还有一批 Linux 上习以为常、macOS 根本没有的命令（`timeout`、`free`、`vmstat`、`watch`、`nproc`、`strace`）。同时 macOS 自带一批别处没有的命令：`pbcopy`/`pbpaste` 接剪贴板、`mdfind` 查 Spotlight 索引、`defaults` 读写 plist、`scutil` 看 DNS 与网络状态、`caffeinate` 阻止睡眠。见 [CLI](/docs/CS/OS/mac/Tools/CLI.md)。

**装软件这件事单独成篇**，因为它是"命令行为不对"的第二大来源：Apple Silicon 上 `/opt/homebrew` 是原生 arm64，Intel 或 Rosetta 下是 `/usr/local`，两者能共存但需要的二进制架构完全不同。bottle、tap、cask、`brew services` 与 launchd 的关系、多架构别名写法，见 [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md)。第三方应用的选型清单在 [Software](/docs/CS/OS/mac/Tools/Software.md)。

**想知道"系统现在在干什么"，靠的是 Apple 自己的动态追踪。** Solaris 血统的 DTrace 在 macOS 上还活着（`dtrace`、`dtruss`、`iosnoop`、`opensnoop`、`execsnoop`、`rwsnoop`），但它受 SIP 限制——SIP 开着的机器上 `dtrace` 直接报 "requires additional privileges"，只有关掉 SIP 或用已签名的 dtrace 探针才能完整使用。见 [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)，`dtruss` 作为 strace 替代品的最小用法见 [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)。

**性能问题的入口和 Linux 不一样**：没有 `perf`，取而代之的是 `powermetrics`（能读到 E/P 核分别的驻留频率与功耗）、`fs_usage`（文件与 I/O 事件流）、`spindump`/`sample`（进程采样）、`leaks`/`malloc_history`（内存分配追踪），上层还有 Instruments 与它的命令行版 `xctrace`。见 [Performance](/docs/CS/OS/mac/Tools/Performance.md)。内存口径的换算（16 KiB 页、`vm_stat` 与活动监视器对不上）见 [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)。

**网络排查**是另一个自成体系的角落：`nettop` 是 `iftop` 的替代，`networkQuality` 跑的是 Apple 自己的响应式测试，`scutil --dns` 与 `networksetup` 管的是系统配置数据库而不是某个配置文件，抓包则要靠 `tcpdump` 或第三方 GUI。见 [Network](/docs/CS/OS/mac/Tools/Network.md)。

**终端本身**在 10.15 从 bash 换成 zsh，默认 shell、login shell 与 `PATH` 的装配顺序因此有一批坑（GUI 应用读不到 shell 的 `PATH` 就是最典型的一个）。Terminal、iTerm2、Warp、Kitty 的取舍，oh-my-zsh 插件与 tmux，见 [Terminal](/docs/CS/OS/mac/Tools/Terminal.md)。编译与调试工具链（Xcode、CLT、LLDB）见 [Development](/docs/CS/OS/mac/Development.md) 与 [LLDB](/docs/CS/OS/mac/LLDB.md)。

## Quick Command

Finder 快捷键：

| Command                  | Function          |
| ------------------------ | ----------------- |
| ⌘⇧.（Command + Shift + .） | show hidden files |
| ⌘⇧4（Command + Shift + 4） | screenshots       |

常用替换：

```shell
vm_stat                    # 内存统计，注意页大小是 16384
lsof -i :8080              # 查端口占用
pbcopy < file              # 复制到系统剪贴板
mdfind "keyword"           # 走 Spotlight 索引全文搜
caffeinate -d              # 阻止睡眠，直到 Ctrl-C
open .                     # 在 Finder 打开当前目录
```

## Issues

MBP 长期不关机时，跨设备 Handoff 会失效（其他设备看不到复制的内容、无法接力），重启后恢复。这类连续互通功能依赖蓝牙 LE 与 AWDL 的常驻状态，长时间运行后状态机卡住，重启是最快的解法。

## Links

- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md)
- [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)
- [Performance](/docs/CS/OS/mac/Tools/Performance.md)
- [Network](/docs/CS/OS/mac/Tools/Network.md)
- [Terminal](/docs/CS/OS/mac/Tools/Terminal.md)

## References

1. [SS64 — macOS / BSD 命令参考](https://ss64.com/osx/)
2. [Apple 支持的 macOS 命令行工具](https://support.apple.com/zh-cn/guide/terminal/welcome/mac)
