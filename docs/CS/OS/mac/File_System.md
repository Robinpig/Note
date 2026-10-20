## Introduction

APFS（Apple File System）从 macOS 10.13 High Sierra 起成为默认文件系统，替换了服役近二十年的 HFS+。它带来的不只是性能改进，而是**一整套新的盘面布局观念**：2019 年的 Catalina 把系统卷拆出来做成只读，2020 年的 Big Sur 又给它加上哈希封印，于是"一块磁盘 = 一个分区 = 一个文件系统"这个 Linux 上的默认心智模型在 macOS 上不成立了。

理解现代 macOS 的盘，起点是：一个物理盘上有一个 APFS **容器**，容器里跑着**五个各司其职的卷**，系统与用户数据分住两处，靠 firmlink 缝合。

## Container and Volume Group

APFS 容器（container）管物理存储，卷（volume）是容器内的逻辑单元。卷**不预分配空间**，而是共享容器的全部剩余空间——这是它和分区（以及和 LVM 逻辑卷）最大的区别：你不需要在格式化时决定每个卷多大。

```shell
$ diskutil list
/dev/disk0 (internal, physical):
   0:      GUID_partition_scheme                        *500.3 GB   disk0
   1:             Apple_APFS_ISC Container disk1         524.3 MB   disk0s1
   2:                 Apple_APFS Container disk3         494.4 GB   disk0s2
   3:        Apple_APFS_Recovery Container disk2           5.4 GB   disk0s3

/dev/disk3 (synthesized):
   0:      APFS Container Scheme -                      +494.4 GB   disk3
                                 Physical Store disk0s2
   1:                APFS Volume Macintosh HD            11.2 GB    disk3s1
   2:              APFS Snapshot com.apple.os.update-... 11.2 GB    disk3s1s1
   3:                APFS Volume Preboot                 6.8 GB     disk3s2
   4:                APFS Volume Recovery                1.0 GB     disk3s3
   5:                APFS Volume Data                    423.5 GB   disk3s5
   6:                APFS Volume VM                      16.1 GB    disk3s6
```

`disk3` 是 synthesized（合成）的容器，`disk3s1` 到 `disk3s6` 是它里面的卷。`disk0s1` 那个 `Apple_APFS_ISC` 是 Apple Silicon 上独有的 iBoot System Container，装的是启动固件相关的内容，别和`Preboot` 搞混。

## Volume Roles

一个卷组（Volume Group）里每个卷都有明确角色，用 `diskutil apfs list` 能看到：

| 角色 | 挂载点 | 内容 | 可写 |
| :--- | :--- | :--- | :--- |
| System | `/`（实际挂载的是它的快照） | macOS 本体、系统应用 | **否**，带哈希封印 |
| Data | `/System/Volumes/Data` | 用户数据、第三方 app、`/Users`、`/Applications` 的可写部分 | 是 |
| Preboot | `/System/Volumes/Preboot` | kernelcache、Cryptexes、FileVault 解锁所需材料 | 是（启动用） |
| Recovery | 不常驻挂载 | 恢复系统 | 否 |
| VM | `/System/Volumes/VM` | swap 文件 | 是 |

System 卷只读、Data 卷可写，这个切分是 macOS 安全模型的地基（封印细节见 [Security](/docs/CS/OS/mac/Security.md)）。

## Why Split System from Data

历史上 macOS 的系统与用户数据同处一个可写卷，这带来两个长期问题：系统文件可以被任意篡改（恶意软件喜欢往 `/Library` 塞东西），以及系统更新是"就地改文件"，中途断电就半残。

拆卷之后两件事都变了：

- **系统更新变成原子操作**：更新写入新的系统卷快照，重启时切换挂载点。失败就回滚到旧快照，不会留下半新半旧的系统。
- **篡改系统需要重新封印**：APFS 对系统卷做哈希树校验，改动会破坏封印。普通 root 权限不够，必须走 Apple 的更新通道或主动降级安全策略。

代价是你会在一些地方看到"看起来在一起、实际在两个卷"的路径，这就是下面要说的 firmlink。

## firmlink

系统卷与数据卷是两个独立的卷，但用户视角里 `/Users`、`/Applications`、`/Library` 是连续的单一目录树。缝合它们的机制叫 **firmlink**，声明文件在 `/usr/share/firmlinks`：

```shell
$ cat /usr/share/firmlinks
/AppleInternal	AppleInternal
/Applications	Applications
/Library	Library
/Users	Users
/Volumes	Volumes
/System/Library/Caches	System/Library/Caches
...
```

每行是一个"系统卷路径 → 数据卷上相对路径"的映射。它和符号链接不同：firmlink 是文件系统层面实现的目录穿透，**不能通过 `..` 跨出边界**（符号链接可以），因此越不过封印的边界。

实际效果：你在 `/Applications` 里装的东西，物理上落在 Data 卷上，而系统自带的 app 留在只读的系统卷上——两者在同一个目录视图里，但只有前者可写。

## Snapshots

APFS 快照是卷级的、基于 copy-on-write 的**元数据操作**：创建瞬间完成、几乎不占空间，只有后续被改写的块才产生额外占用。

快照在 macOS 上有两个日常可见的用途：

- **系统卷快照就是你的 `/`**：启动时挂载的是 `com.apple.os.update-...` 这个快照，而不是卷本身。
- **Time Machine 的本地快照**：即便没接备份盘，APFS 也会周期性留本地快照，`tmutil` 可以看。

```shell
diskutil apfs listSnapshots /      # 列出系统卷快照
tmutil listlocalsnapshots /        # 列出 Time Machine 本地快照
tmutil snapshot                    # 手动创建一个本地快照
tmutil deletelocalsnapshots /      # 删除全部本地快照
```

第二个命令常用于"磁盘空间莫名少了几十 GB"的场景——本地快照占用会计入可用空间，删除后立即释放。

## Clones

文件级的 copy-on-write 叫克隆：`cp -c`（底层是 `clonefile(2)`）创建的副本**瞬间完成且不占额外空间**，直到某一方被修改才分裂出真实数据块。

| 机制 | 创建成本 | 改一个是否影响另一个 | 跨卷 |
| :--- | :--- | :--- | :--- |
| 普通复制 | 全量拷贝 | 否 | 可以 |
| 硬链接 | 极低 | **是**（共享 inode） | 不可以 |
| APFS clone | 极低 | **否**（写时才分裂） | 不可以 |

克隆对大文件（虚拟机磁盘、数据库备份）的意义明显，也是 Time Machine 与部分包管理器能"秒复制"的原因。

## Case Sensitivity and Other Defaults

格式化 APFS 时可以选大小写敏感，但**系统卷默认是 case-insensitive**（`diskutil apfs list` 里能看到 `Macintosh HD (Case-insensitive)`）：

```shell
+-> Volume disk3s1
    Name:                      Macintosh HD (Case-insensitive)
```

选 case-sensitive 作为系统卷会让相当数量的第三方 app 出问题（它们内部对同一文件用了不同大小写），所以除了需要跑特定 Linux/Unix 工具链的场景，别改。

其它值得一提的默认值：APFS 原生支持稀疏文件、TRIM、加密（单卷可选独立密钥，这也是 FileVault 的实现基础）、以及快照的配额预留。

## Commands

| 命令 | 用途 |
| :--- | :--- |
| `diskutil list` | 盘、容器、卷的总览 |
| `diskutil apfs list` | 容器与卷详情，含角色、封印、快照 |
| `diskutil apfs listSnapshots <disk>` | 列出卷快照 |
| `diskutil apfs addVolume / deleteVolume` | 增删卷 |
| `tmutil listlocalsnapshots /` | Time Machine 本地快照 |
| `df -h` / `du -sh` | 空间占用（注意快照与克隆会让 `du` 与 `df` 口径不一致） |

> [!NOTE]
>
> 清理空间时如果发现 `df` 说满了而 `du` 加起来差很多，差额通常在三处：本地快照、被删除但仍被打开的文件、以及共享空间的克隆文件。先 `tmutil listlocalsnapshots /`，再看 `diskutil apfs list` 的 `Capacity In Use By Volumes` 与 `Snapshots` 分项。

## HFS+ Legacy

HFS+（Mac OS Extended）是 1998 年到 2016 年的默认文件系统。macOS 仍能挂载读取 HFS+ 卷，但不能再从它启动。它留下的两个历史包袱值得知道：硬链接靠一个特殊的 `.HFS+ Private Directory Data` 目录实现（所以 HFS+ 上的硬链接行为与 POSIX 有微妙差异），以及资源分支（resource fork）那套 `._` 前缀文件——往非 Apple 文件系统拷贝时产生的 `._filename` 就是它的残留。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [Hackintosh](/docs/CS/OS/mac/Hackintosh.md)

## References

1. [Apple File System Guide](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/APFS_Guide/Introduction/Introduction.html)
2. [APFS — Apple Platform Security](https://support.apple.com/guide/security/apfs-sec4b9c47c73/web)
3. [About the read-only system volume](https://support.apple.com/en-us/102650)
4. [diskutil man page](https://ss64.com/osx/diskutil.html)
