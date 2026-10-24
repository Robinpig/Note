## Introduction

MongoDB 默认安装后是"无鉴权、监听本地"的开发形态；一旦暴露到网络，必须在**认证、授权、传输加密、静态加密、审计**五层同时收紧。真正容易出问题的地方通常不是加密算法，而是"用 root 跑业务""为了省事关掉 authorization""备份文件裸存"这类工程习惯。

## Authentication

| 机制 | 适用 | 说明 |
| :--- | :--- | :--- |
| SCRAM-SHA-256 | 默认 | 用户名/密码，挑战应答，不传明文 |
| SCRAM-SHA-1 | 兼容旧驱动 | 新部署不建议 |
| x.509 | 服务间、客户端证书 | 证书 CN 映射用户 |
| LDAP | 企业版 | 集中认证，可配合 LDAP 授权 |
| Kerberos | 企业版 | 域环境 |
| OIDC | 7.0+ | 访问令牌认证，适合云原生 |

副本集/分片集群的**内部认证**用 keyfile（共享密钥）或 x.509，`security.keyFile` 或 `security.clusterAuthMode` 配置。

```javascript
// 第一个管理员必须在 localhost exception 窗口内创建
use admin
db.createUser({
  user: "admin",
  pwd: passwordPrompt(),
  roles: [{ role: "userAdminAnyDatabase", db: "admin" }, "clusterAdmin"]
})
// 创建完成后开启 authorization: enabled 并重启
```

## Authorization (RBAC)

内置角色按资源层级划分：

| 层级 | 角色 |
| :--- | :--- |
| 库级读 | `read`、`readWrite` |
| 库管理 | `dbAdmin`、`dbOwner`、`userAdmin` |
| 集群 | `clusterAdmin`、`clusterMonitor`、`hostManager` |
| 备份恢复 | `backup`、`restore` |
| 超级权限 | `root` |

原则是**按库、按操作最小授权**：业务账号只给目标库的 `readWrite`，监控账号给 `clusterMonitor`，备份账号给 `backup`。需要更细粒度时用 `db.createRole` 组合 resource 与 action，例如只允许对某集合的 `find` 与 `insert`。

8.0 新增的 `directShardOperations` 角色可以绕过 mongos 直连 shard 执行维护命令，权限极大且可能破坏集群元数据，只在官方支持指导下临时使用。

## Transport Encryption

```yaml
net:
  tls:
    mode: requireTLS
    certificateKeyFile: /etc/ssl/mongodb.pem
    CAFile: /etc/ssl/ca.pem
    allowConnectionsWithoutCertificates: false
```

客户端可以只校验服务端证书（单向 TLS），也可以要求客户端证书（mTLS）。`allowConnectionsWithoutCertificates: false` 才真正强制双向认证。FIPS 140-2 模式需使用 FIPS 构建与企业版。

## Encryption at Rest

- **企业版加密存储引擎**：WiredTiger 数据文件与 journal 加密，密钥由 KMIP 服务器或本地 keyfile 管理。
- **社区版**：不提供内置静态加密，只能依赖文件系统/云盘加密（LUKS、EBS 加密等）。
- **备份加密**：备份文件本身也要加密，不能只依赖数据库层。

## Client-Side Field Level Encryption

敏感字段在**客户端加密后再写入**，服务端只看到密文：

| 方案 | 能力 | 版本 |
| :--- | :--- | :--- |
| CSFLE | 确定性/随机加密，等值查询 | 4.2+ |
| Queryable Encryption | 等值查询，密文可查询 | 7.0 GA（等值） |
| QE Range | 范围查询 | 8.0 |
| QE Prefix/Suffix/Substring | 前缀/后缀/子串查询 | 9.0 GA |

自动加密依赖驱动侧的加密库：早期需要 `mongocryptd` 进程，9.0 起 `mongocryptd` 废弃，改用 **Automatic Encryption Shared Library**（`crypt_shared`）。密钥管理（KMS）与数据密钥要独立于数据库部署。

## Auditing

企业版支持审计日志，记录认证、授权、DDL、CRUD 等事件，输出到文件、syslog 或 console，可用过滤器只保留关注事件。8.0 起支持 OCSF（Open Cybersecurity Schema Framework）schema，便于接入 SIEM。

社区版没有内置审计，只能靠数据库日志、驱动日志与网络层审计补足。

## Hardening Checklist

- [ ] 开启 `security.authorization`
- [ ] 绑定内网地址，前面放防火墙/安全组，不直接暴露 27017
- [ ] 强制 TLS，集群内部也启用
- [ ] 删除默认测试库，业务账号不用 `root`
- [ ] 密码/密钥进密钥管理系统，不进代码仓库
- [ ] 开启慢查询与审计，监控异常登录
- [ ] 定期轮换 keyfile、证书、SCRAM 凭据
- [ ] 备份加密并异地存放，定期演练恢复
- [ ] 用 `db.runCommand({ connectionStatus: 1 })` 核对当前用户权限

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)
- [Operations](/docs/CS/DB/MongoDB/Operations.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)

## References

- [MongoDB Security](https://www.mongodb.com/docs/manual/security/)
- [Authentication](https://www.mongodb.com/docs/manual/core/authentication/)
- [Role-Based Access Control](https://www.mongodb.com/docs/manual/core/authorization/)
- [Queryable Encryption](https://www.mongodb.com/docs/manual/core/queryable-encryption/)
