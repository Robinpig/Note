## Introduction



## L4

L4 LB work on transport layer **forward**

| Model              | Advantage                                                    | Disadvantage         |
| ------------------ | ------------------------------------------------------------ | -------------------- |
| DR                 | High performance                                             |                      |
| NAT(DNAT)          | No change for app server                                     | LB must be a gateway |
| TUNNEL             |                                                              |                      |
| FULLNAT(SNAT+DNAT) | 1. No change for app server 2. Low network environment requirements | Lost client ip       |

Why don't use LVS?

High performance.

Meituan using MGW based on DPDK

[Maglev: A Fast and Reliable Software Network Load Balance](http://static.googleusercontent.com/media/research.google.com/zh-CN//pubs/archive/44824.pdf)



## L7

L7 LB working on application layer, need to through TCP/IP stack and resolve request data **proxy**

## Examples

[Facebook Katran](https://github.com/facebookincubator/katran)

