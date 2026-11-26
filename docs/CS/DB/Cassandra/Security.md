## Introduction

早期 Cassandra 默认「全开」——任何人都能连、能读写所有表。现代版本把安全做成可配置的分层能力：认证、授权、传输加密、静态加密、审计、动态脱敏。生产必须显式开启，否则等于裸奔。

> 基线：Cassandra 5.0.9。Audit Logging 与 TDE 自 4.0；Dynamic Data Masking 与 CIDR Authorizer 自 5.0；Guardrails 自 4.1。

## Authentication

- `authenticator` 默认 `AllowAllAuthenticator`（**无认证**，仅适合测试）。
- 生产设为 `PasswordAuthenticator`，用户存于 `system_auth` keyspace（注意其 RF——默认常只有 1，需调高以免元数据单点）。
- 自定义 `IAuthenticator` 可接 LDAP / 企业 IdP。

## Authorization (RBAC)

- `authorizer` 默认 `AllowAllAuthorizer`；生产设为 `CassandraAuthorizer`。
- 基于 **角色（ROLE）** 的 RBAC：`CREATE ROLE`、`GRANT/REVOKE` 权限（`SELECT/INSERT/MODIFY/AUTHORIZE/...`），角色可继承（`GRANT role_a TO role_b`）。
- 同样依赖 `system_auth`，需保证其可用与冗余。

## Transport Encryption (TLS)

三层独立配置（均在 `cassandra.yaml`）：

- `client_encryption_options`：客户端驱动 ↔ 节点。
- `server_encryption_options.internode`：节点间（可 `none`/`dc`/`rack`/`all`）。
- `server_encryption_options.internode_encryption` + `require_client_auth`：是否双向认证（mTLS）。
- 证书轮换需配合 `cassandra.yaml` 的 keystore/truststore 与滚动重启。

## Encryption at Rest (TDE, 4.0+)

- 4.0 起支持 **Transparent Data Encryption**：SSTable 在落盘时加密，密钥可由 KMS / 自定义 `IKeyProvider` 管理。
- 控制粒度可在表级开关；与传输层 TLS 正交（TLS 护「传输中」、TDE 护「静态」）。

## Audit Logging (4.0+)

- `audit_logging_options` 可捕获 DML/DDL/DCL 活动（含 `fqltool` 的 full query log 抓包回放），对合规与故障复盘极有价值，且官方称对正常负载影响极小。

## Dynamic Data Masking (5.0, CEP-20)

- 用 **masked column** 把脱敏函数绑定到 schema；`SELECT` 时按权限返回明文或脱敏值，存储数据不变。它不是静态加密，能直接读 SSTable 的人仍可看到明文。
- 5.0.9 默认 `dynamic_data_masking_enabled=false`。普通用户默认没有 `UNMASK`；`UNMASK` 允许读取明文，`SELECT_MASKED` 允许在 `WHERE` 中过滤脱敏列但仍只看到脱敏结果。认证关闭时匿名用户拥有全部权限，脱敏不能替代认证。
- 内置函数包括 `mask_null`、`mask_default`、`mask_replace`、`mask_inner`、`mask_outer`、`mask_hash`。绑定到列时省略第一个 value 参数：

```sql
CREATE TABLE users (
    id uuid PRIMARY KEY,
    ssn text MASKED WITH mask_inner(1, null)
);
```

## Guardrails (4.1+) and CIDR Authorizer (5.0)

- **Guardrails**：表数量、分区大小、查询复杂度等限制，可分为 soft（告警）与 hard（拒绝）；是否拦截取决于具体 guardrail 的配置，不能一概写成“越界直接拒绝”。
- **CIDR Authorizer**：基于 CIDR 网段做连接授权，适合「只允许特定子网客户端」的网络层管控。

## Source-Level Classes

- **认证 / 授权 / 角色**：`auth.{IAuthenticator, IAuthorizer, IRoleManager}` 三大可插拔接口；默认实现是 `AllowAllAuthenticator` / `AllowAllAuthorizer` / `CassandraRoleManager`，元数据存于 `system_auth`。`PasswordAuthenticator` / `CassandraAuthorizer` / `CassandraRoleManager` 是常见生产组合，使用 `PasswordAuthenticator` 时必须同时采用 `CassandraRoleManager`，并调高 `system_auth` 的 RF。
- **CIDR Authorizer（CEP-33）**：`auth.CassandraCIDRAuthorizer` 按角色与 CIDR group 做连接授权，权限存于 `system_auth.cidr_permissions`；默认 `MONITOR` 只记录不拒绝，必须切到 `ENFORCE` 才真正阻断。JMX 调用不做 CIDR 检查，superuser 默认也不受限制。
- **TDE（4.0+）**：`security` 包提供 SSTable 块级加密，密钥经可插拔 `IKeyProvider` 接 KMS；与 TLS 正交（TLS 护传输中、TDE 护静态）。
- **审计**：`audit.AuditLogger` 抽象、`FileAuditLogger` / `BinAuditLogger` 实现；`fqltool` 可抓包/回放 full query log 用于复盘。
- **动态脱敏（CEP-20）**：`cql3.functions.masking` 包提供 `mask_inner` / `mask_outer` / `mask_default` / `mask_null` / `mask_hash` / `mask_replace`，由 `UNMASK`、`SELECT_MASKED` 权限与 `dynamic_data_masking_enabled` 控制。
- **Guardrails（4.1+）**：`db.guardrails.Guardrails` 集中管理 soft/hard 限制（表数量、分区大小、查询复杂度等）；soft 告警，hard 拒绝，具体行为取决于配置。

## Source Map

| 机制 | 5.0.9 落点 |
| --- | --- |
| 认证与授权默认值 | `conf/cassandra.yaml:193-217` |
| CIDR 默认实现与模式 | `conf/cassandra.yaml:250-274`、`auth/CassandraCIDRAuthorizer.java:40-55,114-152` |
| 动态脱敏开关 | `conf/cassandra.yaml:1973`、`config/Config.java:639` |
| 脱敏函数与列绑定 | `cql3/functions/masking/MaskingFcts.java:28-36`、`cql3/functions/masking/ColumnMask.java:51-84` |
| 审计默认关闭 | `conf/cassandra.yaml:1891-1903` |

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)

## References

- [Cassandra Security](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/security.html)
- [Cassandra Dynamic Data Masking](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dynamic-data-masking.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
