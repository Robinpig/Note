## Introduction

A servlet is a Jakarta technology-based web component, managed by a container, that generates dynamic content.
Like other Jakarta technology-based components, servlets are platform-independent Java classes that are compiled to platform-neutral byte code that can be loaded dynamically into and run by a Jakarta technology-enabled web server.
Containers, sometimes called servlet engines, are web server extensions that provide servlet functionality.
Servlets interact with web clients via a request/response paradigm implemented by the servlet container.

In functionality, servlets provide a higher level abstraction than Common Gateway Interface (CGI) programs but a lower level of abstraction than that provided by web frameworks such as Jakarta Server Faces.

Servlets have the following advantages over other server extension mechanisms:

- They are generally much faster than CGI scripts because a different process model is used.
- They use a standard API that is supported by many web servers.
- They have all the advantages of the Java programming language, including ease of development and platform independence.
- They can access the large set of APIs available for the Java platform.

### Servlet Container

The servlet container is a part of a web server or application server that provides the network services over which requests and responses are sent, decodes MIME-based requests, and formats MIME-based responses.
A servlet container also contains and manages servlets through their lifecycle.

A servlet container is a complex system.
However, basically there are three things that a servlet container does to service a request for a servlet:

- Creating a request object and populate it with information that may be used by the invoked servlet, such as parameters, headers, cookies, query string, URI, etc.
  A request object is an instance of the `javax.servlet.ServletRequest` interface or the `javax.servlet.http.ServletRequest` interface.
- Creating a response object that the invoked servlet uses to send the response to the web client.
  A response object is an instance of the `javax.servlet.ServletResponse` interface or the `javax.servlet.http.ServletResponse` interface.
- Invoking the service method of the servlet, passing the request and response objects. Here the servlet reads the values from the request object and writes to the response object.

A servlet container can be built into a host Web server, or installed as an add-on component to a Web Server via that server’s native extension API.
Servlet containers can also be built into or possibly installed into Web-enabled application servers.

All servlet containers must support HTTP as a protocol for requests and responses, but additional request/response-based protocols such as HTTPS (HTTP over SSL)may be supported.

## The Servlet Interface

The Servlet interface is the central abstraction of the Java Servlet API.
All servlets implement this interface either directly, or more commonly, by extending a class that implements the interface.
The two classes in the Java Servlet API that implement the Servlet interface are GenericServlet and HttpServlet.
For most purposes, Developers will extend HttpServlet to implement their servlets.

### Request Handling Methods

The basic Servlet interface defines a service method for handling client requests.
This method is called for each request that the servlet container routes to an instance of a servlet.
The handling of concurrent requests to a Web application generally requires that the Web Developer design servlets that can deal with multiple threads executing within the service method at a particular time.
Generally the Web container handles concurrent requests to the same servlet by concurrent execution of the service method on different threads.

```java
package javax.servlet;

public interface Servlet {
    public void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException;
}
```

The HttpServlet abstract subclass adds additional methods beyond the basic Servlet interface that are automatically called by the service method in the HttpServlet class to aid in processing HTTP-based requests.
These methods are:

- doGet for handling HTTP GET requests
- doPost for handling HTTP POST requests
- doPut for handling HTTP PUT requests
- doDelete for handling HTTP DELETE requests
- doHead for handling HTTP HEAD requests
- doOptions for handling HTTP OPTIONS requests
- doTrace for handling HTTP TRACE requests

Typically when developing HTTP-based servlets, a Servlet Developer will only concern himself with the doGet and doPost methods.
The other methods are considered to be methods for use by programmers very familiar with HTTP programming.

See `doPost` override by [org.springframework.web.servlet.FrameworkServlet](/docs/CS/Framework/Spring/MVC.md?id=dispatch)

### Number of Instances

For a servlet not hosted in a distributed environment (the default), the servlet container must use only one instance per servlet declaration.
However, for a servlet implementing the SingleThreadModel interface, the servlet container may instantiate multiple instances to handle a heavy request load and serialize requests to a particular instance.

In the case where a servlet was deployed as part of an application marked in the deployment descriptor as distributable, a container may have only one instance per servlet declaration per Java Virtual Machine.
However, if the servlet in a distributable application implements the SingleThreadModel interface, the container may instantiate multiple instances of that servlet in each JVM of the container.

### Servlet Life Cycle

A servlet is managed through a well defined life cycle that defines how it is loaded and instantiated, is initialized, handles requests from clients, and is taken out of service.
This life cycle is expressed in the API by the init, service, and destroy methods of the jakarta.servlet.Servlet interface that all servlets must implement directly or indirectly through the GenericServlet or HttpServlet abstract classes.

#### Loading and Instantiation

The servlet container is responsible for loading and instantiating servlets.
**The loading and instantiation can occur when the container is started, or delayed until the container determines the servlet is needed to service a request.**

When the servlet engine is started, needed servlet classes must be located by the servlet container.
The servlet container loads the servlet class using normal Java class loading facilities.
The loading may be from a local file system, a remote file system, or other network services.

After loading the Servlet class, the container instantiates it for use.

#### Initialization

After the servlet object is instantiated, the container must initialize the servlet before it can handle requests from clients.
Initialization is provided so that a servlet can read persistent configuration data, initialize costly resources (such as JDBC™ API based connections), and perform other one-time activities.
The container initializes the servlet instance by calling the init method of the Servlet interface with a unique (per servlet declaration) object implementing the ServletConfig interface.
This configuration object allows the servlet to access name-value initialization parameters from the Web application’s configuration information.
The configuration object also gives the servlet access to an object (implementing the ServletContext interface) that describes the servlet’s runtime environment.

实现线程安全通常都是使用synchronized

#### Request Handling

After a servlet is properly initialized, the servlet container may use it to handle client requests.
Requests are represented by request objects of type ServletRequest.
The servlet fills out response to requests by calling methods of a provided object of type ServletResponse.
These objects are passed as parameters to the service method of the Servlet interface.
In the case of an HTTP request, the objects provided by the container are of types HttpServletRequest and HttpServletResponse.

Note that a servlet instance placed into service by a servlet container may handle no requests during its lifetime.

A servlet container may send concurrent requests through the service method of the servlet.
To handle the requests, the Application Developer must make adequate provisions for concurrent processing with multiple threads in the service method.
It is strongly recommended that Developers not synchronize the service method (or methods dispatched to it) because of the detrimental effects on performance

#### End of Service

The servlet container is not required to keep a servlet loaded for any particular period of time.
A servlet instance may be kept active in a servlet container for a period of milliseconds, for the lifetime of the servlet container (which could be a number of days, months, or years), or any amount of time in between.

When the servlet container determines that a servlet should be removed from service, it calls the destroy method of the Servlet interface to allow the servlet to release any resources it is using and save any persistent state.
For example, the container may do this when it wants to conserve memory resources, or when it is being shut down.

Before the servlet container calls the destroy method, it must allow any threads that are currently running in the service method of the servlet to complete execution, or exceed a server-defined time limit.
Once the destroy method is called on a servlet instance, the container may not route other requests to that instance of the servlet.
If the container needs to enable the servlet again, it must do so with a new instance of the servlet’s class.

After the destroy method completes, the servlet container must release the servlet instance so that it is eligible for garbage collection.

## The Request

The request object encapsulates all information from the client request.
In the HTTP protocol, this information is transmitted from the client to the server in the HTTP headers and the message body of the request.

Each request object is valid only within the scope of a servlet’s service method, or within the scope of a filter’s doFilter method,
unless the asynchronous processing is enabled for the component and the startAsync method is invoked on the request object.
In the case where asynchronous processing occurs, the request object remains valid until complete is invoked on the AsyncContext.
Containers commonly recycle request objects in order to avoid the performance overhead of request object creation.
The developer must be aware that maintaining references to request objects for which startAsync has not been called outside the scope described above is not recommended as it may have indeterminate results.

当客户请求某个资源时，HTTP 服务器会用一个 ServletRequest 对象把客户的请求信息封
装起来，然后调用 Servlet 容器的 service 方法，Servlet 容器拿到请求后，根据请求的
URL 和 Servlet 的映射关系，找到相应的 Servlet，如果 Servlet 还没有被加载，就用反射
机制创建这个 Servlet，并调用 Servlet 的 init 方法来完成初始化，接着调用 Servlet 的
service 方法来处理请求，把 ServletResponse 对象返回给 HTTP 服务器，HTTP 服务器会
把响应发送给客户端

## Servlet Context

The ServletContext interface defines a servlet’s view of the Web application within which the servlet is running.
The Container Provider is responsible for providing an implementation of the ServletContext interface in the servlet container.
Using the ServletContext object, a servlet can log events, obtain URL references to resources, and set and store attributes that other servlets in the context can access.

There is one instance object of the ServletContext interface associated with each Web application deployed into a container.
In cases where the container is distributed over many virtual machines, a Web application will have an instance of the ServletContext for each JVM.

Servlet 规范里定义了ServletContext这个接口来对应一个 Web 应用。Web 应用部署好
后，Servlet 容器在启动时会加载 Web 应用，并为每个 Web 应用创建唯一的
ServletContext 对象。 一个 Web 应用可能有多个 Servlet，这些 Servlet 可以通过全局的 ServletContext 来共享数据，这些数据包
括 Web 应用的初始化参数、Web 应用目录下的文件资源等。由于 ServletContext 持有所
有 Servlet 实例，你还可以通过它来实现 Servlet 请求的转发

Servlets in a container that were not deployed as part of a Web application are implicitly part of a “default” Web application and have a default ServletContext.
In a distributed container, the default ServletContext is non-distributable and must only exist in one JVM.

### Reloading Considerations

Although a Container Provider implementation of a class reloading scheme for ease of development is not required, any such implementation must ensure that all servlets, and classes that they may use2, are loaded in the scope of a single class loader.
This requirement is needed to guarantee that the application will behave as expected by the Developer.
As a development aid, the full semantics of notification to session binding listeners should be supported by containers for use in the monitoring of session termination upon class reloading.

Previous generations of containers created new class loaders to load a servlet, distinct from class loaders used to load other servlets or classes used in the servlet context.
This could cause object references within a servlet context to point at unexpected classes or objects, and cause unexpected behavior.
The requirement is needed to prevent problems caused by demand generation of new class loaders.

## The Response

The response object encapsulates all information to be returned from the server to the client.
In the HTTP protocol, this information is transmitted from the server to the client either by HTTP headers or the message body of the request.

Each response object is valid only within the scope of a servlet’s service method, or within the scope of a filter’s doFilter method, unless the associated request object has asynchronous processing enabled for the component.
If asynchronous processing on the associated request is started, then the response object remains valid until complete method on AsyncContext is called.
Containers commonly recycle response objects in order to avoid the performance overhead of response object creation.
The developer must be aware that maintaining references to response objects for which startAsync on the corresponding request has not been called, outside the scope described above may lead to non-deterministic behavior.

### Buffering

A servlet container is allowed, but not required, to buffer output going to the client for efficiency purposes.
Typically servers that do buffering make it the default, but allow servlets to specify buffering parameters.

### Closure of Response Object

When a response is closed, the container must immediately flush all remaining content in the response buffer to the client.
The following events indicate that the servlet has satisfied the request and that the response object is to be closed:

- The termination of the service method of the servlet.
- The amount of content specified in the setContentLength or setContentLengthLong method of the response has been greater than zero and has been written to the response.
- The sendError method is called.
- The sendRedirect method is called.
- The complete method on AsyncContext is called

## Filtering

Filters are Java components that allow on the fly transformations of payload and header information in both the request into a resource and the response from a resource.

The Java Servlet API classes and methods that provide a lightweight framework for filtering active and static content.
It describes how filters are configured in a Web application, and conventions and semantics for their implementation.

A filter is a reusable piece of code that can transform the content of HTTP requests, responses, and header information.
Filters do not generally create a response or respond to a request as servlets do, rather they modify or adapt the requests for a resource, and modify or adapt responses from a resource.

Filters can act on dynamic or static content(dynamic and static content are referred to as Web resources).
Among the types of functionality available to the developer needing to use filters are the following:

- The accessing of a resource before a request to it is invoked.
- The processing of the request for a resource before it is invoked.
- The modification of request headers and data by wrapping the request in customized versions of the request object.
- The modification of response headers and response data by providing customized versions of the response object.
- The interception of an invocation of a resource after its call.
- Actions on a servlet, on groups of servlets, or static content by zero, one, or more filters in a specifiable order.

**Examples of Filtering Components**

- Authentication filters
- Logging and auditing filters
- Image conversion filters
- Data compression filters
- Encryption filters
- Tokenizing filters
- Filters that trigger resource access events
- XSL/T filters that transform XML content
- MIME-type chain filters
- Caching filters

The application developer creates a filter by implementing the `jakarta.servlet.Filter` interface and providing a public constructor taking no arguments.
The class is packaged in the web archive along with the static content and servlets that make up the web application.
A filter is declared using the `<filter>` element in the deployment descriptor.
A filter or collection of filters can be configured for invocation by defining `<filter-mapping>` elements in the deployment descriptor.
This is done by mapping filters to a particular servlet by the servlet’s logical name, or mapping to a group of servlets and static content resources by mapping a filter to a URL pattern.

### Filter Lifecycle

After deployment of the web application, and before a request causes the container to access a web resource, the container must locate the list of filters that must be applied to the web resource as described below.
The container must ensure that it has instantiated a filter of the appropriate class for each filter in the list, and called its init(FilterConfig config) method.
The filter may throw an exception to indicate that it cannot function properly.
If the exception is of type UnavailableException, the container may examine the isPermanent attribute of the exception and may choose to retry the filter at some later time.

Only one instance per <filter> declaration in the deployment descriptor is instantiated per JVM of the container.
The container provides the filter config as declared in the filter’s deployment descriptor, the reference to the ServletContext for the web application, and the set of initialization parameters.

When the container receives an incoming request, it takes the first filter instance in the list and calls its `doFilter` method, passing in the ServletRequest and ServletResponse , and a reference to the FilterChain object it will use.

The `doFilter` method of a filter will typically be implemented following this or some subset of the following pattern:

1. The method examines the request’s headers.
2. The method may wrap the request object with a customized implementation of ServletRequest or
   HttpServletRequest in order to modify request headers or data.
3. The method may wrap the response object passed in to its `doFilter` method with a customized
   implementation of ServletResponse or HttpServletResponse to modify response headers or data.
4. The filter may invoke the next entity in the filter chain. The next entity may be another filter, or if
   the filter making the invocation is the last filter configured in the deployment descriptor for this
   chain, the next entity is the target web resource. The invocation of the next entity is effected by
   calling the doFilter method on the FilterChain object, and passing in the request and response with
   which it was called or passing in wrapped versions it may have created.
   The filter chain’s implementation of the doFilter method, provided by the container, must locate
   the next entity in the filter chain and invoke its doFilter method, passing in the appropriate
   request and response objects.
   Alternatively, the filter chain can block the request by not making the call to invoke the next entity,
   leaving the filter responsible for filling out the response object.
   The service method is required to run in the same thread as all filters that apply to the servlet.
5. After invocation of the next filter in the chain, the filter may examine response headers.
6. Alternatively, the filter may have thrown an exception to indicate an error in processing. If the
   filter throws an UnavailableException during its doFilter processing, the container must not
   attempt continued processing down the filter chain. It may choose to retry the whole chain at a
   later time if the exception is not marked permanent.
7. When the last filter in the chain has been invoked, the next entity accessed is the target servlet or
   resource at the end of the chain.
8. Before a filter instance can be removed from service by the container, the container must first call
   the destroy method on the filter to enable the filter to release any resources and perform other
   cleanup operations.

### Wrapping Requests and Responses

Central to the notion of filtering is the concept of wrapping a request or response in order that it can
override behavior to perform a filtering task. In this model, the developer not only has the ability to
override existing methods on the request and response objects, but to provide new API suited to a
particular filtering task to a filter or target web resource down the chain. For example, the developer
may wish to extend the response object with higher level output objects than the output stream or the
writer, such as API that allows DOM objects to be written back to the client.

In order to support this style of filter the container must support the following requirements:

- When a filter invokes the doFilter method on the container’s filter chain implementation, the
  container must ensure that the request and response objects that it passes to the next entity in the
  filter chain, or to the target web resource if the filter was the last in the chain, is the same object
  that was passed into the doFilter method by the calling filter.
- When a filter or servlet calls RequestDispatcher.forward or RequestDispatcher.include, then the request and response objects seen by the called filter(s) and/or servlet must either: be the same
  wrapper objects that were passed; or wrappers of the objects that were passed.
- When startAsync(ServletRequest, ServletResponse) is used to commence an asynchronous cycle
  then the request and response objects seen by any filter(s) and/or servlet subsequent to an
  AsyncContext.dispatch() (or overloaded variant) must either: be the same wrapper objects that
  were passed; or wrappers of the objects that were passed.

## Listeners

Spring 就实现了自己的监听器[ContextLoaderListener](/docs/CS/Framework/Spring/MVC.md?id=ContextLoaderListener)，来监听 ServletContext 的启动事件，
目的是当 Servlet 容器启动时，init 全局的ApplicationContext方便后续的WebApplicationContext使用
## Sessions

The Hypertext Transfer Protocol (HTTP) is by design a stateless protocol.
To build effective web applications, it is imperative that requests from a particular client be associated with each other.
Many strategies for session tracking have evolved over time, but all are difficult or troublesome for the programmer to use directly.
This specification defines a simple HttpSession interface that allows a servlet container to use any of several approaches to track a user’s session without involving the Application Developer in the nuances of any one approach.

https，加密后攻击者就拿不到sessionid了，另外CSRF也是一种防止session劫持的方式

### Session Tracking Mechanisms

#### Cookies

Session tracking through HTTP cookies is the most used session tracking mechanism and is required to be supported by all servlet containers.

The container sends a cookie to the client. The client will then return the cookie on each subsequent request to the server, unambiguously associating the request with a session.
The standard name of the session tracking cookie must be JSESSIONID.
Containers may allow the name of the session tracking cookie to be customized through container specific configuration.

All servlet containers MUST provide an ability to configure whether or not the container marks the session tracking cookie as HttpOnly.
The established configuration must apply to all contexts for which a context specific configuration has not been established (see SessionCookieConfig javadoc for more details).

If a web application configures a custom name for its session tracking cookies, the same custom name will also be used as the name of the URI parameter if the session id is encoded in the URL (provided that URL rewriting has been enabled).

#### SSL Sessions

Secure Sockets Layer, the encryption technology used in the HTTPS protocol, has a built-in mechanism allowing multiple requests from a client to be unambiguously identified as being part of a session.
A servlet container can easily use this data to define a session.

#### URL Rewriting

URL rewriting is the lowest common denominator of session tracking. When a client will not accept a
cookie, URL rewriting may be used by the server as the basis for session tracking. URL rewriting
involves adding data, a session ID, to the URL path that is interpreted by the container to associate the request with a session.
The session ID must be encoded as a path parameter in the URL string. The name of the parameter
must be jsessionid. Here is an example of a URL containing encoded path information:

```http
http://www.example.com/catalog/index.html;jsessionid=1234
```

URL rewriting exposes session identifiers in logs, bookmarks, referer headers, cached HTML, and the
URL bar. URL rewriting should not be used as a session tracking mechanism where cookies or SSL
sessions are supported and suitable.

#### Session Integrity

Web containers must be able to support the HTTP session while servicing HTTP requests from clients that do not support the use of cookies.
To fulfill this requirement, web containers commonly support the URL rewriting mechanism.

### Session Lifecycle

A session is considered “new” when it is only a prospective session and has not been established.
Because HTTP is a request-response based protocol, an HTTP session is considered to be new until a client “joins” it.
A client joins a session when session tracking information has been returned to the server indicating that a session has been established.
Until the client joins a session, it cannot be assumed that the next request from the client will be recognized as part of a session.

The session is considered to be “new” if either of the following is true:

- The client does not yet know about the session
- The client chooses not to join a session.

These conditions define the situation where the servlet container has no mechanism by which to associate a request with a previous request.
An Application Developer must design the application to handle a situation where a client has not, can not, or will not join a session.

Associated with each session, there is a string containing a unique identifier, which is referred to as the session id.
The value of the session id can be obtained by calling jakarta.servlet.http.HttpSession.getId() and can be changed after creation by invoking jakarta.servlet.http.HttpServletRequest.changeSessionId().

## Web Applications

A web application is a collection of servlets, HTML pages, classes, and other resources that make up a complete application on a web server.
The web application can be bundled and run on multiple containers from multiple vendors.

The servlet container must enforce a one to one correspondence between a web application and a ServletContext.
A ServletContext object provides a servlet with its view of the application.

Web applications can be packaged and signed into a Web ARchive format (WAR) file using the standard Java archive tools.
For example, an application for issue tracking might be distributed in an archive file called issuetrack.war.

## Application Lifecycle Events

Application event listeners are classes that implement one or more of the servlet event listener interfaces.
They are instantiated and registered in the web container at the time of the deployment of the web application.
They are provided by the Application Developer in the WAR.

Servlet event listeners support event notifications for state changes in the ServletContext, HttpSession and ServletRequest objects.
Servlet context listeners are used to manage resources or state held at a JVM level for the application.
HTTP session listeners are used to manage state or resources associated with a series of requests made into a web application from the same client or user.
Servlet request listeners are used to manage state across the lifecycle of servlet requests.
Async listeners are used to manage async events such as time outs and completion of async processing.

There may be multiple listener classes listening to each event type, and the Application Developer may specify the order in which the container invokes the listener beans for each event type.


## ASync

AsyncContext req和res





## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

## References

1. [Jakarta Servlet Specification 6.0](https://jakarta.ee/specifications/servlet/6.0/jakarta-servlet-spec-6.0.pdf)
