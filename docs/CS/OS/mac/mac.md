## Introduction

macOS 不是一个整体的"内核 + 桌面"，而是**两层拼起来的系统**：底下是开源的 Darwin（XNU 内核加一套 BSD 用户态），上面是 Apple 闭源的图形与媒体框架（Quartz、Aqua、Cocoa、Metal、CoreServices 等）。

这个分界决定了本节的读法——Darwin 提供的只是 POSIX 语义（进程、文件、信号、socket），你在终端里能用的一切都在这一层；而"看起来像 macOS"的那部分（窗口合成、字体渲染、Quick Look、Spotlight、Time Machine）全在上层，源码不公开，只能从框架文档和 `otool`/`class-dump` 的角度去观察。Apple 自己也是这么切的：`uname` 报的是 Darwin，`sw_vers` 才报 macOS。

```shell
$ sw_vers
ProductName:            macOS
ProductVersion:         15.3.1
BuildVersion:           24D70

$ uname -a
Darwin <host> 24.3.0 Darwin Kernel Version 24.3.0: Thu Jan  2 20:24:16 PST 2025; root:xnu-11215.81.4~3/RELEASE_ARM64_T6000 arm64
```

血统上它源自 NeXTSTEP（1989）：1996 年 Apple 收购 NeXT，把 OPENSTEP 改造成 Rhapsody，2001 年发布 Mac OS X 10.0，2012 年去掉 "Mac" 改称 OS X，2016 年 Sierra 起改称 macOS。版本号的三次变号也值得记住：`10.0`–`10.15` 用 10.x 递增，2020 年 Big Sur 起改成整数大版本 `11`，2025 年 Tahoe 起又改成**年份制**直接跳到 `26`（与 iOS 26 对齐），次年是 `27`。

## Version Baseline

版本号在本节里是硬事实，三列对齐关系是：macOS 版本 ↔ Darwin 版本 ↔ xnu 源码 tag。Apple 发布后过一段时间才把源码推到 `apple-oss-distributions`，所以"最新公开 tag"常常落后于"最新发售版本"。

| macOS | 代号 | Darwin | xnu | 公开 tag |
| :--- | :--- | :--- | :--- | :--- |
| 15.x | Sequoia | 24.x | 11215 | `xnu-11215.81.4`（本机实测 15.3.1 = 24.3.0） |
| 26.0 | Tahoe | 25.0.0 | 12377 | `xnu-12377.1.9`（2025-09-15 发布） |
| 26.4 | Tahoe | 25.4.0 | 12377 | `xnu-12377.101.15` |
| 27.0 | Golden Gate | 27.0.0（第三方汇总） | 13432 | 未公开 |

> [!NOTE]
>
> 本机实测基线是 **macOS 15.3.1 / Darwin 24.3.0 / xnu-11215.81.4**（Apple M1 Pro，`hw.nperflevels=2`）。上表 26.x 与 27.0 两行来自第三方版本汇总与 `apple-oss-distributions/xnu` 的 tag 列表，不是本机实测——xnu tag 列表里最新的是 `xnu-12377.121.6`，Golden Gate 对应的 13432 系列尚未推送。
> macOS 27 是 Intel Mac 的终点：它只支持 M 系列与 A18 Pro，Intel 机型全部停止支持，只剩 Rosetta 2 继续跑 x86-64 应用。

## Platform Split

两个硬件平台在 macOS 里不是"换个 CPU 重编一遍"的差别，多条内核路径都被换掉了。判断"这段代码行为如何"之前，先确认它跑在哪一侧：

| 维度 | Intel（x86_64，已停售） | Apple Silicon（arm64 / arm64e） |
| :--- | :--- | :--- |
| 页大小 | 4 KiB | **16 KiB**（`hw.pagesize=16384`，影响 mmap 粒度与内存统计换算） |
| 启动链 | EFI → boot.efi → kernel | BootROM → LLB → iBoot → kernelcache（见 [Boot](/docs/CS/OS/mac/Boot.md)） |
| 内核扩展 | kext 为主 | kext 需用户授权，**DriverKit / System Extension 是正路**（见 [Darwin](/docs/CS/OS/mac/Darwin.md)） |
| 指针完整性 | 无 | arm64e 带 PAC（指针认证），系统二进制是 `arm64e`（见 [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)） |
| x86 兼容 | 原生 | Rosetta 2 即时翻译（`sysctl.proc_translated` 可查） |
| 虚拟化 | 依赖 VT-x | Hypervisor.framework + `kern.hv_support=1` |

## Map of This Section

**先弄清内核的形状**，否则后面每一节都会读歪。macOS 的内核 XNU 是混合内核：Mach 提供任务、线程、端口、IPC 与虚拟内存这些原语，BSD 层在其上提供 POSIX 人格（进程、fd、信号、socket、VFS），IOKit 是一个受限 C++ 的驱动框架。三者同处一个内核地址空间、同一特权级——这正是它"混合"而不是"微内核"的原因，也是 Mach IPC 的开销能被省掉的原因。这部分见 [Darwin](/docs/CS/OS/mac/Darwin.md)。

**内核懂了，再问系统是怎么起来的。** Apple Silicon 上没有 BIOS/EFI 那套，BootROM 固件逐级校验签名后把控制权交给 iBoot，再由 iBoot 加载预链接好的 kernelcache；系统盘上的"Macintosh HD"其实是只读的密封快照，运行时挂载的是它的快照而非卷本身。安全启动的档位、恢复模式、`boot-args` 的注入都挂在这条链上，见 [Boot](/docs/CS/OS/mac/Boot.md) 与 [Security](/docs/CS/OS/mac/Security.md)。

**起来之后是存储布局。** macOS 11 起系统卷是密封只读的，用户数据放在另一个卷上，两者靠 firmlink 在 `/usr/share/firmlinks` 里声明的路径缝合起来——所以你在 `/Applications` 看到的东西物理上在 Data 卷。APFS 的容器/卷组/快照/克隆模型、五个卷各自的角色，见 [File System](/docs/CS/OS/mac/File_System.md)。

**用户态的骨架是 launchd**，而不是 sysvinit 或 systemd。它统一管理 daemon、agent、XPC service 与登录会话，域（system / user / login / gui）决定了服务的生命周期归属；`launchctl` 早年的 `load`/`unload`/`start`/`stop` 已经被 `bootstrap`/`bootout`/`kickstart` 取代，写在老教程里的命令现在大多报 "Unrecognized subcommand"。见 [Service Management](/docs/CS/OS/mac/Service_Management.md)。

**内存这块单独拎出来讲**是因为它和 Linux 的直觉差别很大：Mach 的 VM 层以 vm_object 为骨架，内存压力先走压缩器（compressor）再走 swap，Activity Monitor 里的 "Memory Used" 与 `vm_stat` 的口径对不上是常态。见 [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)。

**安全模型是 macOS 最"非 Unix"的部分**：SIP 限制 root 能做什么、Gatekeeper 与公证决定一个下载来的 app 能不能启动、TCC 把敏感目录和硬件（摄像头、麦克风、桌面）从"文件权限"里拿出来单独授权、FileVault 与 Secure Enclave 负责静态加密。它们层层叠加，任何一层没搞对都会得到一句含糊的报错。见 [Security](/docs/CS/OS/mac/Security.md)。

**软件怎么分发、怎么开发**是生态侧的两条主线：分发侧有 `.app` bundle、`.pkg` 安装包、`.dmg` 磁盘映像三种形态，签名与公证是能不能过 Gatekeeper 的关键，App Store 与 Homebrew 是两条并行渠道；开发侧是 Xcode / Command Line Tools / SDK / `xcrun` 这套工具链。分别见 [Package](/docs/CS/OS/mac/Package.md) 与 [Development](/docs/CS/OS/mac/Development.md)。

**硬件侧的分水岭是 Apple Silicon**，不只是换架构：统一内存、大小核（`hw.nperflevels`）、AMX 与神经引擎、16 KiB 页、arm64e 的 PAC、以及 Rosetta 2 的翻译层，都改变了性能调优和二进制兼容的判断方式。见 [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)。

**边界地带留了两篇**：在非 Apple 硬件上安装 macOS 的 [Hackintosh](/docs/CS/OS/mac/Hackintosh.md)，以及在虚拟机里跑 macOS 的 [Virtualization](/docs/CS/OS/mac/Virtualization.md)——后者要区分 Apple 官方的 Virtualization.framework 与 VMware Fusion / UTM 这类第三方方案。

**日常工具自成一个子树**，入口在 [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)。它的前提值得先记住：macOS 自带的是 BSD 命令行而不是 GNU coreutils，所以 Linux 上写熟的 `sed -i`、`date -d` 在这里要么报错要么给出不同结果，见 [CLI](/docs/CS/OS/mac/Tools/CLI.md)。装软件走 [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md)（Apple Silicon 上前缀是 `/opt/homebrew`，Rosetta 下才是 `/usr/local`），终端与 shell 配置见 [Terminal](/docs/CS/OS/mac/Tools/Terminal.md)。想知道"系统现在在干什么"要靠苹果自己的动态追踪 [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)（SIP 开着时受限），性能与功耗有 [Performance](/docs/CS/OS/mac/Tools/Performance.md)，网络排查有 [Network](/docs/CS/OS/mac/Tools/Network.md)（网络配置存在 configd 里而不是配置文件）。第三方应用选型清单在 [Software](/docs/CS/OS/mac/Tools/Software.md)，调试器见 [LLDB](/docs/CS/OS/mac/LLDB.md)。

## Quick Orientation

判断一台机器"现在到底是什么状态"，这几条最省事：

```shell
sw_vers                       # macOS 版本与 build
uname -v                      # Darwin 与 xnu 版本串
sysctl -n machdep.cpu.brand_string hw.memsize hw.pagesize   # 芯片 / 内存 / 页大小
csrutil status                # SIP 是否开启
spctl --status                # Gatekeeper 评估是否启用
lsof -i :8080                 # 查端口占用
pmset -g custom               # 电源与睡眠配置
```

## Links

- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [File System](/docs/CS/OS/mac/File_System.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)

## References

1. [apple-oss-distributions/xnu](https://github.com/apple-oss-distributions/xnu)
2. [Apple Open Source Releases](https://opensource.apple.com/releases/)
3. [Apple Open Source](https://opensource.apple.com/)
4. [macOS Release Notes](https://developer.apple.com/documentation/macos-release-notes)
5. [Apple Platform Security](https://support.apple.com/guide/security/welcome/web)
