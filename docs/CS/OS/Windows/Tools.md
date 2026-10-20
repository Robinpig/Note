## Introduction

在 Windows 上写程序的第一个决定不是语言，而是**你到底要多少人替你的 exe 负责 CRT/POSIX 那一层**。这个决定决定了：编出来的二进制能不能在没有安装任何东西的机器上跑、能不能用 fork 与 `pthreads`、能不能对接 MSVC 编译出来的库。

本文按"编译工具链 → 观察与调试工具 → 包管理与日常工具"这条线索把这节的工具讲清楚。重点是前三者的对比——它们名字相近、常被混为一谈，但 ABI 立场完全不同。

---

## Three Toolchains: MSVC, MinGW-w64 and Cygwin

### MinGW-w64

MinGW-w64 是一组头文件、导入库、库与工具的集合，配上一个编译器（GCC 或 LLVM）之后，就得到一个**原生 Windows 应用**的完整开发环境。它是 2007 年从 mingw.org 分出来的，目的是提供 64 位支持与更新的 API，后来反倒成了主流。

关键性质：**它编出来的是原生 Windows 二进制**，依赖 Windows 自带的 CRT（`msvcrt.dll` 或 UCRT），不需要额外的 DLL 运行时。

参考：[mingw-builds 发布页](https://github.com/niXman/mingw-builds-binaries/releases)

### Cygwin

Cygwin 是另一回事，它的定位由两部分组成：

1. 一大堆 GNU 与开源工具，让 Windows 上获得接近某个 Linux 发行版的体验；
2. **`cygwin1.dll`**——这个 DLL 提供了相当完整的一层 POSIX  API 能力。

关键性质：Cygwin 编出来的程序**依赖 `cygwin1.dll`**，而这个 DLL 把 POSIX 语义翻译到 Win32 API 上——包括 fork、信号、伪终端这些东西。这就意味着它会带来一层适配开销，以及一个必须随附的运行时。

### MSYS2

MSYS2 基本可以把上面两者的边界拉平：它是一个带着 Arch Linux 风格 `pacman`、MinGW-w64 工具链、以及 Cygwin 派生出来的 POSIX 兼容层（精简版）的环境。日常使用上一句话概括：**MSYS2 是今天的实际答案**：它既是包管理器，也是一组任选目标（mingw64/ucrt64/clang64/msys）的工具平台。

### Comparison

| 维度 | MSVC | MinGW-w64 | Cygwin / MSYS2(msys) |
| :-- | :-- | :-- | :-- |
| 产物 | 原生 Windows | 原生 Windows | 依赖 POSIX 兼容 DLL |
| ABI | MSVC ABI（Windows 事实标准） | GCC ABI | POSIX 语义适配层 |
| 与其他库互通 | 最佳（Windows 生态默认） | 与 MSVC 混用时需谨慎处理异常、迭代器、内存模型 | 一般只与同族互通 |
| 需要随附运行时 | Visual C++ Redistributable（或静态链接） | 无（或用 UCRT 已是系统组件） | `cygwin1.dll` / `msys-2.0.dll` |
| 适用场景 | Windows 原生应用、驱动、必须与 MSVC 库互操作 | 跨平台 C/C++、原生二进制、CI | 需要 fork/PTY/signals 等 POSIX 能力的 Unix 软件 |

> [!WARNING]
>
> **不要跨 ABI 混用 C++ 库**
>
> MSVC 与 GCC/Clang 在 C++ 层面互不兼容：异常传播、`std::string` 与 STL 容器的内存布局、以及 CRT 的所有权（谁负责释放这块内存）都不一样。C 层面的 ABI 相对可控，C++ 则几乎是"谁编译就由谁负责"。跨工具链时使用 **C 接口**或显式约定导出/释放函数。

> [!NOTE]
>
> 关于二者差别的经典讨论见 [Stack Overflow: What is the difference between Cygwin and MinGW?](https://stackoverflow.com/questions/771756/what-is-the-difference-between-cygwin-and-mingw)——它值得读的点不在于结论，而在于回答里把"POSIX 兼容层 vs 原生移植"这条界线说清楚了。

---

## Observation and Debugging Tools

Windows 在这件事上提供了别人给不了的东西。**Sysinternals** 是 Windows 内部的最重要的观察工具集（微软 2006 年收购），其中天天要用的几件：

| 工具 | 用途 |
| :-- | :-- |
| Process Explorer | 任务管理器替代品：看进程树、句柄、DLL、令牌 |
| Process Monitor（ProcMon） | 文件/注册表/进程/网络活动的实时过滤器。**排查"我改的注册表没生效""为什么 access denied"的主力** |
| VMMap | 看一个进程的 [VAD 树](/docs/CS/OS/Windows/Memory.md)：保留与提交、私有与共享的细分，是排查碎片与 OOM 的第一手证据 |
| Autoruns | 看全部自启动项（远超任务管理器里的"启动"页） |
| Handle / PsExec / PsList | 谁占着这个文件、以系统权限跑一个命令、列紧凑的进程信息 |
| WinObj | 直接看对象管理器的命名空间树——理解"\Device vs 盘符"的最好方式 |

更深一层是 **ETW（Event Tracing for Windows）**：内核与各组件里内置的、低开销的结构化事件通道。Windows Performance Recorder/Analyzer（WPR/WPA）是它的界面层，也是分析启动耗时、DPC/ISR 延迟、CPU 调度、磁盘延迟这些问题的正规方法——相当于把 perf/eBPF 那套事件通道做进了系统自带工具。

**WinDbg** 则是内核调试的角色：分析内存转储、符号与崩溃调用栈。它处理蓝屏的方式与 gdb 看 panic 不同，因为 Windows 里可供判定故障的信息更丰富——IRQL、驱动校验器、分页池与非分页池的归属都在 dump 里。

---

## Package Management

| 工具 | 风格 | 说明 |
| :-- | :-- | :-- |
| **winget** | 微软官方、随系统提供 | `winget install <pkg>`，仓库来自社区 manifest + 微软验证过的 source |
| **Chocolatey** | 老牌、重量级 | 脚本化的安装模型，生态最大，适合写进系统部署脚本 |
| **Scoop** | 极简、用户级 | 默认装到用户目录，不需要管理员权限，适合个人开发机 |

三者可以同时装，但**尽量只用一种**：混用会让"这软件到底是谁装的、怎么升级"变得难以回答。

---

## PowerToys

PowerToys 是微软把那些"Windows 里一直缺一小块"的功能打包在一起的工具集。常用项：

- **Keyboard Manager**：重映射键位/快捷键（本文最早就是因为"修改键位"这件事而收录它的）；
- **PowerToys Run**：Alt+Space 唤起的执行器，可以取代开始菜单搜索；
- **FancyZones**：窗口布局管理，多显示器下的分区；
- **File Locksmith**：看"这个文件被谁占着"——与上面的 Handle 异曲同工，但有 GUI；
- **Awake**：临时阻止休眠；
- **Color Picker / Text Extractor / Image Resizer** 之类的小工具。

---

## Windows Terminal

Windows Terminal 本身不是壳，它是**宿主**：标签页、GPU 加速渲染、Unicode/emoji、多 profile（Windows PowerShell、PowerShell 7、CMD、WSL 各发行版、Azure Cloud Shell），以及 JSON 配置文件。它的价值在于把前面那些互不兼容的控制台统一到一个窗口里，见 [CMD](/docs/CS/OS/Windows/CMD.md)。

---

## Links

- [命令行与 PowerShell](/docs/CS/OS/Windows/CMD.md)
- [WSL](/docs/CS/OS/Windows/WSL.md)
- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows](/docs/CS/OS/Windows/Windows.md)

---

## References

1. [MinGW-w64](https://www.mingw-w64.org/)
2. [Cygwin](https://cygwin.com)
3. [MSYS2](https://www.msys2.org/)
4. [Sysinternals Utilities](https://learn.microsoft.com/en-us/sysinternals/)
5. [Windows Package Manager (winget)](https://learn.microsoft.com/en-us/windows/package-manager/)
6. [PowerToys](https://learn.microsoft.com/en-us/windows/powertoys/)
