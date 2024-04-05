## Introduction

[Pingora](https://github.com/cloudflare/pingora) is a Rust framework to build fast, reliable and programmable networked systems.

**Feature highlights**:
- Async Rust: fast and reliable
- HTTP 1/2 end to end proxy
- TLS over OpenSSL or BoringSSL
- gRPC and websocket proxying
- Graceful reload
- Customizable load balancing and failover strategies
- Support for a variety of observability tools



Comparsion with nginx

- nignx multi process model isolation -- CPU core, connection reuse | Pingora share the connections between multithreads in order to reduce TCP and TLS  handshake
- other features:
- security: Rust



| | nginx | Pingora |
| -- | -- | -- |
| Process Model | Multiprocesses | Multithreads |



## Links

- [nginx](/docs/CS/CN/nginx//nginx.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## References

1. [Open sourcing Pingora: our Rust framework for building programmable network services](https://blog.cloudflare.com/pingora-open-source)
2. [How we built Pingora, the proxy that connects Cloudflare to the Internet](https://blog.cloudflare.com/zh-cn/how-we-built-pingora-the-proxy-that-connects-cloudflare-to-the-internet-zh-cn/)
