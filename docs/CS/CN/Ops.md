## Introduction

本页与 [CN](/docs/CS/CN/CN.md) 分工：枢纽页讲协议「应该是怎么工作的」，本页讲网络「实际怎么运维的」——分层视角、故障分类、监控与定位体系，都是大规模数据中心网络（南北向探测流、拓扑定位、告警收敛）的实战方法。协议与工具的基础知识见 CN 枢纽的知识地图。

## Layered View of the Network

运维视角下把网络世界细分为六大层次，定位问题时先问「问题落在哪一层」：

| 层 | 内容 |
| :-- | :-- |
| 链路层 | 各类物理链路：机架内互联、跨机房、跨地域长途链路 |
| 硬件设施层 | 交换机、路由器、网关等转发设备 |
| 系统软件层 | 运行于硬件之上的资源管理与调度系统 |
| 协议层 | BGP、OSPF、ISIS 等路由协议，决定报文行进轨迹 |
| 配置层 | 设备上配置的具体参数 |
| 流量层 | 承载实际业务的流量运作层面 |

## Fault Taxonomy

网络故障大致归结为五大类别：

1. **链路故障**：链路抖动、频繁切换、传输质量恶化、链路中断、数据包错误。
2. **硬件故障**：板卡异常、芯片失效、CPU 或内存过载、端口异常、CRC 校验错误。
3. **软件故障**：堆叠分裂、软件缺陷、COPP 限速等控制平面保护机制的副作用。
4. **协议故障**：协议抖动、路由劫持、路由黑洞、转发表项错误。
5. **流量故障**：流量峰值过高导致丢包、优先级队列积压、Incast 现象、微突发流量。

故障诱因涵盖硬件、软件乃至人为因素。规模越大、变更越频繁，故障概率越高——完全避免近乎不可能，因此高可用的关键不是「不出故障」而是「故障自愈」：网络设计具备冗余机制，故障发生时能迅速把故障设备从网络中隔离。以往依赖运维人员凭经验排查隔离的方式难以复制推广，可持续的出路是**系统化、自动化的故障快速发现与定位机制**。

## Fault Detection

三个视角互补，实际运营中通常组合使用：

- **端侧监控**：在终端监测重传数据包等现象来识别网络故障。优点是与业务感知紧密贴合、精准度较高；短板是依赖端侧上报机制（故障本身可能阻碍数据上报），对客户端 CPU 占用有严格要求，且难以直接锁定故障设备，需借助其他定位工具辅助判断。
- **设备侧监控**：收集设备的错误包、丢包、端口状态、CPU/内存、流量水位与日志等指标。优势是直截了当，能按成因制定针对性 SOP；局限是无法穷举所有故障类型，对策略配置类故障引发的数据平面问题或**静默丢包**往往无法察觉。
- **链路监控**：让探测流覆盖所有可能的网络路径，理论上能 100% 发现故障；不足是确定具体故障设备时仍需结合其他工具。

链路监控的核心思路：用**南北向的探测流**遍历所有层次化的网络拓扑（机房集群、POD、SR、FITGROUP 等层级），某层级出现故障时，对失败流的目的 IP 做聚合分析，即可迅速定位到故障点。

### Alert Deduplication and Convergence

目标是让运维与故障定位只关注少量有效告警。流程分三步：先对数据**过滤降噪**，再对告警做**收敛**（低维度告警归并到高维度告警），同时针对探测源做收敛（减少单一源端问题导致的多目标告警）。常见噪音来源：网络隔离造成的长期通信不畅、服务器主动运维带来的丢包、长途传输抖动导致的丢包。手段上采用黑名单过滤与告警收敛，力求把每日告警数量压缩到个位数。

## Fault Localization

定位体系由四部分组成：基于网络事件的定位技术、基于 Flow 的精准定位、热点路径分析，以及综合定位决策系统——由后者依据网络事件与丢包分布特征，科学决策最优定位结果。

- **拓扑定位（庖丁定位）**：根据端口互联关系，用图计算算法构建最短路径，生成网络物理与虚拟拓扑；再依据拓扑上的设备拉取各类异常事件（SMT、SISLOG 巡检异常、其他业务异常日志），揭示设备遭遇的问题及其变化趋势。它是线下故障定位的关键门户。
- **Flow 统计（NDB 流统）**：借助带特殊 DSCP 标记的探测报文，配合拓扑检测每个层级网络设备的报文进出数量是否一致，精准定位丢包集中的设备。实践中暴露的问题：DSCP 标记污染导致基数统计不准、设备端口众多时流统计数读取经常超时。改进办法是在发送端统计发出与接收报文数量的一致性，在首尾设备采集流统计数以判断是否存在丢包，并「尽力而为」地把拓扑与设备流统计数叠加成流量拓扑，提升定位准确性。
- **热点路径定位**：对丢包探测流做正反向 trace，追踪形成的多条路径，找出其中的热点设备以识别故障所在。
- **故障回放**：把整个流程的关键信息与决策依据可视化展现并复盘分析，对定位结果做标注，持续评估与改进工具效能。

以阿里内外网环境的实践为参照，已覆盖场景下的故障发现率达到 90%，定位准确率达到 85%——这两个数字是「链路监控 + 设备侧监控」组合拳的成效基准。

## Network Management and Protocol Ossification

网络中间设备（middleboxes）的演进速度远慢于边缘的客户端与服务器：这些设备部署于特定年代，只认识当时的协议特性集。引入新特性或改变行为，有被判定为「坏流量」而遭丢弃或延迟的风险——用户干脆就不启用这些特性。这种现象称为**协议僵化（protocol ossification）**，它是 QUIC/HTTP/3 设计时必须绕开的现实约束（QUIC 的「不可变握手与可被中间设备识别」设计正与此对抗，见 [QUIC](/docs/CS/CN/HTTP/QUIC.md)）。

网络管理的标准协议是 **SNMP**（Simple Network Management，[RFC 1157](https://www.rfc-editor.org/rfc/rfc1157)）：管理站通过 GET/SET 从被管设备读取或修改对象、设备通过 TRAP 主动上报事件，被管对象的结构由 MIB 描述。SNMPv1/v2c 的社区字符串（community string）是纯明文共享密钥，只有 v3 才提供真正的认证与加密——生产环境应默认禁用前两代。

## Proxy Quick Start: HAProxy

HAProxy 是事件驱动的四层/七层代理，配置即改即生效（reload 不断流），详细机制见 [HAProxy](/docs/CS/CN/Tools/HAProxy.md)。

```shell
# Debian/Ubuntu
apt install haproxy

# 配置文件一般位于 /etc/haproxy/haproxy.cfg，编辑后：
service haproxy restart
```

最小可用的七层反代骨架：

```text
frontend web
    bind *:80
    default_backend servers

backend servers
    balance roundrobin
    server web1 10.0.0.1:80 check
    server web2 10.0.0.2:80 check
```

> [!TIP]
> 改完配置先 `haproxy -c -f /etc/haproxy/haproxy.cfg` 做语法检查再 reload：haproxy 对未知指令是**硬报错**，不会静默忽略，但报错行号指向的是症状而非根因，写错 backend 名时尤其容易看懵。

## Beyond C10k: The C10M Problem

C10k 问题的解法与内核演进（epoll、io_uring、内核旁路）见 [C10k](/docs/CS/CN/C10k.md)。在 C10k 之上还有 **C10M**：单机千万级并发连接。Robert Graham 在 Shmoocon 2013 的演讲《C10M Defending The Internet At Scale》给出了激进判断——「靠内核解决不了这个问题，内核恰恰是问题所在」，路线是绕开内核协议栈（PF_RING、Netmap、Intel DPDK 等内核旁路方案直接接管网卡）。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [C10k](/docs/CS/CN/C10k.md)
- [HAProxy](/docs/CS/CN/Tools/HAProxy.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [QUIC](/docs/CS/CN/HTTP/QUIC.md)
- [Firewall](/docs/CS/CN/CyberSecurity/Firewall.md)

## References

1. [RFC 1157 - A Simple Network Management Protocol (SNMP)](https://www.rfc-editor.org/rfc/rfc1157)
2. [The C10K problem](http://www.kegel.com/c10k.html)
