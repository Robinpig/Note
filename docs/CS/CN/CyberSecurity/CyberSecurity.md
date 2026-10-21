## Introduction

从目标上来说，网络安全(*Cyber Security*)主要用于保护网络、计算机、移动设备、应用程序及数据等资产免受网络攻击，避免造成数据泄露、业务中断等安全问题

本文先给出攻击分类与安全属性的框架，再按工具展开。安全协议（TLS、IPsec、DNSSEC 等）的机制分析见 Security 专题页。

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

## Security Properties

信息安全的经典属性是 CIA 三要素：机密性（confidentiality）、完整性（integrity）、可用性（availability）。在此之外，authentication 与 non-repudiation 是 RFC 4949 定义的标准安全服务术语——authentication 验证参与方身份以防冒充，nonrepudiation 保证行为发生后可被证明、无法抵赖。

> [!WARNING]
> 
> "auditability"（可审计性）**不是标准术语**：RFC 4949 的标准语境使用 audit service（审计服务），ISO/IEC 27000 的注释语境使用 accountability（可问责性）。写安全文档时避免自造该词。

版本注记：ISO/IEC 27000 现行版为 2026 年发布的第 6 版；本文引用的经典 CIA 定义出自 ISO/IEC 27000:2018。

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

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Security](/docs/CS/CN/Security.md)
- [Attack](/docs/CS/CN/Attack.md)

## References

1. [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
2. [RFC 4949 - Internet Security Glossary, Version 2](https://www.rfc-editor.org/rfc/rfc4949)
3. [ISO/IEC 27000:2026 - iso.org](https://www.iso.org/standard/27000)
