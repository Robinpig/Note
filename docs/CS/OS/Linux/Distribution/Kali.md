## Introduction

Kali Linux 是基于 [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) 的开源发行版，面向信息安全任务：渗透测试、安全研究、计算机取证与逆向工程。预装数百款安全工具（nmap、Metasploit、Wireshark、Burp Suite 等），支持裸机、虚拟机、WSL、树莓派与 Docker 镜像等多种交付形态。

> 注：名称取自印度教女神"时母"（Kali），注意不要与印度喀拉拉邦的 Keralite 混淆——这是很常见的拼写错误，本文件早期也曾误拼为 `Kail.md`，现已更正。

安全研究视角的内核关联：渗透与取证大量依赖内核机制——系统调用跟踪（[strace](/docs/CS/OS/Linux/Tools/strace.md)）、`/proc` 与内存取证（[procfs](/docs/CS/OS/Linux/fs/proc.md)）、网络抓包（[network](/docs/CS/OS/Linux/net/network.md)）、容器逃逸（[namespace](/docs/CS/OS/Linux/namespace.md)）。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Debian](/docs/CS/OS/Linux/Distribution/Debian.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
