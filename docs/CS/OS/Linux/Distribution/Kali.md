## Introduction

Kali Linux 是基于 [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) 的发行版，面向信息安全任务：渗透测试、安全研究、计算机取证与逆向工程。由 OffSec（Offensive Security）资助维护，预装数百款安全工具（nmap、Metasploit、Wireshark、Burp Suite 等），支持裸机、虚拟机、WSL、树莓派与 Docker 镜像等交付形态。

> [!NOTE]
>
> 名称取自印度教女神"时母"（Kali），注意不要与印度喀拉拉邦的 Keralite 混淆 —— 这是很常见的拼写错误。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前版本 | **Kali 2026.2**（2026-06-29） |
| 内核（ISO 装机版） | **6.19** |
| 内核（滚动仓库当前） | 已到 **7.1.x**（ISO 刻意留在 6.19） |
| 桌面 | Xfce 4.20.7（默认，团队测试最充分）/ GNOME 50 / KDE Plasma 6.6 |
| 基础 | **Debian testing**（现 trixie 血统） |
| 仓库 | `kali-rolling` |

## What Rolling Release Means

**Kali 不做版本分支**，只有一条持续更新的 `kali-rolling` 仓库：

```
deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware
```

季度快照（2026.2、2026.1…）**只是镜像点，不是长期支持分支** —— 官方发布页把它们标为 "Kali Rolling release"。所以：

```shell
sudo apt update && sudo apt full-upgrade -y
```

这条命令就是"升级到最新版"的全部。**没有"某个版本的支持周期"概念**，工具与内核一直在滚动。

> ⚠️ 但存在 `kali-last-snapshot` 变体：指向季度快照点，**两次发布之间不收更新**。看到这个 suite 名就说明系统不在滚动分支上。

## Three Changes in 2026.2

### APT Sources Changed to deb822 Format

**新装系统不再有 `/etc/apt/sources.list`**，改为 `/etc/apt/sources.list.d/kali.sources`：

```
Types: deb
URIs: http://http.kali.org/kali/
Suites: kali-rolling
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/kali-archive-keyring.gpg
```

**已有系统不受影响** —— 升级上来的机器仍保留旧文件继续工作。转换方法：

```shell
sudo apt update
sudo apt modernize-sources      # 生成 .sources，旧文件存为 .list.bak
```

`modernize-sources` 会补上可推断的 `Signed-By` 值，转换后应检查再删旧文件。

### VMs No Longer Install GPU Firmware

安装器检测到运行在 VM 内时**跳过 NVIDIA / AMD / Intel GPU 固件** —— 这些过去约占 300 MB 并把 initrd 顶到 200 MB 以上。裸机安装不变。

### Service-type Tools Configure start/stop Scripts

依赖后台服务的工具现在附带 `-start` / `-stop` 命令，会报状态、打印默认凭据、有 Web UI 的直接打开。默认安装带 5 个（`gophish-start`、`faraday-start`、`starkiller-start` 等）。

## Kernel: Why the ISO Is 6.19 While the Repository Is at 7.x

这是个容易困惑的点：**Kali 团队把 7.0 内核挡在 ISO 之外，因为 7.0 破坏了 Debian 的 NVIDIA DKMS 驱动**。所以 2026.2 的 ISO 铺的是 6.19，但**滚动仓库已经提供 7.1.5**。

实践含义：

- 用 ISO 装完不动内核 → 停留在 6.19，NVIDIA 用户最稳；
- 跑 `apt full-upgrade` → 内核会跳到 7.x，**依赖 proprietary NVIDIA 驱动的话先确认能编译**。

2026.2 新增 9 款工具：`arsenal-ng`、`hydra-gtk`、`legba`、`oletools`、`penelope`、`shell-gpt`、`tailscale`、`tookie-osint`、`uro`。其中**只有 `hydra-gtk` 进了默认 metapackage**（是重新加入而非新增），其余 8 款需显式 `apt install`。

## Image Selection

| 镜像 | 大小 | 用途 |
| :-- | :-- | :-- |
| `installer-amd64.iso` | 4.5 GiB | 笔记本 / UEFI 桌面 / VM，离线安装含默认工具集 |
| `installer-netinst-amd64.iso` | 743 MiB | 网络好时选它，基础系统之后从镜像拉 |
| `live-amd64.iso` | 5.1 GiB（仅 BT） | 取证用 U 盘盘，**不碰宿主磁盘** |
| `installer-everything-amd64.iso` | 13 GiB（仅 BT） | 气隙环境，全部工具在盘上 |
| `installer-purple-amd64.iso` | 4.6 GiB | Kali Purple，防御向（SOC 工具） |
| `installer-arm64.iso` | 3.7 GiB | Apple Silicon（UTM / Parallels）、ARM64 板子 |

**取证场景选 live 版**：它整个跑在内存里，不写入宿主磁盘 —— 这是它存在的唯一理由（机制上与 tmpfs 思路一致，见 [mm](/docs/CS/OS/Linux/mm/README.md)）。

## Kernel Association from a Security Research Perspective

渗透与取证大量依赖内核机制：

| 工具 | 依赖的内核机制 |
| :-- | :-- |
| strace / ltrace | [ptrace](/docs/CS/OS/Linux/proc/ptrace.md) 的 syscall-stop |
| `/proc` 内存取证 | [procfs](/docs/CS/OS/Linux/fs/proc.md) |
| tcpdump / wireshark | [AF_PACKET](/docs/CS/OS/Linux/net/network.md) 原始套接字 + [NAPI](/docs/CS/OS/Linux/net/NAPI.md) 收包 |
| 容器逃逸 | [namespace](/docs/CS/OS/Linux/namespace.md) 与 [cgroup](/docs/CS/OS/Linux/cgroup/README.md) |
| 反调试检测 | `TracerPid`（见 [strace](/docs/CS/OS/Linux/Tools/strace.md) 一节） |
| 固件分析 | [dev 总线族](/docs/CS/OS/Linux/dev/bus.md) 的 I2C / SPI / MMIO |
| 内存编辑 | `/proc/<pid>/mem` 走 [process_vm_readv](/docs/CS/OS/Linux/proc/process.md) |

`kali-tools-top10` metapackage 只装最常用的 10 个；完整工具集用 `kali-linux-full`。

## Troubleshooting Quick Reference

```shell
# 版本与分支
grep VERSION /etc/os-release
# VERSION="2026.2"  VERSION_CODENAME="kali-rolling"
cat /etc/apt/sources.list.d/kali.sources
grep -r Suite /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null
# Suites: kali-last-snapshot  = 季度快照点（不收更新）
# Suites: kali-last-snapshot = Quarterly Snapshot Point (No Updates)

# 更新
sudo apt update && sudo apt full-upgrade -y
# 升级前务必看 REMOVED 列表；列表过长说明依赖大变动，先 cancel 稍后再试

# 内核
uname -r                            # 6.19.x+kali-amd64（ISO）或 7.1.x
apt-cache policy linux-image-amd64  # 仓库能提供什么版本
# 依赖 proprietary NVIDIA 驱动时，先确认目标内核能编译 DKMS 再升

# 工具
apt install kali-tools-top10
apt install kali-linux-full
apt-cache search <关键词>
which <tool> && <tool> --version
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Debian](/docs/CS/OS/Linux/Distribution/Debian.md)
- [Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md)
- [ptrace](/docs/CS/OS/Linux/proc/ptrace.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Kali Linux Releases History](https://www.kali.org/releases/)
2. [Kali Linux 2026.2 Release Announcement](https://www.kali.org/blog/kali-linux-2026-2-release/)
3. [Kali Linux 官网](https://www.kali.org/)
4. [How to Update Kali Linux](https://www.itechguides.com/how-to-update-kali-linux-a-step-by-step-guide-for-smooth-upgrades/)
