## Introduction


compile
```shell
make
```

```shell
cp *.ko */kmodules/

insmod *.ko

BASEINCLUDE ?= /lib/modules/${shell uname -r}/build
```



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



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)