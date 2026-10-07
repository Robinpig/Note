## Introduction

openEuler 是**开放原子开源基金会**孵化的社区版 openEuler，由华为 2019 年捐赠，2020 年开源。它在国内信创与国产化环境中出现频率很高，特点是**内核层面做了大量增强并反哺上游**。

对读内核笔记的人来说，**openEuler 最有价值的部分不是"又一个发行版"，而是它对内核各子系统的改造清单** —— 这些改造恰好覆盖了本站关注的调度、内存、文件系统、cgroup 四个方向。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前版本 | **openEuler 24.03 LTS SP4** |
| 内核 | **6.6**（SP4 增强扩展版） |
| 治理 | 开放原子开源基金会 + 社区 |
| 架构 | x86 / ARM / **RISC-V** / **LoongArch** / PowerPC / SW-64 |
| 场景 | 服务器、云计算、AI、嵌入式 |
| 特色服务 | EulerCopilot（AI 助手）、iSulad 容器运行时 |

**架构支持是它最突出的地方** —— 六种架构，含 RISC-V 与龙芯 LoongArch。Embedded 版本的 [Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md) 也有 LLVM 构建镜像。

## Kernel Enhancement Features (The Most Valuable Part for Kernel Notes)

⚠️ 以下特性**是 openEuler 的内核增强，不是上游 Linux 6.6 原生具备的**。这正是理解它与本站各子系统关系的入口。

### Scheduler: Cluster Scheduling Domain

主流处理器硬件都已支持 **Cluster 架构**（同簇共享 L2 cache），但上游调度器仍以 core 为粒度。openEuler 的 **Cluster 调度域**让调度器感知簇结构，在这类处理器上提升调度效率。

上游视角：调度域的层级（core → SMT → LLC/NUMA）与 `sched_domain` 的组织方式，见 [sche.md](/docs/CS/OS/Linux/proc/sche.md)。

### Memory Management: Dynamic Software I/O TLB

> 该特性可根据需要**动态调整 I/O TLB 大小**，提升嵌入式/终端等场景的访存效率。

**TLB 是页表遍历的缓存** —— 见 [pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md)。TLB 条目不足会在多进程/多地址空间场景频繁触发 page table walk。动态调整大小 = 按负载平衡缓存命中率与填充成本。

对嵌入式与终端场景，小 TLB 省电但更易 miss；固定大 TLB 常驻内存又浪费。**动态调整是这两者的折中**。

### Memory Management: Dynamic Composite Pages

> 兼容 4K 页生态的同时具备大页的高性能。如匿名页、文件页可**自适应选择页面大小**，提升访存性能；ext4 等文件系统支持 **large folio**，批量化预留、映射文件块，**大 IO 写场景性能最大提升 2 倍**。

这条直接对应本站两个概念：

- **THP（透明大页）** —— 见 [Reclaim.md](/docs/CS/OS/Linux/mm/Reclaim.md) 与 [pm.md](/docs/CS/OS/Linux/mm/pm.md)；
- **large folio** —— folio 是 v6.9 起内核对 `struct page` 的重构（本站笔记已多次提到 folio 化，见 [btrfs.md](/docs/CS/OS/Linux/fs/btrfs.md) 的 memory.stat 说明）。**"批量化预留/映射文件块"正是 folio 相对 page 的核心优势**。

**"兼容 4K 页生态"是设计约束**：大页要 2 MiB 对齐，会浪费内存；自适应选择让系统在内存紧张的场景回退到 4K。

### Memory Management: KSM Fault Page Recovery

> 支持 **KSM（Kernel Shared Memory）故障页的自动恢复**，延长系统可用时间。

KSM 扫描多个进程的相同页面合并为一份以省内存（上游机制，见 [mm/README.md](/docs/CS/OS/Linux/mm/README.md) 的机制索引）。**问题在于 COW 引用被写坏后，那个页就废了** —— openEuler 增加了自动恢复。

### cgroup: Mixed Deployment with Multiple Priorities

> 允许 cgroup 支持**多个优先级**，按照 CPU 的使用比例进行资源的划分，并提供**唤醒抢占**能力，从而支持容器 QoS 细粒度隔离，降低业务间干扰，提升不同类型业务的**混部**能力。

"混部"（mixed workload）是国内云厂商的核心诉求 —— 同一批物理机上既要跑延迟敏感的在线业务，又要跑批处理/CI 任务。上游 cgroup v2 的 `cpu.weight` / `cpu.uclamp` 是单优先级的（见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)），**多优先级 + 唤醒抢占是扩展**。

### Scheduling: Tidal Scheduling (CPU / Memory)

> **CPU 潮汐**：内核提供标准化接口，使能容器 CPU 资源弹性扩缩容。
> **内存潮汐**：通过内核标准化的实现，使能业务容器数据（JAVA 堆内存）**在存储和内存间快速交换**，业务不感知。

**CPU 潮汐**让容器 CPU 配额随负载弹性伸缩（vCPU 热插拔思路延伸）。**内存潮汐**则是内存与存储间的自动换出/换入 —— 对 JVM 这类堆内存大、但有活动周期的业务很有价值，且"业务不感知"是关键（透明性）。

配套效果实测：内存潮汐使在线业务启动时间**降低 80%**；`iSulad` 容器运行时支持 CRI v1.29 / CDI / NRI 与 **cgroup v2**。

### File System and Block Layer

| 特性 | 说明 |
| :-- | :-- |
| **bfq 支持多并发** | I/O 性能倍增（`bfq` 是 Linux 的 I/O 调度器之一，见 [dev/block.md](/docs/CS/OS/Linux/dev/block.md)；注意 `bfq` 与 `kyber` 均未编入多数发行版的默认内核） |
| **I/O (buffer/direct) 并发提升** | 全闪存设备大压力场景**性能提升 20% 以上** |
| **ubi 故障注入框架** | 提升故障场景测试覆盖率 |
| **ubi 磨损均衡** | 提升闪存器件寿命 **2~10 倍** |
| **ext4 日志循环** | 提升文件系统损坏的故障定位效率 |

**ubi 磨损均衡**这条值得关注：闪存寿命由擦写次数决定，**均衡磨损意味着把写入摊到所有块** —— 这是 SSD 的关键算法，也是 openEuler 在存储子系统的实质贡献。

### Security Hardening

> 针对内存分配，**堆混淆加固**方案，防护**堆喷**（heap spraying）攻击。

堆喷是 2010 年代后被主流浏览器与内核都淘汰的攻击面（glibc 的 `ptmalloc` 曾长期受此困扰）。在发行版层面做堆混淆是对应用栈的加固。

### Others

- **oeAware**：微架构信息采集 + 性能动态优化，在 **ARM + Redis** 场景性能提升 **70%**；
- **Gazelle**：用户态 UDP 协议栈，比内核态协议栈性能提升 **50%**（DPDK 思路的落地，见 [DPDK.md](/docs/CS/OS/Linux/IO/DPDK.md)）；
- **eBPF 全栈可观测**：应用级观测（应用协议性能/网络/IO/CPU/MEM），**底噪单核 CPU < 5%**；
- **ARM64 vCPU 热插拔**：虚拟机动态扩容计算能力；
- **首次全面支持 Intel Xeon 6**（Sierra Forest E-core 与 Granite Rapids P-core）、集成 **Intel AMX FP16** 数据类型支持。

## AI for OS / OS for AI

openEuler 24.03 LTS LTS 的定位口号，反映了国内发行版的普遍走向：

| 方向 | 含义 | 落地 |
| :-- | :-- | :-- |
| **OS for AI** | 系统**支撑** AI 工作负载 | 兼容 CUDA / CANN / oneAPI / OpenVINO；支持 PyTorch / TensorFlow；兼容 Qwen 235B 部署 |
| **AI for OS** | 用 AI **改造**操作系统本身 | EulerCopilot 智能问答、**智能 shell**（自然语言输入 → 意图理解 → 自动执行）、智能诊断与调优 |

**AI for OS 的智能 shell** 值得留意 —— 它直接改写的是本站 [shell.md](/docs/CS/OS/Linux/Tools/shell.md) 描述的那层交互：命令补全与意图理解由模型接管，而不是传统的 shell 语法解析。24.03 LTS SP4 的智能诊断用"容器干扰检测 Agent + 已知问题分析 Agent"组合做全链路诊断。

## Interfaces with Other Subsystems

openEuler 的增强特性集中在本站这几个目录，引用时注意区分"上游原生"与"openEuler 增强"：

- 调度 → [proc/sche.md](/docs/CS/OS/Linux/proc/sche.md)、[proc/fair.md](/docs/CS/OS/Linux/proc/fair.md)
- 内存 → [mm/pm.md](/docs/CS/OS/Linux/mm/pm.md)、[mm/pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md)、[mm/Reclaim.md](/docs/CS/OS/Linux/mm/Reclaim.md)
- 压缩 → [mm/Compaction.md](/docs/CS/OS/Linux/mm/Compaction.md)
- cgroup → [cgroup/README.md](/docs/CS/OS/Linux/cgroup/README.md)、[cgroup/controllers.md](/docs/CS/OS/Linux/cgroup/controllers.md)
- 文件系统 → [fs/btrfs.md](/docs/CS/OS/Linux/fs/btrfs.md)
- 用户态旁路 → [IO/DPDK.md](/docs/CS/OS/Linux/IO/DPDK.md)
- 容器 → [Container](/docs/CS/Container/Container.md)

## Troubleshooting Quick Reference

```shell
# 版本与内核
cat /etc/openEuler-release
uname -r                          # 形如 6.6.0-xxx.oe2403sp4.aarch64
cat /etc/os-release

# 内核配置：确认增强特性是否编入
grep -E "CONFIG_.*(TIDF|CLUSTER|IO_TLB|MIXED_PRIORITY)" /boot/config-$(uname -r)
# openEuler 常把关键模块静态编入内核，lsmod 查不到，须查 config

# 架构
uname -m                          # aarch64 / x86_64 / loongarch64 / riscv64

# 容器运行时（iSulad，非 dockerd/containerd）
iSulad version
systemctl status isulad
# 支持 CRI v1.29 / CDI / NRI / cgroup v2

# cgroup v2 验证
stat -fc %T /sys/fs/cgroup         # cgroup2fs
cat /sys/fs/cgroup/cgroup.controllers
cat /sys/fs/cgroup/cgroup.subtree_control

# 混部多优先级
ls /sys/fs/cgroup/ | head
# 各 cgroup 的 cpu.weight / cpu.uclamp.*

# AI 相关
dnf list installed | grep -iE "eulercopilot|cann|cuda"
eulerctl --help                    # openEuler 的统一管理工具

# 源（内网建议换华为云镜像）
cat /etc/yum.repos.d/openEuler.repo
dnf update kernel
dnf info kernel                    # 看可升级版本
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Anolis OS（另一国产系）](/docs/CS/OS/Linux/Distribution/Anolis.md)
- [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)
- [mm 知识地图](/docs/CS/OS/Linux/mm/README.md)
- [proc 知识地图](/docs/CS/OS/Linux/proc/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [openEuler 官网](https://www.openeuler.org/zh/)
2. [openEuler 24.03 LTS SP4 发布公告（开放原子）](https://openatom.org/journalism/detail/KSU7JAigAByU)
3. [openEuler 24.03 LTS 官方镜像服务介绍（阿里云市场）](https://market.aliyun.com/detail/cmjj00066880.html)
4. [openEuler 24.03 vLLM 实测（官方博客）](https://www.openeuler.org/zh/blog/20260820-openEuler%2024.03-%20vLLM-Benchmark/20260820-openEuler%2024.03-%20vLLM-Benchmark.html)
5. [openEuler 安全公告 CVE-2026-31431](https://www.modb.pro/db/2051856013205778432)
