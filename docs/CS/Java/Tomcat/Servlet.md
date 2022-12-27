## Introduction

A servlet is a Jakarta technology-based web component, managed by a container, that generates dynamic content.
Like other Jakarta technology-based components, servlets are platform-independent Java classes that are compiled to platform-neutral byte code that can be loaded dynamically into and run by a Jakarta technology-enabled web server.
Containers, sometimes called servlet engines, are web server extensions that provide servlet functionality.
Servlets interact with web clients via a request/response paradigm implemented by the servlet container.

In functionality, servlets provide a higher level abstraction than Common Gateway Interface (CGI) programs but a lower level of abstraction than that provided by web frameworks such as Jakarta Server Faces.

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

See `doPost` override by [org.springframework.web.servlet.FrameworkServlet](/docs/CS/Java/Spring/MVC.md?id=dispatch)

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
The loading and instantiation can occur when the container is started, or delayed until the container determines the servlet is needed to service a request.

When the servlet engine is started, needed servlet classes must be located by the servlet container.
The servlet container loads the servlet class using normal Java class loading facilities.
The loading may be from a local file system, a remote file system, or other network services.

After loading the Servlet class, the container instantiates it for use.

#### Initialization

After the servlet object is instantiated, the container must initialize the servlet before it can handle requests from clients.
Initialization is provided so that a servlet can read persistent configuration data, initialize costly resources (such as JDBC™ APIbased connections), and perform other one-time activities.
The container initializes the servlet instance by calling the init method of the Servlet interface with a unique (per servlet declaration) object implementing the ServletConfig interface.
This configuration object allows the servlet to access name-value initialization parameters from the Web application’s configuration information.
The configuration object also gives the servlet access to an object (implementing the ServletContext interface) that describes the servlet’s runtime environment.

#### Request Handling

After a servlet is properly initialized, the servlet container may use it to handle client requests.
Requests are represented by request objects of type ServletRequest.
The servlet fills out response to requests by calling methods of a provided object of type ServletResponse.
These objects are passed as parameters to the service method of the Servlet interface.
In the case of an HTTP request, the objects provided by the container are of types HttpServletRequest and HttpServletResponse.

Note that a servlet instance placed into service by a servlet container may handle no requests during its lifetime.

#### End of Service

The servlet container is not required to keep a servlet loaded for any particular
period of time. A servlet instance may be kept active in a servlet container for a
period of milliseconds, for the lifetime of the servlet container (which could be a
number of days, months, or years), or any amount of time in between.
When the servlet container determines that a servlet should be removed from
service, it calls the destroy method of the Servlet interface to allow the servlet to
release any resources it is using and save any persistent state. For example, the
container may do this when it wants to conserve memory resources, or when it is
being shut down.
Before the servlet container calls the destroy method, it must allow any threads that
are currently running in the service method of the servlet to complete execution, or
exceed a server-defined time limit.
Once the destroy method is called on a servlet instance, the container may not route
other requests to that instance of the servlet. If the container needs to enable the
servlet again, it must do so with a new instance of the servlet’s class.

After the destroy method completes, the servlet container must release the servlet instance so that it is eligible for garbage collection.

## The Request

The request object encapsulates all information from the client request.
In the HTTP protocol, this information is transmitted from the client to the server in the HTTP headers and the message body of the request.

Each request object is valid only within the scope of a servlet’s service method, or within the scope of a filter’s doFilter method,
unless the asynchronous processing is enabled for the component and the startAsync method is invoked on the request object.
In the case where asynchronous processing occurs, the request object remains valid until complete is invoked on the AsyncContext.
Containers commonly recycle request objects in order to avoid the performance overhead of request object creation.
The developer must be aware that maintaining references to request objects for which startAsync has not been called outside the scope described above is not recommended as it may have indeterminate results.

## Servlet Context

The ServletContext interface defines a servlet’s view of the Web application within which the servlet is running.
The Container Provider is responsible for providing an implementation of the ServletContext interface in the servlet container.
Using the ServletContext object, a servlet can log events, obtain URL references to resources, and set and store attributes that other servlets in the context can access.

There is one instance object of the ServletContext interface associated with each Web application deployed into a container.
In cases where the container is distributed over many virtual machines, a Web application will have an instance of the ServletContext for each JVM.

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

## DefaultServlet

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

## Sessions

## Links

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)
- [Spring MVC](/docs/CS/Java/Spring/MVC.md)

## References

1. [Jakarta Servlet Specification 6.0](https://jakarta.ee/specifications/servlet/6.0/jakarta-servlet-spec-6.0.pdf)
