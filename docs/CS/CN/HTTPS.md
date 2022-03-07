## Introduction


`HyperText Transfer Protocol Secure`

HTTPS = HTTP + TLS/SSL

The primary goal of TLS is to provide a secure channel between two communicating peers; the only requirement from the underlying transport is a reliable, in-order data stream.  
Specifically, the secure channel should provide the following properties:

-  Authentication: 
   The server side of the channel is always authenticated; the client side is optionally authenticated.
   Authentication can happen via asymmetric cryptography (e.g., RSA, the Elliptic Curve Digital Signature Algorithm (ECDSA), or the Edwards-Curve Digital Signature Algorithm ([EdDSA](https://www.rfc-editor.org/rfc/rfc8032)) or a symmetric pre-shared key (PSK).

-  Confidentiality: 
   Data sent over the channel after establishment is only visible to the endpoints.  
   TLS does not hide the length of the data it transmits, though endpoints are able to pad TLS records in order to obscure lengths and improve protection against traffic analysis techniques.

-  Integrity: 
   Data sent over the channel after establishment cannot be modified by attackers without detection.

These properties should be true even in the face of an attacker who has complete control of the network, as described in [RFC3552](https://www.rfc-editor.org/rfc/rfc3552).  
See Appendix E for a more complete statement of the relevant security properties.

TLS consists of two primary components:
-  A handshake protocol that authenticates the communicating parties, negotiates cryptographic modes and parameters, and establishes shared keying material.  
   The handshake protocol is designed to resist tampering; an active attacker should not be able to force the peers to negotiate different parameters than they would if the connection were not under attack.
-  A record protocol that uses the parameters established by the handshake protocol to protect traffic between the communicating peers.  
   The record protocol divides traffic up into a series of records, each of which is independently protected using the traffic keys.

TLS is application protocol independent; higher-level protocols can layer on top of TLS transparently.  
The TLS standard, however, does not specify how protocols add security with TLS; 
how to initiate TLS handshaking and how to interpret the authentication certificates exchanged are left to the judgment of the designers and implementors of protocols that run on top of TLS.


TLS supports three basic key exchange modes:

-  (EC)DHE (Diffie-Hellman over either finite fields or elliptic curves)
-  PSK-only
-  PSK with (EC)DHE


### security

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

Encryption

Data integrity

Authentication

SSL

`Secure Socket Layer`

TLS

`Transport Layer Security`

key pairs

- private key in Server
- public key

密钥交换算法 - signature algorithms - 对称加密算法 - (分组模式) - 摘要算法

CA

`Certificate Authority`

可信度依次增加

1. DV
2. OV
3. EV

SSL/TLS 协议建立流程:

1. ClientHello

   client->server, send Client Random, support protocol version, algorithm list
2. ServerHello

   check protocol version and algorithm list, return with Server Random CA
3. client response

   check CA, get public key from CA ,

   create pre-master key and send
4. server response

   get pre-master key, calc private key

## Version

### 1.2

2 RTT

### 1.3

1 RTT

ECDHE rather than RSA

0 RTT

Digest Algorithm

## Handshaking

The TLS Handshake Protocol involves the following steps:

-  Exchange hello messages to agree on algorithms, exchange *random values*, and check for session resumption.
-  Exchange the *necessary cryptographic parameters* to allow the client and server to agree on a *premaster secret*.
-  Exchange certificates and cryptographic information to allow the client and server to authenticate themselves.
-  Generate a master secret from the premaster secret and exchanged random values.
-  Provide security parameters to the record layer.
-  Allow the client and server to verify that their peer has calculated the same security parameters and that the handshake occurred without tampering by an attacker.

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

          Message flow for a full handshake
```


## 0-RTT and Anti-Replay



## References

1. [RFC 2246 - The TLS Protocol Version 1.0](https://www.rfc-editor.org/rfc/rfc2246.html)
2. [RFC 4346 - The Transport Layer Security (TLS) Protocol Version 1.1](https://www.rfc-editor.org/rfc/rfc4346.html)
3. [RFC 5246 - The Transport Layer Security (TLS) Protocol Version 1.2](https://www.rfc-editor.org/rfc/rfc5246.html)
4. [RFC 8446 - The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446.html)
