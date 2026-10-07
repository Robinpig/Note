## Introduction

Raspberry Pi OS（旧名 Raspbian）是树莓派基金会的官方系统，**基于 [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) 针对树莓派硬件（ARM）定制**：预装桌面、编程环境与树莓派配置工具 `raspi-config`，内核与固件由官方仓库单独维护。

版本事实（2026-10 核实，官网 2026-06-18 发布 / 2026-09-15 更新）：

| 项 | 值 |
| :-- | :-- |
| 基础 | **Debian 13 "trixie"**（Legacy 系列为 bookworm） |
| 内核 | **6.18**（Legacy 为 6.12） |
| 位数 | **64 位与 32 位并行提供** |
| 变体 | Desktop / Full / Lite（每个位数各一份） |

## 32-bit Still Officially Supported

这一点常被误解：**32 位 Raspberry Pi OS 不是遗留，而是仍在更新的一等公民** —— 官网对它的兼容说明是"Compatible with **All** Raspberry Pi models"，包含 Zero、1A+、1B+、2B 等只有 32 位 SoC 的早期型号，内核同为 6.18。

**Legitimacy 的取舍**：

| 系列 | 基础 | 内核 | 适用 |
| :-- | :-- | :-- | :-- |
| 主线 | Debian 13 trixie | 6.18 | 新设备 |
| Legacy | Debian 12 bookworm | 6.12 | 需要更保守环境 |
| Raspberry Pi Desktop | Debian 11 bullseye | 5.10 | PC/Mac 上跑（独立分支，2022 年后基本停更） |

另外还有独立的 **Raspberry Pi Desktop**（bullseye / 5.10 / 32 位，2022-07 发布），这是给 PC 和 Mac 用的桌面环境，与树莓派主线已分叉。

## ⚠️ 32-bit and 64-bit Use Different Repositories

**这是最容易踩的坑**（来源：树莓派官方论坛确认）：

| 位数 | APT 源 | 更新速度 |
| :-- | :-- | :-- |
| **64 位** | 直接用 **Debian 官方仓库** | 跟上 debian-security 公告 |
| **32 位** | 用 **Raspbian 自己的仓库**（`raspbian.raspberrypi.com`） | **滞后若干天到数周** |

实际影响（论坛实例）：同一台机器上 32 位版的 PHP 停在 `8.4.21`，而 64 位版已经是 `8.4.23` —— 因为 32 位要等 Raspbian 重新构建，armv6/armv7 的构建常需人工介入（有些源码默认按 armv7 配置，得改才能在 armv6 上编过）。

**实践建议**：能用 64 位就用 64 位 —— 不只是性能与内存（1G 以上内存只有 64 位能用），还有**安全更新及时性**这个隐性优势。

## ⚠️ Another Pitfall: 32-bit Userland Running 64-bit Kernel

**内核 6.1 起，32 位 Raspberry Pi OS 默认启动 64 位内核**。这导致：

- `uname -r` 显示 `6.18.x-v8+`（64 位）而用户态是 32 位；
- `linux-headers-rpi`（64 位头）与 `raspberrypi-kernel-headers`（32 位头）**不匹配**；
- 编译内核模块时可能直接失败。

排查与解法：

```shell
uname -r                    # 看 v8+（64 位）还是 v7l+（32 位）
uname -m                    # armv7l = 32 位用户态
# 头文件不匹配时用 rpi-source 拉取与运行内核完全对应的头
sudo rpi-source
```

`rpi-source` 从 GitHub 拉与运行内核精确匹配的源码与头 —— 这是**版本错配的标准解法**（同样的思路适用于任何发行版：头文件版本必须与运行内核完全一致，见 [内核构建](/docs/CS/OS/Linux/build.md)）。

## Hardware Configuration Entry

与其他 Debian 系的核心差异不在包管理，而在**硬件配置**：

| 入口 | 用途 |
| :-- | :-- |
| `raspi-config` | 官方配置工具（Wi-Fi、SSH、时区、接口、Overclock 等） |
| `/boot/firmware/config.txt` | 文本配置（等价于 raspi-config 背后的东西） |
| `/boot/firmware/` | 内核与固件实际所在（**分区名是 firmware 不是 boot**） |
| `vcgencmd` | VideoCore 温度、时钟、电压读取 |
| `/proc/device-tree/` | 设备树（见 [arm.md](/docs/CS/OS/Linux/boot/arm.md)） |

> `/boot/firmware/config.txt` 的存在与 `config.txt` 里的参数（`arm_64bit=1`、`kernel=`、`dtoverlay=`）说明**树莓派内核配置大量经由设备树与 cmdline**，不像 x86 那样编进 `.config` 或走 ACPI。

`vcgencmd get_throttled` 是排查树莓派降频/过热的关键命令（返回 `throttled=0x...`，位标志含义见 `vcgencmd get_throttled` 的输出）—— 相关机制见 [PM 知识地图](/docs/CS/OS/Linux/PM/README.md) 的 cpufreq 部分。

## Installation and Headless Initialization

用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 写卡。**烧录前可在 Imager 的齿轮设置里预配 SSH、Wi-Fi、用户名与密码**，免接显示器完成初始化。

已有系统升级：

```shell
sudo apt update && sudo apt full-upgrade
```

内核升级后**必须重启**才会切到新内核。

## Interfaces with Other Subsystems

- 设备树机制与 initcall level 的关系见 [arm.md](/docs/CS/OS/Linux/boot/arm.md) 与 [boot/README](/docs/CS/OS/Linux/boot/README.md)。
- `raspi-config` 的 Overclock 实际改的是 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md) 策略与时钟。
- VideoCore 是独立于 Linux 的固件（boot/firmware），不经过内核调度。
- 与 Debian 的派生关系见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)。

## Troubleshooting Quick Reference

```shell
# 版本与位数
cat /etc/os-release
uname -r                    # 6.18.x-v8+ 是 64 位内核
uname -m                    # aarch64=64 位用户态 / armv7l=32 位用户态
dpkg --print-architecture   # armhf / arm64

# 内核头文件匹配
uname -r
ls /lib/modules/$(uname -r)/build/     # 有则头文件已就位
sudo rpi-source                        # 精确匹配版（错配时的标准解法）

# APT 源（32 位与 64 位不同！）
cat /etc/apt/sources.list
ls /etc/apt/sources.list.d/
# 64 位用 deb.debian.org → 跟上上游
# 64-bit Uses deb.debian.org -> Tracks Upstream

# 硬件配置
sudo raspi-config
cat /boot/firmware/config.txt
ls /boot/firmware/                     # kernel*.img、config.txt、overlays/
vcgencmd get_throttled                 # 0x0 = 无降频；非 0 见位标志
vcgencmd measure_temp

# 硬件检测
cat /proc/device-tree/model
dmesg | grep -iE "mmc|sd|overheat|throttl"

# 性能问题：先确认不是降频
vcgencmd get_throttled
vcgencmd get_clock arm
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Debian](/docs/CS/OS/Linux/Distribution/Debian.md)
- [Kali](/docs/CS/OS/Linux/Distribution/Kali.md)
- [arm（设备树与启动）](/docs/CS/OS/Linux/boot/arm.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/)
2. [Raspberry Pi OS September 2026 update](https://9to5linux.com/2026/09/raspberry-pi-os-dock-support-new-screenshot-tool/)
3. [Raspberry Pi 官方论坛 — 32 位仓库更新滞后讨论](https://forums.raspberrypi.com/viewtopic.php?t=399908)
4. [raspberrypi/documentation — configuration](https://www.raspberrypi.com/documentation/computers/configuration.html)
