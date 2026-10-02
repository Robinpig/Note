## Introduction

FTP（File Transfer Protocol，文件传输协议，RFC 959）是应用层最古老的文件传输协议之一，采用双连接设计：**控制连接**（端口 21，传命令与应答，全程保持）与**数据连接**（端口 20 或协商端口，只在每次传文件/列目录时建立）。这种分离让控制命令可以在传输期间继续发送（如中止），但也带来了主动/被动模式和 NAT 穿越问题。现代文件共享更多用 SFTP（基于 SSH）、HTTP 上传或对象存储，明文 FTP 在公网已基本淘汰。

## 命令与应答

控制连接是 NVT ASCII 文本协议（与 Telnet 同源），客户端发命令、服务器回三位数字状态码：

| 命令 | 含义 |
|------|------|
| USER / PASS | 用户名 / 密码（明文！） |
| LIST | 列目录（结果走数据连接） |
| RETR / STOR | 下载 / 上传文件 |
| PORT / PASV | 声明主动模式端口 / 请求进入被动模式 |
| CWD / PWD | 切换目录 / 打印当前目录 |
| TYPE I / A | 二进制模式 / ASCII 模式（换行转换，现代应一律用 I） |

应答码首位表示结果类别：1xx 预备、2xx 成功、3xx 需要进一步信息（如 PASS 紧跟 USER）、4xx 临时失败（可重试）、5xx 永久失败。

## 主动模式 vs 被动模式

区别只在**谁发起数据连接的 TCP 三次握手**：

- **主动模式（PORT）**：客户端监听随机端口 N，通过控制连接告诉服务器 `PORT a,b,c,d,p1,p2`（端口 = p1×256+p2）；服务器从自己的 20 端口主动连客户端 N。问题：客户端在 NAT/防火墙后面时，入站连接进不来。
- **被动模式（PASV）**：服务器开一个随机端口并告诉客户端，由客户端发起数据连接。这是今天穿越 NAT 的默认模式（浏览器/客户端都用 EPSV/PASV）。

## 报文交互示例

```
客户端 → 服务器 : USER alice
服务器 → 客户端 : 331 Please specify password
客户端 → 服务器 : PASS secret
服务器 → 客户端 : 230 Login successful
客户端 → 服务器 : PASV
服务器 → 客户端 : 227 Entering Passive Mode (10,0,0,1,195,80)  # 端口 195*256+80=50000
客户端 → 服务器 : RETR report.pdf   # 控制连接发命令
客户端 → 服务器 : TCP 连接 10.0.0.1:50000  # 数据连接取文件
```

## 安全与替代

| 协议 | 传输 | 说明 |
|------|------|------|
| FTP | 全明文 | 密码、数据可被嗅探与篡改 |
| FTPS | FTP over TLS | 命令/数据连接加密；隐式 990 或显式 AUTH TLS；证书与多端口配置麻烦 |
| SFTP | SSH 隧道（端口 22） | 与 FTP **无关**，是 SSH 协议的二进制子协议，单连接、复用认证，Linux 默认选择 |
| SCP | SSH | 老式非交互式拷贝，功能被 SFTP 取代 |
| HTTP/HTTPS | 80/443 | 文件下载/REST 上传的现代主流方式 |

工程要点：服务器端要主动关 FTP 明文端口或强制 TLS；代码中用客户端库（如 Apache Commons Net 的 `FTPClient`）时，传二进制前必须 `setFileType(FTP.BINARY_FILE_TYPE)`，否则图片/压缩包会被换行转换破坏；NAT 设备还要处理 PASV 响应里内网 IP 的改写（或配置对外 IP 与被动端口范围）。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [TLS](/docs/CS/CN/TLS.md)
- [TCP Connection](/docs/CS/CN/CN.md?id=connection-oriented)
- [MIME](/docs/CS/CN/MIME.md)

## References

1. [RFC 959 - File Transfer Protocol](https://datatracker.ietf.org/doc/html/rfc959)
2. [FTP 协议主动被动模式图解（IBM 文档）](https://www.ibm.com/docs/en/connect-direct)
