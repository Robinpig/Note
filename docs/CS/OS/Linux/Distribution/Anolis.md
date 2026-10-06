## Introduction

Anolis OS（龙蜥）是**阿里云发起、捐赠给开放原子开源基金会**的社区版 Linux，定位是"CentOS 停服后的承接者"。社区数据（官方口径）：合作伙伴 1000+、累计装机量 1000 万+、社区用户 317 万+、开发者贡献者 2.2 万+、68 个 SIG。

它最显著的特点是**向上兼容 RHEL/CentOS 的 ABI** —— CentOS 7/8 上的应用与 rpm 包几乎零修改迁移，这对被 CentOS 停服困住的数据中心是最直接的解法。

与 [openEuler](/docs/CS/OS/Linux/Distribution/openEuler.md) 并列为国内两大社区版，但路线不同：**openEuler 偏"内核增强 + AI 定位"，Anolis 偏"RHEL 兼容 + 迁移零成本"**。

## 版本线：三条并存

| 版本 | 兼容目标 | 内核 | 包管理 | 定位 |
| :-- | :-- | :-- | :-- | :-- |
| **Anolis OS 23.x** | 脱离 RHEL 生命周期 | **6.6 LTS** | dnf | 全新一代，社区主推 |
| **Anolis OS 8.10** | RHEL 8 / CentOS 8 | **ANCK 4.19 / 5.10** 双内核 | yum | 企业生产，零修改迁移 |
| **Anolis OS 7** | RHEL 7 / CentOS 7 | — | yum | 存量系统平滑迁移 |

**Anolis OS 8.10 提供 ANCK 与 RHCK 双内核** —— ANCK（Anolis Cloud Kernel）是自研增强内核，RHCK 是 Red Hat 内核的对应版本。这个双内核设计让"想用增强特性"和"想跟 RHEL 完全一致"成为可选项。

> **Anolis OS 23 已脱离 RHEL 生命周期绑定**，内核与用户态组件由龙蜥社区自主发布 LTS（承诺 **10 年支持**）。这与 Rocky/Alma 承诺 RHEL 兼容是不同的时间表策略。

### 架构覆盖

x86_64 / AArch64 / **LoongArch64** / **RISC-V** 四路。**23.4 版本实现了 RVA23U64 支持**（RISC-V 的新 profile），GCC 14.3.0 与 LLVM/Clang 20.1.8 同步向量扩展。

硬件平台覆盖 Intel、AMD、**海光**、**兆芯**、**龙芯**、飞腾 —— 国产 CPU 是它区别于普通社区版的重点。

## 内核：ANCK 与 Dragonwell

| 组件 | 说明 |
| :-- | :-- |
| **ANCK**（Anolis Cloud Kernel） | 自研增强内核，在网络吞吐、存储 IO、容器密度、热迁移效率上针对数据中心与云原生负载调优 |
| **Dragonwell** | OpenJDK 下游长期支持版，内置 JFR 增强、**ZGC 低延迟调优**、国产密码 SM4/SM2 加速引擎，通过 JCK 认证 |
| **LifseaOS** | 容器专属最小化 OS 变体 |

ANCK 的一个可观测特征：**内核 release 字符串带 `.an8` / `.an23` 后缀** —— 排查时可据此判断是否为 Anolis：

```bash
uname -r        # 形如 4.19.90-24.4.v2101.an8.x86_64
rpm -q anolis-release   # 确认是真的 Anolis（而非仅改了 os-release）
```

**这个后缀很有用** —— 跨版本调试时能准确区分"是 Anolis 的行为差异"还是"上游行为"。Anolis 社区的工程实践里甚至建议把版本标识（如 `[anolis8]` / `[anolis23]`）写进排查日志的触发词。

## 云原生工具链

| 工具 | 作用 |
| :-- | :-- |
| **SysOM** | 运维诊断 |
| **KeenTune** | 参数自调优 |
| **LifseaOS** | 容器专属最小化 OS |
| **BabaSSL** | 加密工具 |

**默认启用 cgroup v2、eBPF-based metrics 采集**，Kubernetes 1.30+ 原生适配（含 Device Plugin 扩展框架）。

> cgroup v2 的接口与容器限制见 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)；Device Plugin 与 Kubernetes 集成见 [Container](/docs/CS/Container/Container.md)。

## 迁移工具

- **`centos-to-anolis`** 迁移辅助脚本
- Anolis 迁移 SIG 负责迁移指导方案、案例与工具

**已知的一个具体坑**（社区记录）：Anolis OS 8 默认是 yum 4.x，而最小容器镜像里未装 `dnf-plugins-core`，导致 `dnf module list` 报 no metadata。解法是装 `dnf-plugins-core` 或统一用 yum。

## 国产化生态定位

Anolis OS 通过工信部《信息技术应用创新产品目录》认证，**支持与统信 UOS、麒麟 Kylin 混合部署**。

商业发行版有 14 个（统信、麒麟、华为、浪潮等均有基于 Anolis 的商业版）。

## 与其它子系统的接缝

- **cgroup v2** 是其默认启用的控制接口，见 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)；
- **eBPF 可观测**见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)；
- **Devicetree** 在 ARM / LoongArch / RISC-V 平台上的组织方式见 [arm.md](/docs/CS/OS/Linux/boot/arm.md)；
- RHEL 兼容系整体对照见 [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)。

## 排障速查

```shell
# 确认是 Anolis 而非仅改了 os-release
rpm -q anolis-release
uname -r                        # release 带 .an8 / .an23 后缀

# 版本线
cat /etc/anolis-release
uname -r

# 双内核（8.10）
rpm -qa | grep -E "kernel.*(anck|rhck)"
# 内核后缀 .an8 = ANCK 4.19/5.10

# 架构与国产 CPU
uname -m                          # x86_64 / aarch64 / loongarch64 / riscv64
lscpu | grep -E "Vendor|Model name"

# cgroup v2
stat -fc %T /sys/fs/cgroup        # 应为 cgroup2fs
cat /sys/fs/cgroup/cgroup.controllers

# 工具链
which sysom keen-tune 2>/dev/null
keen-tune --help
docker info | grep -A3 "Runtimes" # containerd / cri-o 是否并存

# 迁移
centos-to-anolis --help

# JDK
java -version                     # 可能是 Dragonwell
rpm -qa | grep -iE "dragonwell|openjdk"

# 包管理坑（Anolis 8）
yum module list                   # 8.x 默认 yum 4.x
dnf module list                   # 最小镜像需先装 dnf-plugins-core
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [openEuler（另一国产社区版）](/docs/CS/OS/Linux/Distribution/openEuler.md)
- [CentOS（它承接的生态位）](/docs/CS/OS/Linux/Distribution/CentOS.md)
- [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [OpenAnolis 官网](https://openanolis.cn/)
2. [OpenAnolis 代码库（内核/RHCK/ANCK）](https://github.com/openanolis)
3. [Anolis KDev 工程记忆机制（版本绑定实践）](https://skillhub.openanolis.cn/skill/kdev-memory)
4. [阿里龙蜥 Anolis OS 生态说明](https://ask.csdn.net/questions/9606782)
