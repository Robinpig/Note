## Introduction

Windows Subsystem for Linux（WSL）让开发者在 Windows 上装一个 Linux 发行版（Ubuntu、Debian、Kali、SUSE 等），直接使用 Linux 的应用程序、工具与 Bash 命令行，**不需要传统虚拟机的开销，也不需要双启动**。

它值得当作操作系统材料而不是"小工具"来讲，因为它是一次架构上的认输与重新出发：NT 曾经尝试用"API 翻译层"（当年的 POSIX 子系统与后来的 SUA，见 [架构篇](/docs/CS/OS/Windows/Architecture.md)）去兼容 Unix 世界，最终没能追上；WSL 2 的回答是——**那就直接跑一个真的 Linux 内核**。

本文按三层推进：先看 **WSL 1 与 WSL 2 的架构差别**（两者不是版本迭代而是两条不同路线），再看**那条最重要的边界：跨 OS 的文件系统**，然后是**网络、systemd、GPU**这些现代称呼，最后给一份**配置清单**以及它与 Docker Desktop 的关系。

---

## Two Architectures, Not Two Versions

WSL 1 与 WSL 2 不是"老版本与新版本"，而是两套不同的实现，并且**可以共存**：每个发行版都能在两者之间来回切换（`wsl --set-version <distro> 1|2`）。

| 特性 | WSL 1 | WSL 2 |
| :-- | :-- | :-- |
| Windows 与 Linux 的整合 | ✅ | ✅ |
| 启动速度 | 快 | 快 |
| 相对传统虚拟机的资源占用 | 小 | 小 |
| 能否与当前版本的 VMware / VirtualBox 共存 | ✅ | ❌（VMware 15.5.5+ 可用，VirtualBox 仍不被支持） |
| 托管 VM（managed VM） | ❌ | ✅ |
| 完整的 Linux 内核 | ❌ | ✅ |
| **完整的系统调用兼容性** | ❌ | ✅ |
| **跨 OS 文件系统的性能** | **✅ 更好** | ❌ 较差 |
| systemd 支持 | ❌ | ✅ |
| IPv6 支持 | ✅ | ✅ |

这两列的最後两行构成了全部选型依据：

- **WSL 2 有真正的 Linux 内核**，因此 Docker、iptables、内核模块、`systemd`、`Btrfs` 这类东西都能跑；
- **WSL 1 在跨 OS 文件访问上更快**，因为它的那些 Linux 系统调用是直接翻译到 NT 内核上的，文件访问不必跨越虚拟机边界。

WSL 2 是现在的默认选项。它的结构是：微软用虚拟化技术在**一个轻量实用 VM（utility VM）**里跑 Linux 内核，各个发行版作为**隔离容器**跑在这个被管理的 VM 内。它们：

- 共享同一份 **网络命名空间**、设备树（`/dev/pts` 除外）、CPU / 内核 / 内存 / swap、以及 `/init` 二进制；
- 各自拥有独立的 **PID / mount / user / cgroup 命名空间**与自己的 `init` 进程。

WSL 2 的 Linux 内核由微软基于 kernel.org 的最新 stable 分支构建，为 WSL 2 做了体积与性能的专门调优，**由 Windows Update 分发维护**，并且是开源的（[microsoft/WSL2-Linux-Kernel](https://github.com/microsoft/WSL2-Linux-Kernel)）。

### When to Prefer WSL 1

微软自己也保留了 WSL 1 的存在理由，主要是这几种：

- 项目文件**必须**放在 Windows 文件系统上，而且会被 Windows 侧工具频繁访问；
- 同一个文件树上同时进行 Windows 与 Linux 两侧的交叉编译/工具调用；
- 需要访问**串口**（WSL 2 不支持串口；USB 设备则可通过 `usbipd-win` 项目接进去）；
- 对内存回收有严格要求——WSL 2 在实例关闭前不会把 cache 页还给 Windows；
- 需要发行版拿到与宿主同一网段的 IP（WSL 2 默认是 NAT）。

---

## The File System Boundary

这是日常最贵的一课：**把项目文件放在哪一边，比怎么优化都重要。**

| 位置 | 访问方 | 性能 |
| :-- | :-- | :-- |
| Linux 文件系统（如 `\\wsl$\Ubuntu\home\…`） | Linux 工具访问 | **最快** |
| Windows 文件系统（`/mnt/c/…`） | Linux 工具访问 | 慢（跨 OS 边界） |
| Linux 文件系统（`\\wsl$\…`） | Windows 工具访问 | 慢（走网络/Plan 9 重定向） |

微软给出的那条概括性建议非常直白：**把项目文件放在与你运行它的那些工具同一个操作系统上。** 也就是说：

- 用 Linux 工具编译、运行的仓库 → 放在 WSL 的 ext4 文件系统里；
- 在 Windows 侧编辑却要在 WSL 侧构建 → 那正是 WSL 1 更合适的场景，或用 VS Code Remote-WSL 之类让编辑器伸进 Linux 那一侧。

> [!TIP]
>
> **三条日常规则**
>
> 1. **不要**在 `/mnt/c` 下做 `git clone` 与 `npm install`——这两件事 WSL 2 上可能比 Linux 文件系统慢一个数量级；
> 2. 从 Windows 访问 Linux 文件用 `\\wsl$\<distro>\` 网络路径，**不要**通过 AppData 里的 ext4.vhdx 直接改；
> 3. 在 WSL 里要打开 Windows 资源管理器就执行 `explorer.exe .`——Windows 可执行文件在 WSL 里是可以直接调用的（互操作本身是 WSL 最顺手的地方）。

---

## Networking, systemd and GPU

### Networking Modes

WSL 2 默认使用 **NAT**（网络地址转换），这意味着 VM 有独立的 IP、并且会在重启后变化。微软在较新版本给出的替代是 **`networkingMode=mirrored`**：把宿主的网络接口视图镜像给 WSL 使用，让 localhost 与端口语义变得直观，还能直接吃到 VPN 与 IPv6。

| 模式 | 说明 |
| :-- | :-- |
| `nat`（默认） | 独立 IP + NAT；从 WSL 2.3.25 起 NAT 失败时会回退到 consomme 模式 |
| `mirrored` | 镜像宿主网络栈，localhost 语义与 Windows 一致（需要 Windows 11 22H2+） |
| `bridged` | 已弃用（自 WSL 2.4.5 起标记 deprecated） |
| `none` | 完全断开网络 |

`localhostForwarding`（默认 true）控制"WSL 里监听的端口能否从 Windows 的 localhost 访问"，但在 **mirrored 模式下会被忽略**——因为那时两者本来就是同一份接口视图。

### systemd

`systemd` 支持是 WSL 2 才有的（上表的对比里那一栏）。它的实际意义是：`systemctl`、单元文件、以及那些假定"有一个 systemd 在发起"的软件（snapd、很多服务的官方安装脚本）终于能正常工作。在此之前 WSL 用 `/init` 自己充当 PID 1。

### GPU and GUI

WSL 还能直接把设备的 GPU 用于 Linux 上的机器学习负载，并支持把 Linux **图形应用**集成进 Windows 桌面。这两个能力的共同点是：它们都不是"WSL 自己实现的"，而是把 Windows 侧的设备栈/窗口栈以某种方式接过去——这也是为什么它们对驱动版本很敏感。

---

## Configuration: .wslconfig

`.wslconfig` 为 WSL 2 上运行的**所有发行版**配置全局选项。它位于 `%UserProfile%\.wslconfig`（例如 `C:\Users\<you>\.wslconfig`），默认不存在，需要自己创建。

> [!WARNING]
>
> **`.wslconfig` 只对 WSL 2 生效**
>
> 这一点微软写得很明白：当前所有 `.wslconfig` 设置**仅适用于 WSL 2 发行版**；WSL 1 的发行版不受影响。此外它要求宿主至少是 Windows Build 19041。

```ini
# Settings apply across all Linux distros running on WSL 2
[wsl2]

# 分配给这个 VM 的内存。默认取宿主总内存的 50%
memory=4GB

# 分配给这个 VM 的逻辑处理器数量。默认与宿主的逻辑处理器数相同
processors=2

# 让 WSL 2 里监听 localhost 的端口可以从 Windows 的 localhost 访问。
# networkingMode=mirrored 时此项会被忽略
localhostForwarding=true

# 自定义内核时用这条（默认是微软维护的那个）
# kernel=C:\\temp\\myCustomKernel

# 镜像宿主网络栈，替代默认的 NAT（需要 Windows 11 22H2+）
# networkingMode=mirrored

# 改变 DNS 请求从 WSL 代理到 Windows 的方式（需 Windows 11 22H2+，默认 true）
# dnsTunneling=true

[experimental]
# 新创建的 VHD 自动设为稀疏格式
sparseVhd=true

# 自动回收缓存页：disabled / gradual / dropCache（默认 dropCache）
autoMemoryReclaim=dropCache
```

改完配置之后必须让 WSL **完全停止**再重启才生效：

```powershell
wsl --shutdown
```

文档里提到的"8 秒规则"值得记住：关掉所有发行版的 shell 之后，通常需要约 8 秒子系统才真正停下来。判断是否已停：

```powershell
wsl --list --running
```

> [!NOTE]
>
> **老配置清单里已经过时的项**
>
> 不少博客上的 `.wslconfig` 示例里还写着 `pageReporting=false`（用来阻止 WSL 把内存还给 Windows）。**当前 wsl-config 文档里已经没有这一项**——它连同旧的"[阻止释放内存"这类调参思路一起退场了。今天对应的现代做法是用上面那两个 `[experimental]` 项：`autoMemoryReclaim` 控制回收策略，`sparseVhd` 控制磁盘占用。
>
> 这正是「sysctl / 配置项存在 ≠ 它还生效」那一类问题：照旧的配置清单抄一遍，往往抄到的是历史。

---

## Installing and Updating

```powershell
wsl --install
```

Windows Version 19044 及以上执行 `wsl.exe --install` 时，会从 Microsoft Store 安装 WSL 这个应用包——也就是说 **WSL 的更新已经从"随 OS 更新"搬到了 Store 上**，因此能更快拿到新功能。已经在用 WSL 的话：

```powershell
wsl --update
```

若 Microsoft Store 在你的组织里不可访问，可以加 `--web-download`（代价是每次都要手动更新）：

```powershell
wsl --update --web-download
```

查看 WSL 版本与正在运行的发行版：

```powershell
wsl --version
wsl --list --running
```

前置条件：**Windows 功能里需要开启 WSL**（较新的系统上 `wsl --install` 会帮你做这件事），低于 build 14393 的版本完全不支持 WSL。

---

## WSL vs Docker Desktop

| 维度 | 纯 WSL 2 | Docker Desktop（WSL 2 backend） |
| :-- | :-- | :-- |
| 形态 | 一个 Linux OS | 一个 Linux VM + 容器引擎 + GUI/CLI + 网络与卷的管理层 |
| 占用 | 极轻 | 更重（多一层管理与若干辅助进程） |
| 群wikkel/生态 | 自己装 dockerd / podman | 开箱可用，含 GUI 与镜像管理 |
| 适合 | 只要一个 Linux 环境 | 需要容器化的完整工作流 |

两者事实上共用同一个底层：Docker Desktop 的 WSL 2 backend 就跑在一个 WSL 发行版里（`docker-desktop` / `docker-desktop-data`）。因此**理解 WSL 的资源占用方式，就是理解 Docker Desktop 在 Windows 上如何吃你的内存**。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [命令行与 PowerShell](/docs/CS/OS/Windows/CMD.md)
- [Windows 工具链](/docs/CS/OS/Windows/Tools.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [容器技术](/docs/CS/Container/Container.md)
- [Windows](/docs/CS/OS/Windows/Windows.md)

---

## References

1. [What is Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/about)
2. [Comparing WSL 1 and WSL 2](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)
3. [Advanced settings configuration in WSL (.wslconfig)](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
4. [WSL2 Linux kernel source](https://github.com/microsoft/WSL2-Linux-Kernel)
5. [WSL repository on GitHub](https://github.com/microsoft/WSL)
