## Introduction

Apple Silicon（M 系列）不是"把 macOS 从 x86 移植到 ARM"这么简单。换了架构之后，一批在 Linux / Intel 上成立的默认假设失效了：页大小变了、核心不再是同构的、内存不再是 CPU 独占的、指针带上了加密签名、二进制多了一层动态翻译。

这些变化大多数不体现在 API 上（POSIX 接口照旧可用），而是体现在**性能特征、二进制兼容和调试方式**上。搞清楚它们，才能解释"为什么同样的代码在 Mac 上跑出不一样的数字"。

## Unified Memory

Apple Silicon 是统一内存架构（UMA）：CPU、GPU、神经引擎共用同一块物理内存，不再有"系统内存"与"显存"的区分，也不需要显式拷贝。

```shell
$ sysctl -n hw.memsize
34359738368        # 32 GB，CPU 与 GPU 共享
```

好处是 GPU 可以直接访问 CPU 的数据（对 Metal 与机器学习负载影响明显），代价是**内存容量不可扩展**，且"内存不足"的现象与独显机器不同——GPU 吃内存会直接挤压系统的可用量。买机器时的容量决策因此比 Intel 时代重要得多。

## Heterogeneous Cores

M 系列同时有性能核（P core）与能效核（E core），系统通过 `hw.nperflevels` 暴露层级数：

```shell
$ sysctl -n hw.nperflevels hw.perflevel0.logicalcpu hw.perflevel1.logicalcpu
2
6
2        # 本机 M1 Pro：6 个性能核 + 2 个能效核
```

调度由内核按 QoS（Quality of Service）类决定落在哪一级：后台任务、UI 交互、用户发起的任务分别对应不同 QoS。这对性能测量的实际意义是——**同一段代码跑在不同 QoS 上，耗时可以差一倍以上**，基准测试必须固定 QoS，否则结果不可复现。

要强制指定核心类型，可以用 `taskpolicy`（或 `posix_spawn` 的 `QOS_CLASS_*` 属性）而不是靠 `nice`。

## arm64e and Pointer Authentication

Apple Silicon 上的系统二进制是 **arm64e**，不是普通的 arm64。差别在于 arm64e 启用了 PAC（Pointer Authentication Codes）：利用 64 位指针里未使用的高位存一段加密签名，写入时签名、读出时验证，任何中途篡改都会让签名失效。

```shell
$ codesign -dv /Applications/Safari.app 2>&1 | head -3
Format=app bundle with Mach-O universal (x86_64 arm64e)
```

机制上：返回地址用**每进程唯一**的密钥签名、以栈指针为 salt；函数指针用**跨进程共享**的固定密钥（这样库的指针可以在进程间共享）；虚表项用共享密钥 + 方法签名派生的 salt。

实践影响：

- 系统自带二进制是 arm64e，第三方 app 通常仍是 arm64（`arm64` 二进制可以在 arm64e CPU 上跑，反之不行）；
- 崩溃日志里出现 `KERN_INVALID_ADDRESS at 0x0040000105394398 -> 0x0000000105394398 (possible pointer authentication failure)` 就是典型的 PAC 失败形态——高位被置位导致指针非法；
- 自己手写汇编或直接操作栈指针的代码（崩溃采集库、JIT）需要显式处理 PAC，`ptrauth.h` 里的 `ptrauth_strip` 是官方工具。

## Rosetta 2

Rosetta 2 是 x86-64 → arm64 的即时翻译层，让 Intel 二进制无需重编译就能跑。它不是模拟器（不模拟硬件），而是**二进制翻译**：首次运行时把 x86-64 指令翻译成 arm64 并缓存，之后直接执行缓存。

```shell
sysctl -n sysctl.proc_translated      # 当前进程是否被翻译：1 = 是
arch -x86_64 zsh                      # 强制以 x86_64 模式启动进程
```

能力边界值得记住：Rosetta 2 支持大多数用户态应用，但**不支持内核扩展、不支持虚拟化 x86-64 虚拟机、不支持 AVX 等部分向量指令**。所以 Docker/虚拟机这类依赖虚拟化的 x86 负载在 Apple Silicon 上必须走 ARM 镜像。

Apple 已明确 Rosetta 2 是过渡方案：随着 Intel Mac 在 macOS 27 全面停止支持，它剩下的价值只是跑那些不再维护的老二进制。

## 16 KiB Pages

Apple Silicon 上页大小是 **16 KiB**，Intel Mac 是 4 KiB：

```shell
$ sysctl -n hw.pagesize
16384
```

影响面比想象中广：mmap 的最小粒度变大、小文件的内存占用上升、按页计数的统计量（`vm_stat`、RSS）换算系数变化、以及**依赖 4 KiB 页假设的代码**（某些数据库与 JIT 的内存管理）会出问题。Rosetta 2 翻译的 x86-64 进程看到的仍是 4 KiB 逻辑页，由内核做转换。

## Accelerators

M 系列 SoC 上挂了一批 Apple 未完全公开的协处理器，它们决定了"什么负载在 Mac 上特别快"：

| 单元 | 用途 | 访问方式 |
| :--- | :--- | :--- |
| AMX（Apple Matrix coprocessor） | 矩阵运算，Accelerate / BLAS 的底层 | 无公开指令文档，通过 Accelerate 等框架间接使用 |
| Neural Engine（ANE） | 神经网络推理 | Core ML；第三方**无直接公开 API** |
| GPU | 图形与通用计算 | Metal / Metal Performance Shaders |
| Secure Enclave | 密钥管理、 biometric、LocalPolicy 签名 | Security 框架 |
| Always On Processor | 低功耗常驻，"嘿 Siri"、手环解锁 | 系统私有 |
| Media Engine | ProRes / HEVC 硬件编解码 | VideoToolbox |

AMX 这一点常被误解：它不需要（也无法）手写汇编调用，Apple 通过 Accelerate 框架的 BLAS/LAPACK 实现自动派发。想吃到这块性能，正确做法是用 Accelerate 而不是自己写 NEON。

## Virtualization

Apple Silicon 提供两层虚拟化能力：

```shell
$ sysctl -n kern.hv_support
1        # Hypervisor.framework 可用
```

- **Hypervisor.framework（HVF）**：底层的 type-2 hypervisor 接口，暴露 ARM 的虚拟化扩展，QEMU / UTM 这类方案基于它。
- **Virtualization.framework**：更高层的 Objective-C / Swift API，提供了完整的虚拟机抽象（含 macOS 客户机支持、Rosetta 支持、 VirtIO 设备）。

注意它**不能虚拟化 x86-64**：ARM 主机上只能跑 ARM 客户机。这与 [Virtualization](/docs/CS/OS/mac/Virtualization.md) 里说的第三方方案是两套东西。

## What Changes for Developers

| 在 Linux / Intel 上的习惯 | Apple Silicon 上的实际情况 |
| :--- | :--- |
| 用 `uname -m` == `x86_64` 判断架构 | 可能是 `arm64`，也可能是 Rosetta 翻译下的 `x86_64` |
| 页大小当 4 KiB 用 | 16 KiB，必须读 `hw.pagesize` |
| 所有核同构，绑核用 `taskset` | 异构，用 QoS / `taskpolicy` |
| 显存与内存分开算 | UMA，共用同一池 |
| 装 x86 二进制依赖包 | 需 arm64 版本，或走 Rosetta（Homebrew 在 `/opt/homebrew` 而非 `/usr/local`） |
| 二进制用 `file` 看架构 | 还要注意 `arm64` vs `arm64e` 的 CPU subtype |

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Virtualization](/docs/CS/OS/mac/Virtualization.md)
- [Development](/docs/CS/OS/mac/Development.md)

## References

1. [Preparing your app to work with pointer authentication](https://developer.apple.com/documentation/security/preparing-your-app-to-work-with-pointer-authentication)
2. [About the Rosetta translation environment](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment)
3. [Tuning your code's performance for Apple silicon](https://developer.apple.com/documentation/apple-silicon/tuning-your-code-s-performance-for-apple-silicon)
4. [Virtualization — Apple Developer Documentation](https://developer.apple.com/documentation/virtualization)
5. [Apple silicon — Apple Platform Security](https://support.apple.com/guide/security/apple-silicon-sec3a0e319d9/web)
