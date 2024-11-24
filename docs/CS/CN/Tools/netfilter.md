## Introduction

netfilter围绕着网络层有5个NF_HOOK
- PRE_ROUTING
- LOCAL_IN
- FORWARD
- OUTPUT
- POSY_ROUTING

Netfilter 允许同一个钩子处注册多个回调函数，每个回调函数有明确的优先级，确保按照预定顺序触发。一个钩子处的多个回调函数串联起来便形成了一条“回调链”（Chained Callbacks）

## iptables
Netfilter 的钩子回调固然强大，但得通过程序编码才能使用，并不适合系统管理员日常运维。为此，基于 Netfilter 框架开发的应用便出现了，如 iptables

Netfilter 中的钩子，在 iptables 中称作“链”（chain）

## Links

- [IP](/docs/CS/CN/IP.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [WireShark](/docs/CS/CN/Tools/WireShark.md)
- [Xcap](/docs/CS/CN/Tools/Xcap.md)