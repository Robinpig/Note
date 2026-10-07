## Introduction

设备驱动是内核里**唯一被允许直接操作硬件**的部分：CPU 通过它读写设备寄存器、响应设备中断、协调 DMA。但写驱动不应是"每个硬件各搞一套"——一台机器上几十上百个设备，如果驱动作者各自处理命名、热插拔、电源、用户态接口，系统会彻底失控。Linux 因此建了一套统一的**设备模型（device model）**，把"设备是什么、挂在哪、由谁驱动、用户怎么看到它"全部标准化。

本页是 `dev/` 目录的链路总图，沿一条因果主线展开：内核先拿到**硬件信息**，据此抽象出 `device`；驱动以 `device_driver` 形式注册，二者在 **bus（总线）** 上按 match 规则相遇、经 **probe 绑定**；绑定后驱动通过**字符 / 块 / 网络三类接口**把能力暴露给用户态，而 **sysfs + udev** 在用户侧呈现和管理这些设备。记住一句：**设备模型是骨架，bus 上的 match/probe 是心脏，三类设备接口是对外窗口**。

## Foundation: kobject and the Device Model

设备模型最底层是统一的引用计数与层次构件，这部分见 [device](/docs/CS/OS/Linux/dev/device.md)：

- **kobject**：每个设备对象内嵌一个 `kobject`，提供引用计数（kref）、父指针、名字，以及挂进 sysfs 的能力；
- **kobj_type**：决定对象如何释放（`release`）和暴露哪些默认属性组；
- **kset**：一组同类 kobject 的集合，负责把它们组织成层级、广播 uevent。

这三者回答"设备对象如何被计数、组织、导出"，但它们本身不区分设备类型——真正描述"一个具体设备 / 一个具体驱动"的是下面三支柱。

## Three Pillars: device, driver, bus

设备模型的核心是三个结构的关系。

**device（设备）** 描述"有这么一个硬件"。内核里是 `struct device`（6.12 `include/linux/device.h`），关键字段：

- `parent`：父设备，构成拓扑层级（控制器 → 挂在其上的设备）；
- `bus`：设备挂在哪条总线上；`driver`：当前由哪个驱动接管（未绑定时为空）；
- `driver_data`：驱动私有数据，probe 时挂上、之后用 `dev_get_drvdata` 取回；
- `dma_mask` / `dma_ops` / `cma_area` 等：DMA 寻址能力与操作集，决定设备能访问哪些物理地址。

**device_driver（驱动）** 描述"我会操作这类设备"。结构是 `struct device_driver`（`include/linux/device/driver.h`），含驱动名、挂在哪条总线、以及最关键的两个回调 `probe`（绑定后初始化设备）与 `remove`（解绑时清理）；`of_match_table` 指向它支持的设备树 ID 表。

**bus_type（总线）** 是把前两者撮合起来的中介，结构 `struct bus_type`（`include/linux/device/bus.h`），核心是两个回调：

```c
struct bus_type {
    ...
    int (*match)(struct device *dev, const struct device_driver *drv);
    int (*probe)(struct device *dev);
    ...
};
```

总线掌握"哪个驱动配哪个设备"的规则——PCI/USB 上是按厂商/设备 ID 匹配，platform/设备树场景按 `compatible` 字符串匹配。没有 bus，device 和 driver 只是两份互不相干的注册表。

## The Core: match and probe Binding

设备与驱动的**绑定（binding）**是设备驱动链最关键的事件，无论设备先到还是驱动先到，逻辑相同：

1. 新设备注册（或新驱动注册）后，总线遍历对方一侧的列表；
2. 对每对 (device, driver) 调总线的 `match()`，按 ID / `compatible` 判断是否相配；
3. 相配则把 `device->driver` 指向该驱动，调用驱动的 `probe()`——驱动在这里分配私有结构、申请内存、注册中断、初始化硬件、把 `driver_data` 挂回 device；
4. probe 成功，绑定完成；失败则解绑、继续尝试下一个驱动。

这个设计解释了**驱动为什么可以按需加载**：设备先插入、驱动模块还没在内存里时，绑定暂不发生；内核经 uevent 通知用户态，`modprobe` 据 modalias 把对应驱动模块加载进来，驱动一注册就回头匹配上那个等待的设备。模块与 modalias 机制见 [LKM](/docs/CS/OS/Linux/module/LKM.md)，用户侧的加载动作见 [udev](/docs/CS/OS/Linux/dev/udev.md)。

> 设备被拔出或驱动卸载时走反向流程：调驱动的 `remove()` 释放资源、解除绑定，从 sysfs 消失并广播 remove uevent。

## Where Hardware Information Comes From: Device Tree / ACPI

驱动要 probe，前提是内核知道"机器上有什么设备、资源如何分配"。这套信息有两大来源：

- **Device Tree（设备树）**：ARM/ARM64、RISC-V 的主流方式。bootloader 把 DTB 传给内核，`setup_arch()` 里经 `setup_machine_fdt()` 扫描、`unflatten_device_tree()` 把每个节点展开为 `struct device_node`，节点间以父/子/兄弟指针相连。`compatible` 属性正是之后 driver 匹配的依据。完整启动流程见 [device 的 device tree 章](/docs/CS/OS/Linux/dev/device.md?id=device-tree)。
- **ACPI**：x86 服务器/PC 的主流方式，由固件提供表（DSDT/SSDT）描述设备与资源。

对驱动而言两者经统一的 firmware-node 抽象收敛——驱动可声明 `of_device_id`（设备树）或 ACPI ID 表，`of_match_table` 与 `compatible` 是常见落点：

```c
struct of_device_id {
    ...
    char    compatible[128];
};
```

还有一类 **platform device**：并非真实物理总线、而是内核自己描述的设备（SoC 内集成外设），它同样走 device + driver + match/probe，只是 bus 换成虚拟的 platform bus。

## External Window: Three Types of Device Interfaces

设备绑定后，用户程序怎么用它？Linux 按设备形态分三类接口，驱动通过实现对应的操作集把能力交出去：

**① 字符设备（character device）**：最常见，按字节流访问、可随机/顺序读写，如串口、键盘、/dev/null。核心是 `struct cdev`（`include/linux/cdev.h`），它内嵌 kobject、持有 `struct file_operations`（open/read/write/ioctl/mmap/release 的函数表）。用户态打开 `/dev/xxx` 时，内核先走统一的占位 fops，再由 `chrdev_open()` 按设备号查出该 cdev 并把 file 的操作表**整体换成驱动的**——这是字符设备分派的关键一步。完整注册流程（设备号申请、三层映射表、miscdevice 快捷方式）见 [字符设备驱动](/docs/CS/OS/Linux/dev/char.md)。

**② 块设备（block device）**：以固定大小"块"为单位、可寻址、能挂文件系统，如磁盘。驱动围绕 `gendisk` 描述设备、提供请求队列处理 I/O 请求，现代硬件走 blk-mq 多队列、纯内存设备走 bio-based `submit_bio`——完整结构与注册、下发链路见 [块设备驱动](/docs/CS/OS/Linux/dev/block.md)；块设备与文件系统、I/O 调度、PageCache 深度耦合（读写路径见 [IO](/docs/CS/OS/Linux/IO/IO.md)）。

**③ 网络设备（network device）**：收发报文，不对应 `/dev` 节点，用 `struct net_device` 描述，经 `register_netdevice` / `register_netdev` 注册，驱动提供收发包回调（NAPI 轮询、`ndo_start_xmit` 等）。完整收发送链路见 [网络知识地图](/docs/CS/OS/Linux/net/README.md)。

三类设备的共同点：都内嵌/关联 `device` 结构，因此自动获得设备模型的命名、sysfs、电源管理、热插拔能力，驱动不必各自实现。

## User Space: sysfs and udev

内核设备模型需要一个对外的呈现面，由两者承担：

- **sysfs**：把设备拓扑与属性导出到 `/sys`——总线、设备、驱动各成目录，目录间的符号链接直接体现"设备绑定了哪个驱动"。驱动可暴露可读/可写属性（如配置寄存器参数），见 [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)。
- **udev**：用户态设备管理器，监听内核 uevent，在 `/dev`（devtmpfs）上建节点、设权限、按设备稳定属性建立不随枚举漂移的符号链接（`/dev/disk/by-id/...`）、并触发 modprobe 自动加载驱动。完整规则与 `udevadm` 见 [udev](/docs/CS/OS/Linux/dev/udev.md)。

冷启动时 udev 经 coldplug 对已存在设备"补发" add 事件，使热插拔与冷启动走同一套规则——至此内核发现设备 → 驱动绑定 → 用户态可见的链路闭环。

## Specialized Subsystem: input

鼠标、键盘、传感器这类"不断产生事件"的设备有专门的 **input 子系统**（[input](/docs/CS/OS/Linux/dev/input.md)），它把设备端（`input_dev`，驱动报告事件）与处理端（`input_handler`，定义如何处理事件）解耦：驱动只负责上报按键/坐标等 input 事件，不必关心事件最终是写进 `/dev/input/eventX` 还是交给系统其他部分。这是设备驱动中"分层解耦"的典型。

## How Drivers Interface with Other Subsystems

- **内存**：驱动申请的缓冲最终来自 [buddy/slab](/docs/CS/OS/Linux/mm/README.md)；DMA 用到的连续内存常由 CMA 提供，这也是 zone 里要给可移动页分组的原因之一。
- **中断**：驱动在 probe 里 `request_irq` 注册中断处理，设备就绪后由硬中断驱动接收流程，见 [Interrupt](/docs/CS/OS/Linux/Interrupt.md)。
- **进程**：驱动的 read/write 常让进程经等待队列睡眠、数据就绪再唤醒，机制同 [thundering herd](/docs/CS/OS/Linux/proc/thundering_herd.md)。
- **内核协同全景**：驱动如何参与一次完整的网络请求，见 [内核协同链路](/docs/CS/OS/Linux/Architecture.md)。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [input](/docs/CS/OS/Linux/dev/input.md)

## References

1. [Linux Device Model — kernel.org driver API](https://www.kernel.org/doc/html/latest/driver-api/driver-model/overview.html)
2. [Driver Binding — kernel.org](https://www.kernel.org/doc/html/latest/driver-api/driver-model/binding.html)
3. [Bus Types — kernel.org](https://www.kernel.org/doc/html/latest/driver-api/driver-model/bus.html)
