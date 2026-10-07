# Nacos Security: Authentication and RBAC

## Introduction

Nacos 官方对自带鉴权的定位非常明确：**它是一个为「可信内网」设计的弱鉴权系统，不是面向公网的强安全方案**。

> Nacos is an internal microservice component and must run in a trusted internal network. Do not expose it to the public Internet... It is a weak auth system, not a strong auth system designed to resist malicious attacks.

因此：Nacos 绝不能裸奔在公网；若必须在不可信网络运行，应叠加外部安全边界（反向代理鉴权、网络隔离、更强鉴权插件）。本篇只讲 Nacos 自带鉴权怎么开、怎么用。

## Enable Authentication

鉴权开关在 `application.properties`（非 Docker 部署）或环境变量（Docker），**修改后立即生效，无需重启**：

```properties
# 选鉴权插件（3.x 规范键 nacos.plugin.auth.type，旧别名 nacos.core.auth.system.type）
nacos.core.auth.system.type=nacos
# 开启客户端 / SDK / OpenAPI / gRPC 鉴权
nacos.core.auth.enabled=true
# Admin API 鉴权（默认 true）
nacos.core.auth.admin.enabled=true
# 控制台鉴权（默认 true）
nacos.core.auth.console.enabled=true
# 服务端之间身份识别（集群必填，且所有节点必须一致）
nacos.core.auth.server.identity.key=${custom_server_identity_key}
nacos.core.auth.server.identity.value=${custom_server_identity_value}
# 生成 JWT 的签名密钥：Base64，解码后原始密钥长度 ≥ 32 字节
nacos.core.auth.plugin.nacos.token.secret.key=${custom_base64_token_secret_key}
```

关键约束：

- **`token.secret.key` 必须自定义、足够长（Base64 解码 ≥ 32 字节）**，绝不用示例值。节点间不一致会报 **`403 invalid token`**，长时间不一致会导致请求异常（见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)）。
- **`server.identity` 集群必填且所有节点一致**；不一致会导致节点间数据不一致。
- **所有节点 secret / identity 必须相同**，且不要跨集群复用。
- 切换 `token.secret.key` 需保证旧 token 仍有效窗口内平滑；改成无效值会导致无法登录、访问异常。

Docker 镜像用环境变量等价开启：`NACOS_AUTH_ENABLE=true` / `NACOS_AUTH_SYSTEM_TYPE=nacos` / `NACOS_AUTH_TOKEN` / `NACOS_AUTH_IDENTITY_KEY` / `NACOS_AUTH_IDENTITY_VALUE`。注意 3.3+ 官方镜像默认开启 Client API 鉴权。

## Token（JWT）

默认 Nacos 鉴权用 **JWT**：登录后签发 token，后续请求带 token 访问。

| 配置 | 默认 | 说明 |
| :-- | :-- | :-- |
| `nacos.core.auth.plugin.nacos.token.secret.key` | 空（必填） | 签名密钥，Base64 ≥ 32B |
| `nacos.core.auth.plugin.nacos.token.expire.seconds` | **18000**（5 小时） | token 有效期 |
| `nacos.core.auth.plugin.nacos.token.cache.enable` | false | 是否缓存 token 解析结果 |
| `nacos.core.auth.caching.enabled` | true | 缓存用户 / 角色 / 权限 |

- token 过期需重新登录；**权限变更有约 15 秒缓存延迟**（`caching.enabled=true`），改完权限后短暂仍按旧策略放行 / 拒绝属正常。
- 鉴权是「运行时生效」的，但 **插件选择（system.type）改动需要重启**。

## RBAC: User / Role / Permission

默认 Nacos 鉴权用本地 RBAC，三张表（见 [Storage](/docs/CS/Framework/nacos/storage.md) 的 `users` / `roles` / `permissions`）：

- `users`：账号 + BCrypt 密码。
- `roles`：用户 → 角色（如 `ROLE_ADMIN`）。
- `permissions`：角色 → 资源（`resource`）+ 操作（`action`，如读 / 写）。

管理走 **`/v3/auth/*` API**（属于默认 auth 插件；其他插件不一定支持）：

- `POST /nacos/v3/auth/user` / `POST /nacos/v3/auth/user/admin`（初始化管理员）
- `POST /nacos/v3/auth/role`
- `POST /nacos/v3/auth/permission`

**管理员初始化**：自 **2.4.0** 起，Nacos **不再内置默认密码 `nacos/nacos`**。首次开启默认鉴权后，必须通过 `/nacos/v3/auth/user/admin` 设置管理员密码（控制台也会进入初始化页）；密码为空时 Nacos 随机生成并展示，务必保存。

## Auth Plugin

Nacos 3.x 把鉴权做成插件 SPI，`nacos.core.auth.system.type`（规范键 `nacos.plugin.auth.type`）选择：

| 模式 | 值 | 适用 |
| :-- | :-- | :-- |
| 默认 Nacos 鉴权 | `nacos` | 小规模、内网 RBAC（本地用户 / 角色 / 权限 / token） |
| LDAP | `ldap` | 已有 LDAP 目录；Nacos 只管角色与权限，认证交给 LDAP（3.2 起为独立可选插件） |
| OIDC / OAuth2 | `oidc` | 企业 SSO、集中身份、MFA，认证委托外部 IdP |
| 自定义 | 自定义值 | 实现 Auth Plugin SPI |

不同插件共享同一套开关，但身份源与权限模型不同；选 LDAP / OIDC 时 Nacos 仍负责角色与权限的授权。

## Console

- `nacos.core.auth.console.enabled=true`（默认）开启控制台登录鉴权。
- 可关闭开源控制台、引导到自定义控制台（鉴权插件手册 / 控制台手册），满足「只留 API、不暴露 UI」的诉求。
- 独立 Console 有自身健康检查：`/v3/console/health/liveness` 与 `/readiness`（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）。

## TLS / Transport Security

Nacos 默认**不启用传输层加密**，明文走 HTTP 8848 / gRPC 9848。官方未提供「一键 TLS 开关」式的原生配置；生产加密通常做法：

- 在 Nacos 前放 **反向代理 / LB / Ingress / Service Mesh**（如 [Istio](/docs/CS/Framework/Istio/Istio.md)）做 TLS 终止；
- 或依赖对应的安全插件 / mesh mTLS。

> 若需要「Nacos 节点间 gRPC 强制 mTLS」这类强传输安全，当前以 LB / mesh 方案为主，配置方式随所选组件而定——**不要凭印象假设 Nacos 有独立 TLS 开关**，以目标版本官方文档为准。

## Boundary of Weak Authentication

再次强调定位：Nacos 自带鉴权防的是「内网误用 / 越权」，不是「公网攻击」。生产 checklist：

- 不暴露公网；不可信网络前加外部安全边界。
- 必开 `enabled=true`，自定义 `token.secret.key`（≥32B Base64）、`server.identity` 全节点一致。
- 初始化管理员密码，不给多人共用高权限账号。
- SDK / OpenAPI / 控制台账号分别管理。
- 敏感配置用配置加密插件（`encrypted_data_key` 存数据密钥，原文密文）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Storage](/docs/CS/Framework/nacos/storage.md)
- [Monitoring](/docs/CS/Framework/nacos/monitoring.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://nacos.io/docs/v3.0/manual/admin/auth/>
- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
- <https://nacos-group.github.io/en/docs/next/manual/admin/auth>
