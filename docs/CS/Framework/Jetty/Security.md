## Introduction

Jetty 12 把整个安全模型从 Servlet（EE）层下放到了核心模块 `jetty-security`。这不是一次随手的搬移，而是编译期事实——看模块声明：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/module-info.java:14-27
module org.eclipse.jetty.security
{
    requires transitive org.eclipse.jetty.server;
    requires transitive org.eclipse.jetty.util;
    requires transitive org.slf4j;
    requires static java.security.jgss;
    requires static transitive java.sql;

    exports org.eclipse.jetty.security;
    exports org.eclipse.jetty.security.authentication;
    exports org.eclipse.jetty.security.jaas;

    uses org.eclipse.jetty.security.Authenticator.Factory;
}
```

依赖列表里**没有 `jakarta.servlet`**：`jetty-security` 只依赖 `jetty-server` 与 `jetty-util`，因此 Constraint、LoginService、Authenticator 这套体系对任何 Handler 树都可用——纯核心应用不需要 EE 层就能做认证授权。`java.security.jgss` 是 `static` 依赖（只有 SPNEGO 用到才加载），`java.sql` 同理（JDBCLoginService）。这与 [EeLayer](/docs/CS/Framework/Jetty/EeLayer.md) 的「核心与 EE 严格分层」是同一件事在安全维度的投影。

但它又刻意保留了对 Servlet 语义的**表达能力**。`Constraint` 的 javadoc 说得很直白：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/Constraint.java:29-32
 * The core constraint is not the same as the servlet specification {@code AuthConstraint}, but it is
 * sufficiently capable to represent servlet constraints.
```

核心 `Constraint` 与 Servlet 的 `auth-constraint` **不是一回事**（前者是「授权语义枚举 + 角色集 + 传输约束」的三元组，后者只是一份角色名单），但前者足以表达后者。EE 层做的只是翻译。这与 [Tomcat Security](/docs/CS/Framework/Tomcat/Security.md) 形成鲜明对照——Tomcat 的安全模型从部署期就是 Servlet 形状的：`web.xml` 直接解析成 `SecurityConstraint` 数组挂在 `Context` 上，认证由 `AuthenticatorBase` Valve 驱动，凭据换 `Principal` 的活交给 `Realm`，三者全部住在 catalina 内核里、按 Servlet 规范的角色组织。两家把安全放的位置不同，切分职责的方式也不同：

| 关注点 | Jetty 12.1（core） | Tomcat（catalina） |
| :--- | :--- | :--- |
| 授权模型 | `Constraint`（Authorization 枚举 + roles + Transport，`combine` 组合代数） | `SecurityConstraint` / `SecurityCollection`（web.xml 描述符形状） |
| 凭据校验 | `LoginService`（只管「用户名 + 凭据 → UserIdentity」） | `Realm`（`authenticate(...)` 六个重载 + `hasResourcePermission` 等授权判定一体） |
| 认证机制 | `Authenticator`（SPI，`Factory` 发现） | `AuthenticatorBase` Valve（按 `auth-method` 装配） |
| 身份与线程 | `IdentityService.associate(...)` 返回 `AutoCloseable` | `Realm` 产出的 `GenericPrincipal` 挂在请求上 |
| 容器挂接点 | `SecurityHandler` 是一个普通 `Handler.Wrapper` | Valve 管道（`StandardContext` 一段） |

一句话概括：**Jetty 把「约束怎么表达、凭据怎么校验、身份怎么绑定线程」拆成三个独立接口，Tomcat 把授权判定留在 Realm 里**。这也决定了 Jetty 里 401/403 的分工与 Tomcat 不同：Tomcat 是「401 由 Authenticator 决定，403 由 Realm 决定」，而 Jetty 里 403 有两个来源——约束本身的 `FORBIDDEN`（`SecurityHandler.java:491-495`）与认证成功但授权不过（`SecurityHandler.java:529-533`）。

本篇源码基线 12.1.14，行号均相对 `/tmp/src/tree/jetty-security-12.1.14/`（ee10 适配层相对 `/tmp/src/tree/jetty-ee10-servlet-12.1.14/`）下的对应文件，如记作 `SecurityHandler.java:489`。请求从 Connector 进来后走到 Handler 树的位置见 [RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)，`SecurityHandler` 正是插在业务 Handler 外面的一层 Wrapper。

## The constraint model

### Authorization and Transport

`Constraint` 是接口（`Constraint.java:34`），由三个维度组成：`Authorization`（认证与授权语义）、`Transport`（传输要求）、`roles`（仅 `SPECIFIC_ROLE` 时非空）。`Authorization` 六个枚举各有明确的 Servlet 对照物：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/Constraint.java:39-72
    enum Authorization
    {
        /**
         * Access not allowed. Equivalent to Servlet AuthConstraint with no roles.
         */
        FORBIDDEN,
        /**
         * Access allowed. Equivalent to Servlet AuthConstraint without any Authorization.
         */
        ALLOWED,
        /**
         * Access allowed for any authenticated user regardless of role. Equivalent to Servlet role "**".
         * ...
         */
        ANY_USER,
        /**
         * Access allowed for authenticated user with any known role. Equivalent to Servlet role "*".
         * ...
         */
        KNOWN_ROLE,
        /**
         * Access allowed only for authenticated user with specific role(s).
         */
        SPECIFIC_ROLE,
        /**
         * Inherit the authorization from a less specific constraint when passed to {@link #combine(Constraint, Constraint)},
         * otherwise act as {@link #ALLOWED}.
         */
        INHERIT;
    }
```

注意 `ANY_USER`（Servlet 的 `"**"`）与 `KNOWN_ROLE`（Servlet 的 `"*"`）的区别：前者不看角色表，只要认证过就行；后者要求用户持有**应用声明过的**角色之一——`LoginService` 里存在的角色不算数。`Transport` 只有三个值：`SECURE`（必须 TLS）、`ANY`、`INHERIT`（`Constraint.java:77-92`）。接口另提供六个预置常量：`ALLOWED`、`FORBIDDEN`、`ANY_USER`、`KNOWN_ROLE`、`SECURE_TRANSPORT`、`ANY_TRANSPORT`（`Constraint.java:195-220`），其中 `SECURE_TRANSPORT` 是「只管传输、授权继承」的单维约束——这个设计正是给 `combine` 当材料用的。

还有一个构建期不变式值得记住：带角色的约束必须是 `SPECIFIC_ROLE`，否则 `from(...)` 直接抛 `IllegalStateException`（`Constraint.java:322-325`）；`authorization` 为 null 时按「有角色 → `SPECIFIC_ROLE`，无角色 → `INHERIT`」推断（`Constraint.java:319-321`）。

### The combine algebra

`combine` 是这套模型的组合代数，语义是「最具体者胜，未指定者继承」：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/Constraint.java:274-286
    static Constraint combine(String name, Constraint leastSpecific, Constraint mostSpecific)
    {
        if (leastSpecific == null)
            return mostSpecific == null ? ALLOWED : mostSpecific;
        if (mostSpecific == null)
            return leastSpecific;

        return from(
            name,
            mostSpecific.getTransport() == Transport.INHERIT ? leastSpecific.getTransport() : mostSpecific.getTransport(),
            mostSpecific.getAuthorization() == Authorization.INHERIT ? leastSpecific.getAuthorization() : mostSpecific.getAuthorization(),
            mostSpecific.getAuthorization() == Authorization.INHERIT ? leastSpecific.getRoles() : mostSpecific.getRoles());
    }
```

javadoc 里的例子讲清了它的用途——`/*` 提供兜底传输约束，更具体的路径只写授权、继承传输：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/Constraint.java:258-266
     *     /*         -> Authorization.FORBIDDEN,roles=[],Transport.SECURE
     *     /admin/*   -> Authorization.SPECIFIC_ROLE,roles=["admin"],Transport.INHERIT
     *
     * The the {@code /admin/*} constraint would be consider most specific and a request to {@code /admin/file} would
     * have {@link Authorization#SPECIFIC_ROLE} from the {@code /admin/*} constraint and
     * {@link Transport#SECURE} inherited from the {@code /*} constraint.
```

javadoc 同时警告：`Note that this combination is not equivalent to the combination done by the EE servlet specification.`（`Constraint.java:268`）。这句话是理解 ee10 适配层的关键，后文「The Jakarta EE 10 adapter」展开。

## SecurityHandler and constraint matching

`SecurityHandler` 是抽象 Handler，同时实现 `Authenticator.Configuration`：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/SecurityHandler.java:68
public abstract class SecurityHandler extends Handler.Wrapper implements Configuration
```

它把「匹配约束 → 传输检查 → 认证 → 授权 → 绑定身份」整条链压进一个 `handle` 方法（`SecurityHandler.java:473-563`）。前半段：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/SecurityHandler.java:483-511
        String pathInContext = Request.getPathInContext(request);
        Constraint constraint = getConstraint(pathInContext, request);
        ...
        if (constraint == null)
            constraint = Constraint.ALLOWED;

        if (constraint.getAuthorization() == Authorization.FORBIDDEN)
        {
            doWriteError(request, response, callback, HttpStatus.FORBIDDEN_403);
            return true;
        }

        // Check data constraints
        if (Transport.SECURE.equals(constraint.getTransport()) && !request.isSecure())
        {
            redirectToSecure(request, response, callback);
            return true;
        }
```

三个要点：

1. **未命中即 `ALLOWED` 兜底**（`SecurityHandler.java:488-489`）。`getConstraint` 是抽象方法（`:650`），由子类决定匹配策略，但无论哪个子类，没配约束的路径就是不设防的。
2. `FORBIDDEN` 直接 403，连认证都不做——它是「这条路永远不走」的语义，不是「先登录再告诉你没权限」。
3. `Transport.SECURE` 不满足时走 `redirectToSecure`（`:652-670`）：读 `HttpConfiguration` 的 `secureScheme`/`securePort` 发 302；`securePort <= 0` 则退化为 403 `!Secure`。这里与 [Connector](/docs/CS/Framework/Jetty/Connector.md) 的 TLS 配置直接联动。

后半段先让 Authenticator 有机会改写授权语义（`FormAuthenticator` 靠这个钩子放行 `/j_security_check`，`Authenticator.java:85-88` 是默认实现），再执行认证与授权：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/SecurityHandler.java:515-556
            AuthenticationState authenticationState = mustValidate ? _authenticator.validateRequest(request, response, callback) : null;
            ...
            else if (mustValidate && !isAuthorized(constraint, authenticationState))
            {
                ...
                return doWriteError(request, response, callback, HttpStatus.FORBIDDEN_403);
            }
            ...
            AuthenticationState.setAuthenticationState(request, authenticationState);
            IdentityService.Association association =
                (authenticationState instanceof AuthenticationState.Succeeded user)
                ? _identityService.associate(user.getUserIdentity(), null) : null;

            try
            {
                //process the request by other handlers
                return next.handle(_authenticator.prepareRequest(request, authenticationState), response, callback);
            }
            finally
            {
                ...
                if (association != null)
                    association.close();
            }
```

授权判定是一个干净的 switch（`SecurityHandler.java:672-697`）：`FORBIDDEN/ALLOWED/INHERIT` 恒真，`ANY_USER` 只查 `UserPrincipal != null`，`KNOWN_ROLE` 遍历 handler 的 known roles，`SPECIFIC_ROLE` 遍历约束自带的角色集。

### PathMapped and PathMethodMapped

两个具体子类都在 `SecurityHandler` 内部。`PathMapped`（`SecurityHandler.java:798`）的 javadoc 示例是嵌入式用法的标准范式，值得整段摘录：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/SecurityHandler.java:768-776
     * SecurityHandler.PathMapped handler = new SecurityHandler.PathMapped();
     * handler.put("/*", Constraint.combine(Constraint.FORBIDDEN, Constraint.SECURE_TRANSPORT));
     * handler.put("", Constraint.ALLOWED);
     * handler.put("/login", Constraint.ALLOWED);
     * handler.put("*.png", Constraint.ANY_TRANSPORT);
     * handler.put("/admin/*", Constraint.from("admin", "operator"));
     * handler.put("/admin/super/*", Constraint.from("operator"));
     * handler.put("/user/*", Constraint.ANY_USER);
     * handler.put("*.xml", Constraint.FORBIDDEN);
```

匹配到多条时按「最不具体 → 最具体」排序后逐个 `combine`：优先级 `EXACT > ROOT > SUFFIX_GLOB > MIDDLE_GLOB > PREFIX_GLOB > DEFAULT`，同组内按 pattern 长度（`SecurityHandler.java:728-739`、`:785-794` 的四个示例）。所以 `/admin/config.xml` 会同时命中 `/*`（FORBIDDEN + SECURE）与 `*.xml`（FORBIDDEN），结果仍是 FORBIDDEN——具体的 `FORBIDDEN` 不被 `ALLOWED` 类约束稀释，这是 `combine` 语义的自然结果（注意这与 Servlet 13.8.1 的合并规则不同，见后文）。

`PathMethodMapped`（`SecurityHandler.java:963`）在路径之上再加 HTTP 方法一维，`*` 表示全部方法，且**全方法约束总是与具体方法约束合并**——javadoc 明说这是为了「用 `/*` + `*` 建立诸如 `SECURE_TRANSPORT` 的默认值」（`SecurityHandler.java:1053-1058`）。它的 `getConstraint` 无匹配时同样返回 `Constraint.ALLOWED`（`:1040`），且 javadoc 用了两段重复「If there is no match ... then the constraint is assumed to be ALLOWED」强调路径与方法两个维度都可能漏配（`:957-959`）。

### The default-allow footgun

Jetty 核心的默认值是**放行**：`combine(null, null)` 返回 `ALLOWED`（`Constraint.java:276-277`），`PathMapped`/`PathMethodMapped` 未命中也返回 `ALLOWED`。Servlet 规范对「未被任何约束覆盖的 HTTP 方法」的默认语义同样是放行（uncovered methods），Tomcat 与 Jetty ee10 都遵循它，翻转开关是规范定义的 `deny-uncovered-http-methods`——Jetty 侧对应 `ConstraintSecurityHandler.setDenyUncoveredHttpMethods`（ee10 `ConstraintSecurityHandler.java:112-113`：未覆盖且开关打开时直接给出 `Constraint.FORBIDDEN`）。所以这条安全线两家一致：**漏配不报错，只静默放行**，Tomcat 侧的部署期检查见 [Tomcat Security](/docs/CS/Framework/Tomcat/Security.md)。`PathMapped` 的 javadoc 因此给出实践守则：`It is therefore good practice to always explicitly configure a constraint for path /* or /.`（`SecurityHandler.java:796`）。

## The authentication execution chain

### Authenticator SPI

`Authenticator`（`Authenticator.java:34`）定义认证机制本身。核心包预置的机制名一排常量：`BASIC`、`FORM`、`DIGEST`、`CLIENT_CERT`、`SPNEGO`、`NEGOTIATE`、`OPENID`、`SIWE`、`MULTI`（`Authenticator.java:36-45`）。核心方法只有两个有实质语义：`validateRequest`（`Authenticator.java:107`，返回 `AuthenticationState`）与 `prepareRequest`（`:69`，认证后恢复原始请求形态，如 Form 登录后重放 POST 参数）。发现机制是标准 `ServiceLoader`：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/Authenticator.java:226-229
    interface Factory
    {
        Authenticator getAuthenticator(Server server, Context context, Configuration configuration);
    }
```

`module-info.java:26` 的 `uses org.eclipse.jetty.security.Authenticator.Factory` 声明对应 `SecurityHandler` 静态块里的装载逻辑（`SecurityHandler.java:88-93`）：ServiceLoader 找到的 Factory 全部登记，末尾再兜底加一个 `DefaultAuthenticatorFactory`。启动时（`SecurityHandler.java:355-391`）若没显式 `setAuthenticator`，就逐个问 Factory；全都不认就退化为 `Authenticator.NoOp`（`Authenticator.java:231-249`）——一个 `validateRequest` 恒返回 null 的桩，等价于「不做认证」。若 `LoginAuthenticator` 被选中，`doStart` 还会装配一个 `AuthenticationState.Deferred`（`SecurityHandler.java:401-405`），这是 `request.login(...)` 程序化登录的运行期载体。

`LoginService` 与 `IdentityService` 的解析在 `doStart` 里有一段「complicated resolution」（`SecurityHandler.java:314-351`）：优先用显式注入；否则从 `Server` 的 bean 列表里按 realm 名匹配（`:287-307`）；`IdentityService` 最后兜底 `new DefaultIdentityService()`，且两者不一致直接抛 `IllegalStateException`——约束很硬：**一个 `SecurityHandler` 只能有一个一致的 `LoginService`/`IdentityService` 组合**。

### AuthenticationState on the request

`AuthenticationState`（`AuthenticationState.java:37`）是运行期挂在请求上的认证状态，四个子类型覆盖完整状态机：`Succeeded`（`:218`，带 `UserIdentity`）、`Deferred`（`:342`，延后认证）、`ResponseSent`（`:261`，challenge 已发出，含 `CHALLENGE`/`SEND_FAILURE`/`SEND_SUCCESS` 三个预置实例）、`ServeAs`（`:311`，换 URI 重发请求）。挂载点就是 `Request.setAuthenticationState`（`AuthenticationState.java:74-77`）。业务代码的静态入口是一组工具方法：

- `AuthenticationState.authenticate(Request)`：无 challenge 地解析 Deferred 后取 `Succeeded`（`AuthenticationState.java:105-119`）；
- `AuthenticationState.authenticate(Request, Response, Callback)`：允许发 challenge，失败直接 403（`:133-151`）；
- `AuthenticationState.login(username, password, Request, Response)`：程序化登录，要求当前是 `Deferred`（`:160-180`）；
- `AuthenticationState.logout(Request, Response)`（`:182-200`）。

### Session restore

Form 等交互式认证的完整往返如下：

```sequence
Title: Form authentication round trip
Browser->SecurityHandler: GET /secure
SecurityHandler->Authenticator: validateRequest
Authenticator->Browser: 302 to login page
Note right of Authenticator: ResponseSent, handler returns
Browser->SecurityHandler: POST /j_security_check
SecurityHandler->LoginService: login(username, credentials)
LoginService->IdentityService: newUserIdentity(subject, principal, roles)
Authenticator->SessionAuthentication: stash into session
SecurityHandler->Browser: redirect to original URI
Browser->SecurityHandler: GET /secure + session cookie
SecurityHandler->Authenticator: session attribute restores Succeeded
SecurityHandler->Browser: 200, identity associated with thread
```

登录成功后跨请求恢复的载体是 `SessionAuthentication`——注意它同时是 `Serializable` 和 `Session.ValueListener`：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/authentication/SessionAuthentication.java:40-48
public class SessionAuthentication extends LoginAuthenticator.UserAuthenticationSucceeded
    implements Serializable, Session.ValueListener
{
    ...
    public static final String AUTHENTICATED_ATTRIBUTE = "org.eclipse.jetty.security.UserIdentity";
```

反序列化路径有两条（`SessionAuthentication.java:105-143`）：若配置了 `persistAuthenticationCredentials`，则拿着存下来的凭据**重新走一遍 `loginService.login(...)`**；否则用序列化保留的用户名与角色数组经 `IdentityService.newUserIdentity` 重建身份，不再触库。恢复失败不抛异常——`readResolve` 把没有 `UserIdentity` 的实例降级为 null（`SessionAuthentication.java:147-158`），javadoc 明说这是为了避免 500 响应。配套的会话防护：认证成功时会话默认重建（`_renewSessionOnAuthentication = true`，`SecurityHandler.java:83`、`:439-450`），防 session fixation。

## LoginService family and user stores

`LoginService` 的职责窄到只剩一件事（`LoginService.java:23-29` 的 javadoc：「check credentials and to create a UserIdentity」）：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/LoginService.java:30-46
public interface LoginService
{
    ...
    UserIdentity login(String username, Object credentials, Request request, Function<Boolean, Session> getOrCreateSession);
```

注意 `login` 带 `Request` 与 `getOrCreateSession` 函数——这是为 OpenID/OAuth 这类需要请求上下文与会话的机制准备的；传统用户名口令机制直接忽略。`validate(UserIdentity)` 用于检查此前签发的身份是否仍有效（撤销场景）。家族实现各管一种凭据来源：`AbstractLoginService` 是公共骨架（UserStore + Credential 校验 + 角色装配）；`HashLoginService` 背靠属性文件 UserStore，是最常用的嵌入式实现；`JDBCLoginService` 走数据库（`module-info.java:20` 的 `requires static transitive java.sql` 为它而设）；`jaas/JAASLoginService` 委托 LoginModule；`SPNEGOLoginService` 对应 Kerberos SSO（`java.security.jgss` 的 static 依赖，`module-info.java:19`）；`AnyUserLoginService` 与 `EmptyLoginService` 是两个极端桩——前者给任何用户签发身份（配合已在外部完成认证的场景），后者永不通过。

用户库本体是 `UserStore`（`UserStore.java:31-33`）：一个 `ConcurrentHashMap`，键是用户名，值是 `UserPrincipal`（含 `Credential`）加一组 `RolePrincipal`。属性文件形态由 `PropertyUserStore` 监视，文件格式：

```java
// 相对 /tmp/src/tree/jetty-security-12.1.14/org/eclipse/jetty/security/PropertyUserStore.java:39-48
 *  username: password [,rolename ...]
 *
 * <p>Passwords may be clear text, obfuscated or checksummed.
 * The class {@link org.eclipse.jetty.util.security.Password} should be used
 * to generate obfuscated passwords or password checksums.</p>
 *
 * <p>If DIGEST Authentication is used, the password must be in a recoverable
 * format, either plain text or obfuscated.</p>
```

**支持热加载**：`PropertyUserStore implements Scanner.DiscreteListener`（`PropertyUserStore.java:50`），用 `setReloadInterval(int scanSeconds)` 配置扫描周期（`PropertyUserStore.java:120-127`），0 表示关闭；旧的 `setHotReload(boolean)` 尚在但已 `@Deprecated`（`:110-113`，等价于 1 秒间隔）。重载时按「本次出现的用户集合」做差量，删掉消失的用户（`PropertyUserStore.java:193-200` 起）。最后一行警告值得重复一次：**Digest 认证要求口令可还原**（明文或 obfuscated），checksum 形态只能配 BASIC/FORM。

## The Jakarta EE 10 adapter

ee10 层的 `ConstraintSecurityHandler`（相对 `/tmp/src/tree/jetty-ee10-servlet-12.1.14/org/eclipse/jetty/ee10/servlet/security/ConstraintSecurityHandler.java:61`）直接继承核心 `SecurityHandler`（不是 `PathMapped`），自己维护 `PathMappings<Map<String, Constraint>>`，在部署期就**预计算**好所有约束组合（javadoc：`servlet spec 3.1 compliant and pre-computes the constraint combinations for runtime efficiency`，`:57-59`）。

web.xml 的翻译链路是：`<security-constraint>`（`web-resource-collection` + `auth-constraint` + `user-data-constraint`）→ `ConstraintMapping`（pathSpec + method + methodOmissions）→ `addConstraintMapping`（`:362-383`，顺带把约束里出现的角色名登记为 known roles）→ `rebuildMappings`（`:385-394`）逐条 `processConstraintMapping` 灌进预计算表。`createConstraint` 展示了 Servlet 元素到核心 `Authorization` 的完整映射（`ConstraintSecurityHandler.java:140-174`）：无角色 + `EmptyRoleSemantic.DENY` → `FORBIDDEN`（等价于「`<auth-constraint>` 存在但为空」），无角色 + PERMIT → `ALLOWED`，有角色 → `SPECIFIC_ROLE`；`TransportGuarantee.CONFIDENTIAL` → `Transport.SECURE`。`@ServletSecurity` 注解走同一条路（`createConstraintsWithMappingsForPath`，`:211-260`）。

真正的看点在合并规则。核心 `combine` 是「最具体者胜」的继承代数，而 Servlet 规范 13.8.1 是另一套——Jetty 的注释毫不掩饰：

```java
// 相对 /tmp/src/tree/jetty-ee10-servlet-12.1.14/org/eclipse/jetty/ee10/servlet/security/ConstraintSecurityHandler.java:441-452
    protected Constraint combineServletConstraints(Constraint constraintA, Constraint constraintB)
    {
        // This method is not identical to Constraint.combine.
        // Instead, it implements the bizarre Jakarta Servlet Spec section 13.8.1: "Combining Constraints"
        // https://jakarta.ee/specifications/servlet/6.1/jakarta-servlet-spec-6.1#combining-constraints

        if (constraintA == null)
            return constraintB == null ? Constraint.ALLOWED_ANY_TRANSPORT : constraintB;
        if (constraintB == null)
            return constraintA;

        // Don't blame me for the following code. Blame Servlet specification
```

规范规则的要点（`ConstraintSecurityHandler.java:461-493`）：`FORBIDDEN` 压倒一切；无授权（`ALLOWED`）压倒一切角色约束（但压不过 `FORBIDDEN`）；`"**"`（`ANY_USER`）压倒除 `FORBIDDEN`/`ALLOWED` 之外的一切；`"*"`（`KNOWN_ROLE`）只压倒 `SPECIFIC_ROLE`；两个 `SPECIFIC_ROLE` 合并时角色取**并集**；Transport 则要求两边都是 `SECURE` 才保持 `SECURE`（取交集）。对比核心 `combine` 的「最具体者整体胜出、未指定者继承」，两者结果经常不同——这就是 `Constraint.java:268` 那句 "not equivalent" 的实体。使用者要分清：写核心应用时你享受的是可预测的继承代数；一旦套上 Servlet 语义（web.xml、注解），合并就换成规范的怪异规则。

未覆盖 HTTP 方法的处理也在这一层收口：`getConstraint` 找不到方法级约束且 `isDenyUncoveredHttpMethods()` 为真时返回 `Constraint.FORBIDDEN`（`:112-113`）；`rebuildMappings` 末尾会 `checkPathsWithUncoveredHttpMethods` 打印所有存在覆盖缺口的路径（`:385-394`）——部署期就该盯着这条 WARN 日志。

## An embedded minimal example

把上面所有角色串起来，一个不依赖任何 EE 模块的最小安全应用：

```java
import org.eclipse.jetty.security.Constraint;
import org.eclipse.jetty.security.HashLoginService;
import org.eclipse.jetty.security.SecurityHandler;
import org.eclipse.jetty.security.authentication.BasicAuthenticator;
import org.eclipse.jetty.server.Server;
import org.eclipse.jetty.server.handler.Handler.HandlerSimple;

public static void main(String[] args) throws Exception
{
    SecurityHandler.PathMapped security = new SecurityHandler.PathMapped();
    security.put("/*", Constraint.combine(Constraint.FORBIDDEN, Constraint.SECURE_TRANSPORT));
    security.put("/health", Constraint.ALLOWED);
    security.put("/api/*", Constraint.from("admin", "operator"));
    security.setAuthenticator(new BasicAuthenticator());
    security.setRealmName("test-realm");
    security.setLoginService(new HashLoginService("test-realm", "etc/realm.properties"));
    security.setHandler(new HandlerSimple(response ->
        response.write(true, null, java.nio.charset.StandardCharsets.UTF_8.encode("ok"))));

    Server server = new Server(8080);
    server.setHandler(security);
    server.start();
}
```

读法：`/*` 兜底「全禁 + 必须 TLS」，`/health` 显式放行，`/api/*` 要求具体角色——注意每条约束的授权都是显式的，没有一条依赖 `ALLOWED` 兜底。`etc/realm.properties` 内容一行一个用户：`admin:SECRET,admin`，口令可用 `org.eclipse.jetty.util.security.Password` 生成 obfuscated 形态。

## Common pitfalls

- **默认 ALLOWED 的安全影响**：未命中约束的路径与方法都静默放行（`SecurityHandler.java:488-489`、`PathMethodMapped` 的 `:1040` 与 `:957-959`）。新增接口而不补约束，等于直接上线未授权访问。守则只有一条：永远显式配置 `/*` 或 `/` 的兜底约束（`SecurityHandler.java:796`），把「放行」写成显式条目而不是默认值。
- **两套合并代数不可混用**：核心 `Constraint.combine` 按「最具体者胜」继承；ee10 `combineServletConstraints` 按规范 13.8.1 合并（`FORBIDDEN` 优先、角色并集、Transport 交集）。同一份路径表在两种规则下结果可能相反，调试授权问题时先确认自己站在哪一层。
- **SessionAuthentication 与会话复制**：认证状态随 session 序列化传播（`SessionAuthentication.java:40-41`），角色数组始终携带，凭据只在 `persistAuthenticationCredentials` 打开时才写入流（`:161-168`）；反序列化后要么重登录要么按角色重建（`:105-143`）。集群部署时注意两点：`UserStore` 里撤销用户不会使已复制的 session 失效（除非依赖 `LoginService.validate`），且无法恢复的身份会被 `readResolve` 静默降级为匿名——表现为偶发的「登录状态丢失」而非报错。
- **IdentityService 与线程池**：`IdentityService.associate` 把 `UserIdentity` 绑定到当前线程，返回 `AutoCloseable` 的 `Association`（`IdentityService.java:32-33`、`:66-70`）；`SecurityHandler` 在 `finally` 里关闭它（`SecurityHandler.java:550-555`）。线程被 [Threading](/docs/CS/Framework/Jetty/Threading.md) 描述的池化模型反复复用，身份绑定必须是严格作用域的——自己写代码时若手动 `associate`，忘记 `close()` 会把身份泄漏给同一线程的下一个请求。
- **`NoOp` 不是「无安全」而是「无认证」**：没有 Authenticator 时启动不报错，退化为 `Authenticator.NoOp`（`SecurityHandler.java:390-391`）——约束匹配与 `FORBIDDEN`/`Transport` 检查照常执行，只有认证环节消失。想要「认证了但没配 LoginService」这类配置错误尽早爆炸，得靠显式装配而非默认路径。

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [EeLayer](/docs/CS/Framework/Jetty/EeLayer.md)
- [RequestFlow](/docs/CS/Framework/Jetty/RequestFlow.md)
- [Threading](/docs/CS/Framework/Jetty/Threading.md)
- [Tomcat Security](/docs/CS/Framework/Tomcat/Security.md)
- [Servlet](/docs/CS/Java/JDK/Servlet.md)

## References

- [Eclipse Jetty 12 Programming Guide](https://jetty.org/docs/jetty/12/programming-guide/index.html)
- [Jakarta Servlet 6.1 Specification, 13.8.1 Combining Constraints](https://jakarta.ee/specifications/servlet/6.1/jakarta-servlet-spec-6.1#combining-constraints)
- [Jakarta Servlet 6.1 Specification, 13.8.4 Uncovered HTTP Protocol Methods](https://jakarta.ee/specifications/servlet/6.1/jakarta-servlet-spec-6.1#handling-uncovered-http-methods)
