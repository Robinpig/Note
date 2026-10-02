## Introduction

Wireshark 是最流行的 **图形化网络协议分析器**（network protocol analyzer），可实时抓取并深度解析几乎全部主流协议的分组，是排障、协议学习与安全分析的标配工具。它偏「抓包 + 解码」，与 tcpdump（命令行抓包）、Xcap（主动发包）、netfilter（内核过滤）互补。

## 抓取与权限

Wireshark 的抓包引擎是 **dumpcap**（借 libpcap / Npcap 调用内核），UI 只负责解析与展示，因此普通用户也无需 root 即可分析已抓文件。

```shell
# RPM 系
sudo yum install wireshark
# DEB 系
sudo apt-get install wireshark wireshark-qt
```

Linux 桌面若提示无权限访问抓包设备（`/dev/bpf*` 权限为 `700`），将当前用户加入 `wireshark` 组或临时改属主：

```shell
cd /dev
ls -a | grep bp        # 列出 bpf* ，默认 700
whoami                 # robin
sudo chown robin:admin bp*
```

## 显示过滤器

Wireshark 区分两类过滤：

- **抓包过滤器（Capture Filter）**：BPF 语法（`tcp port 80`），在抓包前就丢弃无关流量，省内存。
- **显示过滤器（Display Filter）**：抓完后用 Wireshark 表达式（如 `http.request.method == "GET"`、`tcp.analysis.retransmission`）交互筛选，语法更丰富。

## 协议解析与排障技巧

- **协议树（Packet Details）**：分层展开 Ethernet → IP → TCP → 应用层，逐字段查看。
- **Follow TCP Stream**：把某条连接的双向数据重组为可读文本，快速看 HTTP/Redis 等明文会话。
- **Relative sequence numbers**：默认开启「相对序号」让 SYN 从 0 起、便于阅读；可在 `Preference → Protocols → TCP → Relative sequence numbers` 关闭，改看真实 32 位序号（排错乱序/重传时更准）。

## 与 tcpdump 的分工

| 工具 | 形态 | 擅长 |
|---|---|---|
| Wireshark | 图形化 | 深度解析、协议树、交互过滤、流重组 |
| tcpdump | 命令行 | 服务器无界面快速抓包、脚本化 |

实战常两者结合：服务端 `tcpdump -w cap.pcap` 抓包，下载到本地用 Wireshark 打开分析。

## Links

- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [Xcap](/docs/CS/CN/Tools/Xcap.md)
- [netfilter](/docs/CS/CN/Tools/netfilter.md)

## References

- [Wireshark Official Documentation](https://www.wireshark.org/docs/)
- [Wireshark User's Guide](https://www.wireshark.org/docs/wsug_html/)
