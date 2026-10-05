## Introduction

内核 panic 之后，系统已经不具备继续运行的条件，但现场的寄存器、栈、内核数据结构都还有巨大调试价值。Linux 提供两条互补的路径把它们留下来：

- **崩溃转储（crash dump）** —— 用 kexec 跳过一个全新内核启动，直接进入"转储捕获内核"，把崩溃内核的物理内存整块导出成 ELF 文件。**完整但要占用一块常驻内存**。
- **持久日志（pstore）** —— panic 前把日志写进一块掉电不丢的存储区（通常是固件保留的 RAM），重启后从 `/sys/fs/pstore` 读回。**廉价且几乎不占资源，但只有日志，没有内存镜像**。

两者不是二选一：生产环境通常同时开，pstore 保证"至少能看到最后几行"，kdump 保证"能看到全貌"。本文按内核源码里的实际调用链展开，版本基线 **v7.2**（所有行号与常量均在该版本核实）。

## panic 的分叉点

一切从 `panic()` 开始。它是个薄封装，真正的逻辑在 `vpanic()`（`kernel/panic.c`），而**决定"跳去 kdump"的那一行**就在其中：

```c
void vpanic(const char *fmt, va_list args)
{
	/* ... */
	if (!_crash_kexec_post_notifiers)
		__crash_kexec(NULL);

	panic_other_cpus_shutdown(_crash_kexec_post_notifiers);

	printk_legacy_allow_panic_sync();
	atomic_notifier_call_chain(&panic_notifier_list, 0, buf);
	sys_info(panic_print);
	kmsg_dump_desc(KMSG_DUMP_PANIC, buf);

	if (_crash_kexec_post_notifiers)
		__crash_kexec(NULL);
	/* ... */
}
```

`__crash_kexec()` 在这里出现**两次**，中间夹着 notifier 链与 `kmsg_dump`。这不是笔误，而是由 `crash_kexec_post_notifiers` 这个编译期开关决定的：

| 开关 | 顺序 | 权衡 |
| :-- | :-- | :-- |
| 未设置（默认） | 先 `__crash_kexec()`，走 kdump；notifier / kmsg_dump **基本没机会跑** | kdump 成功率高，但可能丢失 panic 前的详细现场 |
| 设置 | 先跑 notifier 与 kmsg_dump（让 pstore 有机会落盘），再 `__crash_kexec()` | pstore 能拿到完整日志，但 notifier 本身可能让崩溃内核更不稳定，**反而降低 kdump 成功率** |

源码注释把后者的风险写得很直白（"since some panic_notifiers can make crashed kernel more unstable, it can increase risks of the kdump failure too"）。这是排查"kdump 偶发失败"时值得先怀疑的一个开关。

另外注意 `__crash_kexec(NULL)` 是**绕过 `panic_cpu` 检查**的直接调用：此刻已经确认本 CPU 是第一个进入 panic 的那个（`panic_try_start()` 抢到了 `panic_cpu`），无需再判断。

## panic_cpu：为什么只有一个 CPU 干这件事

panic 可能多路并发（一个 CPU 在 oops 处理中 panic，另一个 CPU 同时被中断打进来）。内核用单一原子变量选举出"负责 panic 的 CPU"：

```c
bool panic_try_start(void)
{
	int old_cpu, this_cpu;
	/*
	 * Only one CPU is allowed to execute the crash_kexec() code as with
	 * panic().  Otherwise parallel calls of panic() and crash_kexec()
	 * may stop each other.  To exclude them, we use panic_cpu here too.
	 */
	old_cpu = PANIC_CPU_INVALID;
	this_cpu = raw_smp_processor_id();

	return atomic_try_cmpxchg(&panic_cpu, &old_cpu, this_cpu);
}
```

`atomic_try_cmpxchg` 成功者是唯一的执行者，失败者走 `panic_smp_self_stop()` 把自己停住等死。这里有个易踩的细节：**`crash_kexec()` 也走同一个 `panic_try_start()`**，所以如果崩溃是 oops 触发的（`oops_in_progress > 0`），显式调用 `crash_kexec()` 反而可能因为 `panic_cpu` 已被占用而什么都不做。

配套的查询接口有两个，注释说明了各自的使用场景：

```c
bool panic_on_this_cpu(void);    /* 本 CPU 正在 panic —— 别人要让出打印资源 */
bool panic_on_other_cpu(void);   /* 别处正在 panic —— 本 CPU 要立刻让出打印资源 */
```

`panic_on_other_cpu()` 的注释写得很有意思："When true, the local CPU should immediately release any printing resources that may be needed by the panic CPU" —— 这是多核 panic 里 console 锁争用的处理依据。

## 停掉其他 CPU：crash_smp_send_stop

`__crash_kexec()` 拿到 kexec 锁后，真正的第一步是把其他 CPU 全部按停。`kernel/panic.c` 的 `panic_other_cpus_shutdown()` 特意区分了两条路径：

```c
	if (!crash_kexec)
		smp_send_stop();
	else
		crash_smp_send_stop();
```

注释解释了原因：常规的 `smp_send_stop()` **未针对 panic 场景加固**。如果想在 notifier 与 kmsg_dump 之后再做 kdump（`crash_kexec_post_notifiers` 路径），此时调度器已经不工作了，需要架构额外提供的 `crash_smp_send_stop()` 来完成剩余工作。

x86 侧的实现（`arch/x86/kernel/crash.c`）覆盖了 SMP + 本地 APIC 配置，手段是 **NMI shootdown**：

```c
static void kdump_nmi_callback(int cpu, struct pt_regs *regs)
{
	crash_save_cpu(regs, cpu);
	cpu_emergency_stop_pt();   /* 停 Intel PT */
	kdump_sev_callback();
	disable_local_APIC();
}

void kdump_nmi_shootdown_cpus(void)
{
	nmi_shootdown_cpus(kdump_nmi_callback);
	disable_local_APIC();
}
```

用 NMI 而不是 IPI，是因为**目的 CPU 此刻可能已经关中断、甚至正卡在坏掉的路径上**，IPI 需要对方正常响应中断上下文。NMI 不可屏蔽，是崩溃场景下唯一可靠的信号。注意 `crash_save_cpu(regs, cpu)` —— 每个被停的 CPU 都把自己的寄存器状态存下来，这正是转储里各 CPU 栈的来源。

## native_machine_crash_shutdown：x86 关机序列

停完其他 CPU，x86 走 `native_machine_crash_shutdown()`。函数头注释说明了它的设计原则："The minimum amount of code to allow a kexec'd kernel to run successfully needs to happen here." 顺序上有一批不可省的硬件操作：

```c
	local_irq_disable();
	crash_smp_send_stop();
	tdx_sys_disable();
	x86_virt_emergency_disable_virtualization_cpu();
	cpu_emergency_stop_pt();
#ifdef CONFIG_X86_IO_APIC
	/* Prevent crash_kexec() from deadlocking on ioapic_lock. */
	ioapic_zap_locks();
	clear_IO_APIC();
#endif
	lapic_shutdown();
	restore_boot_irq_mode();
	hpet_disable();
	x86_platform.guest.enc_kexec_begin();
	x86_platform.guest.enc_kexec_finish();
	crash_save_cpu(regs, smp_processor_id());
```

几个值得记住的点：

- **`ioapic_zap_locks()` 是为防死锁**。IO APIC 的锁可能被某个坏掉的 CPU 持有，若不做特殊处理，`crash_kexec()` 后续路径会卡在这里。
- **`restore_boot_irq_mode()`** 把中断控制器恢复到引导器交还控制权时的状态，方便第二内核或固件继续用。
- **`enc_kexec_begin()` / `enc_kexec_finish()` 这对调用是 v7.x 的加密内存保护协作点**。注释解释了非崩溃 kexec 与崩溃 kexec 的调用时机差异：前者调度器还在跑，回调可以等所有在途的 shared↔private 转换完成；后者在只剩一个 CPU、中断已关时调用，**只能检测竞争并上报**，无法等待。
- `tdx_sys_disable()` 与 `x86_virt_emergency_disable_virtualization_cpu()` 是 TDX / 虚拟化环境的紧急关闭，防止第二内核在宿主与 Guest 状态不一致时启动。

## 内存预留：crashkernel

kdump 需要一块内存放第二内核。关键点是这块区域**必须从内核的线性映射里摘掉**，否则运行中的 DMA 会把转储镜像写花。源码注释直接点明了这个后果："This ensures that ongoing Direct Memory Access (DMA) from the system kernel does not corrupt the dump-capture kernel."

v7.2 里这块预留的实现已从 `kernel/crash.c` 拆到独立的 **`kernel/crash_reserve.c`**，全局描述符有两个：

```c
struct resource crashk_res = {
	.name  = "Crash kernel",
	.flags = IORESOURCE_BUSY | IORESOURCE_SYSTEM_RAM,
	.desc  = IORES_DESC_CRASH_KERNEL
};
struct resource crashk_low_res = { /* 同上，另一个名字 */ };
```

两个而不是一个，是因为**高端内存（4G 以上）不可用于 DMA**。`crashk_res` 放主区域，`crashk_low_res` 专门留一块 4G 以下的低内存给设备做 DMA 搬运。

`/proc/iomem` 里能看到名为 "Crash kernel" 的两段，这个 resource 结构就是它对应的内核对象。

### crashkernel 参数的完整语法

解析入口是 `parse_crashkernel()`，源码在 `kernel/crash_reserve.c`。语法分两支，由命令行里**有没有冒号**决定（`__parse_crashkernel()`）：

| 语法 | 例子 | 含义 |
| :-- | :-- | :-- |
| 简单式 | `crashkernel=512M` | 只要大小，位置由内核自动搜 |
| 简单式带偏移 | `crashkernel=512M@16M` | 明确指定起始物理地址 |
| 区间式 | `crashkernel=512M-2G:64M,2G-:128M` | 按系统总内存分段给不同大小 |
| 高端 | `crashkernel=512M,high` | 优先放在 4G 以上 |
| 低端 | `crashkernel=512M,low` / `crashkernel=0,low` | 强制 4G 以下；`0,low` 表示禁用低内存分配 |
| CMA | `crashkernel=512M,cma` | 额外为崩溃内核声明 CMA 区域 |

两个从代码里读出来、**文档往往没写的细节**：

1. **多个 `crashkernel=` 时取最后一个**。`get_last_crashkernel()` 循环 `strstr()` 找出所有匹配项，只有最后一个生效——被 grub 追加了参数的场景下这很容易踩坑。
2. **带后缀的项不参与"简单式"匹配**。`get_last_crashkernel()` 在无后缀查找时会跳过所有已知后缀结尾的项，所以 `crashkernel=512M,high` 不会顶掉一个纯 `crashkernel=` 的解析。

### 三个关键常量

来自 `include/linux/crash_reserve.h`：

```c
#define DEFAULT_CRASH_KERNEL_LOW_SIZE	(128UL << 20)   /* 128 MiB */
#define CRASH_ALIGN			SZ_2M            /* 2 MiB 对齐 */
#define CRASH_ADDR_LOW_MAX		SZ_4G            /* 4 GiB */
```

- `CRASH_ALIGN` 是 2 MiB —— 因为普通页不足以描述这段预留，必须 2M 对齐才能用大页。
- `CRASH_ADDR_LOW_MAX` = 4 GiB 就是"DMA 无法触及"的硬件边界，也解释了 `crashk_low_res` 的存在意义。
- ⚠️ **`DEFAULT_CRASH_KERNEL_LOW_SIZE` 在 v7.2 是 128 MiB**。内核文档（`Documentation/admin-guide/kdump/kdump.rst`）写的是 "at least 256M"，这是**过时**的——`reserve_crashkernel_generic()` 在自动降级到高端内存时会用这个常量作为低内存预留量，以源码为准。

### 自动选址的降级逻辑

`reserve_crashkernel_generic()` 用 `memblock_phys_alloc_range()` 搜地址，两轮降级值得记：

- `crashkernel=size` 先搜低内存（< 4G）；失败则改搜高端，并把 `crash_low_size` 兜底为 128 MiB 重试。
- `crashkernel=size,high` 先搜高端；失败则退回低内存。
- 显式给了 `@offset` 的 `fixed_base` 情况**不降级**，直接打印 `crashkernel reservation failed - memory is in use.` 返回。

预留成功后立刻从线性映射摘除并通知 kmemleak：

```c
	kmemleak_ignore_phys(crash_base);
	if (crashk_low_res.end)
		kmemleak_ignore_phys(crashk_low_res.start);
```

`kmemleak_ignore_phys()` 这一步不做好，kmemleak 会持续扫描这块已保留但不可读的内存，误报大量泄漏。

### CMA 版本的 v7.2 新形态

`reserve_crashkernel_cma()` 在 v7.2 里支持**分块降级**：声明 CMA 失败时把请求大小**折半重试**（`request_size = roundup(request_size / 2, PAGE_SIZE)`），最多积累 `CRASHKERNEL_CMA_RANGES_MAX`（4）个区间。原因是转储内核只需要一个连续大区，但系统可能已经被别的 CMA 占用切碎了。

## kexec 装载崩溃内核

`kexec_load()` 的用户态入口最终进 `do_kexec_load()`（`kernel/kexec.c`）。崩溃内核与普通 kexec 共用同一段代码，靠 `KEXEC_ON_CRASH` 标志区分，加载到不同的全局槽位：

```c
#ifdef CONFIG_CRASH_DUMP
	if (flags & KEXEC_ON_CRASH) {
		dest_image = &kexec_crash_image;
		if (kexec_crash_image)
			arch_kexec_unprotect_crashkres();
	} else
#endif
		dest_image = &kexec_image;
```

`kimage_alloc_init()` 里对崩溃内核有两处专属处理：

```c
	if (kexec_on_panic) {
		/* Verify we have a valid entry point */
		if ((entry < phys_to_boot_phys(crashk_res.start)) ||
		    (entry > phys_to_boot_phys(crashk_res.end)))
			return -EADDRNOTAVAIL;
	}
	/* ... */
	if (kexec_on_panic) {
		/* Enable special crash kernel control page alloc policy. */
		image->control_page = crashk_res.start;
		image->type = KEXEC_TYPE_CRASH;
	}
```

**入口地址必须落在 `crashk_res` 区间内**，否则直接 `-EADDRNOTAVAIL`。这是一道硬校验，防止把转储入口指到别处。

还有一处顺序上的讲究：

```c
	/*
	 * Some architecture(like S390) may touch the crash memory before
	 * machine_kexec_prepare(), we must copy vmcoreinfo data after it.
	 */
	ret = kimage_crash_copy_vmcoreinfo(image);
```

**vmcoreinfo 必须在 `machine_kexec_prepare()` 之后拷贝**。VMCOREINFO 是转储文件里描述"哪些内存段包含哪些内核变量"的那段元数据，gdb 和 crash 靠它定位结构体。

## __crash_kexec：跳过去

```c
void __noclone __crash_kexec(struct pt_regs *regs)
{
	if (kexec_trylock()) {
		if (kexec_crash_image) {
			struct pt_regs fixed_regs;

			crash_setup_regs(&fixed_regs, regs);
			crash_save_vmcoreinfo();
			machine_crash_shutdown(&fixed_regs);
			crash_cma_clear_pending_dma();
			machine_kexec(kexec_crash_image);
		}
		kexec_unlock();
	}
}
```

三件事按固定顺序：整理寄存器上下文 → 保存 vmcoreinfo → 架构关机 → 跳转。最后 `machine_kexec()` 永不返回。

**为什么要 `kexec_trylock()`** 而不用普通锁？注释说明了：崩溃时可能正有另一个 CPU 在执行 `sys_kexec_load()` 替换崩溃内核，加锁就死锁了。这个自旋锁在 panic 场景下"拿不到就直接放弃"，是典型的"崩溃路径不可阻塞"设计。

`STACK_FRAME_NON_STANDARD(__crash_kexec)` 标记它的栈帧不符合编译器约定 —— 汇编跳转进来时栈布局与 C 函数不同。

`crash_cma_clear_pending_dma()` 也很关键：如果用 CMA 承载崩溃内核，崩溃前可能有正在进行的 DMA 往那块内存写。它 `mdelay(CMA_DMA_TIMEOUT_SEC * 1000)` 硬等一小段时间。

## ELF core header：把内存描述成文件

转储内核实现在 ELF 格式。构造逻辑在 `crash_prepare_elf64_headers()`，用 `walk_system_ram_res()` 遍历所有 System RAM 区间，为每段生成一个 `PT_LOAD` 段。源码里一段注释解释了段数为何要留余量：

```c
	/*
	 * Exclusion of crash region, crashk_low_res and/or crashk_cma_ranges
	 * may cause range splits. So add extra slots here.
	 * ...
	 * But in order to lest the low 1M could be changed in the future,
	 */
```

**每排除一个区间都可能把一个连续 RAM 段切成两段**，所以段数不等于 RAM 区间数。

启动参数 `elfcorehdr=` 把 ELF 头的物理地址传给第二内核：

> All of the necessary information about the system kernel's core image is encoded in the ELF format, and stored in a reserved area of memory before a crash. The physical address of the start of the ELF header is passed to the dump-capture kernel through the `elfcorehdr=` boot parameter.

语法是 `elfcorehdr=[size[KMG]@]offset[KMG]`，`size` 可选，`offset` 必填。x86 特有的一条硬约束：低端 1 MiB 必须整体保留 —— 固件实际只用 640 KiB，但整块留出可以省掉后续所有处理，kdump 内核起来后能直接把这 1 MiB 当普通 RAM 用。

`crash_save_cpu()` 是各 CPU 寄存器状态的落盘点，它构造的是 ELF 的 `PT_NOTE` 段：

```c
void crash_save_cpu(struct pt_regs *regs, int cpu)
{
	struct elf_prstatus prstatus;
	u32 *buf;
	/* ... */
}
```

`struct elf_prstatus` 是 ELF 规范里表示"一个进程/线程的寄存器快照"的标准结构。`crash_notes_memory_init()`（`subsys_initcall`）在启动早期把这块内存标为保留，pstore/ ramoops 那套"崩溃后仍可读"的机制与它同源。

## 转储捕获内核：/proc/vmcore

第二内核启动后，旧内核的内存通过 **`/proc/vmcore`** 暴露为一个可读文件。`fs/proc/vmcore.c` 有 1700 余行，核心是 `vmcore_read()` —— 它遍历 ELF 段表，对每个 `PT_LOAD` 段用 `copy_to_user()` 把物理页映射进用户空间。

这带来一个重要后果：**读 vmcore 的开销与被转储的内存量成正比**，所以大内存机器上应该用 `makedumpfile` 之类的工具做过滤/压缩（`-d 31` 表示只导出内核数据段），而不是 `cp /proc/vmcore`。

## pstore：廉价但完整的日志

pstore 是 panic 前就把日志写进持久存储的机制，代码在 `fs/pstore/`。它注册为一个文件系统，重启后从 `/sys/fs/pstore` 读回，文件名形如 `dmesg-ramoops-0`、`console-ramoops-0`。

### 类型枚举

`include/linux/pstore.h` 里的类型表（源码注释明确要求数组顺序与枚举一致）：

```c
enum pstore_type_id {
	PSTORE_TYPE_DMESG	= 0,   /* dmesg */
	PSTORE_TYPE_MCE		= 1,   /* mce */
	PSTORE_TYPE_CONSOLE	= 2,   /* console */
	PSTORE_TYPE_FTRACE	= 3,   /* ftrace */
	PSTORE_TYPE_PPC_RTAS	= 4,   /* rtas */
	PSTORE_TYPE_PPC_OF	= 5,   /* powerpc-ofw */
	PSTORE_TYPE_PPC_COMMON	= 6,   /* powerpc-common */
	PSTORE_TYPE_PMSG	= 7,   /* pmsg */
	PSTORE_TYPE_PPC_OPAL	= 8,   /* powerpc-opal */
};
```

Dmesg（内核日志）、Console（全量控制台，含 panic 前的普通输出）、Ftrace（函数调用轨迹）、MCE（机器检查异常）、Pmsg（用户态消息，通过 `/dev/pmsg0`）是实际会用到的几个；后面几个是 PowerPC 专用。

后端通过 `struct pstore_info` 注册，能力标志只有四位：

```c
#define PSTORE_FLAGS_DMESG	BIT(0)
#define PSTORE_FLAGS_CONSOLE	BIT(1)
#define PSTORE_FLAGS_FTRACE	BIT(2)
#define PSTORE_FLAGS_PMSG	BIT(3)
```

### update_ms：一个"默认关闭"的运行时行为

`fs/pstore/platform.c` 里有个容易误解的参数：

```c
static int pstore_update_ms = -1;
module_param_named(update_ms, pstore_update_ms, int, 0600);
MODULE_PARM_DESC(update_ms, "milliseconds before pstore updates its content "
		 "(default is -1, which means runtime updates are disabled; "
		 "enabling this option may not be safe; it may lead to further "
		 "corruption on Oopses)");
```

默认 **-1，即运行期不更新内容**。设计上 oops 记录要延迟一会儿才出现在 `/sys/fs/pstore` 里 —— 注释说得很明白：先看系统是否还活着，"enabling this option may not be safe; it may lead to further corruption on Oopses"。排查 oops 时如果发现 `/sys/fs/pstore` 空了，先查这个参数。

`pstore_init()` 挂在 `late_initcall`，也就是在几乎所有子系统就绪之后才注册。

### 压缩

`PSTORE_COMPRESS` 在 v7.2 **默认 y**（Kconfig 里 `default y`），用 zlib 的 deflate：

```c
static int pstore_compress(const void *in, void *out,
			   unsigned int inlen, unsigned int outlen)
{
	struct z_stream_s zstream = { ... };
	/* ... */
	ret = zlib_deflateInit2(&zstream, Z_DEFAULT_COMPRESSION, Z_DEFLATED,
				-MAX_WBITS, DEF_MEM_LEVEL, Z_DEFAULT_STRATEGY);
	/* ... */
	return zstream.total_out;
}
```

`-MAX_WBITS` 是**裸 deflate 流**（无 zlib/gzip 头尾），记录里靠 `pstore_record.compressed` 布尔位标记是否压缩。默认压缩的理由写在 Kconfig 里：降低 panic 元数据记录时发生二次 oops 的风险。

`PSTORE_DEFAULT_KMSG_BYTES` 默认 **10240**（10 KiB），且 Kconfig 明确说 "Can be enlarged if needed, not recommended to shrink it"。

### 后端：ramoops

最常用的后端是 ramoops（模块名 `ramoops.ko`，因为历史原因模块名与 pstore 不同），`fs/pstore/ram.c` 有 800 余行。参数表：

| 参数 | 默认 | 说明 |
| :-- | :-- | :-- |
| `mem_address` | — | 持久区起始物理地址 |
| `mem_size` | — | 大小，**会向下取整到 2 的幂** |
| `mem_type` | 0 | 0=pgprot_writecombine，1=pgprot_noncached，2=普通内存（全缓存） |
| `record_size` | MIN_MEM_SIZE | 每条记录大小，**同样向下取整到 2 的幂** |
| `console_size` / `pmsg_size` / `ftrace_size` | MIN_MEM_SIZE | 三类缓冲区大小 |
| `max_reason` | — | 按 `kmsg_dump_reason` 过滤 |
| `ecc` | — | 软件 ECC 纠错 |
| `dump_oops` | — | 是否记录 oops |

为什么 `mem_type` 默认是 0（write-combining）而不是普通内存？官方文档解释得很清楚：

> This is because pstore depends on atomic operations. At least on ARM, pgprot_noncached causes the memory to be mapped strongly ordered, and atomic operations on strongly ordered memory are implementation defined, and won't work on many ARMs such as omaps.

**pstore 依赖原子操作**，而强序内存上的原子操作在很多 ARM 上是实现定义的、根本不工作。mem_type=2 开启全缓存能提升性能，但会牺牲原子性。

`max_reason` 的取值来自 `enum kmsg_dump_reason`（`include/linux/kmsg_dump.h`）：

```c
enum kmsg_dump_reason {
	KMSG_DUMP_UNDEF,      /* 0 */
	KMSG_DUMP_PANIC,      /* 1 */
	KMSG_DUMP_OOPS,       /* 2 */
	KMSG_DUMP_EMERG,      /* 3 */
	KMSG_DUMP_SHUTDOWN,   /* 4 */
	KMSG_DUMP_MAX
};
```

所以只要 panic 设 1、panic+oops 设 2。该枚举头部还有一条关键注释：

> Keep this list arranged in rough order of priority. Anything listed after KMSG_DUMP_OOPS will not be logged by default unless `printk.always_kmsg_dump` is passed to the kernel.

即 **`KMSG_DUMP_EMERG` / `SHUTDOWN` 默认不记录**，需要显式 `printk.always_kmsg_dump`。`max_reason=0` 时则由这个参数决定。

### 另一个后端：pstore/blk

`pstore_blk` 把记录写到块设备（如 U 盘或 SATA 盘），参数用 `pstore_blk.<backend>.<option>=` 形式（`blk_size`、`blkdev`、`erasesize`、`cache_size` 等），设备上要有 pstore 专用的分区。适合服务器上不想占用 precious 保留内存、且能容忍"写盘在崩溃时可能不完整"的场景。

`fs/pstore/Makefile` 里的后端清单：`ramoops`（`ram.o ram_core.o`）、`pstore_zone`、`pstore_blk`、以及 `PSTORE_FTRACE` 与 `PSTORE_PMSG` 两个附加能力。

## 进程级 core dump

panic 是整机级事件，而单个进程的异常退出是进程级事件。后者由 `core_pattern` / `core_pipe_limit` 管控，走的是另一条路 —— 但它们常被混为一谈，需要分清。

- `core_pattern` 的默认值是 `core`，即在当前工作目录写 core 文件；支持 `|/path/to/handler` 把 core 管道给用户态程序（systemd-coredump 就是这么接的）。
- `coredump_filter` 控制导出哪些内存段（匿名私有、file-backed、共享、swap、巨大页……），默认值经过逐版本调整，**要看当前内核的 `Documentation/admin-guide/sysctl/kernel.rst`**，不要凭印象。
- `kptr_restrict` 决定 core 里是否保留内核指针：0 全留，1 隐去非特权用户（默认行为），2 全部隐去。

这一块与 KB 里已有的 [coredump](https://stackoverflow.com/questions/793859) 主题相关，但机制在用户态工具侧（`gcore`、systemd-coredump、gdb），不在内核的崩溃转储链里，因此不展开。

## 观测与排障

| 目的 | 手段 |
| :-- | :-- |
| 崩溃后读最后日志 | `ls /sys/fs/pstore/` + `cat /sys/fs/pstore/dmesg-ramoops-0` |
| 确认崩溃内核是否已加载 | `cat /sys/kernel/kexec_crash_loaded`（存在即加载） |
| 确认预留区大小 | `cat /sys/kernel/kexec_crash_size`；或看 `/proc/iomem` 的 "Crash kernel" |
| 看当前 panic 策略 | `/proc/sys/kernel/panic_on_oops`、`/proc/sys/kernel/panic_timeout` |
| 看 pstore 是否运行 | `mount \| grep pstore`；`/sys/fs/pstore/` 是否有内容 |
| 分析转储文件 | `gdb vmlinux vmcore`、`crash`、`makedumpfile -d 31` |

`kexec_should_crash()` 说明了什么情况下 oops 会升级成 panic（这决定你能否拿到 vmcore）：

```c
	if (in_interrupt() || !p->pid || is_global_init(p) || panic_on_oops)
		return 1;
```

在中断上下文出错、init 进程出错、或 `panic_on_oops=1` 时直接转 panic。**其余 oops 不会自动 panic**，如果内核没挂但行为异常，想拿转储需要手动 `echo 1 > /proc/sys/kernel/panic_on_oops` 或直接 `sysrq` 触发。

## 与其它子系统的接缝

- **启动链**：崩溃转储是启动链的**反向**过程 —— 绕过固件与 bootloader，直接由内核跳进第二内核。与 [Start](/docs/CS/OS/Linux/boot/Start.md) 讲的正常引导恰好相反，`machine_kexec()` 之后没有 `setup.bin` 的实模式代码，也没有 [U-Boot](/docs/CS/OS/Linux/boot/U-Boot.md) 那套流程。
- **内存管理**：`crashk_res` 从线性映射摘除、避开 buddy 分配，本质是 [pm](/docs/CS/OS/Linux/mm/pm.md) 里 memblock 阶段的一次特殊保留；CMA 版本则与 `mm/gup.md` 里记的 CMA 机制同源。
- **设备模型**：pstore 是个文件系统（`fs/pstore/`），ramoops 通过 `platform_device` 注册 —— 走的是 [dev/device.md](/docs/CS/OS/Linux/dev/device.md) 那套 model/probe 绑定。
- **调试工具**：`crash`、`gdb` 解析 vmcore 的前提是符号表与 vmlinux 匹配，调试环境搭建见 [Debug](/docs/CS/OS/Linux/Tools/Debug.md)。

## 排障速查

```shell
# 崩溃内核是否已装载
cat /sys/kernel/kexec_crash_loaded
ls -l /sys/kernel/kexec_crash_size

# pstore 内容（重启后）
ls -la /sys/fs/pstore/
cat /sys/fs/pstore/dmesg-ramoops-0

# panic 行为策略
cat /proc/sys/kernel/panic_on_oops      # oops 是否升级为 panic
cat /proc/sys/kernel/panic_timeout      # 重启前等待秒数，0=不重启
cat /proc/sys/kernel/panic_on_warn      # WARN 是否 panic

# 预留区（dmesg 里也有）
grep -i "crashkernel\|reserving" /proc/iomem
dmesg | grep -i crashkernel

# 进程级 core
cat /proc/sys/kernel/core_pattern
cat /proc/sys/kernel/coredump_filter
ulimit -c          # shell 的 core 大小上限，常见为 0/ulimit
```

## Links

- [boot 知识地图](/docs/CS/OS/Linux/boot/README.md)
- [内核启动与内存初始化](/docs/CS/OS/Linux/mm/memory.md)
- [物理内存 pm](/docs/CS/OS/Linux/mm/pm.md)
- [调试 Debug](/docs/CS/OS/Linux/Tools/Debug.md)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)

## References

1. [Linux Kernel Documentation — kdump](https://docs.kernel.org/admin-guide/kdump/kdump.html)
2. [Linux Kernel Documentation — ramoops](https://docs.kernel.org/admin-guide/ramoops.html)
3. [Linux Kernel Documentation — pstore-blk](https://docs.kernel.org/admin-guide/pstore-blk.html)
4. [Linux Kernel Documentation — sysctl kernel](https://docs.kernel.org/admin-guide/sysctl/kernel.html)
5. [Linux Kernel — kexec](https://docs.kernel.org/admin-guide/kexec.html)
