## Introduction

SSH（Secure Shell）是替代明文 Telnet 的**加密远程登录与命令执行协议**，通过**传输层加密 + 身份认证 + 完整性校验**保障在不安全网络上的会话安全。SSH-2 是当前标准（SSH-1 因设计缺陷已废弃）。容器场景下常需手动启用 sshd 以便调试：

```shell
# 容器内安装并启动
apt-get install openssh-server
docker run -it -p 9527:22 ubuntu          # 先做端口映射
vim /etc/ssh/sshd_config
# PermitRootLogin yes
# UsePAM no
service ssh restart
```

## Protocol Layering

SSH-2 由三个协议层叠加：

1. **Transport Layer（SSH-TRANS）**：建立 TCP 后做版本协商、算法协商（kex），通过 Diffie-Hellman 类交换派生会话密钥，提供加密与 MAC 完整性。
2. **User Authentication Layer（SSH-USERAUTH）**：在加密通道上验证客户端，支持 `publickey`、`password`、`hostbased` 等方式。
3. **Connection Layer（SSH-CONN）**：复用单条加密连接为多条逻辑「channel」，承载 shell、exec、X11 转发、端口转发等。

## Authentication Methods

- **公钥认证（推荐）**：客户端持有私钥，服务端 `~/.ssh/authorized_keys` 存公钥；相比密码，抗暴力破解且可免密。
- **密码认证**：简单但有被嗅探/爆破风险，生产应关闭 `PasswordAuthentication no`。
- **hostbased / GSSAPI**：企业内网 Kerberos 集成场景。

## Port Forwarding

同一加密隧道可顺带转发 TCP，是 SSH 常被低估的能力：

- **本地转发 `-L`**：把本地端口映射到远端可达地址（`ssh -L 8080:internal:80 host`，本地 8080 即访问内网 80）。
- **远程转发 `-R`**：把远端端口映射回本地（`ssh -R 9000:localhost:3000 host`，从远端访问本地 3000）。
- **动态转发 `-D`**：启动本地 SOCKS5 代理（`ssh -D 1080 host`），流量经主机出口。

## Companion Commands and Enhanced Clients

- `scp` / `sftp`：基于 SSH 的安全文件拷贝（注意 `scp` 新实现改用 SFTP 协议）。
- `ssh-keygen`：生成/管理密钥对。
- [tssh (trzsz-ssh)](https://github.com/trzsz/trzsz-ssh/tree/main)：兼容 OpenSSH 客户端的增强版，原生支持 `trz`/`tsz` 终端文件传输（替代繁琐的 lrzsz 配置），可作为 openssh 的 drop-in 替换。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Security](/docs/CS/CN/Security.md)
- [TLS](/docs/CS/CN/TLS.md)
- [VPN](/docs/CS/CN/VPN.md)

## References

- [RFC 4251 - The Secure Shell (SSH) Protocol Architecture](https://datatracker.ietf.org/doc/rfc4251/)
- [OpenSSH Manual Pages](https://www.openssh.com/manual.html)
