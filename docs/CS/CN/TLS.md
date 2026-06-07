## 简介

> HTTPS = [HTTP](/docs/CS/CN/HTTP/HTTP.md) + TLS/SSL

TLS 是一个客户端/服务器协议，旨在为两个应用之间的连接提供安全性。
虽然 TLS 可以用于任何底层传输协议之上，但该协议的最初目标是加密 HTTP 流量。
使用 TLS 加密的 HTTP 通常被称为 HTTPS。
按照惯例，TLS 加密的 Web 流量默认使用端口 443 交换，而未加密的 HTTP 默认使用端口 80。

## 协议

记录协议（Record protocol）为客户端和服务器之间交换的数据对象提供分片、压缩、完整性保护和加密，
而握手协议（handshake protocols）建立身份、执行认证、指示告警，并为记录协议在每个连接上提供唯一的密钥材料。
握手协议包括四个特定协议：握手协议（Handshake protocol）、告警协议（Alert protocol）、更改密码规范协议（Change Cipher Spec protocol）和应用数据协议（application data protocol）。

更改密码规范协议用于更改当前操作参数。
这是通过首先使用握手协议设置一个"待定"状态，然后指示从当前状态切换到待定状态（然后成为当前状态）来完成的。
只有在待定状态准备就绪后才允许这种切换。
TLS 依赖五种加密操作：数字签名、流密码加密、分组密码加密、AEAD 和公钥加密。对于完整性保护，TLS 记录层使用 HMAC。
对于密钥生成，TLS 1.2 使用基于 HMAC with SHA-256 的 PRF。TLS 还集成一个可选的压缩算法，在首次建立连接时协商。

HTTPS 仍然是 TLS 的一个重要用例。

### 记录协议

记录协议使用一组可扩展的记录内容类型值来标识被多路复用的消息类型（即哪个高层协议）。
在任何给定时刻，记录协议有一个活动当前连接状态和另一组称为待定连接状态的状态参数。
每个连接状态进一步分为读状态和写状态。
每个这些状态指定了用于通信的压缩算法、加密算法和 MAC 算法，以及任何必要的密钥和参数。
当密钥更改时，首先使用握手协议设置待定状态，然后同步操作（通常使用密码更改协议完成）将当前状态设置为等于待定状态。
首次初始化时，所有状态都设置为 NULL 加密、无压缩和无 MAC 处理。

### 握手协议

TLS 有三个子协议，执行与 IPsec 中 IKE 大致相当的任务。
更具体地说，这些其他协议由记录层用于多路复用和多路分解的编号标识，称为握手协议（22）、
告警协议（21）和密码更改协议（20）。
密码更改协议非常简单。它由一条包含单个字节的消息组成，其值为 1。
该消息的目的是向对端指示希望从当前状态切换到待定状态。接收此消息会将读待定状态移动到当前状态，并指示记录层尽快转换到待定写状态。
此消息由客户端和服务器都使用。

告警协议用于从 TLS 连接的一端向另一端传递状态信息。
这可以包括终止条件（致命错误或受控关闭）或非致命错误条件。
截至 [RFC5246] 发布，标准中定义了 24 条告警消息。其中超过一半始终是致命的（例如，错误的 MAC、缺失或未知消息、算法失败）。

握手协议设置相关的连接操作参数。
它允许 TLS 端点实现六个主要目标：协商算法和交换用于形成对称加密密钥的随机值、
建立算法操作参数、交换证书并执行相互认证、生成会话特定密钥、
向记录层提供安全参数，并验证所有这些操作是否正确执行。

### 重新协商

TLS 支持在保持同一连接的同时重新协商加密连接参数的能力。这可以由服务器或客户端发起。
如果服务器希望重新协商连接参数，它生成一个 HelloRequest 消息，客户端回复一个新的 ClientHello 消息，开始重新协商过程。
客户端也能够自发地生成这样的 ClientHello 消息，无需服务器提示。

TLS 的主要目标是在两个通信对端之间提供安全通道；对底层传输的唯一要求是可靠、有序的数据流。
具体来说，安全通道应提供以下属性：

- **认证（Authentication）：**
  通道的服务器端总是经过认证的；客户端端可选认证。
  认证可以通过非对称加密（例如 RSA、椭圆曲线数字签名算法（ECDSA）、Edwards-Curve 数字签名算法（[EdDSA](https://www.rfc-editor.org/rfc/rfc8032)）或对称预共享密钥（PSK）进行。

- **机密性（Confidentiality）：**
  建立后通过通道发送的数据仅端点可见。
  TLS 不隐藏其传输数据的长度，但端点可以填充 TLS 记录以模糊长度，提高对抗流量分析技术的保护。

- **完整性（Integrity）：**
  建立后通过通道发送的数据不能被攻击者修改而不被检测到。

即使面临完全控制网络的攻击者，这些属性也应保持，如 [RFC3552](https://www.rfc-editor.org/rfc/rfc3552) 所述。
参见附录 E 了解相关安全属性的更完整说明。

TLS 由两个主要组件组成：
- **握手协议**，用于认证通信双方、协商加密模式和参数，并建立共享密钥材料。
  握手协议设计为抗篡改；主动攻击者不应能够强制对端协商与连接不受攻击时不同的参数。
- **记录协议**，使用握手协议建立的参数来保护通信双方之间的流量。
  记录协议将流量分成一系列记录，每个记录使用流量密钥独立保护。

TLS 是应用协议无关的；高层协议可以在 TLS 之上透明分层。
然而，TLS 标准没有规定协议如何通过 TLS 增加安全性；
如何发起 TLS 握手以及如何解释交换的认证证书，留给运行在 TLS 之上的协议的设计者和实现者判断。

TLS 支持三种基本密钥交换模式：

- (EC)DHE（有限域或椭圆曲线上的 Diffie-Hellman）
- PSK-only
- PSK with (EC)DHE

### 安全

verified certifcation

client验证CA证书正确后本地生成随机数用于对称算法 通过公钥传输给服务端私钥解析后对称加密传输

中间人攻击 若中间存在伪造的服务器 则可获得随机数对称解密数据 拿用户请求的数据去请求目标服务器

非对称加密传输对称加密的密钥

对称加密解析比非对称加密快

摘要算法

客户端在发送明文之前会通过摘要算法算出明文的「指纹」，发送的时候把「指纹 + 明文」一同加密成
密文后，发送给服务器，服务器解密后，用相同的摘要算法算出发送过来的明文，通过比较客户端携带
的「指纹」和当前算出的「指纹」做比较，若「指纹」相同，说明数据是完整的。

CA

客户端在发送明文之前会通过摘要算法算出明文的「指纹」，发送的时候把「指纹 + 明文」一同加密成
密文后，发送给服务器，服务器解密后，用相同的摘要算法算出发送过来的明文，通过比较客户端携带
的「指纹」和当前算出的「指纹」做比较，若「指纹」相同，说明数据是完整的。

加密（Encryption）

数据完整性（Data integrity）

认证（Authentication）

SSL

`Secure Socket Layer`

TLS

`Transport Layer Security`

密钥对（key pairs）

- 私钥在服务器（private key in Server）
- 公钥（public key）

密钥交换算法 - 签名算法 - 对称加密算法 - (分组模式) - 摘要算法

CA

`Certificate Authority`

可信度依次增加

1. DV
2. OV
3. EV

SSL/TLS 协议建立流程:

1. ClientHello

   client->server, 发送客户端随机数、支持的协议版本、算法列表
2. ServerHello

   检查协议版本和算法列表，返回服务器随机数和 CA
3. 客户端响应

   检查 CA，从 CA 获取公钥，
   创建预主密钥并发送
4. 服务器响应

   获取预主密钥，计算私钥

## 版本

### 1.2

2 RTT

### 1.3

1 RTT

ECDHE 而非 RSA

0 RTT

摘要算法（Digest Algorithm）

## 握手

TLS 握手协议涉及以下步骤：

- 交换 hello 消息以协商算法，交换*随机值*，并检查会话恢复。
- 交换*必要的加密参数*以允许客户端和服务器就*预主密钥*达成一致。
- 交换证书和加密信息以允许客户端和服务器相互认证。
- 从预主密钥和交换的随机值生成主密钥。
- 向记录层提供安全参数。
- 允许客户端和服务器验证其对端计算了相同的安全参数，并且握手未受到攻击者篡改。

1.2

```
Client                                               Server

   ClientHello                  -------->
                                                    ServerHello
                                                   Certificate*
                                             ServerKeyExchange*
                                            CertificateRequest*
                                 <--------      ServerHelloDone
   Certificate*
   ClientKeyExchange
   CertificateVerify*
   [ChangeCipherSpec]
   Finished                     -------->
                                             [ChangeCipherSpec]
                                 <--------             Finished
   Application Data             <------->     Application Data

          完整握手消息流
```

## 0-RTT 和反重放

DES

unsafe 

AES

## 参考文献

1. [RFC 2246 - The TLS Protocol Version 1.0](https://www.rfc-editor.org/rfc/rfc2246.html)
2. [RFC 4346 - The Transport Layer Security (TLS) Protocol Version 1.1](https://www.rfc-editor.org/rfc/rfc4346.html)
3. [RFC 5246 - The Transport Layer Security (TLS) Protocol Version 1.2](https://www.rfc-editor.org/rfc/rfc5246.html)
4. [RFC 8446 - The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446.html)
5. [Transport Layer Security](https://developer.mozilla.org/en-US/docs/Web/Security/Transport_Layer_Security)
