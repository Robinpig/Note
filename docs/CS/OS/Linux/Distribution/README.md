## Introduction

发行版（Distribution）= **Linux 内核 + GNU 用户态工具 + 包管理器 + 安装器/配置工具** 的完整打包。内核本身只是操作系统核心（见 [Linux 内核笔记](/docs/CS/OS/Linux/Linux.md)），发行版负责把它变成一台"开箱即用"的系统——不同发行版共享同一个上游内核，差异主要在包管理、发布节奏、默认桌面与商业模式上。

## 谱系

```
Linux 内核（kernel.org）
 ├── Debian 系（apt / dpkg）
 │     ├── Debian —— 社区驱动，稳定优先（当前 13 trixie，内核 6.12 LTS）
 │     │     ├── Ubuntu          —— 桌面/云友好，LTS 每 2 年、5 年支持
 │     │     ├── Kali Linux      —— 安全渗透专用，滚动更新
 │     │     └── Raspberry Pi OS —— 树莓派官方系统（ARM）
 │     └── Deepin / UOS 等国产衍生
 ├── Red Hat 系（dnf / rpm）
 │     ├── Fedora —— 上游试验田，新特性先行（当前 44，内核 6.19）
 │     │     └── RHEL —— 商业订阅，企业级稳定（当前 10，内核 6.12，**x86-64-v3**）
 │     │           ├── CentOS Stream —— RHEL 的滚动预览（原 CentOS 停维护）
 │     │           ├── Rocky Linux —— bug-for-bug 重建
 │     │           ├── AlmaLinux —— ABI 兼容重建，可更早拿修复、另发 v2 变体
 │     │           └── Anolis OS —— 阿里发起，CentOS 停服的承接者（见笔记）
 │     └── openEuler —— 开放原子基金会，6 架构 + 内核增强（见笔记）
 └── 独立系
       ├── Arch Linux —— 滚动更新，KISS 哲学，pacman + AUR
       │     └── Omarchy —— DHH 的 omakase 成品桌面（Arch + Hyprland + Quickshell，见笔记）
       ├── NixOS —— 基于 Nix 函数式包管理器的声明式系统（见笔记）
       └── Alpine —— musl libc + BusyBox + OpenRC，容器基础镜像（见笔记）
```

## 当前版本速查（2026-10 核实）

版本事实变化快，涉及具体大版本号时**建议联网复核**（各发行版官网或 [DistroWatch](https://distrowatch.com/)）。

| 发行版 | 当前版本 | 内核 | 支持期 | 备注 |
| :-- | :-- | :-- | :-- | :-- |
| Debian | **13 "trixie"** | 6.12 LTS | 3 年 + 2 年 LTS | riscv64 首次官方支持 |
| Ubuntu | **26.04 LTS** | 7.0 | **5 年**（Pro 到 10 年） | ⚠️ 不是"4 年 + ESM"；最低内存 6G |
| Fedora | **44** | 6.19 | ~13 个月 | 首个 Wayland-only 桌面变体；彻底移除 i686 |
| **RHEL** | **10** | **6.12** | **10 年**（至 2035-05） | **x86-64-v3 基线**；image mode(bootc) |
| CentOS Stream | **10** | — | 5 年 | 开发分支，非生产目标 |
| Rocky Linux | **10** | — | 10 年 | 强制 x86-64-v3；不维护旧 point release |
| AlmaLinux | **10** | — | 10 年 | 另发 x86-64-v2 变体 |
| **openEuler** | **24.03 LTS SP4** | **6.6** | LTS | 6 架构含 LoongArch/RISC-V；内核增强 + AI 定位 |
| **Anolis OS** | 23.x / 8.10 / 7 | 6.6 / 4.19+5.10 | 10 年 | 向上兼容 RHEL/CentOS ABI |
| Kali | **2026.2** | 6.19（ISO） | 滚动 | 仓库已到 7.1.x；7.0 破坏 NVIDIA DKMS |
| Raspberry Pi OS | trixie 系 | 6.18 | 随 Debian | 32 位仍官方支持；32/64 位用不同 APT 仓库 |
| **Alpine** | **3.24.0** | 6.18 | ~2 年（每年 5/11 月切 stable） | **musl libc**；镜像 3.7 MiB |
| Arch 系 | 滚动 | — | 滚动 | linux / linux-lts / linux-zen |
| NixOS | **26.05** | — | **7 个月**（全发行版最短） | initrd 默认转 systemd |

## 各发行版笔记

| 发行版 | 笔记 | 定位 | 包管理 |
| :-- | :-- | :-- | :-- |
| Debian | [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) | Ubuntu/Kali 的母发行版，三分支模型 | apt / dpkg |
| Ubuntu | [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md) | 桌面与云最流行，LTS 支持 5 年 | apt / dpkg |
| Kali | [Kali](/docs/CS/OS/Linux/Distribution/Kali.md) | 渗透测试与安全研究专用，滚动更新 | apt / dpkg |
| Raspberry Pi OS | [Rasp](/docs/CS/OS/Linux/Distribution/Rasp.md) | 树莓派官方系统（Debian ARM 派生） | apt / dpkg |
| Fedora | [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md) | Red Hat 上游，新内核/新特性先行 | dnf / rpm |
| CentOS | [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md) | 原免费 RHEL 克隆 → Stream 转型 | dnf / yum / rpm |
| Rocky Linux | [Rocky](/docs/CS/OS/Linux/Distribution/Rocky.md) | RHEL 1:1 二进制兼容的免费企业版 | dnf / rpm |
| Arch | [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) | 滚动发行、最小化安装、Wiki 出名 | pacman + AUR |
| **RHEL** | [RHEL](/docs/CS/OS/Linux/Distribution/RHEL.md) | **Red Hat 链顶点**：商业订阅、10 年支持、x86-64-v3 基线 | dnf / rpm |
| **Alpine** | [Alpine](/docs/CS/OS/Linux/Distribution/Alpine.md) | **musl + BusyBox**，容器基础镜像标准 | apk |
| **openEuler** | [openEuler](/docs/CS/OS/Linux/Distribution/openEuler.md) | 开放原子基金会，6 架构 + 内核增强 + AI 定位 | dnf / rpm |
| **Anolis OS** | [Anolis](/docs/CS/OS/Linux/Distribution/Anolis.md) | 阿里发起，CentOS 停服承接者，兼容 RHEL ABI | dnf / rpm |
| Omarchy | [Omarchy](/docs/CS/OS/Linux/Distribution/Omarchy.md) | DHH 的 omakase 成品桌面，Arch + Hyprland + Quickshell | pacman + AUR |
| NixOS | [NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md) | 函数式包管理 + 声明式系统配置，可复现构建 | nix |

## 包管理对照

| | Debian 系 | Red Hat 系 | Arch | Alpine |
| :-- | :-- | :-- | :-- | :-- |
| 低层包格式 | `.deb`（dpkg） | `.rpm`（rpm） | `.pkg.tar.zst`（pacman） | `.apk` |
| 高层工具 | `apt` | `dnf`（原 yum） | `pacman` + AUR（yay/paru） | `apk` |
| 安装本地包 | `dpkg -i x.deb` | `dnf install x.rpm` | `pacman -U x.pkg.tar.zst` | `apk add --allow-untrusted x.apk` |
| 更新全系统 | `apt update && apt upgrade` | `dnf upgrade` | `pacman -Syu`（滚动） | `apk update && apk upgrade` |
| 查文件属哪个包 | `dpkg -S` | `rpm -qf` | `pacman -Qo` | `apk info -W` |
| 事务回滚 | （无内建） | `dnf history undo` | （无内建） | （无内建） |
| **init 系统** | systemd | systemd | systemd | **OpenRC** |

## 容器基础镜像怎么选

这是 Alpine 真正的战场。实测压缩体积（linux/amd64，2026-08）：

| 镜像 | 压缩后 | libc | 适用 |
| :-- | --: | :-- | :-- |
| `alpine:3.24` | **3.7 MiB** | musl | 通用，**有 musllinux wheel 的语言栈** |
| `debian:trixie-slim` | 28.4 MiB | glibc | 默认稳妥选择 |
| `static-debian13`（distroless） | ~2 MiB | glibc | **单个静态二进制** |
| `scratch` | 0 | — | 静态二进制 + 完全自定义 |

**两个反直觉的点**：

1. **Alpine 不是最小的** —— distroless（~2 MiB）比它更小。目标若是单个静态二进制，**distroless 或 scratch 优于 Alpine**（K8s 从 v1.15 起就内置 distroless）。
2. **语言栈镜像的优势会被稀释** —— `node:22-alpine` 55.1 MiB vs `node:22-slim` 76.2 MiB，**只小 25%**，而非 7 倍。

**能否换 Alpine 的实用判据**：镜像是否发布 `musllinux` wheel？PEP 656 定义了 `musllinux` 标签 —— **musl 在各发行版间 ABI 兼容，但不与 glibc 构建兼容**。只有 `manylinux`（glibc）wheel 就不行。

Alpine 镜像必须在 Dockerfile 里显式补的三项（详见 [Alpine](/docs/CS/OS/Linux/Distribution/Alpine.md)）：`tzdata`（否则日志全是 UTC）、DNS 解析验证（musl 不走 NSS）、构建依赖（`musl-dev` 等，用虚拟包 `apk del` 删掉）。

## x86-64 微架构级别：最容易被忽略的升级门槛

发行版用 `-march=x86-64-vN` 编译整个包集合，**基线一上移，一批老 CPU 就被排除** —— 而且这不会出现在发行说明里。

| 级别 | 新增指令 | 大致硬件年代 |
| :-- | :-- | :-- |
| **v1** | 2003 年基线（SSE2） | 一切 x86-64 |
| **v2** | SSE4.2、POPCNT | Nehalem（2008）+ |
| **v3** | **AVX2、BMI2、FMA** | **Haswell（2013）+ / Zen（2017）+** |
| **v4** | AVX-512 系列 | Skylake-SP / Zen 4 |

各发行版基线：

| 发行版 | 基线 |
| :-- | :-- |
| **RHEL 10 / CentOS Stream 10 / Rocky 10** | **v3** |
| **AlmaLinux 10** | v3 默认，**另发 v2 构建** |
| RHEL 9 及其重建版 | v2 |
| RHEL 8 及其重建版 | v1 |
| SUSE Linux Enterprise 16 | v2 |
| **Debian 12/13、Ubuntu 24.04/26.04、Fedora、openSUSE Tumbleweed、Alpine** | **v1** |

**"有 AVX 但没 AVX2 是 Sandy Bridge/Ivy Bridge = v2，不是"快到 v3"了"** —— 级别是全有或全无。

### 两秒自检

```bash
/lib64/ld-linux-x86-64.so.2 --help | grep -A6 "Subdirectories of glibc-hwcaps"
```

```
Subdirectories of glibc-hwcaps directories, in priority order:
  x86-64-v4
  x86-64-v3 (supported, searched)     ← 看这一行
  x86-64-v2 (supported, searched)
```

**看到 `x86-64-v3 (supported, searched)` 才能装 RHEL 10。** glibc 的动态加载器是权威裁判 —— 它选库时就要用这个信息。需要 glibc ≥ 2.33（覆盖 Debian 12/13、Ubuntu 22.04+、EL9）。

老系统或救援介质上直接读 flags：

```bash
grep -oE 'sse4_2|popcnt|avx2|bmi2|fma|avx512f' /proc/cpuinfo | sort -u
# sse4_2 + popcnt     → 至少 v2
# 再加 avx2+bmi2+fma  → v3
```

### VM 里更隐蔽

**虚拟 CPU 可以隐藏宿主支持的特性** —— 物理机支持 v3，VM 里未必。按环境排查：

| 环境 | 原因 | 修法 |
| :-- | :-- | :-- |
| 物理服务器 | CPU 不支持 v3 | 换硬件，或停在 EL9 |
| **VMware** | **EVC 屏蔽了 CPU 特性** | EVC 提到 Broadwell+ |
| **KVM/QEMU** | 老或受限的 CPU model | `host-model` / `host-passthrough` |
| VirtualBox | hypervisor bug / 版本旧 | 升到 7.2.10+ |

**没有内核模块或 dnf 包能补上老 CPU 缺的指令** —— 那些指令在硅片上不存在。

### 真实代价：CERN 的案例

CERN 把 **2200 多台加速器控制计算机**从 Red Hat 系迁到 Debian，**直接原因是 CPU 基线**（不是许可、不是口味、不是支持合同）：

- RHEL 9 全系按 **v2** 编译，RHEL 10 提到 **v3**；
- 报道称**仅 v2 基线一项就会让 47% 的嵌入式控制机退役**，v3 一步影响更多；
- 这些机器多是 **VMEbus 单板机与带自定义硬件的 PCI 卡** —— "买新服务器"意味着**重新设计板卡**。

> Debian 的 amd64 仍保持原始基线，所以老板子在那儿继续能跑。**这是个有代价的选择：Debian 在现代 CPU 上留了性能余量。** 对寿命长于硬件刷新周期的设备，这个取舍是对的；对全新云实例则是一笔基本察觉不到的税。

**升级前审计机群，而不是升级后才发现**：

```bash
for h in $(cat hosts.txt); do
  printf "%-20s " "$h"
  ssh "$h" '/lib64/ld-linux-x86-64.so.2 --help 2>/dev/null \
    | grep -q "x86-64-v3 (supported" && echo v3 || echo "< v3"'
done
```

## 内核配置取向的四种

发行版差异都在用户态，但**内核配置取向**直接决定你能用什么特性：

| 取向 | 代表 | 做法 | 后果 |
| :-- | :-- | :-- | :-- |
| **激进上游** | Fedora / Arch | 启用新上游 `CONFIG_*`，少量 backport | 最新特性，但回归风险高 |
| **LTS 保守** | Debian | 选长支持内核分支（6.12） | 稳，新特性要等回合 |
| **ABI 冻结** | RHEL 系 | 冻结的 `CONFIG_*` + **大量 out-of-tree backport** | 内核模块可跨小版本通用；驱动单独打包 |
| **内核增强** | openEuler / Anolis | 在上游基线上做自己的内核特性并反哺上游 | 新特性早于上游可用，但需区分"非上游原生" |
| **libc 受限** | Alpine | musl libc 强制，配置差异大 | 镜像极小，但 glibc 二进制不能直接跑 |

**"内核模块 ABI 稳定"是 RHEL 系最被低估的优势**：第三方 DKMS 模块（尤其 nvidia）不必每个小版本重编。同类问题在 [Kali](/docs/CS/OS/Linux/Distribution/Kali.md) 上就有体现 —— 7.0 内核破坏 DKMS，所以 ISO 刻意留在 6.19。

**"内核增强"路线的代价**是笔记写作时的歧义：openEuler 的 Cluster 调度域、内存动态复合页、混部多优先级 cgroup、潮汐调度等**都不是上游 Linux 原生能力**。引用时务必标明来源，否则会把发行版特性误当内核通用机制。

## 如何选

- **服务器/生产**：Ubuntu LTS 或 RHEL 兼容系（Rocky/Alma）——长支持周期、安全更新可预期；**要厂商支持与认证只能买 RHEL**；
- **桌面/学习**：Ubuntu（省心）或 Arch（想理解系统每一层，安装过程本身就是 [Linux 启动流程](/docs/CS/OS/Linux/boot/Start.md) 的实战课）；
- **要最新内核特性**（试 [sched_ext](/docs/CS/OS/Linux/proc/sche.md)、io_uring 新接口）：Fedora 或 Arch；
- **要内核增强特性且做信创/国产化**：openEuler（6 架构）或 Anolis OS（兼容 RHEL ABI）；
- **老硬件**：Debian / Ubuntu / Alpine（都保持 v1 基线）—— **别选 RHEL 10 / Rocky 10**；
- **可复现基础设施、免配开发环境**：NixOS——声明式配置 + 内容寻址 store；
- **容器基础镜像**：见上文「容器基础镜像怎么选」。

- **嵌入式/开发板**：Raspberry Pi OS / Buildroot / Yocto。

内核视角的关联：发行版的差异都在用户态，`uname -r` 背后的调度器、内存管理、系统调用对各发行版一视同仁（[Kernel](/docs/CS/OS/Linux/Linux.md?id=kernel)）——**但可用的内核版本决定了这些机制是否已存在**。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [CS 总目录](/docs/CS/CS.md)
