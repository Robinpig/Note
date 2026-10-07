## Introduction

字符设备是最古老、也最普适的一类设备接口：串口、键盘、鼠标、帧缓冲、/dev/null、/dev/zero、GPU、KVM、FUSE 全都是。它的特征只有一条——**按字节流访问，语义由驱动自己定义**。块设备必须接受"以块为单位、可随机寻址、经 PageCache 缓存"这一整套约定，网络设备干脆没有文件节点；字符设备则把解释权完全交给驱动：可以只读、可以只写、可以 seek、也可以完全不 seek，可以带缓冲也可以不带。

这种自由度带来一个直接后果：**字符设备是 VFS 与驱动之间最薄的那一层**。驱动只要填一张 `struct file_operations` 表，剩下的路径查找、权限检查、fd 分配全由 VFS 负责。理解字符设备，本质上就是理解"一个 `/dev/xxx` 的文件操作怎么落到驱动代码里"。

本页沿这条主线展开：先解决**编号问题**（设备号如何定位驱动），再看内核里的**三层映射表**，然后是打开时那次关键的 **替换 file_operations**，之后是完整的注册/注销流程，最后是与设备模型、devtmpfs、用户态交互的咬合。与 [块设备驱动](/docs/CS/OS/Linux/dev/block.md) 对照着看效果最好——二者的设计取舍恰好相反。

## Device Number: The Kernel's Address

用户态打开 `/dev/ttyS0` 时，内核拿到的不是路径字符串，而是这个 inode 上记的一个 32 位数 `dev_t`。它把"哪个驱动"和"哪个实例"编在一起（`include/linux/kdev_t.h`）：

```c
#define MINORBITS	20
#define MINORMASK	((1U << MINORBITS) - 1)

#define MAJOR(dev)	((unsigned int) ((dev) >> MINORBITS))
#define MINOR(dev)	((unsigned int) ((dev) & MINORMASK))
#define MKDEV(ma,mi)	(((ma) << MINORBITS) | (mi))
```

高 12 位是**主设备号**，低 20 位是**次设备号**。约定是：主设备号标识驱动，次设备号标识该驱动下的具体实例——`/dev/ttyS0`、`/dev/ttyS1` 主设备号相同，靠次设备号区分。`ls -l` 里看到的 `4, 64` 就是这一对数字。

主设备号的分配有两条路，各有代价：

- **静态分配**：驱动写死一个号（如 misc 固定为 10）。好处是节点可预先创建、无需读 `/proc/devices`；代价是号段是全局稀缺资源，两个驱动撞号就只能二选一。LANANA 维护着官方分配表。
- **动态分配**：`alloc_chrdev_region()` 让内核挑一个空闲主设备号。好处是永不冲突；代价是节点必须在注册后才知道号，只能靠 devtmpfs/udev 动态创建——这在现代系统里已是默认做法。

`find_dynamic_major()` 的策略值得一看，它从**高号段往低号段**找（`CHRDEV_MAJOR_DYN_END` 起递减），耗尽后才尝试扩展区：

```c
static int find_dynamic_major(void)
{
	int i;
	struct char_device_struct *cd;

	for (i = ARRAY_SIZE(chrdevs)-1; i >= CHRDEV_MAJOR_DYN_END; i--) {
		if (chrdevs[i] == NULL)
			return i;
	}

	for (i = CHRDEV_MAJOR_DYN_EXT_START;
	     i >= CHRDEV_MAJOR_DYN_EXT_END; i--) {
		for (cd = chrdevs[major_to_index(i)]; cd; cd = cd->next)
			if (cd->major == i)
				break;

		if (cd == NULL)
			return i;
	}

	return -EBUSY;
}
```

先查 `chrdevs[]` 桶是否为空这一层是 O(1) 快路径，只有桶非空才遍历链表确认——这是内核里典型的"乐观检查 + 精确确认"写法。

## Three-Layer Mapping: From Device Number to Driver Function

一个 `dev_t` 要变成一次函数调用，中间经过三张表。这是字符设备最容易被忽略、也最该弄清楚的部分。

**第一层：号段注册表 `chrdevs`**。它不存 cdev，只记录"这段号被谁占了"（`fs/char_dev.c`）：

```c
static struct char_device_struct {
	struct char_device_struct *next;
	unsigned int major;
	unsigned int baseminor;
	int minorct;
	char name[64];
	struct cdev *cdev;		/* will die */
} *chrdevs[CHRDEV_MAJOR_HASH_SIZE];
```

`CHRDEV_MAJOR_HASH_SIZE` 是 255，按 `major % 255` 分桶、桶内按主次号有序链表。`__register_chrdev_region()` 的插入循环同时检查次号区间是否重叠——重叠就返回 `-EBUSY`。这一层回答的是"**这个号段有没有被占用**"，是纯记账，不参与打开路径。

**第二层：号到对象的映射 `cdev_map`**。这才是打开时要查的表，类型是 `struct kobj_map`（`drivers/base/map.c`）：

```c
struct kobj_map {
	struct probe {
		struct probe *next;
		dev_t dev;
		unsigned long range;
		struct module *owner;
		kobj_probe_t *get;
		int (*lock)(dev_t, void *);
		void *data;
	} *probes[255];
	struct mutex *lock;
};
```

同样是 255 桶按主设备号散列，桶内链表**按 range 升序**排列（插入时 `while (*s && (*s)->range < range) s = &(*s)->next`）。这个排序不是装饰：`kobj_lookup()` 遍历时一旦遇到 `p->range - 1 >= best` 就 break——因为后面的 range 只会更大、不可能更精确。于是**小范围优先**语义自然成立：一个覆盖 0~255 的宽注册和一个覆盖 0~3 的窄注册同时存在时，查 minor=2 会命中窄的那个。

注意 `kobj_map()` 会为每个涉及的主设备号各分配一个 probe（`n = MAJOR(dev + range - 1) - MAJOR(dev) + 1`），所以跨主设备号的注册会在多个桶里各留一份。

**第三层：cdev 本身**（`include/linux/cdev.h`）：

```c
struct cdev {
	struct kobject kobj;
	struct module *owner;
	const struct file_operations *ops;
	struct list_head list;
	dev_t dev;
	unsigned int count;
} __randomize_layout;
```

五个字段各有分工：`ops` 是最终要用的操作表；`dev`/`count` 是它负责的号段；`list` 挂所有**已打开**它的 inode（用于卸载时反查，见下面的 `cdev_purge`）；`kobj` 让 cdev 参与引用计数与 sysfs；`owner` 指向所属模块，打开时 `try_module_get` 防止模块被卸载。

## open: The Substitution Trick of chrdev_open

这里有个反直觉的事实：**所有字符设备文件的 `inode->i_fop` 初始值都是同一个占位表**。VFS 建 inode 时（`fs/inode.c`）：

```c
void init_special_inode(struct inode *inode, umode_t mode, dev_t rdev)
{
	inode->i_mode = mode;
	if (S_ISCHR(mode)) {
		inode->i_fop = &def_chr_fops;
		inode->i_rdev = rdev;
	} else if (S_ISBLK(mode)) {
		...
```

而 `def_chr_fops` 里只有一个能干活的回调（`fs/char_dev.c`）：

```c
const struct file_operations def_chr_fops = {
	.open = chrdev_open,
	.llseek = noop_llseek,
};
```

也就是说，open 之前内核**根本不知道**这个设备该由谁服务——它只知道设备号。真正的分派发生在 `chrdev_open()` 里，靠把 `filp->f_op` **整个换掉**完成：

```c
static int chrdev_open(struct inode *inode, struct file *filp)
{
	const struct file_operations *fops;
	struct cdev *p;
	struct cdev *new = NULL;
	int ret = 0;

	spin_lock(&cdev_lock);
	p = inode->i_cdev;
	if (!p) {
		struct kobject *kobj;
		int idx;
		spin_unlock(&cdev_lock);
		kobj = kobj_lookup(cdev_map, inode->i_rdev, &idx);
		if (!kobj)
			return -ENXIO;
		new = container_of(kobj, struct cdev, kobj);
		spin_lock(&cdev_lock);
		/* Check i_cdev again in case somebody beat us to it while
		   we dropped the lock. */
		p = inode->i_cdev;
		if (!p) {
			inode->i_cdev = p = new;
			list_add(&inode->i_devices, &p->list);
			new = NULL;
		} else if (!cdev_get(p))
			ret = -ENXIO;
	} else if (!cdev_get(p))
		ret = -ENXIO;
	spin_unlock(&cdev_lock);
	cdev_put(new);
	if (ret)
		return ret;

	ret = -ENXIO;
	fops = fops_get(p->ops);
	if (!fops)
		goto out_cdev_put;

	replace_fops(filp, fops);
	if (filp->f_op->open) {
		ret = filp->f_op->open(inode, filp);
		if (ret)
			goto out_cdev_put;
	}

	return 0;

 out_cdev_put:
	cdev_put(p);
	return ret;
}
```

这段代码有几个值得记住的细节：

1. **双重检查加锁**。为了调 `kobj_lookup()`（可能睡眠、可能触发模块加载）必须先放掉 `cdev_lock`，放锁期间别的 CPU 可能已经填好 `inode->i_cdev`，所以重新持锁后要再查一次。这是教科书式的 `lookup + insert` 竞态处理。
2. **inode 缓存**。第一次打开查表，之后 `inode->i_cdev` 直接命中，同一文件的后续 open 不再走 `kobj_lookup`。同时该 inode 被挂进 `cdev->list`，于是 cdev 知道"有哪些 inode 引用我"。
3. **`replace_fops()`**。这是整个机制的枢纽：把驱动的 `file_operations` 装进 `filp`，此后这个 fd 的 read/write/ioctl 全部直达驱动。**注意替换只影响这一个 `struct file`**，其他进程打开同一设备会各自再走一遍。
4. **`.owner` 与引用计数**。`fops_get()` 会 `try_module_get(p->ops->owner)`。驱动忘写 `.owner = THIS_MODULE` 的后果就在这里——模块可以在设备还开着时被 rmmod，然后 fd 上的每次调用都跳到已卸载内存。

### When the Device Node Does Not Exist: Auto-Loading

如果 `kobj_lookup()` 在 255 个桶里都没找到，会退化到 `base_probe`：

```c
static struct kobject *base_probe(dev_t dev, int *part, void *data)
{
	if (request_module("char-major-%d-%d", MAJOR(dev), MINOR(dev)) > 0)
		/* Make old-style 2.4 aliases work */
		request_module("char-major-%d", MAJOR(dev));
	return NULL;
}
```

它返回 NULL，但副作用是触发 `modprobe char-major-10-232` 这样的模块加载请求（modalias 机制，见 [LKM](/docs/CS/OS/Linux/module/LKM.md)）。驱动装载后会注册自己的 cdev，`kobj_lookup()` 里 `goto retry` 再查一遍就命中了。这就是"设备节点先于驱动存在"也能工作的原因——前提是驱动模块写了正确的 `MODULE_ALIAS`。

## Operations Set: file_operations

驱动的全部能力都体现在这张表上（6.12 `include/linux/fs.h`）：

```c
struct file_operations {
	struct module *owner;
	fop_flags_t fop_flags;
	loff_t (*llseek) (struct file *, loff_t, int);
	ssize_t (*read) (struct file *, char __user *, size_t, loff_t *);
	ssize_t (*write) (struct file *, const char __user *, size_t, loff_t *);
	ssize_t (*read_iter) (struct kiocb *, struct iov_iter *);
	ssize_t (*write_iter) (struct kiocb *, struct iov_iter *);
	int (*iopoll)(struct kiocb *kiocb, struct io_comp_batch *,
			unsigned int flags);
	int (*iterate_shared) (struct file *, struct dir_context *);
	__poll_t (*poll) (struct file *, struct poll_table_struct *);
	long (*unlocked_ioctl) (struct file *, unsigned int, unsigned long);
	long (*compat_ioctl) (struct file *, unsigned int, unsigned long);
	int (*mmap) (struct file *, struct vm_area_struct *);
	int (*open) (struct inode *, struct file *);
	int (*flush) (struct file *, fl_owner_t id);
	int (*release) (struct inode *, struct file *);
	int (*fsync) (struct file *, loff_t, loff_t, int datasync);
	int (*fasync) (int, struct file *, int);
	int (*lock) (struct file *, int, struct file_lock *);
	unsigned long (*get_unmapped_area)(struct file *, unsigned long, unsigned long, unsigned long, unsigned long);
	int (*check_flags)(int);
	int (*flock) (struct file *, int, struct file_lock *);
	ssize_t (*splice_write)(struct pipe_inode_info *, struct file *, loff_t *, size_t, unsigned int);
	ssize_t (*splice_read)(struct file *, loff_t *, struct pipe_inode_info *, size_t, unsigned int);
	void (*splice_eof)(struct file *file);
	int (*setlease)(struct file *, int, struct file_lease **, void **);
	long (*fallocate)(struct file *file, int mode, loff_t offset,
			  loff_t len);
	void (*show_fdinfo)(struct seq_file *m, struct file *f);
	...
	ssize_t (*copy_file_range)(struct file *, loff_t, struct file *,
			loff_t, size_t, unsigned int);
	loff_t (*remap_file_range)(struct file *file_in, loff_t pos_in,
				   struct file *file_out, loff_t pos_out,
				   loff_t len, unsigned int remap_flags);
	int (*fadvise)(struct file *, loff_t, loff_t, int);
	int (*uring_cmd)(struct io_uring_cmd *ioucmd, unsigned int issue_flags);
	int (*uring_cmd_iopoll)(struct io_uring_cmd *, struct io_comp_batch *,
				unsigned int poll_flags);
} __randomize_layout;
```

对字符设备驱动而言，常用的只有其中一小部分，分组看更清楚：

| 分组 | 回调 | 说明 |
|---|---|---|
| 生命周期 | `open` / `release` / `flush` | `open` 做初始化与 `private_data` 赋值；`release` 在**最后一个** fd 关闭时调用（不是每次 close） |
| 数据读写 | `read` / `write`；`read_iter` / `write_iter` | 后者是向量化异步接口，`io_uring` 与 `readv/writev` 走它；两者可只实现其一，VFS 有转换层 |
| 定位 | `llseek` | 不支持 seek 的设备应设为 `noop_llseek` 或 `no_llseek`，否则用户态 lseek 会拿到错误的默认行为 |
| 控制 | `unlocked_ioctl` / `compat_ioctl` | 设备专用命令；`compat` 处理 32 位用户态跑在 64 位内核 |
| 事件 | `poll` / `fasync` | `poll` 接入 [select/poll/epoll](/docs/CS/OS/Linux/IO/multiplexing.md)；`fasync` 支持 SIGIO 异步通知 |
| 内存映射 | `mmap` / `get_unmapped_area` | 把设备内存或驱动缓冲直接映射到用户态，见 [mmap](/docs/CS/OS/Linux/mm/mmap.md) |
| 现代 I/O | `iopoll` / `uring_cmd` | 让设备接入 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md) 的轮询与命令直通 |
| 零拷贝 | `splice_read` / `splice_write` | 与管道互传，避免用户态中转 |

`fop_flags` 是 6.x 新增的能力位（如 `FOP_UNSIGNED_OFFSET` 给 `/dev/mem` 用），一般驱动留空即可。

## Registering a Character Device

完整流程是四步，前三步注册、最后一步建节点：

```c
static dev_t my_devno;
static struct cdev my_cdev;
static struct class *my_class;

static int __init my_init(void)
{
	int ret;

	/* ① 申请设备号——动态分配，baseminor=0，要 1 个 */
	ret = alloc_chrdev_region(&my_devno, 0, 1, "mydev");
	if (ret < 0)
		return ret;

	/* ② 初始化 cdev 并绑定操作集 */
	cdev_init(&my_cdev, &my_fops);
	my_cdev.owner = THIS_MODULE;

	/* ③ 加入内核的映射表——此后设备立刻可被打开 */
	ret = cdev_add(&my_cdev, my_devno, 1);
	if (ret < 0)
		goto err_unregister;

	/* ④ 建设备节点（经 devtmpfs）与 sysfs 目录 */
	my_class = class_create("myclass");
	device_create(my_class, NULL, my_devno, NULL, "mydev%d", MINOR(my_devno));
	return 0;

err_unregister:
	unregister_chrdev_region(my_devno, 1);
	return ret;
}
```

几个必须注意的点：

- **`cdev_init` 与 `cdev_alloc` 的区别**。`cdev_init()` 用调用者提供的存储空间（通常内嵌在驱动的私有结构里），release 时只做清理；`cdev_alloc()` 自己 `kzalloc`，release 时会 `kfree`。二者绑定的 `kobj_type` 不同：

  ```c
  static void cdev_default_release(struct kobject *kobj)
  {
  	struct cdev *p = container_of(kobj, struct cdev, kobj);
  	struct kobject *parent = kobj->parent;

  	cdev_purge(p);
  	kobject_put(parent);
  }

  static void cdev_dynamic_release(struct kobject *kobj)
  {
  	struct cdev *p = container_of(kobj, struct cdev, kobj);
  	struct kobject *parent = kobj->parent;

  	cdev_purge(p);
  	kfree(p);
  	kobject_put(parent);
  }
  ```

  选错的表现是：对 `cdev_init` 出来的 cdev 调 `cdev_del` 不会释放内存（正确，因为你提供内存），但你若在它还有引用时释放了宿主结构就会崩——这正是要靠 kobject 引用计数把 cdev 与宿主 `device` 的生命周期绑起来的原因。

- **`cdev_add()` 之后设备立刻可用**。这不是理论风险，内核注释写得很直白：

  > NOTE: Callers must assume that userspace was able to open the cdev and can call cdev fops callbacks at any time, even if this function fails.

  所以**初始化顺序不能反**：必须先把驱动内部状态（缓冲、硬件、锁）准备好，最后才 `cdev_add`。反过来写会开出一个窗口，用户态能在硬件还没就绪时进来。

- **`cdev_del()` 与 `unregister_chrdev_region()` 要都调**。前者从 `cdev_map` 摘掉映射并 `kobject_put`，后者把号段还给 `chrdevs`。只做前者会泄漏设备号，只做后者会让 `/dev` 节点还能打开（虽然新的 open 会失败，已开的 fd 还在）。

- **`cdev_purge()` 负责清理已开 inode**。卸载时若还有进程开着设备，它把所有 `inode->i_cdev` 清空、从 `cdev->list` 摘掉，避免 inode 比 cdev 活得久而产生悬垂指针：

  ```c
  static void cdev_purge(struct cdev *cdev)
  {
  	spin_lock(&cdev_lock);
  	while (!list_empty(&cdev->list)) {
  		struct inode *inode;
  		inode = container_of(cdev->list.next, struct inode, i_devices);
  		list_del_init(&inode->i_devices);
  		inode->i_cdev = NULL;
  	}
  	spin_unlock(&cdev_lock);
  }
  ```

  注意它**只解除关联，不阻止已经打开的 fd 继续调用**——真正防卸载的是 `.owner` 上的模块引用计数。

### Binding cdev and device Together

现代驱动几乎都让 cdev 与 `struct device` 共存于同一个宿主结构，此时应改用 `cdev_device_add()`，它把父子关系一并处理好（`fs/char_dev.c`）：

```c
int cdev_device_add(struct cdev *cdev, struct device *dev)
{
	int rc = 0;

	if (dev->devt) {
		cdev_set_parent(cdev, &dev->kobj);

		rc = cdev_add(cdev, dev->devt, 1);
		if (rc)
			return rc;
	}

	rc = device_add(dev);
	if (rc && dev->devt)
		cdev_del(cdev);

	return rc;
}
```

`cdev_set_parent()` 把 cdev 的 kobject 父节点设为 device 的 kobject，于是**只要还有人引用 cdev（即设备还开着），device 就不会被释放**。这解决了驱动最常见的 use-after-free：用户态 open 着设备，同时设备被热拔出。

## Where Device Nodes Come From

`cdev_add` 只建立内核内部的映射，用户态看不到任何东西。`/dev/mydev0` 这个入口由 [设备模型](/docs/CS/OS/Linux/dev/device.md) 与 devtmpfs 合作生成：`device_add()` 里（`drivers/base/core.c`）有这段：

```c
	if (MAJOR(dev->devt)) {
		error = device_create_file(dev, &dev_attr_dev);
		if (error)
			goto DevAttrError;

		error = device_create_sys_dev_entry(dev);
		if (error)
			goto SysEntryError;

		devtmpfs_create_node(dev);
	}
```

即：**只要 `device->devt` 非零，`device_add()` 就会自动在 devtmpfs 上创建节点**。这也解释了为什么前面示例里 `class_create()` + `device_create()` 之后节点就出现了——不需要手动 `mknod`。

三者分工是：内核负责在 devtmpfs 上建出**最朴素**的节点（正确的主要/次要号、默认权限）；用户态 [udev](/docs/CS/OS/Linux/dev/udev.md) 监听 uevent，再按规则改权限、改属主、建稳定符号链接（`/dev/serial/by-id/...`）。纯手工验证时也可以 `mknod /dev/mydev0 c 240 0` 直接建节点——这正说明**节点只是 (类型, 主号, 次号) 三元组的一个具名入口**，不含任何驱动信息。

## Shortcut: miscdevice

如果一个驱动只需要**一个**设备号、且不想去申请主设备号，内核提供了 misc 子系统：所有 misc 设备共享主设备号 `MISC_MAJOR`（10），只用次设备号区分。结构极其简单（`include/linux/miscdevice.h`）：

```c
struct miscdevice  {
	int minor;
	const char *name;
	const struct file_operations *fops;
	struct list_head list;
	struct device *parent;
	struct device *this_device;
	const struct attribute_group **groups;
	const char *nodename;
	umode_t mode;
};
```

注册时（`drivers/char/misc.c`）：

```c
int misc_register(struct miscdevice *misc)
{
	dev_t dev;
	int err = 0;
	bool is_dynamic = (misc->minor == MISC_DYNAMIC_MINOR);

	INIT_LIST_HEAD(&misc->list);

	mutex_lock(&misc_mtx);

	if (is_dynamic) {
		int i = misc_minor_alloc();

		if (i < 0) {
			err = -EBUSY;
			goto out;
		}
		misc->minor = i;
	} else {
		struct miscdevice *c;

		list_for_each_entry(c, &misc_list, list) {
			if (c->minor == misc->minor) {
				err = -EBUSY;
				goto out;
			}
		}
	}

	dev = MKDEV(MISC_MAJOR, misc->minor);

	misc->this_device =
		device_create_with_groups(&misc_class, misc->parent, dev,
					  misc, misc->groups, "%s", misc->name);
	if (IS_ERR(misc->this_device)) {
		if (is_dynamic) {
			misc_minor_free(misc->minor);
			misc->minor = MISC_DYNAMIC_MINOR;
		}
		err = PTR_ERR(misc->this_device);
		goto out;
	}

	/*
	 * Add it to the front, so that later devices can "override"
	 * earlier defaults
	 */
	list_add(&misc->list, &misc_list);
 out:
	mutex_unlock(&misc_mtx);
	return err;
}
```

三个要点：

1. **次设备号可动态分配**。填 `MISC_DYNAMIC_MINOR`（255）即由 ida 分配；否则遍历链表查重，撞了返回 `-EBUSY`。
2. **注册即建节点**。`device_create_with_groups()` 一步完成 sysfs 目录 + devtmpfs 节点 + 属性组，驱动不用自己 `class_create`。
3. **自动填 `private_data`**。这是 misc 最实用的便利——`misc_open()` 在换 fops 之前就把 `struct miscdevice *` 塞进 `file->private_data`：

   ```c
   	/*
   	 * Place the miscdevice in the file's
   	 * private_data so it can be used by the
   	 * file operations, including f_op->open below
   	 */
   	file->private_data = c;

   	err = 0;
   	replace_fops(file, new_fops);
   	if (file->f_op->open)
   		err = file->f_op->open(inode, file);
   ```

   于是驱动连 `open` 都可以不实现，直接从 `file->private_data` 取回自己的 `miscdevice`（通常再 `container_of` 拿宿主结构）。`misc_open` 同样支持"节点存在但驱动未加载"时的 `request_module`。

misc 的代价是**打开时要遍历链表**找次号，且与所有 misc 设备共享主设备号 10——所以它只适合"一个驱动一个设备"的小设备。内核里用它的远比想象的多：KVM（232）、FUSE（229）、TUN/TAP（200）、UHID（239）、VHOST_NET（238）、loop-control（237）、device-mapper 控制节点（236）、HPET（228）、 watchdog（130）、hwrng（183）都在 `miscdevice.h` 里占着固定次号。

## Interacting from User Space

驱动运行在内核态，用户态传来的指针**不能直接解引用**——那个地址在当前页表里可能根本无效，或者是恶意构造的。必须用带检查的拷贝：`copy_to_user()` / `copy_from_user()` 内部先做 `access_ok()` 校验，越界返回未拷贝字节数（不是负 errno），失败要 `-EFAULT`。

ioctl 是字符设备的"万能后门"，命令号按方向/大小/类型/序号编码（`_IOR`/`_IOW`/`_IOWR`），驱动在 `unlocked_ioctl` 里 switch 分发。注意：ioctl 没有统一的编号管理机构，跨驱动撞号是常态，所以要在魔数里带上类型字段。

阻塞语义由驱动自己实现，标准做法是在 `read` 里检查数据是否就绪，不就绪就把当前任务挂到等待队列上睡眠，中断或写侧再唤醒——这套机制与 [惊群](/docs/CS/OS/Linux/proc/thundering_herd.md) 里 socket 的阻塞读完全同构。想让用户态能多路复用，就额外实现 `poll`（返回就绪掩码 + 注册等待队列），设备立刻获得被 [epoll](/docs/CS/OS/Linux/IO/epoll.md) 监听的能力。

## Comparison with Block Devices

两类接口的设计取舍几乎处处相反，对照着看最容易记住：

| 维度 | 字符设备 | 块设备 |
|---|---|---|
| 访问单位 | 字节流，语义驱动自定 | 固定大小块（通常 512B/4K） |
| 随机访问 | 可选（`llseek` 可为 `noop_llseek`） | 必须支持按块寻址 |
| 缓存 | 无（除非驱动自己做） | 必经 PageCache，由内核统一管理 |
| 核心结构 | `struct cdev` | `struct gendisk` + `request_queue` |
| 操作集 | `file_operations`（面向 fd） | `block_device_operations`（面向 disk） |
| 打开路径 | `chrdev_open` 查 `cdev_map` 换 fops | `blkdev_open` 经 `bd_acquire` 找 gendisk |
| I/O 下发 | 驱动直接处理 | bio → request → blk-mq → 驱动 |
| 挂载文件系统 | 不能 | 能 |
| 典型例子 | tty、/dev/null、KVM、GPU | 磁盘、SSD、loop |

一句话概括：**字符设备给驱动自由度，块设备给内核控制权**。要不要内核帮忙做缓存、做 I/O 调度、做回写，是选择二者的根本判据——这也是为什么 loop 设备明明是"用文件模拟磁盘"却必须做成块设备。

## Crossing Subsystem Boundaries

字符设备不是孤立的，它几乎和内核每个子系统都有接触面：

- **VFS**：路径查找、权限检查、fd 管理全部复用通用文件机制，驱动只看到 `struct file` / `struct inode`。完整链路见 [文件管理链路总图](/docs/CS/OS/Linux/fs/README.md)。
- **设备模型**：cdev 内嵌 kobject，因而自动获得引用计数、sysfs 呈现与热插拔事件；`cdev_device_add()` 把 cdev 的生命周期挂到 `device` 之下，见 [device](/docs/CS/OS/Linux/dev/device.md)。
- **devtmpfs 与 udev**：节点由内核在 devtmpfs 建出、由用户态 udev 加工，见 [udev](/docs/CS/OS/Linux/dev/udev.md)。
- **内存**：`mmap` 让设备内存直接进用户态页表，涉及 VMA、缺页与页保护，见 [mmap](/docs/CS/OS/Linux/mm/mmap.md)。
- **I/O 多路复用**：实现 `poll` 即接入 select/poll/epoll；实现 `uring_cmd` 可接入 io_uring，见 [I/O 链路总图](/docs/CS/OS/Linux/IO/README.md)。
- **中断与睡眠**：驱动常在 [中断](/docs/CS/OS/Linux/Interrupt.md) 上半部收数据，再唤醒等待队列上的读进程；不能在中断上下文睡眠，所以拷贝与复杂处理通常交给 [workqueue](/docs/CS/OS/Linux/workqueue.md)。

## Links

- [设备驱动链路总图](/docs/CS/OS/Linux/dev/README.md)
- [内核模块与自动加载](/docs/CS/OS/Linux/module/LKM.md)
- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)

## References

1. [Character device drivers — Linux Device Drivers, 3rd Edition](https://lwn.net/Kernel/LDD3/)
2. [The Linux Kernel Driver API — driver model](https://www.kernel.org/doc/html/latest/driver-api/driver-model/overview.html)
3. [Linux allocated devices (LANANA)](https://www.kernel.org/doc/html/latest/admin-guide/devices.html)
4. [devtmpfs — kernel documentation](https://www.kernel.org/doc/html/latest/filesystems/tmpfs.html)
