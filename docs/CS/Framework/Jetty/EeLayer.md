## Introduction

Jetty 12 把 Jakarta EE 支持整层拆成独立模块，动机不是打包整洁，而是一条硬需求：**同一个 JVM、同一个 `Server` 要能同时承载 Servlet 6.0（EE 10）与 Servlet 6.1（EE 11）的应用**，而这两套 API 的 Java 包名完全相同、类却互不兼容。要办到这件事，核心就不能依赖任何 `jakarta.servlet` 类型；一旦 `org.eclipse.jetty.server` import 了 `HttpServletRequest`，核心就永久被钉死在某一个 EE 版本上。于是 Jetty 12 的核心只剩三件事：`Request`/`Response`/`Callback` 契约、`Handler` 链、`Content.Source`/`Content.Sink` 读写模型；EE 语义全部外推到 `jetty-ee10-*` / `jetty-ee11-*`，靠**覆写一个挂载点** `wrapRequest` + **一个可复用状态机** `ServletChannel` + **双向适配器**嫁接回核心。这篇按源码顺序拆开这一层，所有结论标注相对 `/tmp/src/tree/` 的路径与行号（Jetty 12.1.14）。

> [!NOTE]
> 本镜像含 `jetty-server`、`jetty-security`、`jetty-ee10-servlet`、`jetty-ee10-webapp`、`jetty-ee10-annotations`、`jetty-ee11-servlet`，**不含 ee8 层与 ee11-webapp**，涉及它们的结论一律不外推。

## module-info as an architectural assertion

拆分靠不住口头约定，Jetty 把它写进 JPMS 描述符，使「核心不许看见 Servlet」成为**编译失败级别**的约束。

| 模块 | requires transitive | 有 jakarta.servlet 吗 |
| :--- | :--- | :--- |
| `jetty-server-12.1.14/module-info.java:16-18` | `org.eclipse.jetty.http`、`org.slf4j` | **无** |
| `jetty-security-12.1.14/module-info.java:15-17` | `org.eclipse.jetty.server`、`org.eclipse.jetty.util` | **无** |
| `jetty-ee10-servlet-12.1.14/module-info.java:19-24` | `jakarta.servlet`、`org.eclipse.jetty.server`、`org.eclipse.jetty.security`、`org.eclipse.jetty.session` | 有 |
| `jetty-ee11-servlet-12.1.14/module-info.java` | 与 ee10 **逐条相同**（模块名 `org.eclipse.jetty.ee11.servlet`） | 有 |

核心侧（`jetty-server-12.1.14/module-info.java`）：

```java
module org.eclipse.jetty.server
{
    requires transitive org.eclipse.jetty.http;
    requires transitive org.slf4j;
```

EE 侧（`jetty-ee10-servlet-12.1.14/module-info.java`）依赖方向是反的——**EE 层单向依赖核心**，核心不知道 EE 存在：

```java
module org.eclipse.jetty.ee10.servlet
{
    requires org.slf4j;

    requires transitive jakarta.servlet;
    requires transitive org.eclipse.jetty.server;
    requires transitive org.eclipse.jetty.security;
    requires transitive org.eclipse.jetty.session;
```

值得注意的一点：ee10 与 ee11 的 module-info 都写 `requires transitive jakarta.servlet`，**被依赖的模块名是同一个**。所以「两套 EE 并存」在 classpath 上靠 Jetty 自身包名（`ee10.*` vs `ee11.*`）隔离成立，而在单一 JPMS layer 里两份 `jakarta.servlet` 不可能共存——要么分层加载，要么把 API 交给每个 webapp 的类加载器各自提供。这是 EE 并存机制真正的约束来源，比「包名不同」更值得记住。

## Core contract Request Response Callback

EE 层嫁接的目标物是这三个类型，它们不带任何 Servlet 词汇：

```java
public interface Request extends Attributes, Content.Source       // jetty-server-12.1.14/.../Request.java:144
public interface Response extends Content.Sink                    // jetty-server-12.1.14/.../Response.java:57

@FunctionalInterface                                              // jetty-server-12.1.14/.../Request.java:791
interface Handler { boolean handle(Request request, Response response, Callback callback) throws Exception; }
```

`Request extends Attributes` 给出了嫁接用的「寄生面」：EE 层不需要改核心签名，只把自己的对象塞进 `Attributes`（以及连接级 `Components` 缓存），下游再取回来。`Content.Source`/`Content.Sink` 则把「读请求体 / 写响应体」统一成异步 chunk 模型——`ServletInputStream` 与 `ServletOutputStream` 最后必须被适配到它上面（见 [ContentModel.md](/docs/CS/Framework/Jetty/ContentModel.md)）。

## wrapRequest is the graft point

Jetty 12 没有在核心链后面「挂一段 Servlet 流程」，而是**覆写 `ContextHandler` 的一个抽象挂载点**：

```java
public class ServletContextHandler extends ContextHandler      // ee10/servlet/ServletContextHandler.java:133
                                     // 核心基类 server/handler/ContextHandler.java:79
```

核心 `ContextHandler.wrapRequest` 的语义是「把裸 `Request` 包装成本 context 的 `ContextRequest`」。`ServletContextHandler` 覆写它（`ee10/servlet/ServletContextHandler.java:1161-1196`，原样摘录）：

```java
    @Override
    protected ContextRequest wrapRequest(Request request, Response response)
    {
        String decodedPathInContext;
        MatchedResource<ServletHandler.MappedServlet> matchedResource;

        // Need to ask directly to the Context for the pathInContext, rather than using
        // Request.getPathInContext(), as the request is not yet wrapped in this Context.
        decodedPathInContext = URIUtil.decodePath(getContext().getPathInContext(request.getHttpURI().getCanonicalPath()));
        matchedResource = _servletHandler.getMatchedServlet(decodedPathInContext);

        if (matchedResource == null)
            return wrapNoServlet(request, response);
        ServletHandler.MappedServlet mappedServlet = matchedResource.getResource();
        if (mappedServlet == null)
            return wrapNoServlet(request, response);

        // Get a servlet request, possibly from a cached version in the channel attributes.
        Attributes cache = request.getComponents().getCache();
        Object cachedChannel = cache.getAttribute(ServletChannel.class.getName());
        ServletChannel servletChannel;
        if (cachedChannel instanceof ServletChannel sc && sc.getContext() == getContext() && !sc.isAborted())
        {
            servletChannel = sc;
        }
        else
        {
            servletChannel = new ServletChannel(this, request);
            cache.setAttribute(ServletChannel.class.getName(), servletChannel);
        }

        ServletContextRequest servletContextRequest = newServletContextRequest(servletChannel, request, response, decodedPathInContext, matchedResource);
        servletChannel.associate(servletContextRequest);
        Request.addCompletionListener(servletContextRequest, servletChannel::recycle);
        return servletContextRequest;
    }

    private ContextRequest wrapNoServlet(Request request, Response response)
    {
        Handler next = getServletHandler().getHandler();
        if (next == null)
            return null;
        return super.wrapRequest(request, response);
    }
```

四个要点：

1. **Servlet 映射失败即退回核心链**。`wrapNoServlet()`（`:1198`）在还有下一跳时调 `super.wrapRequest(...)`，也就是走普通 `ContextHandler` 语义，请求继续交给核心 `Handler` 处理，`ServletChannel` 根本不会被创建。这正是 Jetty 12 允许「核心 Handler 与 Servlet 混排在同一 context」的机制根源——不是靠特殊分支，而是**Servlet 化只是一个可选的包装**。
2. **`ServletChannel` 缓存在连接级 `Components` 里**（`:1179-1190`，key 是类名字符串），并且复用前校验两件事：`sc.getContext() == getContext()`（同一 channel 不能跨 context 复用）与 `!sc.isAborted()`。
3. **`recycle` 由完成监听器驱动**（`:1194`）：`Request.addCompletionListener(..., servletChannel::recycle)`。这一行是「channel 跨请求复用」生命周期的另一半，与下面的 `associate` 成对。
4. 类注释本身自嘲命名（`ServletContextHandler.java:128-130`）：本该叫 `ServletContext`，但会与 `jakarta.servlet.ServletContext` 混淆。

## How ServletHandler recovers ServletChannel

`ServletHandler` 是核心 `Handler.Wrapper`（`ee10/servlet/ServletHandler.java:86`），它的 `handle` 只做「取回 channel 并驱动状态机」：

```java
    public boolean handle(Request request, Response response, Callback callback) throws Exception   // :458-475
    {
        // We have a ServletContextRequest only when an enclosing ServletContextHandler matched a Servlet
        ServletChannel servletChannel = Request.get(request, ServletContextRequest.class, ServletContextRequest::getServletChannel);
        if (servletChannel != null)
        {
            ...
            // But request, response and/or callback may have been wrapped after the ServletContextHandler, so update the channel.
            servletChannel.associate(request, response, callback);
            servletChannel.handle();
            return true;
        }

        // Otherwise, there is no matching servlet so we pass to our next handler (if any)
        return super.handle(request, response, callback);
    }
```

`associate(request, response, callback)` 不是冗余调用：`wrapRequest` 时挂进去的是当时的三元组，而**中间任何 handler 都可能重新包装** `request`/`response`/`callback`（典型是 gzip、统计、安全相关的 wrapper），所以真正派发前要用最新的那一份覆盖。注释把这件事说得很直白。取不到 channel 时 `super.handle` 继续核心链——与 `wrapNoServlet` 呼应，形成双保险。

## ServletChannel and four orthogonal states

`ServletChannel` **不 implements 任何核心接口**（`ee10/servlet/ServletChannel.java:76`），它不是 handler，而是「一个连接的 Servlet 语义推进器」。类注释（`:58-73`）明确本类在同一连接的多次请求之间复用，靠 `recycle`/`associate` 成对切换；`handle()`（`:417` 起）是一个 `while` 循环，反复从状态机取下一个 `Action` 并执行，直到 `WAIT` / `TERMINATED`。

状态全在 `ServletChannelState.java`，关键是它用了**四个互相独立的维度**而不是一个 `state` 变量：

`Action`（`:166-179`）——循环每次迭代的输出：

```java
    public enum Action
    {
        DISPATCH,         // handle a normal request dispatch
        ASYNC_DISPATCH,   // handle an async request dispatch
        SEND_ERROR,       // Generate an error page or error dispatch
        ASYNC_ERROR,      // handle an async error
        ASYNC_TIMEOUT,    // call asyncContext onTimeout
        WRITE_CALLBACK,   // handle an IO write callback
        READ_CALLBACK,    // handle an IO read callback
        UPGRADE,         // Complete the response by closing output
        COMPLETE,         // Complete the response by closing output
        TERMINATED,       // No further actions
        WAIT,             // Wait for further events
    }
```

`State`（`:59-69`，含源码里的 ASCII 图 `IDLE ↔ HANDLING → WAITING → WOKEN`，另有 `UPGRADED`）描述**线程此刻在不在处理这个请求**：

```java
    public enum State
    {
        IDLE,        // Idle request
        HANDLING,    // Request dispatched to filter/servlet or Async IO callback
        WAITING,     // Suspended and waiting
        WOKEN,       // Dispatch to handle from ASYNC_WAIT
        UPGRADED     // Request upgraded the connection
    }
```

`RequestState`（`:86-97`）描述 Servlet 规范生命周期里的阶段：`BLOCKING / ERRORING / ASYNC / DISPATCH / EXPIRE / EXPIRING / UPGRADING / COMPLETE / COMPLETING / COMPLETED`。`InputState`（`:129-133`）`IDLE / UNREADY / READY`，`OutputState`（`:152-158`）`IDLE / OPEN / COMPLETED / ABORTED`。

为什么要四个维度：Servlet 语义里「线程是否在跑」「请求是否已 `startAsync`」「输入是否已注册 demand」「输出是否已 close」是**彼此可任意组合**的。例如 `State = IDLE`（线程已退出 `service()`）而 `RequestState = ASYNC`、`OutputState = OPEN` 是合法组合（异步等待中），而 `State = HANDLING` + `InputState = UNREADY` + `RequestState = BLOCKING` 则是阻塞读期间。压成单一枚举需要约 4×10×3×4 个组合值，且转换条件横跨多个维度、写出来必然漏。拆开之后每个维度的迁移都是局部的，`Action` 只是四者当前的**派生结论**——这就是 `handle()` 能用一个平铺 `while` 循环表达全部规范分支的原因。

`AsyncContextState` 是这条链的对外门面：`public class AsyncContextState implements AsyncContext`（`:28`），内部只握着一个 `volatile ServletChannelState _state`（`:30`），`complete()`→`state().complete()`（`:59-62`）、`dispatch(path)`→`state().dispatch(null, path)`（`:84-87`）、`addListener`→`state().addListener`（`:53-56`）、`setTimeout`→`state().setTimeout`（`:129-131`）。**规范 API 与状态机之间没有第二套状态**，应用线程与容器线程看到的永远是同一个 `ServletChannelState`。

## Bidirectional adapters

EE 层要同时把核心翻译成 Servlet，又把 Servlet 翻译回核心，两个方向各有四个位置：

| 方向 | 类 | 声明 | 位置 |
| :--- | :--- | :--- | :--- |
| 核心 → Servlet | `ServletContextRequest` | `extends ContextRequest implements ServletContextHandler.ServletRequestInfo, Request.ServeAs` | `ee10/servlet/ServletContextRequest.java:60` |
| 核心 → Servlet | `ServletApiRequest` | `implements HttpServletRequest` | `ee10/servlet/ServletApiRequest.java:110` |
| 核心 → Servlet | `HttpInput` | `extends ServletInputStream` | `ee10/servlet/HttpInput.java:36` |
| 核心 → Servlet | `HttpOutput` | `extends ServletOutputStream` | `ee10/servlet/HttpOutput.java:55` |
| Servlet → 核心 | `ServletCoreRequest` | `implements Request`，另有 `static Request wrap(HttpServletRequest)` | `ee10/servlet/ServletCoreRequest.java:61,63` |

反向适配器容易被忽略，但它解释了一个真实问题：**filter 或 servlet 里拿到的是 `HttpServletRequest`，可它要继续驱动核心 handler 怎么办**。`ServletCoreRequest.wrap(HttpServletRequest)` 就是为此存在，调用点在 `ServletApiRequest.java:281,300` 与 `ResourceServlet.java:558`（后者配合 `ServletCoreResponse.wrap`）。也就是说 `include`/`forward` 以及非 servlet 资源（静态文件）派发时，Servlet 层的对象被剥回核心三元组，**直接复用核心 handler，而不用绕回连接器**。这是「混排」能力的第二块拼图：正向让核心请求能被 servlet 处理，反向让 servlet 请求能被核心处理。

## Internal handler chain built by relinkHandlers

`ServletContextHandler` 内部固定要串 session → security → servlet 三段，但用户可能随时 `setSessionHandler(null)` 或插入自定义 handler，所以顺序不是硬编码而是**每次重链**。`relinkHandlers()`（`ee10/servlet/ServletContextHandler.java:1000-1046`）的三段是同构的：从 `this` 出发，沿 `getHandler()` 向下找到链尾 `Singleton`（遇到已知的下一段类型就停），再 `doSetHandler` 挂上去：

```java
        // link session handler
        if (getSessionHandler() != null)
        {
            while (!(handler.getHandler() instanceof SessionHandler) &&
                !(handler.getHandler() instanceof SecurityHandler) &&
                !(handler.getHandler() instanceof ServletHandler) &&
                handler.getHandler() instanceof Singleton wrapped)
            {
                handler = wrapped;
            }

            if (handler.getHandler() != _sessionHandler)
                doSetHandler(handler, _sessionHandler);
            handler = _sessionHandler;
        }
```

`doSetHandler(Singleton, Handler)`（`:992-998`）的意义是「挂到链尾而不是挂到我头上」——`wrapper == this` 时才用 `super.setHandler`。也正因此，`setHandler` 是个危险入口，它被覆写成分派器（`:974-990`）：识别出 `SessionHandler`/`SecurityHandler`/`ServletHandler` 就转给对应的 `set*Handler`，否则打 WARN 后重链：

```java
            if (handler != null)
                LOG.warn("ServletContextHandler.setHandler should not be called directly. Use insertHandler or setSessionHandler etc.");
```

结论：往 context 里插自定义 handler 用 `insertHandler`，不要用 `setHandler`——后者会静默改掉链头，把 session/security 甩到一边。

## Security and session de-Servlet-ized

如果只有 servlet 层被拆出去，而 security/session 仍依赖 `jakarta.servlet`，核心依然装不了纯核心应用。Jetty 把这两件事也搬到核心侧：

- **安全**：`jetty-security-12.1.14/module-info.java:15-17` 无 `jakarta.servlet`。`Constraint` 在核心是 **interface**（`security/Constraint.java:33`），内部枚举 `Authorization`（`:43` 起，`FORBIDDEN`/`ALLOWED`/`ANY_USER`/`KNOWN_ROLE`…）与 `Transport`（`:102`），方法 `getRoles()`（`:113`）、静态 `combine(...)`（`:283-285`）。`SecurityHandler` 是 `abstract extends Handler.Wrapper implements Configuration`（`security/SecurityHandler.java:68`），无约束时以 `Constraint.ALLOWED` 兜底（`:489`），子类 `PathMapped`（`:798`）/`PathMethodMapped`（`:963`）。`SecurityHandler.java:769-776` 的 javadoc 示例是「核心侧配置约束」的直接写法：

  ```java
  handler.put("/*", Constraint.combine(Constraint.Authorization.FORBIDDEN, Constraint.Transport.SECURE_TRANSPORT));
  ```

  Servlet 的 `<security-constraint>` XML 语义由 `ee10/servlet/security/ConstraintSecurityHandler.java:61` 适配，`:444` 注释自嘲它「implements the bizarre Jakarta Servlet Spec section 13.8.1」——**规范里那些反直觉的 URL pattern / role 合并规则被刻意隔离在这一层**，核心只见 `Constraint`。
- **会话**：核心契约 `server/Session.java:29` `interface Session extends Attributes`，配 `Session.API` 包装协议（`:41-47`）。EE 侧实现 `ee10/servlet/SessionHandler.java:53` `extends AbstractSessionManager implements Handler.Singleton`，`CookieConfig`（`:107`）、`ServletSessionApi implements HttpSession, Session.API`（`:278`）、`NonServletSessionRequest extends Request.Wrapper`（`:722`）。最后一类名字本身就是这篇主题的注脚：**同一段会话既服务 `HttpSession` 也服务非 Servlet 请求**。

## How ee10 and ee11 coexist

镜像里 `jetty-ee11-servlet-12.1.14/org/eclipse/jetty/ee11/servlet/` 是 ee10 的**完整平行镜像**：50 个 `.java` 与 ee10 同名一一对应（`ServletContextHandler.java` 的 `wrapRequest` 与构造器签名相同，见 ee11 `:248,253`）。隔离是三重的：

| 维度 | ee10 | ee11 |
| :--- | :--- | :--- |
| Maven groupId | `org.eclipse.jetty.ee10` | `org.eclipse.jetty.ee11` |
| Java 包名 | `org.eclipse.jetty.ee10.servlet` | `org.eclipse.jetty.ee11.servlet` |
| JPMS 模块名 | `org.eclipse.jetty.ee10.servlet` | `org.eclipse.jetty.ee11.servlet` |
| `Bundle-Version` | `12.1.14` | `12.1.14` |
| EE API | `jakarta.servlet`（Servlet 6.0） | `jakarta.servlet`（Servlet 6.1，**包名相同**） |

因为 Jetty 自己的类不共用包名，两套 EE 层可以在同一 classpath 上同时存在、共用同一份核心；`ee10.ServletContextHandler` 与 `ee11.ServletContextHandler` 是两个毫无继承关系的类，各自持有各自的 `ServletChannel`/`ServletChannelState`。同一 `Server` 挂两套 EE 应用的正确写法思路（**核心与 EE 之间没有任何 SPI 自动装配**，全靠显式装配）：

```java
Server server = new Server(8080);

org.eclipse.jetty.ee10.servlet.ServletContextHandler ee10 =
        new org.eclipse.jetty.ee10.servlet.ServletContextHandler("/ee10",
                org.eclipse.jetty.ee10.servlet.ServletContextHandler.SESSIONS
                        | org.eclipse.jetty.ee10.servlet.ServletContextHandler.SECURITY);

org.eclipse.jetty.ee11.servlet.ServletContextHandler ee11 =
        new org.eclipse.jetty.ee11.servlet.ServletContextHandler("/ee11",
                org.eclipse.jetty.ee11.servlet.ServletContextHandler.SESSIONS
                        | org.eclipse.jetty.ee11.servlet.ServletContextHandler.SECURITY);

// 两个 EE context 与纯核心 handler 平铺在同一顶层 handler 下，由核心按 contextPath 选择
server.setHandler(HandlerSequence.of(ee10, ee11, new MyCoreHandler()));
```

要点是**每个 EE context 自带一整套 EE 层类**（含它自己的 `ServletChannel`），因此不存在跨版本共享的 Servlet 语义对象；跨 context 只共享连接、线程与 buffer。上面 `ee11` 侧的构造器形态取自 ee11 `ServletContextHandler.java:248,253` 的同签名镜像；`HandlerSequence.of` 只是示意「用核心 handler 组合两者」，具体装配 API 以核心页 [Connector.md](/docs/CS/Framework/Jetty/Connector.md) / [RequestFlow.md](/docs/CS/Framework/Jetty/RequestFlow.md) 为准。

## WAR deployment and pluggable configurators

`ee10/webapp/WebAppContext.java:87` `extends ServletContextHandler implements WebAppClassLoader.Context`——webapp 只是在 EE 挂载点上再加一层类加载器与 `WEB-INF` 语义。部署期行为由**配置器链**决定，而不是硬编码顺序：`Configuration.java:52`（接口，`webapp/Configuration.java`）+ `Configurations.java:61`（有序集合）。`WebAppContext()` 无参构造的默认链是 `new ErrorPageErrorHandler()` + `SESSIONS|SECURITY`（`:160-163`），带 `(String webApp, String contextPath)` 的构造在 `:169-173`。注解扫描（`@WebServlet` 等）不在 webapp 模块里，而在 `jetty-ee10-annotations`（`AnnotationConfiguration`、`WebServletAnnotationHandler` 等 21 类），它作为一个 `Configuration` 被插进同一条链——**这就是「配置器链」设计换到的可扩展性**：annotation、JSP、JNDI、plus 都是可插拔项。ee11 侧的 webapp 模块不在本镜像内，不做推断。

## Embedded usage vs Tomcat

Jetty 12 的嵌入式入口在 EE 层，且 12.1 起签名简化（`ee10/servlet/ServletContextHandler.java:250-253`）：**不再需要显式传 `Context` / `ServletContext`**。

```java
new ServletContextHandler(String contextPath)              // :250-253
new ServletContextHandler(String contextPath, int options) // :260，SESSIONS = 1, SECURITY = 2, NO_* = 0
```

| 关注点 | Jetty 12 EE 层 | Tomcat 内嵌 |
| :--- | :--- | :--- |
| 入口对象 | 核心 `Handler`（`ServletContextHandler` / `WebAppContext`） | Tomcat 对象 + `ContextConfig`/`addWebapp`，围绕 `Engine→Host→Context` 容器树 |
| 核心与规范的关系 | 编译期分离，核心无 `jakarta.servlet` | 不存在分离，Coyote 之上直接是 Servlet 容器 |
| 装配方式 | 无 SPI 自动装配，显式 `server.setHandler(...)` | 由 `Tomcat` 门面按容器树默认装配 |
| war 语义 | `Configuration`/`Configurations` 可插拔链 | `WebappLoader` + `DefaultWebXmlListener` 等内建流程 |
| 多 EE 版本并存 | ee10 / ee11 包名双隔离，同 JVM 可并存 | 单一 Servlet 规范版本，跨版本只能多 Tomcat 实例 |

Tomcat 侧的部署与容器树细节见 [Container.md](/docs/CS/Framework/Tomcat/Container.md) 与 [Deployment.md](/docs/CS/Framework/Tomcat/Deployment.md)。

## Blocking and async read-write strategies

Servlet API 表面同时允许阻塞 IO 与非阻塞 IO，而核心只有异步 `Content.Source`/`Content.Sink`。这一层靠三个 producer 抽象收口（同目录）：

| 类 | 位置 | 策略 |
| :--- | :--- | :--- |
| `ContentProducer` | `ee10/servlet/ContentProducer.java:21` | 接口，读端统一抽象 |
| `AsyncContentProducer` | `ee10/servlet/AsyncContentProducer.java:35` | `:258` 通过 `demand` 驱动，不阻塞线程 |
| `BlockingContentProducer` | `ee10/servlet/BlockingContentProducer.java:24` | `:96-126`：先试异步，拿不到再 `_semaphore.acquire()` |

`BlockingContentProducer.isReady()` 的实现值得看一眼，它直接暴露了语义差：

```java
    public boolean isReady()                                    // :135-137
    {
        boolean ready = available() > 0;
```

写端同理：`HttpOutput.java:238-255` 用 `Blocker.Callback` 把一次同步写「盖」在核心的异步写之上——同步 `write` 的线程 park，回调线程完成实际 flush。

配置项 `delayDispatchUntilContent` 已在 12.1.0 废弃，替代方案是核心 handler 而非布尔开关（`jetty-server-12.1.14/.../HttpConfiguration.java`）：

```java
     * @deprecated Use {@link org.eclipse.jetty.server.handler.EagerContentHandler} instead.
     */
    @Deprecated (forRemoval = true, since = "12.1.0")      // :371, :377
    public void setDelayDispatchUntilContent(boolean delay)
```

## Pitfalls

1. **`HttpInput.isReady()` 不等于规范意义上的「可以安全注册 demand」**。异步形态下它关联的是 `ServletChannelState.InputState`（`IDLE`/`UNREADY`/`READY`，见 `ServletChannelState.java:103-150` 的迁移图与注释），而阻塞形态（`BlockingContentProducer.java:135-137`）退化成 `available() > 0`。手写非阻塞读取时若绕过 `setReadListener` 直接 `read()`，`InputState` 会从 `READY` 被 `read()` 抢走内容（源码注释明说这条边），`ReadListener` 就再也不会被通知——表现为「有数据但回调不触发」。
2. **用 `setHandler` 插 handler**。`ServletContextHandler.setHandler`（`:974-990`）对未知类型只打 WARN 然后重链，结果是链头被替换、session/security 段错位。用 `insertHandler` 或 `setSessionHandler`/`setSecurityHandler`。
3. **忘了 `SESSIONS|SECURITY` option**。`new ServletContextHandler("/x")` 与 `new ServletContextHandler("/x", SESSIONS|SECURITY)`（`:250-260`）差的是整段 handler 是否存在；漏掉后 `@WebServlet`/`web.xml` 里的会话与约束配置**静默失效**，而不是报错。`WebAppContext` 的默认值在 `:160-163`。
4. **`ee10` 与 `ee11` 的类不可互换**。包名不同意味着 `org.eclipse.jetty.ee10.servlet.ServletContextHandler` 与 ee11 版没有共同父类，反射装配、XML 配置、DI 容器按类名注入的地方都要跟着版本走。
5. **以为存在自动装配**。核心与 EE 之间没有 SPI/service loader，`server.setHandler(...)` 必须自己调；同理**不要找 `JettyEmbedded` 之类的门面**——这个类名在 12.1.14 全树零命中。
6. **`ServletCoreRequest.wrap` 之后又去拿 `HttpServletRequest`**。反向适配器是为了让核心 handler 复用，剥皮后的对象再想转回 Servlet 语义必须走完整套正向包装，别缓存 `HttpServletRequest` 跨请求使用——`ServletChannel` 是按连接复用的，`recycle`（`ServletContextHandler.java:1194` 注册）会重置它的状态。

## Links

- [Jetty 12 架构与线程模型](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)
- [Servlet 规范](/docs/CS/Java/JDK/Servlet.md)

## References

- [Jetty 12 Extension Guide](https://jetty.org/docs/jetty/12/extension-guide/)
- [Jetty 12 Programming Guide](https://jetty.org/docs/jetty/12/programming-guide/)
- [Jakarta Servlet 6.0 Specification](https://jakarta.ee/specifications/servlet/6.0/)
- [Jakarta Servlet 6.1 Specification](https://jakarta.ee/specifications/servlet/6.1/)
