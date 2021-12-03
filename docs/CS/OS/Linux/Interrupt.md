# Interrupt



什么是中断？简单来说就是**CPU停下当前的工作任务，去处理其他事情，处理完后回来继续执行刚才的任务**，这一过程便是中断。

本文旨在进一步揭开中断机制的面纱，理清中断的过程，就中断做出以下几个方面的介绍：

中断分类，中断描述符表，中断控制器，和中断过程



## 中断分类

- 外部
  - 可屏蔽
  - 不可屏蔽
- 内部
  - 陷阱
  - 故障
  - 终止





### 外部中断

**1、可屏蔽中断**：**通过INTR线向CPU请求的中断**，主要来自外部设备如硬盘，打印机，网卡等。此类中断并不会影响系统运行，可随时处理，甚至不处理，所以名为可屏蔽中断。

**2、不可屏蔽中断**：**通过NMI线向CPU请求的中断**，如电源掉电，硬件线路故障等。这里不可屏蔽的意思不是不可以屏蔽，不建议屏蔽，而是问题太大，屏蔽不了，不能屏蔽的意思。

注：INTR和NMI都是CPU的引脚



### 内部中断

(软中断，异常)

**1、陷阱：是一种有意的，预先安排的异常事件**，一般是在编写程序时故意设下的陷阱指令，而后执行到陷阱指令后，CPU将会调用特定程序进行相应的处理，**处理结束后返回到陷阱指令的下一条指令**。如系统调用，程序调试功能等。

尽管我们平时写程序时似乎并没有设下陷阱，那是因为平常所用的高级语言对底层的指令进行了太多层的抽象封装，已看不到底层的实现，但其实是存在的。例如**printf函数，最底层的实现中会有一条int 0x80指令**，这就是一条陷阱指令，使用0x80号中断进行系统调用。

**2、故障：故障是在引起故障的指令被执行，但还没有执行结束时，CPU检测到的一类的意外事件。**出错时交由故障处理程序处理，**如果能处理修正这个错误，就将控制返回到引起故障的指令即CPU重新执这条指令。如果不能处理就报错**。

常见的故障为缺页，当CPU引用的虚拟地址对应的物理页不存在时就会发生故障。缺页异常是能够修正的，有着专门的缺页处理程序，它会将缺失的物理页从磁盘中重新调进主存。而后再次执行引起故障的指令时便能够顺利执行了。

**3、终止：执行指令的过程中发生了致命错误，不可修复，程序无法继续运行，只能终止，通常会是一些硬件的错误。**终止处理程序不会将控制返回给原程序，而是直接终止原程序



## 中断描述符表

中断描述符表类似全局描述附表，表内存放的描述符，与GDT不同的是IDT内可以存放4种描述符：任务门描述符，陷阱门描述符，调用门描述符，中断门描述符。

咱们在此只介绍中断门描述符，4种描述符除了任务门其他都类似，中断门也是最常用的，如Linux的系统调用就是使用中断门实现的。



### 中断描述符

![一文讲透计算机的“中断”](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/72a699d5ec644da5be09800ef3dd880b~tplv-k3u1fbpfcp-zoom-1.image)

中断描述符的结构如上，重要字段和属性为已标出，有个了解就好，不必深究各个位的具体含义。

### 中断向量号

在介绍中断向量号之前，我们先引入一个段选择子（segment selector）的概念。所谓段选择子，就是段寄存器的值，段选择子的高13位为全局描述符表的索引号，其他的位置是属性位，这就好比是数组下标索引数组元素。

至于中断向量号，作用等同于段选择子的高13位，用来在IDT中索引相对的中断描述符，但没有相应的类似段选择子的结构。

部分中断向量表，需要了解的部分如下图所示：

![一文讲透计算机的“中断”](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

**3**

中断描述符表寄存器IDTR

![一文讲透计算机的“中断”](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

IDTR也类似于GDTR，存放的是48位数据信息，高32位是IDT的地址，低16位表示IDT的界限。

同GDTR，IDTR也有相应的加载指令：**lidt m16&32**，m是那48位数据信息，lidt指令将其加载到IDTR寄存器，使得CPU知道IDT在哪。



## 中断控制器

每个独立运行的外设都可以是一个中断源，能够向CPU发送中断请求，为了方便管理和减少引脚数目，设立了中断控制器，让所有的可屏蔽中断都通过INTR信号线与CPU进行交流。

中断控制器中较为流行的是Intel 8259A芯片，下面对8259A作简单介绍：

**1**

级联

**单个8259A芯片只有8根中断请求信号线**（IRQ0, IRQ1, … , IRQ7），这是不够用的，所以采用多个8259A芯片。将它们如下图一样像串联的方式组合起来，这种组合方式就叫做级联。

![一文讲透计算机的“中断”](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

**级联时只能有一个主片，其余的均为从片**，最多可级联9个，即最多支持64个中断。为什么不是8 * 9 = 72个呢？从上图可以看出**级联时后面的芯片会占用前面芯片的一个IRQ接口**，而最后一个8259A没有其他人占用，所以8259A的个数和支持的中断数关系为7n + 1。

**2**

8259A的一些功寄存器和功能部件

1、IMR：Interrupt Mask Register，中断屏蔽寄存器，其中的每个位标志着一个外设，1表示屏蔽该外设，0表示中断允许。

2、IRR：Interrrupt Request Register，中断请求寄存器，请求中断的外设在IRR对应的位 值为1。当有多个中断请求时，IRR寄存器中多位将会置1，相当于维持了一个请求中断的队列。

3、ISR：In_Service Register，中断服务寄存器，正在进行处理的中断在ISR对应的位值为1。

4、PR：Priority Resolver，优先级裁决器，用于从IRR中挑选一个优先级最大的中断。(IRQ接口号小的优先级大)。



## 中断过程



### 中断请求

**1、**当外设发出中断信号后，信号被送入8259A；

**2、**8259A检查IMR寄存器中是否屏蔽了来自该IRQ的信号，若IMR寄存器中对应的位为1，表示屏蔽了IRQ代表的中断，则丢掉此中断信号，若IMR寄存器中对应的位为0，表示未屏蔽此中断，则将IRR寄存器中与此中断对应的位 置1。

**3、**PR优先级裁决器从IRR寄存器中挑选一个优先级最大的中断，然后8259A向CPU发送INTR信号。

**2**

### 中断响应

**1、**CPU收到INTR信号后便知道有新的中断了，在执行完当前指令后，向8259A发送一个中断回复信号。

**2、**8259A收到回复信号后，将选出来的优先级最大的中断在ISR寄存器中相应的位 置1，表示该中断正在处理，同时将此中断在IRR寄存器中相应的位 置0，相当于将此中断从中断请求队列中去掉。

**3、**CPU再次向8259A发送INTR信号，表示想要获取中断向量号。

**4、**8259A通过数据总线向CPU发送中断向量号，**中断向量号 = 起始向量号 + IRQ接口号**，一般起始向量号为32，从中断向量表可看出0—31已经被占用，后面的32—127是分配给可屏蔽中断的，所以此处外设的中断设置的起始向量号便为32。

**3**

### 保护现场——压栈

**1、**CPU据中断向量号去IDT中获取中断描述符，取出选择子中的DPL与当前特权级CPL进行比较，若特权级发生变化，则需要切换栈。（不同特权级有着不同的栈，如Linux使用了0， 3特权级，则有两个栈，一个内核栈，一个用户栈）

**2、**于是处理器临时保存当前的旧栈SS和ESP的值，从TSS（每一个任务有一个TSS结构，其中保存着不同特权级栈的SS和ESP值）中获取与DPL特权级同的栈信息加载到SS和ESP寄存器。再将旧栈SS和ESP的值压入新栈中。若没有特权级变化，则跳过此步骤。

3、压入程序状态信息，即EFLAGS寄存器

4、压入断点，即返回地址，即当前任务的CS，EIP值。

5、若该中断有错误码，压入错误码



### 定位中断服务程序

具体步骤如下：

**1、**据中断向量号去IDT中索引中断描述符，具体操作：取出IDTR中的IDT地址，加上中断向量号 * 8，得到的地址指向所要的中断描述符。

**2、**据中断描述符中的段选择子去GDT中索引段描述符，具体操作：取出GDTR中的GDT地址。加上段选择子高13位 * 8， 得到的地址为中断处理程序所在段的段基址。

**3、**上一步得到的段基址加上段描述符中的段内偏移量得到的地址变为中断服务程序的地址。

**5**

### 中断处理过程

中断的实际处理过程就是执行中断处理程序，Linux将中断处理程序分为上下两部分，需要紧急处理立即执行的归为上半部，不那么紧急的归为下半部。

这便涉及到了开关中断的问题。开中断，即EFLAGS的IF位置1，表示允许响应中断；关中断，即EFLAGS的IF位置0，表示不允许响应中断。

**1、**上半部分是刻不容缓的，需要立即执行的部分，所以要在关中断的状态下执行。

**2、**而下半部分不那么紧急，在开中断的情况下进行，如果此时有新的中断发生，当前中断处理程序便会换下CPU，CPU会另寻时间重新调度，完成整个中断处理程序。

**6**

### 中断返回——出栈

中断返回就是出栈的过程，将第三步保护现场压入栈中的信息弹出。

**1、**有错误码弹出错误码。

**2、**此时的栈顶指针ESP应指向EIP_old，剩余栈中的信息使用iret指令弹出，CPU执行到iret指令时再次检查和比较特权级是否变化。

**3、**弹出EIP_old, CS_old

**4、**若特权级变化，将ESP_old, SS_old, 加载到ESP，SS寄存器。

至此，中断已返回，中断也已处理。

上述的中断过程是我根据资料照着自己的理解分为了6步，每步又有许多微操作，可能跟某些书籍资料等所划分的步骤不同，甚至一些微操作的顺序也不太一样，比如说中断处理时什么时候关中断，我查阅了许多资料和书籍，讲述得都有区别。

不同操作系统在中断方面的实现有所不同，但总体来说都会经历上述的步骤，可能细微之处略有差别，却也不影响我们了解中断的过程。



## END

中断是操作系统重要的机制，没有中断，操作系统什么也干不了，没法输入没法输出，不能管理硬件资源，也不能向上层应用提供服务。而且操作系统本身就像是一个死循环，等待事件发生需求来临，然后为其提供服务解决问题。而这事件的发生与处理就是靠中断机制来控制的，所以说中断对于操作系统来说有着举足轻重的作用，而我们也有必要了解中断，理清中断的过程。


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

	retval = __setup_irq(irq, desc, action);

	if (retval) {
		irq_chip_pm_put(&desc->irq_data);
		kfree(action->secondary);
		kfree(action);
	}

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