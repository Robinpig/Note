## Introduction

Darwin 是 macOS 的开源基座，由 **XNU 内核**加一套 BSD 用户态（libSystem、shell、基础命令）组成。它提供 POSIX 语义与 Mach 原语，但不包含任何图形界面——Quartz、Aqua、Cocoa、Metal 这些"让 macOS 像 macOS"的部分是闭源的，不在 Darwin 里。所以从 Darwin 的角度看 macOS，看到的是一个 Unix，而不是一个桌面。

XNU 是 **X is Not Unix** 的递归缩写，本质是混合内核（hybrid kernel）：Mach 微内核的血统 + BSD 的 POSIX 人格 + 一个用受限 C++ 写的驱动框架 IOKit，三者编译进同一个内核镜像、跑在同一地址空间和同一特权级。

## Three Layers

| 层 | 源码目录 | 提供的抽象 | 谁在用 |
| :--- | :--- | :--- | :--- |
| Mach | `osfmk/` | task / thread / port / message / memory object，调度、虚拟内存、IPC | 内核内部、libsystem 的 `_kernelrpc_*` 包装 |
| BSD | `bsd/` | process / fd / signal / socket / VFS / cred / kauth / MACF | 绝大多数应用走的 POSIX 接口 |
| IOKit | `iokit/`、`libkern/` | 驱动对象树、匹配与即插即用、电源管理 | kext、DriverKit 用户态驱动 |

Mach 管的是"资源所有权"：task 是虚拟地址空间与端口权的持有者，thread 是执行流，port 是单向通信通道，内存通过 memory object 抽象交给外部 pager。BSD 管的是"Unix 人格"：进程号、信号、文件描述符、socket、凭证。IOKit 则是驱动模型，用 C++ 类层次 + 发布订阅匹配，让驱动可以按需加载卸载而不改内核核心代码。

## Why Hybrid, Not Microkernel

Mach 3 的原设计是真正的微内核：I/O、文件系统、网络都放在用户态服务进程里，靠消息传递通信。这个设计在 CMU 跑通了，但性能不行——每次跨层操作都要一次 IPC。Apple 的取舍是**保留 Mach 的概念分层，取消它的地址空间隔离**：BSD 与 Mach 链接进同一个内核镜像，跨层调用变成直接函数调用，IPC 开销归零。

结果是"混合"这个词的准确含义：抽象上是分层的（Mach 原语清晰、BSD 建立在它之上），物理上是一体的（同一个内核地址空间，一次 panic 全盘皆输）。这个决定带来的好处是模块化程度高于纯宏内核，代价是 Mach IPC 的安全隔离优势基本没了。

## Two Syscall Entrances

用户态进内核有**两个入口**，靠调用号的正负号区分，这是 XNU 特有的形态，也是很多跨平台工具（ptrace、strace 类）在 macOS 上难做的根本原因之一。

Mach trap 用**负**编号，定义在 `osfmk/mach/syscall_sw.h`：

```c
kernel_trap(_kernelrpc_mach_vm_allocate_trap,-10,5) /* 4 args, +1 for mach_vm_size_t */
kernel_trap(_kernelrpc_mach_vm_map_trap,-15,9)
kernel_trap(_kernelrpc_mach_port_allocate_trap,-16,3)
kernel_trap(mach_reply_port,-26,0)
kernel_trap(thread_self_trap,-27,0)
kernel_trap(task_self_trap,-28,0)
kernel_trap(host_self_trap,-29,0)
kernel_trap(mach_msg_trap,-31,7)
```

BSD syscall 用**正**编号，从 1 起，定义在 SDK 的 `sys/syscall.h`：

```c
#define	SYS_exit           1
#define	SYS_fork           2
#define	SYS_open           5
#define	SYS_mmap           197
#define	SYS_kevent         363
```

用户态平时并不直接写这些号：BSD 侧由 libSystem 的 `libsystem_kernel` 提供 C 函数，Mach 侧由同样的库提供 `_kernelrpc_mach_vm_map_trap` 之类的封装（SDK 的 `mach/mach_traps.h` 里能看到它们的原型）。要观察进程实际走了哪些调用，`dtruss` 是 macOS 上的对应工具（见 [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)），但它受 SIP 限制，默认不可用。

## BSD Sits on Mach, in Both Directions

BSD 层"在 Mach 之上"这句话容易理解成单向依赖，实际是**双向**的：每个 BSD 进程（`proc`）对应且仅对应一个 Mach task，两边都能直接查到对方。`bsd/sys/proc_internal.h` 里的这组函数就是证据：

```c
extern void proc_set_task(proc_t, task_t);
extern task_t proc_get_task_raw(proc_t proc);
extern proc_t task_get_proc_raw(task_t task);
```

因此有几个直接推论：

- **pthread 是 Mach thread 的封装**，`thread_self_trap()` 拿到的就是当前线程的 Mach port；
- **进程的资源边界是 task 边界**，Mach 的 vm_map 才是地址空间的真身，`proc` 只是它的 BSD 侧记账结构；
- **`mach_*` 调用可以绕过 BSD 层**直接改另一个 task 的内存——这正是 SIP 要封堵的能力，也是 `task_for_pid()` 需要特权的原因。

## Source Tree

XNU 源码由 Apple 发布在 `apple-oss-distributions/xnu`，顶层目录的职责（取自仓库 README）：

| 目录 | 职责 |
| :--- | :--- |
| `osfmk/` | Mach 子系统：task、thread、IPC、VM、调度器、体系结构胶水 |
| `bsd/` | BSD 子系统：进程、syscall、网络、VFS、凭证、信号 |
| `iokit/`、`libkern/` | IOKit 驱动框架与其 C++ 运行时 |
| `pexpert/` | 平台相关代码：中断处理、原子操作 |
| `libsyscall/` | 用户态 syscall 库接口 |
| `libsa/` | 内核启动引导代码 |
| `libkdd/` | 解析 kernel chunked data 的用户态库 |
| `security/` | 强制访问控制（MACF）策略接口与实现 |
| `config/`、`SETUP/`、`makedefs/` | 配置、内核版本与 kext symbol 管理、构建规则 |
| `EXTERNAL_HEADERS/` | 从其它项目同步来的头文件，避免构建依赖环 |
| `san/`、`tests/`、`tools/` | Sanitizer、测试、调试与性能剖析工具 |

构建由两个 make 变量驱动，`KERNEL_CONFIGS` 决定变体（debug / development / release / profile，对应不同的断言与编译选项），`ARCH_CONFIGS` 决定架构：

```shell
make SDKROOT=macosx.internal ARCH_CONFIGS=ARM64 KERNEL_CONFIGS=DEVELOPMENT
```

产物是 `kernel.[config]`（可引导镜像）与 `kernel.[config].unstripped`（带符号，供 LLDB 调试用）。调试内核还需要 KDK（Kernel Debug Kit），本机默认不装。

## Kernelcache and Kernel Extensions

macOS 实际启动加载的不是裸 kernel，而是**预链接好的 kernelcache**：内核与其依赖的 kext 被静态链接成一个镜像，省掉启动时的动态链接开销。本机可以看到两套东西——发布在 `/System/Library/Kernels/` 的通用与各机型变体，以及真正被加载的 cache（位于 Preboot 卷上，路径随系统版本哈希变化）：

```shell
$ ls /System/Library/Kernels/
kernel                    kernel.release.t6000    kernel.release.t6020
kernel.release.t6030      kernel.release.t6031    kernel.release.t6041
kernel.release.t8103      ...
```

```shell
$ ls /System/Volumes/Preboot/*/boot/*/System/Library/Caches/com.apple.kernelcaches/
```

kext（kernel extension）是内核态驱动包，放在 `/System/Library/Extensions`（Apple）与 `/Library/Extensions`（第三方）。内核对外只暴露有限接口，即 `com.apple.kpi.*` 系列：

```shell
$ kextstat | head -4
Index Refs Address            Size       Wired      Name (Version) UUID
    1  217 0                  0          0          com.apple.kpi.bsd (24.3.0)
    2   11 0                  0          0          com.apple.kpi.dsep (24.3.0)
    3  245 0                  0          0          com.apple.kpi.iokit (24.3.0)
```

kpi 是 kernel programming interface 的缩写，一个 kext 只能链接它声明过的 kpi，版本号必须与内核匹配，否则拒绝加载。在 Apple Silicon 上第三方 kext 还额外需要用户在恢复模式里显式降低安全策略并重启授权——这正是 Apple 推动**DriverKit 与 System Extension** 取代 kext 的原因：驱动跑在用户态，崩溃不致于拖垮内核。

## Kernel Startup

启动的三个阶段分别落在三个子系统里，读源码时按这个顺序看：`osfmk/kern/startup.c`（Mach 子系统初始化）→ `bsd/kern/bsd_init.c`（BSD 层上线，POSIX 人格就绪）→ `iokit/Kernel/IOStartIOKit.cpp`（C++ 运行时就绪，驱动匹配开始）。启动子系统带 rank，最后有一个 lockdown 阶段：把标记了 `__startup_data` / `__startup_const` 的数据和 `__startup_func` 的代码**解除映射**，把 `__security_const_late` 变成只读——启动期的一次性代码从此不存在，攻击面随之缩小。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [LLDB](/docs/CS/OS/mac/LLDB.md)

## References

1. [apple-oss-distributions/xnu](https://github.com/apple-oss-distributions/xnu)
2. [XNU README — source tree and build](https://github.com/apple-oss-distributions/xnu/blob/main/README.md)
3. [Kernel Programming Guide — Apple Developer Documentation Archive](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/About/About.html)
4. [Mach Overview](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/Mach/Mach.html)
5. [IOKit Fundamentals](https://developer.apple.com/library/archive/documentation/DeviceDrivers/Conceptual/IOKitFundamentals/Introduction/Introduction.html)
