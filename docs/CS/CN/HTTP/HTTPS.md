## Introduction


一个完整、未复用连接的 HTTPS 请求需要经过以下 5 个阶段：DNS 域名解析、TCP 握手、SSL 握手、服务器处理、内容传输


请求阶段分析所示，这些阶段共需要 5 个 RTT = 1 RTT（DNS Lookup，域名解析）+ 1 RTT（TCP Handshake，TCP 握手）+ 2 RTT（SSL Handshake，SSL 握手）+ 1 RTT（Data Transfer，HTTP 内容请求传输)




## Links

- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## References

