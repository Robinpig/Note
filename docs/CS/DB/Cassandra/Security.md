## Introduction

早期 Cassandra 默认「全开」——任何人都能连、能读写所有表。现代版本把安全做成可配置的分层能力：认证、授权、传输加密、静态加密、审计、动态脱敏。生产必须显式开启，否则等于裸奔。

> 基线：Cassandra 5.0。Audit Logging 与 TDE 自 4.0；Dynamic Data Masking 与 CIDR Authorizer 自 5.0；Guardrails 自 4.1。

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

- 用 **masked column** 概念：定义列如何脱敏（hash、null、redact、partial 等），`SELECT` 时按角色权限决定是否展示明文，存储不变。适合 GDPR/合规场景。例：

```sql
CREATE TABLE users (id uuid PRIMARY KEY, ssn text MASKED WITH (FUNCTION = 'partial', '****', '**', '****'));
```

## Guardrails (4.1+) and CIDR Authorizer (5.0)

- **Guardrails**：表数量、分区大小、查询复杂度等软硬限制，越界直接拒绝而非拖垮集群。
- **CIDR Authorizer**：基于 CIDR 网段做连接授权，适合「只允许特定子网客户端」的网络层管控。

## Source-Level Classes

- **认证 / 授权 / 角色**：`auth.{IAuthenticator, IAuthorizer, IRoleManager}` 三大可插拔接口；默认实现 `PasswordAuthenticator` / `CassandraAuthorizer` / `CassandraRoleManager`，元数据存于 `system_auth`（务必调高其 RF，否则权限元数据单点）。`AllowAllAuthenticator` / `AllowAllAuthorizer` 是测试默认（等同无安全）。
- **CIDR Authorizer（CEP-33）**：`auth.CIDRAuthorizer` 按 CIDR 网段做连接授权。
- **TDE（4.0+）**：`security` 包提供 SSTable 块级加密，密钥经可插拔 `IKeyProvider` 接 KMS；与 TLS 正交（TLS 护传输中、TDE 护静态）。
- **审计**：`audit.AuditLogger` 抽象、`FileAuditLogger` / `BinAuditLogger` 实现；`fqltool` 可抓包/回放 full query log 用于复盘。
- **动态脱敏（CEP-20）**：脱敏函数为 `cql3.functions.masked` 包（mask_inner / mask_outer / mask_default / mask_null / mask_hash / mask_replace），由 `UNMASK` 权限或 `dynamic_data_masking_enabled` 控制。
- **Guardrails（4.1+）**：`service.guardrails.Guardrails` 集中管理软硬限制（表数量、分区大小、查询复杂度等），越界直接拒绝而非拖垮集群。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)
- [Architecture](/docs/CS/DB/Cassandra/Architecture.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)

## References

- [Cassandra Security (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/operating/security.html)
- [CEP-20 Dynamic Data Masking](https://cassandra.apache.org/doc/latest/cassandra/architecture/masking.html)
