## Introduction

Servlet 是一种基于 Jakarta 技术的 Web 组件，由容器管理，用于生成动态内容。
与其他基于 Jakarta 技术的组件一样，servlet 是平台无关的 Java 类，它们被编译为平台中立的字节码，可以动态加载到支持 Jakarta 技术的 Web 服务器中运行。
容器（有时称为 servlet 引擎）是提供 servlet 功能的 Web 服务器扩展。
Servlet 通过 servlet 容器实现的请求/响应范式与 Web 客户端进行交互。

在功能上，servlet 提供了比通用网关接口（CGI）程序更高级别的抽象，但比 Jakarta Server Faces 等 Web 框架提供的抽象级别更低。

Servlet 与其他服务器扩展机制相比具有以下优势：

- 它们通常比 CGI 脚本快得多，因为使用了不同的进程模型。
- 它们使用一个被许多 Web 服务器支持的标准 API。
- 它们拥有 Java 编程语言的所有优势，包括易于开发和平台无关性。
- 它们可以访问 Java 平台可用的庞大 API 集合。

### Servlet Container

servlet container 是 Web 服务器或应用服务器的一部分，它提供发送请求和响应的网络服务，解码基于 MIME 的请求，并格式化基于 MIME 的响应。
servlet container 还通过其生命周期包含和管理 servlet。

servlet container 是一个复杂的系统。
然而，基本上 servlet container 为处理 servlet 请求做三件事：

- 创建请求对象，并用被调用 servlet 可能使用的信息填充它，例如参数、标头、cookies、查询字符串、URI 等。
  请求对象是 `javax.servlet.ServletRequest` 接口或 `javax.servlet.http.ServletRequest` 接口的实例。
- 创建响应对象，被调用的 servlet 使用该对象向 Web 客户端发送响应。
  响应对象是 `javax.servlet.ServletResponse` 接口或 `javax.servlet.http.ServletResponse` 接口的实例。
- 调用 servlet 的 service 方法，传递请求和响应对象。在这里，servlet 从请求对象读取值并写入响应对象。

servlet container 可以内置于宿主 Web 服务器中，也可以作为附加组件通过该服务器的本地扩展 API 安装到 Web 服务器中。
Servlet container 也可以内置于或可能安装到支持 Web 的应用服务器中。

所有 servlet container 必须支持 HTTP 作为请求和响应的协议，但也可以支持其他基于请求/响应的协议，如 HTTPS（基于 SSL 的 HTTP）。

## The Servlet Interface

Servlet 接口是 Java Servlet API 的核心抽象。
所有 servlet 要么直接实现此接口，或者更常见地，通过扩展实现该接口的类来实现。
Java Servlet API 中实现 Servlet 接口的两个类是 GenericServlet 和 HttpServlet。
在大多数情况下，开发者将扩展 HttpServlet 来实现他们的 servlet。

### Request Handling Methods

基本的 Servlet 接口定义了一个用于处理客户端请求的 service 方法。
对于 servlet container 路由到 servlet 实例的每个请求，都会调用此方法。
处理 Web 应用程序的并发请求通常要求 Web 开发者设计能够在 service 方法中同时处理多个线程执行的 servlet。
通常，Web 容器通过在多个线程上并发执行 service 方法来处理对同一 servlet 的并发请求。

```java
package javax.servlet;

public interface Servlet {
    public void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException;
}
```

HttpServlet 抽象子类在基本 Servlet 接口之上添加了额外的方法，这些方法由 HttpServlet 类中的 service 方法自动调用，以帮助处理基于 HTTP 的请求。
这些方法包括：

- doGet 用于处理 HTTP GET 请求
- doPost 用于处理 HTTP POST 请求
- doPut 用于处理 HTTP PUT 请求
- doDelete 用于处理 HTTP DELETE 请求
- doHead 用于处理 HTTP HEAD 请求
- doOptions 用于处理 HTTP OPTIONS 请求
- doTrace 用于处理 HTTP TRACE 请求

通常，在开发基于 HTTP 的 servlet 时，Servlet 开发者只需关注 doGet 和 doPost 方法。
其他方法被认为是供非常熟悉 HTTP 编程的程序员使用的。

参见 `doPost` override by [org.springframework.web.servlet.FrameworkServlet](/docs/CS/Framework/Spring/MVC.md?id=dispatch)

### Number of Instances

对于不在分布式环境中托管的 servlet（默认情况），servlet container 每个 servlet 声明只能使用一个实例。
然而，对于实现 SingleThreadModel 接口的 servlet，servlet container 可以实例化多个实例来处理繁重的请求负载，并将请求序列化到特定实例。

如果 servlet 作为部署描述符中标记为可分布式应用的一部分部署，则每个 Java 虚拟机每个 servlet 声明只能有一个实例。
但是，如果可分布式应用中的 servlet 实现了 SingleThreadModel 接口，则容器可以在容器的每个 JVM 中实例化该 servlet 的多个实例。

### Servlet Life Cycle

servlet 通过一个定义良好的生命周期进行管理，该生命周期定义了如何加载和实例化、如何初始化、如何处理客户端请求以及如何被停用。
这个生命周期在 API 中由 `jakarta.servlet.Servlet` 接口的 init、service 和 destroy 方法表达，所有 servlet 必须直接或通过 GenericServlet 或 HttpServlet 抽象类间接实现。

#### Loading and Instantiation

servlet container 负责加载和实例化 servlet。
**加载和实例化可以在容器启动时发生，或者延迟到容器确定需要 servlet 来处理请求时。**

当 servlet 引擎启动时，servlet container 必须定位所需的 servlet 类。
servlet container 使用正常的 Java 类加载设施加载 servlet 类。
加载可以来自本地文件系统、远程文件系统或其他网络服务。

加载 Servlet 类后，容器将其实例化以供使用。

#### Initialization

在 servlet 对象实例化后，容器必须在它可以处理客户端请求之前初始化 servlet。
初始化是为了让 servlet 能够读取持久配置数据、初始化昂贵资源（如基于 JDBC™ API 的连接）以及执行其他一次性活动。
容器通过调用 Servlet 接口的 init 方法来初始化 servlet 实例，传递一个唯一的（每个 servlet 声明）实现 ServletConfig 接口的对象。
这个配置对象允许 servlet 从 Web 应用的配置信息中访问名称-值初始化参数。
配置对象还允许 servlet 访问一个描述 servlet 运行时环境的对象（实现 ServletContext 接口）。

实现线程安全通常都是使用synchronized

#### Request Handling

在 servlet 正确初始化后，servlet container 可以使用它来处理客户端请求。
请求由 ServletRequest 类型的请求对象表示。
servlet 通过调用提供的 ServletResponse 类型对象的方法来填写对请求的响应。
这些对象作为参数传递给 Servlet 接口的 service 方法。
对于 HTTP 请求，容器提供的对象是 HttpServletRequest 和 HttpServletResponse 类型。

请注意，由 servlet container 投入服务的 servlet 实例在其生命周期中可能不会处理任何请求。

servlet container 可能通过 servlet 的 service 方法发送并发请求。
为了处理这些请求，应用开发者必须在 service 方法中为多线程并发处理做出充分安排。
强烈建议开发者**不要**同步 service 方法（或其调度的其他方法），因为这对性能有不利影响。

#### End of Service

servlet container 不需要在任何特定时间段内保持 servlet 的加载状态。
servlet 实例可以在 servlet container 中保持活动状态几毫秒、整个 servlet container 的生命周期（可能是数天、数月或数年），或介于两者之间的任何时间段。

当 servlet container 确定应将 servlet 从服务中移除时，它调用 Servlet 接口的 destroy 方法，以允许 servlet 释放其正在使用的任何资源并保存任何持久状态。
例如，当容器想要节省内存资源或正在关闭时，可能会这样做。

在 servlet container 调用 destroy 方法之前，它必须允许当前正在 servlet 的 service 方法中运行的任何线程完成执行，或超过服务器定义的时间限制。
一旦在 servlet 实例上调用了 destroy 方法，容器就不能再将其他请求路由到该 servlet 实例。
如果容器需要再次启用该 servlet，它必须使用该 servlet 类的新实例。

在 destroy 方法完成后，servlet container 必须释放 servlet 实例，使其符合垃圾回收的条件。

## The Request

请求对象封装了来自客户端请求的所有信息。
在 HTTP 协议中，这些信息通过 HTTP 标头和请求消息体从客户端传输到服务器。

每个请求对象仅在 servlet 的 service 方法范围内或过滤器的 doFilter 方法范围内有效，
除非为组件启用了异步处理并且在请求对象上调用了 startAsync 方法。
在发生异步处理的情况下，请求对象保持有效，直到在 AsyncContext 上调用了 complete 方法。
容器通常会回收请求对象，以避免创建请求对象的性能开销。
开发者必须注意，不建议在未调用 startAsync 的情况下，在上述范围之外维护对请求对象的引用，因为这可能导致不确定的结果。

当客户请求某个资源时，HTTP 服务器会用一个 ServletRequest 对象把客户的请求信息封
装起来，然后调用 Servlet 容器的 service 方法，Servlet 容器拿到请求后，根据请求的
URL 和 Servlet 的映射关系，找到相应的 Servlet，如果 Servlet 还没有被加载，就用反射
机制创建这个 Servlet，并调用 Servlet 的 init 方法来完成初始化，接着调用 Servlet 的
service 方法来处理请求，把 ServletResponse 对象返回给 HTTP 服务器，HTTP 服务器会
把响应发送给客户端

## Servlet Context

ServletContext 接口定义了 servlet 对其运行的 Web 应用的视图。
容器提供者负责在 servlet container 中提供 ServletContext 接口的实现。
使用 ServletContext 对象，servlet 可以记录事件、获取资源的 URL 引用，以及设置和存储上下文中其他 servlet 可以访问的属性。

每个部署到容器中的 Web 应用关联一个 ServletContext 接口的实例对象。
在容器分布在多个虚拟机上的情况下，每个 JVM 的 Web 应用都有一个 ServletContext 实例。

Servlet 规范里定义了ServletContext这个接口来对应一个 Web 应用。Web 应用部署好
后，Servlet 容器在启动时会加载 Web 应用，并为每个 Web 应用创建唯一的
ServletContext 对象。 一个 Web 应用可能有多个 Servlet，这些 Servlet 可以通过全局的 ServletContext 来共享数据，这些数据包
括 Web 应用的初始化参数、Web 应用目录下的文件资源等。由于 ServletContext 持有所
有 Servlet 实例，你还可以通过它来实现 Servlet 请求的转发

容器中未作为 Web 应用一部分部署的 servlet 隐式属于"默认"Web 应用，并拥有一个默认的 ServletContext。
在分布式容器中，默认的 ServletContext 是不可分布的，且只能存在于一个 JVM 中。

### Reloading Considerations

尽管不要求容器提供者实现用于简化开发的类重载方案，但任何此类实现必须确保所有 servlet 及其可能使用的类都在单个类加载器范围内加载。
这个要求是为了保证应用的行为符合开发者的预期。
作为开发辅助，容器应支持会话绑定监听器的完整通知语义，用于在类重载时监控会话终止。

前几代容器创建新的类加载器来加载 servlet，与用于加载其他 servlet 或 servlet 上下文中使用的类的类加载器不同。
这可能导致 servlet 上下文中的对象引用指向意外的类或对象，并导致意外行为。
这个要求是为了防止因按需生成新类加载器而引起的问题。

## The Response

响应对象封装了所有要从服务器返回给客户端的信息。
在 HTTP 协议中，这些信息通过 HTTP 标头或请求的消息体从服务器传输到客户端。

每个响应对象仅在 servlet 的 service 方法范围内或过滤器的 doFilter 方法范围内有效，除非为组件启用了关联请求对象的异步处理。
如果启动了关联请求的异步处理，则响应对象保持有效，直到在 AsyncContext 上调用了 complete 方法。
容器通常会回收响应对象，以避免创建响应对象的性能开销。
开发者必须注意，在未对相应请求调用 startAsync 的情况下，在上述范围之外维护对响应对象的引用可能导致非确定性行为。

### Buffering

允许（但不要求）servlet container 为了效率而缓冲输出到客户端的数据。
通常进行缓冲的服务器将其设为默认行为，但允许 servlet 指定缓冲参数。

### Closure of Response Object

当响应关闭时，容器必须立即将响应缓冲区中的所有剩余内容刷新到客户端。
以下事件表明 servlet 已满足请求，并且响应对象将被关闭：

- servlet 的 service 方法终止。
- 在 setContentLength 或 setContentLengthLong 方法中指定的内容量大于零且已写入响应。
- 调用了 sendError 方法。
- 调用了 sendRedirect 方法。
- 在 AsyncContext 上调用了 complete 方法。

## Filtering

过滤器是 Java 组件，允许在请求进入资源和响应离开资源时，动态转换负载和标头信息。

Java Servlet API 提供了用于过滤动态和静态内容的轻量级框架的类和方法。
它描述了如何在 Web 应用中配置过滤器，以及其实现的约定和语义。

过滤器是可重用的代码片段，可以转换 HTTP 请求、响应和标头信息的内容。
过滤器通常不像 servlet 那样创建响应或响应请求，而是修改或适配对资源的请求，以及修改或适配来自资源的响应。

过滤器可以作用于动态或静态内容（动态和静态内容称为 Web 资源）。
需要使用过滤器的开发者可用的功能类型包括：

- 在请求被调用之前访问资源。
- 在调用之前处理对资源的请求。
- 通过用自定义版本的请求对象包装请求来修改请求标头和数据。
- 通过提供自定义版本的响应对象来修改响应标头和数据。
- 在资源调用后拦截其调用。
- 以可指定的顺序对零个、一个或多个过滤器作用于一个 servlet、一组 servlet 或静态内容。

**过滤组件示例**

- 认证过滤器
- 日志记录和审计过滤器
- 图像转换过滤器
- 数据压缩过滤器
- 加密过滤器
- 标记化过滤器
- 触发资源访问事件的过滤器
- 转换 XML 内容的 XSL/T 过滤器
- MIME 类型链过滤器
- 缓存过滤器

应用开发者通过实现 `jakarta.servlet.Filter` 接口并提供不接受参数的公共构造函数来创建过滤器。
该类与构成 Web 应用的静态内容和 servlet 一起打包在 Web 归档中。
使用部署描述符中的 `<filter>` 元素声明过滤器。
通过定义部署描述符中的 `<filter-mapping>` 元素，可以配置调用一个过滤器或过滤器集合。
这是通过将过滤器映射到特定 servlet（按 servlet 的逻辑名称），或者通过将过滤器映射到 URL 模式来映射到一组 servlet 和静态内容资源。

### Filter Lifecycle

在部署 Web 应用之后，在请求导致容器访问 Web 资源之前，容器必须定位必须应用于该 Web 资源的过滤器列表，如下所述。
容器必须确保已为列表中的每个过滤器实例化了适当类的过滤器，并调用了它的 init(FilterConfig config) 方法。
过滤器可以抛出异常以指示它无法正常工作。
如果异常属于 UnavailableException 类型，容器可以检查异常的 isPermanent 属性，并可能选择稍后重试该过滤器。

每个 JVM 中，每个 `<filter>` 声明只实例化一个实例。
容器提供如过滤器的部署描述符中声明的过滤器配置、对 Web 应用的 ServletContext 的引用以及初始化参数集。

当容器接收到传入请求时，它获取列表中的第一个过滤器实例并调用其 `doFilter` 方法，传入 ServletRequest 和 ServletResponse，以及它将使用的 FilterChain 对象的引用。

过滤器的 `doFilter` 方法通常会按照以下模式或其子集实现：

1. 该方法检查请求的标头。
2. 该方法可以使用 ServletRequest 或 HttpServletRequest 的自定义实现来包装请求对象，以修改请求标头或数据。
3. 该方法可以使用 ServletResponse 或 HttpServletResponse 的自定义实现来包装传入其 `doFilter` 方法的响应对象，以修改响应标头或数据。
4. 过滤器可以调用过滤器链中的下一个实体。下一个实体可以是另一个过滤器，或者如果进行调用的过滤器是为此链配置的部署描述符中的最后一个过滤器，则下一个实体是目标 Web 资源。通过调用 FilterChain 对象上的 doFilter 方法，并传入调用时使用的请求和响应，或传入它可能创建的自定义包装版本，来影响下一个实体的调用。
   容器提供的过滤器链的 doFilter 方法实现必须定位过滤器链中的下一个实体并调用其 doFilter 方法，传入适当的请求和响应对象。
   或者，过滤器链可以通过不调用下一个实体来阻止请求，让过滤器负责填充响应对象。
   service 方法必须与应用于 servlet 的所有过滤器在同一个线程中运行。
5. 在调用链中的下一个过滤器之后，过滤器可以检查响应标头。
6. 或者，过滤器可能抛出异常以指示处理错误。如果过滤器在其 doFilter 处理期间抛出 UnavailableException，则容器不得尝试继续处理过滤器链。如果异常未标记为永久性，它可能选择稍后重试整个链。
7. 当链中的最后一个过滤器被调用后，访问的下一个实体是链末尾的目标 servlet 或资源。
8. 在容器将过滤器实例从服务中移除之前，容器必须首先调用过滤器的 destroy 方法，以使过滤器能够释放任何资源并执行其他清理操作。

### Wrapping Requests and Responses

过滤的核心概念是包装请求或响应的概念，以便它可以覆盖行为以执行过滤任务。
在此模型中，开发者不仅能够覆盖请求和响应对象上的现有方法，还能为链下游的过滤器或目标 Web 资源提供适合特定过滤任务的新 API。例如，开发者可能希望使用比输出流或 writer 更高级别的输出对象来扩展响应对象，例如允许 DOM 对象写回客户端的 API。

为了支持这种样式的过滤，容器必须满足以下要求：

- 当过滤器调用容器的过滤器链实现上的 doFilter 方法时，容器必须确保它传递给过滤器链中下一个实体（或者如果过滤器是链中的最后一个，则传递给目标 Web 资源）的请求和响应对象，与调用过滤器传入 doFilter 方法的对象相同。
- 当过滤器或 servlet 调用 RequestDispatcher.forward 或 RequestDispatcher.include 时，被调用的过滤器和/或 servlet 看到的请求和响应对象必须是：传入的相同包装对象；或传入对象的包装对象。
- 当使用 startAsync(ServletRequest, ServletResponse) 开始异步周期时，在 AsyncContext.dispatch() 之后由任何过滤器和/或 servlet 看到的请求和响应对象必须是：传入的相同包装对象；或传入对象的包装对象。

## Listeners

Spring 就实现了自己的监听器[ContextLoaderListener](/docs/CS/Framework/Spring/MVC.md?id=ContextLoaderListener)，来监听 ServletContext 的启动事件，
目的是当 Servlet 容器启动时，init 全局的ApplicationContext方便后续的WebApplicationContext使用

## Sessions

超文本传输协议（HTTP）在本质上是无状态的协议。
要构建有效的 Web 应用，必须将来自特定客户端的请求相互关联起来。
多年来已经发展出许多会话跟踪策略，但直接使用对程序员来说都很困难或麻烦。
本规范定义了一个简单的 HttpSession 接口，它允许 servlet container 使用多种方法中的任何一种来跟踪用户的会话，而无需应用开发者了解任何一种方法的细微差别。

https，加密后攻击者就拿不到sessionid了，另外CSRF也是一种防止session劫持的方式

### Session Tracking Mechanisms

#### Cookies

通过 HTTP cookies 进行会话跟踪是最常用的会话跟踪机制，并且所有 servlet container 都必须支持它。

容器向客户端发送一个 cookie。然后客户端在每次后续请求中向服务器返回该 cookie，明确地将该请求与会话关联起来。
会话跟踪 cookie 的标准名称必须是 JSESSIONID。
容器可以允许通过容器特定的配置来自定义会话跟踪 cookie 的名称。

所有 servlet container **必须**提供配置容器是否将会话跟踪 cookie 标记为 HttpOnly 的能力。
已建立的配置必须适用于所有尚未建立上下文特定配置的上下文。

如果 Web 应用为其会话跟踪 cookie 配置了自定义名称，则如果将会话 ID 编码到 URL 中（假设已启用 URL 重写），相同的自定义名称也将用作 URI 参数的名称。

#### SSL Sessions

安全套接字层（SSL），即 HTTPS 协议中使用的加密技术，具有内置机制，可以明确地将来自客户端的多个请求识别为同一会话的一部分。
servlet container 可以轻松使用此数据来定义会话。

#### URL Rewriting

URL 重写是会话跟踪的最低公分母。当客户端不接受 cookie 时，服务器可以使用 URL 重写作为会话跟踪的基础。URL 重写涉及将会话 ID 作为数据添加到 URL 路径中，容器解释该路径以将请求与会话关联起来。
会话 ID 必须作为路径参数编码在 URL 字符串中。参数名称必须是 jsessionid。以下是包含编码路径信息的 URL 示例：

```http
http://www.example.com/catalog/index.html;jsessionid=1234
```

URL 重写会在日志、书签、referer 标头、缓存的 HTML 和 URL 栏中暴露会话标识符。
在支持且适合使用 cookie 或 SSL 会话的情况下，不应使用 URL 重写作为会话跟踪机制。

#### Session Integrity

Web 容器必须能够在不支持使用 cookie 的客户端上处理 HTTP 请求时支持 HTTP 会话。
为了满足这一要求，Web 容器通常支持 URL 重写机制。

### Session Lifecycle

当会话只是预期会话且尚未建立时，它被认为是"新的"。
由于 HTTP 是基于请求-响应的协议，HTTP 会话在客户端"加入"它之前被认为是新的。
当会话跟踪信息返回到服务器指示会话已建立时，客户端加入一个会话。
在客户端加入会话之前，不能假定来自客户端的下一个请求将被识别为会话的一部分。

如果以下任一条件成立，则会话被视为"新的"：

- 客户端还不知道该会话
- 客户端选择不加入会话。

这些条件定义了 servlet container 无法将请求与先前的请求关联起来的情况。
应用开发者必须设计应用以处理客户端未加入、不能加入或不会加入会话的情况。

每个会话关联一个包含唯一标识符的字符串，称为 session id。
会话 ID 的值可以通过调用 `jakarta.servlet.http.HttpSession.getId()` 获取，并且可以在创建后通过调用 `jakarta.servlet.http.HttpServletRequest.changeSessionId()` 更改。

## Web Applications

Web 应用是构成 Web 服务器上完整应用的 servlet、HTML 页面、类和其他资源的集合。
Web 应用可以打包并在来自多个供应商的多个容器上运行。

servlet container 必须强制 Web 应用与 ServletContext 之间的一一对应关系。
ServletContext 对象为 servlet 提供其应用视图。

Web 应用可以使用标准 Java 归档工具打包和签名成 Web 归档（WAR）格式文件。
例如，问题跟踪应用可以分发给一个名为 issuetrack.war 的归档文件。

## Application Lifecycle Events

应用事件监听器是实现一个或多个 servlet 事件监听器接口的类。
它们在 Web 应用部署时在 Web 容器中实例化和注册。
它们由应用开发者提供在 WAR 中。

Servlet 事件监听器支持 ServletContext、HttpSession 和 ServletRequest 对象的状态更改事件通知。
Servlet 上下文监听器用于管理应用在 JVM 级别持有的资源或状态。
HTTP 会话监听器用于管理与来自同一客户端或用户对 Web 应用的系列请求相关的状态或资源。
Servlet 请求监听器用于管理 servlet 请求生命周期中的状态。
异步监听器用于管理超时和异步处理完成等异步事件。

可能有多个监听器类监听每种事件类型，并且应用开发者可以指定容器为每种事件类型调用监听器 bean 的顺序。

## ASync

AsyncContext req和res

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

## References

1. [Jakarta Servlet Specification 6.0](https://jakarta.ee/specifications/servlet/6.0/jakarta-servlet-spec-6.0.pdf)
