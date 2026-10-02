## Introduction

Rocky Linux 是 RHEL（Red Hat Enterprise Linux）的社区重建版，目标是提供**免费、1:1 二进制兼容**的企业级发行版，接棒原 CentOS 停更后留下的生态位。

- 背景：由原 CentOS 联合创始人 Gregory Kurtzer 在 2020 年 CentOS 转向 Stream 后发起，2021 年 6 月发布首个稳定版 Rocky Linux 8.4（对应 RHEL 8.4）。
- 治理：由社区非营利组织 Rocky Enterprise Software Foundation（RESF）托管，避免路线再次被单一商业公司左右。
- 兼容方式：从 RHEL 公开源码（含 SRPM）重新编译，保证 ABI/API 与 RHEL 一致——为 RHEL 编译的软件、内核模块（如 NVIDIA 驱动、第三方 `.rpm`）可直接在 Rocky 上运行。
- 构建系统：自研 **Peridot** 自动化构建流水线（早期用 mock+koji），保证从源码到发布可复现、可审计。

定位与 [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md) Stream 不同：Stream 是"略超前于 RHEL"的滚动预览（RHEL 的上游），而 Rocky 是"与 RHEL 同步"的下游兼容克隆。同赛道的还有 AlmaLinux（由 CloudLinux 主导）。

包管理与 [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)、CentOS 完全一致：`dnf`/`yum` + rpm。

## 版本与迁移

```shell
cat /etc/redhat-release     # Rocky Linux release 9.x (Blue Onyx)
dnf update                  # 全系统升级（与 RHEL 节奏同步）

# 从 CentOS / RHEL 原地迁移到 Rocky
sudo migrate2rocky          # 切换仓库到 RESF，替换发行标识
```

- 主版本与 RHEL 主线对齐：Rocky 8（基于 RHEL 8）、Rocky 9（2022，代号 Blue Onyx）、Rocky 10（2025，基于 RHEL 10）。
- 每个主版本约 10 年支持（约 5 年完整维护 + 5 年维护更新），安全更新可预期。

## 适用场景

- 生产服务器、私有云、HPC 集群——需要长期稳定与 RHEL 生态兼容，又不愿购买 RHEL 订阅；
- CI/CD 中作为"免费 RHEL"构建 / 测试节点；
- 学习 [SELinux](/docs/CS/OS/Linux/SELinux.md)、cgroup 等红帽系默认启用机制的最佳平替。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Rocky Linux 官网](https://rockylinux.org/)
2. [Rocky Enterprise Software Foundation](https://resf.org/)
