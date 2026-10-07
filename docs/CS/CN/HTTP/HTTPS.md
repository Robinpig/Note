## Introduction

HTTPS = **HTTP over TLS**：在 HTTP 与 TCP 之间插入 TLS 加密层，对请求/响应做加密与身份认证，防止窃听、篡改与中间人冒充。一个完整、未复用连接的 HTTPS 请求通常经历 **5 个阶段**，累计约 **5 个 RTT**：

```
1 RTT  DNS 解析        (域名 → IP)
1 RTT  TCP 握手        (SYN / SYN-ACK / ACK)
2 RTT  TLS 握手        (ClientHello / ServerHello + 证书 / 密钥交换 / Finished)
1 RTT  HTTP 请求+响应  (应用数据)
```

启用 **TCP 连接复用（keep-alive）** 与 **TLS 会话恢复（Session ID / Session Ticket）** 可省去重复握手；**TLS 1.3** 更把握手压缩到 **1-RTT（甚至 0-RTT 重连）**，显著削减延迟。

## TLS Handshake Differences

- **TLS 1.2**：完整握手 2-RTT，需在 ServerHello 后发送证书并做 RSA/DHE/ECDHE 密钥交换，再互发 `ChangeCipherSpec` + `Finished`。
- **TLS 1.3**：合并握手消息，默认 **1-RTT**；移除静态 RSA 密钥交换（仅保留前向安全的 (EC)DHE），并支持 **0-RTT** 早期数据（以重放风险为代价换极低延迟）。

## Certificate and Trust Chain

- 服务器出示 **X.509 证书**，包含域名、公钥、颁发者（CA）签名。
- 客户端沿 **信任锚（内置根 CA）→ 中间 CA → 叶子证书** 校验签名与有效期，防止伪造身份。
- 自签名证书需手动信任；公开服务应使用受信 CA（Let's Encrypt 免费签发，Caddy/Nginx 可自动续期）。

## Hardening Mechanism

- **HSTS**（`Strict-Transport-Security` 响应头）：强制浏览器只走 HTTPS，避免降级/SSL Stripping 攻击。
- **证书透明度（CT）/ OCSP Stapling**：提升吊销校验效率与透明度。
- **HTTP/2 over TLS**：HTTPS 常搭配 HTTP/2 多路复用进一步提升吞吐。

## Links

- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [TLS](/docs/CS/CN/TLS.md)
- [QUIC](/docs/CS/CN/HTTP/QUIC.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

- [RFC 9110 - HTTP Semantics](https://datatracker.ietf.org/doc/rfc9110/)
- [RFC 8446 - The TLS 1.3 Protocol](https://datatracker.ietf.org/doc/rfc8446/)
