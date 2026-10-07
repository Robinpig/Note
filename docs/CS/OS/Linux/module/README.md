## Introduction

内核模块（Loadable Kernel Module，LKM）让内核在运行时动态扩展功能。它的存在理由很实际：内核集成编译时不可能把每个驱动、每种文件系统都塞进去——那样镜像会大到影响启动，而绝大多数硬件你根本不会插。模块机制把"编译期决定一切"变成"用到再加载"。

这个目录收两篇，分工是**机制**与**实践**：[LKM](/docs/CS/OS/Linux/module/LKM.md) 讲模块在原理上是什么、内核怎么把它接进来；[module](/docs/CS/OS/Linux/module/module.md) 讲怎么写出一个模块、编译加载时会踩什么坑。

理解模块有个关键前提：**`.ko` 不是可执行文件，而是一个 ELF 目标文件**。它不能自己运行，也没有 `main()`——内核把它当共享库一样加载、重定位、解析未定义符号，然后调用其中被 `module_init()` 标记的那个函数。这个视角一旦建立，模块的诸多限制（为什么要版本校验、为什么符号必须 `EXPORT_SYMBOL`）就都顺理成章了。

## How a Module Is Plugged into the Kernel

普通 ELF 可执行文件靠**动态链接器**在运行时解析对 `libc` 的引用；内核模块没有这个中间人，解析工作由**内核自己**完成。内核维护一张导出符号表——只有用 `EXPORT_SYMBOL()` / `EXPORT_SYMBOL_GPL()` 显式标记的符号才对外可见，其余的内部函数和数据模块根本无法引用。这既是封装手段，也是稳定 ABI 的边界所在。

模块里能调用 `printk`、`kmalloc`、`register_chrdev` 等等，靠的就是它们在导出表里。[LKM](/docs/CS/OS/Linux/module/LKM.md) 顺着 ELF 对象的结构把这条加载链路讲清了，并覆盖自动加载、模块参数、版本与签名。

## Lifecycle and Initialization Order

模块的一生很短：`insmod` 触发 `init_module` 系统调用（或 `finit_module` 从文件描述符加载），内核完成重定位后调用模块的 `init` 函数；卸载时调 `exit` 函数并释放。这一对函数由 `module_init()` / `module_exit()` 注册，[module](/docs/CS/OS/Linux/module/module.md) 给出了最小可编译的例子。

有一处容易忽略的约定：**同一套 `module_init` 宏，编成模块时在加载那一刻执行，编进内核时则退化为启动过程中的一次 initcall 调用**——具体落在 `device_initcall` 这一级。这意味着模块的初始化顺序不只是"谁先 insmod"的问题，在集成编译场景下它由 [initcall 分级](/docs/CS/OS/Linux/boot/README.md?id=initcall-why-initialization-order-is-a-hard-constraint) 决定。模块之间若存在依赖，就得选对 level，否则会出现"依赖的子系统还没初始化，自己的 init 就被调用了"。

当前内核里的顺序大体是：把模块本身送进内存（`finit_module`）→ 在模块自己的初始化函数里注册热插拔回调。**注意不要把注册顺序和硬件探测顺序搞混**——设备是在模块注册之后才被探测到的。

## Auto-loading and Visibility

手写 `insmod` 只是开发期的用法。生产环境靠自动加载：设备出现时内核发出 uevent，用户态 [udev](/docs/CS/OS/Linux/dev/udev.md) 根据设备属性匹配 `MODULE_ALIAS` 声明过的别名，再调用 `modprobe` 把对应模块拉起来。模块在 [sysfs](/docs/CS/OS/Linux/fs/sysfs.md) 下有对应节点，模块参数也通过它暴露（`/sys/module/<name>/parameters/`），这给了运行时调参一条不需要重新编译的路径。

版本与签名是加载前的最后一道关。模块携带编译时记录的 `vermagic`（内核版本、编译选项等信息），签名则包含版本与哈希两层含义——内核借此确认"这个模块是不是用当前这份内核代码编出来的"。版本不匹配会直接拒绝加载，避免结构体布局差异导致的内存破坏。

## When Not to Use Modules

模块并非所有场景的最优解。[LKM](/docs/CS/OS/Linux/module/LKM.md) 里有一节专门对比三种扩展方式：

- **built-in**——启动就要用的东西（根文件系统驱动、调度器策略）必须编进内核，否则根本无法挂载根分区；
- **LKM**——功能完整、需要访问内核数据结构、写起来是标准内核代码，代价是每次内核升级都要重新编译；
- **eBPF**——不需要编译模块、不依赖内核版本 ABI，但只能做"观测与有限干预"，改不了内核行为。见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。

选择的分界线大致是：**要新增功能就用 LKM，只想观察或做策略拦截就用 eBPF**。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
