## Introduction

[Xcap](http://xcap.weebly.com/) 是一款运行在 Windows 上的 **数据包生成与发送工具**（packet generator & sender）。与 tcpdump / Wireshark 这类「抓取并分析已有流量」的工具相反，Xcap 让你**手工构造任意报文**（自定义各层协议字段），再从指定网卡发送出去，常用于协议测试、防火墙/IDS 规则验证、网络设备的健壮性压测。

## 核心能力

- **报文构造**：从 Ethernet / IP / TCP / UDP / ICMP 等逐层填充字段（源/目的 MAC、IP、端口、标志位、载荷），支持校验和自动计算。
- **指定出口**：选择本机某个网络接口（interface）作为发送通道，可叠加 VLAN / MPLS 等标签。
- **发送模式**：单次发送、连续发送（按速率/数量），便于模拟洪泛或重放。

## 与抓包/分析工具的分工

| 工具 | 角色 | 典型用途 |
|---|---|---|
| Xcap | 生成 + 发送 | 主动构造异常/边界报文做测试 |
| tcpdump | 抓取（命令行） | 服务端快速抓包过滤 |
| Wireshark | 抓取 + 深度解析 | 图形化协议分析、排障 |
| netfilter | 内核过滤/改写 | iptables/nftables 流量控制 |

Xcap 处在「主动发包」一端，后三者偏「被动观测/控制」，常组合使用：用 Xcap 发特定包，再用 Wireshark 验证对端响应。

## Links

- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [WireShark](/docs/CS/CN/Tools/WireShark.md)
- [netfilter](/docs/CS/CN/Tools/netfilter.md)

## References

- [科来网络分析系统](https://www.colasoft.com.cn/download/capsa.php)
- [Xcap - Packet Generator](http://xcap.weebly.com/)
