## Introduction

Rocky Linux 是 RHEL（Red Hat Enterprise Linux）的社区重建版，目标是提供**免费、1:1 二进制兼容**的企业级发行版，接棒原 CentOS 停更后留下的生态位。

- 背景：由原 CentOS 联合创始人 Gregory Kurtzer 在 2020 年 CentOS 转向 Stream 后发起，2021 年 6 月发布首个稳定版 Rocky Linux 8.4（对应 RHEL 8.4）。
- 治理：由社区非营利组织 Rocky Enterprise Software Foundation（RESF）托管，避免路线再次被单一商业公司左右。
- 兼容方式：从 RHEL 公开源码（含 SRPM）重新编译，保证 ABI/API 与 RHEL 一致——为 RHEL 编译的软件、内核模块（如 NVIDIA 驱动、第三方 `.rpm`）可直接在 Rocky 上运行。
- 构建系统：自研 **Peridot** 自动化构建流水线（早期用 mock+koji），保证从源码到发布可复现、可审计。

定位与 [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md) Stream 不同：Stream 是"略超前于 RHEL"的滚动预览（RHEL 的上游），而 Rocky 是"与 RHEL 同步"的下游兼容克隆。同赛道的还有 AlmaLinux（由 CloudLinux 主导，2023-07 起改为 ABI 兼容路线）。

包管理与 [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)、CentOS 完全一致：`dnf`/`yum` + rpm。

## Version and Support Period

| 版本 | 代号 | 发布 | 支持至 |
| :-- | :-- | :-- | :-- |
| Rocky 8 | — | 2021-06-21 | 2029-05-31 |
| Rocky 9 | Blue Onyx | 2022-07-14 | 2032-05-31 |
| **Rocky 10** | **Red Quartz** | **2025-06-11** | **2035-05-31** |

每个主版本约 10 年支持。**CentOS Stream 10 只给 5 年**（2024-12-12 → 2030-05-31）—— 短支持期本身就是"它是开发分支"的诚实信号。

### ⚠️ Rocky 10's CPU Baseline Is x86-64-v3

RHEL 10 把硬件基线提到 `x86-64-v3`（需 AVX2 等较新指令集），**Rocky 10 跟进该基线并放弃了 x86-64-v2**。

**在老 host CPU 的廉价 VPS 上，这直接决定系统能否安装。** 需要 v2 请用 AlmaLinux 的 x86-64-v2 变体（见 [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md) 的三方对照表）。

```shell
lscpu | grep -o 'Flags.*' | tr ' ' '\n' | grep -c avx2   # 0 = 不支持 v3
```

### Rocky Does Not Maintain Old point Releases

**Rocky 10.1 在 10.2 发布后即停止安全更新** —— 需要安全补丁必须跟到最新的 point release。这与 AlmaLinux 的节奏不同，也是运维排期时要注意的点。

## Basic Operations

```shell
cat /etc/redhat-release     # Rocky Linux release 10.x (Red Quartz)
dnf update                  # 全系统升级

# 从 CentOS / RHEL 原地迁移到 Rocky
sudo migrate2rocky          # 切换仓库到 RESF，替换发行标识
```

## Use Cases

- 生产服务器、私有云、HPC 集群——需要长期稳定与 RHEL 生态兼容，又不愿购买 RHEL 订阅；
- CI/CD 中作为"免费 RHEL"构建 / 测试节点；
- 学习 [SELinux](/docs/CS/OS/Linux/SELinux.md)、cgroup 等红帽系默认启用机制的最佳平替。

## Troubleshooting Quick Reference

```shell
# 版本与仓库
cat /etc/rocky-release /etc/redhat-release
dnf repolist
dnf update --info              # 升级前看会动多少包

# CPU 基线（Rocky 10 关键）
lscpu | grep -o 'Flags.*' | tr ' ' '\n' | grep -c avx2
# 报 Illegal instruction 且无 avx2 → 硬件不支持 v3 基线

# DKMS / 第三方内核模块
dkms status
uname -r
# 内核 ABI 冻结是 Rocky 的优势；跨小版本一般不需重编

# SELinux
getenforce && sestatus
ausearch -m AVC -ts recent

# 容器
podman ps                     # podman 占用 docker 命令
podman run -v /h:/c:z IMAGE   # :z 重打标签（SELinux 必需）
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [CentOS（三方对照）](/docs/CS/OS/Linux/Distribution/CentOS.md)
- [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Rocky Linux 官网](https://rockylinux.org/)
2. [Rocky Enterprise Software Foundation](https://resf.org/)
3. [From Red Hat to CentOS to Rocky and AlmaLinux](https://www.ssdnodes.com/learn/history-of-red-hat-centos-rocky-alma)
