## Introduction

Tomcat 是少数在同一个三年窗口里同时改动了**四件事**的基础组件：包命名空间（`javax.*` → `jakarta.*`）、Java 运行时基线（8 → 11 → 17）、native I/O 层（APR/native connector 整体下线）、以及一个 HTTP/2 特性（server push）。这四件事彼此独立，却都落在同一批 API 与 `server.xml` 属性上。

后果是：**互联网上绝大多数 Tomcat 文章、书籍章节、StackOverflow 回答写于 8.5/9.0 时代**，其中关于「性能不够就上 APR」「`-ClientPoller` 线程」「SecurityManager policy 文件」「`maxParameterCount` 默认 10000」的叙述，今天在 11 上要么不成立，要么指向已经不存在的代码。它们不会报错，只会安静地误导——因为类名还在、属性名还在、只是语义或默认值变了。

本页面给整个 Tomcat 子树提供**版本坐标**：本库 [Connector](/docs/CS/Framework/Tomcat/Connector.md)、[threads](/docs/CS/Framework/Tomcat/threads.md) 等笔记停在 9.0/10.1 视角，读它们时必须知道哪些结论已经过期。因此本文同时充当**勘误表**（见「本库旧笔记的已知偏差」）。

事实基线：本地源码镜像 `tomcat-{catalina,coyote,util,websocket,jasper}-11.0.26`（Tomcat 11.0.26）。凡标注「源码证据」的结论都可按给出的路径复核；标不出来的一律来自官方版本映射页，并注明不确定性。**镜像里没有 `tomcat-cluster` 模块**，所以集群相关结论不做源码断言。

## Version line quick table

| 版本线 | Java 基线 | 平台代次与关键 spec | 命名空间 | connector 后端 | 本页关注点 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 8.5.x | 7+ | Servlet 3.1 / JSP 2.3 / EL 3.0（Java EE 8 前身） | `javax.*` | NIO / NIO2 / **APR-native** | BIO 已删；APR 仍是「高性能选项」；`Globals.IS_SECURITY_ENABLED` 满仓库 |
| 9.0.x | 8+ | Servlet 4.0 / JSP 2.3 / EL 3.0（Java EE 8） | `javax.*` | NIO / NIO2 / APR-native | 引入 HTTP/2 push（`PushBuilder`）；AJP 默认值收紧；仍是网上资料的主流假设 |
| 10.1.x | 11+ | Servlet 6.0 / JSP 3.1 / EL 5.0（Jakarta EE 10） | **`jakarta.*`** | NIO / NIO2（**APR-native 下线**） | 迁移目标代：换包名 + 换 Java 基线，应用侧改动最大 |
| 11.0.x | **17+** | Servlet 6.1 / Pages 4.0 / EL 6.0 / WebSocket 2.2 / Authentication 3.1 / Annotations 3.0（Jakarta EE 11） | `jakarta.*` | NIO / NIO2（纯 Java + JSSE/Java 自带 TLS） | **SecurityManager 支持整体移除**；push 移除；默认值继续收紧 |

维护状态（哪条线还在收 CVE、哪条已 EOL）**不写死在本页**，以官方 [Apache Tomcat Downloads](https://tomcat.apache.org/download.cgi) 为准（该页按版本线列出当前推荐版本）；spec 与版本线的对应关系以 [Which Version Do You Want?](https://tomcat.apache.org/whichversion.html) 为准。这两页会随发布节奏更新，抄进笔记必然过时。

Java 基线与 EE 代次的对应（17 / Servlet 6.1 / Pages 4.0 / EL 6.0 / WebSocket 2.2 / Authentication 3.1 / Annotations 3.0）来自官方版本映射页，与镜像目录 `tomcat-*-11.0.26` 一致。

JSP 侧的代次（Pages 4.0）落到实现上就是 Jasper 生成代码的行为约定，从 `.jsp` 到 Servlet 的编译链见 [Jasper](/docs/CS/Framework/Tomcat/Jasper.md)。

## The javax to jakarta watershed

这是唯一一条**不可绕过**的分水岭，其它破坏性变更都有临时兼容手段，这条没有。

### 10.0 and 10.1 are the migration target generation

EE 侧把 `jakarta.servlet.Servlet` 这类接口的**全限定类名**改了，而 Java 里类名同时是「类型身份」和「二进制契约」。Tomcat 10 的意义就是提供一份只认 `jakarta.*` 的容器实现：

- 10.0 是过渡版本（生命周期极短，官方建议直接上 10.1），10.1 才是 Jakarta EE 10 的正式载体。
- 9.0 的容器只认 `javax.*`，10.1 的容器只认 `jakarta.*`。**没有「同一个 Tomcat 同时支持两套命名空间」的模式**。

### Why 10.1 and 11 jars cannot be mixed

两层原因叠加，任何一层单独就足以致命：

1. **平台代次不同**：Servlet 6.0（10.1）与 Servlet 6.1（11）虽然都叫 `jakarta.servlet.*`，但 spec 版本与 SPI 有增量差异，容器 `catalina.jar` 与 `jakarta.servlet-api` 的代次必须配对。11 的容器加载 10.1 编译的 API jar 组合，属于跨代次混用。
2. **Tomcat 内部 API 二进制不兼容**：`org.apache.catalina.*` / `org.apache.coyote.*` / `org.apache.tomcat.util.*` 这些**非 spec 类**的签名在 10.1 → 11 之间变了（见下文源码证据）。凡是直接 import 内部类的容器扩展——自定义 `Valve`、`Realm`、`Loader`、`WebResourceRoot`、`ProtocolHandler`、`SessionListener`——重新编译时就会撞上 `NoSuchMethodError` / `NoClassDefFoundError`，而不是干净的编译错误。

判据很简单：**只要你的代码 import 了 `org.apache.catalina` 或 `org.apache.coyote`，就必须在目标 Tomcat 版本上重新编译并在目标容器上跑一遍全量集成测试**，「换个 jar 就行」在这里不成立。

### The migration tool is not in Tomcat trunk

把 `javax.*` 字节码改写成 `jakarta.*` 的工具是**独立构件** `org.apache.tomcat:jakartaee-migration`（仓库 [apache/tomcat-jakartaee-migration](https://github.com/apache/tomcat-jakartaee-migration)）：

- 它有**自己的版本号**，与 Tomcat 的 8.5/9.0/10.1/11.0 版本号**没有对应关系**。看到「Tomcat 迁移工具 11.x」这类说法就是混淆了两条版本线。
- 它是**离线改写**（对 WAR / JAR 做类引用重定位，也提供 webapp class loader 的运行时转换模式），不改变 Tomcat 本身的运行时依赖。
- 它只能处理**纯命名空间**替换：`javax.annotation` 与 `javax.crypto` / `javax.sql` / `javax.naming` 这些**属于 JDK 的包同名前缀**，需要它内部的规则区分（并非所有 `javax.` 都要迁）。凡是靠反射按字符串拿类名、或写在 SPI 配置文件 / TLD `uri` / `web.xml` 里的引用，工具改不到，必须人工过一遍。

## Breaking changes

每条给「旧写法 / 11 的现实 / 源码证据 / 迁移动作」四段。源码路径相对 `org/apache/`。

### SecurityManager support removed

- **旧写法**：旧笔记里成段的 `if (Globals.IS_SECURITY_ENABLED) { ... doPrivileged ... }` 分支、`catalina.policy` 文件、`-Djava.security.manager -Djava.security.policy==...` 启动方式。
- **11 的现实**：Tomcat 不再提供任何 SecurityManager 集成。相关分支连同 `PermissionCheck` 这套自定义权限检查抽象一起消失；容器代码路径不再做 `doPrivileged`。JDK 侧 Security Manager 本身也已在 JDK 17+ 被标记废弃（JEP 411），所以这不是 Tomcat 单方面动作。
- **源码证据**：全镜像 `grep -rln` 对 `IS_SECURITY_ENABLED`、`doPrivileged`、`PermissionCheck` **零命中**（覆盖 catalina / coyote / util / websocket / jasper 五棵树）。`catalina` 树里已不存在带该常量的 `Globals` 字段。
- **迁移动作**：删除 `catalina.policy` 与启动参数中的 `-Djava.security.manager`；依赖「用 policy 限制 webapp 文件访问」做隔离的系统要换方案——进程级（容器 / `namespace` / `cgroup`）、`SELinux`、或应用侧沙箱。**旧的 policy 文件在 11 上没有消费方，但也不会报错**，这是最危险的静默失效。

### APR native connector removed

- **旧写法**：`<Listener className="org.apache.catalina.core.AprLifecycleListener" SSLEngine="on"/>` + `<Connector protocol="org.apache.coyote.http11.Http11AprProtocol">`，并配合「并发高 / 需要原生 socket 就切 APR」的性能建议。
- **11 的现实**：APR 后端已不存在（10.1 起下线，11 里连残留都没有）。连接器只剩纯 Java 的 NIO / NIO2，TLS 走 JDK 自带 JSSE。`AprLifecycleListener` 这个类**还在**，但职责缩到只服务 OpenSSL/FIPS 配置：它的成员是 `FIPSMode`、`fipsModeActive`、以及「取 OpenSSL 版本串」，不再注册任何 connector 后端。
- **源码证据**：`Http11AprProtocol`、`AprEndpoint` 零命中；`catalina/core/AprLifecycleListener.java` 仍在（:49 类声明，:93-:115 为 `FIPSMode` 相关常量，:179 是「Get the installed OpenSSL version string」），:272 为 FIPS 初始化失败即 fatal。
- **迁移动作**：删掉 `<Connector protocol="...Http11AprProtocol">` 的显式指定（改成 `HTTP/1.1` 让默认 NIO 生效），否则启动即失败；把「性能不够上 APR」的容量预案换成 NIO 参数调优（`maxConnections` / `acceptCount` / 线程池，见 Connector 与 threads 两篇）；只有在**确实需要 OpenSSL/FIPS 证书栈**时才保留 `AprLifecycleListener`。

### HTTP/2 server push removed

- **旧写法**：`request.newPushBuilder().path("/app.css").push()`，或 `Http2PushBuilder`；教程里把 push 当成 HTTP/2 的默认福利。
- **11 现实**：Servlet 6.1 已删掉 `PushBuilder` API，浏览器侧也已放弃 push 语义（实际收益为负），Tomcat 不再实现。
- **源码证据**：镜像内 `PushBuilder` / `Http2PushBuilder` **零命中**；只剩 `FrameType.PUSH_PROMISE` 这个帧类型常量与 `StreamStateMachine` 里的分支残留——**协议层能识别这个帧不等于能发它**，这类「常量还在、能力没了」正是凭印象最容易写错的地方。
- **迁移动作**：push 改为 `103 Early Hints`、preload link、或直接把资源内联/合并；用 `grep -rn "newPushBuilder\|PushBuilder"` 扫源码，编译不过就是最直接的信号（这条属于会显式失败的变更，比 SecurityManager 幸运）。

### maxParameterCount default tightened

- **旧写法**：默认 `10000`，很多调优文章把它当「不用动的安全值」。
- **11 的现实**：`Connector` 的 `maxParameterCount` 默认是 **1000**。超出上限的参数**被静默丢弃**（不抛异常、不返回 4xx），只留一条 warn 日志。
- **源码证据**：`catalina/connector/Connector.java:251` → `protected int maxParameterCount = 1000;`，:528 / :538 为 getter / setter。**注意这是「sysctl 存在 ≠ 还生效」型陷阱的反面：属性还在、名字没变，只有默认值变了。**
- **迁移动作**：升级前搜「一次提交参数很多的场景」——批量表单、可重复 `name` 的复选框组、超长 query、把参数当 payload 的报表导出。有这些场景就在 `<Connector>` 上**显式**写 `maxParameterCount`，不要依赖默认；升级后重点看 `Parameters.parseParameters` 相关的 warn 日志。具体是哪一个小版本从 10000 改到 1000，请按对应版本线发布说明核对，本页不断言。

### SingleThreadModel fully gone

- **旧写法**：`implements SingleThreadModel` 当并发保护手段（老 Java EE 教程的常见建议）。
- **11 的现实**：该接口早在 Servlet 2.4 就被废弃，`jakarta.servlet` 已彻底移除，Tomcat 内部也无任何特判。
- **源码证据**：全镜像 `SingleThreadModel` **零命中**。
- **迁移动作**：删实现声明；需要串行化就在 Servlet 内部自己做锁，或者干脆把状态挪到 `HttpSession` / 外部存储。**更值得警惕的是它背后的模式**：任何依赖「容器帮我保证单实例串行」的隐式并发假设都要重新审视。

### WAR URL separator and FailedRequestFilter

- **旧写法**：WAR 在远程/嵌套 URL 里用 `war:file:/path/a.war*/WEB-INF/...` 或带 `^` 的旧分隔约定来定位资源；用 `FailedRequestFilter`（或 `RewriteValve`）把 404 转成 500，以便暴露部署失败原因。
- **11 的现实**：`^` 分隔约定已移除；`FailedRequestFilter` 这类工具类不复存在。部署失败的处理走 `Context` 状态与 `FailedContext` 路径。
- **源码证据**：`catalina/webresources/` 与 `core/StandardContext.java` 中对 `FailedRequestFilter` 与 `^` 分隔符 **零命中**。
- **迁移动作**：改用标准 `war:file:...*/` 形式访问嵌套资源；把「靠 500 暴露部署失败」的运维手段换成检查 `HostConfig` 部署日志与 Manager 应用状态。**注意**：`^` 在正则与 shell 里语义多，扫描时要按具体分隔符上下文确认，不要只看命中数。

### Internal API binary incompatibility

- **旧写法**：抄博客里的类图/继承链，或直接扩展内部类。
- **11 的现实**：11.0.x 与 10.1.x 在**非 spec 类**上二进制不兼容——既有 jakarta 平台代次差异，也有 Tomcat 自身内部类签名与继承层次变化。最直观的一例：`NioEndpoint` 的父类从 `AbstractJsseEndpoint` 变成了 `AbstractNetworkChannelEndpoint`，同时 `AbstractJsseEndpoint`、`SelectorPool` 两个类整体消失。
- **源码证据**：`tomcat/util/net/NioEndpoint.java:73` → `public class NioEndpoint extends AbstractNetworkChannelEndpoint<NioChannel,SocketChannel> {`；`tomcat/util/net/AbstractNetworkChannelEndpoint.java:31-32` → `extends AbstractEndpoint<S,U>`；`AbstractJsseEndpoint.java` 与 `SelectorPool.java` 在 `util/net/` 下不存在、全树零命中。
- **迁移动作**：容器扩展一律在目标版本重编译；把继承内部类改成**实现 spec 接口**（`ServletContainerInitializer`、`Filter`、`GenericServlet` 等）；确需内部 API 时锁死 Tomcat 小版本并把类图写进自己的构建校验。

### Cluster EncryptInterceptor

- **旧写法**：`<Cluster><Channel ...><Encrypter secretKey="..."/></Channel></Cluster>`，9.0/10.1 时代可跨版本混跑节点。
- **11 的现实**：复制消息的加密实现在 11 的某个小版本有**破坏性变更**（涉及密钥/算法与线上报文格式），跨小版本混跑集群节点可能出现解密失败而只报复制错误。**镜像里没有 `tomcat-cluster` 模块，本页无法给出源码证据，也不指定版本号**——必须按你实际使用的小版本发布说明逐条核对。
- **源码证据**：无（`EncryptInterceptor` 不在本镜像覆盖范围内）。诚实标注为待核对。
- **迁移动作**：升级前把集群节点视为**必须同进同退**的整体，避免 10.1 与 11 节点混跑复制组；升级后专门验证一次跨节点 session 复制与加解密（看 `EncryptInterceptor` 相关异常），并保留一条不含 `Encrypter` 的对照组快速定位问题来源。

## How to re-verify each claim

这一节是方法论，因为**「grep 不到」有三种完全不同的含义**，混起来用会得出反方向的结论。

### Mirror vs repository layout

本文用的本地镜像按 **Maven 源码构件**分模块：`tomcat-catalina-11.0.26`、`tomcat-coyote-11.0.26`、`tomcat-util-11.0.26`、`tomcat-websocket-11.0.26`、`tomcat-jasper-11.0.26`，模块根下直接是 `org/apache/...`（即本文所有 `util/net/...` 路径的完整形态是 `tomcat-coyote-11.0.26/org/apache/tomcat/util/net/...`）。

Tomcat 主干 Git 仓库布局不同：单一树、源码在 `java/` 前缀下、不分模块（`java/org/apache/catalina/...`），`conf/`、`bin/`、`webapps/`、`RELEASE-NOTES` 在仓库根。远程核对用分支而非 tag：

```bash
R=https://raw.githubusercontent.com/apache/tomcat/11.0.x/java
curl -sL -m 40 "$R/org/apache/tomcat/util/net/NioEndpoint.java" | grep -n "class NioEndpoint"
```

两点注意：判断文件是否存在不能只看 HTTP 状态码（缓存会给过期值），要看首行是不是 `<!DOCTYPE`；**spec 接口本身不在这个仓库里**（`jakarta.servlet.*` 来自 EE 平台的 API jar），所以「Servlet 6.1 删了 `PushBuilder`」这类断言要在 API jar 侧核，Tomcat 镜像只能证明**它没有实现**。

### Three meanings of zero hits

| 现象 | 含义 | 本例 | 后果 |
| :-- | :-- | :-- | :-- |
| 类、接口、属性**全无命中** | 真的删除了 | `Http11AprProtocol`、`SelectorPool`、`PushBuilder`、`IS_SECURITY_ENABLED` | 编译期或启动期就炸，**属于幸运的一档** |
| **常量或名字还在**，消费方没了 | 语义已死，名字是残留 | `FrameType.PUSH_PROMISE` 还在，但没有任何 push 实现；`AprLifecycleListener` 还在，但不再注册 connector | 最容易写错的一档：搜到符号就以为能力还在 |
| 属性名不变、**默认值变了** | 静默行为变更 | `maxParameterCount` 1000、`maxConnections` 8192 | 不报错、不失败，只在高负载或大批量参数时丢数据 |

反过来也成立：**存在 ≠ 仍是原语义**。同一份镜像里 `minSpareThreads` 的字段还在（:1435），但围绕它的 `prestartminSpareThreads` 开关已消失，所以「预热线程」这个动作需要重新确认由谁负责（:1450 的 setter 会直接调 `setCorePoolSize`）。

### Writing conventions for this subtree

引用 Tomcat 源码时写 `模块内相对路径:行号` + **明确版本号**（如 `tomcat-coyote-11.0.26` → `util/net/NioEndpoint.java:73`），并区分三种断言来源：源码证据 / 官方版本映射页 / 待核对。本文的「集群 EncryptInterceptor」就是最后一档——镜像不含 `tomcat-cluster`，所以既不写版本号也不写结论。这样做的目的是让下一次版本跳动时，只需要重跑一遍 grep 就能定位哪些句子要改，而不是重写整篇。



## Known drift in this vault

本表是本文对子树的直接贡献：**读下列笔记时把右列当作现状**。表中每一条旧说法都按给出的行号定位过，右列与「证据」均由 11.0.26 镜像逐条 grep 复核。

| 位置 | 笔记里的说法 | 11.0.26 现实 | 证据 |
| :-- | :-- | :-- | :-- |
| [Connector.md](/docs/CS/Framework/Tomcat/Connector.md) :74 / :127 / :432 | `class NioEndpoint extends AbstractJsseEndpoint<NioChannel,SocketChannel>` | 父类是 `AbstractNetworkChannelEndpoint<NioChannel,SocketChannel>`；`AbstractJsseEndpoint` 类已不存在 | `util/net/NioEndpoint.java:73`；全树零命中 |
| Connector.md :69 | `LimitLatch maxConnection = 10000` | `maxConnections` 默认 **8192**（`8 * 1024`）；10000 那个值属于已删的 APR 时代默认 | `util/net/AbstractEndpoint.java:1016` |
| Connector.md :103 | 线程名 `getName() + "-ClientPoller"` | 服务端 selector 线程名是 **`-Poller`**（`http-nio-8080-Poller`） | `util/net/NioEndpoint.java:541` |
| [threads.md](/docs/CS/Framework/Tomcat/threads.md) :43 | `if (prestartminSpareThreads) { ... }` | 该属性已删；`minSpareThreads`（默认 10）仍在，预热语义并入 setter 对 core pool 的调整 | `util/net/AbstractEndpoint.java:1435` 与 :1450；`prestartminSpareThreads` 零命中 |
| Connector.md :1579 / :1667 | `if (Globals.IS_SECURITY_ENABLED) { ... }` 分支 | 常量与整个 SecurityManager 路径都已移除，**这些分支在 11 源码里已无对应实现**；照抄会找不到符号 | 全镜像 `IS_SECURITY_ENABLED` / `doPrivileged` / `PermissionCheck` 零命中 |
| Connector.md :1703 起的 `## APR` 一节（及 :344 的 `// APR specific.`） | APR 用堆外内存 + `sendfile` 当性能预案 | 后端整体不存在，`AprLifecycleListener` 仅剩 FIPS/OpenSSL 职责（TLS.md 已另有一节说明） | `Http11AprProtocol` / `AprEndpoint` 零命中 |
| Connector.md :1351 | `StandardWrapperValve` 的注释提到「respecting … `SingleThreadModel` support」 | 接口已从 `jakarta.servlet` 删除，容器侧无任何特判；这条契约描述只剩历史意义 | 全镜像 `SingleThreadModel` 零命中 |

另有两条「本库暂无、但补笔记时别按旧资料加回来」的符号：`AbstractJsseEndpoint`（父类已被 `AbstractNetworkChannelEndpoint` 取代）与 `SelectorPool`（整体删除，旧类图里它是 NIO 阻塞读复用 selector 的关键部件）。当前 Tomcat 子树没有引用它们，列出只为防回归。

补充一条读法上的提醒：Connector.md 的继承链叙述本身是**理解设计**的好材料，不必改写成 11 的类名了事——但要知道今天按类名去 `grep` 或反射是找不到 `AbstractJsseEndpoint` 的。反过来，[Container](/docs/CS/Framework/Tomcat/Container.md)、[HTTP2](/docs/CS/Framework/Tomcat/HTTP2.md)、[Security](/docs/CS/Framework/Tomcat/Security.md)、[TLS](/docs/CS/Framework/Tomcat/TLS.md) 四篇已按 11.0.26 基线校准过，读它们不需要本表这类折扣。

## Upgrade checklist

### Dependency and bytecode scanning

1. 列出所有 jar/war，扫 `javax.servlet`、`javax.annotation`、`javax.el`、`javax.websocket`、`javax.security.auth.message`、`javax.servlet.jsp` 的**类路径引用**（含反射字符串、`META-INF/services`、TLD `uri`、`web.xml` 全限定类名）——工具改不到的正是这几处。
2. 纯命名空间替换用 `org.apache.tomcat:jakartaee-migration`（版本号自成一线，与 Tomcat 版本无关）；能改源码就从源码改，别长期依赖离线改写。
3. 凡是 import `org.apache.catalina` / `org.apache.coyote` / `org.apache.tomcat.util` 的模块（自定义 Valve、Realm、Loader、WebResourceRoot、ProtocolHandler、SessionListener、集群 DeltaDataSource 配置），**在目标 Tomcat 上重新编译**，然后按上文「内部 API 二进制不兼容」跑全量集成测试。
4. 确认构建与运行 JDK ≥ 17（`maven-compiler-plugin` 的 release、CI 镜像、`JAVA_HOME`）。

### server.xml and attributes

1. 删 `<Connector protocol="org.apache.coyote.http11.Http11AprProtocol">` 之类显式 APR 协议；`AprLifecycleListener` 只在需要 OpenSSL/FIPS 时保留。
2. **显式**设置 `maxParameterCount`（默认 1000），并搜一遍高参数量的表单与报表接口。
3. `minSpareThreads` 之外不要再指望 `prestartminSpareThreads`；线程池相关属性名以目标版本 Configuration Reference 为准逐条对齐。
4. 复核 AJP：`secret` 与 `allowedAttributes` 的默认值在新版本收紧（若不兼容的旧 httpd 对端仍在跑，会表现为「能连上但属性丢失 / 鉴权失败」），要么显式配置，要么按「去掉 AJP」的路线改用 mod_proxy_http 或 HTTP/2。
5. 移除任何 push 相关配置与代码，以及 `-Djava.security.manager` / `catalina.policy`。

### Logging JMX and operations

1. 旧 `catalina.policy` 与 SecurityManager 启动参数在 11 上**不会报错但完全无效**——把它们从启动脚本清掉，别让下一个人以为隔离还在。
2. JMX ObjectName、告警规则、监控面板里凡是嵌了 Tomcat 内部类名或线程名的（`-ClientPoller` 就是典型），要跟着改名后的现实更新；`getName()` 语义未变但拼装结果变了。
3. 集群 `EncryptInterceptor` 变更需按你所在小版本的发布说明核对；升级期间不要让两个版本线的节点混在同一个复制组。
4. 检查 Java 17 强封装带来的反射访问问题（`--add-opens` / `--add-exports` 只是过渡手段，根因多半是上面第 3 条那类内部 API 依赖）。

### Verification order

静态扫描 → 目标版本重编译 → 单元/集成 → 启动即失败项（APR 协议、`PushBuilder`、`SingleThreadModel`）→ **静默行为项**（`maxParameterCount` 截断、policy 文件失效、AJP 属性丢失）→ 集群与 session 复制 → 压测确认容量假设（不能再拿 APR 当预案）。**把静默项单独跑一遍**，因为它们不会让升级「失败」，只会让线上少数据。

## Why this page lives in the Tomcat subtree

因为它是**读子树内其它笔记的前置坐标**，不是「软件工程知识」。[Engineering](/docs/CS/SE/Engineering.md) 关心的是通用升级方法论与兼容性设计；而本文的每条结论都落在 Tomcat 的具体类名、具体属性默认值和具体镜像证据上，只有贴着子树写才能保持可复核。此外三条现实约束：

- 本库的 [Connector](/docs/CS/Framework/Tomcat/Connector.md)、[threads](/docs/CS/Framework/Tomcat/threads.md) 等页是**按旧版本源码摘写**的机制叙述，价值在「为什么这样设计」，不在「今天类名叫什么」。勘误表放在同一子树里，才能和被纠正的页面互相指认。
- 与 [Jetty](/docs/CS/Framework/Jetty/Jetty.md)、[Servlet](/docs/CS/Java/JDK/Servlet.md)、[Spring_Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md) 的关系是**同代次对照**：Jetty 12 用 EE10/EE11 双代次模块化解掉命名空间问题、Spring Boot 的版本与内嵌容器代次强绑定，两者都需要「Tomcat 的版本线怎么划分」这个公共坐标。命名空间这件事只有放在容器侧才讲得完整。
- 版本判断的**证据形态**（镜像 grep、零命中怎么解读、常量存在不等于能力存在）本身就是 Tomcat 源码阅读技能的一部分，放 SE 目录会丢掉可核对性。

## Links

- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [threads](/docs/CS/Framework/Tomcat/threads.md)
- [Servlet](/docs/CS/Java/JDK/Servlet.md)
- [HTTP2](/docs/CS/Framework/Tomcat/HTTP2.md)
- [Valve](/docs/CS/Framework/Tomcat/Valve.md)
- [TLS](/docs/CS/Framework/Tomcat/TLS.md)

## References

- [Apache Tomcat Downloads（各版本线当前推荐版本）](https://tomcat.apache.org/download.cgi)
- [Which Version of Apache Tomcat Do You Want?](https://tomcat.apache.org/whichversion.html)
- [Apache Tomcat Migration Guide](https://tomcat.apache.org/migration.html)
- [Apache Tomcat migration tool for Jakarta EE](https://github.com/apache/tomcat-jakartaee-migration)
- [Jakarta EE 11 Platform specifications](https://jakarta.ee/specifications/platform/11/)
- [JEP 411: Deprecate the Security Manager for Removal](https://openjdk.org/jeps/411)
