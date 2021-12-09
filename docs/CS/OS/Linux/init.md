## Introduction



## Init


```c

/*
 * The following fragment of code is executed with the MMU enabled.
 *
 *   x0 = __PHYS_OFFSET
 */
SYM_FUNC_START_LOCAL(__primary_switched)
	adr_l	x4, init_task
	init_cpu_task x4, x5, x6

	adr_l	x8, vectors			// load VBAR_EL1 with virtual
	msr	vbar_el1, x8			// vector table address
	isb

	stp	x29, x30, [sp, #-16]!
	mov	x29, sp

	str_l	x21, __fdt_pointer, x5		// Save FDT pointer

	ldr_l	x4, kimage_vaddr		// Save the offset between
	sub	x4, x4, x0			// the kernel virtual and
	str_l	x4, kimage_voffset, x5		// physical mappings

	// Clear BSS
	adr_l	x0, __bss_start
	mov	x1, xzr
	adr_l	x2, __bss_stop
	sub	x2, x2, x0
	bl	__pi_memset
	dsb	ishst				// Make zero page visible to PTW

#if defined(CONFIG_KASAN_GENERIC) || defined(CONFIG_KASAN_SW_TAGS)
	bl	kasan_early_init
#endif
	mov	x0, x21				// pass FDT address in x0
	bl	early_fdt_map			// Try mapping the FDT early
	bl	init_feature_override		// Parse cpu feature overrides
#ifdef CONFIG_RANDOMIZE_BASE
	tst	x23, ~(MIN_KIMG_ALIGN - 1)	// already running randomized?
	b.ne	0f
	bl	kaslr_early_init		// parse FDT for KASLR options
	cbz	x0, 0f				// KASLR disabled? just proceed
	orr	x23, x23, x0			// record KASLR offset
	ldp	x29, x30, [sp], #16		// we must enable KASLR, return
	ret					// to __primary_switch()
0:
#endif
	bl	switch_to_vhe			// Prefer VHE if possible
	ldp	x29, x30, [sp], #16
	bl	start_kernel
	ASM_BUG()
SYM_FUNC_END(__primary_switched)

	.pushsection ".rodata", "a"
SYM_DATA_START(kimage_vaddr)
	.quad		_text
SYM_DATA_END(kimage_vaddr)
EXPORT_SYMBOL(kimage_vaddr)
	.popsection
```


The code scanning for EFI embedded-firmware runs near the end of start_kernel(), just before calling rest_init(). For normal drivers and subsystems using subsys_initcall() to register themselves this does not matter. This means that code running earlier cannot use EFI embedded-firmware.

### start_kernel



```c
asmlinkage __visible void __init __no_sanitize_address start_kernel(void)
{
       char *command_line;
       char *after_dashes;
```

[init task](/docs/CS/OS/Linux/process.md?id=init-task)
```c
       set_task_stack_end_magic(&init_task);
       smp_setup_processor_id();
       debug_objects_early_init();

       cgroup_init_early();

       local_irq_disable();
       early_boot_irqs_disabled = true;

       /*
        * Interrupts are still disabled. Do necessary setups, then
        * enable them.
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
       trap_init();
```

```c
       mm_init();

       ftrace_init();

       /* trace_printk can be enabled here */
       early_trace_init();

       /*
        * Set up the scheduler prior starting any interrupts (such as the
        * timer interrupt). Full topology setup happens at smp_init()
        * time - but meanwhile we still have a functioning scheduler.
        */
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

       /*
        * Allow workqueue creation and work item queueing/cancelling
        * early.  Work item execution depends on kthreads and starts after
        * workqueue_init().
        */
       workqueue_init_early();

       rcu_init();

       /* Trace events are available after this */
       trace_init();

       if (initcall_debug)
              initcall_debug_enable();

       context_tracking_init();
       /* init some links before init_ISA_irqs() */
       early_irq_init();
       init_IRQ();
       tick_init();
       rcu_init_nohz();
       init_timers();
       hrtimers_init();
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





### kernel_init

kernel_thread to run `kernel_init`

```c
noinline void __ref rest_init(void)
{
       struct task_struct *tsk;
       int pid;

       rcu_scheduler_starting();
       /*
        * We need to spawn init first so that it obtains pid 1, however
        * the init task will end up wanting to create kthreads, which, if
        * we schedule it before we create kthreadd, will OOPS.
        */
       pid = kernel_thread(kernel_init, NULL, CLONE_FS);
       /*
        * Pin init on the boot CPU. Task migration is not properly working
        * until sched_init_smp() has been run. It will set the allowed
        * CPUs for init to the non isolated CPUs.
        */
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
	 * Kernel mappings are now finalized - update the userspace page-table
	 * to finalize PTI.
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