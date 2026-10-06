## Introduction

Kafka 的安全分三层：**认证**（SASL 确认「你是谁」）→ **传输加密**（SSL/TLS）→ **授权**（ACL 确认「你能做什么」）。4.x 的一个关键变化是**ACL 已全部迁到 KRaft metadata log**，不再是 ZooKeeper 时代的 `/brokers/topics/...` 路径。

> 版本基线：**4.3.1**（`gradle.properties:17`）。

```tex
Client ──SASL 认证──▶ Broker ──▶ Controller
                        │         └─ ACL 存 __cluster_metadata（KRaft metadata log）
                        └──SSL/TLS 加密传输
```

## SASL

### 默认值（多与常见资料不符）

> [!IMPORTANT]
> **broker 端与客户端端的默认机制都是 `GSSAPI`（Kerberos），不是 PLAIN。**
>
> | 配置 | 位置 | 默认值 |
> | ---- | ---- | ------ |
> | `sasl.enabled.mechanisms` | broker | `GSSAPI` |
> | `sasl.mechanism` | 客户端 | `GSSAPI` |
> | `sasl.mechanism.inter.broker.protocol` | broker | `GSSAPI` |
>
> `PLAIN` 只出现在测试代码里（如 `KafkaClusterTestKit.java:233`），**不是默认值**。

`clients/src/main/java/org/apache/kafka/common/config/internals/BrokerSecurityConfigs.java:99`：
```java
// 实际以 Collections.singletonList 形式
private static final List<String> DEFAULT_SASL_ENABLED_MECHANISMS = Collections.singletonList("GSSAPI");
```

`clients/.../SaslConfigs.java:35`：
```java
public static final String DEFAULT_SASL_MECHANISM = GSSAPI_MECHANISM;
```

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `sasl.jaas.config` | **null（必须显式设置）** | SaslConfigs.java:380 |
| **`sasl.kerberos.service.name`** | **null** | :370 |
| `sasl.login.callback.handler.class` | null | :382 |
| `sasl.client.callback.handler.class` | null | :381 |
| `sasl.server.callback.handler.class` | null | BrokerSecurityConfigs.java:179 |
| `sasl.login.class` | null | SaslConfigs.java:383 |
| `sasl.kerberos.kinit.cmd` | `/usr/bin/kinit` | :65 |
| `sasl.kerberos.ticket.renew.window.factor` | 0.80 | :70 |
| `sasl.kerberos.ticket.renew.jitter` | 0.05 | :74 |
| `sasl.kerberos.min.time.before.relogin` | 60000 | :78 |
| `sasl.login.refresh.window.factor` | 0.80 | :86 |
| `sasl.login.refresh.min.period.seconds` | 60 | :100 |
| `sasl.login.refresh.buffer.seconds` | 300 | :108 |
| `sasl.login.retry.backoff.ms` | 100 | :130 |
| `sasl.login.retry.backoff.max.ms` | 10000 | :124 |
| `connections.max.reauth.ms` | 0L | BrokerSecurityConfigs.java:111 |
| `sasl.server.max.receive.size` | 524288（512KB） | :119 |
| `sasl.kerberos.principal.to.local.rules` | `["DEFAULT"]` | :65 |

> [!WARNING]
> **`sasl.kerberos.service.name` 默认是 `null`**，不是常见资料说的 `kafka`。用 Kerberos 时**必须显式设置**，否则会认证失败。
>
> 同时下列配置名在 4.3.1 中**全仓零命中**，不要写进笔记：
> - `sasl.kerberos.minimum.version`
> - `sasl.realm`
> - `sasl.token.broker.renew.interval.ms`
> - `sasl.login.delegation.token.*`（全部）

### OAUTHBEARER

4.x 已支持，配置项规模很大：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `sasl.oauthbearer.jwt.retriever.class` | `org.apache.kafka.common.security.oauthbearer.DefaultJwtRetriever` | SaslConfigs.java:136 |
| `sasl.oauthbearer.jwt.validator.class` | `...DefaultJwtValidator` | :150 |
| `sasl.oauthbearer.assertion.algorithm` | `RS256`（合法值 `ES256`/`RS256`）| :205 |
| `sasl.oauthbearer.assertion.claim.exp.seconds` | 300 | :216 |
| `sasl.oauthbearer.assertion.claim.nbf.seconds` | 60 | :242 |
| `sasl.oauthbearer.assertion.claim.jti.include` | false | :236 |
| `sasl.oauthbearer.scope.claim.name` | `scope` | :303 |
| `sasl.oauthbearer.sub.claim.name` | `sub` | :309 |
| `sasl.oauthbearer.jwks.endpoint.refresh.ms` | 3600000（1 小时）| :330 |
| `sasl.oauthbearer.jwks.endpoint.retry.backoff.ms` | 100 | :345 |
| `sasl.oauthbearer.jwks.endpoint.retry.backoff.max.ms` | 10000 | :339 |
| `sasl.oauthbearer.clock.skew.seconds` | 30 | :351 |
| `sasl.oauthbearer.header.urlencode` | false | :366 |
| `sasl.oauthbearer.expected.audience` | `List.of()`（空）| :412 |
| `sasl.oauthbearer.token.endpoint.url` / `jwks.endpoint.url` / `expected.issuer` / `client.credentials.client.id` | null | :406,407,413,390 |

### Delegation Token（令牌代理）

让客户端用 token 而非长期 Kerberos 凭证，便于短期授权。

> [!WARNING]
> 配置在 **`server-common/.../server/config/DelegationTokenManagerConfigs.java`**（**不在 `KafkaConfig`**），且**只有 4 个**：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `delegation.token.secret.key` | **null（PASSWORD 类型）** | :31（注册 :50）|
| `delegation.token.max.lifetime.ms` | **604800000（7 天）** | :38（注册 :51）|
| `delegation.token.expiry.time.ms` | 86400000（1 天）| :42（注册 :52）|
| `delegation.token.expiry.check.interval.ms` | 3600000（1 小时）| :46（注册 :53）|

**总开关逻辑**（`:63`）：

```java
tokenAuthEnabled = secretKey != null && !secretKey.value().isEmpty();
```

> [!IMPORTANT]
> **secret key 未配置则整个 delegation token 认证与 API 直接禁用** —— 不是「配了但不生效」，是整个功能关闭。文档印证：`docs/security/authentication-using-sasl.md:724`。

> [!NOTE]
> `DelegationTokenCache`（`clients/.../token/delegation/internals/DelegationTokenCache.java`）是**纯内存缓存类，内无任何配置读取**。
>
> 下列配置名在 4.3.1 中**不存在**：`delegation.token.lifetime.ms`、`delegation.token.renew.interval.ms`、`delegation.token.max.renewable.expiry`、`delegation.token.secret.hmac.init.expiry.ms`、`delegation.token.primary.scheme`。

### SCRAM

- `ScramLoginModule.java:31-33`：JAAS 选项为 `username`、`password`，外加 `tokenauth`。
- `ScramCredentialUtils`（`clients/.../scram/internals/`）公开方法仅三个：`credentialToString`(:43)、`credentialFromString`(:55)、`createCache`(:80)。

> [!WARNING]
> **`SCRAMLoginValidator` 类在 4.3.1 中不存在**（全仓 grep 无匹配）。Scram internals 包只有 `ScramSaslClient`/`ScramSaslServer`/`ScramFormatter`/`ScramMessages`/`ScramExtensions`/`ScramMechanism`/`ScramCredentialUtils`/`ScramServerCallbackHandler`/`ScramSaslClientProvider`/`ScramSaslServerProvider`。

## SSL

### 核心默认值

`clients/src/main/java/org/apache/kafka/common/config/SslConfigs.java`：

| 配置名 | 默认值 | 行号 | 备注 |
| ------ | ------ | ---- | ---- |
| **`ssl.protocol`** | **`TLSv1.3`** | 40 | 首选 |
| **`ssl.enabled.protocols`** | **`TLSv1.2,TLSv1.3`** | 56 | ⚠️ 不含 TLSv1/1.1 |
| `ssl.keystore.type` | **`JKS`** | 61 | ⚠️ 4.x **未**改 PKCS12 |
| `ssl.truststore.type` | **`JKS`** | 91 | 同上 |
| **`ssl.keymanager.algorithm`** | **`KeyManagerFactory.getDefaultAlgorithm()`** | 104 | ⚠️ **不是 `SunX509`** |
| **`ssl.trustmanager.algorithm`** | **`TrustManagerFactory.getDefaultAlgorithm()`** | 109 | ⚠️ **既非 `PKIX` 也非 `SunX509`** |
| **`ssl.endpoint.identification.algorithm`** | **`https`** | 113 | ⚠️ 4.x 已默认开启主机名校验 |
| `ssl.cipher.suites` | `List.of()`（空 = JVM 全部可用）| 129 | |
| `ssl.client.auth` | `none` | BrokerSecurityConfigs.java:88 | |
| `ssl.principal.mapping.rules` | **`DEFAULT`** | BrokerSecurityConfigs.java:55 | ⚠️ 不是表达式列表 |
| `principal.builder.class` | `...DefaultKafkaPrincipalBuilder` | :74 | |

> [!IMPORTANT]
> **本篇最反直觉的三条**：
>
> 1. **`ssl.trustmanager.algorithm` 既不是 `PKIX` 也不是 `SunX509`** —— 默认是 `TrustManagerFactory.getDefaultAlgorithm()`，即 **JVM 运行时动态值**（HotSpot 上通常解析为 `PKIX`，但**代码里没有硬编码**）。`ssl.keymanager.algorithm` 同理。
>    ```java
>    // SslConfigs.java:104
>    public static final String DEFAULT_SSL_KEYMANGER_ALGORITHM = KeyManagerFactory.getDefaultAlgorithm();
>    // :109
>    public static final String DEFAULT_SSL_TRUSTMANAGER_ALGORITHM = TrustManagerFactory.getDefaultAlgorithm();
>    ```
> 2. **`ssl.endpoint.identification.algorithm` 默认已经是 `https`** —— 4.x 已强制开启主机名校验以防中间人攻击。这不是「需手动开」的配置。
> 3. **keystore/truststore 类型仍是 `JKS`**，4.x 未改 PKCS12（文档虽提支持 `[JKS, PKCS12, PEM]`）。

`ssl.principal.mapping.rules` 默认值就是单个字符串 **`DEFAULT`**（`BrokerSecurityConfigs.java:55`），不是 `RULE:...` 表达式列表。

解析逻辑在 `SslPrincipalMapper.java`（规则正则 `RULE_PATTERN` `:30`，`isDefault` 时 `toString()` 追加 `"DEFAULT"` `:195`）。行为：**返回 X.500 DN 全串**（`docs/security/authorization-and-acls.md:59`），形如：

```text
CN=writeuser,OU=Unknown,O=Unknown,L=Unknown,ST=Unknown,C=Unknown
```

> [!NOTE]
> 4.x TLS 状态：TLS v1.3 **已默认启用**，协商逻辑 `SslConfigs.java:36-38`（双端支持则用 1.3，否则回落 1.2）。

## ACL 与授权

### 4.x 最重要的变化：ACL 在 KRaft metadata log

> [!IMPORTANT]
> **ACL 已全部迁到 KRaft metadata log `__cluster_metadata`，ZK 路径不再是 ACL 的存储位置。**
>
> 官方文档 `docs/security/authorization-and-acls.md:29` 原文：
> > "Kafka provides a default implementation which store ACLs in the cluster metadata (KRaft metadata log). For KRaft clusters, use the following configuration on all nodes (brokers, controllers, or combined broker/controller nodes): `authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer`"
>
> 证据链：
> - `metadata/src/main/java/org/apache/kafka/controller/AclControlManager.java:56` —— *"manages any ACLs that are stored in the `__cluster_metadata` topic"*
> - `metadata/.../authorizer/ClusterMetadataAuthorizer.java:41` —— *"An interface for Authorizers which store state in the `__cluster_metadata` log"*
> - `metadata/.../authorizer/` 目录下**无任何 `ZooKeeperClient` 引用**，无 `/brokers/topics` ZK 路径
> - Delegation Token 同在 metadata log（`metadata/.../controller/DelegationTokenControlManager.java`）

相关类：`AclsImage`、`AclsDelta`、`AclsMutator`、`StandardAuthorizer`。

> [!NOTE]
> `__cluster_metadata` 常量定义在 `clients/.../common/internals/Topic.java:30`。
>
> 这个变化意味着：**从 ZK 迁移到 KRaft 的集群不需要单独迁移 ACL**，它随 metadata log 一起走。

### AclOperation（16 个值）

`clients/src/main/java/org/apache/kafka/common/acl/AclOperation.java`：

| 值 | code | 行号 |
| -- | ---- | ---- |
| `UNKNOWN` | 0 | 45 |
| `ANY` | 1 | 50 |
| `ALL` | 2 | 55 |
| `READ` | 3 | 60 |
| `WRITE` | 4 | 65 |
| `CREATE` | 5 | 70 |
| `DELETE` | 6 | 75 |
| `ALTER` | 7 | 80 |
| `DESCRIBE` | 8 | 85 |
| `CLUSTER_ACTION` | 9 | 90 |
| `DESCRIBE_CONFIGS` | 10 | 95 |
| `ALTER_CONFIGS` | 11 | 100 |
| **`IDEMPOTENT_WRITE`** | 12 | 105 |
| **`CREATE_TOKENS`** | 13 | 110 |
| **`DESCRIBE_TOKENS`** | 14 | 115 |
| **`TWO_PHASE_COMMIT`** | 15 | 120 |

> [!TIP]
> 后三个（`CREATE_TOKENS`/`DESCRIBE_TOKENS`/`TWO_PHASE_COMMIT`）常被漏掉。源码注释 `:122-123` 提示上限 30 个。
>
> 蕴含关系（`:26-38`）：`ALL` ⇒ 全部；`READ`/`WRITE`/`DELETE`/`ALTER` ⇒ `DESCRIBE`；`ALTER_CONFIGS` ⇒ `DESCRIBE_CONFIGS`。所以授 `WRITE` 隐含 `DESCRIBE`。

### ResourceType（8 个值）

`clients/.../common/resource/ResourceType.java`：`UNKNOWN(0)` `:31`、`ANY(1)` `:36`、`TOPIC(2)` `:41`、`GROUP(3)` `:46`、`CLUSTER(4)` `:51`、`TRANSACTIONAL_ID(5)` `:56`、`DELEGATION_TOKEN(6)` `:61`、`USER(7)` `:66`。

**PatternType**（`PatternType.java`）：`UNKNOWN(0)` `:33`、`ANY(1)` `:38`、`MATCH(2)` `:51`、`LITERAL(3)` `:60`、`PREFIXED(4)` `:67`。

### authorizer.class.name

| 项 | 值 | 出处 |
| -- | -- | ---- |
| 常量 | `authorizer.class.name` | `server-common/.../ServerConfigs.java:119` |
| **默认值** | **`""`（空字符串）** | `:120`（注册 `:139`，带 `NonNullValidator`）|
| 加载逻辑 | 空 → `None`（**不装任何 authorizer**）| `core/.../KafkaConfig.scala:253-260` |
| 生产用值 | `org.apache.kafka.metadata.authorizer.StandardAuthorizer` | 文档 `:32` |

> [!WARNING]
> **`authorizer.class.name` 默认是空字符串，等于「不装任何 authorizer」** —— 不配就**没有任何 ACL 校验**。这是 4.x 新部署最容易漏的安全配置。

### super.users

- 定义：`metadata/.../authorizer/StandardAuthorizer.java:58` → `SUPER_USERS_CONFIG = "super.users"`，读取 `:196`
- 文档示例（`authorization-and-acls.md:50`）：`super.users=User:Bob;User:Alice` —— **分号分隔**（因为 SSL 用户名可能含逗号）
- **没有** `process.super.users`，**没有**改名为 `broker` 超级用户

`allow.everyone.if.no.acl.found` 的默认行为：资源无 ACL 时**仅 super user 可访问**（`authorization-and-acls.md:38`）。

**KRaft Principal Forwarding**（4.x 特有，`authorization-and-acls.md:52-55`）：admin 请求经 broker 以 `Envelope` 转发到 controller，controller 先认证 broker principal 再认证转发的 client principal。自定义 principal 必须实现 `KafkaPrincipalSerde`。

### CLI

**`kafka-acls.sh`**（`bin/kafka-acls.sh:17` → `org.apache.kafka.tools.AclCommand`）：

> [!WARNING]
> - 类名是 **`AclCommand`（单数）**，不是 `AclsCommand`。
> - **仅支持 `--bootstrap-server` 与 `--bootstrap-controller`**（`AclCommand.java:438`、`:412-413`）。`:551` 要求二者必有其一。**`--zookeeper` 已完全移除。**
> - 动作互斥（`:553-558`）：`--list` / `--add` / `--remove` 恰好一个。
> - 资源选项：`--topic`、`--cluster`、`--group`、`--delegation-token`、`--transactional-id`、`--idempotent`。
> - `--resource-pattern-type` 在 add 时不可用 `match`（`:215`）。

**`TopicCommand`** 包名是 `org.apache.kafka.tools`（`tools/.../TopicCommand.java:18`），**不是** `kafka.admin.TopicCommand`（0.10.x 时代）。

## 需要打假的常见说法

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「`ssl.trustmanager.algorithm` 默认 `PKIX`（或 `SunX509`）」 | ❌ **两个都不对**，是 `TrustManagerFactory.getDefaultAlgorithm()`（JVM 动态值，代码无硬编码）|
| 「`ssl.keymanager.algorithm` 默认 `SunX509`」 | ❌ `KeyManagerFactory.getDefaultAlgorithm()` 动态值 |
| 「`ssl.endpoint.identification.algorithm` 默认空，需手动开 HTTPS」 | ❌ **默认就是 `https`**，4.x 已强制主机名校验 |
| 「4.x keystore/truststore 类型改 PKCS12」 | ❌ **仍是 `JKS`**，4.x 未改 |
| 「`ssl.enabled.protocols` 含 TLSv1/1.1」 | ❌ `TLSv1.2,TLSv1.3`；且 `ssl.protocol` 本身默认已是 `TLSv1.3` |
| 「`ssl.principal.mapping.rules` 默认是 `RULE:^CN=(.*?)...`」 | ❌ 默认值就是单个字符串 `DEFAULT`，原样返回 X.500 DN 全串 |
| 「4.x 的 ACL 还在 ZooKeeper `/brokers/topics/...`」 | ❌ **已在 `__cluster_metadata`**，内置 `StandardAuthorizer` 无 ZK 代码路径 |
| 「`sasl.enabled.mechanisms` 服务端默认 PLAIN」 | ❌ 默认 **GSSAPI**；`PLAIN` 只在测试代码 |
| 「`sasl.kerberos.service.name` 默认 `kafka`」 | ❌ **null**，须显式设置 |
| 「有 `sasl.kerberos.minimum.version` / `sasl.realm` / `sasl.token.broker.renew.interval.ms`」 | ❌ 三者均不存在 |
| 「有 `delegation.token.lifetime.ms` / `renew.interval.ms` / `primary.scheme`」 | ❌ 全部不存在，实际只有 4 个（见上表）|
| 「有 `SCRAMLoginValidator` 类」 | ❌ 类不存在 |
| 「`authorizer.class.name` 默认 `StandardAuthorizer`」 | ❌ 默认 **`""` 空字符串**，须显式配置，否则无任何 ACL 校验 |
| 「4.x 把 `super.users` 改成 `broker` 超级用户」 | ❌ 仍为 `super.users`，无 `process.super.users` |
| 「`kafka-acls.sh --zookeeper` 仍可用」 | ❌ 仅 `--bootstrap-server` / `--bootstrap-controller` |
| 「ACL 命令类是 `AclsCommand`」 | ❌ 类名 **`AclCommand`**（单数）|
| 「`TopicCommand` 是 `kafka.admin.TopicCommand`」 | ❌ 包名 `org.apache.kafka.tools` |

## 未查到清单

- `authorizer.class.name` 除 `StandardAuthorizer` 外的 4.x 内置实现（KRaft 下 `AclControlManager` 是唯一内置路径）
- `sasl.oauthbearer.expected.audience` 为空列表时的实际校验行为（仅确认默认空）

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [KRaft](/docs/CS/MQ/Kafka/KRaft.md)
- [Broker](/docs/CS/MQ/Kafka/Broker.md)
- [ShareGroup](/docs/CS/MQ/Kafka/ShareGroup.md)
- [RabbitMQ（另一种鉴权模型）](/docs/CS/MQ/RabbitMQ.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [SslConfigs.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/clients/src/main/java/org/apache/kafka/common/config/SslConfigs.java)
3. [Authorization and ACLs](https://kafka.apache.org/documentation/#security_authorization_and_acls)
4. [Authentication using SASL](https://kafka.apache.org/documentation/#security_sasl)
