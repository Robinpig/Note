## Introduction

XNU 的虚拟内存是 Mach 的遗产，不是 BSD 的。Linux 的 `mm` 子系统把"进程地址空间"当一等公民，Mach VM 则是把**内存对象**（memory object）当一等公民：地址空间（vm_map）只是把一段段内存对象映射进来的视图，内存对象背后由 pager 负责提供内容。这个差别决定了 macOS 上一整套与 Linux 对不上的术语和统计量。

另一个更实际的区别是**内存压力的处理顺序**：Linux 是先回收 page cache、再 swap；macOS 中间夹了一层**压缩器**（compressor），脏页先被压缩留在内存里，压到一定程度才真正换出。这也是为什么 Mac 在内存吃紧时"看起来还有内存但机器已经很卡"。

## Mach VM Building Blocks

| 概念 | 含义 | Linux 近似对应 |
| :--- | :--- | :--- |
| `vm_map` | 一个地址空间；每个 Mach task 有一个（见 [Darwin](/docs/CS/OS/mac/Darwin.md)） | `mm_struct` |
| `vm_map_entry` | 地址空间里的一段映射 | `vm_area_struct` |
| `vm_object` | 这段映射背后的数据对象 | `address_space` / inode 的 page cache |
| `vm_page` | 物理页 | `struct page` |
| pager | 为 vm_object 提供/回收内容的后端 | `address_space_operations` |

pager 有几种：vnode pager（文件后备，最常见）、device pager、swap pager，以及**用户态 pager**。后者是 Mach 微内核设计的残留——理论上可以让用户态进程充当内存管理器，虽然 macOS 上基本没人这么用。

## Compressor

内存压力上来时的处理顺序是：回收干净的页 → **压缩脏页** → 换出到 swap。压缩器把多个 16 KiB 页压进更小的空间，读回时按页解压。

```shell
$ sysctl -a | grep compressor
vm.compressor_mode: 4
vm.compressor_is_active: 1
vm.compressor_bytes_used: 13393057600           # 当前压缩区占用 ≈ 12.5 GB
vm.compressor_input_bytes: 6596158095360        # 累计送进去压缩的字节
vm.compressor_compressed_bytes: 2697626184092   # 压缩后的字节
```

从累计值能算出这台机器的长期压缩率大约是 **2.4x**（6.6 TB 输入压成 2.7 TB）。压缩器带来的直接体验是：内存不够时系统不会立刻开始换页，而是先挤压缩区，表现为"内存压力很高但 swap 没怎么涨"，同时 CPU 花在压缩/解压上的开销上升——这是 Mac 卡顿的一个常见来源，而 `vm_stat` 里看不出来。

## Swap

macOS 的 swap 是**按需增长的文件集合**，放在独立的 APFS 卷上（见 [File System](/docs/CS/OS/mac/File_System.md)）：

```shell
$ sysctl -n vm.swapusage
vm.swapusage: total = 15360.00M  used = 14333.94M  free = 1026.06M  (encrypted)

$ ls /System/Volumes/VM/
```

末尾的 `(encrypted)` 是关键：**swap 默认加密**，不需要像 Linux 那样额外配 dm-crypt 或 zswap。FileVault 开启时如此（见 [Security](/docs/CS/OS/mac/Security.md)）。

## Reading vm_stat

`vm_stat` 是 Mach VM 的统计出口，但它的单位是**页**，而 Apple Silicon 上一页是 16 KiB——这是最容易算错的地方：

```shell
$ vm_stat
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                7028.
Pages active:                            474779.
Pages inactive:                          471221.
Pages speculative:                         3096.
Pages throttled:                              0.
Pages wired down:                        191268.
Pages purgeable:                              9.
```

换算一下（× 16384）：active ≈ 7.2 GB，inactive ≈ 7.2 GB，wired ≈ 2.9 GB。

| 字段 | 含义 |
| :--- | :--- |
| active | 当前正在被使用的页 |
| inactive | 曾经用过、可回收的页（文件后备优先） |
| speculative | 预读/推测性映射的页，最先被回收 |
| wired | **不可换出**的页：内核、页表、被锁定的内存 |
| purgeable | 可随时丢弃的页（`NSPurgeableData`、磁盘缓存） |
| free | 完全空闲的页 |

`wired` 这一项在 macOS 上往往比 Linux 的 "Slab + KernelStack" 大得多，因为内核与驱动占用的内存都在这里。

## Why the Numbers Don't Add Up

同是"这台机器用了多少内存"，三个来源给三个答案，这不是 bug：

| 来源 | 口径 |
| :--- | :--- |
| 活动监视器"内存压力" | 综合指标，考虑压缩器与 swap 活跃度，不是简单的字节数 |
| 活动监视器"已使用内存" | app 内存 + wired + 压缩区 |
| `vm_stat` | 只看物理页分类，**不含压缩区** |
| `footprint` / `phys_footprint` | 单进程的"内存占用"，是进程被杀时的判定依据 |

`phys_footprint` 特别值得记住：它是 **macOS 真正的 OOM 判定标准**（`Jetsam` 依据它决定杀谁），与 RSS 不同——RSS 会把共享库、共享内存重复计入，footprint 会做去重与权重处理。查单进程真实占用：`vmmap <pid>` 或 `footprint <pid>`。

## Commands

| 命令 | 用途 |
| :--- | :--- |
| `vm_stat <间隔秒数>` | 持续输出页分类统计 |
| `memory_pressure` | 施加/观察内存压力，看系统反应 |
| `sysctl vm.compressor_bytes_used` | 压缩区占用 |
| `sysctl -n vm.swapusage` | swap 总量与是否加密 |
| `vmmap <pid>` | 单进程地址空间详情，末尾有 footprint 汇总 |
| `sysctl -n hw.pagesize` | 确认页大小（Apple Silicon 上是 16384） |

> [!NOTE]
>
> 诊断"内存不够"时，正确的顺序是先看内存压力与压缩器占用，再看 swap。只看 `vm_stat` 的 free 会得出错误结论——macOS 倾向于把空闲内存用做缓存，free 低是常态而非异常。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [File System](/docs/CS/OS/mac/File_System.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)

## References

1. [Memory Usage Performance Guidelines](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/ManagingMemory/Articles/AboutMemory.html)
2. [Mach Memory Management](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/vm/vm.html)
3. [Memory Allocation — Managing Memory](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/ManagingMemory/Articles/MemoryAlloc.html)
