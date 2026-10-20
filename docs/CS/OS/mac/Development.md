## Introduction

macOS 的开发工具链是围绕 **Xcode** 组织的，但多数时候你并不需要打开它。真正决定编译器、SDK、签名工具用的是哪一套的，是 `xcode-select` 指向的那个 Developer 目录——理解这一点能省掉大量"为什么命令行和 IDE 行为不一样"的困惑。

工具链的关键结构是这样的：Xcode.app 里带着完整的 SDK 与工具链，Command Line Tools 是它的一个精简子集，`xcrun` 是统一入口。三者加上 `xcode-select` 的切换，构成了 macOS 上"多版本工具链共存"的机制。

## Xcode vs Command Line Tools

| | Xcode | Command Line Tools（CLT） |
| :--- | :--- | :--- |
| 体积 | 数十 GB | 数百 MB |
| 内容 | IDE、SDK、模拟器、Instruments、Metal 工具 | 编译器、链接器、SDK 头、make/git 等命令行工具 |
| 用途 | App 开发、界面调试、性能分析 | 命令行编译、Homebrew 依赖、脚本构建 |

```shell
$ xcode-select -p
/Applications/Xcode.app/Contents/Developer

$ clang --version
Apple clang version 16.0.0 (clang-1600.0.26.3)
Target: arm64-apple-darwin24.3.0

$ pkgutil --pkg-info=com.apple.pkg.CLTools_Executables
version: 16.4.0.0.1.1747106510
```

注意 `clang` 报的 target 是 `arm64-apple-darwin24.3.0`：架构-厂商-**Darwin 版本**都在里面，这正是 [Darwin](/docs/CS/OS/mac/Darwin.md) 里说的版本对应关系在工具链上的体现。

装了 Xcode 之后 CLT 仍然是独立的包（上面的 `CLTools_Executables`），两者可以共存；`xcode-select -s <路径>` 决定当前生效的是哪一套，CI 与多版本环境下经常靠它切换。

## xcrun

`xcrun` 是工具链的统一入口，它的价值在于**永远解析到当前选定 Developer 目录里的那个工具**。直接调 `/usr/bin/clang` 或写死 `/usr/bin/git`，实际上调的是 xcode-select 的 shim，行为随当前选择变化——所以脚本里应该用 `xcrun`：

```shell
xcrun --find clang          # 找出实际路径
xcrun --show-sdk-path       # 当前 SDK 路径
xcrun --sdk macosx --show-sdk-version    # SDK 版本（本机 15.0）
xcrun --sdk macosx clang ...             # 指定 SDK 调工具
```

两个环境变量值得记住：`SDKROOT` 决定编译时用哪个 SDK，`MACOSX_DEPLOYMENT_TARGET` 决定产出的二进制**最低支持哪个 macOS 版本**。SDK 版本（向后能看到新 API）与部署目标（向前能跑在老系统上）是两件事，混淆它们会得到"在我机器上能跑、用户机器上崩"的经典问题。

## SDKs

SDK 是分版本安装的，本机上能看到多个并存：

```shell
$ pkgutil --pkgs | grep CLTools_SDK
com.apple.pkg.CLTools_SDK_macOS12
com.apple.pkg.CLTools_SDK_macOS13
com.apple.pkg.CLTools_SDK_macOS14
com.apple.pkg.CLTools_SDK_macOS_LMOS
```

SDK 本质是一份"目标系统的头文件与 stub 库"快照，编译期用它做符号解析，运行期则是 dyld 在真机上解析——所以**编译通过不等于能在老系统上跑**，弱链接（weak linking）与 `if (@available(...))` 才是应对方式。

## Building

| 方式 | 命令 | 适用 |
| :--- | :--- | :--- |
| Xcode 命令行构建 | `xcodebuild -scheme X -configuration Release` | 有 Xcode 工程的项目 |
| 归档与导出 | `xcodebuild -archivePath` + `-exportArchive` | 打包分发（见 [Package](/docs/CS/OS/mac/Package.md)） |
| Swift Package Manager | `swift build` / `swift test` / `swift package` | Swift 库与命令行工具 |
| 传统 Makefile | `make` + `xcrun` | 移植的 Unix 项目 |

签名在现代 Xcode 里是构建流程的一部分：Xcode 会自动选择合适的签名身份与 profile，失败时通常报 `No signing certificate` 或 entitlements 不匹配，而不是链接错误。

## Universal Binaries

macOS 的 fat binary（Mach-O universal）可以在一个文件里装多个架构切片，用 `lipo` 操作：

```shell
$ lipo -archs /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal
x86_64 arm64e

$ file /path/to/Terminal
Mach-O universal binary with 2 architectures: [x86_64:Mach-O 64-bit executable x86_64] [arm64e]

lipo -create -output <universal> <arm64-bin> <x86_64-bin>   # 合并
lipo -thin arm64 <universal> -output <thin>                  # 抽出单个架构
```

系统二进制同时带有 `x86_64` 与 `arm64e` 两个切片——注意是 arm64e 而非 arm64（PAC 的区别见 [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)）。Xcode 里控制它的是 `ARCHS` 与 `ONLY_ACTIVE_ARCH`：后者在 Debug 构建下默认开启，只编当前架构以加快编译，这有时会让"Debug 能跑、Archive 失败"。

## Debugging and Profiling

调试器是 LLDB（见 [LLDB](/docs/CS/OS/mac/LLDB.md)），性能分析的主力是 Instruments：

| Instruments 模板 | 看什么 |
| :--- | :--- |
| Time Profiler | CPU 时间分布，调用栈采样 |
| Allocations | 分配量、存活对象、对象增长趋势 |
| Leaks | 泄漏检测 |
| VM Tracker | 虚拟内存区域与脏页 |
| System Trace | 系统调用、线程调度、上下文切换 |

不想开 Instruments 时，命令行有一组等价工具：`sample`（采样进程调用栈）、`spindump`（含内核栈与等待链，卡顿分析常用）、`heap`、`leaks`、`vmmap`（地址空间与 footprint）。内存相关的口径问题见 [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)。

DTrace 系工具（[dtruss](/docs/CS/OS/mac/Tools/dtruss.md)）在系统调用跟踪上很有用，但受 SIP 限制需要关掉才能用；日常更轻量的替代是 `os_signpost` + Instruments，或用 `log` 命令配合统一日志系统。

## Media and Acceleration

GPU 与专用硬件的开发入口都在框架层：Metal（图形与通用计算）、Core ML（模型推理，会派发到 Neural Engine）、VideoToolbox（硬件编解码）、Accelerate（BLAS/LAPACK，会派发到 AMX）。这些框架的调度细节见 [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Package](/docs/CS/OS/mac/Package.md)
- [LLDB](/docs/CS/OS/mac/LLDB.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)

## References

1. [Xcode — Apple Developer](https://developer.apple.com/xcode/)
2. [xcodebuild man page](https://www.unix.com/man-page/osx/1/xcodebuild/)
3. [Swift Package Manager](https://www.swift.org/documentation/package-manager/)
4. [Instruments Help](https://help.apple.com/instruments/)
5. [Metal — Apple Developer Documentation](https://developer.apple.com/documentation/metal)
