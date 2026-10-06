## Introduction

Tomcat 的容器级认证授权由三层拼成：部署期把 `web.xml` 与注解中的安全约束解析成 `SecurityConstraint` 数组挂在 `Context` 上；运行期由 `AuthenticatorBase` 这个 Valve 逐请求判断「要不要认证、认证方式是什么、角色够不够」；把凭据换成 `Principal` 的活交给 `Realm`。跨 Context 的单点登录由 `SingleSignOn` Valve 维护一张以 cookie 值为键的会话表。

版本基线 **Tomcat 11.0.26**。下文路径缩写：

| 缩写 | 实际目录 |
| :--- | :--- |
| `CAT` | `tomcat-catalina-11.0.26/org/apache/catalina` |
| `COY` | `tomcat-coyote-11.0.26/org/apache/tomcat` |

11 里两处让旧资料失效的改动：SecurityManager 彻底移除（`CAT/realm`、`CAT/authenticator`、`CAT/core` 全树 grep 不到 `AccessController` / `doPrivileged` 调用，只剩两处历史注释），以及 `AuthenticatorBase` 把 JASPIC 前置、SSO 再认证模式、CORS 预检放行提升成了一等公民。

## Parsing security constraints

解析入口在 `ContextConfig`，它监听 Context 的生命周期事件（`CAT/startup/ContextConfig.java:288`），`CONFIGURE_START_EVENT` 触发 `configureStart()`（`:300`、`:1034`），顺序是：先 `webConfig()`（`:1288`）把 globalWebXml、conf/web.xml、`WEB-INF/web.xml`、碎片与注解解析成同一个 `WebXml` 对象，再由 `configureContext(WebXml)`（`:1464`）写进 `Context`。

安全模型类在 11 里位于 `org.apache.tomcat.util.descriptor.web` 包（`CAT/startup/ContextConfig.java:105-106` 的 import 可证），`SecurityConstraint` / `SecurityCollection` / `SecurityRole` / `SecurityRoleRef` / `LoginConfig` 都是这一族，不再从 `org.apache.catalina.deploy` 取。

```java
boolean allAuthenticatedUsersIsAppRole =
        webxml.getSecurityRoles().contains(SecurityConstraint.ROLE_ALL_AUTHENTICATED_USERS);
for (SecurityConstraint constraint : webxml.getSecurityConstraints()) {
    if (allAuthenticatedUsersIsAppRole) {
        constraint.treatAllAuthenticatedUsersAsApplicationRole();
    }
    context.addConstraint(constraint);
}
```

`CAT/startup/ContextConfig.java:1531-1539`。`**`（`ROLE_ALL_AUTHENTICATED_USERS`）在应用自己声明了同名角色时会被降级成普通角色名，这是 `treatAllAuthenticatedUsersAsApplicationRole()` 存在的原因。

注解路径独立于 web.xml：`applicationAnnotationsConfig()`（`:322`，由 `configureStart()` 在 `:1049` 调用）→ `WebAnnotationSet.loadApplicationAnnotations()`（`CAT/startup/WebAnnotationSet.java:72`）→ `@ServletSecurity` 转成 `ServletSecurityElement` 后交给 `context.addServletSecurity(...)`（`:157-160`）。`CAT/core/StandardContext.java:5071` 里的实现按 URL pattern 逐个比对：只要该 pattern 上已有 `isFromDescriptor()` 为真的集合就判定冲突并跳过（同一 pattern 不允许描述符与注解混用），否则先删掉注解来源的旧 pattern 再装换后的新约束（`SecurityConstraint.createConstraints`，`CAT/core/StandardContext.java:5125-5129`）。`@DeclareRoles` 与 `@RunAs` 分别落在 `WebAnnotationSet.java:191-194` 与 `:151-153`。

约束解析完，`validateSecurityConstraints()` 那一段（`CAT/startup/ContextConfig.java:1234-1262`）会把约束里引用到、但 `<security-role>` 没声明的角色名补成 Context 角色，`run-as` 与 `security-role-ref` 的 link 目标同样纳入检查。

最后 `authenticatorConfig()`（`CAT/startup/ContextConfig.java:338`）按 `login-config` 的 `auth-method` 自动装 Valve：映射表是 `CAT/startup/Authenticators.properties`（`:157` 加载），没有 Realm 直接报 `contextConfig.missingRealm` 并让部署失败（`:355-359`）。

| auth-method | Authenticator 实现 |
| :--- | :--- |
| BASIC | `org.apache.catalina.authenticator.BasicAuthenticator` |
| CLIENT-CERT | `org.apache.catalina.authenticator.SSLAuthenticator` |
| DIGEST | `org.apache.catalina.authenticator.DigestAuthenticator` |
| FORM | `org.apache.catalina.authenticator.FormAuthenticator` |
| NONE | `org.apache.catalina.authenticator.NonLoginAuthenticator` |
| SPNEGO | `org.apache.catalina.authenticator.SpnegoAuthenticator` |

注意 11 已无 `JAASAuthenticator`，JAAS 只剩 `JAASRealm` 一侧。没有 `<login-config>` 时 `ContextConfig` 会塞一个 `DUMMY_LOGIN_CONFIG`（auth-method 为 `NONE`，`CAT/startup/ContextConfig.java:144`、`:340-343`），目的是让 `HttpServletRequest.login()` 在无认证配置的上下文里也可用。

## Realm contract

`CAT/Realm.java` 把职责切成两组：认证 `authenticate(...)` 六个重载（`:69` 用户名、`:80` 用户名加口令、`:100` Digest、`:112` GSSContext、`:123` GSSName、`:134` X509 证书链）与授权 `findSecurityConstraints()`（`:152`）、`hasResourcePermission()`（`:167`）、`hasUserDataPermission()`（`:196`），再加口令散列入口 `getCredentialHandler()`（`:43`）。

Authenticator 只负责「按 auth-method 把客户端凭据取出来」，取出来之后调哪个 `authenticate` 重载由凭据形态决定；反过来 `RealmBase` 完全不懂 HTTP 握手。这条边界是排查「为什么 401 变 403」的前提。

`RealmBase.findSecurityConstraints()`（`CAT/realm/RealmBase.java:545`）按四轮匹配挑出适用约束，先命中先返回：

| 轮次 | 模式形态 | 位置 | 要点 |
| :--- | :--- | :--- | :--- |
| 1 | 精确路径 | `:588-633` | 空 pattern 特判为 Context 根 |
| 2 | `/xxx/*` 前缀 | `:640-706` | 取**最长**匹配，更长者会清空已收集结果 |
| 3 | `*.ext` 扩展名 | `:707-727` | 点后缀长度必须与 pattern 一致 |
| 4 | `/` | `:734-758` | 命中即收集，不再校验 HTTP method |

第 4 轮不查 method 是刻意的，但也是坑：给 `/` 加 `user-data-constraint` 等于对全部方法生效。

Realm 的选取是就近原则：`CAT/core/ContainerBase.java:479-494` 的 `getRealm()` 先看自己身上，没有就递归问父容器，所以 Engine 上一份 Realm 会被全部 Context 共享，Context 内的 `<Realm>` 只覆盖自己。`server.xml` 里 `<Realm>` 可嵌套（`CAT/startup/RealmRuleSet.java:63-77`）：最外层走 `setRealm`，内层走 `addRealm`，这正是 `CombinedRealm` / `LockOutRealm` 包裹子 Realm 的配置形态。

| Realm | 用途与关键事实 |
| :--- | :--- |
| `MemoryRealm` | 读 `tomcat-users.xml`，`getPassword()` / `getPrincipal()` 查两张内存表（`CAT/realm/MemoryRealm.java:218-228`） |
| `UserDatabaseRealm` | 通过 JNDI `UserDatabase` 读同一份文件，`resolveNames` 决定是否用静态 Principal（`CAT/realm/UserDatabaseRealm.java:72-73`） |
| `JNDIRealm` | LDAP，六个 `authenticate` 重载全接（`CAT/realm/JNDIRealm.java:1270/1450/1474/1499/1523/1547`） |
| `DataSourceRealm` | JDBC，`dataSourceName` + `userTable` / `userRoleTable` 等列名（`CAT/realm/DataSourceRealm.java:66-102`） |
| `JAASRealm` | 委托 LoginModule，`appName` / `userClassNames` / `roleClassNames`（`CAT/realm/JAASRealm.java:136/250/312`） |
| `CombinedRealm` | 按配置顺序逐个试，任一跳成功即通过，要求用户名全局唯一（`CAT/realm/CombinedRealm.java:42-46`） |
| `LockOutRealm` | 继承 `CombinedRealm`，只包装其它 Realm；`failureCount` 默认 5、`lockOutTime` 默认 300 秒（`CAT/realm/LockOutRealm.java:56-62`） |
| `NullRealm` | 永远返回 null，作为未配置 Realm 时的兜底 |
| `AuthenticatedUserRealm` | 只按用户名造 `GenericPrincipal`，不校验凭据，配 NonLogin 之外的 Authenticator 不安全 |

## AuthenticatorBase.invoke chain

`CAT/authenticator/AuthenticatorBase.java:498` 起，一条请求依次经过下面几步（行号均为该方法内）：

```java
// Have we got a cached authenticated Principal to record?
if (cache) {
    Principal principal = request.getUserPrincipal();
    if (principal == null) {
        Session session = request.getSessionInternal(false);
        if (session != null) {
            principal = session.getPrincipal();
            ...
```

`CAT/authenticator/AuthenticatorBase.java:503-512`。SSO Valve 或上游组件已经放过 Principal 时，这里直接复用会话里缓存的 Principal 与 authType。

1. `isContinuationRequired(request)`（`:522`）：FORM 用它把「提交 `j_security_check`」和「登录后重定向回原请求」两类续传请求拉进认证流程（`CAT/authenticator/FormAuthenticator.java:354-371`）。
2. `realm.findSecurityConstraints(request, context)`（`:527`）取约束。
3. `getJaspicContextState()`（`:529`）：只要 Context 配了 JASPIC，`authRequired` 无条件为真（`:531-537`），即使没有任何安全约束。
4. 无约束且未开 `preemptiveAuthentication` 且不需要认证 → 直接 `getNext().invoke()` 放行（`:538-544`）。
5. `disableCaching()`（`:551`、实现 `:667`）给受约束资源加 `Pragma: No-cache` 或 `Cache-Control: private`；`securePagesWithPragma` 默认已是 false（`:184`）。
6. `checkUserDataConstraints()`（`:554`）→ `RealmBase.hasUserDataPermission()`（`CAT/realm/RealmBase.java:989`）执行 `transport-guarantee`：非 secure 请求先问 `redirectPort`，`<=0` 直接 403（`:1026-1031`），否则按 `transportGuaranteeRedirectStatus` 重定向，默认 302（`:162`）。
7. 扫一遍约束算出 `hasAuthConstraint`（`:560-577`）：只有 `auth-constraint` 存在且列了角色（或 `allRoles` / `authenticatedUsers`）才算需要身份。
8. `allowCorsPreflightBypass(request)`（`:587-593`、`:711`）：`allowCorsPreflight` 取 `NEVER`/`FILTER`/`ALWAYS`（默认 `NEVER`，`:238`、`:1523-1541`），OPTIONS 预检可在认证前放行。
9. `authRequired` 为真时走 `doAuthenticateExtended()`（`:598`、`:850`），基类只是包一层 `doAuthenticate()`（`:835`）；返回值三态见 `AuthenticationResult`（`:1570-1590`），`PASSED_CONSTRAINTS_NEED_REFRESH` 会重算约束、重做缓存禁用与用户数据约束检查（`:599-609`）。
10. 有约束则 `realm.hasResourcePermission(...)`（`:650-662`）做角色判定。
11. 全部通过后放行，并在 JASPIC 生效时调用 `secureResponseJaspic()`（`:660-664`）。

## 401 or 403

判断口径很简单：**401 由 Authenticator 决定（凭据没拿到或不对），403 由 Realm 决定（身份没问题但角色不够、或 `redirectPort` 被禁用）**。

| 状态 | 产生点 | 位置 |
| :--- | :--- | :--- |
| 401 | BASIC 无有效 `Authorization` | `CAT/authenticator/BasicAuthenticator.java:123` |
| 401 | DIGEST nonce/校验失败 | `CAT/authenticator/DigestAuthenticator.java:376` |
| 401 | CLIENT-CERT 无证书 / Realm 不认识 | `CAT/authenticator/SSLAuthenticator.java:95`、`:105` |
| 401 | SPNEGO 各阶段 | `CAT/authenticator/SpnegoAuthenticator.java:209/221/238/247/293/305/317/353` |
| 403 | 角色不匹配 | `CAT/realm/RealmBase.java:887` |
| 403 | `confidential` 但 `redirectPort <= 0` | `CAT/realm/RealmBase.java:1030` |
| 403 | FORM 待存请求体超 `maxSavePostSize` | `CAT/authenticator/FormAuthenticator.java:249` |
| 400 | FORM 还原请求失败 / 非 POST 打 `j_security_check` | `CAT/authenticator/FormAuthenticator.java:201`、`:219` |
| 408 | FORM 登录成功但会话已过期且无 `landingPage` | `CAT/authenticator/FormAuthenticator.java:297` |
| 500 | JASPIC 已配置但 `ServerAuthConfig` 初始化失败 | `CAT/authenticator/AuthenticatorBase.java:611-614` |

`RealmBase.hasResourcePermission()` 内部对 `denyfromall` 用 `break` 提前结束（`CAT/realm/RealmBase.java:822-832`），即某条约束 `auth-constraint` 存在但角色列表为空就是彻底拒绝，后续约束不再看。`allRolesMode` 默认 `STRICT_MODE`（`:152`），`role-name="*"` 只在 `AUTH_ONLY_MODE` / `STRICT_AUTH_ONLY_MODE` 下会放宽（`:849-880`）。

## Handshake semantics per Authenticator

`CAT/authenticator/AuthenticatorBase.java:108` 定义 `AUTH_HEADER_NAME = "WWW-Authenticate"`，四个产生挑战的实现各有取舍。

BASIC 直接解析 `Authorization` 头（`CAT/authenticator/BasicAuthenticator.java:88-106`），解析器是内部类 `BasicCredentials`（`:146`），失败即造 `Basic realm="...", charset=UTF-8`（`:112-123`，字符集由 `setCharset` 控制 `:69`）。凭据在链路上是 base64，因此 `sendAuthInfoResponseHeaders`（`:224`、`:1168-1172`）向后转发时要格外小心。

FORM 是唯一会改写请求语义的实现，`doAuthenticate()` 直接抛 `UnsupportedOperationException`（`CAT/authenticator/FormAuthenticator.java:348-351`），全部逻辑在 `doAuthenticateExtended()`：

- 非登录动作请求 → `saveRequest()` 存原始请求（`:679`）→ `forwardToLoginPage()` 转发到 `<form-login-page>`（`:341`）。
- 命中 `j_security_check` 常量（`CAT/authenticator/Constants.java:42`）→ 读 `j_username` / `j_password`（`Constants.java:47/51`）→ `realm.authenticate(username, password)`（`FormAuthenticator.java:266`）。
- 口令错 → `forwardToErrorPage()`，**不发 401**（`:268-271`）。
- 成功 → `register()` 后 303（HTTP/1.1）或 302 重定向回原 URI（`:318-341`）。

还原阶段 `restoreRequest()`（`:572`）把方法、头、cookie、请求体整体回填，若 HTTP method 被换掉则返回 `PASSED_CONSTRAINTS_NEED_REFRESH`（`:663-666`）——因为 GET 与 POST 可能落在不同约束上。`changeSessionIdOnAuthentication`（`AuthenticatorBase.java:169`，默认 true）与 `Constants.SESSION_ID_NOTE` 的组合用于阻断会话固定：登录时比对预期会话 ID，不符就作废（`FormAuthenticator.java:280-289`）。`cache=false` 时用户名口令被写进会话 note 以便逐请求再认证（`:386-405`），这是一份真实的明文口令驻留。

DIGEST 的 11 版有几点与旧资料不同：挑战算法列表默认 `[SHA-256, MD5]`，会为每个算法各发一条 `WWW-Authenticate`（`CAT/authenticator/DigestAuthenticator.java:151`、`:434-463`），`userhash` 明确不支持；nonce 用 `SHA-256(clientIP:timestamp:key)` 生成（`:68`、`:398-424`）；`nonceValidity` 默认 5 分钟（`:133`）、nonce 缓存 1000 条 FIFO（`:114`、`:494-515`）、`nc` 窗口 100（`:121`）、`validateUri` 默认开（`:143`）；构造器里 `setCache(false)`（`:88`）——服务端不缓存 DIGEST 认证结果，因为它拿不到明文口令。`checkForCachedAuthentication(request, response, false)` 也拒绝用 SSO 缓存的口令重放（`:347`）。安全性判断留给读者：Digest 的 H(A1) 等价于口令替代品，服务端一旦按 `{MD5}` 之类存 H(a1:realm:a2)，拿到库就等于拿到口令。

CLIENT-CERT 见下一节。SPNEGO 走 `GSSContext.acceptSecContext`（`CAT/authenticator/SpnegoAuthenticator.java:252-290`），响应体里带 `Negotiate` token（`:336-353`），JaaS 配置缺省时指向 `conf/jaas.conf`、Kerberos 配置缺省 `conf/krb5.ini`（`CAT/authenticator/Constants.java:58-78`）。NONE 即 `NonLoginAuthenticator`，任何情况下都「认证成功」但不给角色（`CAT/authenticator/NonLoginAuthenticator.java:79-100`），作用是让 SSO 与 `HttpServletRequest.login()` 在同一 Host 内共用会话。

## SingleSignOn mechanism and placement

`CAT/authenticator/SingleSignOn.java:106` 的 `cache` 是 `ConcurrentHashMap<String,SingleSignOnEntry>`，键就是 cookie 值；cookie 名 `JSESSIONIDSSO`（`CAT/authenticator/Constants.java:84`），path 固定 `/`，`secure`/`httpOnly`/`Partitioned` 跟随会话 cookie 规则（`AuthenticatorBase.java:1207-1226`）。

`invoke()`（`SingleSignOn.java:237`）只做两件事：请求已有 Principal 就直接放行；否则拿 cookie 查 `SingleSignOnEntry`，命中则写 `REQ_SSOID_NOTE`，并且在 `requireReauthentication` 为 false 时直接把缓存的 Principal 与 authType 挂到请求上（`:287-294`）；查不到就下发一个 `Max-Age=0` 的删除 cookie（`:296-320`）。

条目本身记录 Principal、authType、用户名、口令，以及一组 `SingleSignOnSessionKey`（`CAT/authenticator/SingleSignOnEntry.java:65`、`SingleSignOnSessionKey.java:38-46` 的 `sessionId` + `contextName` + `hostName`）。`addSession()` 首次绑定时给会话挂 `SingleSignOnListener`（`SingleSignOnEntry.java:101-108`），会话销毁即回调 `sessionDestroyed()`（`SingleSignOn.java:337`）；`deregister()` 则遍历所有 key 调 `expire()`（`:405-434`），`expire()` 沿 `engine.findChild(hostName)` → `host.findChild(contextName)` → `manager.findSession(sessionId)` → `session.expire()` 逐级找回来（`:438-472`）。这条链解释了为什么 key 里要存 host 与 context 名：**SSO 表是跨 Context 的，注销必须能定位到任意 Context 的会话**。

放置位置决定作用域。`AuthenticatorBase.startInternal()` 从自己的父容器开始逐级向上找 `SingleSignOn` Valve（`CAT/authenticator/AuthenticatorBase.java:1359-1371`），Context 级 pipeline 只有本 Context 的 Authenticator 能看到，因此要跨 Context 共享必须把 `<Valve className="org.apache.catalina.valves.SingleSignOn" />` 挂在 `<Host>` 或 `<Engine>` 上；实践上 Engine 是唯一能覆盖同 Host 全部 Context 又只装一份的位置。

再认证语义在 11 变复杂了。`requireReauthentication`（`SingleSignOn.java:110/185/220`）为 true 时 SSO 不代填 Principal，`AuthenticatorBase.checkForCachedAuthentication()`（`:981`）按 `ssoReauthenticationMode`（`DEFAULT`/`PRINCIPAL`/`PASSWORD`/`FULL`，`:236`、`:1544-1562`）决定用缓存 Principal 还是用缓存用户名口令去 `sso.reauthenticate()`（`:1098-1120`）。类注释列出了五种 auth-method 的回退方式，并点明 CLIENT-CERT 与 SPNEGO 场景下只缓存 Principal 不够用（`SingleSignOn.java:60-83`）。

跨节点的 SSO 表共享由集群模块的 `ClusterSingleSignOn` 承担（把注册/注销动作变成 tribes 消息广播），机制与放置约束见 [Cluster](/docs/CS/Framework/Tomcat/Cluster.md)。

## Credential storage and CredentialHandler

`CAT/CredentialHandler.java:23` 只有两个方法：`matches(input, stored)` 与 `mutate(input)`（生成存储值）。`RealmBase.authenticate(username, credentials)`（`CAT/realm/RealmBase.java:377-415`）先查存储值，查不到时仍调用 `getCredentialHandler().mutate(credentials)` 消耗一次散列时间，避免通过响应时延枚举用户；比对命中才 `getPrincipal(username)`。

| 实现 | 关键默认值 | 位置 |
| :--- | :--- | :--- |
| `MessageDigestCredentialHandler` | `DEFAULT_ITERATIONS = 1`，无 salt 无迭代时输出旧格式裸散列；支持 `{MD5}` / `{SHA}` 前缀 | `CAT/realm/MessageDigestCredentialHandler.java:66`、`:143` |
| `SecretKeyCredentialHandler` | `DEFAULT_ITERATIONS = 20000`（PBKDF2，带密钥） | `CAT/realm/SecretKeyCredentialHandler.java:48` |
| `DigestCredentialHandlerBase` | `DEFAULT_SALT_LENGTH = 32` 字节，存储格式 `hexSalt$iterations$digest` | `CAT/realm/DigestCredentialHandlerBase.java:49`、`:158`、`:172` |
| `NestedCredentialHandler` | `matches` 逐个尝试，`mutate` 只用第一个 | `CAT/realm/NestedCredentialHandler.java:42-63` |

Realm 未显式配置 handler 时，`startInternal()` 兜底 `new MessageDigestCredentialHandler()`（`CAT/realm/RealmBase.java:1096-1097`）。升级口令策略的正解是 `NestedCredentialHandler`：新算法放第一个，旧算法留在后面兜底，`mutate` 只按首个 handler 写新值，于是存量口令在用户下次改密时自然迁移。`<CredentialHandler>` 元素在 XML 里可嵌套（`CAT/startup/CredentialHandlerRuleSet.java:70-85`，层数上限由系统属性控制，默认 3，`:30-31`）。注意 11 已经没有 `SHA256WithSaltCredentialHandler`（全树 grep 无匹配），旧文档里的类名要换。

生成散列值可直接用 RealmBase 自带的命令行工具（`CAT/realm/RealmBase.java:1346`），它会依次试 `credentialHandlerClasses` 里登记的 `MessageDigestCredentialHandler` 与 `SecretKeyCredentialHandler`（`:93-101`、`:1435`）。

## Client certificate authentication

链路起点在握手期：`certificateVerification` 决定 JSSE 侧的 `setNeedClientAuth` / `setWantClientAuth`（`COY/util/net/AbstractEndpoint.java:767-777`），详见 [TLS](/docs/CS/Framework/Tomcat/TLS.md)。

证书到手有两种姿势：`SSLAuthenticator.getRequestCertificates()`（`CAT/authenticator/SSLAuthenticator.java:138-151`）先看 `jakarta.servlet.request.X509Certificate` 属性（`COY/util/net/SSLSupport.java:44`），没有就触发 `ActionCode.REQ_SSL_CERTIFICATE` 惰性向连接要。后者要求请求体尚未被消费，且受 `maxSavePostSize`（默认 4 KiB，`COY/org/apache/coyote/http11/AbstractHttp11Protocol.java:249`）限制，超量会抛 `IllegalStateException` 并被吞成认证失败。

Realm 侧 `RealmBase.authenticate(X509Certificate[])`（`CAT/realm/RealmBase.java:455-483`）在 `validate`（默认 true，`:137`）打开时逐张 `checkValidity()`，然后 `getPrincipal(certs[0])`（`:1222`）把 Subject DN 变成用户名，可换 `X509UsernameRetriever` / `X509SubjectDnRetriever` 定制取值（`:287`、`:1613`）。注意这一步只做有效期检查，**签名链的信任校验在握手期由 TLS 层完成**，把 `certificateVerification` 配成 `none` 时 Realm 拿到的是未经信任校验的自报证书。

`SSLAuthenticator.startInternal()`（`:157-236`）会主动体检并在两种情况下告警：Connector 上存在 `h2` ALPN（HTTP/2 既不允许重协商也不支持 PHA），或某个 `SSLHostConfig` 启用了 TLSv1.3 而 `isTls13RenegotiationAvailable()` 为 false（JSSE 无 PHA）。结论是：CLIENT-CERT 只有在所有虚拟主机都 `certificateVerification="required"` 时才可靠。

## JASPIC pre-processing

`AuthenticatorBase` 用 `JaspicContextState`（`CAT/authenticator/AuthenticatorBase.java:1512`，一个 `AuthConfigProvider` + `ServerAuthConfig` 的 record）缓存模块发现结果，`getJaspicContextState()`（`:1421-1462`）经 `AuthConfigFactory.getFactory()` 取工厂，再以 `layer="HttpServlet"`、`appContext = virtualServerName + " " + contextPath`（`:1357`）注册监听并 `getConfigProvider(...)`。`RegistrationListener.notify()`（`:1411-1417`）把缓存置空，配合读写锁保证并发请求看到一致的 JASPIC 状态。

请求期 `getJaspicRequestState()`（`:805-820`）造 `MessageInfoImpl` 并 `getServerAuthContext`，`authenticateJaspic()`（`:889-953`）调 `validateRequest`，成功后从 `Subject` 造 `GenericPrincipal`（`:956`），并读取 map 里的 `jakarta.servlet.http.registerSession` 与 `jakarta.servlet.http.authType` 决定 `register()` 的 `alwaysUseSession` / `cache` 实参（`:920-946`），最后把 `Subject` 存进 `REQ_JASPIC_SUBJECT_NOTE`。响应侧由 `secureResponseJaspic()`（`:794-802`）调 `secureMessageResponse`。`jaspicCallbackHandlerClass` 默认 `org.apache.catalina.authenticator.jaspic.CallbackHandlerImpl`（`:214`）。

`CAT/authenticator/jaspic/` 下 Tomcat 自带的实现是 `AuthConfigFactoryImpl`、`SimpleAuthConfigProvider`、`SimpleServerAuthConfig`、`SimpleServerAuthContext`、`MessageInfoImpl`、`CallbackHandlerImpl`、`PersistentProviderRegistrations`；持久注册写在 `conf/jaspic-providers.xml`（`CAT/authenticator/jaspic/AuthConfigFactoryImpl.java:62-63`）。`AuthConfigFactoryImpl` 本身由 JASPIC API 的工厂发现机制装载，与 Tomcat 的 `<Realm>` 体系完全平行：JASPIC 生效时模块自己负责挑战与响应，容器只做约束匹配与角色判定。

## Pitfalls

| 现象 | 根因 | 定位 |
| :--- | :--- | :--- |
| Realm 配在 Context 上却不生效 | 找 Realm 是就近向上递归，先看父级 | `CAT/core/ContainerBase.java:479-494` |
| SSO 只在一个应用里有效 | Valve 挂在 Context 上，其它 Context 的 Authenticator 找不到它 | `CAT/authenticator/AuthenticatorBase.java:1359-1371` |
| 登录后 403 而不是回到原页 | 原请求 method 与 GET 不同，重算约束后角色不再匹配 | `CAT/authenticator/FormAuthenticator.java:663-666` |
| `transport-guarantee="CONFIDENTIAL"` 直接 403 | `redirectPort` 未配或为 0 | `CAT/realm/RealmBase.java:1026-1031` |
| 反向代理终结 TLS 后约束判定异常 | `request.isSecure()` 为 false，需要 `RemoteIpValve` 改写 | `CAT/realm/RealmBase.java:1014` |
| `<security-role-ref>` 像是没起作用 | 它只作用于 `isUserInRole()`，约束授权走 Realm 角色名 | `CAT/connector/Request.java:2347-2353` 对 `CAT/realm/RealmBase.java:902-912` |
| 角色别名生效路径不清 | `hasRole()` 会先查 Context 级 role mapping（来自 `PropertiesRoleMappingListener`） | `CAT/core/StandardContext.java:3004/3282` |
| 加了 `auth-constraint` 却全都拒绝 | 角色列表为空即 `denyfromall`，直接 break | `CAT/realm/RealmBase.java:822-832` |
| 无 `<login-config>` 却能用 `req.login()` | 容器补了 `DUMMY_LOGIN_CONFIG`（NONE） | `CAT/startup/ContextConfig.java:144/340-343` |
| 改密后旧散列无法校验 | 单一 handler 只认自己格式，需 `NestedCredentialHandler` | `CAT/realm/NestedCredentialHandler.java:42-50` |
| DIGEST 换算法后部分客户端失败 | 服务端会发多条 `WWW-Authenticate`，旧客户端只认 MD5 | `CAT/authenticator/DigestAuthenticator.java:151/434-463` |
| 会话固定防护误伤 | `SESSION_ID_NOTE` 与 `changeSessionIdOnAuthentication` 联动 | `CAT/authenticator/FormAuthenticator.java:280-289` |

`Authenticator` 与框架自身安全层（如 Spring Security 的过滤器链）是两套并行机制：容器认证发生在进入 Servlet 之前，框架认证发生在过滤器链内，二者对 `isUserInRole`、`authenticate()` 的语义并不等价，选型时只保留一层为主。

## Links

- [TLS](/docs/CS/Framework/Tomcat/TLS.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Start](/docs/CS/Framework/Tomcat/Start.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Jetty Security](/docs/CS/Framework/Jetty/Security.md)

## References

- [Apache Tomcat 11.0 Realm Configuration](https://tomcat.apache.org/tomcat-11.0-doc/config/realm.html)
- [Apache Tomcat 11.0 Valve Configuration](https://tomcat.apache.org/tomcat-11.0-doc/config/valve.html)
- [Apache Tomcat 11.0 HTTP Connector Configuration](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html)
- [RFC 7617 - The HTTP Basic Authentication Scheme](https://www.rfc-editor.org/rfc/rfc7617)
- [RFC 7616 - HTTP Digest Access Authentication](https://www.rfc-editor.org/rfc/rfc7616)
