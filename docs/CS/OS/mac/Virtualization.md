## Introduction

在 Mac 上跑虚拟机有三条路可走，区分它们的关键是**谁来当 hypervisor**：Apple 自己提供的框架（Hypervisor.framework / Virtualization.framework）、第三方产品（VMware Fusion、Parallels、UTM），以及容器运行时（Docker Desktop、colima、lima——它们底层其实还是前面两者之一）。

选哪条路的第一约束不是功能，而是**架构**：Apple Silicon 只能跑 ARM 客户机。这条限制与软件无关，是硬件指令集决定的，任何号称"在 M 系列上跑 x86 虚拟机"的方案都是模拟而非虚拟化，性能差一个数量级。

## Apple Native Frameworks

```shell
$ sysctl -n kern.hv_support
1        # 硬件虚拟化扩展可用
```

| 框架 | 层次 | 能力 |
| :--- | :--- | :--- |
| Hypervisor.framework（HVF） | 底层 | type-2 hypervisor 接口，直接暴露 ARM 虚拟化扩展；QEMU / UTM 建立在它之上 |
| Virtualization.framework | 高层 | macOS 12 起的 ObjC / Swift API，提供完整虚拟机抽象 |

Virtualization.framework 提供了 HVF 之上缺失的那一层：VirtIO 设备（块、网络、串口、socket）、CPU 与内存配置、以及 **macOS 客户机支持**（Apple Silicon 上受官方支持）。它还能在 Linux 客户机里启用 Rosetta，让 ARM Linux 虚拟机直接跑 x86-64 二进制。

值得注意的是：**Apple 官方框架支持 macOS 客户机，VMware Fusion 反而不支持**。想在 Apple Silicon 上开一台 macOS 虚拟机，走的是 Virtualization.framework（或基于它的 UTM 之类工具），不是商业虚拟机软件。

## Third-party Products

| 产品 | 底层 | 许可 | Apple Silicon | macOS 客户机 |
| :--- | :--- | :--- | :--- | :--- |
| VMware Fusion Pro | 自有引擎 | **免费**（个人 / 教育 / 商业，2024-11 起免 license key） | 支持 | 不支持 |
| Parallels Desktop | 自有引擎 | 付费订阅 | 支持 | 支持 |
| UTM | QEMU + Hypervisor.framework | 开源免费 | 支持 | 支持（走官方框架） |
| VirtualBox | 自有引擎 | 开源免费 | 支持有限 | 不支持 |

VMware Fusion 的授权在 2024 年变过一次：Broadcom 收购 VMware 后，自 2024-11-11 起把 Fusion Pro 与 Workstation Pro 改为**全部使用场景免费**且不再需要 license key；2025 年 3 月进一步澄清免费用户不含 Broadcom 全球支持（只剩文档、知识库与社区）。当前版本是 **26H1（2026-05 发布）**，25H2 之后要求 Mac 能支持 macOS 15 Sequoia 及以上。

> [!NOTE]
>
> 免费的是 hypervisor，不是客户机系统。Windows 授权仍需自行购买；macOS 客户机还额外受 Apple 的软件许可协议约束——协议只允许在 **Apple 硬件**上虚拟化 macOS，这也是 [Hackintosh](/docs/CS/OS/mac/Hackintosh.md) 在法律层面的边界。

## Architecture Constraints

| 客户机 | Apple Silicon Mac | Intel Mac |
| :--- | :--- | :--- |
| Windows 11 on ARM | 是（唯一路径） | 不常用 |
| Windows 10/11 x86-64 | **不可能** | 是 |
| ARM Linux（Ubuntu 等） | 是 | 否 |
| x86 Linux | **不可能**（可模拟，极慢） | 是 |
| macOS 作为客户机 | 仅官方框架支持 | 是 |

"Apple Silicon 上跑 Windows"这件事的实际含义是 Windows 11 on ARM：它自带 x86 应用翻译层，多数 Windows 软件能跑，但**需要安装驱动的硬件（加密狗、采集卡、工业设备）无法翻译**，是直接失败而不是变慢。

## Preparing Install Media

准备 macOS 安装镜像的标准流程是用 `gibMacOS` 直接从 Apple 服务器取安装器，而不是找第三方镜像：

1. 用 [gibMacOS](https://github.com/corpnewt/gibMacOS) 下载 `InstallAssistant.pkg`
2. 安装该 pkg，得到 `/Applications/Install macOS <版本>.app`
3. 用磁盘工具或 `hdiutil` 制作 dmg 映像

```shell
# dmg 转 iso（部分虚拟机软件只认 iso）
hdiutil convert <file>.dmg -format UDTO -o <file>.iso
mv <file>.iso.cdr <file>.iso
```

另一条路是制作物理安装盘，Apple 官方有[创建可引导的 macOS 安装器](https://support.apple.com/zh-cn/HT201372)的说明（`createinstallmedia`）。[Rufus](https://rufus.ie/zh/) 是常用的启动盘工具，但对 macOS 镜像的支持有限，一般还是走 `createinstallmedia`。

Linux 客户机直接取发行版的 arm64 镜像即可，例如 Ubuntu 的 daily-live `jammy-desktop-arm64.iso`。

## Fixes

**安装未签名的软件被 Gatekeeper 拦下**：虚拟机软件与 patch 工具常未公证，需要临时放开评估（见 [Security](/docs/CS/OS/mac/Security.md)）：

```shell
sudo spctl --master-disable
```

**VMware 里鼠标移动延迟高**：用 [beamoff](https://github.com/JasF/beamoff) 缓解，它关闭了 beam 同步造成的输入延迟。

**在 Intel Mac 的 VMware Workstation 上装 macOS**：VMware 官方不启用 macOS 客户机，历史上靠 Unlocker 这类补丁打开开关。这条路在 Apple Silicon 上完全不成立（架构不支持 x86 客户机），且不受官方支持。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [Hackintosh](/docs/CS/OS/mac/Hackintosh.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)

## References

1. [Virtualization — Apple Developer Documentation](https://developer.apple.com/documentation/virtualization)
2. [Hypervisor — Apple Developer Documentation](https://developer.apple.com/documentation/hypervisor)
3. [VMware Fusion & Workstation Desktop Hypervisor FAQs](https://www.vmware.com/docs/desktop-hypervisor-faqs)
4. [VMware Fusion Pro 26H1 Release Notes](https://techdocs.broadcom.com/content/dam/broadcom/techdocs/us/en/pdf/vmware/desktop-hypervisors/fusion-pro/vmware-fusion-pro-26h1.pdf)
5. [gibMacOS](https://github.com/corpnewt/gibMacOS)
6. [创建可引导的 macOS 安装器](https://support.apple.com/zh-cn/HT201372)
