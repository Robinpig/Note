## Introduction

**udev** 是 Linux 的**用户态设备管理器**：内核负责发现硬件、初始化驱动，并通过 [sysfs](/docs/CS/OS/Linux/fs/sysfs.md) 把设备模型导出；udev 在用户态监听内核的 **uevent**，据此在 `/dev` 下创建设备节点、设置属主权限、建立稳定的符号链接、加载所需模块并触发用户配置的动作。

它要解决的核心问题：内核按发现顺序给设备命名（`sda`、`sdb`……），而同一磁盘在不同启动顺序下名字会漂移。udev 用设备的**稳定属性**（厂商/型号/序列号、文件系统 UUID/标签、总线位置等）经规则匹配，给出固定名称（如 `/dev/disk/by-id/...`、`/dev/disk/by-uuid/...`），让上层引用不再受枚举顺序影响。

现代系统上 udev 已并入 **systemd** 仓库（systemd-udevd），配合 devtmpfs 工作。

## Architecture

| 组件 | 职责 |
| --- | --- |
| 内核 + devtmpfs | 内核维护一个挂载在 `/dev` 的最小设备文件系统，按主次设备号自动创建基础节点 |
| **systemd-udevd** | 常驻守护进程，从内核 netlink 接收 uevent，顺序执行规则 |
| **udev rules** | `/usr/lib/udev/rules.d`（发行版/包提供）、`/etc/udev/rules.d`（管理员，优先级高）中的 `*.rules` |
| **udevadm** | 查询与控制工具（info / trigger / monitor / settle / control） |
| `libudev` / `sd-device` | 程序库，供应用枚举/监视设备 |
| modprobe（kmod） | 按 modalias 自动加载匹配驱动，见 [LKM](/docs/CS/OS/Linux/module/LKM.md) |

事件流：

```
内核发现设备/加载驱动
   → 注册 device(kobject)，在 sysfs 生成目录，发 kobject_uevent
   → netlink(KOBJ_UEVENT) 广播 add/remove/change + SUBSYSTEM/MODALIAS/...
   → systemd-udevd 接收，按字典序匹配规则
        ├─ 设置 NAME/SYMLINK/OWNER/GROUP/MODE
        ├─ 在 /dev(devtmpfs) 上调整节点/建符号链接
        ├─ 触发 modprobe、RUN 程序、打 TAG
        └─ 更新 /run/udev 数据库
```

## Rules

规则文件按文件名字典序处理（`NN-xxx.rules`，数字越小越早），一个文件内从上到下匹配；同一设备的键值可累积，可自定义"仅首次匹配生效""跳到指定 label"等控制流。常见键：

| 键 | 含义 |
| --- | --- |
| 匹配 | `SUBSYSTEM`、`KERNEL`（内核名）、`ATTR{}`/`ATTRS{}`（sysfs 属性）、`ENV{}`、`KERNELS`、`SUBSYSTEMS`、`TAG` |
| 赋值 | `NAME`（节点名）、`SYMLINK`（稳定别名）、`OWNER/GROUP/MODE`（权限） |
| 动作 | `RUN+=`（执行外部程序）、`ENV{KEY}=`（设变量）、`TAG+="systemd"` |
| 元规则 | `ACTION=="add|change|remove"` |

示例（固定一个 USB 串口设备的名字与权限）：

```udev
# /etc/udev/rules.d/99-myusb.rules
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60",
    ATTRS{serial}=="0001", SYMLINK+="myusb", MODE="0666"
```

磁盘的稳定命名由发行版规则自动生成，常见符号链接目录：

```
/dev/disk/by-id/      # 硬件/序列号稳定标识
/dev/disk/by-uuid/    # 文件系统 UUID
/dev/disk/by-label/   # 文件系统标签
/dev/disk/by-path/    # 总线/拓扑位置
```

`/etc/fstab` 推荐用 UUID/by-id 而不是 `/dev/sdaN`，正是利用 udev 的稳定命名。

## udevadm

```bash
# 查看某设备的全部 sysfs 属性、用于写匹配规则
udevadm info -a -n /dev/sdb
udevadm info -q property -n /dev/sdb          # 设备当前属性/环境变量

# 实时监听 uevent（调试热插拔/规则）
udevadm monitor --udev --kernel

# 对已存在设备重放 add 事件（改完规则后让其重新生效）
udevadm trigger --subsystem-match=usb --action=add
udevadm settle                                # 等待事件队列处理完(脚本里常用)
```

## Boot and Coldplug

启动早期由 devtmpfs 先提供基础 `/dev` 节点（内核直接建），随后 udevd 启动并通过 **coldplug**（`udevadm trigger`）对 sysfs 里已存在的设备"补发"一遍 add 事件，使所有规则、稳定链接、模块加载在用户空间就绪。这样热插拔与冷启动走同一套规则路径。

## Relationship to sysfs and Modules

- udev 的设备视图与判断信息几乎全部来自 [sysfs](/docs/CS/OS/Linux/fs/sysfs.md) 的层级与属性，规则里的 `ATTRS{}` 就是沿 sysfs 父链向上找属性。
- 自动加载驱动依赖 uevent 携带的 `MODALIAS`：设备在 sysfs 暴露 modalias，模块用 `MODULE_DEVICE_TABLE` 声明支持的 ID 表，`modprobe` 据此匹配装载，详见 [LKM 自动装载](/docs/CS/OS/Linux/module/LKM.md)。
- 更底层的设备模型（`struct device`、总线、驱动绑定、device tree）见 [device](/docs/CS/OS/Linux/dev/device.md)。

## Links

- [device model](/docs/CS/OS/Linux/dev/device.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)
- [LKM](/docs/CS/OS/Linux/module/LKM.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [systemd udev manual](https://www.freedesktop.org/software/systemd/man/latest/udev.html)
2. [Writing udev rules (reactivated.net)](https://reactivated.net/writing_udev_rules.html)
3. [Kernel Documentation: device-model / uevent](https://docs.kernel.org/driver-api/driver-model/overview.html)
4. [udevadm manual](https://www.freedesktop.org/software/systemd/man/latest/udevadm.html)
