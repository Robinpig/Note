## Introduction



Swap



Swap space  when RAM all filedl and limit 2G

init

```c
// mm/vmscan.c
static int __init kswapd_init(void)
{
       int nid;

       swap_setup();
       for_each_node_state(nid, N_MEMORY)
              kswapd_run(nid);
       return 0;
}

module_init(kswapd_init)
```



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)