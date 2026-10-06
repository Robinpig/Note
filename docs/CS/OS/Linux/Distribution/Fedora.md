## Introduction

Fedora 是 Red Hat 赞助、社区主导的**上游发行版**：新内核、新工具链（GCC / systemd / Wayland 等）总是先在 Fedora 落地验证，成熟后再进入 RHEL。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前版本 | **Fedora 44**（2026-04-28） |
| 内核 | **6.19** |
| 桌面 | **GNOME 50**（Wayland-only）/ KDE Plasma 6.6 |
| 支持期 | 约 **13 个月**（无 LTS） |
| 工具链 | DNF 5（Fedora 41 起默认） |

**它最重要的定位**是 RHEL 的上游：`Fedora（试验田）→ RHEL（企业稳定版）→ Rocky / Alma / CentOS Stream（免费生态）`。想在第一时间用上最新内核特性（EEVDF、sched_ext、io_uring 演进，见 [sche](/docs/CS/OS/Linux/proc/sche.md) 与 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)），Fedora 和 [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) 是最方便的两个选择。

## 支持期为何只有 13 个月

发布节奏是**每 6 个月一版，每版支持约 13 个月**（= 6 个月发布 × 2 + 4 周）。**Fedora 没有 LTS**。

这个数字的含义：**你每年要升两次系统**。对服务器不是问题（因为服务器用 [RHEL 兼容系](/docs/CS/OS/Linux/Distribution/CentOS.md)）；对桌面也合理（新特性红利值得频繁升级）。

## Fedora 44 的三个"首次"

Fedora 44 是个里程碑版本：

- **彻底移除 i686** —— 不再支持 32 位 x86（i686 是最后一批有意义的 32 位架构之一）；
- **首个 Wayland-only 桌面变体** —— GNOME 50 去掉了 X11 会话（**XWayland 仍在**，所以 X11 应用能跑，但不再有 X11 会话本身）；
- **NTSYNC 默认启用** —— 显著改善 Windows 游戏在 Proton 下的表现（减少 CPU 占用与卡顿）。

另有 **COSMIC 成为官方 spin**（System76 捐给 Fedora 的 Rust 桌面），以及 **Nix system extension 实验支持** —— 想在 Fedora 上试 Nix 而不换系统。

## 六种 Edition

| Edition | 用途 |
| :-- | :-- |
| Workstation | GNOME 桌面（默认） |
| KDE Plasma Desktop | KDE 桌面（现在是一等 Edition，非 spin） |
| Server | 服务器 |
| CoreOS | 极简、容器化、面向云基础设施 |
| Cloud & IoT | 边缘设备与 IoT |
| Everything | 单一大镜像，文档与源 |

另有社区 spin（Xfce、Budgie、Sway、Development 等）。

## Btrfs 透明压缩（Silverblue 的基础）

Fedora 44 的桌面版默认用 **Btrfs 并开启透明压缩** —— 小容量设备上能省不少空间。机制见 [btrfs](/docs/CS/OS/Linux/fs/btrfs.md)：

```shell
# 查看压缩状态（btrfs-progs ≥ 5.15）
btrfs filesystem usage /
btrfs filesystem defragment /     # 看 compression 比例
findmnt -no FSTYPE,OPTIONS /       # 挂载选项里能看到 compress
```

**Atomic 变体**（Silverblue / Kinoite）把 `/usr` 做成只读，升级走原子替换：

| 概念 | 作用 |
| :-- | :-- |
| 原子升级 | 系统更新不可中断，失败自动回滚 |
| OSTree 布局 | `/ostree` 存两个系统树，切换靠改软链接 |
| rpm-ostree | 事务化包管理 |
| `flatpak` | 桌面应用走 Flatpak，**不装进系统** |

这解决了传统发行版"更新把系统搞坏"的长期痛点。代价是**需要理解 OSTree 的两层模型**（host 与 container），且自定义系统级配置比传统方式麻烦。

## 包管理：DNF 5

```shell
dnf search <pkg>          # 搜索
dnf install <pkg>         # 安装
dnf upgrade               # 全系统升级
dnf update --refresh       # 仅刷新元数据缓存
rpm -ivh x.rpm            # 本地 rpm（不解决依赖）
rpm -qf /usr/bin/ls       # 查某文件属于哪个包
dnf repoquery --whatprovides <file>   # 同上，但走 dnf 解析
dnf history undo          # 回滚上一次事务
```

**DNF 5 自 Fedora 41 起为默认** —— 相比 DNF 4 性能提升显著（用 C++ 重写、`libdnf5` 库），多数人已察觉不到包管理器速度带来的摩擦。

> **仍需 RPM Fusion**：专有软件（NVIDIA 驱动、部分媒体编解码器）不在官方仓库，需第三方 RPM Fusion。注意它是第三方源，不是 Fedora 官方认可的。

## SELinux

Fedora **默认 SELinux enforcing**（不是 permissive）。这是与 Debian/Ubuntu 系最显著的实践差异：

```shell
getenforce                  # Enforcing / Permissive
sestatus                    # 详细状态
setenforce 0                # 临时关（不持久）
setenforce 1
# 持久：/etc/selinux/config 的 SELINUX=
```

**最常见的"Debian 迁移痛点"就是 SELinux** —— 在 Ubuntu 上能跑的服务（尤其是自建服务 + 文件标签不对）在 Fedora 上可能被拒绝。机制属于内核 LSM，见 [SELinux](/docs/CS/OS/Linux/SELinux.md)。

**Docker/podman 场景的经典坑**：`podman` 已占用 `docker` 命令，且 **SELinux 会给 bind mount 重打标签**（`:z` / `:Z` 后缀），照搬 Ubuntu 的 Docker 教程会失败。

## 排障速查

```shell
# 版本
cat /etc/fedora-release
rpm -E %fedora
uname -r

# 包
dnf info <pkg>
dnf list installed | wc -l
dnf history                     # 事务历史
dnf history undo last
rpm -qa --last | head          # 最近安装的包

# SELinux
getenforce
sestatus
ausearch -m AVC -ts recent     # 最近的拒绝记录（排 SELinux 问题）
sealert -a /var/log/audit/audit.log

# atomic 变体
rpm-ostree status
rpm-ostree upgrade
ostree admin status
flatpak list
rpm-ostree db list layers

# btrfs 压缩
findmnt -no OPTIONS /
btrfs filesystem usage /
btrfs filesystem defragment /

# 清理
dnf clean all
dnf autoremove
dnf check                       # 依赖完整性
rpm -Va                         # 校验已装文件
```

## 与其它子系统的接缝

- 内核与调度器：[sche](/docs/CS/OS/Linux/proc/sche.md)（Fedora 通常最先拿到 EEVDF / sched_ext）
- 安全策略：[SELinux](/docs/CS/OS/Linux/SELinux.md)（Fedora 默认 enforcing）
- 容器：CoreOS 与 Atomic 变体的 [cgroup](/docs/CS/OS/Linux/cgroup/README.md) 用法
- 文件系统：[btrfs](/docs/CS/OS/Linux/fs/btrfs.md)（透明压缩）

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)
- [Rocky Linux](/docs/CS/OS/Linux/Distribution/Rocky.md)
- [Arch](/docs/CS/OS/Linux/Distribution/Arch.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [btrfs](/docs/CS/OS/Linux/fs/btrfs.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Fedora Magazine](https://fedoramagazine.org/)
2. [Fedora 44 release announcement](https://fedoramagazine.org/fedora-linux-44-released/)
3. [Fedora 官网](https://fedoraproject.org/)
4. [Fedora Docs — SELinux](https://docs.fedoraproject.org/en-US/fedora/latest/system-administrators-guide/security-selinux/)
