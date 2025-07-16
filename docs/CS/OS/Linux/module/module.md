## Introduction

内核模块是 Linux 支持动态功能扩展的最主要机制 内核代码中有很多模块 用户也可以编写外部的模块 再将模块动态添加到内核中执行



compile
```shell
make
```

```shell
cp *.ko */kmodules/

insmod *.ko

BASEINCLUDE ?= /lib/modules/${shell uname -r}/build
```


module 开发比较典型的是初始化和退出函数
由于模块可以由外部代码编写 内核版本有很多个 所以内核必须确保该模块是使用当前内核代码编译出来的 否则会执行报错
每个模块在编译时会从内核获取版本号 内核在install新的模块时会检测签名是否一致
模块签名有两层含义 版本号和 哈希签名


```c
nclude <linux/init.h>
#include <linux/module.h>


static init __init my_test_init(void)
{
        printk("my first kernel module init\n");
        return 0;
}       

static void __exit my_test_exit(void)
{       
        printk("goodbye\n");
}       

module_init(my_test_init);
module_exit(my_test_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("robin");
MODULE_DESCRIPTION("my test kernel module");
MODULE_ALIAS("my test");

```

当模块之间存在依赖关系 需要使用带初始化顺序的 init方法 这个初始化顺序也是 Linux 内核在启动过程内部初始化的顺序

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)