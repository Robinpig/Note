## Introduction

通常操作系统启动都是由Bootloader 

- Gurb

解压bzImage

vmlinux




x86 开启a20

```c
/*
 * Actual routine to enable A20; return 0 on ok, -1 on failure
 */

#define A20_ENABLE_LOOPS 255    /* Number of times to try */

int enable_a20(void)
{
       int loops = A20_ENABLE_LOOPS;
       int kbc_err;

       while (loops--) {
           /* First, check to see if A20 is already enabled
          (legacy free, etc.) */
           if (a20_test_short())
               return 0;
           
           /* Next, try the BIOS (INT 0x15, AX=0x2401) */
           enable_a20_bios();
           if (a20_test_short())
               return 0;
           
           /* Try enabling A20 through the keyboard controller */
           kbc_err = empty_8042();

           if (a20_test_short())
               return 0; /* BIOS worked, but with delayed reaction */
    
           if (!kbc_err) {
               enable_a20_kbc();
               if (a20_test_long())
                   return 0;
           }
           
           /* Finally, try enabling the "fast A20 gate" */
           enable_a20_fast();
           if (a20_test_long())
               return 0;
       }
       
       return -1;
}
```


```c
static int a20_test(int loops)
{
    int ok = 0;
    int saved, ctr;

    set_fs(0x0000);
    set_gs(0xffff);

    saved = ctr = rdfs32(A20_TEST_ADDR);

    while (loops--) {
        wrfs32(++ctr, A20_TEST_ADDR);
        io_delay(); /* Serialize and make delay constant */
        ok = rdgs32(A20_TEST_ADDR+0x10) ^ ctr;
        if (ok)
            break;
    }

    wrfs32(saved, A20_TEST_ADDR);
    return ok;
}
```


对于x86 i386架构，这部分代码在arch/x86/kernel/head_32.S

对于x86 x64架构，这部分代码在arch/x86/kernel/head_64.S

以arm64 架构为例

```c
/*
 * Kernel startup entry point.
 * ---------------------------
 *
 * The requirements are:
 *   MMU = off, D-cache = off, I-cache = on or off,
 *   x0 = physical address to the FDT blob.
 *
 * Note that the callee-saved registers are used for storing variables
 * that are useful before the MMU is enabled. The allocations are described
 * in the entry routines.
 */
```


在内核源代码的init/目录中只有一个文件main.c。系统在执行完boot/目录中的head.s 程序后就将
执行权交给了main.c。


链接脚本最终会把大量编译好的二进制文件（.o文件）合并为一个二进制可执行文件，也就是把每一个二进制文件整合到一个大文件中
这个大文件有一个总的代码/数据/未初始化数据段，这个链接脚本在Linux内核里面其实就是vmlinux.lds.S文件


## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)