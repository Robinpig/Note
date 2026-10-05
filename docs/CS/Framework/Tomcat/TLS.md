# Tomcat TLS

## Introduction

Tomcat 11 的 TLS 栈比多数旧文章描述的**窄得多**：连接器（Connector）之下只剩两条实现路线。

1. **JSSE**：`org.apache.tomcat.util.net.jsse.*`，走 JDK 的 `SSLContext` / `SSLEngine`，是默认路线。
2. **OpenSSL provider**：`org.apache.tomcat.util.net.openssl.*`，走 Java binding 调用 OpenSSL，通过 `sslImplementationName` 显式选择。

两条路线共享同一个配置装配基类 `SSLUtilBase` 和同一套对象模型 `SSLHostConfig` / `SSLHostConfigCertificate`，差异被压到「实现 SPI」这一层。

**「APR 时代」的资料整体失效**。APR/native 连接器在 Tomcat 10.1 起弃用、11 中彻底移除：coyote 里查不到任何 `Http11AprProtocol` 或 `AprEndpoint` 的 Java 实现，`net/` 目录剩下的端点只有 `NioEndpoint` 与 `Nio2Endpoint`（`tomcat-coyote-11.0.26/org/apache/tomcat/util/net/` 目录清单）。`AprLifecycleListener` 字样只在两处残留：`openssl/OpenSSLContext.java:174-176` 的注释，以及 `net/LocalStrings*.properties`、`catalina/core/LocalStrings*.properties` 里未清理的旧消息串（`aprListener.*` 现在只剩 FIPS 相关文案）。所以凡是讲 `APR` + `SSLProtocol` + `useSSLEngine`、或把 `tcnative` 当作性能必选项的文章，都需要按本篇重写。`docs/CS/Framework/Tomcat/Connector.md` 末尾的 APR 一节同属过时内容。

另一条影响全局的前提：**11 已移除 SecurityManager**，旧文里 `AccessController.doPrivileged` 包裹 TLS 初始化的叙述一律不成立。

## Two implementation routes and SPI

`sslImplementationName` 是选择实现路线的连接器属性。它挂在 protocol handler 上，再由 handler 转交给 endpoint：

```java
                jsseProtocolHandler.isSSLEnabled() && jsseProtocolHandler.getSslImplementationName() == null) {
```

（`tomcat-catalina-11.0.26/org/apache/catalina/connector/Connector.java:1273`，此处可见 `Connector` 只在「已启用 SSL 且未指定实现名」时走默认分支。）

SPI 出口是 `net/SSLImplementation.java`，两个实现各自注册：

| 路线 | 入口类 | 上下文 | 支持 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| JSSE | `net/jsse/JSSEImplementation.java` | `jsse/JSSESSLContext.java` | `SSLContext` | `jsse/JSSEUtil.java`、`JSSESupport.java`、`JSSEKeyManager.java`；`jsse/PEMFile.java` 让 JSSE 也能直接吃 PEM |
| OpenSSL | `net/openssl/OpenSSLImplementation.java` | `openssl/OpenSSLContext.java` | `OpenSSLEngine.java` | 附带 `openssl/ciphers/` 套件解析器、`OpenSSLConf` / `OpenSSLConfCmd` 配置语言、`OpenSSLCertificateVerifier.java`、`OpenSSLSessionContext.java`、`OpenSSLSessionStats.java` |

`SSLUtilBase` 承担所有**与 provider 无关**的决策：协议求交集、套件求交集、TLS 1.3 后握手认证可用性探测。构造器（约 `net/SSLUtilBase.java:129` 起）里最关键的三段：

```java
        if (!implementedProtocols.contains(Constants.SSL_PROTO_TLSv1_3) &&
                !sslHostConfig.isExplicitlyRequestedProtocol(Constants.SSL_PROTO_TLSv1_3)) {
            configuredProtocols.remove(Constants.SSL_PROTO_TLSv1_3);
        }
```

```java
        if (!JreCompat.isJre22Available() && sslHostConfig.getCiphers().startsWith("PROFILE=")) {
            // OpenSSL profiles cannot be resolved without Java 22
            this.enabledCiphers = new String[0];
        } else {
            boolean warnOnSkip = !sslHostConfig.getCiphers().equals(SSLHostConfig.DEFAULT_TLS_CIPHERS_12);
            List<String> configuredCiphers = sslHostConfig.getJsseCipherNames();
```

```java
            if (enabled.isEmpty()) {
                // Don't use the defaults in this case. They may be less secure
                // than the configuration the user intended.
                // Force the failure of the connector
                throw new IllegalArgumentException(sm.getString("sslUtilBase.noneSupported", name, configured));
            }
```

值得记住的是最后一段：配置项与 provider 能力求交后**为空时不回落默认值，而是让连接器启动失败**。这是「配了却不生效」类问题的根因定位点——日志里 `sslUtilBase.skipped` 会列出被跳过的名字。

## SSLHostConfig object model

层级是**三层**，不是两层：

```
Connector
└── SSLHostConfig            (按 hostName 区分，一份 = 一个 TLS 虚拟主机)
    └── SSLHostConfigCertificate  (按 Type 区分，RSA / EC / ... 各一张)
```

关键字段（`net/SSLHostConfig.java`）：

```java
    private SSLHostConfigCertificate defaultCertificate = null;
```

```java
    private final Set<SSLHostConfigCertificate> certificates = new LinkedHashSet<>(4);
```

`hostName` 为 null/未设时取 `DEFAULT_SSL_HOST_NAME = "_default_"`（`:63`）；`certificates` 是 `LinkedHashSet`，**顺序即优先级**，第一张同时是 `defaultCertificate`。

证书类型枚举是 `SSLHostConfigCertificate.Type`（`net/SSLHostConfigCertificate.java:561-586`），构造参数是它接受的 `Authentication`（即 TLS 签名/密钥交换算法族）：

```java
        RSA(Authentication.RSA),
        DSA(Authentication.DSS, Authentication.EdDSA),
        EC(Authentication.ECDH, Authentication.ECDSA),
        MLDSA("ML-DSA", Authentication.MLDSA);
```

（注意 `EC` 的实参是 `Authentication.ECDH, Authentication.ECDSA`；`MLDSA` 是 11 里为**后量子签名**新增的类型，字符串名带连字符 `ML-DSA`。另外还有一个内部用的 `UNDEFINED`。）

结论：**没有 `DJK` 这个类型**。`dJKU`（digital signature / keyEncipherment / keyAgreement）是 TLS 1.3 侧的用法标记，不是 Tomcat 的配置枚举，旧资料里 `type="DJK"` 之类写法在 11 无处落地。

多证书的实际用法是给同一虚拟主机同时挂 RSA 与 EC 证书，让握手时按客户端提供的套件挑选；ML-DSA 则是为混合签名证书链留的位。

## certificateVerification and depth

`SSLHostConfig.certificateVerification`（`:164`，默认 `NONE`）驱动「要不要向客户端索取并校验证书」。字符串常量由枚举的 `fromString()` 定义（约 `:1664`）：

```java
        public static CertificateVerification fromString(String value) {
            if ("true".equalsIgnoreCase(value) || "yes".equalsIgnoreCase(value) || "require".equalsIgnoreCase(value) ||
                    "required".equalsIgnoreCase(value)) {
                return REQUIRED;
            } else if ("optional".equalsIgnoreCase(value) || "want".equalsIgnoreCase(value)) {
                return OPTIONAL;
            } else if ("optionalNoCA".equalsIgnoreCase(value) || "optional_no_ca".equalsIgnoreCase(value)) {
                return OPTIONAL_NO_CA;
            } else if ("false".equalsIgnoreCase(value) || "no".equalsIgnoreCase(value) ||
                    "none".equalsIgnoreCase(value)) {
                return NONE;
            } else {
                // Could be a typo. Don't default to NONE since that is not
                // secure. Force user to fix config. Could default to REQUIRED
                // instead.
                throw new IllegalArgumentException(sm.getString("sslHostConfig.certificateVerificationInvalid", value));
            }
        }
```

四态的完整集合是 `NONE(false)` / `OPTIONAL_NO_CA(true)` / `OPTIONAL(true)` / `REQUIRED(false)`，构造参数是 `optional` 标记（`:1619-1640`）。三点值得注意：

* 可写的值远不止 `none`/`want`/`need`——`require`、`required`、`true`、`yes` 都归一到 `REQUIRED`；`want` 只是 `optional` 的别名。旧文档的 `need` 在 11 里对应 `required`。
* 拼错**不会静默降级**，而是抛 `IllegalArgumentException` 拒绝启动，源码注释明确解释了「不敢默认回落到 NONE」。
* `NONE` 与 `REQUIRED` 的 `optional` 都是 `false`，只有两个 OPTIONAL 变体为 `true`。

深度：`certificateVerificationDepth = 10`（`:168`），并有 `certificateVerificationDepthConfigured` 标志（`:173`）区分「用户显式设过」与「用默认」，供 trust config 派生时判断是否要跟着调整。校验链材料来自 `certificateRevocationListFile` / `certificateRevocationListPath`（`:160` / `:281`）与 `caCertificateFile` / `caCertificatePath`（`:285` / `:289`），以及 JSSE 侧的 `truststoreFile` 系列（`:252-264`，直接读 `javax.net.ssl.trustStore*` 系统属性作为默认）。

TLS 1.3 在这件事上有一个硬约束，`SSLUtilBase` 构造器主动报警：

```java
        if (enabledProtocols.contains(Constants.SSL_PROTO_TLSv1_3) &&
                sslHostConfig.getCertificateVerification().isOptional() && !isTls13RenegAuthAvailable() && warnTls13) {
            log.warn(sm.getString("sslUtilBase.tls13.auth"));
        }

        // Make TLS 1.3 renegotiation status visible further up the stack
        sslHostConfig.setTls13RenegotiationAvailable(isTls13RenegAuthAvailable());
```

TLS 1.3 取消了 renegotiation，客户端证书只能在握手内或 post-handshake authentication 里要。若 provider 不支持后握手认证，`want`（OPTIONAL）语义在 TLS 1.3 上**无法兑现**——这就是 `tls13RenegotiationAvailable`（`:123`）存在的意义，它把探测结果向上传给 `SSLAuthenticator` 层。

握手成功后证书链才交给 catalina 的认证层（`SSLAuthenticator` → Realm 的证书认证入口），本篇不展开，见 `docs/CS/Framework/Tomcat/Security.md`。

## Why ciphers and cipherSuites are separate fields

`SSLHostConfig.java:170-198`（原样）：

```java
    /**
     * Whether the certificate verification depth was explicitly configured.
     */
    private boolean certificateVerificationDepthConfigured = false;
    /**
     * The cipher configuration for TLS 1.2 and below (OpenSSL format).
     */
    private String ciphers = DEFAULT_TLS_CIPHERS_12;
    /**
     * The cipher suite configuration for TLS 1.3.
     */
    private String cipherSuites = DEFAULT_TLS_CIPHERS_13;
    private String cipherSuitesFromCiphers = null;
    /**
     * The parsed cipher list for TLS 1.2 and below.
     */
    private LinkedHashSet<Cipher> cipherList = null;
    /**
     * The parsed cipher suite list for TLS 1.3.
     */
    private LinkedHashSet<Cipher> cipherSuiteList = null;
    /**
     * The JSSE cipher names derived from the configuration.
     */
    private List<String> jsseCipherNames = null;
    /**
     * Whether to honor the server's cipher order preference.
     */
    private boolean honorCipherOrder = false;
```

根因是 **TLS 1.3 的套件表不可扩展、也不接受 OpenSSL 的表达式语法**。TLS 1.2 及以下沿用 OpenSSL 的选择语言（`HIGH:!aNULL:...`、`PROFILE=...`），而 TLS 1.3 只有固定的少数几个 suite，只能按名字列。两套语义塞进一个字符串必然分裂，于是拆成两字段，解析结果分别落在 `cipherList` 与 `cipherSuiteList`，再由 `jsseCipherNames` 桥接成 JSSE 认识的 `TLS_*` 名字；`cipherSuitesFromCiphers` 用于「只写了 ciphers」时推导出的 1.3 部分。

默认值直接暴露了安全基线（`:71` / `:75`）：

```java
    public static final String DEFAULT_TLS_CIPHERS_12 = "HIGH:!aNULL:!eNULL:!DES:!RC4:!MD5:!kRSA";
    public static final String DEFAULT_TLS_CIPHERS_13 = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256";
```

`!kRSA` 排除了无前向保密的 RSA 密钥交换。另有 `DEFAULT_TLS_CIPHERS`（`:81`）已标 `@deprecated Replaced by DEFAULT_TLS_CIPHERS_12`——旧文章照抄的常量名就是它。

`honorCipherOrder`（默认 `false`）控制服务端顺序优先还是客户端顺序优先。`true` 时服务端把自己认为最强的套件排到前面（`cipherList` 是 `LinkedHashSet`，顺序即优先级），配合 `DEFAULT_TLS_CIPHERS_13` 把 AES-256-GCM 写在首位，可以让客户端优先选它。代理场景要注意：LB 与服务端各自协商一次，`honorCipherOrder` 只作用于**这一段**握手，不穿透。

provider 差异：OpenSSL 系能直接吃 `PROFILE=` 与全部 OpenSSL 语法；JSSE 系靠 `OpenSSLCipherConfigurationParser`（`SSLHostConfig.java:41-43` 的 import）把 OpenSSL 表达式翻译成 JSSE 套件名，覆盖面受限，且 `PROFILE=` 在 Java 22 以下**解析不了**（见上文的 `JreCompat.isJre22Available()` 分支）。named group 同理：`groups` 字段（`:272`）默认取 `jdk.tls.namedGroups` 系统属性，解析成 `Group` 列表。

## SNI and ClientHello parsing

Tomcat 不能等握手完成再决定「用哪张证书、哪个虚拟主机」——证书选择本身就在握手里。办法是**先把明文可读的 ClientHello 抠出来**：

> This class extracts the SNI host name and ALPN protocols from a TLS client-hello message.

（`net/TLSClientHelloExtractor.java:37`）

它的输出是一组客户端请求信息（`:44-50`，原样）：

```java
    private final ExtractorResult result;
    private final List<Cipher> clientRequestedCiphers;
    private final List<String> clientRequestedCipherNames;
    private final String sniValue;
    private final List<String> clientRequestedApplicationProtocols;
    private final List<String> clientRequestedProtocols;
    private final List<Group> clientSupportedGroups;
```

`ExtractorResult`（`:530`）共五种状态，解析主循环按它们分支：`NOT_PRESENT`（初值，`:87`）、`NON_SECURE`（`:109`）、`COMPLETE`（`:195`）、`UNDERFLOW` / `NEED_READ`（`handleIncompleteRead()`，`:328-334`）。`getSNIValue()` 只在 `COMPLETE` 时给值，且**返回小写形式**（`:231-236`）——大小写归一发生在解析层，上层不必再处理。

调用链（NIO 为例）：

1. `SecureNioChannel` 在读到首块数据时调 `processSNI()`（`net/SecureNioChannel.java:268`，NIO2 对应 `SecureNio2Channel.java:388`）。
2. `processSNI()` 累积缓冲并驱动 `TLSClientHelloExtractor`；`UNDERFLOW` 时回去续读，超过上限即判非法。
3. 解析完成后把 `extractor.getSNIValue()` 作为 hostName（`SecureNio2Channel.java:420`）传给 `createSSLEngine(hostName, clientRequestedCiphers, clientRequestedApplicationProtocols, ...)`（`SecureNioChannel.java:981-984`）。
4. 真正造 engine 的是 endpoint：`AbstractEndpoint.createSSLEngine(String sniHostName, ...)`（`net/AbstractEndpoint.java:707`，内部 `sslContext.createSSLEngine()` 于 `:720`）。它按 `sniHostName` 去本连接器的 `SSLHostConfig` 集合里查对应那份配置（每份 `SSLHostConfig` 有自己的 `SSLContext`，所以查中哪份就用哪份证书）。
5. **未命中就回落到默认虚拟主机**：`AbstractEndpoint.defaultSSLHostConfigName`，初值即 `SSLHostConfig.DEFAULT_SSL_HOST_NAME = "_default_"`（`:405`）。也就是说客户端不发 SNI、或 SNI 与任何 `<SSLHostConfig hostName=...>` 都不匹配时，握手照常成功、只是拿到默认证书；至于这个连接最终落到哪个 `<Host>`，由 HTTP 层的 `Host` 头与 Mapper 决定，与 SNI 无强制绑定——这正是「SNI 证书与虚拟主机不一致」告警的来源。

`AbstractEndpoint.getSNIValue()` 之外，还有一道防御性上限（`net/AbstractEndpoint.java:357`，原样）：

```java
    private int sniParseLimit = 64 * 1024;
```

连接器属性 `sniParseLimit` 经 `AbstractHttp11Protocol.setSniParseLimit()`（`org/apache/coyote/http11/AbstractHttp11Protocol.java:1095-1096`）转给 endpoint。意义在于：ClientHello 是明文长度可增长的输入，若不加限制，攻击者可以持续投递「看起来还没读完」的分片，让服务端为每条半连接无界地堆积解析缓冲（慢速握手 / 内存放大型 DoS）。64 KiB 恰好覆盖合法 ClientHello 的正常尺寸上限，超过即放弃该连接。

注意 `SSLHostConfig` 里**没有** `defaultSniProxy` 之类字段（全树检索无命中），「按 SNI 反代到别的上游」不是 Tomcat TLS 层的概念，别照抄其他服务器的说法。

## OCSP switches and soft fail

`SSLHostConfig.java:202-214`（含注释，原样摘录字段行）：

```java
    private boolean ocspEnabled = false;
    private boolean ocspSoftFail = true;
    private int ocspTimeout = 15000;
    private int ocspVerifyFlags = 0;
```

语义是**对端证书的吊销检查**（服务端检查客户端证书，或 OpenSSL 管理信任时检查链），不要与「OCSP stapling（服务端把签好的一侧响应附在自己证书上发出）」混为一谈；后者在 Tomcat 里属于 OpenSSL 配置语言范畴，用 `<OpenSSLConfCmd>` 表达。

装配点有两处：`SSLUtilBase.java:561-563` 读取 `ocspEnabled` 并据 `ocspSoftFail` 决定失败处理；OpenSSL 侧把四个字段翻译成 `OpenSSLConfCmd`（`net/openssl/OpenSSLContext.java:417-425`，原样）：

```java
                if (!foundOcspConfig) {
                    sslHostConfig.getOpenSslConf().addCmd(new OpenSSLConfCmd(OpenSSLConfCmd.NO_OCSP_CHECK,
                            Boolean.toString(!sslHostConfig.getOcspEnabled())));
                    sslHostConfig.getOpenSslConf().addCmd(new OpenSSLConfCmd(OpenSSLConfCmd.OCSP_SOFT_FAIL,
                            Boolean.toString(sslHostConfig.getOcspSoftFail())));
                    sslHostConfig.getOpenSslConf().addCmd(new OpenSSLConfCmd(OpenSSLConfCmd.OCSP_TIMEOUT,
                            Integer.toString(sslHostConfig.getOcspTimeout())));
                    sslHostConfig.getOpenSslConf().addCmd(new OpenSSLConfCmd(OpenSSLConfCmd.OCSP_VERIFY_FLAGS,
                            Integer.toString(sslHostConfig.getOcspVerifyFlags())));
```

注意 `NO_OCSP_CHECK` 写的是 `!ocspEnabled`——Tomcat 用「显式关闭」的 OpenSSL 指令来反向表达「启用」，且 `foundOcspConfig` 保证用户自己写的 `OpenSSLConfCmd` 优先，Tomcat 不覆盖。软硬失败按 OpenSSL 语义：soft fail（默认 `true`）= responder 不可达 / 超时（默认 15000 ms）时**放行**；hard fail = 拿不到有效响应就拒绝。选哪个取决于你更怕「CA 抖动导致业务不可用」还是「吊销检查形同虚设」。

`OpenSSLContext.java:124` 的注释还提示：只有走 **OpenSSL managed trust** 时才需要 `OpenSSLConf` 实例来承载这些 OCSP 参数。JSSE 路线的 OCSP 语义不靠这几个 cmd，若要精确控制请改用 JDK 的 `ocsp.enable` 等安全属性。

另有一个易混字段：`SSLHostConfig.revocationEnabled`（`:236`，默认 `false`）属于 JDK 证书吊销（CRL / PKIX）开关，与 `ocspEnabled` 不是一回事。

## Certificate lifecycle and session reuse

**热更新**。11 里名字最接近的类是 `catalina/security/TLSCertificateReloadListener.java`，但它**不是** ServiceStateListener，而是 `LifecycleListener`（`:45`）；从可见行为看，它做的是**临期巡检与告警**：`checkCertificatesForRenewal(Server)`（`:134`）遍历各 connector 的 `findSslHostConfigs()`（`:154`），筛出 `expiringCertificates`，逐条打印 subject 与 `getNotAfter()` 日期（`:167-171`）。也就是说它解决的是「证书快到期没人知道」，而不是「自动换证书」。

真正让新证书生效的路径是 endpoint 的 `reloadSslHostConfigs()`（`net/AbstractEndpoint.java:540`）——它销毁并按当前配置重建各 `SSLHostConfig` 的 `SSLContext`，可经 JMX 触发，因此**不必重启 JVM**。运维落地方式仍是「把新证书写到配置指向的位置 → 调 reload」，或直接对 connector 做 stop/start。

**会话复用**。这里要纠正一个常见误解：`SSLSessionManager` **不是会话缓存**，它是一个只有一个方法的接口（`net/SSLSessionManager.java`）：

```java
public interface SSLSessionManager {
    /**
     * Invalidate the SSL session
     */
    void invalidateSession();
}
```

它的职责是「让当前这个 SSL session 失效」，供上层（例如需要强制重新握手的路径）调用。真正的会话复用参数在 `SSLHostConfig`（`:223-232`、`:297`）：

```java
    private int sessionCacheSize = -1;
    private int sessionTimeout = 86400;
```

`sessionCacheSize = -1` 表示用 provider 默认缓存，`sessionTimeout = 86400` 即 24 小时（秒）。字段名是 `sessionTimeout` 而非旧文章常写的 `SSLSessionCacheTimeout`；另有 `disableSessionTickets`（`:297`，默认 `false`）控制用 ticket 恢复会话，OpenSSL 侧还能通过 `openssl/OpenSSLSessionContext.java` / `OpenSSLSessionStats.java` 观测命中情况。会话复用与 `certificateVerification` 有隐性耦合：复用命中时**不再重发客户端证书**，依赖证书做认证的逻辑必须确认自己拿到的是缓存会话里的同一身份。

## JSSE vs OpenSSL capabilities

| 维度 | JSSE（默认） | OpenSSL provider | 依据 |
| :--- | :--- | :--- | :--- |
| 依赖 | JDK 自带，无 native | 需 Java binding + native 库 | `net/jsse/` vs `net/openssl/` 目录清单 |
| 选择方式 | 不写 `sslImplementationName` 即默认 | `sslImplementationName` 指定实现类 | `Connector.java:1273` |
| 套件语法 | OpenSSL 表达式经解析器翻译，`PROFILE=` 需 Java 22 | 原生支持全部语法与 profile | `SSLUtilBase.java` 构造器、`SSLHostConfig.java:41-43` |
| TLS 1.3 | 取决于 JDK 版本 | 取决于 native 库版本 | `SSLUtilBase.java` 构造器 `isTls13RenegAuthAvailable()` |
| 后握手认证（`want` 在 1.3） | 探测失败则告警，语义不可兑现 | 同一路径统一探测 | `SSLUtilBase.java:141-146`、`SSLHostConfig.java:123` |
| OCSP | JDK 安全属性为主 | 四个 cmd 直接下发 | `SSLUtilBase.java:561-563`、`OpenSSLContext.java:417-425` |
| 配置语言 | 仅 Java 属性 | `OpenSSLConf` / `OpenSSLConfCmd` | `openssl/OpenSSLConf.java` |
| 会话统计 | 走 JSSE 标准 API | `OpenSSLSessionStats` | `openssl/OpenSSLSessionStats.java` |
| 不安全 renegotiation | 无对应项 | `insecureRenegotiation`，标为 OpenSSL 专有 | `SSLHostConfig.java:301,1522-1524` |
| FIPS | 换外部 JSSE provider | 历史上经 `AprLifecycleListener` 的 FIPSMode 配置 | `catalina/core/LocalStrings*.properties` 残留 `aprListener.*FIPS*` 文案 |
| 性能 | 受 JDK GC / 栈影响 | 传统上握手与批量吞吐更优，但要装 native | 经验结论，需自测 |

`SSLHostConfig` 用 `setProperty(name, Type.OPENSSL)` 记录某属性被标为「OpenSSL 专有」（例如 `insecureRenegotiation`，`:1523`），配合 `configType` / `trustConfigType`（`:97` / `:101`）在混用时给出一致性判断。跨 provider 迁移配置前先想这一点：**能写的属性不等于会被读到的属性**。

## ALPN handoff to HTTP/2

`TLSClientHelloExtractor` 与 SNI 一次性把 ALPN 列表（`clientRequestedApplicationProtocols`）也抠了出来，随 `createSSLEngine(...)` 传入（`SecureNioChannel.java:981-984`），因此 HTTP/2 的协议协商在同一个 SSLEngine 上完成，不需要额外的第二次握手。`clientRequestedProtocols`（`:49`）则承载 TLS 版本候选。协商细节与升级路径见 `docs/CS/Framework/Tomcat/HTTP2.md`。

## Connector attributes and TLS terminated at proxy

| 属性 | 作用 | 坑 |
| :--- | :--- | :--- |
| `SSLEnabled` | 打开该 connector 的 TLS | 关掉后 `SSLHostConfig` 子元素不再参与装配 |
| `scheme` | 逻辑协议名，影响 `request.getScheme()` / `isSecure()` | 只写 `scheme="https"` 不等于做了 TLS |
| `secure` | `isSecure()` 的真实来源 | LB 终结 TLS 后必须为 `true`，否则应用判定为明文 |
| `server` | 覆盖响应 `Server` 头 | 隐藏版本号属加固，不影响握手 |
| `sslProtocol` | JSSE 协议名，默认 `Constants.SSL_PROTO_TLS`（`SSLHostConfig.java:240`） | 与 `protocols` 集合是两个层面 |
| `bind` / `address` 之外的 `sniParseLimit` | ClientHello 解析上限 | 见上文防御意义 |

TLS 在 LB / Ingress 终结时，Tomcat 这一跳是**明文 HTTP**，于是 `isSecure()` 为 false、`HSTS` 判断失效、重定向回到 http、客户端证书彻底消失。必须补一个 Valve 从转发头恢复语义：`RemoteIpValve` 管 `X-Forwarded-For` / `X-Forwarded-Proto`，`SSLValve` 管证书头（并把剩余链按规则拆分）。详见 `docs/CS/Framework/Tomcat/Valve.md`。

## Pitfalls

**多证书与 `type` 冲突**。`addCertificate()`（约 `SSLHostConfig.java:510`）有硬校验：

```java
        if (certificates.size() == 1 &&
                certificates.iterator().next().getType() == SSLHostConfigCertificate.Type.UNDEFINED ||
                certificate.getType() == SSLHostConfigCertificate.Type.UNDEFINED) {
            // Invalid config
            throw new IllegalArgumentException(sm.getString("sslHostConfig.certificate.notype"));
        }
```

规则是「**多于一张证书时，任何一张都不允许是 `UNDEFINED`**」。只配一张时 `registerDefaultCertificate()` 会补一个 `Type.UNDEFINED` 的默认证书；一旦你加了第二张却没给每张写 `type`，连接器直接启动失败。这就是「单证书正常、加 EC 证书后起不来」的标准成因。

**`want` 与 `required` 的差异不在 HTTP 状态码上**。`required`（REQUIRED）下校验失败发生在**握手期**，客户端看到的是 TLS 层错误，拿不到任何 HTTP 响应；`want`（OPTIONAL）下握手成功，若客户端没发证书，认证层看到的是**空证书链**，结果是不匹配受保护约束 → 由 `SSLAuthenticator` 走 401，而不是 400/403。把它描述成「400 还是 403」的差异是错的；而且别忘了 TLS 1.3 + 无后握手认证时 `want` 本身就不可兑现（见上文告警分支）。

**已废弃 / 不存在的属性**。`allowSafeRenegotiation`（以及 `useSSLEngine`、`SSLProtocol` 这些 APR 侧名字）在 11 的 `SSLHostConfig` / `AbstractHttp11Protocol` 里已无对应字段——全树检索只剩 `insecureRenegotiation`（`:301`，OpenSSL 专有）与 `tls13RenegotiationAvailable`（`:123`，只读探测结果，不是配置开关）。`DEFAULT_TLS_CIPHERS` 也已 `@deprecated`，改用 `DEFAULT_TLS_CIPHERS_12`。配了不报错但也不生效的属性是危险信号，因为 11 的默认风格是**拼错就拒绝启动**，静默忽略的反而是历史遗留名。

**`APR` 相关的一切**。`docs/CS/Framework/Tomcat/Connector.md` 的 `## APR` 一节描述的连接器后端已不存在；同一段配置在 11 下要么被忽略，要么直接报错。参考 `docs/CS/Framework/Tomcat/Version_Migration.md`。

**OpenSSL 的「检查不到实现」路径**。若 native 库缺失，`getImplementedProtocols()` / `getImplementedCiphers()` 返回空集，`getEnabled()` 会「用配置值硬撑」（`SSLUtilBase.java` 中 `implemented.isEmpty()` 分支），错误推迟到实际使用时才炸。排障时先确认 provider 是否真的加载成功，再看套件名。

**改证书文件不等于生效**。`reloadSslHostConfigs()` 是显式动作；同时 `TLSCertificateReloadListener` 只做临期告警，不会替你换证书。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Security](/docs/CS/Framework/Tomcat/Security.md)
- [HTTP/2](/docs/CS/Framework/Tomcat/HTTP2.md)
- [Valve](/docs/CS/Framework/Tomcat/Valve.md)
- [WebSocket](/docs/CS/Framework/Tomcat/WebSocket.md)

## References

- [Tomcat 11 Configuration: HTTP Adapter](https://tomcat.apache.org/tomcat-11.0-doc/config/http.html)
- [Tomcat SSL/TLS Configuration How-To](https://tomcat.apache.org/tomcat-11.0-doc/ssl-howto.html)
- [Apache Tomcat Native library](https://tomcat.apache.org/native-doc/)
- [Java Secure Socket Extension (JSSE) Reference Guide](https://docs.oracle.com/en/java/javase/21/security/java-secure-socket-extension-jsse-reference-guide.html)
- [RFC 6066: TLS Extensions](https://www.rfc-editor.org/rfc/rfc6066)
- [RFC 8446: The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446)
