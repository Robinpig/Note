## Introduction

A servlet is a Jakarta technology-based web component, managed by a container, that generates dynamic content.
Like other Jakarta technology-based components, servlets are platform-independent Java classes that are compiled to platform-neutral byte code that can be loaded dynamically into and run by a Jakarta technology-enabled web server.
Containers, sometimes called servlet engines, are web server extensions that provide servlet functionality.
Servlets interact with web clients via a request/response paradigm implemented by the servlet container.

The servlet container is a part of a web server or application server that provides the network services over which requests and responses are sent, decodes MIME-based requests, and formats MIME-based responses.
A servlet container also contains and manages servlets through their lifecycle.

Directory structure of Most Web Applications

```
| -  MyWebApp
      | -  WEB-INF/web.xml  
      | -  WEB-INF/lib/   
      | -  WEB-INF/classes/   
      | -  META-INF/      
```

In functionality, servlets provide a higher level abstraction than Common Gateway Interface (CGI) programs but a lower level of abstraction than that provided by web frameworks such as Jakarta Server Faces.

### Servlet Container

A servlet container is a complex system. However, basically there are three things that a servlet container does to service a request for a servlet:

- Creating a request object and populate it with information that may be used by the invoked servlet, such as parameters, headers, cookies, query string, URI, etc.
  A request object is an instance of the `javax.servlet.ServletRequest` interface or the `javax.servlet.http.ServletRequest` interface.
- Creating a response object that the invoked servlet uses to send the response to the web client.
  A response object is an instance of the `javax.servlet.ServletResponse` interface or the `javax.servlet.http.ServletResponse` interface.
- Invoking the service method of the servlet, passing the request and response objects. Here the servlet reads the values from the request object and writes to the response object.

## Servlet

Defines methods that all servlets must implement.

A servlet is a small Java program that runs within a Web server. Servlets receive and respond to requests from Web clients, usually across [HTTP](/docs/CS/CN/HTTP/HTTP.md), the HyperText Transfer Protocol.

To implement this interface, you can write a generic servlet that extends `javax.servlet.GenericServlet` or an HTTP servlet that extends `javax.servlet.http.HttpServlet`.

This interface defines methods to initialize a servlet, to service requests, and to remove a servlet from the server.
These are known as life-cycle methods and are called in the following sequence:

- The servlet is constructed, then initialized with the init method.
- Any calls from clients to the service method are handled.
- The servlet is taken out of service, then destroyed with the destroy method, then garbage collected and finalized.

In addition to the life-cycle methods, this interface provides the getServletConfig method, which the servlet can use to get any startup information,
and the getServletInfo method, which allows the servlet to return basic information about itself, such as author, version, and copyright.

```java
package javax.servlet;

public interface Servlet {

    public void init(ServletConfig config) throws ServletException;

    public ServletConfig getServletConfig();

    public void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException;
  
    public String getServletInfo();

    public void destroy();
}

```

### ServletConfig

A servlet configuration object used by a servlet container to pass information to a servlet during initialization.

```java
package javax.servlet;

public interface ServletConfig {

    public String getServletName();

    public ServletContext getServletContext();

    public String getInitParameter(String name);

    public Enumeration<String> getInitParameterNames();
}
```

### ServletContext

Defines a set of methods that a servlet uses to communicate with its servlet container, for example, to get the MIME type of a file, dispatch requests, or write to a log file.

There is one context per "web application" per Java Virtual Machine. (A "web application" is a collection of servlets and content installed under a specific subset of the server's URL namespace such as /catalog and possibly installed via a .war file.)

In the case of a web application marked "distributed" in its deployment descriptor, there will be one context instance for each virtual machine.
In this situation, the context cannot be used as a location to share global information (because the information won't be truly global). Use an external resource like a database instead.

The ServletContext object is contained within the ServletConfig object, which the Web server provides the servlet when the servlet is initialized.

```java

public interface ServletContext {

    public static final String TEMPDIR = "javax.servlet.context.tempdir";

    public static final String ORDERED_LIBS = "javax.servlet.context.orderedLibs";

    public String getContextPath();

    public ServletContext getContext(String uripath);

    public int getMajorVersion();

    public int getMinorVersion();

    public int getEffectiveMajorVersion();

    public int getEffectiveMinorVersion();

    public String getMimeType(String file);

    public Set<String> getResourcePaths(String path);

    public URL getResource(String path) throws MalformedURLException;

    public InputStream getResourceAsStream(String path);

    public RequestDispatcher getRequestDispatcher(String path);

    public RequestDispatcher getNamedDispatcher(String name);

    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Servlet getServlet(String name) throws ServletException;

    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Enumeration<Servlet> getServlets();

    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Enumeration<String> getServletNames();

    public void log(String msg);

    public String getRealPath(String path);

    public String getServerInfo();

    public String getInitParameter(String name);

    public Enumeration<String> getInitParameterNames();

    public boolean setInitParameter(String name, String value);

    public void setAttribute(String name, Object object);
  
    public void removeAttribute(String name);

    public String getServletContextName();

    public ServletRegistration.Dynamic addServlet(String servletName, Servlet servlet);

    public ServletRegistration.Dynamic addServlet(String servletName,
            Class<? extends Servlet> servletClass);

    public <T extends Servlet> T createServlet(Class<T> c)
            throws ServletException;

    public ServletRegistration getServletRegistration(String servletName);

    public Map<String, ? extends ServletRegistration> getServletRegistrations();

    public FilterRegistration.Dynamic addFilter(String filterName, String className);

    public FilterRegistration.Dynamic addFilter(String filterName, Filter filter);

    public FilterRegistration.Dynamic addFilter(String filterName,
            Class<? extends Filter> filterClass);

    public <T extends Filter> T createFilter(Class<T> c) throws ServletException;

    public FilterRegistration getFilterRegistration(String filterName);

    public Map<String, ? extends FilterRegistration> getFilterRegistrations();

    public SessionCookieConfig getSessionCookieConfig();

    public void addListener(String className);

    public <T extends EventListener> void addListener(T t);

    public void addListener(Class<? extends EventListener> listenerClass);

    public <T extends EventListener> T createListener(Class<T> c)
            throws ServletException;

    public ClassLoader getClassLoader();
}
```

create a Servlet

### Servlet Life Cycle

A servlet is managed through a well defined life cycle that defines how it is loaded and instantiated, is initialized, handles requests from clients, and is taken out of service.
This life cycle is expressed in the API by the init, service, and destroy methods of the jakarta.servlet.Servlet interface that all servlets must implement directly or indirectly through the GenericServlet or HttpServlet abstract classes.

#### GenericServlet

Defines a generic, protocol-independent servlet. To write an HTTP servlet for use on the Web, extend javax.servlet.http.HttpServlet instead.

GenericServlet implements the Servlet and ServletConfig interfaces. GenericServlet may be directly extended by a servlet, although it's more common to extend a protocol-specific subclass such as HttpServlet.

GenericServlet makes writing servlets easier.
It provides simple versions of the lifecycle methods init and destroy and of the methods in the ServletConfig interface. GenericServlet also implements the log method, declared in the ServletContext interface.

To write a generic servlet, you need only override the abstract service method.

```java
public abstract class GenericServlet implements Servlet, ServletConfig,
        java.io.Serializable {

    private static final long serialVersionUID = 1L;

    private transient ServletConfig config;

    public GenericServlet() {
        // NOOP
    }

    @Override
    public void destroy() {
        // NOOP by default
    }

    @Override
    public String getInitParameter(String name) {
        return getServletConfig().getInitParameter(name);
    }

    @Override
    public Enumeration<String> getInitParameterNames() {
        return getServletConfig().getInitParameterNames();
    }

    @Override
    public ServletConfig getServletConfig() {
        return config;
    }

    @Override
    public ServletContext getServletContext() {
        return getServletConfig().getServletContext();
    }

    @Override
    public void init(ServletConfig config) throws ServletException {
        this.config = config;
        this.init();
    }

    public void init() throws ServletException {
        // NOOP by default
    }
}
```

### Request Handling Methods

#### service

The basic Servlet interface defines a service method for handling client requests.
This method is called for each request that the servlet container routes to an instance of a servlet.
See [HttpServlet](/docs/CS/Java/Tomcat/Servlet.md?id=http).

The handling of concurrent requests to a web application requires that the web developer design servlets that can deal with multiple threads executing within the service method at a particular time.

```java
public abstract class GenericServlet implements Servlet, ServletConfig,
        java.io.Serializable {
  
    @Override
    public abstract void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException;

}
```

### HttpServlet

The HttpServlet abstract subclass adds additional methods beyond the basic Servlet interface that are automatically called by the service method in the HttpServlet class to aid in processing HTTP-based requests.

These methods are:

- doGet for handling HTTP GET requests
- doPost for handling HTTP POST requests
- doPut for handling HTTP PUT requests
- doDelete for handling HTTP DELETE requests
- doHead for handling HTTP HEAD requests
- doOptions for handling HTTP OPTIONS requests
- doTrace for handling HTTP TRACE requests

Typically when developing HTTP-based servlets, an Application Developer is concerned with the doGet
and doPost methods. The other methods are considered to be methods for use by programmers very
familiar with HTTP programming.

Provides an abstract class to be subclassed to create an HTTP servlet suitable for a Web site. A subclass of HttpServlet must override at least one method, usually one of these:

- doGet, if the servlet supports HTTP GET requests
- doPost, for HTTP POST requests
- doPut, for HTTP PUT requests
- doDelete, for HTTP DELETE requests
- init and destroy, to manage resources that are held for the life of the servlet
- getServletInfo, which the servlet uses to provide information about itself

There's almost no reason to override the service method. service handles standard HTTP requests by dispatching them to the handler methods for each HTTP request type (the doMethod methods listed above).
Likewise, there's almost no reason to override the doOptions and doTrace methods.

Servlets typically run on multithreaded servers, so be aware that a servlet must handle concurrent requests and be careful to synchronize access to shared resources. Shared resources include in-memory data such as instance or class variables and external objects such as files, database connections, and network connections. See the Java Tutorial on Multithreaded Programming  for more information on handling multiple threads in a Java program.

```java
public abstract class HttpServlet extends GenericServlet {

    public HttpServlet() {
        // NOOP
    }

    private static Method[] getAllDeclaredMethods(Class<?> c) {

        if (c.equals(javax.servlet.http.HttpServlet.class)) {
            return null;
        }

        Method[] parentMethods = getAllDeclaredMethods(c.getSuperclass());
        Method[] thisMethods = c.getDeclaredMethods();

        if ((parentMethods != null) && (parentMethods.length > 0)) {
            Method[] allMethods =
                    new Method[parentMethods.length + thisMethods.length];
            System.arraycopy(parentMethods, 0, allMethods, 0,
                    parentMethods.length);
            System.arraycopy(thisMethods, 0, allMethods, parentMethods.length,
                    thisMethods.length);

            thisMethods = allMethods;
        }

        return thisMethods;
    }


    @Override
    public void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException {

        HttpServletRequest request;
        HttpServletResponse response;

        try {
            request = (HttpServletRequest) req;
            response = (HttpServletResponse) res;
        } catch (ClassCastException e) {
            throw new ServletException("non-HTTP request or response");
        }
        service(request, response);
    }
}
```

#### http

See `doPost` override by [org.springframework.web.servlet.FrameworkServlet](/docs/CS/Java/Spring/MVC.md?id=dispatch)

```java
public abstract class HttpServlet extends GenericServlet {
    protected void service(HttpServletRequest req, HttpServletResponse resp)
            throws ServletException, IOException {

        String method = req.getMethod();

        if (method.equals(METHOD_GET)) {
            long lastModified = getLastModified(req);
            if (lastModified == -1) {
                // servlet doesn't support if-modified-since, no reason
                // to go through further expensive logic
                doGet(req, resp);
            } else {
                long ifModifiedSince;
                try {
                    ifModifiedSince = req.getDateHeader(HEADER_IFMODSINCE);
                } catch (IllegalArgumentException iae) {
                    // Invalid date header - proceed as if none was set
                    ifModifiedSince = -1;
                }
                if (ifModifiedSince < (lastModified / 1000 * 1000)) {
                    // If the servlet mod time is later, call doGet()
                    // Round down to the nearest second for a proper compare
                    // A ifModifiedSince of -1 will always be less
                    maybeSetLastModified(resp, lastModified);
                    doGet(req, resp);
                } else {
                    resp.setStatus(HttpServletResponse.SC_NOT_MODIFIED);
                }
            }

        } else if (method.equals(METHOD_HEAD)) {
            long lastModified = getLastModified(req);
            maybeSetLastModified(resp, lastModified);
            doHead(req, resp);

        } else if (method.equals(METHOD_POST)) {
            doPost(req, resp);

        } else if (method.equals(METHOD_PUT)) {
            doPut(req, resp);

        } else if (method.equals(METHOD_DELETE)) {
            doDelete(req, resp);

        } else if (method.equals(METHOD_OPTIONS)) {
            doOptions(req,resp);

        } else if (method.equals(METHOD_TRACE)) {
            doTrace(req,resp);

        } else {
            //
            // Note that this means NO servlet supports whatever
            // method was requested, anywhere on this server.
            //

            String errMsg = lStrings.getString("http.method_not_implemented");
            Object[] errArgs = new Object[1];
            errArgs[0] = method;
            errMsg = MessageFormat.format(errMsg, errArgs);

            resp.sendError(HttpServletResponse.SC_NOT_IMPLEMENTED, errMsg);
        }
    }


    protected void doGet(HttpServletRequest req, HttpServletResponse resp)
            throws ServletException, IOException
    {
        String protocol = req.getProtocol();
        String msg = lStrings.getString("http.method_get_not_supported");
        if (protocol.endsWith("1.1")) {
            resp.sendError(HttpServletResponse.SC_METHOD_NOT_ALLOWED, msg);
        } else {
            resp.sendError(HttpServletResponse.SC_BAD_REQUEST, msg);
        }
    }

    protected void doPost(HttpServletRequest req, HttpServletResponse resp)
            throws ServletException, IOException {

        String protocol = req.getProtocol();
        String msg = lStrings.getString("http.method_post_not_supported");
        if (protocol.endsWith("1.1")) {
            resp.sendError(HttpServletResponse.SC_METHOD_NOT_ALLOWED, msg);
        } else {
            resp.sendError(HttpServletResponse.SC_BAD_REQUEST, msg);
        }
    }

}
```

## Request/Response

### ServletRequest

Defines an object to provide client request information to a servlet. The servlet container creates a ServletRequest object and passes it as an argument to the servlet's service method.

A ServletRequest object provides data including parameter name and values, attributes, and an input stream.
Interfaces that extend ServletRequest can provide additional protocol-specific data (for example, HTTP data is provided by javax.servlet.http.HttpServletRequest.

```java
public interface ServletRequest {

}
```

### HttpServletRequest

Extends the ServletRequest interface to provide request information for HTTP servlets.
The servlet container creates an HttpServletRequest object and passes it as an argument to the servlet's service methods (doGet, doPost, etc).

```java
public interface HttpServletRequest extends ServletRequest {

}
```

### ServletResponse

Defines an object to assist a servlet in sending a response to the client. The servlet container creates a ServletResponse object and passes it as an argument to the servlet's service method.

To send binary data in a MIME body response, use the ServletOutputStream returned by getOutputStream. To send character data, use the PrintWriter object returned by getWriter.
To mix binary and text data, for example, to create a multipart response, use a ServletOutputStream and manage the character sections manually.

The charset for the MIME body response can be specified explicitly or implicitly. The priority order for specifying the response body is:

1. explicitly per request using setCharacterEncoding and setContentType
2. implicitly per request using setLocale
3. per web application via the deployment descriptor or ServletContext.setRequestCharacterEncoding(String)
4. container default via vendor specific configuration
5. ISO-8859-1

The setCharacterEncoding, setContentType, or setLocale method must be called before getWriter and before committing the response for the character encoding to be used.
See the Internet RFCs such as RFC 2045  for more information on MIME. Protocols such as SMTP and HTTP define profiles of MIME, and those standards are still evolving.

```java
public interface ServletResponse {


}
```

### HttpServletResponse

Extends the ServletResponse interface to provide HTTP-specific functionality in sending a response. For example, it has methods to access HTTP headers and cookies.
The servlet container creates an HttpServletResponse object and passes it as an argument to the servlet's service methods (doGet, doPost, etc).

```java
public interface HttpServletResponse extends ServletResponse {

}
```

### DefaultServlet

The default resource-serving servlet for most web applications, used to serve static resources such as HTML pages and images.

This servlet is intended to be mapped to /e.g.:

```xml
<servlet-mapping>
    <servlet-name>default</servlet-name>
    <url-pattern>/</url-pattern>
</servlet-mapping>
```

input output buffer

```java
    protected void serveResource(HttpServletRequest request,
                               HttpServletResponse response,
                               boolean content,
                               String inputEncoding)
          throws IOException, ServletException {
      // ... 
      // Check if the conditions specified in the optional If headers are
      // satisfied.
      if (resource.isFile()) {
        // Checking If headers
        included = (request.getAttribute(
                RequestDispatcher.INCLUDE_CONTEXT_PATH) != null);
        if (!included && !isError && !checkIfHeaders(request, response, resource)) {
          return;
        }
      }
    }
```

checkIfHeaders

- Etag : If-None-Match
- Last-Modified : If-Modified-Since

```java
public class DefaultServlet {
  protected boolean checkIfHeaders(HttpServletRequest request,
                                   HttpServletResponse response,
                                   WebResource resource)
          throws IOException {

    return checkIfMatch(request, response, resource)
            && checkIfModifiedSince(request, response, resource)
            && checkIfNoneMatch(request, response, resource)
            && checkIfUnmodifiedSince(request, response, resource);

  }

  protected boolean checkIfNoneMatch(HttpServletRequest request, HttpServletResponse response, WebResource resource)
          throws IOException {

    String headerValue = request.getHeader("If-None-Match");
    if (headerValue != null) {

      boolean conditionSatisfied;

      String resourceETag = generateETag(resource);
      if (!headerValue.equals("*")) {
        if (resourceETag == null) {
          conditionSatisfied = false;
        } else {
          // RFC 7232 requires weak comparison for If-None-Match headers
          Boolean matched = EntityTag.compareEntityTag(new StringReader(headerValue), true, resourceETag);
          if (matched == null) {
            if (debug > 10) {
              log("DefaultServlet.checkIfNoneMatch:  Invalid header value [" + headerValue + "]");
            }
            response.sendError(HttpServletResponse.SC_BAD_REQUEST);
            return false;
          }
          conditionSatisfied = matched.booleanValue();
        }
      } else {
        conditionSatisfied = true;
      }

      if (conditionSatisfied) {
        // For GET and HEAD, we should respond with
        // 304 Not Modified.
        // For every other method, 412 Precondition Failed is sent
        // back.
        if ("GET".equals(request.getMethod()) || "HEAD".equals(request.getMethod())) {
          response.setStatus(HttpServletResponse.SC_NOT_MODIFIED);
          response.setHeader("ETag", resourceETag);
        } else {
          response.sendError(HttpServletResponse.SC_PRECONDITION_FAILED);
        }
        return false;
      }
    }
    return true;
  }
}
```

CacheResource

If the `cachingAllowed` flag is true, the cache for static resources will be used.
If not specified, the default value of the flag is true.
This value may be changed while the web application is running (e.g. via JMX).
When the cache is disabled any resources currently in the cache are cleared from the cache.

The maximum size of the static resource cache in kilobytes.
If `cacheMaxSize` not specified, the default value is 10240(10 megabytes).
This value may be changed while the web application is running (e.g. via JMX).
If the cache is using more memory than the new limit the cache will attempt to reduce in size over time to meet the new limit.
If necessary, cacheObjectMaxSize will be reduced to ensure that it is no larger than cacheMaxSize/20.

The amount of time in milliseconds between the revalidation of cache entries.
If `cacheTtl` not specified, the default value is 5000 (5 seconds).
This value may be changed while the web application is running(e.g. via JMX).
When a resource is cached it will inherit the TTL in force at the time it was cached and retain that TTL until the resource is evicted from the cache regardless of any subsequent changes that may be made to this attribute.

```java
public class StandardRoot extends LifecycleMBeanBase implements WebResourceRoot {
  protected WebResource getResource(String path, boolean validate,
                                    boolean useClassLoaderResources) {
    if (validate) {
      path = validate(path);
    }

    if (isCachingAllowed()) {
      return cache.getResource(path, useClassLoaderResources);
    } else {
      return getResourceInternal(path, useClassLoaderResources);
    }
  }
}
```

## Listener

## Filter

Servlet3.0之前1请求1线程

3.0

1. 请求被Servlet容器接受,分配线程流转Filter链
2. Servlet使用req.startAsync返回异步上下文
3. 异步线程处理完请求后拿AsyncContext写回请求方

`@WebServlet(asyncSupport = true)` 开启异步支持, `AsyncContext` start task

`AsyncListener`

Servlet3.1非阻塞IO

在Servlet处理请求时，从ServletInputStream中读取请求体时是阻塞的。而我们想要的是，当数据就绪时通知我们去读取就可以了，因为这可以避免占用Servlet容器线程或者业务线程来进行阻塞读取

IO数据需要等待内核接收就绪方可,期间会阻塞容器线程

ReadListener到ServletInputStream 数据准备好后回调onDataAvailable方法

响应不同的异步

1. DeferredResult封装 代理了AsyncContext的流程
2. Callable封装 使用TaskExecutor执行

webflux

HttpHandler Adapter

## Links

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)
- [Spring MVC](/docs/CS/Java/Spring/MVC.md)

## References

1. [Jakarta Servlet Specification 6.0](https://jakarta.ee/specifications/servlet/6.0/jakarta-servlet-spec-6.0.pdf)
