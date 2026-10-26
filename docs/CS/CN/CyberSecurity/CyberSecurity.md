## Introduction

从目标上来说，网络安全(*Cyber Security*)主要用于保护网络、计算机、移动设备、应用程序及数据等资产免受网络攻击，避免造成数据泄露、业务中断等安全问题。

本文先给出攻击分类与安全属性的框架，再按工具展开，最后用一张地图指向七个分册。安全协议（TLS、IPsec、DNSSEC 等）的机制分析见 [Security](/docs/CS/CN/Security.md) 专题页，报文级攻击手段见 [Attack](/docs/CS/CN/Attack.md)——本页与分册回答的是"这个学科由哪些知识块构成"，而不是任何一个协议或攻击的细节。

## Attack Taxonomy

Web 应用安全领域使用最广的风险分类是 OWASP Top 10，它是面向开发者与安全工程师的共识性风险清单（standard awareness document）。**现行版为 2025 版**（2026-10 核实，勿再引用已过时的 2021 版清单）：

1. A01 Broken Access Control —— 访问控制失效
2. A02 Security Misconfiguration —— 安全配置错误
3. A03 Software Supply Chain Failures —— 软件供应链失效
4. A04 Cryptographic Failures —— 加密失效
5. A05 Injection —— 注入
6. A06 Insecure Design —— 不安全设计
7. A07 Authentication Failures —— 认证失效
8. A08 Software or Data Integrity Failures —— 软件或数据完整性失效
9. A09 Security Logging and Alerting Failures —— 安全日志与告警失效
10. A10 Mishandling of Exceptional Conditions —— 异常条件处理不当

与 2021 版相比的关键差异：SSRF（服务端请求伪造）跌出前十；新增供应链（A03）与异常条件处理（A10）两类；A09 由 Security Logging and Monitoring Failures 改名为 Security Logging and Alerting Failures。

> [!TIP]
>
> 这份清单的正确用法是**自查索引**而不是威胁排行：它告诉你"过去十年被反复打穿的是这十类地方"。A01~A10 每一条都能在本子树找到对应机制——注入与浏览器侧看 [HTTP Security](/docs/CS/CN/HTTP/Security.md)，加密失效看 [Cryptography](/docs/CS/CN/CyberSecurity/Cryptography.md) 与 [PKI](/docs/CS/CN/CyberSecurity/PKI.md)，认证失效看 [Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)，供应链与恶意载荷看 [Malware](/docs/CS/CN/CyberSecurity/Malware.md)。

## Security Properties

信息安全的经典属性是 CIA 三要素：机密性（confidentiality）、完整性（integrity）、可用性（availability）。在此之外，authentication 与 non-repudiation 是 RFC 4949 定义的标准安全服务术语——authentication 验证参与方身份以防冒充，nonrepudiation 保证行为发生后可被证明、无法抵赖。

> [!WARNING]
>
> "auditability"（可审计性）**不是标准术语**：RFC 4949 的标准语境使用 audit service（审计服务），ISO/IEC 27000 的注释语境使用 accountability（可问责性）。写安全文档时避免自造该词。

版本注记：ISO/IEC 27000 现行版为 2026 年发布的第 6 版；本文引用的经典 CIA 定义出自 ISO/IEC 27000:2018。

三个属性与攻击类型一一对位，构成全子树的组织轴：破坏可用性的是 DoS/DDoS（[Attack](/docs/CS/CN/Attack.md)），破坏机密性/完整性的是嗅探、欺骗与中间人（同上），未授权访问则要靠认证与授权体系关门（[Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)），而"关门"用的锁与钥匙全部来自 [Cryptography](/docs/CS/CN/CyberSecurity/Cryptography.md)。

## Tools

以下工具覆盖信息收集、漏洞测试与靶场练习三类场景。测试前应先确认授权范围，未授权的扫描与渗透可能触碰法律红线。

### Burp Suite

[Burp Suite](https://portswigger.net/burp/communitydownload) 是 Web 应用安全测试的集成平台，具备多种功能，能辅助安全人员检测漏洞、分析安全问题，在安全领域应用广泛。

> [!NOTE]
>
> **社区版（Community Edition）只包含手工工具**，PortSwigger 官方原话 "The best manual tools to start web security testing"；Scanner（漏洞扫描）、DAST 等自动化能力属于 Professional / 企业版。这是常见误解，写测试方案时注意版本边界。

### HackBar

[HackBar](https://github.com/0140454/hackbar) 是一个用于渗透测试的浏览器插件：载荷生成、编解码转换、哈希计算，以及 SQLi/XSS/LFI 快捷测试。

### Wappalyzer

[Wappalyzer](https://www.wappalyzer.com/) 是一款强大且多功能的网站技术栈嗅探工具，能够帮助用户识别任意网站所使用的技术。

### bWAPP

bWAPP 是一个故意留下漏洞的免费开源靶场（deliberately insecure web application），覆盖 OWASP Top 10 各类漏洞，适合练习与教学。

```shell
docker pull docker.1ms.run/raesene/bwapp:latest
docker run -d -p 0.0.0.0:80:80 docker.1ms.run/raesene/bwapp:latest
```

登陆 http://localhost/install.php , install 并 create user

### OWASP ZAP

OWASP ZAP（Zed Attack Proxy）：zaproxy.org 官网原话 "The world's most widely used web app scanner. Free and open source."——免费开源、社区驱动的 Web 应用扫描器。

## Map of This Section

七个分册对应七类问题，也大致对应一门"计算机网络安全"课程的骨架：先有原语，才有信任体系；先有信任体系，才有边界、检测、恶意代码与认证；无线则是把前三者放到无物理边界的介质上重新考验一遍。

- **[Cryptography](/docs/CS/CN/CyberSecurity/Cryptography.md)**——「锁与钥匙本身」。对称加密与 AEAD、哈希、MAC、非对称签名与密钥交换、KDF 与随机数，以及后量子迁移（FIPS 203/204/205、混合密钥交换、harvest-now-decrypt-later）。读协议页之前的必修课：协议层的每个设计决策都是这些原语约束的结果。
- **[PKI](/docs/CS/CN/CyberSecurity/PKI.md)**——「凭什么信这把公钥」。X.509 结构、信任链与路径校验、CA 生态与 root program、吊销机制为何事实上失效、短寿命证书时间表（2029 年 47 天）、ACME 自动化、证书透明度与后量子时代的 MTC。所有"证书报错"的答案都在这页。
- **[Firewall](/docs/CS/CN/CyberSecurity/Firewall.md)**——「边界上的门卫」。包过滤到 NGFW 的谱系、DMZ 拓扑、状态检测与 conntrack、nftables 的默认化、eBPF/XDP 与云原生防火墙、NAT 的误区与防火墙的能力边界。
- **[IDS_IPS](/docs/CS/CN/CyberSecurity/IDS_IPS.md)**——「门卫之外的哨兵」。四类检测方法、Snort/Suricata/Zeek 三层开源栈的分工、旁路与 inline 的部署取舍、告警工程与加密流量带来的行业拐点。
- **[Malware](/docs/CS/CN/CyberSecurity/Malware.md)**——「被投递进来的敌人」。分类学、蠕虫世代史、2026 年勒索软件生态（fragmentation、RaaS 卡特尔、EDR-kill、AI 进入攻击链）、入口向量与检测防御体系。
- **[Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)**——「怎么证明你是谁」。Kerberos 票据体系及其渗透面、EAP/802.1X、RADIUS/Diameter/TACACS+ 三代 AAA 协议（含 Blast-RADIUS）、WebAuthn L3 与 passkeys 迁移方法论、授权模型。
- **[Wireless_Security](/docs/CS/CN/CyberSecurity/Wireless_Security.md)**——「没有物理边界的网络」。WEP 破产史、WPA2 四次握手与 KRACK、WPA3 的 SAE 设计与 Dragonblood 教训、FragAttacks/Kr00k 等设计层攻击、企业与个人 checklist。

分册之间不重复展开彼此的主题：协议机制在 Security/TLS/VPN 三页，攻击手法在 Attack 页，HTTP 层机制在 [HTTP Security](/docs/CS/CN/HTTP/Security.md)，WAF 在 [nginx security](/docs/CS/CN/nginx/security.md)，漏洞利用在 [Vulnerability Analysis](/docs/CS/Security/Vulnerability_Analysis.md)，概念掠影在 [Security（CS 树）](/docs/CS/Security/Security.md)——本子树只做这些主题的学科组织与展开。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Security](/docs/CS/CN/Security.md)
- [Attack](/docs/CS/CN/Attack.md)
- [TLS](/docs/CS/CN/TLS.md)
- [VPN](/docs/CS/CN/VPN.md)
- [HTTP Security](/docs/CS/CN/HTTP/Security.md)

## References

1. [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
2. [RFC 4949 - Internet Security Glossary, Version 2](https://www.rfc-editor.org/rfc/rfc4949)
3. [ISO/IEC 27000:2026 - iso.org](https://www.iso.org/standard/27000)
