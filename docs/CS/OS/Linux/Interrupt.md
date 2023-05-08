## Introduction

## Hardware

- task gate
- interrupt gate
- trap gate
- call gate

## init

### trap_init

```c
// arch/x86/kernel/traps.c
void __init trap_init(void)
{
	/* Init cpu_entry_area before IST entries are set up */
	setup_cpu_entry_areas();

	/* Init GHCB memory pages when running as an SEV-ES guest */
	sev_es_init_vc_handling();

	idt_setup_traps();

	/*
	 * Should be a barrier for any external CPU state:
	 */
	cpu_init();

	idt_setup_ist_traps();
}
```

### init_IRQ

```c
// arch/x86/kernel/irqinit.c
void __init init_IRQ(void)
{
	int i;

	/*
	 * On cpu 0, Assign ISA_IRQ_VECTOR(irq) to IRQ 0..15.
	 * If these IRQ's are handled by legacy interrupt-controllers like PIC,
	 * then this configuration will likely be static after the boot. If
	 * these IRQs are handled by more modern controllers like IO-APIC,
	 * then this vector space can be freed and re-used dynamically as the
	 * irq's migrate etc.
	 */
	for (i = 0; i < nr_legacy_irqs(); i++)
		per_cpu(vector_irq, 0)[ISA_IRQ_VECTOR(i)] = irq_to_desc(i);

	BUG_ON(irq_init_percpu_irqstack(smp_processor_id()));

	x86_init.irqs.intr_init();
}
```

```c
struct x86_init_ops x86_init __initdata = {
.irqs = {
		.pre_vector_init	= init_ISA_irqs,
		.intr_init		= native_init_IRQ,
		.intr_mode_select	= apic_intr_mode_select,
		.intr_mode_init		= apic_intr_mode_init,
		.create_pci_msi_domain	= native_create_pci_msi_domain,
	},
};
```

native_init_IRQ

```c
void __init native_init_IRQ(void)
{
	/* Execute any quirks before the call gates are initialised: */
	x86_init.irqs.pre_vector_init();

	idt_setup_apic_and_irq_gates();
	lapic_assign_system_vectors();

	if (!acpi_ioapic && !of_ioapic && nr_legacy_irqs()) {
		/* IRQ2 is cascade interrupt to second interrupt controller */
		if (request_irq(2, no_action, IRQF_NO_THREAD, "cascade", NULL))
			pr_err("%s: request_irq() failed\n", "cascade");
	}
}
```

init_ISA_irqs

```c

void __init init_ISA_irqs(void)
{
	struct irq_chip *chip = legacy_pic->chip;
	int i;

	/*
	 * Try to set up the through-local-APIC virtual wire mode earlier.
	 *
	 * On some 32-bit UP machines, whose APIC has been disabled by BIOS
	 * and then got re-enabled by "lapic", it hangs at boot time without this.
	 */
	init_bsp_APIC();

	legacy_pic->init(0);

	for (i = 0; i < nr_legacy_irqs(); i++)
		irq_set_chip_and_handler(i, chip, handle_level_irq);
}
```

## irq

Bit masks for desc->core_internal_state__do_not_mess_with_it

- IRQS_AUTODETECT		- autodetection in progress
- IRQS_SPURIOUS_DISABLED	- was disabled due to spurious interrupt
- detection
- IRQS_POLL_INPROGRESS		- polling in progress
- IRQS_ONESHOT			- irq is not unmasked in primary handler
- IRQS_REPLAY			- irq is replayed
- IRQS_WAITING			- irq is waiting
- IRQS_PENDING			- irq is pending and replayed later
- IRQS_SUSPENDED		- irq is suspended
- IRQS_NMI			- irq line is used to deliver NMIs

```c
// kernal/irq/internals.h
enum {
	IRQS_AUTODETECT		= 0x00000001,
	IRQS_SPURIOUS_DISABLED	= 0x00000002,
	IRQS_POLL_INPROGRESS	= 0x00000008,
	IRQS_ONESHOT		= 0x00000020,
	IRQS_REPLAY		= 0x00000040,
	IRQS_WAITING		= 0x00000080,
	IRQS_PENDING		= 0x00000200,
	IRQS_SUSPENDED		= 0x00000800,
	IRQS_TIMINGS		= 0x00001000,
	IRQS_NMI		= 0x00002000,
};
```

### request_irq

request_irq - Add a handler for an interrupt line

- irq:	The interrupt line to allocate
- handler:	Function to be called when the IRQ occurs. Primary handler for threaded interrupts If NULL, the default primary handler is installed
- flags:	Handling flags
- name:	Name of the device generating this interrupt
- dev:	A cookie passed to the handler function

This call allocates an interrupt and establishes a handler; see the documentation for request_threaded_irq() for details.

```c
// include/linux/interrupt.h
static inline int __must_check
request_irq(unsigned int irq, irq_handler_t handler, unsigned long flags,
	    const char *name, void *dev)
{
	return request_threaded_irq(irq, handler, NULL, flags, name, dev);
}
```

If a (PCI) device interrupt is not connected we set dev->irq to
IRQ_NOTCONNECTED. This causes request_irq() to fail with -ENOTCONN, so we
can distingiush that case from other error returns.
0x80000000 is guaranteed to be outside the available range of interrupts
and easy to distinguish from other possible incorrect values.

```c
#define IRQ_NOTCONNECTED	(1U << 31)


// kernel/irq/manage.c
int request_threaded_irq(unsigned int irq, irq_handler_t handler,
irq_handler_t thread_fn, unsigned long irqflags,
const char *devname, void *dev_id)
{
struct irqaction *action;
struct irq_desc *desc;
int retval;

	if (irq == IRQ_NOTCONNECTED)
		return -ENOTCONN;

	/*
	 * Sanity-check: shared interrupts must pass in a real dev-ID,
	 * otherwise we'll have trouble later trying to figure out
	 * which interrupt is which (messes up the interrupt freeing
	 * logic etc).
	 *
	 * Also shared interrupts do not go well with disabling auto enable.
	 * The sharing interrupt might request it while it's still disabled
	 * and then wait for interrupts forever.
	 *
	 * Also IRQF_COND_SUSPEND only makes sense for shared interrupts and
	 * it cannot be set along with IRQF_NO_SUSPEND.
	 */
	if (((irqflags & IRQF_SHARED) && !dev_id) ||
	    ((irqflags & IRQF_SHARED) && (irqflags & IRQF_NO_AUTOEN)) ||
	    (!(irqflags & IRQF_SHARED) && (irqflags & IRQF_COND_SUSPEND)) ||
	    ((irqflags & IRQF_NO_SUSPEND) && (irqflags & IRQF_COND_SUSPEND)))
		return -EINVAL;

	desc = irq_to_desc(irq);
	if (!desc)
		return -EINVAL;

	if (!irq_settings_can_request(desc) ||
	    WARN_ON(irq_settings_is_per_cpu_devid(desc)))
		return -EINVAL;

	if (!handler) {
		if (!thread_fn)
			return -EINVAL;
		handler = irq_default_primary_handler;
	}

	action = kzalloc(sizeof(struct irqaction), GFP_KERNEL);
	if (!action)
		return -ENOMEM;

	action->handler = handler;
	action->thread_fn = thread_fn;
	action->flags = irqflags;
	action->name = devname;
	action->dev_id = dev_id;

	retval = irq_chip_pm_get(&desc->irq_data);
	if (retval < 0) {
		kfree(action);
		return retval;
	}
```

call __setup_irq

```c
	retval = __setup_irq(irq, desc, action);

	if (retval) {
		irq_chip_pm_put(&desc->irq_data);
		kfree(action->secondary);
		kfree(action);
	}
```

```c
#ifdef CONFIG_DEBUG_SHIRQ_FIXME
	if (!retval && (irqflags & IRQF_SHARED)) {
		/*
		 * It's a shared IRQ -- the driver ought to be prepared for it
		 * to happen immediately, so let's make sure....
		 * We disable the irq to make sure that a 'real' IRQ doesn't
		 * run in parallel with our fake.
		 */
		unsigned long flags;

		disable_irq(irq);
		local_irq_save(flags);

		handler(irq, dev_id);

		local_irq_restore(flags);
		enable_irq(irq);
	}
#endif
	return retval;
}
```

### free

free_irq - free an interrupt allocated with request_irq

- irq: Interrupt line to free
- dev_id: Device identity to free

Remove an interrupt handler. The handler is removed and if the
interrupt line is no longer in use by any driver it is disabled.
On a shared IRQ the caller must ensure the interrupt is disabled
on the card it drives before calling this function. The function
does not return until any executing interrupts for this IRQ
have completed.

This function must not be called from interrupt context.
Returns the devname argument passed to request_irq.

```c
// kernel/irq/manage.c
const void *free_irq(unsigned int irq, void *dev_id)
{
	struct irq_desc *desc = irq_to_desc(irq);
	struct irqaction *action;
	const char *devname;

	if (!desc || WARN_ON(irq_settings_is_per_cpu_devid(desc)))
		return NULL;

#ifdef CONFIG_SMP
	if (WARN_ON(desc->affinity_notify))
		desc->affinity_notify = NULL;
#endif

	action = __free_irq(desc, dev_id);

	if (!action)
		return NULL;

	devname = action->name;
	kfree(action);
	return devname;
}
```

### handle

common_interrupt() handles all normal device IRQ's (the special SMP cross-CPU interrupts have their own entry points).

```c
DEFINE_IDTENTRY_IRQ(common_interrupt)
{
	struct pt_regs *old_regs = set_irq_regs(regs);
	struct irq_desc *desc;

	/* entry code tells RCU that we're not quiescent.  Check it. */
	RCU_LOCKDEP_WARN(!rcu_is_watching(), "IRQ failed to wake up RCU");

	desc = __this_cpu_read(vector_irq[vector]);
	if (likely(!IS_ERR_OR_NULL(desc))) {
		handle_irq(desc, regs);
	} else {
		ack_APIC_irq();

		if (desc == VECTOR_UNUSED) {
			pr_emerg_ratelimited("%s: %d.%u No irq handler for vector\n",
					     __func__, smp_processor_id(),
					     vector);
		} else {
			__this_cpu_write(vector_irq[vector], VECTOR_UNUSED);
		}
	}

	set_irq_regs(old_regs);
}
```

```c
// kernel/irq/handle.c
irqreturn_t handle_irq_event(struct irq_desc *desc)
{
	irqreturn_t ret;

	desc->istate &= ~IRQS_PENDING;
	irqd_set(&desc->irq_data, IRQD_IRQ_INPROGRESS);
	raw_spin_unlock(&desc->lock);

	ret = handle_irq_event_percpu(desc);

	raw_spin_lock(&desc->lock);
	irqd_clear(&desc->irq_data, IRQD_IRQ_INPROGRESS);
	return ret;
}
```

#### handle_irq_event_percpu

```c
// kernel/irq/handle.c
irqreturn_t handle_irq_event_percpu(struct irq_desc *desc)
{
	irqreturn_t retval;
	unsigned int flags = 0;

	retval = __handle_irq_event_percpu(desc, &flags);

	add_interrupt_randomness(desc->irq_data.irq, flags);

	if (!irq_settings_no_debug(desc))
		note_interrupt(desc, retval);
	return retval;
}


irqreturn_t __handle_irq_event_percpu(struct irq_desc *desc, unsigned int *flags)
{
	irqreturn_t retval = IRQ_NONE;
	unsigned int irq = desc->irq_data.irq;
	struct irqaction *action;

	record_irq_time(desc);

	for_each_action_of_desc(desc, action) {
		irqreturn_t res;

		/*
		 * If this IRQ would be threaded under force_irqthreads, mark it so.
		 */
		if (irq_settings_can_thread(desc) &&
		    !(action->flags & (IRQF_NO_THREAD | IRQF_PERCPU | IRQF_ONESHOT)))
			lockdep_hardirq_threaded();

		trace_irq_handler_entry(irq, action);
		res = action->handler(irq, action->dev_id);
		trace_irq_handler_exit(irq, action, res);

		if (WARN_ONCE(!irqs_disabled(),"irq %u handler %pS enabled interrupts\n",
			      irq, action->handler))
			local_irq_disable();

		switch (res) {
		case IRQ_WAKE_THREAD:
			/*
			 * Catch drivers which return WAKE_THREAD but
			 * did not set up a thread function
			 */
			if (unlikely(!action->thread_fn)) {
				warn_no_thread(irq, action);
				break;
			}

			__irq_wake_thread(desc, action);

			fallthrough;	/* to add to randomness */
		case IRQ_HANDLED:
			*flags |= action->flags;
			break;

		default:
			break;
		}

		retval |= res;
	}

	return retval;
}
```

### setup_irq

Internal function to register an irqaction - typically used to
allocate special interrupts that are part of the architecture.

Locking rules:

- desc->request_mutex	Provides serialization against a concurrent free_irq()
- chip_bus_lock	Provides serialization for slow bus operations
- desc->lock	Provides serialization against hard interrupts

chip_bus_lock and desc->lock are sufficient for all other management and
interrupt related functions. desc->request_mutex solely serializes
request/free_irq().

```c
// kernel/irq/manage.c
static int
__setup_irq(unsigned int irq, struct irq_desc *desc, struct irqaction *new)
{
	struct irqaction *old, **old_ptr;
	unsigned long flags, thread_mask = 0;
	int ret, nested, shared = 0;

	if (!desc)
		return -EINVAL;

	if (desc->irq_data.chip == &no_irq_chip)
		return -ENOSYS;
	if (!try_module_get(desc->owner))
		return -ENODEV;

	new->irq = irq;

	/*
	 * If the trigger type is not specified by the caller,
	 * then use the default for this interrupt.
	 */
	if (!(new->flags & IRQF_TRIGGER_MASK))
		new->flags |= irqd_get_trigger_type(&desc->irq_data);

	/*
	 * Check whether the interrupt nests into another interrupt
	 * thread.
	 */
	nested = irq_settings_is_nested_thread(desc);
	if (nested) {
		if (!new->thread_fn) {
			ret = -EINVAL;
			goto out_mput;
		}
		/*
		 * Replace the primary handler which was provided from
		 * the driver for non nested interrupt handling by the
		 * dummy function which warns when called.
		 */
		new->handler = irq_nested_primary_handler;
	} else {
		if (irq_settings_can_thread(desc)) {
			ret = irq_setup_forced_threading(new);
			if (ret)
				goto out_mput;
		}
	}

	/*
	 * Create a handler thread when a thread function is supplied
	 * and the interrupt does not nest into another interrupt
	 * thread.
	 */
	if (new->thread_fn && !nested) {
		ret = setup_irq_thread(new, irq, false);
		if (ret)
			goto out_mput;
		if (new->secondary) {
			ret = setup_irq_thread(new->secondary, irq, true);
			if (ret)
				goto out_thread;
		}
	}

	/*
	 * Drivers are often written to work w/o knowledge about the
	 * underlying irq chip implementation, so a request for a
	 * threaded irq without a primary hard irq context handler
	 * requires the ONESHOT flag to be set. Some irq chips like
	 * MSI based interrupts are per se one shot safe. Check the
	 * chip flags, so we can avoid the unmask dance at the end of
	 * the threaded handler for those.
	 */
	if (desc->irq_data.chip->flags & IRQCHIP_ONESHOT_SAFE)
		new->flags &= ~IRQF_ONESHOT;

	/*
	 * Protects against a concurrent __free_irq() call which might wait
	 * for synchronize_hardirq() to complete without holding the optional
	 * chip bus lock and desc->lock. Also protects against handing out
	 * a recycled oneshot thread_mask bit while it's still in use by
	 * its previous owner.
	 */
	mutex_lock(&desc->request_mutex);

	/*
	 * Acquire bus lock as the irq_request_resources() callback below
	 * might rely on the serialization or the magic power management
	 * functions which are abusing the irq_bus_lock() callback,
	 */
	chip_bus_lock(desc);

	/* First installed action requests resources. */
	if (!desc->action) {
		ret = irq_request_resources(desc);
		if (ret) {
			pr_err("Failed to request resources for %s (irq %d) on irqchip %s\n",
			       new->name, irq, desc->irq_data.chip->name);
			goto out_bus_unlock;
		}
	}

	/*
	 * The following block of code has to be executed atomically
	 * protected against a concurrent interrupt and any of the other
	 * management calls which are not serialized via
	 * desc->request_mutex or the optional bus lock.
	 */
	raw_spin_lock_irqsave(&desc->lock, flags);
	old_ptr = &desc->action;
	old = *old_ptr;
	if (old) {
		/*
		 * Can't share interrupts unless both agree to and are
		 * the same type (level, edge, polarity). So both flag
		 * fields must have IRQF_SHARED set and the bits which
		 * set the trigger type must match. Also all must
		 * agree on ONESHOT.
		 * Interrupt lines used for NMIs cannot be shared.
		 */
		unsigned int oldtype;

		if (desc->istate & IRQS_NMI) {
			pr_err("Invalid attempt to share NMI for %s (irq %d) on irqchip %s.\n",
				new->name, irq, desc->irq_data.chip->name);
			ret = -EINVAL;
			goto out_unlock;
		}

		/*
		 * If nobody did set the configuration before, inherit
		 * the one provided by the requester.
		 */
		if (irqd_trigger_type_was_set(&desc->irq_data)) {
			oldtype = irqd_get_trigger_type(&desc->irq_data);
		} else {
			oldtype = new->flags & IRQF_TRIGGER_MASK;
			irqd_set_trigger_type(&desc->irq_data, oldtype);
		}

		if (!((old->flags & new->flags) & IRQF_SHARED) ||
		    (oldtype != (new->flags & IRQF_TRIGGER_MASK)) ||
		    ((old->flags ^ new->flags) & IRQF_ONESHOT))
			goto mismatch;

		/* All handlers must agree on per-cpuness */
		if ((old->flags & IRQF_PERCPU) !=
		    (new->flags & IRQF_PERCPU))
			goto mismatch;

		/* add new interrupt at end of irq queue */
		do {
			/*
			 * Or all existing action->thread_mask bits,
			 * so we can find the next zero bit for this
			 * new action.
			 */
			thread_mask |= old->thread_mask;
			old_ptr = &old->next;
			old = *old_ptr;
		} while (old);
		shared = 1;
	}

	/*
	 * Setup the thread mask for this irqaction for ONESHOT. For
	 * !ONESHOT irqs the thread mask is 0 so we can avoid a
	 * conditional in irq_wake_thread().
	 */
	if (new->flags & IRQF_ONESHOT) {
		/*
		 * Unlikely to have 32 resp 64 irqs sharing one line,
		 * but who knows.
		 */
		if (thread_mask == ~0UL) {
			ret = -EBUSY;
			goto out_unlock;
		}
		/*
		 * The thread_mask for the action is or'ed to
		 * desc->thread_active to indicate that the
		 * IRQF_ONESHOT thread handler has been woken, but not
		 * yet finished. The bit is cleared when a thread
		 * completes. When all threads of a shared interrupt
		 * line have completed desc->threads_active becomes
		 * zero and the interrupt line is unmasked. See
		 * handle.c:irq_wake_thread() for further information.
		 *
		 * If no thread is woken by primary (hard irq context)
		 * interrupt handlers, then desc->threads_active is
		 * also checked for zero to unmask the irq line in the
		 * affected hard irq flow handlers
		 * (handle_[fasteoi|level]_irq).
		 *
		 * The new action gets the first zero bit of
		 * thread_mask assigned. See the loop above which or's
		 * all existing action->thread_mask bits.
		 */
		new->thread_mask = 1UL << ffz(thread_mask);

	} else if (new->handler == irq_default_primary_handler &&
		   !(desc->irq_data.chip->flags & IRQCHIP_ONESHOT_SAFE)) {
		/*
		 * The interrupt was requested with handler = NULL, so
		 * we use the default primary handler for it. But it
		 * does not have the oneshot flag set. In combination
		 * with level interrupts this is deadly, because the
		 * default primary handler just wakes the thread, then
		 * the irq lines is reenabled, but the device still
		 * has the level irq asserted. Rinse and repeat....
		 *
		 * While this works for edge type interrupts, we play
		 * it safe and reject unconditionally because we can't
		 * say for sure which type this interrupt really
		 * has. The type flags are unreliable as the
		 * underlying chip implementation can override them.
		 */
		pr_err("Threaded irq requested with handler=NULL and !ONESHOT for %s (irq %d)\n",
		       new->name, irq);
		ret = -EINVAL;
		goto out_unlock;
	}

	if (!shared) {
		init_waitqueue_head(&desc->wait_for_threads);

		/* Setup the type (level, edge polarity) if configured: */
		if (new->flags & IRQF_TRIGGER_MASK) {
			ret = __irq_set_trigger(desc,
						new->flags & IRQF_TRIGGER_MASK);

			if (ret)
				goto out_unlock;
		}

		/*
		 * Activate the interrupt. That activation must happen
		 * independently of IRQ_NOAUTOEN. request_irq() can fail
		 * and the callers are supposed to handle
		 * that. enable_irq() of an interrupt requested with
		 * IRQ_NOAUTOEN is not supposed to fail. The activation
		 * keeps it in shutdown mode, it merily associates
		 * resources if necessary and if that's not possible it
		 * fails. Interrupts which are in managed shutdown mode
		 * will simply ignore that activation request.
		 */
		ret = irq_activate(desc);
		if (ret)
			goto out_unlock;

		desc->istate &= ~(IRQS_AUTODETECT | IRQS_SPURIOUS_DISABLED | \
				  IRQS_ONESHOT | IRQS_WAITING);
		irqd_clear(&desc->irq_data, IRQD_IRQ_INPROGRESS);

		if (new->flags & IRQF_PERCPU) {
			irqd_set(&desc->irq_data, IRQD_PER_CPU);
			irq_settings_set_per_cpu(desc);
			if (new->flags & IRQF_NO_DEBUG)
				irq_settings_set_no_debug(desc);
		}

		if (noirqdebug)
			irq_settings_set_no_debug(desc);

		if (new->flags & IRQF_ONESHOT)
			desc->istate |= IRQS_ONESHOT;

		/* Exclude IRQ from balancing if requested */
		if (new->flags & IRQF_NOBALANCING) {
			irq_settings_set_no_balancing(desc);
			irqd_set(&desc->irq_data, IRQD_NO_BALANCING);
		}

		if (!(new->flags & IRQF_NO_AUTOEN) &&
		    irq_settings_can_autoenable(desc)) {
			irq_startup(desc, IRQ_RESEND, IRQ_START_COND);
		} else {
			/*
			 * Shared interrupts do not go well with disabling
			 * auto enable. The sharing interrupt might request
			 * it while it's still disabled and then wait for
			 * interrupts forever.
			 */
			WARN_ON_ONCE(new->flags & IRQF_SHARED);
			/* Undo nested disables: */
			desc->depth = 1;
		}

	} else if (new->flags & IRQF_TRIGGER_MASK) {
		unsigned int nmsk = new->flags & IRQF_TRIGGER_MASK;
		unsigned int omsk = irqd_get_trigger_type(&desc->irq_data);

		if (nmsk != omsk)
			/* hope the handler works with current  trigger mode */
			pr_warn("irq %d uses trigger mode %u; requested %u\n",
				irq, omsk, nmsk);
	}

	*old_ptr = new;

	irq_pm_install_action(desc, new);

	/* Reset broken irq detection when installing new handler */
	desc->irq_count = 0;
	desc->irqs_unhandled = 0;

	/*
	 * Check whether we disabled the irq via the spurious handler
	 * before. Reenable it and give it another chance.
	 */
	if (shared && (desc->istate & IRQS_SPURIOUS_DISABLED)) {
		desc->istate &= ~IRQS_SPURIOUS_DISABLED;
		__enable_irq(desc);
	}

	raw_spin_unlock_irqrestore(&desc->lock, flags);
	chip_bus_sync_unlock(desc);
	mutex_unlock(&desc->request_mutex);

	irq_setup_timings(desc, new);

	/*
	 * Strictly no need to wake it up, but hung_task complains
	 * when no hard interrupt wakes the thread up.
	 */
	if (new->thread)
		wake_up_process(new->thread);
	if (new->secondary)
		wake_up_process(new->secondary->thread);

	register_irq_proc(irq, desc);
	new->dir = NULL;
	register_handler_proc(irq, new);
	return 0;

mismatch:
	if (!(new->flags & IRQF_PROBE_SHARED)) {
		pr_err("Flags mismatch irq %d. %08x (%s) vs. %08x (%s)\n",
		       irq, new->flags, new->name, old->flags, old->name);
#ifdef CONFIG_DEBUG_SHIRQ
		dump_stack();
#endif
	}
	ret = -EBUSY;

out_unlock:
	raw_spin_unlock_irqrestore(&desc->lock, flags);

	if (!desc->action)
		irq_release_resources(desc);
out_bus_unlock:
	chip_bus_sync_unlock(desc);
	mutex_unlock(&desc->request_mutex);

out_thread:
	if (new->thread) {
		struct task_struct *t = new->thread;

		new->thread = NULL;
		kthread_stop(t);
		put_task_struct(t);
	}
	if (new->secondary && new->secondary->thread) {
		struct task_struct *t = new->secondary->thread;

		new->secondary->thread = NULL;
		kthread_stop(t);
		put_task_struct(t);
	}
out_mput:
	module_put(desc->owner);
	return ret;
}
```

## softirq

Signals are software interrupts.
The simplest interface to the signal features of the UNIX System is the signal function.

```shell
cat /proc/softirqs


cat /proc/interrupts
cat /proc/irq/<number>/smp_affinity

```

PLEASE, avoid to allocate new softirqs, if you need not _really_ high frequency threaded job scheduling.
For almost all the purposes tasklets are more than enough. F.e. all serial device BHs et al. should be converted to tasklets, not to softirqs.

```c
enum
{
	HI_SOFTIRQ=0,
	TIMER_SOFTIRQ,
	NET_TX_SOFTIRQ,
	NET_RX_SOFTIRQ,
	BLOCK_SOFTIRQ,
	IRQ_POLL_SOFTIRQ,
	TASKLET_SOFTIRQ,
	SCHED_SOFTIRQ,
	HRTIMER_SOFTIRQ,
	RCU_SOFTIRQ,    /* Preferable RCU should always be the last softirq */

	NR_SOFTIRQS
};
```

### init_softirq

called by [start_kernel](/docs/CS/OS/Linux/init.md?id=start_kernel)

```c
// 
void __init softirq_init(void)
{
	int cpu;

	for_each_possible_cpu(cpu) {
		per_cpu(tasklet_vec, cpu).tail =
			&per_cpu(tasklet_vec, cpu).head;
		per_cpu(tasklet_hi_vec, cpu).tail =
			&per_cpu(tasklet_hi_vec, cpu).head;
	}

	open_softirq(TASKLET_SOFTIRQ, tasklet_action);
	open_softirq(HI_SOFTIRQ, tasklet_hi_action);
}
```

#### open_softirq

```c
// kernel/softirq.c
void open_softirq(int nr, void (*action)(struct softirq_action *))
{
	softirq_vec[nr].action = action;
}
```

### run_ksoftirqd

```c

static void run_ksoftirqd(unsigned int cpu)
{
	ksoftirqd_run_begin();
	if (local_softirq_pending()) {
		/*
		 * We can safely run softirq on inline stack, as we are not deep
		 * in the task stack here.
		 */
		__do_softirq();
		ksoftirqd_run_end();
		cond_resched();
		return;
	}
	ksoftirqd_run_end();
}
```

#### do_softirq

```c

asmlinkage __visible void __softirq_entry __do_softirq(void)
{
	unsigned long end = jiffies + MAX_SOFTIRQ_TIME;
	unsigned long old_flags = current->flags;
	int max_restart = MAX_SOFTIRQ_RESTART;
	struct softirq_action *h;
	bool in_hardirq;
	__u32 pending;
	int softirq_bit;

	/*
	 * Mask out PF_MEMALLOC as the current task context is borrowed for the
	 * softirq. A softirq handled, such as network RX, might set PF_MEMALLOC
	 * again if the socket is related to swapping.
	 */
	current->flags &= ~PF_MEMALLOC;

	pending = local_softirq_pending();

	softirq_handle_begin();
	in_hardirq = lockdep_softirq_start();
	account_softirq_enter(current);

restart:
	/* Reset the pending bitmask before enabling irqs */
	set_softirq_pending(0);

	local_irq_enable();

	h = softirq_vec;

	while ((softirq_bit = ffs(pending))) {
		unsigned int vec_nr;
		int prev_count;

		h += softirq_bit - 1;

		vec_nr = h - softirq_vec;
		prev_count = preempt_count();

		kstat_incr_softirqs_this_cpu(vec_nr);

		trace_softirq_entry(vec_nr);
		h->action(h);   // do action func
		trace_softirq_exit(vec_nr);
		if (unlikely(prev_count != preempt_count())) {
			pr_err("huh, entered softirq %u %s %p with preempt_count %08x, exited with %08x?\n",
			       vec_nr, softirq_to_name[vec_nr], h->action,
			       prev_count, preempt_count());
			preempt_count_set(prev_count);
		}
		h++;
		pending >>= softirq_bit;
	}

	if (!IS_ENABLED(CONFIG_PREEMPT_RT) &&
	    __this_cpu_read(ksoftirqd) == current)
		rcu_softirq_qs();

	local_irq_disable();

	pending = local_softirq_pending();
	if (pending) {
		if (time_before(jiffies, end) && !need_resched() &&
		    --max_restart)
			goto restart;

		wakeup_softirqd();
	}

	account_softirq_exit(current);
	lockdep_softirq_end(in_hardirq);
	softirq_handle_end();
	current_restore_flags(old_flags, PF_MEMALLOC);
}
```

#### spawn_ksoftirqd

```c
/*
 * CPU type, hardware bug flags, and per-CPU state.  Frequently used state comes earlier:
 */
struct cpuinfo_ia64 {
 ...
   struct task_struct *ksoftirqd; /* kernel softirq daemon for this CPU */
 ... 
}
```

```c
/**
 * smpboot_register_percpu_thread - Register a per_cpu thread related
 * 					    to hotplug
 * @plug_thread:	Hotplug thread descriptor
 *
 * Creates and starts the threads on all online cpus.
 */
int smpboot_register_percpu_thread(struct smp_hotplug_thread *plug_thread)
{
	unsigned int cpu;
	int ret = 0;

	cpus_read_lock();
	mutex_lock(&smpboot_threads_lock);
	for_each_online_cpu(cpu) {
		ret = __smpboot_create_thread(plug_thread, cpu);
		if (ret) {
			smpboot_destroy_threads(plug_thread);
			goto out;
		}
		smpboot_unpark_thread(plug_thread, cpu);
	}
	list_add(&plug_thread->list, &hotplug_threads);
out:
	mutex_unlock(&smpboot_threads_lock);
	cpus_read_unlock();
	return ret;
}
```

```c

static struct smp_hotplug_thread softirq_threads = {
	.store			= &ksoftirqd,
	.thread_should_run	= ksoftirqd_should_run,
	.thread_fn		= run_ksoftirqd,
	.thread_comm		= "ksoftirqd/%u",
};

static __init int spawn_ksoftirqd(void)
{
	cpuhp_setup_state_nocalls(CPUHP_SOFTIRQ_DEAD, "softirq:dead", NULL,
				  takeover_tasklets);
	BUG_ON(smpboot_register_percpu_thread(&softirq_threads));

	return 0;
}
early_initcall(spawn_ksoftirqd);
```

### raise_softirq

```c

// kernel/softirq.c
void __raise_softirq_irqoff(unsigned int nr)
{
	lockdep_assert_irqs_disabled();
	trace_softirq_raise(nr);
	or_softirq_pending(1UL << nr);
}


static int ksoftirqd_should_run(unsigned int cpu)
{
	return local_softirq_pending();
}
```

```c
// include/linux/interrupt.h
#ifndef local_softirq_pending_ref
#define local_softirq_pending_ref irq_stat.__softirq_pending
#endif

#define local_softirq_pending()	(__this_cpu_read(local_softirq_pending_ref))
#define set_softirq_pending(x)	(__this_cpu_write(local_softirq_pending_ref, (x)))
#define or_softirq_pending(x)	(__this_cpu_or(local_softirq_pending_ref, (x)))
```

### tasklet

Because tasklets are implemented on top of softirqs, they are softirqs.

Tasklets --- multithreaded analogue of BHs.

This API is deprecated. Please consider using threaded IRQs instead:
https://lore.kernel.org/lkml/20200716081538.2sivhkj4hcyrusem@linutronix.de

Main feature differing them of generic softirqs: tasklet is running only on one CPU simultaneously.

Main feature differing them of BHs: different tasklets may be run simultaneously on different CPUs.

Properties:

- If tasklet_schedule() is called, then tasklet is guaranteed to be executed on some cpu at least once after this.
- If the tasklet is already scheduled, but its execution is still not started, it will be executed only once.
- If this tasklet is already running on another CPU (or schedule is called from tasklet itself), it is rescheduled for later.
- Tasklet is strictly serialized wrt itself, but not wrt another tasklets. If client needs some intertask synchronization, he makes it with spinlocks.

```c
struct tasklet_struct
{
	struct tasklet_struct *next;
	unsigned long state;
	atomic_t count;
	bool use_callback;
	union {
		void (*func)(unsigned long data);
		void (*callback)(struct tasklet_struct *t);
	};
	unsigned long data;
};
```

#### tasklet_action

```c

static __latent_entropy void tasklet_action(struct softirq_action *a)
{
	tasklet_action_common(a, this_cpu_ptr(&tasklet_vec), TASKLET_SOFTIRQ);
}


static void tasklet_action_common(struct softirq_action *a,
				  struct tasklet_head *tl_head,
				  unsigned int softirq_nr)
{
	struct tasklet_struct *list;

	local_irq_disable();
	list = tl_head->head;
	tl_head->head = NULL;
	tl_head->tail = &tl_head->head;
	local_irq_enable();

	while (list) {
		struct tasklet_struct *t = list;

		list = list->next;

		if (tasklet_trylock(t)) {
			if (!atomic_read(&t->count)) {
				if (tasklet_clear_sched(t)) {
					if (t->use_callback)
						t->callback(t);
					else
						t->func(t->data);
				}
				tasklet_unlock(t);
				continue;
			}
			tasklet_unlock(t);
		}

		local_irq_disable();
		t->next = NULL;
		*tl_head->tail = t;
		tl_head->tail = &t->next;
```

call raise_softirq

```c
		__raise_softirq_irqoff(softirq_nr);
		local_irq_enable();
	}
}
```

#### tasklet_schedule

```c

void __tasklet_schedule(struct tasklet_struct *t)
{
	__tasklet_schedule_common(t, &tasklet_vec,
				  TASKLET_SOFTIRQ);
}


static void __tasklet_schedule_common(struct tasklet_struct *t,
				      struct tasklet_head __percpu *headp,
				      unsigned int softirq_nr)
{
	struct tasklet_head *head;
	unsigned long flags;

	local_irq_save(flags);
	head = this_cpu_ptr(headp);
	t->next = NULL;
	*head->tail = t;
	head->tail = &(t->next);
	raise_softirq_irqoff(softirq_nr);
	local_irq_restore(flags);
}
```

## syscall

```c
// 
#define IA32_SYSCALL_VECTOR		0x80

```

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
