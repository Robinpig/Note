## Introduction



Linux 中用于管理硬件设备和驱动程序的结构和框架称为 设备模型

Linux 设备模型中, kset、kobject 和 ktype 是实现设备模型的三个重要概念

kobj_type

```c
struct kobj_type {
	void (*release)(struct kobject *kobj);
	const struct sysfs_ops *sysfs_ops;
	const struct attribute_group **default_groups;
	const struct kobj_ns_type_operations *(*child_ns_type)(const struct kobject *kobj);
	const void *(*namespace)(const struct kobject *kobj);
	void (*get_ownership)(const struct kobject *kobj, kuid_t *uid, kgid_t *gid);
};
```
kobject

```c
struct kobject {
	const char		*name;
	struct list_head	entry;
	struct kobject		*parent;
	struct kset		*kset;
	const struct kobj_type	*ktype;
	struct kernfs_node	*sd; /* sysfs directory entry */
	struct kref		kref;

	unsigned int state_initialized:1;
	unsigned int state_in_sysfs:1;
	unsigned int state_add_uevent_sent:1;
	unsigned int state_remove_uevent_sent:1;
	unsigned int uevent_suppress:1;

#ifdef CONFIG_DEBUG_KOBJECT_RELEASE
	struct delayed_work	release;
#endif
};
```

kset

```c
struct kset {
	struct list_head list;
	spinlock_t list_lock;
	struct kobject kobj;
	const struct kset_uevent_ops *uevent_ops;
} __randomize_layout;
```

设备驱动程序通过注册 ktype 创建 kobject 并将 kobject 添加到适当的 kset中


Linux内核主要包括三种驱动模型，字符设备驱动，块设备驱动以及网络设备驱动



内核使用了大量不同的宏来标记具有不同作用的函数和数据结构。如宏__init 、__devinit 等
这些宏在include/linux/init.h 头文件中定义
- __init
- __exit
- __initdata
- __devinit
- __devinitdata
- __devexit
- xxx_initcall



```c
// include/linux/cdev.h
struct cdev {
	struct kobject kobj;
	struct module *owner;
	const struct file_operations *ops;
	struct list_head list;
	dev_t dev;
	unsigned int count;
} __randomize_layout;
```
设备驱动可以通过两种方式产生cdev 一种是全局静态变量 另一种是使用内核提供的cdev_alloc()接口函数

### net_device

struct net_device - The DEVICE structure.

Actually, this whole structure is a big mistake.  It mixes I/O data with strictly "high-level" data, and it has to know about almost every data structure used in the INET module.


```c
// linux/netdevice.h

```


register_netdevice	- register a network device


Take a completed network device structure and add it to the kernel interfaces. 
A %NETDEV_REGISTER message is sent to the netdev notifier chain. 0 is returned on success. A negative errno code is returned on a failure to set up the device, or if the name is a duplicate.

Callers must hold the rtnl semaphore. You may want register_netdev() instead of this.

BUGS:
The locking appears insufficient to guarantee two parallel registers will not get the same name.

```c
void cdev_init(struct cdev *, const struct file_operations *);

struct cdev *cdev_alloc(void);
```






对于设备树的处理 基本上就在 setup_arch() 这个函数里
以 ARM 为例

```c
void __init setup_arch(char **cmdline_p)
{
	setup_machine_fdt(atags_vaddr);
    unflatten_device_tree();
}
```



unflatten_device_tree 将设备树的各节点转换成相应的 struct device_node 结构体

```c
void __init unflatten_device_tree(void)
{
	void *fdt = initial_boot_params;

	/* Save the statically-placed regions in the reserved_mem array */
	fdt_scan_reserved_mem_reg_nodes();

	/* Populate an empty root node when bootloader doesn't provide one */
	if (!fdt) {
		fdt = (void *) __dtb_empty_root_begin;
		/* fdt_totalsize() will be used for copy size */
		if (fdt_totalsize(fdt) >
		    __dtb_empty_root_end - __dtb_empty_root_begin) {
			pr_err("invalid size in dtb_empty_root\n");
			return;
		}
		of_fdt_crc32 = crc32_be(~0, fdt, fdt_totalsize(fdt));
		fdt = copy_device_tree(fdt);
	}

	__unflatten_device_tree(fdt, NULL, &of_root,
				early_init_dt_alloc_memory_arch, false);

	/* Get pointer to "/chosen" and "/aliases" nodes for use everywhere */
	of_alias_scan(early_init_dt_alloc_memory_arch);

	unittest_unflatten_overlay_base();
}
```








## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)






