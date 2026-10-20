## Introduction

Windows 的文件系统生态有一个特点：**数量很少，延续极长**。NTFS 从 1993 年 NT 3.1 一路用到今天，中间加过元数据日志、ACL、加密、配额、重解析点、USN 日志这些增量，却从没被替换。相比之下 Linux 上有 ext2/3/4、XFS、Btrfs、F2FS 等等并行存在，各自的 mount 选项与行为都可以完全不同。

为什么 NTFS 能维持这么久？因为 Windows 上**文件系统的语义与 Windows API 的语义是相互成就的**：大小写不敏感但保留大小写、删除时的 delete-on-close 语义、文件命名流（named stream）、junction 与符号链接各自不同的历史包袱——这些都不是"某个文件系统如何分配数据块"的问题，而是"Windows 整个 API 面在这一层的投影"。换掉文件系统，等于换掉应用的运行环境。

本文按一条从内到外的线索推进：先看 **NTFS 的盘上组织**（MFT 与元数据文件），再看它在 API 层暴露的**链接与重解析点语义**，然后是 Windows 特有的 **USN 日志、机会锁与变更通知**，最后做一张 **NTFS / ReFS / FAT32 / exFAT 的对照**，划清各自的适用边界。

---

## NTFS on Disk: The MFT

NTFS 的核心是一切皆属性、一切皆表项。

### Master File Table

每个文件或目录在 **MFT（主文件表）**里都占一条固定大小的记录（经典大小 1 KB）。记录的内容是若干**属性**：文件名、时间戳、安全描述符、以及数据本体（`$DATA`）。属性分两种存在方式：

| 存在方式 | 含义 | 适用 |
| :-- | :-- | :-- |
| resident（常驻） | 属性值直接塞进 MFT 记录内 | 小文件内容、小目录索引 |
| non-resident（非常驻） | 属性值放在盘上的其它集群，MFT 记下 extent 列表 | 大文件 |

这条设计有一个直接后果：**足够小的文件不占用额外的磁盘块**，读写它只需要一次 MFT 访问。这解释了为什么 NTFS 在海量小文件场景下有时会意外地快，也解释了为什么 MFT 碎片会让这个优势消失。

### Metadata Files

NTFS 保留了一批不可见的系统文件，名字都以 `$` 开头：

| 元文件 | 作用 |
| :-- | :-- |
| `$MFT` | MFT 本身 |
| `$MFTMirr` | MFT 前几条记录的镜像，用于灾备恢复 |
| `$LogFile` | 日志文件，保证元数据事务的一致性（注意：这只管元数据，不管用户数据） |
| `$Volume` | 卷名与卷信息 |
| `$AttrDef` | 属性定义表 |
| `$.`（根目录） | 根目录索引 |
| `$Bitmap` | 位图，跟踪每个集群的分配状态 |
| `$BadClus` | 坏集群记录 |
| `$Secure` | 全卷统一存放的安全描述符表 |
| `$Upcase` | 大写转换表（这也是 NTFS 大小写不敏感但保留大小写的实现基础） |
| `$Extend` | 后续扩展项的容器：$ObjId、$Quota、$Reparse、$UsnJrnl 等 |

> [!WARNING]
>
> **日志只保护元数据**
>
> NTFS 的 `$LogFile` 保证的是"文件系统结构本身不会因断电而损坏"，**不保证用户写入的数据落盘**。因此"NTFS 是日志文件系统"不等于"写完 `WriteFile` 数据就安全了"——真要保证持久化，得用 `FlushFileBuffers` 或写通 flag，参见 [Windows I/O](/docs/CS/OS/Windows/IO.md)。

### Other NTFS Facilities

| 功能 | 说明 |
| :-- | :-- |
| 稀疏文件（sparse file） | 大段的零不占物理空间，写的时候才真正分配集群。虚拟磁盘、数据库镜像爱用 |
| 文件压缩 | per-file 的透明压缩，基于 NTFS 压缩算法（不可与加密并存） |
| EFS（加密文件系统） | per-file 的对称加密，密钥用用户证书包起来。与 BitLocker 的"全卷加密"是两回事 |
| 磁盘配额 | per-volume + per-user 的空间配额 |
| 命名流（alternate data stream） | 一个文件可以有多个 `$DATA` 属性，Zone.Identifier 就走这条语义 |
| 硬链接 | 同一条 MFT 记录的多个文件名；删掉任一个名字不影响其它名字 |
| 事务 TxF | 已不推荐使用：TxF 在现代 Windows 上处于被弃用状态，新代码不要用 |

---

## Links, Junctions and Reparse Points

Windows 上的"链接"有四种，名字相近但语义完全不同，这是移植 Unix 软件时最容易踩的一块：

| 类型 | 创建方式 | 能否跨卷 | 目标 | 适用 |
| :-- | :-- | :-- | :-- | :-- |
| 硬链接 | `mklink /H`、`CreateHardLink` | **不能** | 只限同一卷上的文件 | 同一文件的多个名字，删除任一不影响其它 |
| 符号链接 | `mklink`、`CreateSymbolicLink` | 可以 | 文件或目录 | 需要管理员/开发者模式（历史限制，现代 Windows 放宽） |
| 目录交接点 junction | `mklink /J` | 可以 | 只限目录 | 老机制，兼容旧版 Windows |
| 重解析点 reparse point | 驱动自定义 | 取决于实现 | 任意 | OneDrive 占位文件、挂载点、去重文件的底层机制 |

**重解析点（reparse point）是这四种里唯一的机制而非工具**：文件系统看到一个打了 reparse tag 的对象，就把处理权交还给安装了对应该 tag 的过滤驱动。理解它等于理解了：为什么 OneDrive 的"仅在线文件"看起来是文件但点开才下载；为什么挂载一个卷到空目录（junction 之外的 mount point）是可行的；以及为什么 `dir` 里有时会看到 `<SYMLINKD>`、`<JUNCTION>` 这些标记。

---

## Notifications: USN Journal, Change Notifications and Oplocks

Windows 给"我怎么知道文件变了"这个问题准备了三种不同粒度的答案，必须分清：

| 机制 | 粒度 | 代价 | 适用 |
| :-- | :-- | :-- | :-- |
| **USN journal** | 卷级别的持久变更日志，每条记录说明哪个文件的哪个 reason 变了 | 极低 | 备份软件、索引器、杀毒全盘扫描的增量依据 |
| **变更通知**（`ReadDirectoryChangesW`、`FindFirstChangeNotification`） | 目录级别，告诉"有变化"而不告诉"变成什么" | 低 | 文件监视、热重载 |
| **机会锁 oplock** | 缓存一致性协作机制 | 由内核管理 | SMB 客户端缓存、本地延迟写入的依据 |

三者常常被混用导致 bug：`ReadDirectoryChangesW` 丢事件时会一整块返回溢出，此时必须全量重扫而不能增量；而**正确的高性能做法是读 USN journal**。

至于 oplock，它是 Windows 对 lease 的叫法：多个客户端打开同一个网络文件时，谁可以缓存、谁必须在租约被打破之前回写，全靠它。这也解释了"网络驱动器上的文件偶尔看不到别人的改动"——那是缓存一致性的既定语义，而不一定是 bug。

---

## Filesystem Comparison

Windows 这边值得一提的四个文件系统：

| 文件系统 | 主要场景 | 关键限制 / 特点 |
| :-- | :-- | :-- |
| **NTFS** | 通用、系统卷、可移动（部分场景） | 单文件/卷上限 256 TB；文件名最长 255 个 Unicode 字符；路径最长 32 KB；支持 ACL、EFS、压缩、配额，以及仅保护元数据的事务式日志 |
| **ReFS** | 服务器数据卷、Storage Spaces、备份目标、Hyper-V 存储、Dev Drive | 单文件/卷上限 35 PB； integrity streams、block clone、sparse VDL；**不支持**事务、对象 ID、ODX、短名、磁盘配额、可移动介质、可引导、卷收缩 |
| **FAT32** | 兼容性、U 盘（旧） | 单文件 4 GB 上限，无 ACL |
| **exFAT** | 闪存媒体、跨平台大文件 | 无 journal、无 ACL，单文件理论上限极大 |

### NTFS vs ReFS: The Official Boundary

微软自己的对比表划出的边界很清楚。两者共有 BitLocker 加密、重复数据删除、扩展属性、CSV 支持、junction/软链接、硬链接、故障转移群集、ACL、USN journal、变更通知、挂载点、重解析点、卷快照、文件 ID、机会锁、稀疏文件、命名流、Trim/Unmap、页面文件支持。差别在两头：

**只有 ReFS 有的**：块克隆（block clone）、稀疏 VDL、镜像加速奇偶（限 Storage Spaces Direct）、文件级快照（Windows Server 2022 起）。

**ReFS 不支持的**：事务（TxF）、对象 ID、ODX、短名、磁盘配额、可移动介质、可引导、**卷收缩**。

其中"不可引导"这一条最要紧：**Windows 系统卷目前仍须是 NTFS**。这注定了 ReFS 作为"第一文件系统"的门还关着，它暂时只能是数据卷的选择。

> [!NOTE]
>
> **ReFS 的完整性 = 检测 + 修复需要另一份拷贝**
>
> ReFS 始终对元数据做校验和，但对普通文件数据的校验要靠可选的 integrity streams。更重要的是：**检测到损坏不等于能修复**。修复需要另一个有效副本，而那个副本通常来自 Storage Spaces 的镜像或奇偶。单盘 ReFS 只能"检测到并把坏数据从命名空间里摘掉"，不能凭空把它恢复回来。
>
> 换句话说，ReFS 与你已有的冗余层是组合关系，不是替代关系——它既不是备份，也不能在单盘上自愈。

### Dev Drive

**Dev Drive** 是微软近年给开发 workload 开的一个专用位置：一个用 **ReFS** 格式化的卷，**最小 50 GB**，用来放源码仓库、包缓存与构建产物（而不是用来装 IDE 与 SDK）。

它带来两收益：

1. **块克隆**。从 Windows 11 24H2 / Windows Server 2025 起，Dev Drive 上的文件复制可以走 ReFS 块克隆——`node_modules`、NuGet 缓存这类"大量被引用的相同数据"的复制变成元数据操作，而不是成吨的读写。
2. **Defender 性能模式**。格式化时 Dev Drive 会被打上 **trusted** 标记，这个标记就是 Microsoft Defender 切换到 **performance mode**（异步扫描）的信号：不再对每次文件写入做同步扫描，而是异步跟进。它是"把目录加进排除列表"的安全替代方案——防病毒过滤仍然挂着。若卷变成 untrusted，Defender 会退回同步的实时保护模式。

> [!WARNING]
>
> **Dev Drive 的三条硬限制**
>
> - **不能把已有卷转成 Dev Drive**：这个标记只在初始格式化时打下，转换等于重格；
> - **`C:` 不能做 Dev Drive**，开发工具与 SDK 仍应留在系统盘；
> - 若 VHD 被复制到另一台机器，trust 状态与过滤策略**不会跟着走**，需要 `fsutil devdrv trust <盘符>:` 重新指定。
>
> 另外 [WSL](/docs/CS/OS/Windows/WSL.md) 访问 Dev Drive 上的 Windows 路径不会带来预期加速——因为性能关键在 Linux 那一侧的文件系统；而且 ReFS 卷不支持 WSL 用于保留 Linux 权限的 `metadata` 挂载选项。

创建方式除了设置里的向导（存储 → 磁盘和卷 → 创建开发驱动器），命令行更直接：

```powershell
Format-Volume -DriveLetter D -DevDrive
```

这不是把 NTFS 换掉，而是给"开发这台机器上有一类 workload 明显不同于一般文档处理"这件事一个专用位置。

---

## Network File Systems: The Redirector

Windows 上访问 UNC 路径（`\\server\share`）不是某个文件系统的事，而是**多个 UNC provider（MUP）+ 网络重定向器**的工作：MUP 挑出能处理这个路径的 provider（通常是 SMB 重定向器），之后由它与远端协商 SMB 版本、oplock/lease、签名与加密。

因此 Windows 上"网络驱动器很慢"的排查要从两头看：本地的文件缓存/oplock 语义、以及 SMB 协商出来的版本与包大小——它们都不在文件系统层，而是重定向器层的议题。

---

## Links

- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 安全模型](/docs/CS/OS/Windows/Security.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [文件系统](/docs/CS/OS/file.md)

---

## References

1. [NTFS overview](https://learn.microsoft.com/en-us/windows-server/storage/file-server/ntfs-overview)
2. [Resilient File System (ReFS) overview](https://learn.microsoft.com/en-us/windows-server/storage/refs/refs-overview)
3. [Hard Links and Junctions](https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions)
4. [Reparse Points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)
5. [File Encryption](https://learn.microsoft.com/en-us/windows/win32/fileio/file-encryption)
6. [Dev Drive](https://learn.microsoft.com/en-us/windows/dev-drive/)
