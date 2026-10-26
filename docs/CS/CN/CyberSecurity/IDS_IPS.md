## Introduction

IDS（Intrusion Detection System，入侵检测）回答"网络上正在发生什么异常"，IPS（Intrusion Prevention）则把同样的检测能力串接进转发路径、直接丢弃恶意报文。与 [Firewall](/docs/CS/CN/CyberSecurity/Firewall.md) 的分工：防火墙按**静态策略**放行（"只允许 443"），检测系统按**行为与内容**发现（"有人在扫 WebLogic 漏洞"）——前者不需要知道什么是恶意，后者不需要有拦截权限。这一页讲检测方法、开源工具谱系、部署形态与告警工程；抓包层面的手工分析在 [WireShark](/docs/CS/CN/Tools/WireShark.md)。

## Detection Methods

四类方法按"知道什么"排列，现实产品都是混合体：

| 方法 | 原理 | 强项 | 弱项 |
| :--- | :--- | :--- | :--- |
| 误用/签名 | 匹配已知恶意特征（字节序列、字段组合） | 精确、可解释、有海量现成规则 | 对变形与未知攻击零覆盖，规则滞后于漏洞披露 |
| 异常/统计 | 为正常流量建基线（流量模型、熵、端口分布），偏离即告警 | 能发现未知攻击与慢速扫描 | 基线难维护，误报多，需长期调优 |
| 协议规范 | 按 RFC 逐字段校验协议实现（畸形分片、非法标志组合） | 对 0day 的畸形利用天然有效 | 只覆盖已知协议语义 |
| 信誉 | 比对威胁情报（IP/域名/文件哈希黑名单） | 零成本挡住已知坏人 | 纯黑名单、无检测能力；IP 信誉对云主机误伤大 |

签名是绝对主力（ET Open、Snort 社区/Talos 规则都是万级规模），异常与协议方法是补充，信誉是前置过滤器。**没有一种方法能单独成立**，这是厂商宣传里最需要警惕的话术。

## The Open-Source Stack

三个工具不是竞品关系，而是三层不同的能力（版本均为 2026-10 核实）：

| 工具 | 定位 | 现行版本与事实 |
| :--- | :--- | :--- |
| **Snort** | 规则驱动的 NIDS/NIPS，1998 年 Martin Roesch 创建，Sourcefire 2013 年被 Cisco 收购；GPLv2+ | Snort 3.12.x（3.12.4.0，2026-10）；规则分 Community（免费）、Registered、Subscriber（Talos 实时）三层，Talos lightSPD 单一包覆盖所有在维版本；2026-01-20 官方公告多个 Snort 2/3 旧版本 EOL、停发 Talos 规则；提供 `snort2lua` 迁移配置；SnortML 把机器学习检测接进规则引擎 |
| **Suricata** | 多线程高性能 NIDS/NSM，OISF 出品；GPLv2 | 8.0.4（2026-03）；多线程吃满多核，原生协议解析（HTTP/TLS/SMB/DNS）、EVE JSON 统一日志、AF_PACKET 高性能捕包、GPU 卸载、兼容 Snort 规则语法 |
| **Zeek** | 网络**安全监控**（NSM）而非严格意义上的 IDS；BSD 许可，Vern Paxson 1995 年起在 LBNL 开发（原名 Bro，2018 改名） | 8.0.10 LTS / 8.2.2 特性版（均 2026-08-19），9.0.0-rc2（2026-08-31）；事件引擎 + 策略脚本（Zeek 脚本语言）产出结构化日志（conn/dns/http/ssl/kerberos/ntlm 等），Spicy 框架写新协议分析器；约四个月一个版本、LTS 维护一年 |

辅助件：**Sigma**（厂商中立的检测规则格式，一份规则翻译成各 SIEM 的查询）、**YARA**（文件内容匹配，恶意软件家族分类）、**ET Open Rules**（Emerging Threats 免费规则集）。三者组合是 SOC 自建检测的标准件。

选择逻辑：**要拦（inline IPS）选 Snort/Suricata；要"看得全"（流量考古、威胁狩猎）选 Zeek**；要合规审计日志选 Suricata 的 EVE 或 Zeek 的结构化输出。Security Onion 发行版把三者打包成一个可部署的 NSM 平台，是自建的标准起点。

## Deployment

| 形态 | 位置 | 延迟 | 失败模式 |
| :--- | :--- | :--- | :--- |
| 旁路 NIDS | SPAN/TAP 镜像流量 | 无（不影响业务） | 只能看不能拦；镜像丢包即漏检 |
| Inline IPS | L2 透明串接（或虚拟网卡） | 每包增加检查耗时 | fail-open（故障放行，可用性优先）/ fail-closed（故障断网，安全性优先）必须显式决策 |
| 主机 HIDS | 装在每台机器上看系统调用与日志 | 本地 | 覆盖主机行为但占用主机资源、易被针对性规避 |

工程现实：高带宽链路（10G+）上全量深度检测的成本极高，通用做法是**旁路全量留存 + 抽样/热点 inline**，把重活留给离线 pcap 分析。IDS/IPS 与 [Firewall](/docs/CS/CN/CyberSecurity/Firewall.md) 串接时，IPS 通常放在边界防火墙之后——先挡掉明显恶意，再进状态检测。

## From Alerts to Response

检测的产出是告警，而告警的价值取决于 triage 质量——**误报是 IDS 的第一死因**：一个每天上千条噪声的系统等于没有。工程要点：

- **告警进 SIEM 关联**：单点事件（一条 Snort 命中）意义有限，跨源关联（同一 IP 先扫描后利用、失败登录后成功登录）才构成事件；自建走 Wazuh/Elastic，商业走 Splunk/Sentinel；
- **威胁情报订阅**：IP/域名/哈希信誉实时喂给检测系统，把"事后发现"提前成"当场拦住"；
- **指标是 MTTD/MTTR**（平均检测/响应时间），不是"装了几个传感器"；
- **紫队验证**：定期用 Atomic Red Team / 自研 TTP 回放验证规则是否真的会触发——没被触发的规则是幻觉。

## The Encrypted Traffic Problem

加密普及把 NIDS 推到了拐角：HTTPS 流量占比超过九成后，签名与内容检测能看到的只有 SNI 与证书元数据。现实的应对与边界：

- **元数据指纹**：JA3/JA4（TLS ClientHello 的指纹，可在握手明文里算）、证书序列号与 SAN 模式——足以识别恶意家族与 C2 通道，即使流量加密；
- **TLS 解密检查**（企业防火墙的 SSL inspection）正在被两头挤压：TLS 1.3 的 ECH（Encrypted Client Hello）把 SNI 也加密掉；证书钉扎的应用（银行 App、部分国产 App）在解密后握手直接失败；
- **端点数据源补位**：EDR 的系统调用遥测在加密之前就看见行为——这是主机侧相对网络侧的结构性优势，也是 EDR 成为恶意软件检测主力（见 [Malware](/docs/CS/CN/CyberSecurity/Malware.md)）的原因。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [WireShark](/docs/CS/CN/Tools/WireShark.md)
- [Firewall](/docs/CS/CN/CyberSecurity/Firewall.md)
- [netfilter](/docs/CS/CN/Tools/netfilter.md)
- [Malware](/docs/CS/CN/CyberSecurity/Malware.md)
- [Attack](/docs/CS/CN/Attack.md)

## References

1. [Snort Official Site and Downloads](https://www.snort.org/)
2. [Suricata Official Site](https://suricata.io/)
3. [Zeek Network Security Monitor](https://zeek.org/)
4. [Sigma Rules Repository](https://github.com/SigmaHQ/sigma)
5. [Security Onion Documentation](https://docs.securityonion.net/)
6. [NIST SP 800-94 Rev. 1 - Guide to Intrusion Detection and Prevention Systems (IDPS)](https://csrc.nist.gov/pubs/sp/800/94/r1/final)
