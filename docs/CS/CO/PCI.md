## Introduction

PCI（Peripheral Component Interconnect）是 Intel 1992 年推出的本地总线标准，让 CPU 以统一方式与扩展卡（网卡、显卡、磁盘控制器）通信；2003 年推出的 **PCI Express（PCIe）** 以串行、点对点、全双工的高速互连彻底取代了并行 PCI，成为今天 GPU、NVMe SSD、100G 网卡与 CPU 互连的事实标准。

## 并行 PCI 与 PCIe 的区别

| 维度 | 传统 PCI | PCIe |
|------|---------|------|
| 拓扑 | 多设备共享并行总线 | 点对点 switch 交换（树形） |
| 信号 | 32/64 位并行，半双工 | 串行差分对，全双工，每条链路独立 |
| 带宽 | 33/66MHz × 位宽，数百 MB/s | 每代翻倍，见下表 |
| 中断 | 物理 INTA–D 共享 | MSI/MSI-X（内存写触发，可每队列一个中断） |

并行总线在高频下存在信号线串扰和时钟同步问题，串行链路靠差分信号和编码反而能跑高得多的频率。

## Lane 与版本带宽

PCIe 链路由若干条 **lane**（发送一对差分线 + 接收一对差分线）组成，常见规格 x1/x4/x8/x16。单 lane 每方向理论有效带宽：

| 版本 | 编码 | 单 lane（单向） | x16（单向） |
|------|------|----------------|-------------|
| PCIe 3.0 | 128b/130b | ≈ 0.985 GB/s | ≈ 15.75 GB/s |
| PCIe 4.0 | 128b/130b | ≈ 1.97 GB/s | ≈ 31.5 GB/s |
| PCIe 5.0 | 128b/130b | ≈ 3.94 GB/s | ≈ 63 GB/s |
| PCIe 6.0 | PAM4 + FLIT | ≈ 7.56 GB/s | ≈ 121 GB/s |

全双工意味着上下行各有一份带宽。GPU 通常用 x16，NVMe SSD 用 x4，普通网卡 x4/x8。

## 软件视角：枚举、BAR 与 DMA

- **配置空间（Configuration Space）**：每个 PCIe 功能（function）有 256B（扩展为 4KB）配置寄存器，记录厂商 ID、设备 ID、BAR、能力链。系统启动时由根复合体（Root Complex）递归枚举总线，分配地址与中断——`lspci -vv` 读的就是它。
- **BAR（Base Address Register）**：设备寄存器被映射到 CPU 物理地址空间（MMIO），驱动通过读写 BAR 指向的内存地址来操作设备，无需专门的 I/O 指令。
- **DMA（Direct Memory Access）**：设备绕过 CPU 直接读写主存；高带宽设备（NVMe/网卡）必须 DMA。DMA 的安全问题催生 **IOMMU**（Intel VT-d/AMD-Vi）：像虚拟内存给进程做地址翻译一样，给设备做 DMA 地址翻译与权限限制，也是虚拟化设备直通（VFIO passthrough）的基础。
- **MSI/MSI-X**：设备通过向特定内存地址写数据触发中断；MSI-X 支持更大的中断向量表，NVMe/多队列网卡为每个完成队列分配独立中断（与 NAPI、[多队列 IO] 配合），避免共享中断的串行化。

## 拓扑与查看

```
Root Complex（CPU 内 PCIe 控制器）
 ├─ x16 → GPU
 ├─ x4  → NVMe SSD
 └─ PCIe Switch
      ├─ x8 → 网卡 0
      └─ x8 → 网卡 1
```

```shell
lspci                 # 列出所有 PCI 设备
lspci -vv -s 01:00.0  # 查看某设备的链路速率/宽度（LnkSta: Speed 8GT/s, Width x4）
lspci -t -v           # 树形拓扑
```

注意协商速率可能低于规格：插槽物理宽度不够、转接卡降速、散热或 BIOS 设置都会让 LnkSta 显示较低代际，GPU/NVMe 跑不满时先查这里。

## 与系统其他部分的关联

- GPU 训练多卡场景：PCIe（或 NVIDIA NVLink，带宽更高）承载梯度同步的 all-reduce 流量，见并行计算相关笔记；
- 虚拟化：virtio 是半虚拟化队列模型，VFIO + IOMMU 是设备直通；SR-IOV 让一张物理网卡虚拟出多个 VF 直通给虚拟机/容器；
- CXL（Compute Express Link，基于 PCIe 5.0 物理层）允许内存池化与设备一致缓存访问，是后续内存解耦的方向。

## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [多处理器内存（UMA/NUMA）](/docs/CS/CO/memory.md)
- [Linux IO 子系统](/docs/CS/OS/Linux/IO/IO.md)

## References

1. [PCI Express Base Specification（PCI-SIG）](https://pcisig.com/specifications)
2. [Linux kernel documentation - PCI](https://docs.kernel.org/PCI/pci.html)
