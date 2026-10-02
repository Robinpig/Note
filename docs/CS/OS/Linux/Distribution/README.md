## Introduction

发行版（Distribution）= **Linux 内核 + GNU 用户态工具 + 包管理器 + 安装器/配置工具** 的完整打包。内核本身只是操作系统核心（见 [Linux 内核笔记](/docs/CS/OS/Linux/Linux.md)），发行版负责把它变成一台"开箱即用"的系统——不同发行版共享同一个上游内核，差异主要在包管理、发布节奏、默认桌面与商业模式上。

## 谱系

```
Linux 内核（kernel.org）
 ├── Debian 系（apt / dpkg）
 │     ├── Debian —— 社区驱动，稳定优先
 │     │     ├── Ubuntu          —— 桌面/云友好，LTS 每 2 年
 │     │     ├── Kali Linux      —— 安全渗透专用
 │     │     └── Raspberry Pi OS —— 树莓派官方系统（ARM）
 │     └── Deepin / UOS 等国产衍生
 ├── Red Hat 系（dnf / rpm）
 │     ├── Fedora —— 上游试验田，新特性先行
 │     │     └── RHEL —— 商业订阅，企业级稳定
 │     │           ├── CentOS Stream —— RHEL 的滚动预览（原 CentOS 停维护）
 │     │           ├── Rocky Linux —— 社区重建的 RHEL 1:1 二进制兼容克隆（见笔记）
 │     │           └── AlmaLinux —— 社区重建的 RHEL 兼容克隆
 │     └── openEuler / Anolis 等国产衍生
 └── 独立系
       ├── Arch Linux —— 滚动更新，KISS 哲学，pacman + AUR
       │     └── Omarchy —— DHH 的 omakase 成品桌面（Arch + Hyprland + Quickshell，见笔记）
       └── NixOS —— 基于 Nix 函数式包管理器的声明式系统（见笔记）
```

## 各发行版笔记

| 发行版 | 笔记 | 定位 | 包管理 |
| :-- | :-- | :-- | :-- |
| Debian | [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) | Ubuntu/Kali 的母发行版，三分支模型 | apt / dpkg |
| Ubuntu | [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md) | 桌面与云最流行，LTS 支持 5 年 | apt / dpkg |
| Kali | [Kali](/docs/CS/OS/Linux/Distribution/Kali.md) | 渗透测试与安全研究专用 | apt / dpkg |
| Raspberry Pi OS | [Rasp](/docs/CS/OS/Linux/Distribution/Rasp.md) | 树莓派官方系统（Debian ARM 派生） | apt / dpkg |
| Fedora | [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md) | Red Hat 上游，新内核/新特性先行 | dnf / rpm |
| CentOS | [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md) | 原免费 RHEL 克隆 → Stream 转型 | dnf / yum / rpm |
| Rocky Linux | [Rocky](/docs/CS/OS/Linux/Distribution/Rocky.md) | RHEL 1:1 二进制兼容的免费企业版 | dnf / rpm |
| Arch | [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) | 滚动发行、最小化安装、Wiki 出名 | pacman + AUR |
| Omarchy | [Omarchy](/docs/CS/OS/Linux/Distribution/Omarchy.md) | DHH 的 omakase 成品桌面，Arch + Hyprland + Quickshell | pacman + AUR |
| NixOS | [NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md) | 函数式包管理 + 声明式系统配置，可复现构建 | nix |

## 包管理对照

| | Debian 系 | Red Hat 系 | Arch |
| :-- | :-- | :-- | :-- |
| 低层包格式 | `.deb`（dpkg） | `.rpm`（rpm） | `.pkg.tar.zst`（pacman） |
| 高层工具 | `apt`（搜索/依赖解决/升级） | `dnf`（原 yum） | `pacman` + AUR（yay/paru） |
| 安装本地包 | `dpkg -i x.deb` | `dnf install x.rpm` | `pacman -U x.pkg.tar.zst` |
| 更新全系统 | `apt update && apt upgrade` | `dnf upgrade` | `pacman -Syu`（滚动） |

## 如何选

- **服务器/生产**：Ubuntu LTS 或 RHEL 兼容系（Rocky/Alma）——长支持周期、安全更新可预期；
- **桌面/学习**：Ubuntu（省心）或 Arch（想理解系统每一层，安装过程本身就是 [Linux 启动流程](/docs/CS/OS/Linux/boot/Start.md) 的实战课）；
- **安全研究**：Kali——预装渗透工具链；
- **跟随最新内核特性**（如试 [sched_ext](/docs/CS/OS/Linux/proc/sche.md)、io_uring 新接口）：Fedora 或 Arch 滚动源；
- **可复现 / 版本化基础设施、免配开发环境**：NixOS——声明式配置 + 内容寻址 store，构建确定性可回滚；
- **嵌入式/开发板**：Raspberry Pi OS / Buildroot / Yocto。

内核视角的关联：发行版的差异都在用户态，`uname -r` 背后的调度器、内存管理、系统调用对各发行版一视同仁（[Kernel](/docs/CS/OS/Linux/Linux.md?id=kernel)）。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [CS 总目录](/docs/CS/CS.md)
