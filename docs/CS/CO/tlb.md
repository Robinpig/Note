## Introduction

虚拟内存给了每个进程独立的地址空间，但把"虚拟地址 → 物理地址"的翻译留给硬件。如果每次访存都去查多级页表，一次翻译就是四五次内存访问——存储层次的努力会被翻译本身吃光。**TLB（Translation Lookaside Buffer，翻译后备缓冲）**是硬件里的翻译缓存：它是[缓存层次](/docs/CS/CO/Cache.md)最容易被人忘记的一层，也是[操作系统内存管理](/docs/CS/OS/Linux/mm/pagetable.md)与 CPU 硬件之间最关键的接缝。本页讲硬件视角的 TLB：它长什么样、 miss 之后发生什么、与 cache 谁先谁后、以及它如何反过来塑造了 OS 的页表设计。

## 为什么需要 TLB

多级页表把页表本身拆成页表页按需驻留，代价是翻译路径长：以 x86-64 四级页表为例，一次翻译要依次访问 PML4/PDPT/PD/PT 四张表，再加上最终的数据访问，**最坏 5 次内存往返**，L1 命中也救不回来（页表页一般不驻留 L1）。

但翻译有极强的**局部性**：程序在一小批页面上反复访问（代码段、栈、堆的工作集）。TLB 正是抓住这一点——只缓存最终翻译结果（VPN → PPN + 权限位），命中时连页表树都不碰。**多级页表能成立的前提，就是 TLB 命中率足够高**；TLB 覆盖不了的工作集（大内存随机扫描）会持续 page walk，性能断崖式下跌——这是 huge page 存在的主要理由。

## TLB 的组织

### 表项字段

一个 TLB entry 除地址对外，还必须携带：

| 字段 | 作用 |
|------|------|
| VPN / PPN | 虚拟页号 → 物理页号（含页内偏移拼接） |
| ASID / PCID | 地址空间 ID，区分不同进程的翻译，避免切换进程就全刷 |
| 权限位 | R/W/X、U/S（用户/超级用户）、NX（不可执行） |
| 脏位 / 访问位 | 页是否被写过/读过，供 OS 换出决策 |
| 全局位（G） | 内核常用页，TLB 刷新时保留 |
| 有效位 | 条目是否可用 |

权限位**在 TLB 命中时逐条检查**——页表改了但 TLB 未失效期间，硬件仍按旧条目放行，这正是"改页表必须刷 TLB"的原因（OS 侧的 `mmu_gather` 批量刷新技术见 [Linux 页表管理](/docs/CS/OS/Linux/mm/pagetable.md)）。

### 组织方式与层级

- **全相联**：任意 VPN 可放任意条目，查找时并行比较所有 tag——TLB 条目少（几十到上千），全相联可行；
- **组相联**：大容量 TLB 用，降低比较成本；
- **多级 TLB**：与 cache 一样分层。典型 x86 核：**L1 DTLB**（数据，极小，全相联，~1 周期）、**L1 ITLB**（指令）、**L2 STLB**（共享大表，4K 条目量级，数个周期），miss 再走 page walk。

### ASID / PCID

进程切换时，若 TLB 里全是上个进程的翻译，全部作废代价太大。硬件给每个条目打上 **ASID（ARM）或 PCID（x86，CR3 的低 12 位）** 标签，切换进程只需换 CR3 的 PCID 值，旧条目自然失效于新上下文而无需刷新。PCID 让"进程切换零 TLB 刷新"成为可能，代价是条目数上限被标签位约束。

### Huge Page 与 TLB 覆盖

TLB 条目数多年只增长数倍，而工作集增长快得多。TLB 覆盖（TLB reach = 条目数 × 页大小）因此成为硬指标：4 KiB 页 + 1536 条目 = 6 MiB 覆盖，数据库/大内存应用轻易击穿。解法是**大页**：

- x86-64：2 MiB（PD 级）与 1 GiB（PDPT 级）；
- ARM：64 KiB 基本块、512 MiB/1 GiB  contiguous 条目；
- RISC-V：`Svpbmt` + 超级页扩展。

1 GiB 大页把单条目覆盖抬高 26 万倍，直接决定大内存场景的实测差距。代价是内部碎片与分配难度，需要 OS/应用配合（Linux THP、`mmap` 对齐、VM 的 large page 支持）。

## TLB Miss 之后：Page Walk

TLB miss 后由硬件页表遍历器（page walker）按页表格式逐级查表，三种架构走出两条路线：

| 架构 | 遍历实现 | 特点 |
|------|----------|------|
| x86-64 | **硬件 walker**，CR3 定位根表，自动四级遍历，miss 只贡献延迟不陷 OS | 4 级页表；LA57 五级页表（2016 年起，57 位虚拟地址、128 PiB 空间） |
| ARMv8-A | **硬件 walker**，TTBR0/TTBR1 分用户/内核基址，Stage-1 翻译 | 虚拟化场景再叠 Stage-2 |
| RISC-V | **软件 trap**：TLB miss 触发异常，内核遍历 Sv39/Sv48/Sv57 页表后 `sfence.vma` 填入 | 灵活可换页表格式，代价是每次 miss 一次陷入 |

注意区分两个截然不同的事件：

- **TLB miss**：页表里有翻译，只是没缓存——硬件/软件补齐即可，应用无感；
- **Page fault**：页表项本身无效（未分配、已换出、写时复制）——必须 OS 介入，可能触发换页。

两者都表现为"访存没快速完成"，但前者是性能问题，后者是语义事件。

## TLB 与 Cache 的先后

虚拟地址到物理地址的翻译发生在缓存访问**之前还是之后**，直接决定 cache 的标记方式：

- **VIPT（虚拟索引物理标记）**：用页内偏移（虚拟地址低位）选组——偏移部分不依赖翻译，可与 TLB 查找并行；L1 几乎都是 VIPT（要求 路数×行大小 ≤ 页大小以消歧义，如 32 KiB 8 路 64 B 行正好）；
- **PIPT（物理索引物理标记）**：索引也要物理地址，必须等 TLB——L2/L3 及 TLB 本身都是 PIPT；
- **VIVT（虚拟索引虚拟标记）**：老式 ARM 用过，无需等翻译但有同义缓存（aliasing）问题，已淘汰。

推论链：**TLB 命中是 cache 命中的前置条件**。TLB miss 触发 page walk 时，load 不可能先命中 L1——流水线里表现为一类特殊长停顿。

## 虚拟化：第二阶段翻译

EPT（Intel）／NPT（AMD）／ARM Stage-2 在 TLB 之后再加一层翻译：客户机虚拟地址 →（TLB/OS 页表）→ 客户机物理地址 →（EPT/NPT）→ 主机物理地址。两层串联让每次访存两次翻译，硬件因此为 TLB 增加第二维标签，VPID 之上再叠 EPTP。代价是 miss 时两层 walk（可达 4+4 次访存），这也是半虚拟化与巨页在虚拟化环境收益更显著的原因。详见 [KVM](/docs/CS/OS/Linux/KVM.md)。

## 失效与一致性

TLB 是 OS 改页表时的"缓存一致性"问题：任何对已缓存页表项的修改，都必须让对应条目失效。x86 用 `invlpg`（单页）/`invpcid`（按标签）；ARM 用 `TLBI` 系列；RISC-V 用 `sfence.vma`（可限定地址与 ASID）。广播这些失效给所有核的成本随核数上升——多核改页表是真实的扩展性瓶颈，Linux 用 `mmu_gather` 把"摘除 → 批量失效 → 释放"拆开摊销，细节见 [Linux 页表管理](/docs/CS/OS/Linux/mm/pagetable.md)。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [缓存层次](/docs/CS/CO/Cache.md)
- [多处理器内存（UMA/NUMA）](/docs/CS/CO/memory.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)
- [Linux 页表管理](/docs/CS/OS/Linux/mm/pagetable.md)
- [操作系统内存管理](/docs/CS/OS/memory.md)
- [KVM](/docs/CS/OS/Linux/KVM.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Intel® 64 and IA-32 Architectures Software Developer Manuals — Paging](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
3. [ARM Architecture Reference Manual — MMU](https://developer.arm.com/documentation/ddi0487/latest)
4. [The RISC-V Instruction Set Manual, Volume II: Privileged Architecture](https://riscv.org/specifications/isa-manual/)
