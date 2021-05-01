# HTTPS

`HyperText Transfer Protocol Secure`

HTTPS = HTTP + TLS(SSL)

传输安全 防止传输被监听 数据被窃取 确认网站真实性



verified certifcation

client验证CA证书正确后本地生成随机数用于对称算法 通过公钥传输给服务端私钥解析后对称加密传输

中间人攻击 若中间存在伪造的服务器 则可获得随机数对称解密数据 拿用户请求的数据去请求目标服务器

对称加密解析比非对称加密快



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