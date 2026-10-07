## Introduction

一条总线的工作可以拆成三段：**发现设备 → 匹配驱动 → 绑定并操作**。Linux 用统一模型覆盖所有总线 —— 设备树描述拓扑，driver model 负责配对，总线类型提供统一的操作原语（读写寄存器、DMA、中断）。

本篇是总线族的**横向串联**：讲清共性机制与三套支撑设施（regmap / pinctrl+GPIO / clk），总线特有的部分（PCI 的 BAR、URB 模型、I2C 时序）点到为止并给出独立笔记入口。

版本基线 **v7.2**。⚠️ 本篇开头有一批 v7.2 的 API 重命名（`spi_master`→`spi_controller`、regmap 字节序字段拆分、`gpiod_get`→`gpiod_get_index`），旧资料照抄会编译不过。

## Three-Phase Pattern: Discovery / Matching / Binding

### Discovery

设备从三个来源出现：

| 来源 | 机制 | 典型场景 |
| :-- | :-- | :-- |
| 设备树 | `of_platform_default_populate_init()` 扫描 `device_node` 树创建 `platform_device` | ARM/嵌入式 SoC |
| ACPI | `acpi_device_add()` | x86 |
| 固件枚举 | 总线驱动自己遍历硬件（如 PCI 的 CF8/CFC 扫描、EHCI 的端口探测） | PC 扩展设备 |

设备树路径与 initcall level 的关系见 [arm.md](/docs/CS/OS/Linux/boot/arm.md) —— `of_platform_default_populate_init` 处在 `arch_initcall_sync`（3s level），而 I2C/SPI 控制器本身是 `platform_device`、用 level 4 初始化，**这个 level 差是硬约束**，选错就会在自己的依赖还没初始化时被调用。

### Matching: The Unified Entry Point of the Driver Model

所有总线共享同一套匹配逻辑，在 `drivers/base/bus.c` 的 `bus_match_device()`。`struct bus_type` 里的 `.match` 回调由各总线提供：

```c
static int pci_bus_match(struct device *dev, const struct device_driver *drv)
```

匹配成功后调用驱动的 `probe()`。**PCI 的匹配细节**（`pci_match_device()` → 先查动态表 `drv->dynids.list`，再遍历 `drv->id_table`，最后看 `driver_override`）见 [dev/README.md](/docs/CS/OS/Linux/dev/README.md) 的 match/probe 一节。

### Binding

绑定后设备与驱动配对，`struct device` 里记着 `dev->driver`。热插拔时解除绑定并调用 `remove()`，驱动必须在此把资源（IRQ、寄存器映射、DMA 句柄）全部释放干净。

## PCI

### BAR: Window into the Address Space

**BAR = Base Address Register**，是设备上的一组寄存器，描述"我需要多大的地址空间"和"我的地址放在哪"。这是 PCI 规范术语（不在内核源码里展开）。

BAR 的地址空间类型由 `PCI_BASE_ADDRESS_SPACE` 决定：

```c
#define PCI_BASE_ADDRESS_SPACE 0x01        /* 0=memory, 1=I/O */
#define PCI_BASE_ADDRESS_SPACE_IO 0x01
#define PCI_BASE_ADDRESS_SPACE_MEMORY 0x00
#define PCI_BASE_ADDRESS_MEM_TYPE_MASK 0x06
#define PCI_BASE_ADDRESS_MEM_TYPE_32 0x00
#define PCI_BASE_ADDRESS_MEM_TYPE_1M 0x02 /* Below 1M [obsolete] */
#define PCI_BASE_ADDRESS_MEM_TYPE_64 0x04
```

BAR 0~5 是标准六条（32 位或 64 位），`0x30` 起是扩展寄存器：

```c
#define PCI_ROM_ADDRESS 0x30
#define PCI_ROM_ADDRESS_ENABLE 0x01
#define PCI_ROM_ADDRESS_MASK (~0x7ffU)
```

> **`PCI_BASE_ADDRESS_MEM_TYPE_1M` 带 `[obsolete]` 注释** —— 1M 以下的地址空间早已不用，写驱动时遇到这个标记直接忽略。

### The enable Family: Reference Counting

```c
#define PCI_ENABLE_...
```

`pci_enable_device_flags()` 内部用 `atomic_t enable_cnt` 计数（字段注释是 `/* pci_enable_device has been called */`），**多次 enable 不重复操作，disable 时归零才真正关闭**。

```c
	pci_enable_device_mem(dev);   /* = pci_enable_device_flags(dev, IORESOURCE_MEM) */
	pci_enable_device(dev);       /* IORESOURCE_MEM | IORESOURCE_IO */
```

> ⚠️ **v7.2 的变化**：旧的 `pci_enable_device_io()` / `pci_enable_device_bars()` **不存在**。要精确控制用 `pci_enable_device_flags()` 传自定义 flags。

### pcim_*: The devres-Aware Renaming

> ⚠️ **v7.2 的变化**：`pci_iomap` / `pci_iomap_range` / `pci_iomap_kasme` / `struct pci_devres` **全部不存在**，改为 `pcim_*` 家族：

```c
	pcim_iomap(pdev, bar, maxlen)
	pcim_iomap_region(pdev, bar, maxlen)
	pcim_iounmap_region(pdev, bar)
	pcim_iomap_regions(pdev, mask)
	pcim_request_region(pdev, bar)
	pcim_request_all_regions(pdev, mask)
	pcim_iomap_table(pdev)
	pcim_intx(pdev)
```

`pcim_` 前缀 = "PCI managed"，**资源自动随设备解绑释放**。这是 v7.x 的方向：**从"手动 request/free"迁移到"devres 托管"**。写新驱动一律用 `pcim_`。

### MSI/MSI-X and Vector Allocation

```c
int pci_alloc_irq_vectors(struct pci_dev *dev, unsigned int min_vecs,
			  unsigned int max_vecs, unsigned int flags);
void pci_free_irq_vectors(struct pci_dev *dev);
int pci_irq_vector(struct pci_dev *dev, unsigned int nr);
```

flags：

```c
#define PCI_IRQ_INTX (1 << 0)
#define PCI_IRQ_MSI (1 << 1)
#define PCI_IRQ_MSIX (1 << 2)
#define PCI_IRQ_AFFINITY (1 << 3)
#define PCI_IRQ_ALL_TYPES (PCI_IRQ_INTX | PCI_IRQ_MSI | PCI_IRQ_MSIX)
```

**`PCI_IRQ_ALL_TYPES` 存在而 `PCI_IRQ_ALL_MSIX` 不存在** —— 聚合常量是"所有类型"而非"仅 MSI-X"。

`pci_alloc_irq_vectors_affinity()` 的分配逻辑：MSIX 走 `__pci_enable_msix_range()`，MSI 走 `__pci_enable_msi_range()`，`PCI_IRQ_INTX` 且只求 1 个向量时走传统 `pci_intx()`。**向量数不够返回 `-ENOSPC`**，所以驱动必须检查返回值。

### Configuration Space Access

v7.2 的抽象是 **`struct pci_raw_ops`**（不是 `pci_ecam_...` 命名）：

```c
const struct pci_raw_ops pci_mmcfg = { .read = pci_mmcfg_read, .write = pci_mmcfg_write };
const struct pci_raw_ops pci_direct_conf1 = { .read = pci_conf1_read, .write = pci_conf1_write };
```

两种实现：**ECAM/MMCONFIG**（内存映射配置空间，64 位快）与 **legacy CF8/CFC**（端口 IO，慢但通用）。`pci_read_config_dword()` 是通用入口。

> **路径变化**：`arch/x86/kernel/pci/` 在 v7.2 **已不存在**，迁至 `arch/x86/pci/`（含 `mmconfig_64.c` / `direct.c` / `common.c`）。`include/linux/pci_regs.h` 也移到了 `include/uapi/linux/pci_regs.h`。

### Initialization Timing

```c
postcore_initcall(pci_driver_init);
```

**是 `postcore_initcall` 而非 `subsys_initcall(pci_init)`** —— PCI 总线在 core 初始化之后才注册，因为 PCI 设备探测依赖其他基础设施。

### SR-IOV

```c
int pci_enable_sriov(struct pci_dev *dev, int nr_virtfn);
int pci_disable_sriov(struct pci_dev *dev);
int pci_num_vf(struct pci_dev *dev);
int pci_vfs_assigned(struct pci_dev *dev);
```

> ⚠️ 旧的 `pci_num_virtfn()` 改为 **`pci_num_vf()`**。

回调侧 `struct pci_driver` 里的 SR-IOV 钩子：

```c
	int  (*sriov_configure)(struct pci_dev *dev, int num_vfs);
	int  (*sriov_set_msix_vec_count)(struct pci_dev *vf, unsigned int msix_vec_count);
	u32  (*sriov_get_vf_total_msix)(struct pci_dev *pf);
	const struct pci_error_handlers *err_handler;
```

`err_handler` 是 AER（Advanced Error Reporting）钩子 —— PCIe 错误注入与处理（用于验证机器的健壮性）。

## USB

### URB: The Carrier of All Transfers

USB 的核心抽象是 **URB（USB Request Block）**。`struct urb` 在 v7.2 有 1300 余行，关键字段：

```c
	struct usb_anchor *anchor;          /* 用于取消/超时处理 */
	struct usb_device *dev;
	struct usb_host_endpoint *ep;
	unsigned int pipe;                  /* 端点 + 方向 + 类型全编码在一个整数 */
	unsigned int stream_id;             /* 3.0+ bulk stream */
	int status;
	unsigned int transfer_flags;
	void *transfer_buffer;
	dma_addr_t transfer_dma;
	struct scatterlist *sg;
	struct sg_table *sgt;
	int num_mapped_sgs;
	int num_sgs;
	u32 transfer_buffer_length;
	u32 actual_length;
	unsigned char *setup_packet;        /* control 请求的 8 字节 setup 包 */
	dma_addr_t setup_dma;
	int start_frame;
	int number_of_packets;
	int interval;
	int error_count;
	void *context;                      /* 驱动私有数据挂这里 */
	usb_complete_t complete;            /* 完成回调 */
	struct usb_iso_packet_descriptor iso_frame_desc[];
```

> ⚠️ **v7.2 的重要变化**：`struct urb` **既没有 `type` 字段也没有 `user_data` 字段**！
> - **类型由 pipe 编码推导**：`usb_pipetype(pipe)` 从高位取值
> - **驱动私有数据用 `context`**

### Bit-Field Encoding of pipe

```c
#define USB_DIR_OUT 0        /* to device */
#define USB_DIR_IN 0x80      /* to host */
```

而类型常量是**独立的命名空间**：

```c
#define PIPE_ISOCHRONOUS		0
#define PIPE_INTERRUPT			1
#define PIPE_CONTROL			2
#define PIPE_BULK			3
```

⚠️ **这是个经典陷阱**：`PIPE_*` 的值序与设备描述符里的 `USB_ENDPOINT_XFER_*`（0=CONTROL, 1=ISOC, 2=BULK, 3=INT）**完全不同**。内核源码注释直接点明：

```c
/* NOTE: these are not the standard USB_ENDPOINT_XFER_* values!! (yet ...
 * they're the values used by usbfs) */
```

**只有 usbfs（用户态 API）保留了 usbfs 的历史错位，内核内部则统一用 `PIPE_*`。**

编码/访问宏：

```c
#define usb_pipein(pipe)  ((pipe) & USB_DIR_IN)
#define usb_pipeout(pipe) ((pipe) & ~USB_DIR_IN)
#define usb_pipedevice(pipe)   (((pipe) >> 8) & 0x7f)
#define usb_pipeendpoint(pipe) (((pipe) >> 15) & 0xf)
#define usb_pipetype(pipe)     (((pipe) >> 30) & 3)
```

构造时类型在**最高 2 位**（`pipe >> 30`），端点在第 15 位，设备号在第 8 位，方向在最低位。填充 URB 的三个便捷函数：

```c
void usb_fill_control_urb(struct urb *urb, struct usb_device *dev,
			  unsigned int pipe, void *buffer, unsigned int buffer_length,
			  void (*callback)(struct urb *urb), void *context);
void usb_fill_bulk_urb(...);
void usb_fill_int_urb(...);
```

**三者的方向由 `usb_fill_*` 自行设置**（`urb->transfer_flags |= (is_out ? URB_DIR_OUT : URB_DIR_IN)`）—— 旧版需要手工设 `URB_DIR_*`。

### transfer_flags

```c
#define URB_SHORT_NOT_OK 0x0001
#define URB_ISO_ASAP 0x0002
#define URB_NO_TRANSFER_DMA_MAP 0x0004
#define URB_ZERO_PACKET 0x0040
#define URB_NO_INTERRUPT 0x0080
#define URB_FREE_BUFFER 0x0100
/* 内部用（usbcore 与 HCD）：*/
#define URB_DIR_IN 0x0200
#define URB_DIR_OUT 0
```

`URB_ZERO_PACKET` 对 bulk 传输特别重要 —— **批量传输必须以 ZLP 结束**，否则设备可能一直等不到短包。

> ⚠️ 旧的 `URB_NO_FSBR` 在 v7.2 **不存在**。`0x0008`/`0x0010`/`0x0020` 是空洞。

### Descriptor Parsing

```c
static int usb_parse_endpoint(struct usb_device *dev, int endpoint, ...)
static int usb_parse_interface(struct usb_device *dev, ...)
static int usb_parse_configuration(struct usb_device *dev, ...)
```

三者都是 `static`，链式调用。最大包大小的读取改由 uapi inline 函数完成：

```c
#define usb_endpoint_maxp(epd)  (le16_to_cpu((epd)->wMaxPacketSize) & USB_ENDPOINT_MAXP_MASK)
#define usb_endpoint_maxp_mult(epd)  (USB_EP_MAXP_MULT(usb_endpoint_maxp(epd)) + 1)
```

> ⚠️ 旧的 `usb_max_packet()` / `usb_get_max_packet()` **不存在**。`maxp_mult` 是 USB 2.0 的"每帧包数倍数"（高速设备每微帧可发多包）。

### Registration and Ports

> ⚠️ **v7.2 的变化**：`usb_add_interface()` / `usb_add_interface_locked()` **不存在** —— 绑定改由 driver model 驱动（`device_attach(&intf->dev)`）。`usb_register` 是宏：

```c
#define usb_register(driver) usb_register_driver(driver, THIS_MODULE, KBUILD_MODNAME)
#define module_usb_driver(__usb_driver) \
	module_driver(__usb_driver, usb_register, usb_deregister)
```

端口事件处理也从 `hub_port_event()` 改名 **`port_event()`**；没有 `usb_add_port()` —— v7.2 改为**预建 `struct usb_port` 对象**（`hub->ports[port1 - 1]`）。

Gadget 侧（设备模式）主入口是 `usb_gadget_register_driver_owner()`，composite 框架用 `usb_composite_probe()`（`drivers/usb/gadget/composite.c`）。

## I2C

### Algorithms and Adapters

> ⚠️ **v7.2 的变化**：`struct i2c_algorithm` 的 `master_xfer` 降级为 **union 别名**（新名 `xfer`）：

```c
	union {
		int (*xfer)(struct i2c_adapter *adap, struct i2c_msg *msgs, int num);
		int (*master_xfer)(struct i2c_adapter *adap, struct i2c_msg *msgs, int num);
	};
	...
	union {
		int (*xfer_atomic)(...);
		int (*master_xfer_atomic)(...);
	};
```

文档标注 `@master_xfer: deprecated, use @xfer`。target 侧同理：

```c
	union {
		int (*reg_target)(struct i2c_client *client);
		int (*reg_slave)(struct i2c_client *client);
	};
```

旧的 `master_xfer_emailed` / `smbus_xfer_emailed` / `reg_notify` / `unreg_notify` **不存在**（只有 `_atomic` 变体）。

`struct i2c_adapter` 的关键字段：

```c
	struct module *owner;
	unsigned int class;
	const struct i2c_algorithm *algo;
	void *algo_data;
	const struct i2c_lock_operations *lock_ops;
	struct rt_mutex bus_lock;
	struct rt_mutex mux_lock;
	int timeout; /* in jiffies */
	int retries;
	struct device dev;
	unsigned long locked_flags;
	int nr;
	char name[48];
	struct irq_domain *host_notify_domain;
```

> ⚠️ **无 `busnr` / `list` / `adapter_type` / `slaves` 字段** —— adapter 表由 core 内部的 `idr` 承担。`nr` 是唯一标识（`of_alias_get_id()` 从设备树 alias 取）。

> ⚠️ `i2c_register_adapter()` 变成 **`static`**；`i2c_new_adapter()` / `i2c_adapter_unregister()` **不存在**。导出的只有 `i2c_add_adapter` / `devm_i2c_add_adapter` / `i2c_add_numbered_adapter` / `i2c_del_adapter`。`i2c_add_driver()` 也变成宏（转发 `i2c_register_driver()`）。

### Call Chain of a Single Transfer

`i2c_transfer()` → `__i2c_transfer()` → `adap->algo->master_xfer` → 适配器驱动 → 控制器寄存器。

`__i2c_transfer()` 的重试循环是关键：

```c
	for (ret = 0, try = 0; try <= adap->retries; try++) {
		if (i2c_in_atomic_xfer_mode() && adap->algo->master_xfer_atomic)
			master_xfer_atomic(...);
		else
			master_xfer(adap, msgs, num);
		if (ret != -EAGAIN)
			break;
		if (time_after(jiffies, orig_jiffies + adap->timeout))
			break;
	}
```

**只有 `-EAGAIN` 才重试**（表示"总线忙，稍后"），且受 `retries`（次数）与 `timeout`（jiffies 时限）双重限制 —— 用 jiffies 而非真实时间，说明这段代码假定运行在可抢占的上下文。

判空那行有个 v7.2 特征：

```c
	if (!adap->algo->master_xfer)
		return -EOPNOTSUPP;
```

**仍以 union 的 `master_xfer` 名字做判空**（新名 `xfer` 才是主字段）—— 读源码时容易困惑。

### Bit-bang: Running Without a Hardware Controller

```c
#define setscl(adap,val) adap->setscl(adap->data, val)
#define getscl(adap)     adap->getscl(adap->data)
static void scllo(void) { setscl(adap,0); }
static int sclhi(void) { ... setscl(adap,1); while (!getscl(adap)) ... }
```

`sclhi()` 里的注释说明了为什么要轮询：

```c
	/* Raise scl line, and do checking for delays. This is necessary for slower ... */
```

**I2C 没有硬件时钟拉伸信号线**（时钟是主设备拉出来的），所以主设备必须"拉高后等 SCL 真的高上去"，即软件实现的时钟同步 —— 这就是 `sclhi()` 里 `udelay(adap->udelay)` 轮询的由来。

算法名是 `i2c_bit_algo`（不是旧的 `i2c_albit`）：

```c
const struct i2c_algorithm i2c_bit_algo = { .xfer = bit_xfer, .xfer_atomic = bit_xfer_atomic, .functionality = bit_func };
```

> ⚠️ 文件路径也变了：`drivers/i2c/algo-bit.c` → **`drivers/i2c/algos/i2c-algo-bit.c`**。

### User-Space Interface

`/dev/i2c-N`（`drivers/i2c/i2c-dev.c`）暴露两个 ioctl：

| ioctl | 作用 |
| :-- | :-- |
| `I2C_SLAVE` / `I2C_SLAVE_FORCE` | 设置后续 ioctl 操作的从设备地址（**不需要内核已有该设备的 client**） |
| `I2C_RDWR` | 一次事务里做多组读写（`struct i2c_rdwr_ioctl_data`） |
| `I2C_SMBUS` | 走 SMBus 协议（`union i2c_smbus_data`） |

`I2C_SLAVE` 允许用户态对**任意地址**发事务（不限于已注册的 client），配合 `I2C_SLAVE_FORCE` 可绕过设备检查 —— 这是用户态驱动（如 spidev 风格的 I2C 工具）的基础。

## SPI

> ⚠️ **v7.2 的重大重命名**：`struct spi_master` → **`struct spi_controller`**，`spi_register_master()` → `spi_register_controller()`。**全树替换**，照抄旧代码会编译不过。

`struct spi_controller` 的关键字段：

```c
struct device dev;
struct list_head list;
s16 bus_num;
u16 num_chipselect;
u16 num_data_lanes;
u32 mode_bits;
u32 bits_per_word_mask;
u32 min_speed_hz;
u32 max_speed_hz;
u16 flags;
size_t (*max_transfer_size)(struct spi_controller *ctlr);
size_t (*max_message_size)(struct spi_controller *ctlr);
struct mutex io_mutex;
spinlock_t bus_lock_spinlock;
```

flags：

```c
#define SPI_CONTROLLER_HALF_DUPLEX BIT(0)
#define SPI_CONTROLLER_NO_RX       BIT(1)
#define SPI_CONTROLLER_NO_TX       BIT(2)
#define SPI_CONTROLLER_MUST_RX     BIT(3)
#define SPI_CONTROLLER_MUST_TX     BIT(4)
#define SPI_CONTROLLER_GPIO_SS     BIT(5)
#define SPI_CONTROLLER_SUSPENDED   BIT(6)
#define SPI_CONTROLLER_MULTI_CS    BIT(7)
```

`->flags` 里的 `MUST_TX` / `MUST_RX` 值得注意 —— 它们声明"每次传输必须同时收发"，用于某些只能全双工工作的控制器。

### chip_select Is an Array

> ⚠️ 旧的 `spi_cs_gpios`（标量）改为**数组** `chip_select[SPI_DEVICE_CS_CNT_MAX]` + 访问器 `spi_get_chipselect()` / `spi_set_chipselect()`。
> 注意 controller 级属性名是**复数** `cs_gpiods`。

### Transfer API

```c
static inline int spi_sync(struct spi_device *spi, struct spi_message *message);
static inline int spi_async(struct spi_device *spi, struct spi_message *message);
int spi_sync_locked(struct spi_device *spi, struct spi_message *message);
```

`spi_sync()` 的加锁包装：

```c
	mutex_lock(&spi->controller->bus_lock_mutex);
	__spi_sync(spi, message);
	mutex_unlock(&spi->controller->bus_lock_mutex);
```

`__spi_sync()` 里有条快路径：

```c
	if (READ_ONCE(ctlr->queue_empty) && !ctlr->must_async) {
		message->actual_length = 0;
		message->status = -EINVALPROGRESS;
		... __spi_transfer_message_noqueue(ctlr, message);
	}
```

**`must_async` 为假时走无队列的直接提交** —— 同步传输在驱动未提供 `->transfer_one` 时也能工作（走 `->transfer_one_message`）。

`spi_optimize_message()` 可让驱动把多个 `spi_transfer` 合并成一次控制器级传输（`ctlr->transfer` 回调），`devm_spi_optimize_message()` 用 devres 管理。

> `spi_finalize_message` 在 v7.2 改为面向 provider 的 `spi_finalize_current_message()` / `spi_finalize_current_transfer()`。

## Three Supporting Facilities

### regmap: Unified Abstraction for Register Access

I2C/SPI/MMIO 三种总线的寄存器访问逻辑高度相似（都是"写地址 → 写/读数据"），regmap 把它们统一成一套带缓存的 API。

> ⚠️ **v7.2 的重要变化**：`struct regmap_config` **没有单一的 `format` 字段**，字节序拆成两个独立字段：
> ```c
> enum regmap_endian reg_format_endian;
> enum regmap_endian val_format_endian;
> ```
> 也没有 `debug` / `verbose` 字段。

**8/16/32 位宽度 API 也不存在** —— 旧的 `regmap_readb` / `regmap_writeb` 等在 v7.2 统一为：

```c
int regmap_read(struct regmap *map, unsigned int reg, unsigned int *val);
int regmap_write(struct regmap *map, unsigned int reg, unsigned int val);
int regmap_bulk_read(struct regmap *map, unsigned int reg, void *val, size_t count);
int regmap_bulk_write(struct regmap *map, unsigned int reg, const void *val, size_t count);
int regmap_update_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int val);
```

宽度由 `val_bits` + format 决定，不需要 `readb/readw/readl` 三套函数。

**寄存器可读性/可写性/易失性**是 regmap 的核心概念 —— 声明了 `volatile_reg` 的寄存器不会被缓存：

```c
	bool (*writeable_reg)(struct device *dev, unsigned int reg);
	bool (*readable_reg)(struct device *dev, unsigned int reg);
	bool (*volatile_reg)(struct device *dev, unsigned int reg);
	bool (*precious_reg)(struct device *dev, unsigned int reg);
```

### Cache: The enum Member Is the "Backend Implementation Name"

> ⚠️ **v7.2 的变化**：`enum regcache_type` 的成员**从"存储粒度"改成了"后端实现名"**：
> ```c
> enum regcache_type {
> 	REGCACHE_NONE,
> 	REGCACHE_RBTREE,
> 	REGCACHE_FLAT,
> 	REGCACHE_MAPLE,
> 	REGCACHE_FLAT_S,
> };
> ```

旧资料里的 `regmap_cache_byte` / `regmap_cache_word` / `regmap_cache_block` **全部不存在** —— 命名维度换了：现在是"用哪种数据结构实现缓存"（红黑树 / 扁平数组 / maple 树 / 扁平稀疏）。

**新增 `REGCACHE_MAPLE`** 与内核其它地方从红黑树迁移到 maple 树的方向一致（见 [maple_tree](/docs/CS/OS/Linux/mm/maple_tree.md)）。

缓存 ops：

```c
struct regcache_ops {
	const char *name;
	enum regcache_type type;
	int (*init)(struct regmap *map);
	int (*exit)(struct regmap *map);
	int (*populate)(struct regmap *map);
	int (*read)(struct regmap *map, unsigned int reg, unsigned int *value);
	int (*write)(struct regmap *map, unsigned int reg, unsigned int value);
	int (*sync)(struct regmap *map, int min, int max);
	int (*drop)(struct regmap *map, int min, int max);
};
```

**读 volatile 寄存器会绕过缓存并返回 `-EINVAL`** —— 这是正确行为（volatile 意味着值可能被别人改了，缓存里的值是脏的）。理解这一点能解释"为什么读某些寄存器总是读到旧值"这类问题。

### Locking

```c
	regmap_lock lock;
	regmap_unlock unlock;
```

是**函数指针**（不是 mutex/spinlock 类型），配 `lock_arg`。`struct regmap` 内部用 union 容纳三种锁形态（mutex / spinlock / raw_spinlock），由 `can_sleep` / `use_raw_spinlock` 决定。

### IRQ domain

```c
int regmap_add_irq_chip_fwnode(struct regmap *map, struct regmap_irq_chip_data *data);
struct irq_domain *regmap_irq_get_domain(struct regmap_irq_chip_data *data);
int regmap_irq_get_virq(struct regmap_irq_chip_data *data, unsigned int hwirq);
```

`regmap_irq_get_domain()` 的注释说明了它为何接受 NULL：

```c
	Useful for drivers to request their own IRQs and for integration with
	subsystems. For ease of integration NULL is accepted as a domain,
	allowing devices to just call this even if no domain is allocated.
```

> 旧的 `regmap_irq_get_ressource()` **不存在**。

### pinctrl and GPIO

pinctrl 分两层，**这个划分很重要**：

> ⚠️ **`struct pinctrl_ops` 不含 `get` / `set` / `select_pinmux`**。真正的引脚复用操作在 **`struct pinmux_ops`** 里：
> ```c
> struct pinmux_ops {
> 	int (*request)(struct device *dev, unsigned int pin);
> 	void (*free)(struct device *dev, unsigned int pin);
> 	int (*get_functions_count)(struct pinctrl *pinctrl);
> 	...
> 	int (*set_mux)(struct device *dev, unsigned int pin, unsigned int function);
> 	void (*gpio_request_enable)(struct device *dev, unsigned int pin);
> 	...
> 	bool strict;
> };
> ```

`struct pinctrl_ops` 保留的是**分组/命名/DT 解析**层：

```c
struct pinctrl_ops {
	int (*get_groups_count)(struct pinctrl *pinctrl);
	void (*get_group_name)(struct pinctrl *pinctrl, unsigned int group, const char **name);
	int (*get_group_pins)(struct pinctrl *pinctrl, unsigned int group, const unsigned int **pins, unsigned int *num_pins);
	void (*pin_dbg_show)(struct pinctrl *pinctrl, struct seq_file *s);
	...
	int (*dt_node_to_map)(...);
	void (*dt_free_map)(...);
};
```

**四个 state 名称**（`include/linux/pinctrl/pinctrl-state.h`）：

```c
#define PINCTRL_STATE_DEFAULT "default"
#define PINCTRL_STATE_INIT "init"
#define PINCTRL_STATE_IDLE "idle"
#define PINCTRL_STATE_SLEEP "sleep"
```

设备树里 `pinctrl-names = "default"` 这个字符串就对应 `PINCTRL_STATE_DEFAULT` —— 这是设备树与内核之间的一条隐式契约。

state 切换 API：

```c
struct pinctrl_state *pinctrl_lookup_state(struct pinctrl *p, const char *name);
int pinctrl_select_state(struct pinctrl *p, struct pinctrl_state *s);
int pinctrl_select_default_state(struct device *dev);
struct pinctrl *devm_pinctrl_get(struct device *dev);
```

便利 inline `pinctrl_get_select()` = get + lookup + select 三步合一。

### gpiod: The Descriptor-Based GPIO

> ⚠️ **v7.2 的变化**：`gpiod_get()` / `gpiod_get_from_dev()` **不存在**，统一为：
> ```c
> struct gpio_desc *gpiod_get_index(struct device *dev, const char *con_id, unsigned int index);
> struct gpio_desc *gpiod_get_optional(struct device *dev, const char *con_id);
> struct gpio_desc *devm_gpiod_get_index_optional(struct device *dev, const char *con_id, unsigned int index);
> struct gpio_desc *fwnode_gpiod_get_index(struct fwnode_handle *fwnode, const char *con_id, int index);
> ```

**descriptor 方式（`struct gpio_desc *` + `con_id` 字符串）取代了 legacy 方式（整数引脚号）**。legacy 版集中在 `drivers/gpio/gpiolib-legacy.c`，只剩少量 `EXPORT_SYMBOL_GPL`。

cansleep 变体的存在理由在 `drivers/gpio/gpiolib.c` 的注释里：

```c
	This function may sleep if gpiod_cansleep() is true.
```

**GPIO 控制器可能挂在 I2C/SPI 上** —— 那种情况下操作引脚要发 I2C 事务，**必然睡眠**。所以 `gpiod_direction_output()` / `gpiod_set_value()` 在这类控制器上不能用在中断上下文。

```c
struct gpio_desc *gpiod_to_irq?  /* 实际是函数，不是类型 */
int gpiod_to_irq(struct gpio_desc *desc);
bool gpiod_cansleep(struct gpio_desc *desc);
```

`gpiod_to_irq()` 走 IRQ domain：`gpiochip_to_irq()` → `irq_create_mapping()`（或层级域下 `irq_create_fwspec_mapping()`）。**注意返回 0 表示 `NO_IRQ`**，判断时别写成 `if (irq)`。

> ⚠️ `gpiod_set_irq()` / `devm_gpiod_request_irq()` **不存在**。请求 GPIO 中断的惯用路径是 `gpiod_to_irq()` + `request_irq()`。

> ⚠️ **`/sys/class/gpio` 在 v7.2 仍然存在**（`drivers/gpio/gpiolib-sysfs.c`），同时 `drivers/gpio/gpiolib-cdev.c` 提供字符设备与 `GPIO_V2_LINE_*` ioctl。**两个接口并存**，"sysfs 已废弃"的说法在 v7.2 不成立。

### clk: The Clock Framework

> ⚠️ `struct clk_ops` 在 **`include/linux/clk-provider.h`**（不在 `clk.h`）。`struct clk_core` 定义在 `drivers/clk/clk.c` 内部（私有）。

`struct clk_ops` 的成员（v7.2）：

```c
	int (*prepare)(struct clk_hw *hw);
	void (*unprepare)(struct clk_hw *hw);
	int (*is_prepared)(struct clk_hw *hw);
	void (*unprepare_unused)(struct clk_hw *hw);
	int (*enable)(struct clk_hw *hw);
	void (*disable)(struct clk_hw *hw);
	int (*is_enabled)(struct clk_hw *hw);
	void (*disable_unused)(struct clk_hw *hw);
	int (*save_context)(struct clk_hw *hw);
	void (*restore_context)(struct clk_hw *hw);
	unsigned long (*recalc_rate)(struct clk_hw *hw, unsigned long parent_rate);
	int (*determine_rate)(struct clk_hw *hw, struct clk_rate_request *req);
	int (*set_parent)(struct clk_hw *hw, u8 index);
	u8 (*get_parent)(struct clk_hw *hw);
	int (*set_rate)(struct clk_hw *hw, unsigned long rate, unsigned long parent_rate);
	int (*set_rate_and_parent)(struct clk_hw *hw, unsigned long rate, unsigned long parent_rate, u8 index);
	unsigned long (*recalc_accuracy)(struct clk_hw *hw, unsigned long parent_accuracy);
	int (*get_phase)(struct clk_hw *hw);
	int (*set_phase)(struct clk_hw *hw, int degrees);
	int (*get_duty_cycle)(struct clk_hw *hw, struct clk_duty *duty);
	int (*set_duty_cycle)(struct clk_hw *hw, struct clk_duty *duty);
	int (*init)(struct clk_hw *hw);
	void (*terminate)(struct clk_hw *hw);
	void (*debug_init)(struct clk_hw *hw, struct dentry *dentry);
```

> ⚠️ **无 `is_essential` / `pll_ops`** —— v7.2 新增了 `determine_rate()`（新式 rate 请求接口）。

### Three Basic Cell Types

| 类型 | 结构 | 关键字段 |
| :-- | :-- | :-- |
| gate | `struct clk_gate` | `reg`, `bit_idx`, `flags` |
| divider | `struct clk_divider` | `reg`, `shift`, `width`, `table`, `flags` |
| mux | `struct clk_mux` | `reg`, `table`, `mask`, `shift`, `flags` |

**divider 的"+1 陷阱"**（`drivers/clk/clk-divider.c` 的 `_get_div()`）：

```c
	if (flags & CLK_DIVIDER_ONE_BASED)       return val;      /* 直接用寄存器值 */
	if (flags & CLK_DIVIDER_POWER_OF_TWO)    return 1 << val;  /* 2^val */
	/* 默认 */                                   return val + 1;  /* 寄存器值 + 1 */
```

**默认是"寄存器值 + 1"** —— 硬件 divider 寄存器写 0 通常表示"不分频"（除数 1），不是"除以 0"。搞反会导致频率算错 N 倍。

```c
#define CLK_DIVIDER_ONE_BASED BIT(0)
#define CLK_DIVIDER_POWER_OF_TWO BIT(1)
#define CLK_DIVIDER_MAX_AT_ZERO BIT(6)
```

> ⚠️ `CLK_DIVIDER_ZERO_BASED` **不存在**（别按名字猜）。

mux 的 index 编码：

```c
#define CLK_MUX_INDEX_ONE BIT(0)    /* index 就是寄存器值，不 +1 */
#define CLK_MUX_INDEX_BIT BIT(1)
```

**mux 默认行为与 divider 类似**（index 语义需看硬件），`CLK_MUX_INDEX_ONE` 让它按"直接用寄存器值"处理。

### Consumer API

```c
struct clk *clk_get(struct device *dev, const char *id);
struct clk *devm_clk_get(struct device *dev, const char *id);
struct clk *devm_clk_get_optional(struct device *dev, const char *id);
int clk_prepare_enable(struct clk *clk);
void clk_disable_unprepare(struct clk *clk);
unsigned long clk_get_rate(struct clk *clk);
int clk_set_rate(struct clk *clk, unsigned long rate);
long clk_round_rate(struct clk *clk, unsigned long rate);
int clk_set_rate_range(struct clk *clk, unsigned long min, unsigned long max);
```

**`clk_set_rate_range()` 是一对多调频的正确写法** —— 某些 SoC 在多个消费者都声明需求时，只能设一个共同频率（读-改-写会竞态），声明范围由框架统一仲裁。

`clk_prepare_enable()` / `clk_disable_unprepare()` 是"启用/禁用 + 计数"的组合，避免手工配对出错。

### Hierarchical Propagation

```c
static struct clk_core *clk_calc_new_rates(struct clk_core *core, unsigned long rate)
```

> ⚠️ 函数名是**复数** `clk_calc_new_rates`（旧资料写单数 `clk_calc_new_rate`）。

它在树上自底向上重算频率，规则由 flag 决定：

```c
#define CLK_SET_RATE_PARENT BIT(2) /* propagate rate change up one level */
```

注释说明了必须走完子树的原因：

```c
	/* Notify about rate changes in a subtree. Always walk down the whole
	   tree so that in case of an error we can walk down the whole tree again */
```

**`->set_rate` 失败后不能只回滚一部分** —— 所以要么整棵子树都算成功，要么整棵都不改。

### Device Tree Bindings

```c
struct clk *of_clk_get(struct device_node *np, int index);
struct clk *of_clk_get_by_name(struct device_node *np, const char *name);
```

DT 属性：

```dts
clocks = <&osc 1>, <&pll 2>;    /* 索引对应 #clock-cells */
clock-names = "ref_clk", "pll";
```

`devm_clk_get(dev, "ref_clk")` 内部就走 `of_clk_get_by_name()`。

**`#clock-cells` 决定索引的含义**：0 表示只有一个时钟，1 表示后面跟一个参数（如 mux 的选择位）。

> ⚠️ `of_clk_parse` 在 v7.2 **不存在**。

### Debugging

```shell
mount -t debugfs none /sys/kernel/debug
cat /sys/kernel/debug/clk/clk_summary
```

`clk_summary` 递归打印整棵时钟树（`clk_summary_show_subtree()`），是排查"某个设备时钟没开"的第一个工具。

## Seams with Other Subsystems

- **设备模型**：总线与 driver model 的绑定见 [设备模型 device](/docs/CS/OS/Linux/dev/device.md)。
- **device tree**：总线设备的发现依赖 DT，见 [arm](/docs/CS/OS/Linux/boot/arm.md)。
- **initcall 顺序**：总线初始化的 level 约束见 [启动链](/docs/CS/OS/Linux/boot/README.md)。
- **中断**：MSI/MSI-X、regmap irqchip、GPIO irq 都要接 IRQ domain，见 [Interrupt](/docs/CS/OS/Linux/Interrupt.md)。
- **电源管理**：runtime PM 的回调由总线执行、devfreq/clk 受 power domain 管理，见 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md)。
- **内存**：DMA 相关的内存屏障与映射，见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md) 与 [mm/pagetable](/docs/CS/OS/Linux/mm/pagetable.md)。
- **kprobe/eBPF**：动态观测总线的手段，见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。

## Troubleshooting Quick Reference

```shell
# 设备树里声明了什么
ls /proc/device-tree/*/status              # ok = 驱动已绑定（bound）
cat /proc/device-tree/*/compatible | tr '\0' '\n'
ls -l /sys/bus/i2c/devices/                # I2C client
ls -l /sys/bus/spi/devices/                # SPI device
ls -l /sys/bus/pci/devices/                # PCI 设备

# 调试 driver model
cat /sys/bus/i2c/drivers/<drv>/bind        # 手动 bind
echo <addr> > /sys/bus/i2c/drivers/<drv>/unbind
dmesg | grep -E "probe failed|bind failed"

# regmap 调试（有 debugfs 时）
mount -t debugfs none /sys/kernel/debug
ls /sys/kernel/debug/regmap/               # 缓存内容可视化
cat /sys/kernel/debug/regmap/<addr>/registers

# 时钟树
cat /sys/kernel/debug/clk/clk_summary | grep -i <name>

# GPIO
cat /sys/kernel/debug/gpio                 # 全局状态
cat /sys/kernel/debug/pinctrl/             # pinctrl 状态

# USB
lsusb -t                                  # 拓扑与速度
cat /sys/bus/usb/devices/*/power/control

# 设备未绑定时最常见的原因
dmesg | grep -iE "of_match|probe defer|EPROBE_DEFER|no device tree"
```

## Links

- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [Linux 枢纽](/docs/CS/OS/Linux/Linux.md)
- [启动链](/docs/CS/OS/Linux/boot/README.md)
- [arm（设备树与 initcall level）](/docs/CS/OS/Linux/boot/arm.md)
- [Interrupt](/docs/CS/OS/Linux/Interrupt.md)
- [runtime PM 设备省电](/docs/CS/OS/Linux/PM/runtimepm.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)

## References

1. [Linux Kernel Documentation — Driver model](https://docs.kernel.org/driver-api/driver-model/overview.html)
2. [Linux Kernel Documentation — PCI](https://docs.kernel.org/PCI/index.html)
3. [Linux Kernel Documentation — USB/USB](https://docs.kernel.org/usb/index.html)
4. [Linux Kernel Documentation — I2C](https://docs.kernel.org/i2c/index.html)
5. [Linux Kernel Documentation — SPI](https://docs.kernel.org/spi/index.html)
6. [Linux Kernel Documentation — regmap](https://docs.kernel.org/basic-devices/regmap/regmap.html)
7. [Linux Kernel Documentation — pinctrl](https://docs.kernel.org/driver-api/pinctrl.html)
8. [Linux Kernel Documentation — Common Clock Framework](https://docs.kernel.org/driver-api/clk.html)
