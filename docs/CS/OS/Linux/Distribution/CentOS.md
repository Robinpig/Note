## Introduction

> [!WARNING]
>
> **CentOS Linux 已于 2021-12-31 结束维护**（CentOS 8），CentOS 7 于 2024-06-30 EOL。2020-12-08 Red Hat 宣布转型，CentOS Stream 取而代之。

CentOS 曾是 RHEL 的免费二进制克隆（下游重建），因"稳定免费的企业级系统"而广泛部署于生产环境。转型后格局变为三条路：

| 项目 | 定位 | 兼容目标 | 支持期 |
| :-- | :-- | :-- | :-- |
| **CentOS Stream** | **RHEL 上游的滚动预览** | 略**超前于** RHEL | 5 年 |
| **Rocky Linux** | bug-for-bug 重建 | 与 RHEL **完全一致** | 10 年 |
| **AlmaLinux** | ABI 兼容重建 | **二进制可运行**即可 | 10 年 |

**关键区别**：CentOS Stream 站在 RHEL **前面**（它是开发分支），Rocky/Alma 站在 RHEL **后面**（是复刻）。这个方向差异决定了各自用途：

- **要开发/测试"未来会进 RHEL 的东西"** → CentOS Stream；
- **要生产环境且要求与 RHEL 逐字节一致** → Rocky；
- **要生产环境且允许 ABI 兼容（能更早拿到修复）** → AlmaLinux。

版本事实（2026-10 核实）：

| 项目 | 当前版 | 发布 | 支持至 |
| :-- | :-- | :-- | :-- |
| CentOS Stream | **10**（对应 RHEL 10） | 2024-12-12 | **2030-05-31** |
| Rocky Linux | **10**（"Red Quartz"） | 2025-06-11 | 2035-05-31 |
| AlmaLinux | **10**（"Purple Lion"） | 2025-05-27 | 2035-05-31 |
| RHEL | **10** | 2025-05-20 | 2035-05-31 |

> **CentOS Stream 的 5 年支持期是"诚实的信号"** —— 它明确标示自己是开发分支而非冻结目标。Rocky 与 Alma 都给 10 年。

## Roadmap Differences between Rocky and Alma

这两个"接棒者"在 2023 年做出分岔：

**AlmaLinux 在 2023-07 放弃 bug-for-bug，改用 ABI 兼容**（董事会由 benny Vasquez 主持）。含义：

- 为 RHEL 编译的软件在 AlmaLinux 上**不改就能跑**，但两者**不是同一份构建产物**；
- AlmaLinux **可以先于 RHEL 合入修复**，也能继续支持 RHEL 已放弃的硬件 —— 这是买来的自由度。

**Rocky 坚持 bug-for-bug**，追求与 RHEL 逐包一致。代价是必须等 RHEL 修完才跟。

### ⚠️ CPU Baseline Differences (Pitfalls You Will Actually Hit)

**RHEL 10 把硬件基线提到 `x86-64-v3`**（需要 AVX2 等较新 CPU 指令集）。三者应对不同：

| 项目 | x86-64-v3 | 老 CPU（v2）支持 |
| :-- | :-- | :-- |
| RHEL 10 | 强制 | ✗ |
| **Rocky 10** | 强制，**已放弃 v2** | ✗ |
| **AlmaLinux 10** | 默认 v3 | ✓ **另发 x86-64-v2 变体** |

**在跑老 host CPU 的廉价 VPS 上，这一项决定系统能否安装。** 需要 v2 就选 AlmaLinux 的 v2 构建。

## Other Behavioral Differences

**Rocky 不维护旧 point release**：Rocky 10.1 在 10.2 发布后即停止安全更新。Alma 也没有同样激进的策略，但版本节奏更常规。

**SUSE 与 Oracle 的动作**（2023-07 同期）：SUSE 宣布 fork 公开可得的 RHEL 源码并投入逾 1000 万美元；Oracle（自 2006 年的 Oracle Linux）发布自有响应。三者与 CIQ 于 2023-08-10 成立 **OpenELA** —— 一个只做一件事的行业协会：发布企业 Linux 源码，让 RHEL 兼容发行版能持续构建且可自由再分发。

> **AlmaLinux 没有加入 OpenELA** —— 这直接源于它的 ABI 决策：既然不需要精确的源码馈送，就不必加入。

## Kernel Policy: ABI Freeze

RHEL 系承诺**内核 ABI 稳定**，这决定了它与 Fedora 的根本差异：

| | Fedora | RHEL 系 |
| :-- | :-- | :-- |
| 内核 | 上游原版，激进更新 | **PAUSED / 冻结的 `CONFIG_*` 组合** |
| 补丁 | 少量 out-of-tree | **大量 out-of-tree backport** |
| 驱动 | 跟随内核 | 独立打包为 RPM（`kernel-modules-*`） |
| 固件 | 随包 | 单独打包 |

**"内核 ABI 冻结"的实际含义**：第三方内核模块（DKMS）若只用导出符号与稳定结构，可以在多个 RHEL 小版本间通用而不重编。这对 nvidia 驱动尤其重要 —— 也是 [Kali](/docs/CS/OS/Linux/Distribution/Kali.md) 把 7.0 内核挡在 ISO 之外的原因（会破坏 DKMS）。

## Migration from Debian/Ubuntu

日常差异主要在包管理器。常用对照：

| 目的 | Debian 系 | RHEL 系 |
| :-- | :-- | :-- |
| 搜索 | `apt search` | `dnf search` |
| 安装 | `apt install` | `dnf install` |
| 卸载 | `apt remove` | `dnf remove` |
| 更新索引 | `apt update` | `dnf check-update` |
| 升级 | `apt upgrade` | `dnf upgrade` |
| 查文件属于哪个包 | `dpkg -S` | `rpm -qf` |
| 列出已装 | `dpkg -l` | `rpm -qa` |
| 本地包 | `dpkg -i` | `dnf install ./x.rpm` |
| 回滚 | （无内建） | `dnf history undo` |
| 防火墙 | `ufw` | `firewalld`（`firewall-cmd`） |
| 网络配置 | netplan / ifupdown | NetworkManager（`nmcli`） |

**两个最常见的实践差异**：

1. **SELinux 默认 enforcing**（见 [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md) 一节）；
2. **podman 已占用 `docker` 命令**，且 bind mount 需要 `:z` / `:Z` 重打标签。

## How to Choose

| 需求 | 选择 |
| :-- | :-- |
| 需要厂商支持合同与认证 | **买 RHEL** —— 订阅本身就是产品，重建版给不了认证与支持线 |
| 想要原 CentOS Linux 的替代 | **AlmaLinux 或 Rocky** —— 都免费且 10 年支持 |
| 开发/测试"未来进 RHEL 的东西" | **CentOS Stream**（5 年支持期就是代价） |
| 生产 + 与 RHEL 逐字节一致 | **Rocky** |
| 生产 + 想更早拿修复 / 有老硬件 | **AlmaLinux**（v2 变体） |
| cPanel / web 主机面板 | **AlmaLinux** —— cPanel 直接支持，且继承了原 CentOS 用户群 |

> 需要注意 CentOS Stream **不适合要求"经过测试的变更"的生产负载** —— 它是开发分支。

## Troubleshooting Quick Reference

```shell
# 确认是哪个 Stream / 兼容版
cat /etc/os-release
rpm -E %rhel                       # 重建版通常为空或伪装
dnf repolist

# Stream 特有
dnf update --release=10             # 跨 minor 升级
rpm -E %{version}                   # 当前版本号
# Stream 是滚动更新，不做 point release 冻结

# CPU 基线确认（Rocky/Alma 的关键差异）
lscpu | grep -o 'Flags.*' | tr ' ' '\n' | grep -c avx2   # 有=支持 v3
# 报 Illegal instruction 且 CPU 无 avx2 → 需要 AlmaLinux v2 构建

# SELinux
getenforce
sestatus
ausearch -m AVC -ts recent

# 容器（podman 占用 docker 命令）
podman ps
podman run -v /host/path:/ctr/path:z IMAGE     # :z 重打标签（SELinux 必需）
getenforce                                   # 若 Permissive 可去掉 :z

# 防火墙
firewall-cmd --list-all
firewall-cmd --add-port=8080/tcp --permanent && firewall-cmd --reload
systemctl status firewalld

# 包与回滚
dnf history
dnf history undo last
rpm -qa --last | head
```

## Interfaces with Other Subsystems

- 内核 ABI 冻结与 DKMS 依赖的关系（Kali 挡 7.0 内核的同源问题）
- SELinux 的 LSM 机制，见 [SELinux](/docs/CS/OS/Linux/SELinux.md)
- podman 的 cgroup 用法见 [cgroup](/docs/CS/OS/Linux/cgroup/README.md)

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)
- [Rocky Linux](/docs/CS/OS/Linux/Distribution/Rocky.md)
- [AlmaLinux（发行版知识地图条目）](/docs/CS/OS/Linux/Distribution/README.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [CentOS 官网](https://www.centos.org/)
2. [CentOS Stream 官网](https://www.centos.org/centos-stream/)
3. [From Red Hat to CentOS to Rocky and AlmaLinux](https://www.ssdnodes.com/learn/history-of-red-hat-centos-rocky-alma)
4. [CentOS Linux EOL 时间线（阿里云）](https://help.aliyun.com/zh/ecs/user-guide/other-operating-systems)
5. [OpenELA](https://openela.org/)
