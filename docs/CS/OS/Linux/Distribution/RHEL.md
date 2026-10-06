## Introduction

RHEL（Red Hat Enterprise Linux）是 Red Hat 系的**商业顶点**：Fedora 是它的试验田，CentOS Stream / Rocky / AlmaLinux 是它的各种"复刻或预览"形态（见 [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)）。**要厂商支持合同、认证矩阵与支持线，只能买 RHEL** —— 订阅本身就是产品，重建版给不了这些。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前版本 | **RHEL 10**（2025-05-20 发布，支持至 **2035-05-31**） |
| 内核 | **6.12**（从 RHEL 8 的 5.14 升来） |
| glibc | **2.39**（从 2.34 升来） |
| CPU 基线 | **x86-64-v3**（Haswell 2013+ / Zen+） |
| 容器镜像 | **UBI 10**（`registry.access.redhat.com/ubi10/ubi-minimal`） |
| 新增 | **image mode（bootc）**、**后量子密码**、Lightspeed CLI |

## x86-64-v3：最容易被忽略的"静默升级门槛"

RHEL 10 把硬件基线提到 **x86-64-v3**。这不是"支持更好"的意思，而是**一批老 CPU 被直接排除**。Intel 侧大致是 Haswell（2013）之后，AMD 侧是 Excavator（2015）与全部 Zen。

**要命的是它不体现在发行说明里。** 没有哪个 release headline 会写"drops Ivy Bridge"。机制在于：发行版用 `-march=x86-64-v3` 编译整个包集合，于是——

> 动态链接器本身没事，但 libc 或 bash 里的**第一条 `POPCNT`** 就触发 `SIGILL`。你得到一台**能装、但启动就死**的机器，或者更糟：**死在某个 rarely used 二进制的某个时刻**。

glibc 的动态加载器就是权威裁判 —— 它知道运行 CPU 支持哪些级别，因为选库时要用：

```bash
/lib64/ld-linux-x86-64.so.2 --help | grep -A6 "Subdirectories of glibc-hwcaps"
```

输出示例：

```
Subdirectories of glibc-hwcaps directories, in priority order:
  x86-64-v4
  x86-64-v3 (supported, searched)
  x86-64-v2 (supported, searched)
```

**看到 `x86-64-v3 (supported, searched)` 才能装 RHEL 10。** RHEL 8 时代的 glibc 太老、没这个输出，改看 CPU flags：

```bash
grep -q avx2 /proc/cpuinfo && echo "x86-64-v3 capable"
```

无 AVX2 的机器**在 RHEL 9 到 2032 年退役** —— 与你机群里其他机器的更新计划无关。

### 各发行版的基线对照

| 发行版 | 基线 |
| :-- | :-- |
| RHEL 10 / CentOS Stream 10 / Rocky 10 | **v3** |
| AlmaLinux 10 | v3 默认，**另发 v2 构建** |
| RHEL 9 及其重建版 | v2 |
| RHEL 8 及其重建版 | v1 |
| **Debian 12/13、Ubuntu 24.04/26.04、Fedora、openSUSE Tumbleweed** | **v1** |
| SUSE Linux Enterprise 16 | v2 |

**两件事值得注意**：

1. **企业 Linux 是唯一果断上移的**；其余发行版要么保持基线，要么并行提供"优化变体"。
2. **Debian/Ubuntu/Fedora 保持 v1** —— 老硬件继续能跑，代价是不用 AVX2/FMA。对寿命长于硬件刷新周期的设备（如 CERN 的加速器控制机），这个取舍是对的；对全新云实例则是一笔小税。

### 虚拟机里更隐蔽

VM 的虚拟 CPU **可以隐藏宿主支持的特性**。物理机支持 v3，VM 里未必 —— 这是"宿主明明支持却装不上"的常见原因。按环境排查：

| 环境 | 原因 | 修法 |
| :-- | :-- | :-- |
| 物理服务器 | CPU 不支持 v3 | 换硬件，或停在 EL9 |
| **VMware** | **EVC 屏蔽了 CPU 特性** | EVC 提到 Broadwell 或更高 |
| **KVM/QEMU** | 老或受限的 CPU model | `host-model`、`host-passthrough` 或 v3-capable model |
| VirtualBox | hypervisor bug / 版本旧 | 升到 7.2.10+ 并确认宿主 CPU |

**没有内核模块或 dnf 包能补上老 CPU 缺的指令** —— 那些指令在硅片上不存在。

## 升级路径：不能跳级

原地升级走 **`leapp`**，且**一次只能跨一个大版本**：8.10 → 9 → 10。**从 RHEL 8 到 10 要走两次**。

正确姿势是先做 `leapp preupgrade`，它会**在系统还在跑的时候**产出阻塞项报告（teamd 配置、cgroup v1 消费者、已移除的包），照着改完再执行 `leapp upgrade`。**很多团队干脆跳过原地升级，在新大版本上重建**。

在重建版里，**AlmaLinux 维护的 ELevate** 承担 leapp 的角色（用于跨大版本原地升级）。

## el8 → el10 的移除项

跨两个大版本，移除的东西不少：

| 移除 | 影响 |
| :-- | :-- |
| **32 位 multilib 链接** | Red Hat **完全不再构建 32 位包**（AlmaLinux 10 反其道重新加回 i686 包） |
| **modular content**（RHEL 8 的模块流） | 依赖它的部署脚本要改 |
| `iptables-nft` | 包还在（1.8.11）但已弃用，**nftables 是唯一长期目标** |
| bonding 的 nmcli 侧旧接口 | 迁移到新写法 |

> AlmaLinux 10 **有意在几处分叉**，其中一处就是重新加回 32 位 i686 包 —— 它软化了上述移除项中的两条。

## RHEL 10 的新增

| 特性 | 说明 |
| :-- | :-- |
| **image mode（bootc）** | **操作系统以 bootc 容器镜像交付和更新，彻底改变打补丁流程** |
| **后量子密码** | TLS 栈里的 PQ 密码算法 |
| **Lightspeed CLI** | 命令行 AI 助手（`c "你的问题"`）；**在基础仓库里但默认不启用**，需自行安装配置 |

image mode 是最需要理解的架构变化：**它让"更新操作系统"变成"拉一个新容器镜像并切换引导"** —— 与 [btrfs 快照](/docs/CS/OS/Linux/fs/btrfs.md) 的 OSTree 原子升级（见 [Fedora Silverblue](/docs/CS/OS/Linux/Distribution/Fedora.md)）思路一致，但机制在 bootc 层面。

## UBI 容器镜像

容器用宿主内核，**所以 UBI 的意义是 glibc 与工具链**：

```
registry.access.redhat.com/ubi10/ubi-minimal
registry.access.redhat.com/ubi10/ubi
registry.access.redhat.com/ubi10/ubi-minimal-micro
```

RHEL 10 与 UBI 10 同期发布（2025-06-01 前后）。**升级 UBI 10 时宿主内核不用动**，只有 glibc 变 —— 这对不能重启宿主内核的场景（K8s 节点）很关键。

## 与其它子系统的接缝

- **x86-64 基线与指令集**关系见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md) 的微架构级别对照表。
- **SELinux** 是 RHEL 系默认强制的机制，见 [SELinux](/docs/CS/OS/Linux/SELinux.md)。
- **cgroup v1 消费者**是 leapp 报告的常见阻塞项，v2 见 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)。
- 内核 ABI 冻结与 DKMS 的关系见 [Kali](/docs/CS/OS/Linux/Distribution/Kali.md)（同源问题）。
- **podman** 占用 `docker` 命令，bind mount 需 `:z`/`:Z`（SELinux 重打标签）。

## 排障速查

```shell
# CPU 基线自检（权威方法）
/lib64/ld-linux-x86-64.so.2 --help | grep -A6 "Subdirectories of glibc-hwcaps"
# 看到 x86-64-v3 (supported, searched) 才能装 EL10

# 老 glibc 的退化路径
grep -q avx2 /proc/cpuinfo && echo "x86-64-v3 capable"
grep -oE 'avx2|bmi2|fma|avx512f' /proc/cpuinfo | sort -u

# 版本与订阅
cat /etc/redhat-release
subscription-manager list --installed
rpm -q subscription-manager

# 仓库
dnf repolist
dnf list --showduplicates kernel        # 看可用的多个内核版本

# 升级：先 preupgrade（在系统还在跑时出报告）
dnf install -y leapp-upgrade
leapp preupgrade
less /var/log/leapp/leapp-report.txt   # 照报告逐项修
leapp upgrade
reboot
# 版本不能跳级：8.10 → 9 → 10

# 某条阻塞项是否致命（可忽略 vs 必修）
grep -E "Inhibitor|Error" /var/log/leapp/leapp-report.txt

# 内核 ABI 冻结带来的稳定性
uname -r
dkms status                          # 第三方模块跨小版本一般无需重编

# 容器
podman run -v /h:/c:z registry.access.redhat.com/ubi10/ubi-minimal
podman info --format '{{.Host.OCIRuntime.Name}}'   # 宿主 OCI runtime
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [CentOS（三方对照与 Stream）](/docs/CS/OS/Linux/Distribution/CentOS.md)
- [Rocky Linux](/docs/CS/OS/Linux/Distribution/Rocky.md)
- [Fedora（上游试验田）](/docs/CS/OS/Linux/Distribution/Fedora.md)
- [Alpine（对比 v1 基线）](/docs/CS/OS/Linux/Distribution/Alpine.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Red Hat Enterprise Linux 10 官方文档](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10)
2. [RHEL 8 vs 9 vs 10 对比](https://computingforgeeks.com/rhel-8-vs-rhel-9-vs-rhel-10/)
3. [Fix Fatal glibc Error: CPU Does Not Support x86-64-v3 on RHEL 10](http://www.golinuxcloud.com/rhel-10-cpu-does-not-support-x86-64-v3)
4. [x86-64-v3 Requirements and Your Old Server Hardware](https://www.bigiron.cc/guides/x86-64-v3-requirements-and-your-old-server-hardware)
5. [CERN Left Red Hat for Debian: The CPU Baseline Lesson](https://www.devopsness.com/blog/cern-red-hat-to-debian-control-systems)
6. [RHEL 10 & UBI 10 available](https://blog.nashcom.de/nashcomblog.nsf/dx/redhat-enterprise-linux-10-ubi-10-available.htm)
