## Introduction

macOS 的网络排查有个前提需要先接受：**网络配置不存放在某个配置文件里，而是存放在系统配置数据库（configd）中**。改 DNS、改代理、改接口顺序都要通过 `networksetup` 或 `scutil` 写入这个数据库，直接编辑 `/etc/resolv.conf` 通常无效——那个文件在 macOS 上多数时候只是个符号链接或由系统生成的快照，改完会被覆盖。

```shell
$ /usr/sbin/scutil --dns
resolver #1
  nameserver[0] : 172.18.1.1
  if_index : 29 (en7)
  flags    : Request A records
  reach    : 0x00020002 (Reachable,Directly Reachable Address)
```

## Configuration: scutil and networksetup

两者分工不同：`scutil` 读的是运行时状态（含 configd 的动态存储），`networksetup` 写的是持久化配置。

```shell
scutil --dns                       # 当前生效的 DNS 解析器列表（含顺序与来源接口）
scutil --proxy                     # 当前代理配置
scutil --get HostName              # 主机名（还有 ComputerName / LocalHostName）
scutil -r example.com              # 可达性判定，比 ping 更符合系统自己的判断
scutil --nwi                       # 网络接口与默认路由概览

networksetup -listallnetworkservices        # 列出所有网络服务
networksetup -getdnsservers Wi-Fi           # 查 DNS
networksetup -setdnsservers Wi-Fi 8.8.8.8   # 设 DNS
networksetup -listpreferredwirelessnetworks en0
```

`scutil -r` 值得单独提一句：它走的是 `SCNetworkReachability`，与 App 判定网络是否可用的机制一致。用户报"应用说没网但浏览器能开"时，用它比 `ping` 更能复现应用的视角。

## Port and Connection

```shell
lsof -i :8080                      # 谁占用了这个端口
lsof -iTCP -sTCP:LISTEN -n -P      # 所有监听中的 TCP 端口
netstat -an -p tcp                 # 连接表
nettop -m tcp                      # 按进程实时看流量，iftop 的替代
nettop -p 1234                     # 只跟一个进程
nettop -d                          # delta 模式，显示增量而非累计
```

`nettop` 是这套工具里最有用的一个：`-m` 可选 `tcp`/`udp`/`route`，`-d` 切到增量模式后能直接看出"现在谁在传数据"，`-n` 关掉反向解析可以避免 DNS 拖慢输出。

## Routing and Interface

```shell
$ /sbin/route get default
   route to: default
destination: default
       gateway: 172.18.1.1
     interface: en7
         flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,GLOBAL>
              mtu       expire
              1500      0
```

`route get <host>` 比 `route -n` 更有用：它回答"到这个目标实际会走哪条路"，而不只是列出路由表。多网卡、VPN、Docker 网桥并存时这是定位出口的第一条命令。

接口命名也和 Linux 不同：`en0`/`en1` 是物理网卡（无线通常是 `en0` 或 `en1`，取决于机型），`lo0` 是回环，`utun*` 是 VPN 或系统隧道，`awdl0` 是 Apple Wireless Direct Link（AirDrop 与连续互通走的就是它），`bridge*` 是网桥。

```shell
ifconfig en0                       # 接口详情
ifconfig awdl0                     # AWDL，排查 AirDrop/Handoff 时会看到它
```

Wi-Fi 的详细信息要用一个不在 PATH 里的隐藏工具：

```shell
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s   # 扫描
```

本机实测该文件仍然存在（`-rwxr-xr-x root wheel`）。它不在 `/usr/bin` 里，需要用全路径或自己加别名。

## Quality and Capture

```shell
networkQuality                     # Apple 自己的响应式网络质量测试
networkQuality -c                  # 输出机器可读格式
networkQuality -s                  # 只测上行
networkQuality -I en0              # 指定接口
```

`networkQuality` 从 macOS Monterey 起自带，测的是"响应式"（responsiveness）而非单纯带宽，能给出上下行容量与往返延迟的分位数。它比 speedtest 更适合判断"为什么视频会议卡"这类问题。

抓包方面系统自带 `tcpdump`（`/usr/sbin/tcpdump`）：

```shell
sudo tcpdump -i en0 -w /tmp/cap.pcap      # 写文件供 Wireshark 分析
sudo tcpdump -i en0 port 443 -A           # 看明文内容
sudo tcpdump -i pktap,en0                 # pktap 能带上进程信息
```

`-i pktap` 是 macOS 特有的伪接口，抓到的包会附带 PID 与进程名——这在定位"是哪个进程发起的连接"时非常省事，是 Linux 上需要额外工具才能做到的。

## Troubleshooting Sequence

| 症状 | 第一步 |
| :--- | :--- |
| 端口被占 | `lsof -i :PORT` |
| DNS 解析不对 | `scutil --dns` 看 resolver 顺序；`networksetup -getdnsservers` 看配置 |
| 能 ping 通但应用说没网 | `scutil -r host` |
| 不知道走哪个出口 | `route get <host>` |
| 想看谁在传数据 | `nettop -d` |
| Wi-Fi 信号/漫游 | `airport -I` |
| 抓包定位进程 | `tcpdump -i pktap,en0` |

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Performance](/docs/CS/OS/mac/Tools/Performance.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)

## References

1. [networksetup — SS64 macOS 命令参考](https://ss64.com/osx/networksetup.html)
2. [Use networkQuality to test network performance](https://support.apple.com/en-us/102330)
