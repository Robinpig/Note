# HTTPS

`HyperText Transfer Protocol Secure`

HTTPS = HTTP + TLS/SSL

在建立连接时，增加了TLS握手

传输过程使用对称加密算法

传输安全 防止传输被监听 数据被窃取 确认网站真实性

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



密钥交换算法 - 签名算法 - 对称加密算法 - (分组模式) - 摘要算法



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

## TLS/SSL

TLS握手演变

TLS1.2 4次 两次RTT RFC5246

TLS1.3 3次 一次RTT

