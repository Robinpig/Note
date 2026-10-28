# Hive Security and Governance

## Introduction

Hive 的安全分两层：**认证（Authentication，验身份）** 与 **授权（Authorization，验权限）**。生产 Hive 通常 Kerberos 打底，细粒度访问控制与审计交给 Apache Ranger，数据血缘与治理交给 Apache Atlas。4.2.1 是一次纯安全修复版，修了三个 CVE，跑 4.2.0 及更早 4.x 的集群应优先升级。

## Authentication

- **Kerberos** 为主，是安全集群的基线。
- **4.0 起 HS2 支持 SAML 2.0 / JWT**（走 Thrift over HTTP），Kerberos 与 LDAP 可并行开启。
- **HMS 也有 JWT 认证**（4.0），用于服务间调用。

## Authorization Modes

Hive 提供三套授权模式，满足不同用例：

1. **Storage Based Authorization（SBA，Metastore Server，HIVE-7583 / 0.14）**：基于底层文件系统权限控制库/表/分区级访问——HDFS 权限是唯一真相源，与 Hive 配置一致。限制：文件系统权限到目录/文件级，**无法控制列/行级**，且只对经 HMS 的访问有效；CLI 用户直连 HDFS 可绕过。
2. **SQL Standard Based Authorization（HS2，HIVE-5837 / 0.13）**：基于 SQL 标准授权，用 `GRANT` / `REVOKE` 做库/表/列/视图级细粒度控制，由 HS2 查询处理时强制执行。**注意**：对 Hive CLI 用户（直接 HDFS 访问）被禁用，否则等于给虚假安全感。
3. **Apache Ranger / Sentry（插件）**：生产事实标准——Ranger 提供 Web 策略管理、审计、动态行/列级访问控制（含 column masking），与 HMS 集成保证 HS2 与 metastore 两侧一致。

## Column/Row Masking and Audit

Ranger 可在策略里定义列脱敏（如 hash / partial mask）与行过滤（如 `dept='HR'` 仅 HR 可见），并在中央审计日志里记录所有访问。这是比 SBA / SQL Std Auth 更完整的治理闭环，也是企业安全套件「认证 → 授权 → 血缘 → 审计」全链的一环。

## Transport Security

HS2 支持 Thrift over HTTP（JWT 认证走此通道），可用 TLS/SSL 加密传输；HMS 同样可走 Thrift over HTTP。SAML bearer 认证仅在 `hive.server2.authentication=SAML` 且 transport 为 HTTP 时启用——这也是下面 CVE 的触发条件。

## 4.2.1 Security Fixes

> [!WARNING]
> **Hive 4.2.1（2026-08-25）是一次安全修复版，修了三个 CVE，影响版本均为 4.0.0 – 4.2.0**：
> - **HIVE-29622 / CVE-2026-49845**：HMS partition-name direct-SQL 路径 SQL 注入。metastore 默认开启 direct SQL（`metastore.try.direct.sql=true`），认证用户可借构造的分区名读/改非预期的分区元数据。4.2.1 把这些查找改成参数化。
> - **HIVE-29653 / CVE-2026-53561**：HS2 HTTP SAML bearer-token 校验缺陷，未授权网络攻击者可在 `authentication=SAML` + HTTP 传输的部署上伪造 `Authorization: Bearer` 以任意 Hive 用户身份拿到 HS2 会话。仅 SAML+HTTP 路径受影响；Kerberos / LDAP 部署不受此特定 CVE 影响，但仍建议升 4.2.1 拿另外两个修复。
> - **HIVE-29671 / CVE-2026-55976**：Avro SerDe 经 `avro.schema.url` 的 SSRF（2.1.0 – 4.2.0）。有 `CREATE TABLE` 权限的认证用户可令 Hive 进程抓取攻击者控制的 URL（云元数据、内网、本地文件）。4.2.1 校验 scheme/host 并默认禁用远程 HTTP schema 抓取。
>
> 结论：**Hive 的 4.x 线仍在积极安全维护，但 3.x 及更早线已无社区补丁**——跑老线等于跑一个不修 CVE 的系统。

## Links

- [Hive](/docs/CS/DB/Hive/Hive.md)
- [Architecture](/docs/CS/DB/Hive/Architecture.md)
- [Operations](/docs/CS/DB/Hive/Operations.md)

## References

1. [Hive LanguageManual Authorization](https://hive.apache.org/docs/latest/language/languagemanual-authorization/)
2. [[ANNOUNCE] Apache Hive 4.2.1 Released](https://lists.apache.org/thread/pc3jr2mj1ycmnf0cod7424qzhz94447p)
3. [Apache Hive security advisories](https://security.apache.org/projects/hive/)
4. [Apache Ranger](https://ranger.apache.org/)
