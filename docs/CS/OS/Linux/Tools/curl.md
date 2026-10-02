## Introduction

**curl** 是一个命令行与库（libcurl）形态的**数据传输工具**，支持通过 URL 在多种协议间收发数据：HTTP/HTTPS、FTP/SFTP、SCP、SMTP/POP3/IMAP、DICT、FILE、gopher 等。它不只是"下载工具"，更是排查 [HTTP](/docs/CS/CN/HTTP/HTTP.md) API、调试 [TLS](/docs/CS/CN/TLS.md) 握手、验证代理/重定向/认证行为最常用的瑞士军刀。脚本、CI、健康检查里普遍用它做精确可控的请求构造。

## Common Options

| 选项 | 作用 |
| --- | --- |
| `-X, --request` | 指定方法（GET/POST/PUT/DELETE…） |
| `-H, --header` | 加请求头（可多次） |
| `-d, --data` | 请求体（默认 `application/x-www-form-urlencoded`） |
| `--data-raw` / `--data-binary` | 不解析 `@`/原样二进制发送 |
| `-F, --form` | `multipart/form-data` 上传文件 |
| `-G, --get` | 把 `-d` 数据拼到 query string |
| `-i, --include` | 响应中含响应头 |
| `-I, --head` | 只发 HEAD 请求 |
| `-v, --verbose` | 打印请求/响应头与 TLS 握手过程 |
| `-s, --silent` / `-S` | 静默（`-S` 出错时仍提示） |
| `-o, --output` / `-O` | 输出到文件 / 用远端文件名 |
| `-L, --location` | 跟随 3xx 重定向 |
| `-k, --insecure` | 跳过 TLS 证书校验（仅排错用） |
| `-u, --user` | Basic/Digest 认证 `user:pass` |
| `-x, --proxy` | 指定代理 |
| `-m, --max-time` | 总超时；`--connect-timeout` 连接超时 |
| `-w, --write-out` | 输出自定义指标（耗时、状态码等） |
| `--resolve` | 强制 host:port 解析到指定 IP |
| `-b/-c, --cookie/--cookie-jar` | 发送/保存 Cookie |

## HTTP Examples

```bash
# JSON POST（注意显式声明 Content-Type）
curl -X POST https://api.example.com/v1/orders \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"item":"book","qty":2}'

# 表单上传
curl -F 'name=robin' -F 'avatar=@/tmp/a.png' https://example.com/upload

# 跟随重定向 + 显示响应头
curl -sIL https://example.com

# query 参数
curl -G https://api.example.com/search --data-urlencode 'q=linux kernel'
```

## Timing

用 `-w` 量化一次请求各阶段耗时（排查 DNS/建连/TLS/首字节延迟）：

```bash
curl -o /dev/null -s -w '\
dns:        %{time_namelookup}s\n\
connect:    %{time_connect}s\n\
tls:        %{time_appconnect}s\n\
ttfb:       %{time_starttransfer}s\n\
total:      %{time_total}s\n\
http_code:  %{http_code}\n\
remote_ip:  %{remote_ip}:%{remote_port}\n\
size:       %{size_download} bytes\n' https://example.com
```

这些阶段分别对应 DNS 解析、TCP 三次握手、[TLS](/docs/CS/CN/TLS.md) 握手、等待服务端首字节（TTFB）与总耗时，是区分网络问题还是应用处理慢的关键。

## TLS Debugging

```bash
# 查看完整握手：证书链、协商的 TLS 版本与套件、SNI
curl -v https://example.com 2>&1 | grep -Ei 'subject|issuer|SSL|TLS|cipher|ALPN'

# 指定 TLS 版本 / CA / 客户端证书（双向认证）
curl --tlsv1.2 --cacert ca.pem --cert client.crt --key client.key https://svc/

# 只测连通与证书（跳过校验仅用于自签名排障）
curl -kv https://internal:8443/health
```

## Resolve and Proxy

```bash
# 不改 /etc/hosts，把某域名强制打到指定 IP（灰度/直连源站）
curl --resolve example.com:443:10.0.0.1 https://example.com/

# 经 HTTP/SOCKS 代理
curl -x http://proxy:3128 https://example.com/
curl -x socks5h://127.0.0.1:1080 https://example.com/   # socks5h 让代理解析 DNS
```

`--resolve` 对验证 L4 [负载均衡](/docs/CS/CN/Load%20Balance.md)后端、源站直连、绕过异常 DNS 很有用。

## Exit Status and Scripting

- 用 `--fail` / `--fail-with-body` 让 HTTP 4xx/5xx 返回非零退出码，便于在脚本/CI 中判断；
- 常用判断：`--retry N`（重试）、`--connect-timeout`/`--max-time`（避免挂死）、`-fSs`（失败即退出、静默但显示错误）；
- libcurl 被几乎所有语言绑定（Python pycurl、Java、Go 等），核心能力与命令行一致。

```bash
# 健康检查：静默、失败退出、限时、只取状态码
curl -fsS -m 5 -o /dev/null -w '%{http_code}\n' http://localhost:8080/actuator/health
```

## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [TLS](/docs/CS/CN/TLS.md)
- [DNS](/docs/CS/CN/DNS.md)
- [OAuth](/docs/CS/CN/HTTP/OAuth.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)

## References

1. [curl Documentation](https://curl.se/docs/)
2. [curl man page](https://curl.se/docs/manpage.html)
3. [curl — Everything curl (book)](https://everything.curl.dev/)
4. [curl write-out variables](https://curl.se/docs/manpage.html#-w)
