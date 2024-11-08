




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