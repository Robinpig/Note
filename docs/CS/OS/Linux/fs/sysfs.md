## Introduction

**sysfs** 是 Linux 的一个**基于内存的虚拟文件系统**，通常挂载在 `/sys`，自 2.6 引入。它把内核里**设备模型（device model）**的层级关系——总线、设备、驱动、类（class）——以及大量子系统的运行时参数，以目录/文件的形式导出到用户空间。用户态程序通过读这些文件获取设备信息与状态，通过写（权限允许时）调整内核参数，也可以用 `poll`/`inotify` 感知变化。

sysfs 与 [proc](/docs/CS/OS/Linux/fs/proc.md) 的区别：proc 最初用于进程信息，后来也塞进各种内核调优项（`/proc/sys`）；sysfs 则是为**统一设备模型**专门设计，结构更规整、与内核对象生命周期严格对应。通用 VFS 抽象见 [fs](/docs/CS/OS/Linux/fs/fs.md)，sysfs 之上由 [udev](/docs/CS/OS/Linux/dev/udev.md) 自动创建 `/dev` 节点。

## Layout

`/sys` 下的主要子目录：

| 路径 | 内容 |
| --- | --- |
| `/sys/devices` | 设备树的**真身**，按内核发现设备的拓扑（平台总线、PCI、USB 等）组织，所有其他视图多是它的符号链接 |
| `/sys/bus` | 按总线类型（pci、usb、platform、net…）分类，下有 `devices/` 与 `drivers/` |
| `/sys/class` | 按**功能类**组织：net、block、tty、input、power_supply、gpio… |
| `/sys/block` | 块设备符号链接（历史保留，新结构在 class/block） |
| `/sys/module` | 每个已装载[内核模块](/docs/CS/OS/Linux/module/LKM.md)的参数、引用计数 |
| `/sys/fs` | 各文件系统自身的控制项（如 cgroup、fuse） |
| `/sys/kernel` | 内核全局对象，如 kobject、调试与安全相关条目 |
| `/sys/power`、`/sys/dev/.../power` | 电源管理、运行时 PM、唤醒控制 |

一个典型设备路径同时能从拓扑（`devices/pci0000:00/.../`）和功能（`class/net/eth0`）看到，后者通常是指向真身的符号链接。

## kobject and Attributes

sysfs 的内部基础是统一设备模型的核心对象 **kobject**：

- 每个 kobject 在内核里对应一个引用计数对象、一个父指针（构成层级）、一个名字和一个 `ktype`；
- kobject 通过 `kobject_add` 注册时在 sysfs 创建同名目录，目录结构就是 kobject 父子树；
- 具体对象（`struct device`、`struct device_driver` 等）**内嵌**一个 kobject，从而自动获得 sysfs 表示；
- **attribute（属性）**是 kobject 目录下的文件，用 `__ATTR` / `DEVICE_ATTR` 等宏声明，每个文件绑定一对 `show()`/`store()` 回调，读文件调 show、写文件调 store。

因此 sysfs 不是"信息转储"，而是**每个文件对应内核里一个具名属性和一对读写函数**，这保证了语义清晰、单值约定（sysfs 约定一个属性文件尽量只表示一个值，用一行文本）。

## Read and Write

```bash
# 读：网卡的 MAC、链路状态、MTU
cat /sys/class/net/eth0/address
cat /sys/class/net/eth0/operstate
cat /sys/class/net/eth0/mtu

# 写：触发一次设备动作（需要 root 且属性可写）
echo 1 > /sys/class/leds/input::capslock/brightness

# 块设备调度器：方括号标出当前选择
cat /sys/block/sda/queue/scheduler
# echo mq-deadline > /sys/block/sda/queue/scheduler

# 内核模块参数（module_param 暴露）
cat /sys/module/nf_conntrack/parameters/hashsize
```

约定与注意：

- 属性多为 ASCII 文本、单值、读顺序不保证并发安全，写要写入完整值；
- 频繁轮询不优雅时应使用 `poll()` 监听变化（如 `uevent`、电源/热插拔事件）；
- 与 proc 的 `sysctl`（`/proc/sys`）不同，sysfs 紧贴设备与驱动模型；做网络/存储参数调优时很多项就在 `/sys/class` 或 `/sys/block`。

## uevent and Hotplug

设备的**添加/移除/变化**由 kobject 的 **uevent** 机制广播：内核把事件（如 `add`、`remove`、`change`）连同设备属性（`DEVPATH`、`SUBSYSTEM`、`MODALIAS` 等 key=value）发出。用户态的 [udev](/docs/CS/OS/Linux/dev/udev.md) 通过 netlink 监听这些事件，从而：

- 在 `/dev` 下创建/删除设备节点并设权限；
- 依据 modalias 自动 `modprobe` 加载驱动（与 [LKM](/docs/CS/OS/Linux/module/LKM.md) 的 `MODULE_DEVICE_TABLE` 呼应）；
- 触发规则里的命名、符号链接与自定义命令。

也可向某设备的 `uevent` 文件 `echo add` 手动重放事件（冷插拔补事件时常用）。

## sysfs vs procfs vs debugfs

| 文件系统 | 挂载点 | 定位 | 稳定性 |
| --- | --- | --- | --- |
| sysfs | `/sys` | 统一设备模型、kobject 属性 | ABI 较稳定，面向用户程序 |
| procfs | `/proc` | 进程信息 + `/proc/sys` 调优 | 大部分稳定，部分历史混杂 |
| debugfs | `/sys/kernel/debug` | 开发者调试信息 | **不稳定**，不应用于生产逻辑 |
| configfs | `/sys/kernel/config` | 从用户态"创建对象/配置"（写创建、读查看） | 较稳定 |

## Links

- [fs (VFS)](/docs/CS/OS/Linux/fs/fs.md)
- [proc](/docs/CS/OS/Linux/fs/proc.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [device model](/docs/CS/OS/Linux/dev/device.md)
- [LKM](/docs/CS/OS/Linux/module/LKM.md)

## References

1. [Kernel Documentation: sysfs — The filesystem for exporting objects](https://docs.kernel.org/filesystems/sysfs.html)
2. [Kernel Documentation: The Linux Device Model](https://docs.kernel.org/driver-api/driver-model/overview.html)
3. [sysfs rules and conventions](https://www.kernel.org/doc/Documentation/filesystems/sysfs-rules.txt)
4. [Kernel source: fs/sysfs](https://elixir.bootlin.com/linux/latest/source/fs/sysfs)
