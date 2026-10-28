## Introduction

认证（authentication）回答"你是谁"，授权（authorization）回答"你能干什么"，记账（accounting）回答"你做了什么"——三者合称 AAA，是所有访问控制的共同骨架。加密解决机密性，但 [TLS](/docs/CS/CN/TLS.md) 只能证明"通道那端是持钥人"；把"持钥人"映射到"某个人、某台设备、某个服务账号"，是本页这些协议的工作：Kerberos（域内票据）、EAP/802.1X（网络接入）、RADIUS/Diameter/TACACS+（AAA 协议的三种形态）、WebAuthn/passkeys（抗钓鱼的公钥认证）。证书侧的信任问题见 [PKI](/docs/CS/CN/CyberSecurity/PKI.md)，应用层授权框架（OAuth/OIDC）见 [OAuth](/docs/CS/CN/HTTP/OAuth.md)。

## Kerberos

Kerberos（RFC 4120）是 Active Directory 与大数据库（Hadoop/HBase/Hive）的默认域认证协议，核心是三服务器模型：

- **AS（Authentication Server）**：用户用长期密钥（口令哈希）向 AS 证明身份，换到 **TGT（Ticket-Granting Ticket）**；
- **TGS（Ticket-Granting Server）**：用户拿 TGT 换访问具体服务的 **Service Ticket**，无需重复输入口令；
- 服务端用与 KDC 共享的密钥验证 Service Ticket——**双向认证**（mutual authentication）：客户端也验证了服务是真的。

设计精妙处：口令永不上网（只有加密的票据在飞）、票据带有效期与可再生标志、时钟同步是硬要求（默认 5 分钟容忍）。PKINIT（RFC 4556）把初始认证换成证书/智能卡。它的软肋几乎全在"票据即凭证"上：

- **Kerberoasting**：任何域用户都能请求任意服务的 Service Ticket，票据用服务账号口令哈希加密——离线爆破该口令即接管服务账号（服务账号常是本地管理员且口令常年不换，是 AD 渗透的标准一步）；
- **Pass-the-ticket / Golden ticket**：偷到票据即可重放；偷到 KRBTGT 哈希则可伪造任意 TGT，等于域内无限期 root；
- **委派滥用**：无约束委派（Unconstrained Delegation）与基于资源的约束委派（RBCD）配置不当，可让服务账号替攻击者申请任意票据。

防御要点：服务账号用 120+ 位随机口令（爆破成本即不可行）、开启 AES 加密类型禁用 RC4、禁用不用的委派、监控异常 TGT 请求（TGS 请求风暴是 Kerberoasting 的信号）。

## EAP and 802.1X

EAP（Extensible Authentication Protocol）本身不是认证机制，而是"认证方法的封装框架"，跑在 802.1X 的端口级接入控制里：设备接入交换机/AP 端口时，端口只放行 EAP 流量，认证通过才打开网络。三个角色：supplicant（客户端）、authenticator（交换机/AP，只当二传）、authentication server（通常 RADIUS 服务器）。

方法族的取舍：

| EAP 方法 | 凭证 | 评价 |
| :--- | :--- | :--- |
| EAP-TLS | 双方证书 | 最强，无口令可窃；需要 PKI 基础设施（企业无线的推荐答案） |
| PEAP-MSCHAPv2 | 服务器证书 + 用户口令 | 部署最广；但客户端**必须验证服务器证书**，否则可被伪 AP 钓走口令 |
| EAP-TTLS/PAP | 服务器证书 + 任意内层方法 | 兼容性好，安全性取决于内层方法 |
| EAP-pwd | 共享口令 | Dragonfly 握手的另一应用场；FreeRADIUS 实现出过 invalid-curve 绕过与信息泄露（CVE-2019-11235 / CVE-2019-13456，见 [Wireless Security](/docs/CS/CN/CyberSecurity/Wireless_Security.md)） |
| EAP-AKA / AKA' | SIM 凭证 | 蜂窝网络漫游场景，5G 的主认证方法之一 |

## AAA Protocols

NAS（网络接入服务器）与 AAA 服务器之间怎么对话，三个协议、三种设计：

| 维度 | RADIUS | Diameter | TACACS+ |
| :--- | :--- | :--- | :--- |
| 标准 | RFC 2865（认证）/ 2866（记账），2000 | RFC 6733，2012 | Cisco 主导，**RFC 8907（2020）** 标准化 |
| 传输 | UDP 1812/1813 | TCP 或 SCTP，端口 3868 | TCP 49 |
| AAA 分离 | 认证与授权合并在一次 Access-Accept | 完全分离 | 完全分离，支持**逐命令授权** |
| 加密 | 仅 User-Password 属性混淆（弱）；全程加密靠 RadSec（RFC 6614，RADIUS over TLS） | 原生 TLS/IPsec | 全报文加密（legacy 为 MD5 共享密钥；**RFC 9887（2025）** 定义 TACACS+ over TLS 1.3） |
| 主战场 | 网络接入（宽带、WiFi、VPN、802.1X） | 移动核心（4G/5G 的 PCRF/OCS/HSS） | **网络设备管理**（路由器/交换机/防火墙的命令级授权） |

> [!WARNING]
>
> **Blast-RADIUS（CVE-2024-3596，2024-07 披露）**：RADIUS 的 Response Authenticator 用 MD5 保护，攻击者利用 MD5 的选择前缀碰撞可在不知道共享密钥的情况下把 Access-Reject 篡改为 Access-Accept——一次中间人即可绕过整个 RADIUS 认证。IETF RADEXT 工作组正在标准化 RadSec 并推进正式弃用裸 UDP/TCP 上的 RADIUS。**新部署直接上 RadSec（TLS），存量系统把迁移排进日程。**

## Passkeys and WebAuthn

passkey 是 2020 年代中期认证领域唯一的范式转移：从"共享秘密（口令）"变成"公钥凭证 + 本地手势"。

- **FIDO2 = WebAuthn（W3C 浏览器 API）+ CTAP（浏览器与 authenticator 间的协议）**。WebAuthn **Level 3 于 2026-08-25 成为 W3C 正式 Recommendation**（取代 2021 年的 L2），此前浏览器与平台早已按草案部署，L3 只是把这些能力变成可引用的规范；
- **抗钓鱼的原理**：凭证绑定 origin（RP ID），私钥永不离开设备、服务器上无可窃之物——钓鱼站点在另一个 origin 上，签名请求直接失败。这与"短信验证码"有代差：后者可被实时中继；
- **凭证形态由 BE/BS 标志区分**：Backup Eligible + Backup State 让依赖方知道这是"可跨设备同步的 passkey"（iCloud 钥匙串 / Google 密码管理器 / Microsoft Edge 142 起同步）还是"设备绑定凭证"（Windows Hello、YubiKey 类安全密钥）——高价值账户应要求后者；
- **L3 新增的能力**：Conditional Get（passkey 自动填充 UI）/ Conditional Create（登录过程中静默帮用户建 passkey——把"要不要升级 passkey"从用户任务变成登录副产品，这是 adoption 的最大杠杆）、Signals API（依赖方通知客户端"此凭证已失效"，补上 passkey 撤销的短板）、Related Origin Requests（一个 passkey 跨关联域名）、混合传输（手机上签名、电脑上登录）；
- **采纳面**：2026-08 的统计，支持 passkey 的浏览器占全球页面浏览量约 93%；跨生态迁移仍未解决——凭证交换格式 CXF 1.0 已定稿，但真正搬凭证的 CXP 还是工作草案，"passkey 锁定在单一生态"仍是现实风险。

**迁移方法论**（各 IdP 的实践共识）：保留口令兜底 → 登录时自动提示创建 passkey → 默认 passkey → 逐步收紧口令路径。账户恢复是新的攻击面——密码没了，帮助台社工就是唯一入口，恢复流程的强度决定整套体系的下限。

## Federation and Tokens

域内认证之外，跨组织场景走联邦协议：**OAuth 2.0 / OIDC**（授权码 + token，互联网 API 的事实标准，展开见 [OAuth](/docs/CS/CN/HTTP/OAuth.md)）、**SAML 2.0**（企业 SSO 的老兵，XML 重、但存量巨大）、**JWT**（token 格式而非协议，常见陷阱：`alg: none`、`kid` 注入、把敏感声明当加密用、不做过期校验）。NIST SP 800-63-4（2025-07/08 发布，取代 2017 年的 Rev.3）把身份保证分成 IAL（身份证明强度）/ AAL（认证强度）/ FAL（联邦断言强度）三轴——"要不要 MFA""能不能远程开户"在这套语言里都有对应等级，是企业身份架构与合规的对齐基准。

## Authorization Models

认证之后是授权，三种模型的适用面：

| 模型 | 判定依据 | 适用 |
| :--- | :--- | :--- |
| RBAC | 角色（admin/auditor/dev） | 组织职责稳定时；最简单可审计 |
| ABAC | 属性（部门、时间、IP、数据敏感级） | 大规模细粒度策略 |
| ReBAC | 关系（owner/editor/parent-of） | 社交/文档类协作 |

工程铁律只有一条：**授权决策必须服务端做**——前端隐藏按钮不是授权；[CSRF](/docs/CS/CN/HTTP/Security.md?id=csrf) 的存在正说明"带着会话 Cookie 的请求"不等于"经过授权的请求"。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Wireless Security](/docs/CS/CN/CyberSecurity/Wireless_Security.md)
- [PKI](/docs/CS/CN/CyberSecurity/PKI.md)
- [OAuth](/docs/CS/CN/HTTP/OAuth.md)
- [Security](/docs/CS/CN/Security.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)

## References

1. [RFC 4120 - The Kerberos Network Authentication Service (V5)](https://datatracker.ietf.org/doc/html/rfc4120)
2. [RFC 4556 - Public Key Cryptography for Initial Authentication in Kerberos (PKINIT)](https://datatracker.ietf.org/doc/html/rfc4556)
3. [RFC 2865 - Remote Authentication Dial In User Service (RADIUS)](https://datatracker.ietf.org/doc/html/rfc2865)
4. [RFC 6614 - Transport Layer Security (TLS) Encryption for RADIUS](https://datatracker.ietf.org/doc/html/rfc6614)
5. [RFC 8907 - The Terminal Access Controller Access-Control System Plus (TACACS+) Protocol](https://datatracker.ietf.org/doc/html/rfc8907)
6. [RFC 9887 - TACACS+ over TLS 1.3](https://datatracker.ietf.org/doc/html/rfc9887)
7. [FIDO Alliance - WebAuthn Level 3 Is Now a W3C Recommendation](https://fidoalliance.org/webauthn-level-3-is-now-a-w3c-recommendation/)
8. [NIST SP 800-63-4 - Digital Identity Guidelines](https://pages.nist.gov/800-63-4/)
9. [Blast-RADIUS - CVE-2024-3596](https://www.blastradius.fail/)
