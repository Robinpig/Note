## Introduction

There are three primary properties of information, whether in a computer network or not, that may be desirable from an information security point of view:
confidentiality, integrity, and availability (the CIA triad), summarized here:
- Confidentiality means that information is made known only to its intended users (which could include processing systems).
- Integrity means that information has not been modified in an unauthorized way before it is delivered.
- Availability means that information is available when needed.

These are core properties of information, yet there are other properties we may also desire, including authentication, nonrepudiation, and auditability.
Authentication means that a particular identified party or principal is not impersonating another principal.
Nonrepudiation means that if some action is performed by a principal (e.g., agreeing to the terms of a contract), this fact can be proven later (i.e., cannot successfully be denied).
Auditability means that some sort of trustworthy log or accounting describing how information has been used is available.
Such logs are often important for forensic (i.e., legal and prosecutorial) purposes.

> [!NOTE]
> 术语口径：authentication 与 non-repudiation 是标准安全服务词汇（RFC 4949 互联网安全词汇表）；**auditability 本身不是标准术语**，标准语境里对应的是 audit service（RFC 4949）与 accountability（ISO/IEC 27000 注释）。写正式文档时优先用后两者。

本页是安全协议的**总览与选型入口**：传输通道加密、网络层安全与 DNS 信任链各解决一段路径上的问题，深入机制分别见 [TLS](/docs/CS/CN/TLS.md)、[Attack](/docs/CS/CN/Attack.md) 与 [CyberSecurity](/docs/CS/CN/CyberSecurity/CyberSecurity.md)。

## TLS

TLS（Transport Layer Security）保护**端到端的应用数据通道**，最典型的用途是 HTTPS：在 TCP 之上提供机密性、完整性与服务器（可选客户端）身份认证。要点：

- 现行规范是 **RFC 9846（2026-07）**，它废止了 RFC 8446（2018）；中文资料普遍还停在 8446，引用时注意版本口径（详见 [TLS](/docs/CS/CN/TLS.md) 页首基线块）。
- **TLS 1.3 完整握手 1-RTT**（1.2 是 2-RTT，由其消息流推导）；PSK 恢复仍是 1-RTT，0-RTT 则是把 early data 追加进首个 flight——**0-RTT 数据不具前向保密、且无跨连接抗重放保证**，涉及支付等幂等敏感操作要显式禁用。
- 1.3 只保留 AEAD 算法，静态 RSA/DH 密钥交换被移除，**前向保密成为必需**。
- 分层定位：TLS 工作在传输层之上、只保护它承载的应用，对 IP 层头的篡改与流量分析无感知——那是 IPsec 的地盘。

## IPsec

IPsec 在**网络层**成组地保护 IP 报文，对上层应用透明（VPN 与站点间互联的主流选择）：

- 两种模式：**传输模式**保护的是上层协议载荷（端到端主机间），**隧道模式**把整个 IP 包装进新的外层 IP 头（网关间组网，VPN 的常见形态）。
- 两个安全协议：**AH**（协议号 51）提供完整性与源认证（可含抗重放），**不加密**；**ESP**（协议号 50）提供同等服务**外加机密性**。
- **IKEv2**（RFC 7296，STD 79）负责双向认证与协商安全关联（SA）；IKEv1（RFC 2409）已被 4306/7296 一系取代。
- 与 TLS 的选择逻辑：TLS 天然只为支持它的应用服务、部署在socket 库上；IPsec 覆盖主机/网段间所有 IP 流量，但引入网关部署、NAT 穿越（UDP 500/4500）与 MTU 等运维复杂度。

## DNSSEC

DNSSEC 给 DNS 数据加**来源认证与完整性**签名，让解析器能验证「这条记录确实是 zone owner 签发的、未被篡改」：

- 它**不提供机密性**（RFC 4033 明言 extensions do not provide confidentiality），也不防 DoS——查询隐私要靠 DoH/DoT（RFC 8484/7858）这类传输加密。
- 四种记录各司其职：**DNSKEY** 存公钥、**RRSIG** 存对 RRset 的签名、**DS** 在父区存子区 DNSKEY 的摘要、**NSEC/NSEC3** 提供「不存在」的认证证明（NSEC3 额外防 zone 遍历）。
- 信任链：从根区开始，DNSKEY 与 DS 交替成链，逐级 vouching，直到签中目标数据的 DNSKEY——链的起点是内置在解析器/操作系统的根密钥。
- 现行核心规范仍是 RFC 4033/4034/4035（即 DNSSEC-bis；不存在所谓的「4033bis 新版」），概览性文档是 RFC 9364（BCP 237）。

## Defense in Depth

没有任何单一协议覆盖全路径：TLS 不管 DNS 被投毒，DNSSEC 不加密查询，IPsec 不理解应用语义。因此纵深防御是默认姿态——通道加密（TLS）+ 网络层隔离（IPsec/VPN）+ 命名系统信任（DNSSEC）+ 主机与边界防护（见 [CyberSecurity](/docs/CS/CN/CyberSecurity/CyberSecurity.md) 的攻击分类与 OWASP Top 10）+ 可审计的日志。攻击面的系统性梳理见 [Attack](/docs/CS/CN/Attack.md)。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [TLS](/docs/CS/CN/TLS.md)
- [Attack](/docs/CS/CN/Attack.md)
- [VPN](/docs/CS/CN/VPN.md)
- [CyberSecurity](/docs/CS/CN/CyberSecurity/CyberSecurity.md)
- [Cryptography](/docs/CS/CN/CyberSecurity/Cryptography.md)

## References

1. [RFC 9846 - The Transport Layer Security (TLS) Protocol Version 1.3](https://datatracker.ietf.org/doc/html/rfc9846)
2. [RFC 4301 - Security Architecture for the Internet Protocol](https://datatracker.ietf.org/doc/html/rfc4301)
3. [RFC 4303 - IP Encapsulating Security Payload (ESP)](https://datatracker.ietf.org/doc/html/rfc4303)
4. [RFC 7296 - Internet Key Exchange Protocol Version 2 (IKEv2)](https://datatracker.ietf.org/doc/html/rfc7296)
5. [RFC 4033 - DNS Security Introduction and Requirements](https://datatracker.ietf.org/doc/html/rfc4033)
6. [RFC 4034 - Resource Records for the DNS Security Extensions](https://datatracker.ietf.org/doc/html/rfc4034)
7. [RFC 4949 - Internet Security Glossary, Version 2](https://datatracker.ietf.org/doc/html/rfc4949)
