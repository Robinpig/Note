## Introduction

[Spring Security](https://spring.io/projects/spring-security) is a powerful and highly customizable authentication and access-control framework.
It is the de-facto standard for securing Spring-based applications.
Spring Security is a framework that focuses on providing both authentication and authorization to Java applications.

### Version Evolution

Spring Security 5.7 / 6.0 是一条重要分界线，理解新旧 API 对应关系是读旧资料的前提：

| 能力 | 5.x（旧） | 6.x / 7.x（现行） |
| :-- | :-- | :-- |
| 配置入口 | 继承 `WebSecurityConfigurerAdapter` | 声明 `SecurityFilterChain` Bean |
| DSL 风格 | `and()` 链式拼接 | lambda DSL（`http.authorizeHttpRequests(auth -> ...)`），`and()` 在 7.0 已移除 |
| 请求授权 | `authorizeRequests()` + `AccessDecisionManager` | `authorizeHttpRequests()` + `AuthorizationManager`（7.0 移除 `authorizeRequests`） |
| 末端拦截器 | `FilterSecurityInterceptor` | `AuthorizationFilter` |
| Context 传递 | `SecurityContextPersistenceFilter` | `SecurityContextHolderFilter` |
| 方法安全 | `@EnableGlobalMethodSecurity` | `@EnableMethodSecurity` |
| 请求匹配器 | `AntPathRequestMatcher` / `MvcRequestMatcher` | `PathPatternRequestMatcher`（7.0 移除旧匹配器） |

Spring Security 6 要求 Java 17 基线（与 Spring Framework 6 / Spring Boot 3 对齐），`javax.servlet` 全面切换为 `jakarta.servlet`；Spring Security 7 延续 Java 17 基线并对齐 Jakarta EE 11。

### Spring Security 7.0

7.0（2025-11 GA，随 Spring Boot 4 发布）是一次大版本清理，主要是**删除全部遗留 API**并内聚模块：

- **移除**：`HttpSecurity.and()`、`authorizeRequests()`、`AuthorizationManager#check`（改为 `authorize`）、`AntPathRequestMatcher` / `MvcRequestMatcher`、Password Grant（OAuth 2.0）、OpenSAML 4、`ApacheDsContainer`。
- **模块合并**：Spring Authorization Server、Kerberos 扩展并入 Spring Security 主线；原访问决策 API（`AccessDecisionManager`、`AccessDecisionVoter`）迁到独立的 `spring-security-access` 模块。
- **新能力**：一等公民的多因素认证（`AllAuthoritiesAuthorizationManager` + `Authentication.Builder`）、SPA 友好的 CSRF DSL（`csrf.spa()`）、基于 Password4j 的 Argon2/Scrypt 等编码器、OAuth 2.0 授权服务器默认启用 PKCE、`NimbusJwtEncoder` 构建器。

## Architecture

Spring Security’s Servlet support is based on Servlet Filters, so it is helpful to look at the role of Filters generally first.
The client sends a request to the application, and the container creates a FilterChain which contains the Filters and Servlet that should process the HttpServletRequest based on the path of the request URI. 
In a Spring MVC application the Servlet is an instance of DispatcherServlet. 
At most one Servlet can handle a single HttpServletRequest and HttpServletResponse. 
However, more than one Filter can be used to:
- Prevent downstream Filters or the Servlet from being invoked. In this instance the Filter will typically write the HttpServletResponse.
- Modify the HttpServletRequest or HttpServletResponse used by the downstream Filters and Servlet

Since a Filter only impacts downstream Filters and the Servlet, the order each Filter is invoked is extremely important.


### DelegatingFilterProxy

Spring provides a Filter implementation named DelegatingFilterProxy that allows bridging between the Servlet container’s lifecycle and Spring’s ApplicationContext. 
The Servlet container allows registering Filters using its own standards, but it is not aware of Spring defined Beans. 
DelegatingFilterProxy can be registered via standard Servlet container mechanisms, but delegate all the work to a Spring Bean that implements Filter.

Here is a picture of how DelegatingFilterProxy fits into the Filters and the FilterChain.

![DelegatingFilterProxy](https://docs.spring.io/spring-security/reference/_images/servlet/architecture/delegatingfilterproxy.png)

DelegatingFilterProxy looks up *Bean Filter0* from the ApplicationContext and then invokes *Bean Filter0*.

Another benefit of DelegatingFilterProxy is that it allows **delaying looking Filter bean instances**. 
This is important because the container needs to register the Filter instances before the container can startup. 
However, Spring typically uses a ContextLoaderListener to load the Spring Beans which will not be done until after the Filter instances need to be registered.


### FilterChainProxy

Spring Security’s Servlet support is contained within FilterChainProxy. 
FilterChainProxy is a special Filter provided by Spring Security that allows delegating to many Filter instances through SecurityFilterChain. 
Since FilterChainProxy is a Bean, it is typically wrapped in a DelegatingFilterProxy.

![FilterChainProxy](https://docs.spring.io/spring-security/reference/_images/servlet/architecture/filterchainproxy.png)

SecurityFilterChain is used by FilterChainProxy to determine which Spring Security Filters should be invoked for this request.

> [!TIP]
> 
> See [Security Filters](https://docs.spring.io/spring-security/reference/servlet/architecture.html#servlet-security-filters)


FilterChainProxy provides a number of advantages to registering directly with the Servlet container or DelegatingFilterProxy. 
- First, it provides a starting point for all of Spring Security’s Servlet support.
- Second, since FilterChainProxy is central to Spring Security usage it can perform tasks that are not viewed as optional.
- In addition, it provides more flexibility in determining when a SecurityFilterChain should be invoked.

```dot
strict digraph{
    req [shape="polygon" label="Request"]
    asyncFilter [shape="polygon" label="WebAsyncManagerIntegrationFilter"]
    contextFilter [shape="polygon" label="SecurityContextPersistenceFilter"]
    headerFilter [shape="polygon" label="HeaderWriterFilter"]
    csrfFilter [shape="polygon" label="CsrfFilter"]
    logoutFilter [shape="polygon" label="LogoutFilter"]
    req->asyncFilter->contextFilter->headerFilter->csrfFilter->logoutFilter
    
    logoutHandler [shape="polygon" label="LogoutHandler"]
    logoutSuccessHandler [shape="polygon" label="LogoutSuccessHandler"]
    
    logoutFilter->logoutHandler[label="logout"]
    logoutHandler->logoutSuccessHandler
    
    loginFilter [shape="polygon" label="LoginPageGeneratingWebFilter"]
    loginUserFilter [shape="polygon" label="UsernamePasswordAuthenticationFilter"]
    authenticationManager [shape="polygon" label="AuthenticationManager"]
    daoAuthenticationProvider [shape="polygon" label="DaoAuthenticationProvider"]
    logoutFilter->loginFilter[label="login"]
    loginFilter->loginUserFilter[label="login"]
    loginUserFilter->authenticationManager[label="attemptAuthentication"]
    authenticationManager->daoAuthenticationProvider[label="loadUserByUsername"]
    
    DefaultLogoutPageGeneratingFilter [shape="polygon" label="DefaultLogoutPageGeneratingFilter"]
    loginFilter->DefaultLogoutPageGeneratingFilter
    
    RequestCacheAwareFilter [shape="polygon" label="RequestCacheAwareFilter"]
    SecurityContextHolderAwareRequestFilter [shape="polygon" label="SecurityContextHolderAwareRequestFilter"]
    anonymousAuthenticationFilter [shape="polygon" label="AnonymousAuthenticationFilter"]
    sessionManagementFilter [shape="polygon" label="SessionManagementFilter"]
    exceptionTranslationFilter [shape="polygon" label="ExceptionTranslationFilter"]
    filterSecurityInterceptor [shape="polygon" label="FilterSecurityInterceptor"]
    DefaultLogoutPageGeneratingFilter->RequestCacheAwareFilter->SecurityContextHolderAwareRequestFilter->anonymousAuthenticationFilter->sessionManagementFilter->exceptionTranslationFilter->filterSecurityInterceptor
    
    accessDeniedHandler [shape="polygon" label="AccessDeniedHandler"]
    controller [shape="polygon" label="Controller"]
    filterSecurityInterceptor -> accessDeniedHandler[label="denied"]
    filterSecurityInterceptor -> controller[label="allowed"]
}
```

## Authentication

At the heart of Spring Security’s authentication model is the SecurityContextHolder. It contains the SecurityContext.

![SecurityContextHolder](https://docs.spring.io/spring-security/reference/_images/servlet/authentication/architecture/securitycontextholder.png)

### Authentication Filters

#### SecurityContextPersistenceFilter

> [!WARNING]
> `SecurityContextPersistenceFilter` 在 Spring Security 6 中已被 `SecurityContextHolderFilter` 取代。
> 新 Filter 不再负责"读 + 存"完整生命周期：它只负责从 `SecurityContextRepository` 读取并加载 context，
> 保存动作改由显式配置（`HttpSecurity.securityContext()`，默认仍写 HttpSession）完成。

SecurityContextPersistenceFilter MUST be executed BEFORE any authentication processing mechanisms.
Authentication processing mechanisms (e.g. BASIC, CAS processing filters etc) expect the SecurityContextHolder(default to using [MODE_THREADLOCAL](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)) to contain a valid SecurityContext by the time they execute.

SecurityContextPersistenceFilter populates the SecurityContextHolder with information obtained from the configured SecurityContextRepository prior to the request and stores it back in the repository once the request has completed and clearing the context holder.
By default it uses an HttpSessionSecurityContextRepository. See this class for information HttpSession related configuration options.
This filter will only execute once per request, to resolve servlet container (specifically Weblogic) incompatibilities.


#### AuthenticationProcessingFilter

AuthenticationProcessingFilter

The filter requires that you set the authenticationManager property. 
An AuthenticationManager is required to process the authentication request tokens created by implementing classes.
This filter will intercept a request and attempt to perform authentication from that request if the request matches the setRequiresAuthenticationRequestMatcher(RequestMatcher).
Authentication is performed by the `attemptAuthentication` method.


UsernamePasswordAuthenticationFilter

Wrap `UsernamePasswordAuthenticationToken` to AuthenticationManager
```java
public class UsernamePasswordAuthenticationFilter extends
        AbstractAuthenticationProcessingFilter {
    public UsernamePasswordAuthenticationFilter() {
        super(new AntPathRequestMatcher("/login", "POST"));
    }

    public Authentication attemptAuthentication(HttpServletRequest request,
                                                HttpServletResponse response) throws AuthenticationException {
        if (postOnly && !request.getMethod().equals("POST")) {
            throw new AuthenticationServiceException(
                    "Authentication method not supported: " + request.getMethod());
        }

        String username = obtainUsername(request);
        String password = obtainPassword(request);

        if (username == null) {
            username = "";
        }

        if (password == null) {
            password = "";
        }

        username = username.trim();

        UsernamePasswordAuthenticationToken authRequest = new UsernamePasswordAuthenticationToken(
                username, password);

        // Allow subclasses to set the "details" property
        setDetails(request, authRequest);

        return this.getAuthenticationManager().authenticate(authRequest);
    }
}
```


#### authenticate

Attempts to authenticate the passed Authentication object, returning a fully populated Authentication object (including granted authorities) if successful.
An AuthenticationManager must honour the following contract concerning exceptions:

- A DisabledException must be thrown if an account is disabled and the AuthenticationManager can test for this state.
- A LockedException must be thrown if an account is locked and the AuthenticationManager can test for account locking.
- A BadCredentialsException must be thrown if incorrect credentials are presented. Whilst the above exceptions are optional, an AuthenticationManager must always test credentials.

Exceptions should be tested for and if applicable thrown in the order expressed above (i.e. if an account is disabled or locked, the authentication request is immediately rejected and the credentials testing process is not performed). 
This prevents credentials being tested against disabled or locked accounts.

```java
public class ProviderManager implements AuthenticationManager, MessageSourceAware, InitializingBean {

    public Authentication authenticate(Authentication authentication)
            throws AuthenticationException {
        Class<? extends Authentication> toTest = authentication.getClass();
        AuthenticationException lastException = null;
        AuthenticationException parentException = null;
        Authentication result = null;
        Authentication parentResult = null;
        boolean debug = logger.isDebugEnabled();

        for (AuthenticationProvider provider : getProviders()) {
            if (!provider.supports(toTest)) {
                continue;
            }

            try {
                result = provider.authenticate(authentication);

                if (result != null) {
                    copyDetails(authentication, result);
                    break;
                }
            }
            catch (AccountStatusException | InternalAuthenticationServiceException e) {
                prepareException(e, authentication);
                // SEC-546: Avoid polling additional providers if auth failure is due to
                // invalid account status
                throw e;
            } catch (AuthenticationException e) {
                lastException = e;
            }
        }

        if (result == null && parent != null) {
            // Allow the parent to try.
            try {
                result = parentResult = parent.authenticate(authentication);
            }
            catch (ProviderNotFoundException e) {
                // ignore as we will throw below if no other exception occurred prior to
                // calling parent and the parent
                // may throw ProviderNotFound even though a provider in the child already
                // handled the request
            }
            catch (AuthenticationException e) {
                lastException = parentException = e;
            }
        }

        if (result != null) {
            if (eraseCredentialsAfterAuthentication
                    && (result instanceof CredentialsContainer)) {
                // Authentication is complete. Remove credentials and other secret data
                // from authentication
                ((CredentialsContainer) result).eraseCredentials();
            }

            // If the parent AuthenticationManager was attempted and successful then it will publish an AuthenticationSuccessEvent
            // This check prevents a duplicate AuthenticationSuccessEvent if the parent AuthenticationManager already published it
            if (parentResult == null) {
                eventPublisher.publishAuthenticationSuccess(result);
            }
            return result;
        }

        // Parent was null, or didn't authenticate (or throw an exception).

        if (lastException == null) {
            lastException = new ProviderNotFoundException(messages.getMessage(
                    "ProviderManager.providerNotFound",
                    new Object[] { toTest.getName() },
                    "No AuthenticationProvider found for {0}"));
        }

        // If the parent AuthenticationManager was attempted and failed then it will publish an AbstractAuthenticationFailureEvent
        // This check prevents a duplicate AbstractAuthenticationFailureEvent if the parent AuthenticationManager already published it
        if (parentException == null) {
            prepareException(lastException, authentication);
        }

        throw lastException;
    }
}
```




### Username/Password

UserDetailService

```java
public interface UserDetails extends Serializable {

	Collection<? extends GrantedAuthority> getAuthorities();

	String getPassword();

	String getUsername();

	boolean isAccountNonExpired();

	boolean isAccountNonLocked();

	boolean isCredentialsNonExpired();

	boolean isEnabled();
}
```

`DaoAuthenticationProvider` 内部委托 `UserDetailsService.loadUserByUsername()` 加载用户，再做密码比对；
应用接入点通常就是实现一个 `UserDetailsService` Bean（内存 / JDBC / LDAP 皆为预制实现）。

### PasswordEncoder

Spring Security 5 起默认使用 `DelegatingPasswordEncoder`：密码串带 `{bcrypt}` / `{argon2}` 等前缀，按前缀路由到具体编码器，并天然支持存量密码平滑升级（`upgradeEncoding`）。

```java
public interface PasswordEncoder {

	String encode(CharSequence rawPassword);

	boolean matches(CharSequence rawPassword, String encodedPassword);

	default boolean upgradeEncoding(String encodedPassword) {
		return false;
	}
}
```

| 实现要点 | 说明 |
| :-- | :-- |
| `BCryptPasswordEncoder` | 最常用默认选择，自带随机盐，成本因子可调（默认 10） |
| `DelegatingPasswordEncoder` | `PasswordEncoderFactories.createDelegatingPasswordEncoder()`，按 `{id}` 前缀分发 |
| `NoOpPasswordEncoder` | 明文，仅遗留兼容，已废弃 |

## Authorization

Spring Security provides interceptors which control access to secure objects such as method invocations or web requests. 
A pre-invocation decision on whether the invocation is allowed to proceed is made by the AccessDecisionManager.

### AccessDecisionManager (Legacy 5.x API)

```java
public interface AccessDecisionManager {

	void decide(Authentication authentication, Object object,
			Collection<ConfigAttribute> configAttributes) throws AccessDeniedException,
			InsufficientAuthenticationException;

	boolean supports(ConfigAttribute attribute);

	boolean supports(Class<?> clazz);
}
```


```java
public abstract class AbstractAccessDecisionManager implements AccessDecisionManager, InitializingBean, MessageSourceAware {

    private List<AccessDecisionVoter<?>> decisionVoters;

    protected MessageSourceAccessor messages = SpringSecurityMessageSource.getAccessor();
    
    public boolean supports(ConfigAttribute attribute) {
        for (AccessDecisionVoter voter : this.decisionVoters) {
            if (voter.supports(attribute)) {
                return true;
            }
        }

        return false;
    }
}
```


### SecurityInterceptor


The AbstractSecurityInterceptor will ensure the proper startup configuration of the security interceptor.
It will also implement the proper handling of secure object invocations, namely:

1. Obtain the Authentication object from the SecurityContextHolder.
2. Determine if the request relates to a secured or public invocation by looking up the secure object request against the SecurityMetadataSource.
3. For an invocation that is secured (there is a list of ConfigAttributes for the secure object invocation):
    1. If either the Authentication.isAuthenticated() returns false, or the alwaysReauthenticate is true, authenticate the request against the configured AuthenticationManager.
       When authenticated, replace the Authentication object on the SecurityContextHolder with the returned value.
    2. Authorize the request against the configured AccessDecisionManager.
    3. Perform any run-as replacement via the configured RunAsManager.
    4. Pass control back to the concrete subclass, which will actually proceed with executing the object.
       A InterceptorStatusToken is returned so that after the subclass has finished proceeding with execution of the object,
       its finally clause can ensure the AbstractSecurityInterceptor is re-called and tidies up correctly using finallyInvocation(InterceptorStatusToken).
    5. The concrete subclass will re-call the AbstractSecurityInterceptor via the afterInvocation(InterceptorStatusToken, Object) method.
    6. If the RunAsManager replaced the Authentication object, return the SecurityContextHolder to the object that existed after the call to AuthenticationManager.
    7. If an AfterInvocationManager is defined, invoke the invocation manager and allow it to replace the object due to be returned to the caller.
4. For an invocation that is public (there are no ConfigAttributes for the secure object invocation):
    1. As described above, the concrete subclass will be returned an InterceptorStatusToken which is subsequently re-presented to the AbstractSecurityInterceptor after the secure object has been executed.
       The AbstractSecurityInterceptor will take no further action when its afterInvocation(InterceptorStatusToken, Object) is called.
5. Control again returns to the concrete subclass, along with the Object that should be returned to the caller. The subclass will then return that result or exception to the original caller.

### AuthorizationManager (New 6.x API / Renamed authorize in 7.x)

Spring Security 6 用 `AuthorizationManager` 取代 `AccessDecisionManager` + `AccessDecisionVoter` 组合，投票语义收敛为一次判定调用（6.x 方法名为 `check`，**7.0 更名为 `authorize`**，`check` 已移除）：

```java
public interface AuthorizationManager<T> {

	// 6.x 为 check(...)，7.0 起为 authorize(...)
	AuthorizationDecision authorize(Supplier<Authentication> authentication, T object);

	default void verify(Supplier<Authentication> authentication, T object) {
		AuthorizationDecision decision = authorize(authentication, object);
		if (decision != null && !decision.isGranted()) {
			throw new AccessDeniedException("Access Denied");
		}
	}
}
```

- `RequestMatcherDelegatingAuthorizationManager`：请求级分发器，按 `RequestMatcher` 路由到具体 manager（`AuthorityAuthorizationManager`、`AuthenticatedAuthorizationManager` 等静态工厂取代了 Voter）。
- 末端拦截器从 `FilterSecurityInterceptor` 换成 `AuthorizationFilter`，由 `authorizeHttpRequests()` DSL 注册。
- 旧 `AccessDecisionManager` 仍可通过 `AuthorizationFilter` 适配挂载，但只建议存量过渡。

### Method Security

```java
@Configuration
@EnableMethodSecurity // 取代 @EnableGlobalMethodSecurity，prePostEnabled 默认开启
public class MethodSecurityConfig { }
```

```java
@PreAuthorize("hasRole('ADMIN') or #userId == authentication.name")
public User getUser(String userId) { ... }

@PostAuthorize("returnObject.owner == authentication.name")
public Order getOrder(Long orderId) { ... }

@PreFilter / @PostFilter  // 对集合参数/返回值逐元素过滤
```

实现基于 Spring AOP：`AuthorizationManagerBeforeMethodInterceptor` 等拦截器在方法调用前后执行对应的 `AuthorizationManager`。
注解可标注在接口上，支持元注解组合成自定义注解（如 `@AdminOnly`），与 `@Secured`、JSR-250 的 `@RolesAllowed` 并存。

## Configuration

### SecurityFilterChain（6.x）

```java
@Bean
SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
    http
        .authorizeHttpRequests(auth -> auth
            .requestMatchers("/public/**").permitAll()
            .requestMatchers("/admin/**").hasRole("ADMIN")
            .anyRequest().authenticated())
        .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .oauth2ResourceServer(rs -> rs.jwt(Customizer.withDefaults()));
    return http.build();
}
```

- 每个 `SecurityFilterChain` Bean 即一条链，多条链按 `securityMatcher` 顺序由 `FilterChainProxy` 匹配，命中即止。
- CSRF 默认开启；纯 API + Bearer Token 的无状态场景通常显式关闭。
- 前后端分离 + JWT 场景必配 `SessionCreationPolicy.STATELESS`，否则每请求仍会创建 HttpSession。
- 集群场景下的会话共享由 [Spring Session](/docs/CS/Framework/Spring/Session.md) 承接。

## OAuth

Spring Security supports protecting endpoints using two forms of OAuth 2.0 Bearer Tokens:
- JWT
- Opaque Tokens


### Authorization Grants

### Resource Server

Resource Server 侧核心抽象是 `JwtDecoder`（JWT）与 `OpaqueTokenIntegrator`（不透明令牌），
由 `BearerTokenAuthenticationFilter` 从 `Authorization: Bearer <token>` 头提取令牌并交给 `AuthenticationManager` 认证：

```java
@Bean
JwtDecoder jwtDecoder(@Value("${spring.security.oauth2.resourceserver.jwt.jwk-set-uri}") String jwkSetUri) {
    return NimbusJwtDecoder.withJwkSetUri(jwkSetUri).build();
}
```

- JWT：解码 + 验签（`NimbusJwtDecoder`，JWK Set 端点拉取公钥），`JwtAuthenticationConverter` 负责把 claim 映射成 `GrantedAuthority`。
- Opaque Token：每请求回调授权服务器的 introspection 端点校验，代价高但支持即时吊销。
- Client / Authorization Server 侧（登录态、令牌签发）见 [Spring OAuth](/docs/CS/Framework/Spring/OAuth.md)，协议本身见 [OAuth 2.0](/docs/CS/CN/HTTP/OAuth.md)。


## Init

```java
public abstract class AbstractSecurityWebApplicationInitializer implements WebApplicationInitializer {
    public final void onStartup(ServletContext servletContext) {
        beforeSpringSecurityFilterChain(servletContext);
        if (this.configurationClasses != null) {
            AnnotationConfigWebApplicationContext rootAppContext = new AnnotationConfigWebApplicationContext();
            rootAppContext.register(this.configurationClasses);
            servletContext.addListener(new ContextLoaderListener(rootAppContext));
        }
        if (enableHttpSessionEventPublisher()) {
            servletContext.addListener("org.springframework.security.web.session.HttpSessionEventPublisher");
        }
        servletContext.setSessionTrackingModes(getSessionTrackingModes());
        insertSpringSecurityFilterChain(servletContext);
        afterSpringSecurityFilterChain(servletContext);
    }
    
    private void insertSpringSecurityFilterChain(ServletContext servletContext) {
        String filterName = DEFAULT_FILTER_NAME;
        DelegatingFilterProxy springSecurityFilterChain = new DelegatingFilterProxy(
                filterName);
        String contextAttribute = getWebApplicationContextAttribute();
        if (contextAttribute != null) {
            springSecurityFilterChain.setContextAttribute(contextAttribute);
        }
        registerFilter(servletContext, true, filterName, springSecurityFilterChain);
    }
}
```


## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

## References

1. [Spring Security Architecture](https://docs.spring.io/spring-security/reference/servlet/architecture.html)
2. [Spring Security 6.0 Migration Guide](https://docs.spring.io/spring-security/reference/migration-7/index.html)
3. [Spring Security Source (GitHub)](https://github.com/spring-projects/spring-security)
