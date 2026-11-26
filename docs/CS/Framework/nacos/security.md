# Nacos Security: Authentication and RBAC

## Introduction

Nacos 自带鉴权的定位非常明确：**为「可信内网」设计的弱鉴权系统，不是面向公网的强安全方案**。它防的是内网误用与越权，不是公网攻击。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。鉴权 SPI 在 `auth` / `plugin/auth`，默认实现在 `plugin-default-impl/nacos-default-auth-plugin`。

反直觉点：

- **3.3+ Docker 镜像默认开启 Client API 鉴权**；3.2.4 源码侧 `nacos.core.auth.enabled` 默认值仍是 `false`，但控制台鉴权 `console.enabled` 默认 `true`。
- 网上常见的「3.x 规范键是 `nacos.plugin.auth.type`」是错的——3.2.4 全树只有 `nacos.core.auth.system.type`（常量 `Constants.Auth.NACOS_CORE_AUTH_SYSTEM_TYPE`）。
- 自 **2.4.0** 起不再内置默认密码 `nacos/nacos`；首次开启鉴权必须显式初始化管理员，否则控制台进不去。
- 3.2.4 新增 **AI 资源匿名访问**：开启后会自动建一个系统保留用户 / 角色，授予 `public:*:ai/*` 的读权限。

## Why the Auth Boundary Is Weak

官方文档的原话：

> Nacos is an internal microservice component and must run in a trusted internal network. Do not expose it to the public Internet... It is a weak auth system, not a strong auth system designed to resist malicious attacks.

因此：绝不裸奔公网；若必须在不可信网络运行，应叠加外部安全边界（反向代理鉴权、网络隔离、更强鉴权插件）。本篇只讲 Nacos 自带鉴权怎么开、怎么用。

## Enable Authentication

配置在 `application.properties`（非 Docker）或环境变量（Docker）。核心键定义在 `plugin/auth` 的 `Constants.Auth`：

```java
public static class Auth {
    
    public static final String NACOS_CORE_AUTH_ENABLED = "nacos.core.auth.enabled";
    
    public static final String NACOS_CORE_AUTH_CONSOLE_ENABLED =
        "nacos.core.auth.console.enabled";
    
    public static final String NACOS_CORE_AUTH_ADMIN_ENABLED = "nacos.core.auth.admin.enabled";
    
    public static final String NACOS_CORE_AUTH_SYSTEM_TYPE = "nacos.core.auth.system.type";
    
    public static final String NACOS_CORE_AUTH_CACHING_ENABLED =
        "nacos.core.auth.caching.enabled";
    
    public static final String NACOS_CORE_AUTH_SERVER_IDENTITY_KEY =
        "nacos.core.auth.server.identity.key";
    
    public static final String NACOS_CORE_AUTH_SERVER_IDENTITY_VALUE =
        "nacos.core.auth.server.identity.value";
}
```

典型配置：

```properties
nacos.core.auth.system.type=nacos
nacos.core.auth.enabled=true
nacos.core.auth.admin.enabled=true       # 默认 true
nacos.core.auth.console.enabled=true     # 默认 true
nacos.core.auth.server.identity.key=${custom_server_identity_key}
nacos.core.auth.server.identity.value=${custom_server_identity_value}
nacos.core.auth.plugin.nacos.token.secret.key=${custom_base64_token_secret_key}
```

为什么多数开关「改完立即生效」？`AuthConfigs` 订阅 `ServerConfigChangeEvent`，事件到达时把所有字段重新从环境读一遍：

```java
@Override
public void onEvent(ServerConfigChangeEvent event) {
    try {
        authEnabled =
            EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_ENABLED, Boolean.class, false);
        consoleAuthEnabled = EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_CONSOLE_ENABLED,
            Boolean.class, true);
        cachingEnabled = EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_CACHING_ENABLED,
            Boolean.class, true);
        serverIdentityKey =
            EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_SERVER_IDENTITY_KEY, "");
        serverIdentityValue =
            EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_SERVER_IDENTITY_VALUE, "");
        nacosAuthSystemType =
            EnvUtil.getProperty(Constants.Auth.NACOS_CORE_AUTH_SYSTEM_TYPE, "");
        refreshPluginProperties();
    } catch (Exception e) {
        LOGGER.warn("Upgrade auth config from env failed, use old value", e);
    }
}
```

> [!WARNING]
> 虽然 `nacosAuthSystemType` 也被重新读取，但**插件 Bean 是按 `system.type` 在启动时条件装配的**，运行时改它不会换插件实现——插件切换仍需重启。另外 `validate()` 会校验：开启鉴权后 `system.type` 不能为空，集群模式（非 standalone）下 `server.identity.key/value` 不能为空。

关键约束：

- **`token.secret.key` 必须自定义、Base64 解码 ≥ 32 字节**，绝不用示例值；节点间不一致会报 `403 invalid token`（见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)）。
- **`server.identity` 集群必填且所有节点一致**，不要跨集群复用。
- 切换 secret 时要保证旧 token 仍在有效期内平滑过渡；设成无效值会导致无法登录。

Docker 用等价环境变量：`NACOS_AUTH_ENABLE=true` / `NACOS_AUTH_SYSTEM_TYPE=nacos` / `NACOS_AUTH_TOKEN` / `NACOS_AUTH_IDENTITY_KEY` / `NACOS_AUTH_IDENTITY_VALUE`。

## Token (JWT)

默认插件用 JWT，登录后签发 token，后续请求带 `Authorization: Bearer <token>`。`JwtTokenManager.createToken` 展示了签发逻辑——鉴权关闭且没配密钥时直接返回占位串 `AUTH_DISABLED`：

```java
public String createToken(String userName) {
    // create a token when auth enabled or nacos.core.auth.plugin.nacos.token.secret.key is configured
    if (!authConfigs.isAuthEnabled() && null == jwtParser) {
        return AUTH_DISABLED_TOKEN;
    } else if (authConfigs.isAuthEnabled()) {
        // check nacos.core.auth.plugin.nacos.token.secret.key only if auth enabled
        checkJwtParser();
    }
    return jwtParser.jwtBuilder().setUserName(userName)
        .setExpiredTime(this.tokenValidityInSeconds).compact();
}
```

密钥长度不是「建议」而是硬校验，且直接决定 HMAC 算法（HS256 / HS384 / HS512）：

```java
public NacosJwtParser(String base64edKey) {
    this.validKey(base64edKey);
    byte[] decode = Base64Decode.decode(base64edKey);
    int bitLength = decode.length << 3;
    if (bitLength < 256) {
        String msg = "The specified key byte array is " + bitLength + " bits which "
            + "is not secure enough for any JWT HMAC-SHA algorithm.  The JWT "
            + "JWA Specification (RFC 7518, Section 3.2) states that keys used with HMAC-SHA algorithms MUST have a "
            + "size >= 256 bits (the key size must be greater than or equal to the hash "
            + "output size).  See https://tools.ietf.org/html/rfc7518#section-3.2 for more information.";
        throw new IllegalArgumentException(msg);
    }
    
    if (bitLength < 384) {
        this.signatureAlgorithm = NacosSignatureAlgorithm.HS256;
    } else if (bitLength < 512) {
        this.signatureAlgorithm = NacosSignatureAlgorithm.HS384;
    } else {
        this.signatureAlgorithm = NacosSignatureAlgorithm.HS512;
    }
    this.key = new SecretKeySpec(decode, signatureAlgorithm.getJcaName());
}
```

| 配置 | 默认 | 说明 |
| :-- | :-- | :-- |
| `nacos.core.auth.plugin.nacos.token.secret.key` | 空（必填） | 签名密钥，Base64 解码 ≥ 256 bit |
| `nacos.core.auth.plugin.nacos.token.expire.seconds` | **18000**（5 小时） | token 有效期 |
| `nacos.core.auth.plugin.nacos.token.cache.enable` | false | 是否缓存 token 解析结果 |
| `nacos.core.auth.caching.enabled` | true | 缓存用户 / 角色 / 权限 |

默认常量来自 `AuthConstants.DEFAULT_TOKEN_EXPIRE_SECONDS = 18_000L`。权限变更有约 15 秒缓存延迟（`caching.enabled=true`），改完权限后短暂仍按旧策略放行属正常。

## RBAC: User / Role / Permission

默认插件用本地 RBAC，三张表（见 [Storage](/docs/CS/Framework/nacos/storage.md) 的 `users` / `roles` / `permissions`）：`users` 存账号 + 加密密码，`roles` 存用户 → 角色（`ROLE_ADMIN`），`permissions` 存角色 → 资源 + 操作。

管理走 **`/v3/auth/*` API**（路径常量为 `USER_PATH = "/v3/auth/user"`、`ROLE_PATH = "/v3/auth/role"`、`PERMISSION_PATH = "/v3/auth/permission"`）。管理员初始化接口 `/v3/auth/user/admin` 的关键逻辑：

```java
@PostMapping("/admin")
public Result<User> createAdminUser(@RequestParam(required = false) String password) {
    
    if (StringUtils.isBlank(password)) {
        password = PasswordGeneratorUtil.generateRandomPassword();
    }
    
    if (AuthSystemTypes.NACOS.name().equalsIgnoreCase(authConfigs.getNacosAuthSystemType())) {
        if (iAuthenticationManager.hasGlobalAdminRole()) {
            return Result.failure(HttpStatus.CONFLICT.value(), "have admin user cannot use it.",
                null);
        }
        String username = AuthConstants.DEFAULT_USER;
        userDetailsService.createUser(username, password);
        roleService.addAdminRole(username);
        User result = new User();
        result.setUsername(username);
        result.setPassword(password);
        return Result.success(result);
    } else {
        return Result.failure(HttpStatus.NOT_IMPLEMENTED.value(),
            "Current auth type not supported create admin user.", null);
    }
}
```

注意三点：密码留空时**随机生成**并在响应里回传（务必保存）；只有 `system.type=nacos` 支持该接口，LDAP / OIDC 返回 `NOT_IMPLEMENTED`；已有全局管理员时返回 `409 CONFLICT`。

## Auth Plugin

`nacos.core.auth.system.type` 选择插件，3.2.4 随发行版提供三个实现，各自通过 SPI 文件注册：

| 插件模块 | 类型值 | 适用 |
| :-- | :-- | :-- |
| `nacos-default-auth-plugin` | `nacos` | 小规模、内网 RBAC（本地用户 / 角色 / 权限 / JWT） |
| `nacos-ldap-auth-plugin` | `ldap` | 已有 LDAP 目录，认证交给 LDAP，Nacos 仍管授权 |
| `nacos-oidc-auth-plugin` | `oidc` | 企业 SSO / MFA，认证委托外部 IdP |

默认插件内部的 `AuthSystemTypes` 枚举只有 `NACOS`、`LDAP` 两项；`oidc` 是独立插件，其类型值由 `plugin/auth` 的 `OidcProtocolConstants.AUTH_PLUGIN_TYPE = "oidc"` 提供——所以「枚举里没有 oidc」不代表不支持 OIDC。

> [!WARNING]
> 网上不少地方写「3.x 规范键是 `nacos.plugin.auth.type`，旧别名 `nacos.core.auth.system.type`」——以 3.2.4 源码为准这是反的：`nacos.plugin.auth.type` 全树 0 命中，真实存在的只有 `nacos.core.auth.system.type`，且 `AuthErrorCode.INVALID_TYPE` 的报错文案就是 "Please set `nacos.core.auth.system.type`"。别按前者配，配了不生效。

## AI Resource Anonymous Access (3.2.4)

3.2.4 新增 `nacos.core.auth.nacos.anonymous.ai.enabled`（默认 `false`）。开启后 `AnonymousAccessInitializer` 会在启动时补齐一套保留身份：

```java
@PostConstruct
public void init() {
    if (!authConfigs.isAiAnonymousEnabled()) {
        LOGGER.info("[ANONYMOUS-INIT] AI anonymous access is disabled, skip initialization.");
        return;
    }
    try {
        ensureAnonymousUser();
        ensureAnonymousRole();
        ensureDefaultPermission();
    } catch (Exception e) {
        LOGGER.error("[ANONYMOUS-INIT] Failed to initialize anonymous access", e);
    }
}
```

保留用户是 `__nacos_anonymous__`、角色是 `__nacos_anonymous_role__`，默认权限为 `public:*:ai/*` 的读操作（`r`）。这是为 PUBLIC 范围 AI 资源提供免登录读取的通道，与 AI Registry 的 `scope` 字段联动（见 [AI Registry](/docs/CS/Framework/nacos/ai-registry.md)）；生产按需开启。

## Console and Transport

- `nacos.core.auth.console.enabled=true`（默认）开启控制台登录鉴权；可关闭开源控制台、引导到自定义控制台，满足「只留 API、不暴露 UI」。
- 独立 Console 自带 `/v3/console/health/liveness` 与 `/readiness`（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）。
- Nacos **默认不启用传输层加密**，明文走 HTTP 8848 / gRPC 9848，没有「一键 TLS 开关」。生产加密靠前置 LB / Ingress / Service Mesh 做 TLS 终止或 mTLS，配置随所选组件而定。

## Boundary Checklist

- 不暴露公网；不可信网络前加外部安全边界。
- 必开 `enabled=true`，自定义 `token.secret.key`（≥32B Base64）、`server.identity` 全节点一致。
- 初始化管理员密码，不给多人共用高权限账号；SDK / OpenAPI / 控制台账号分别管理。
- 敏感配置用配置加密插件（`encrypted_data_key` 存数据密钥，原文密文）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Storage](/docs/CS/Framework/nacos/storage.md)
- [Monitoring](/docs/CS/Framework/nacos/monitoring.md)
- [AI Registry](/docs/CS/Framework/nacos/ai-registry.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)

## References

- <https://nacos.io/docs/v3.0/manual/admin/auth/>
- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
