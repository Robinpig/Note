## Introduction

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


















## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)






