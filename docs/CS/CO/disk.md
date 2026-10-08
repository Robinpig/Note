## Introduction

存储设备（二级存储）是 CPU/内存之外的持久层，与[缓存层次](/docs/CS/CO/Cache.md)、[多处理器内存](/docs/CS/CO/memory.md)共同构成完整的存储金字塔。理解硬盘（HDD）与固态盘（SSD）的物理结构与时延模型，是解释[操作系统页面缓存](/docs/CS/OS/Linux/mm/PageCache.md)、文件系统布局、数据库 I/O 性能差异的硬件基础。本章从机械盘的"寻道-旋转"瓶颈讲到 SSD 的 FTL/写放大，最后落到与系统软件的接口。

## 机械硬盘（HDD）

### 物理结构

- **盘片（platter）/ 盘面**：涂磁介质的同心圆，双面可读写；
- **磁道（track）/ 柱面（cylinder）**：同一半径上的所有磁道构成柱面，是连续空间的单位；
- **扇区（sector）**：磁道上的最小读写单元，**传统 512 B**，现代高级格式化多为 **4 KiB**；
- **磁头（head）/  actuator arm**：读写臂在盘面上径向移动定位。

### 一次随机读的三段时延

1. **寻道时间（seek）**：磁头移到目标磁道，几到十几毫秒，是最大头；
2. **旋转延迟（rotational latency）**：盘片转到目标扇区，平均半圈，7200 RPM 约 4.2 ms；
3. **传输时间（transfer）**：读出扇区数据，相对可忽略。

因此 **随机小 I/O 极慢，顺序大块 I/O 快得多**——这正是日志结构、预读、批量写等优化的物理动机。接口上常见 **SATA**（消费级，~600 MB/s 上限）与 **SAS**（企业级，双端口）。

## 固态盘（SSD）

### 细胞与层级

闪存按每个**单元（cell）**存几位分代，密度↑但速度↓、寿命↓：

| 类型 | 每 cell 位数 | 特点 |
|------|-------------|------|
| SLC | 1 | 最快最耐，企业/工控 |
| MLC | 2 | 消费级高性能 |
| TLC | 3 | 主流，容量/价格平衡 |
| QLC | 4 | 大容量廉价，慢、寿命最短 |

层级组织：**cell → 串（string，32–64 cell） → 阵列 → 页（page，2–16 KiB，读写最小单元） → 块（block，64–512 page，擦除最小单元） → 平面（plane） → die**。

### FTL：闪存转换层

闪存**只能整块擦除、页须顺序写、有写入寿命（P/E cycles）**，不可能直接当随机写块设备。FTL（固件中的映射层）负责：

- **地址映射**：逻辑页号 → 物理页，对上隐藏"先擦后写"；
- **磨损均衡（wear leveling）**：均匀耗尽各块寿命；
- **垃圾回收（GC）**：搬移有效页、擦除无效块以腾出空间。

### 写放大（Write Amplification）

一次"改写某页"在物理上可能触发 **读-改-写整块 + GC 搬移**，实际写入量远大于逻辑写入量，比值即写放大。随机小写入、剩余空间不足（OP 过度配置不足）时写放大飙升，吞吐骤降、寿命缩短。

### 接口与命令

- **SATA SSD**：沿用 AHCI，受限于单队列（深度 32）；
- **NVMe SSD**：走 [PCIe](/docs/CS/CO/PCI.md)，多队列（每核独立提交/完成队列）、低延迟、高并行，是今天高性能盘的事实标准。

SSD 无机械寻道，随机 vs 顺序差距远小于 HDD，但仍受 GC、预取、内部并行度影响。OS 侧需 `TRIM/DISCARD` 通知盘哪些页已释放，让 GC 提前回收。

## HDD vs SSD 速查

| 维度 | HDD | SSD |
|------|-----|-----|
| 随机 I/O | 极慢（毫秒级寻道） | 快（微秒级） |
| 顺序吞吐 | 受转速限制 | 受 PCIe/NAND 接口限制，高得多 |
|  latency 来源 | 寻道 + 旋转 | 页读 + 写放大 + GC |
| 寿命模型 |  mechanical 损耗 | P/E 擦写次数（写放大是关键） |
| 典型接口 | SATA/SAS | SATA（AHCI）或 NVMe（PCIe） |

## 与系统软件的接口

块设备（block device）抽象把"扇区/页"隐藏在统一接口后，[操作系统](/docs/CS/OS/OS.md)用**页缓存（page cache）**缓冲文件 I/O，详见 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)；[多处理器内存](/docs/CS/CO/memory.md)的 DMA 机制让设备直接读写主存，绕过 CPU。数据库、KV 存储的 LSM-Tree / B+Tree 取舍，本质上都是在对这套时延模型做工程适配。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [缓存层次](/docs/CS/CO/Cache.md)
- [多处理器内存（UMA/NUMA）](/docs/CS/CO/memory.md)
- [PCIe 总线](/docs/CS/CO/PCI.md)
- [Linux 页面缓存](/docs/CS/OS/Linux/mm/PageCache.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [NVMe Express Base Specification](https://nvmexpress.org/specifications/)
3. [Linux Documentation - Block IO Layer](https://docs.kernel.org/block/index.html)
