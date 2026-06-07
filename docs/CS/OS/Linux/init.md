## 简介

与其他任何程序一样，内核在执行正常任务之前要经历加载和初始化阶段。
虽然在普通应用程序的情况下，这个阶段并不是特别有趣，但内核作为系统核心层必须解决许多特定的问题。
启动阶段分为以下三个部分：
- 将内核加载到 RAM 并创建最小运行时环境。
- 跳转到（平台相关的）内核机器代码，并用汇编语言对基本系统功能进行系统特定的初始化。
- 跳转到（平台无关的）用 C 编写的初始化代码部分，完成所有子系统的初始化，随后切换到正常运行。

通常，引导加载程序负责第一阶段。其任务在很大程度上取决于特定架构的要求。
由于理解第一阶段的全部细节需要深入了解特定的处理器特性和问题，因此架构特定的参考手册是一个很好的信息来源。
第二阶段也非常依赖硬件。

在第三个与系统无关的阶段，内核已驻留在内存中，并且（在某些架构上）处理器已从引导模式切换到内核随后运行所需的执行模式。
在 IA-32 机器上，需要将处理器从启动时立即激活的 8086 模拟模式切换到保护模式，以使系统具备 32 位能力。
其他架构也需要设置工作——例如，通常需要显式启用分页，并且核心系统组件必须置于确定的初始状态以便工作开始。
所有这些任务都必须用汇编语言编写，因此它们不是内核中最吸引人的部分。

专注于启动的第三阶段可以省去许多架构特定的琐事，并且还有一个额外的好处：
一般来说，后续的操作序列与内核运行的具体平台无关。

当计算机启动时，BIOS 执行上电自检（POST）以及初始设备发现和初始化，因为操作系统的引导过程可能依赖于对磁盘、屏幕、键盘等的访问。
接下来，引导磁盘的第一个扇区，即 MBR（主引导记录），被读入固定的内存位置并执行。
该扇区包含一个小型（512 字节）程序，该程序从引导设备（如 SATA 或 SCSI 磁盘）加载一个名为 boot 的独立程序。
boot 程序首先将其自身复制到固定的高内存地址，以便为操作系统释放低内存。

一旦移动完成，boot 读取引导设备的根目录。
为此，它必须理解文件系统和目录格式，一些引导加载程序（如 GRUB）确实具备此能力。
其他流行的引导加载程序（如 Intel 的 LILO）不依赖于任何特定的文件系统。
相反，它们需要块映射和描述物理扇区、磁头和柱面的低级地址来找到要加载的相关扇区。

然后 boot 读入操作系统内核并跳转到它。此时，它已完成其工作，内核正在运行。

内核启动代码是用汇编语言编写的，并且高度依赖于机器。


> 内核启动中输出的信息可以通过 `dmesg` 命令查看

## boot


```c
// arch/x86/boot/main.c
void main(void)
{
	init_default_io_ops();

	/* First, copy the boot header into the "zeropage" */
	copy_boot_params();

	/* Initialize the early-boot console */
	console_init();
	if (cmdline_find_option_bool("debug"))
		puts("early console in setup code\n");

	/* End of heap check */
	init_heap();

	/* Make sure we have all the proper CPU support */
	if (validate_cpu()) {
		puts("Unable to boot - please use a kernel appropriate for your CPU.\n");
		die();
	}

	/* Tell the BIOS what CPU mode we intend to run in */
	set_bios_mode();

	/* Detect memory layout */
	detect_memory();

	/* Set keyboard repeat rate (why?) and query the lock flags */
	keyboard_init();

	/* Query Intel SpeedStep (IST) information */
	query_ist();

	/* Query APM information */
#if defined(CONFIG_APM) || defined(CONFIG_APM_MODULE)
	query_apm_bios();
#endif

	/* Query EDD information */
#if defined(CONFIG_EDD) || defined(CONFIG_EDD_MODULE)
	query_edd();
#endif

	/* Set the video mode */
	set_video();

	/* Do the last things and invoke protected mode */
	go_to_protected_mode();
}
```


## Init

```c
// arch/x86/inculde/asm/setup.h

#ifdef __i386__

asmlinkage void __init i386_start_kernel(void);

#else
asmlinkage void __init x86_64_start_kernel(char *real_mode);
```
i386_start_kernel
```c
asmlinkage __visible void __init i386_start_kernel(void)
{
	/* Make sure IDT is set up before any exception happens */
	idt_setup_early_handler();

	cr4_init_shadow();

	sanitize_boot_params(&boot_params);

	x86_early_init_platform_quirks();

	/* Call the subarch specific early setup function */
	switch (boot_params.hdr.hardware_subarch) {
	case X86_SUBARCH_INTEL_MID:
		x86_intel_mid_early_setup();
		break;
	case X86_SUBARCH_CE4100:
		x86_ce4100_early_setup();
		break;
	default:
		i386_default_early_setup();
		break;
	}

	start_kernel();
}
```

扫描 EFI 嵌入式固件的代码在 start_kernel() 末尾附近运行，就在调用 rest_init() 之前。
对于使用 subsys_initcall() 注册自身的普通驱动程序和子系统，这无关紧要。
这意味着早期运行的代码无法使用 EFI 嵌入式固件。

## start_kernel

`start_kernel` 充当调度函数，执行与平台无关和平台相关的任务，所有这些任务都是用 C 实现的。
它负责调用几乎所有内核子系统的高级初始化例程。
用户可以通过该函数最先做的事情之一是在屏幕上显示 Linux 横幅来识别内核何时进入此初始化阶段。
（该消息在启动操作早期生成，但在控制台系统初始化之前不会显示在屏幕上。在此期间它被缓冲。）

```c
asmlinkage __visible void __init __no_sanitize_address start_kernel(void)
{
       char *command_line;
       char *after_dashes;
```

[init task](/docs/CS/OS/Linux/proc/process.md?id=init-task)
```c
       set_task_stack_end_magic(&init_task);
       smp_setup_processor_id();
       debug_objects_early_init();

       cgroup_init_early();

       local_irq_disable();
       early_boot_irqs_disabled = true;

       /*
        * Interrupts are still disabled. Do necessary setups, then enable them.
        */
       boot_cpu_init();
       page_address_init();
       pr_notice("%s", linux_banner);
       early_security_init();
       setup_arch(&command_line);
       setup_boot_config();
       setup_command_line(command_line);
       setup_nr_cpu_ids();
       setup_per_cpu_areas();
       smp_prepare_boot_cpu();        /* arch-specific boot-cpu hooks */
       boot_cpu_hotplug_init();

       build_all_zonelists(NULL);
       page_alloc_init();

       pr_notice("Kernel command line: %s\n", saved_command_line);
       /* parameters may set static keys */
       jump_label_init();
       parse_early_param();
       after_dashes = parse_args("Booting kernel",
                              static_command_line, __start___param,
                              __stop___param - __start___param,
                              -1, -1, NULL, &unknown_bootoption);
       if (!IS_ERR_OR_NULL(after_dashes))
              parse_args("Setting init args", after_dashes, NULL, 0, -1, -1,
                        NULL, set_init_arg);
       if (extra_init_args)
              parse_args("Setting extra init args", extra_init_args,
                        NULL, 0, -1, -1, NULL, set_init_arg);

       /*
        * These use large bootmem allocations and must precede
        * kmem_cache_init()
        */
       setup_log_buf(0);
       vfs_caches_init_early();
       sort_main_extable();
```       

```c       
       trap_init();
```
[Init memory](/docs/CS/OS/Linux/memory.md?id=init)
```c
       mm_init();

       ftrace_init();

       /* trace_printk can be enabled here */
       early_trace_init();
```
在任何中断（如定时器中断）启动之前设置调度器。完整的拓扑设置在 smp_init() 时进行——但与此同时，我们仍然有一个正常工作的调度器。

```c
       sched_init();
       /*
        * Disable preemption - early bootup scheduling is extremely
        * fragile until we cpu_idle() for the first time.
        */
       preempt_disable();
       if (WARN(!irqs_disabled(),
               "Interrupts were enabled *very* early, fixing it\n"))
              local_irq_disable();
       radix_tree_init();

       /*
        * Set up housekeeping before setting up workqueues to allow the unbound
        * workqueue to take non-housekeeping into account.
        */
       housekeeping_init();
```
允许早期创建工作队列和排队/取消工作项。工作项的执行依赖于内核线程，并在 workqueue_init() 之后开始。
```c
       workqueue_init_early();

       rcu_init();

       /* Trace events are available after this */
       trace_init();

       if (initcall_debug)
              initcall_debug_enable();

       context_tracking_init();
       /* init some links before init_ISA_irqs() */
       early_irq_init();
```
[Init IRQ](/docs/CS/OS/Linux/Interrupt.md?id=init_IRQ)
```c
       init_IRQ();
```

```c       
       tick_init();
```

```c       
       rcu_init_nohz();
```
[Init timers](/docs/CS/OS/Linux/timer.md?id=init_timers)
```c
       init_timers();
```

```c
       hrtimers_init();
```
[init softirq](/docs/CS/OS/Linux/Interrupt.md?id=init_softirq)
```c
       softirq_init();
       timekeeping_init();
       kfence_init();

       /*
        * For best initial stack canary entropy, prepare it after:
        * - setup_arch() for any UEFI RNG entropy and boot cmdline access
        * - timekeeping_init() for ktime entropy used in rand_initialize()
        * - rand_initialize() to get any arch-specific entropy like RDRAND
        * - add_latent_entropy() to get any latent entropy
        * - adding command line entropy
        */
       rand_initialize();
       add_latent_entropy();
       add_device_randomness(command_line, strlen(command_line));
       boot_init_stack_canary();

       time_init();
       perf_event_init();
       profile_init();
       call_function_init();
       WARN(!irqs_disabled(), "Interrupts were enabled early\n");

       early_boot_irqs_disabled = false;
       local_irq_enable();
```

```c
       kmem_cache_init_late();

       /*
        * HACK ALERT! This is early. We're enabling the console before
        * we've done PCI setups etc, and console_init() must be aware of
        * this. But we do want output early, in case something goes wrong.
        */
       console_init();
       if (panic_later)
              panic("Too many boot %s vars at `%s'", panic_later,
                    panic_param);

       lockdep_init();

       /*
        * Need to run this when irqs are enabled, because it wants
        * to self-test [hard/soft]-irqs on/off lock inversion bugs
        * too:
        */
       locking_selftest();

       /*
        * This needs to be called before any devices perform DMA
        * operations that might use the SWIOTLB bounce buffers. It will
        * mark the bounce buffers as decrypted so that their usage will
        * not cause "plain-text" data to be decrypted when accessed.
        */
       mem_encrypt_init();

    #ifdef CONFIG_BLK_DEV_INITRD
       if (initrd_start && !initrd_below_start_ok &&
           page_to_pfn(virt_to_page((void *)initrd_start)) < min_low_pfn) {
              pr_crit("initrd overwritten (0x%08lx < 0x%08lx) - disabling it.\n",
                  page_to_pfn(virt_to_page((void *)initrd_start)),
                  min_low_pfn);
              initrd_start = 0;
       }
    #endif
       setup_per_cpu_pageset();
       numa_policy_init();
       acpi_early_init();
       if (late_time_init)
              late_time_init();
       sched_clock_init();
       calibrate_delay();
       pid_idr_init();
       anon_vma_init();
    #ifdef CONFIG_X86
       if (efi_enabled(EFI_RUNTIME_SERVICES))
              efi_enter_virtual_mode();
    #endif
       thread_stack_cache_init();
       cred_init();
       fork_init();
       proc_caches_init();
       uts_ns_init();
       key_init();
       security_init();
       dbg_late_init();
       vfs_caches_init();
       pagecache_init();
       signals_init();
       seq_file_init();
       proc_root_init();
       nsfs_init();
       cpuset_init();
       cgroup_init();
       taskstats_init_early();
       delayacct_init();

       poking_init();
       check_bugs();

       acpi_subsystem_init();
       arch_post_acpi_subsys_init();
       kcsan_init();
```


call rest_init -> [kernel_init](/docs/CS/OS/Linux/init.md?id=kernel_init)
```c
       /* Do the rest non-__init'ed, we're now alive */
       arch_call_rest_init();

```

```c
       prevent_tail_call_optimization();
}
```





### rest_init


rest_init函数的重要功能就是建立了两个Linux  [kernel_thread](/docs/CS/OS/Linux/proc/process.md?id=kernel_clone):  `kernel_init`(用户态为 init 进程, 所有用户态进程的祖先) and `kthreadd`(负责所有内核态线程的调度和管理 所有内核态线程的祖先)


```c
noinline void __ref rest_init(void)
{
       struct task_struct *tsk;
       int pid;

       rcu_scheduler_starting();
```
我们需要先生成 init 以便它获得 pid 1，然而 init 任务最终会想要创建内核线程，如果我们在此之前调度它，将会 OOPS。
```c
       pid = kernel_thread(kernel_init, NULL, CLONE_FS);
```
Pin init on the boot CPU. Task migration is not properly working until sched_init_smp() has been run. It will set the allowed CPUs for init to the non isolated CPUs.

```c       
       rcu_read_lock();
       tsk = find_task_by_pid_ns(pid, &init_pid_ns);
       set_cpus_allowed_ptr(tsk, cpumask_of(smp_processor_id()));
       rcu_read_unlock();

       numa_default_policy();
       pid = kernel_thread(kthreadd, NULL, CLONE_FS | CLONE_FILES);
       rcu_read_lock();
       kthreadd_task = find_task_by_pid_ns(pid, &init_pid_ns);
       rcu_read_unlock();

       /*
        * Enable might_sleep() and smp_processor_id() checks.
        * They cannot be enabled earlier because with CONFIG_PREEMPTION=y
        * kernel_thread() would trigger might_sleep() splats. With
        * CONFIG_PREEMPT_VOLUNTARY=y the init task might have scheduled
        * already, but it's stuck on the kthreadd_done completion.
        */
       system_state = SYSTEM_SCHEDULING;

       complete(&kthreadd_done);

       /*
        * The boot idle thread must execute schedule()
        * at least once to get things moving:
        */
       schedule_preempt_disabled();
       /* Call into cpu_idle with preempt disabled */
       cpu_startup_entry(CPUHP_ONLINE);
}
```




#### kernel_init

Linux内核的第一个用户态进程是在kernel_init线程建立的

```c
// init/main.c
static int __ref kernel_init(void *unused)
{
	int ret;

	kernel_init_freeable();
	/* need to finish all async __init code before freeing the memory */
	async_synchronize_full();
	kprobe_free_init_mem();
	ftrace_free_init_mem();
	kgdb_free_init_mem();
	free_initmem();
	mark_readonly();

	/*
	 * Kernel mappings are now finalized - update the userspace page-table to finalize PTI.
	 */
	pti_finalize();

	system_state = SYSTEM_RUNNING;
	numa_default_policy();

	rcu_end_inkernel_boot();

	do_sysctl_args();

	if (ramdisk_execute_command) {
		ret = run_init_process(ramdisk_execute_command);
		if (!ret)
			return 0;
		pr_err("Failed to execute %s (error %d)\n",
		       ramdisk_execute_command, ret);
	}

	/*
	 * We try each of these until one succeeds.
	 *
	 * The Bourne shell can be used instead of init if we are
	 * trying to recover a really broken machine.
	 */
	if (execute_command) {
		ret = run_init_process(execute_command);
		if (!ret)
			return 0;
		panic("Requested init %s failed (error %d).",
		      execute_command, ret);
	}

	if (CONFIG_DEFAULT_INIT[0] != '\0') {
		ret = run_init_process(CONFIG_DEFAULT_INIT);
		if (ret)
			pr_err("Default init %s failed (error %d)\n",
			       CONFIG_DEFAULT_INIT, ret);
		else
			return 0;
	}

	if (!try_to_run_init_process("/sbin/init") ||
	    !try_to_run_init_process("/etc/init") ||
	    !try_to_run_init_process("/bin/init") ||
	    !try_to_run_init_process("/bin/sh"))
		return 0;

	panic("No working init found.  Try passing init= option to kernel. "
	      "See Linux Documentation/admin-guide/init.rst for guidance.");
}

```

kernel_init -> kernel_init_freeable -> do_basic_setup -> do_initcalls -> do_initcall_level -> for do_one_initcall -> initcall 

```c
// include/linux/init.h
#define core_initcall(fn)		__define_initcall(fn, 1)
```


## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)