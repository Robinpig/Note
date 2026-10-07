## Introduction

协议本身（四种授权模式、access token / refresh token、授权服务器与资源服务器的角色划分）见 [OAuth 协议](/docs/CS/CN/HTTP/OAuth.md)。
本篇只讲 Spring 生态如何落地 OAuth 2.0 / OpenID Connect 1.0。

需要先厘清两个历史分界：

1. 独立的 **Spring Security OAuth**（`spring-security-oauth`）项目已于 2022 年 5 月结束维护（EOL）；从 Spring Security 5 开始，OAuth 2.0 能力被收编进 Spring Security 主模块。
2. **Spring Authorization Server** 曾作为独立项目存在，从 **Spring Security 7.0 / Boot 4 起已并入 Spring Security 主线**，依赖管理也统一由 Spring Security 提供，无需再单独声明版本。

因此现在的标准组合是：

| 角色 | 实现 | 典型 starter |
| ---- | ---- | ---- |
| 客户端 Client（拿 token 访问资源 / 第三方登录） | Spring Security 的 OAuth2 Client | `spring-boot-starter-security-oauth2-client` |
| 资源服务器 Resource Server（校验 token、保护 API） | Spring Security 的 OAuth2 Resource Server | `spring-boot-starter-security-oauth2-resource-server` |
| 授权服务器 Authorization Server（签发 token） | 原 Spring Authorization Server，已并入 Spring Security | `spring-boot-starter-security-oauth2-authorization-server` |

> [!WARNING]
> 旧 starter 名 `spring-boot-starter-oauth2-client` / `-resource-server` / `-authorization-server` 在 Boot 4 已弃用，建议统一换成 `spring-boot-starter-security-oauth2-*`。

## Client

OAuth2 Client 负责发起授权、保存与刷新 token、在调用下游时自动带上 `Authorization: Bearer` 头。

### Client Registration

一个对接的第三方提供方（GitHub、Google、自研认证中心）抽象为一个 `ClientRegistration`，配置前缀 `spring.security.oauth2.client.registration`：

```yaml
spring:
  security:
    oauth2:
      client:
        registration:
          github:
            client-id: ${GITHUB_CLIENT_ID}
            client-secret: ${GITHUB_CLIENT_SECRET}
            scope: read:user, user:email
        provider:
          github:
            authorization-uri: https://github.com/login/oauth/authorize
            token-uri: https://github.com/login/oauth/access_token
            user-info-uri: https://api.github.com/user
            user-name-attribute: id
```

GitHub、Google、Okta 等常见提供方 Spring 已经内置默认值，通常只需给 `client-id` / `client-secret`。

### Login

引入 client starter 后，最常见用途是“使用第三方账号登录”（实际是基于 OAuth2 的 OIDC SSO）。把普通表单登录的配置换成 `oauth2Login()`：

```java
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/", "/login**").permitAll()
                .anyRequest().authenticated())
            .oauth2Login(Customizer.withDefaults()); // 触发授权码流程
        return http.build();
    }
}
```

登录成功后可通过 `OAuth2AuthenticationToken` / `OAuth2User` 拿到用户信息（OIDC 下是 `OidcUser`，含 id_token claims）。

### Authorized Client

服务端自己作为 client 去调用受保护资源时，用 `@RegisteredOAuth2AuthorizedClient` 注入一个已授权的 access token，过期会自动刷新：

```java
@GetMapping("/repos")
public String repos(@RegisteredOAuth2AuthorizedClient("github")
                    OAuth2AuthorizedClient authorizedClient,
                    RestClient restClient) {
    String token = authorizedClient.getAccessToken().getTokenValue();
    return restClient.get()
            .uri("https://api.github.com/user/repos")
            .headers(h -> h.setBearerAuth(token))
            .retrieve().body(String.class);
}
```

`AuthorizedClientService` 负责 token 的持久化（默认内存 `InMemoryOAuth2AuthorizedClientService`，生产应换成 JDBC/Redis 实现）。

## Resource Server

资源服务器的职责是**校验**请求带来的 Bearer token，本身不参与用户登录。两种主流校验方式：

- **JWT 自校验**：本地用授权服务器的 JWK 公钥验签、解析 claims，无需每次远程调用（`oauth2ResourceServer().jwt()`）。
- **Opaque Token 内省**：token 是不透明随机串，调用授权服务器的 introspection endpoint 校验（`oauth2ResourceServer().opaqueToken()`）。

```java
http
    .authorizeHttpRequests(auth -> auth
        .requestMatchers("/api/public").permitAll()
        .requestMatchers("/api/admin").hasAuthority("SCOPE_admin")
        .anyRequest().authenticated())
    .oauth2ResourceServer(oauth2 -> oauth2.jwt(Customizer.withDefaults()));
```

```yaml
spring:
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: https://idp.example.com/issuer   # 据此自动发现 JWK set
```

JWT 里的 `scope` 会被映射为 `SCOPE_xxx` 权限，自定义 claim→authority 用 `JwtAuthenticationConverter`。

## Authorization Server

当系统需要自己签发 token（而不是对接 GitHub 这类外部 IdP）时，用 Authorization Server：注册客户端（`RegisteredClientRepository`）、配置 JWK 源（签名密钥）、暴露授权端点与 token 端点，签发 JWT access token 与 refresh token。它是协议意义上的"授权服务器"，与上面的 Client、Resource Server 可以分属不同服务。

### Merged into Spring Security 7.0

Spring Authorization Server 自 2020 年起是独立项目，**2025 年 9 月官宣并入 Spring Security，随 7.0 一起发布**。这次合并对用户的影响被刻意压得很小：

| 事项 | 变化 |
| ---- | ---- |
| Maven 坐标 | **不变**，仍是 `org.springframework.security:spring-security-oauth2-authorization-server` |
| 版本号 | **改为跟随 Spring Security**（Boot 4.1.1 → 7.1.1），不再有独立版本线 |
| 依赖管理 | 由 `spring-security-bom` 提供，Boot BOM 里已无对应版本属性 |
| 绝大多数类名与包路径 | 保持不变 |

> [!WARNING]
> **不存在 Spring Authorization Server 2.x。** 历史上只发过 `2.0.0-M1` / `2.0.0-M2` 两个里程碑就被废弃，改号为 7.0.0 以对齐 Spring Security。看到"升级到 SAS 2.0"的说法都是描述了一个从未 GA 的版本。

### Two Package Relocations When Upgrading

真正会让编译报错的只有两个类，它们被移到了 `spring-security-config` 这个 jar，而且**没有搬进同一个包**：

| 类 | 原位置（SAS ≤ 1.5.x） | 现位置（Security ≥ 7.0） |
| ---- | ---- | ---- |
| `OAuth2AuthorizationServerConfiguration` | `…oauth2.server.authorization.config.annotation.web.configuration` | `…config.annotation.web.configuration` |
| `OAuth2AuthorizationServerConfigurer` | `…oauth2.server.authorization.config.annotation.web.configurers` | `…config.annotation.web.configurers.oauth2.server.authorization` |

同时，**大家最常调用的静态方法 `OAuth2AuthorizationServerConfiguration.applyDefaultSecurity(http)` 被删除了**。替代写法是自己构造 configurer 并显式注册：

```java
@Bean
SecurityFilterChain authorizationServerSecurityFilterChain(HttpSecurity http) throws Exception {
    http
        .securityMatcher(new OrRequestMatcher(
                new AntPathRequestMatcher("/oauth2/authorize"),
                new AntPathRequestMatcher("/oauth2/token"),
                new AntPathRequestMatcher("/oauth2/jwks"),
                new AntPathRequestMatcher("/connect/register"),
                new AntPathRequestMatcher("/userinfo"),
                new AntPathRequestMatcher("/connect/logout")))
        .with(new OAuth2AuthorizationServerConfigurer(), server -> server.oidc(
                oidc -> oidc.clientRegistrationEndpoint(Customizer.withDefaults())));
    return http.build();
}
```

> [!TIP]
> IDE 的"整理 import"通常能自动找到搬走后的第一个类，但常常抓不住包路径深了五层的 `OAuth2AuthorizationServerConfigurer`——报错信息会伪装成"包不存在"而不是"类改名"。遇到这种情况直接手动补第二个 import。

### RegisteredClient and PKCE

```java
RegisteredClient client = RegisteredClient.withId(UUID.randomUUID().toString())
        .clientId("gateway")
        .clientSecret("{noop}secret")            // 生产用 BCrypt / {pbkdf2}
        .authorizationGrantType(AuthorizationGrantType.AUTHORIZATION_CODE)
        .authorizationGrantType(AuthorizationGrantType.REFRESH_TOKEN)
        .redirectUri("https://app.example.com/login/oauth2/code/gateway")
        .scope("read")
        .clientSettings(ClientSettings.builder()
                .requireProofKey(true)           // 强制 PKCE
                .requireAuthorizationConsent(false)
                .build())
        .tokenSettings(TokenSettings.builder()
                .accessTokenTimeToLive(Duration.ofMinutes(15))
                .refreshTokenTimeToLive(Duration.ofDays(7))
                .build())
        .build();
```

`RegisteredClientRepository` 开发期可用 `InMemoryRegisteredClientRepository`，生产需要换成 JDBC（`JdbcRegisteredClientRepository`）实现。另外 7.x 起 `RegisteredClient` 实现了 `Serializable`，便于序列化到自定义存储。

token 内容的定制走 `OAuth2TokenGenerator` / `OAuth2TokenCustomizer<JwtEncodingContext>`，往 access token 里加业务 claim 的标准入口就是后者。

## Common Authorization Model Selection

| 模式 | 场景 |
| ---- | ---- |
| Authorization Code + PKCE | 有后端的 Web 应用、现代 SPA / App（首选） |
| Client Credentials | 服务间调用（machine-to-machine），无用户参与 |
| Refresh Token | access token 过期后无感续期 |
| Resource Owner Password | 已不推荐，仅在迁移遗留系统、高度信任时使用 |
| Implicit / 密码隐式 | OAuth 2.1 已废弃，不要用 |

## Links

- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring Web MVC](/docs/CS/Framework/Spring/MVC.md)
- [Spring Authorization Server 并入 Spring Security 公告](https://spring.io/blog/2025/09/11/spring-authorization-server-moving-to-spring-security-7-0)

## References

1. [Spring Security Reference - OAuth2](https://docs.spring.io/spring-security/reference/servlet/oauth2/index.html)
2. [Spring Authorization Server moving to Spring Security 7.0（官方公告）](https://spring.io/blog/2025/09/11/spring-authorization-server-moving-to-spring-security-7-0)
3. [OAuth 2.1 Authorization Framework Draft](https://datatracker.ietf.org/doc/draft-ietf-oauth-v2-1/)
4. [RFC 7636 - Proof Key for Code Exchange（PKCE）](https://datatracker.ietf.org/doc/html/rfc7636)
