## Introduction

协议本身（四种授权模式、access token / refresh token、授权服务器与资源服务器的角色划分）见 [OAuth 协议](/docs/CS/CN/HTTP/OAuth.md)。
本篇只讲 Spring 生态如何落地 OAuth 2.0 / OpenID Connect 1.0。

需要先厘清一个历史分界：独立的 **Spring Security OAuth**（`spring-security-oauth`）项目已经在 2022 年 5 月结束维护（EOL）。
从 Spring Security 5 开始，OAuth 2.0 能力被收编进 Spring Security 主模块；而“授权服务器”这一块则另起新项目 **Spring Authorization Server**。因此现在的标准组合是：

| 角色 | 实现 | 典型 starter |
| ---- | ---- | ---- |
| 客户端 Client（想要拿 token 去访问资源 / 做第三方登录） | Spring Security 的 OAuth2 Client | `spring-security-oauth2-client` |
| 资源服务器 Resource Server（校验 token、保护 API） | Spring Security 的 OAuth2 Resource Server | `spring-security-oauth2-resource-server` |
| 授权服务器 Authorization Server（签发 token） | Spring Authorization Server（独立项目） | `spring-authorization-server` |

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

当系统需要自己签发 token（而不是对接 GitHub 这类外部 IdP）时，用 Spring Authorization Server：注册客户端、配置 JWK 源（签名密钥）、授权端点与 token 端点、支持授权码 + PKCE、client_credentials 等模式，并能签发 JWT access token 与 refresh token。
它是协议意义上的“授权服务器”，与上面的 Client、Resource Server 可以分属不同服务。

## 常见授权模式选型

| 模式 | 场景 |
| ---- | ---- |
| Authorization Code + PKCE | 有后端的 Web 应用、现代 SPA / App（首选） |
| Client Credentials | 服务间调用（machine-to-machine），无用户参与 |
| Refresh Token | access token 过期后无感续期 |
| Resource Owner Password | 已不推荐，仅在迁移遗留系统、高度信任时使用 |
| Implicit / 密码隐式 | OAuth 2.1 已废弃，不要用 |

## Links

- [OAuth 协议](/docs/CS/CN/HTTP/OAuth.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Web MVC](/docs/CS/Framework/Spring/MVC.md)

## References

1. [Spring Security Reference - OAuth2](https://docs.spring.io/spring-security/reference/servlet/oauth2/index.html)
2. [Spring Authorization Server](https://spring.io/projects/spring-authorization-server)
3. [OAuth 2.1 Authorization Framework Draft](https://datatracker.ietf.org/doc/draft-ietf-oauth-v2-1/)
