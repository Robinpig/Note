## Introduction


Directory structure of Most Web Applications
```
| -  MyWebApp
      | -  WEB-INF/web.xml        
      | -  WEB-INF/lib/           
      | -  WEB-INF/classes/       
      | -  META-INF/              
```

## Servlet

Defines methods that all servlets must implement.

A servlet is a small Java program that runs within a Web server. Servlets receive and respond to requests from Web clients, usually across [HTTP](/docs/CS/CN/HTTP.md), the HyperText Transfer Protocol.

To implement this interface, you can write a generic servlet that extends `javax.servlet.GenericServlet` or an HTTP servlet that extends `javax.servlet.http.HttpServlet`.

This interface defines methods to initialize a servlet, to service requests, and to remove a servlet from the server. 
These are known as life-cycle methods and are called in the following sequence:
- The servlet is constructed, then initialized with the init method.
- Any calls from clients to the service method are handled.
- The servlet is taken out of service, then destroyed with the destroy method, then garbage collected and finalized.

In addition to the life-cycle methods, this interface provides the getServletConfig method, which the servlet can use to get any startup information, 
and the getServletInfo method, which allows the servlet to return basic information about itself, such as author, version, and copyright.

```java
package javax.servlet.GenericServlet;

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

```java

/**
 * A servlet configuration object used by a servlet container to pass
 * information to a servlet during initialization.
 */
public interface ServletConfig {

    /**
     * Returns the name of this servlet instance. The name may be provided via
     * server administration, assigned in the web application deployment
     * descriptor, or for an unregistered (and thus unnamed) servlet instance it
     * will be the servlet's class name.
     *
     * @return the name of the servlet instance
     */
    public String getServletName();

    /**
     * Returns a reference to the {@link ServletContext} in which the caller is
     * executing.
     *
     * @return a {@link ServletContext} object, used by the caller to interact
     *         with its servlet container
     * @see ServletContext
     */
    public ServletContext getServletContext();

    /**
     * Returns a <code>String</code> containing the value of the named
     * initialization parameter, or <code>null</code> if the parameter does not
     * exist.
     *
     * @param name
     *            a <code>String</code> specifying the name of the
     *            initialization parameter
     * @return a <code>String</code> containing the value of the initialization
     *         parameter
     */
    public String getInitParameter(String name);

    /**
     * Returns the names of the servlet's initialization parameters as an
     * <code>Enumeration</code> of <code>String</code> objects, or an empty
     * <code>Enumeration</code> if the servlet has no initialization parameters.
     *
     * @return an <code>Enumeration</code> of <code>String</code> objects
     *         containing the names of the servlet's initialization parameters
     */
    public Enumeration<String> getInitParameterNames();
}
```



### ServletContext

```java

/**
 * Defines a set of methods that a servlet uses to communicate with its servlet
 * container, for example, to get the MIME type of a file, dispatch requests, or
 * write to a log file.
 * <p>
 * There is one context per "web application" per Java Virtual Machine. (A
 * "web application" is a collection of servlets and content installed under a
 * specific subset of the server's URL namespace such as <code>/catalog</code>
 * and possibly installed via a <code>.war</code> file.)
 * <p>
 * In the case of a web application marked "distributed" in its deployment
 * descriptor, there will be one context instance for each virtual machine. In
 * this situation, the context cannot be used as a location to share global
 * information (because the information won't be truly global). Use an external
 * resource like a database instead.
 * <p>
 * The <code>ServletContext</code> object is contained within the
 * {@link ServletConfig} object, which the Web server provides the servlet when
 * the servlet is initialized.
 *
 * @see Servlet#getServletConfig
 * @see ServletConfig#getServletContext
 */
public interface ServletContext {

    public static final String TEMPDIR = "javax.servlet.context.tempdir";

    /**
     * @since Servlet 3.0
     */
    public static final String ORDERED_LIBS = "javax.servlet.context.orderedLibs";

    /**
     * Return the main path associated with this context.
     *
     * @return The main context path
     *
     * @since Servlet 2.5
     */
    public String getContextPath();

    /**
     * Returns a <code>ServletContext</code> object that corresponds to a
     * specified URL on the server.
     * <p>
     * This method allows servlets to gain access to the context for various
     * parts of the server, and as needed obtain {@link RequestDispatcher}
     * objects from the context. The given path must be begin with "/", is
     * interpreted relative to the server's document root and is matched against
     * the context roots of other web applications hosted on this container.
     * <p>
     * In a security conscious environment, the servlet container may return
     * <code>null</code> for a given URL.
     *
     * @param uripath
     *            a <code>String</code> specifying the context path of another
     *            web application in the container.
     * @return the <code>ServletContext</code> object that corresponds to the
     *         named URL, or null if either none exists or the container wishes
     *         to restrict this access.
     * @see RequestDispatcher
     */
    public ServletContext getContext(String uripath);

    /**
     * Returns the major version of the Java Servlet API that this servlet
     * container supports. All implementations that comply with Version 3.1 must
     * have this method return the integer 3.
     *
     * @return 3
     */
    public int getMajorVersion();

    /**
     * Returns the minor version of the Servlet API that this servlet container
     * supports. All implementations that comply with Version 3.1 must have this
     * method return the integer 1.
     *
     * @return 1
     */
    public int getMinorVersion();

    /**
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     *
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public int getEffectiveMajorVersion();

    /**
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public int getEffectiveMinorVersion();

    /**
     * Returns the MIME type of the specified file, or <code>null</code> if the
     * MIME type is not known. The MIME type is determined by the configuration
     * of the servlet container, and may be specified in a web application
     * deployment descriptor. Common MIME types are <code>"text/html"</code> and
     * <code>"image/gif"</code>.
     *
     * @param file
     *            a <code>String</code> specifying the name of a file
     * @return a <code>String</code> specifying the file's MIME type
     */
    public String getMimeType(String file);

    /**
     * Returns a directory-like listing of all the paths to resources within the
     * web application whose longest sub-path matches the supplied path
     * argument. Paths indicating subdirectory paths end with a '/'. The
     * returned paths are all relative to the root of the web application and
     * have a leading '/'. For example, for a web application containing<br>
     * <br>
     * /welcome.html<br>
     * /catalog/index.html<br>
     * /catalog/products.html<br>
     * /catalog/offers/books.html<br>
     * /catalog/offers/music.html<br>
     * /customer/login.jsp<br>
     * /WEB-INF/web.xml<br>
     * /WEB-INF/classes/com.acme.OrderServlet.class,<br>
     * <br>
     * getResourcePaths("/") returns {"/welcome.html", "/catalog/",
     * "/customer/", "/WEB-INF/"}<br>
     * getResourcePaths("/catalog/") returns {"/catalog/index.html",
     * "/catalog/products.html", "/catalog/offers/"}.<br>
     *
     * @param path
     *            the partial path used to match the resources, which must start
     *            with a /
     * @return a Set containing the directory listing, or null if there are no
     *         resources in the web application whose path begins with the
     *         supplied path.
     * @since Servlet 2.3
     */
    public Set<String> getResourcePaths(String path);

    /**
     * Returns a URL to the resource that is mapped to a specified path. The
     * path must begin with a "/" and is interpreted as relative to the current
     * context root.
     * <p>
     * This method allows the servlet container to make a resource available to
     * servlets from any source. Resources can be located on a local or remote
     * file system, in a database, or in a <code>.war</code> file.
     * <p>
     * The servlet container must implement the URL handlers and
     * <code>URLConnection</code> objects that are necessary to access the
     * resource.
     * <p>
     * This method returns <code>null</code> if no resource is mapped to the
     * pathname.
     * <p>
     * Some containers may allow writing to the URL returned by this method
     * using the methods of the URL class.
     * <p>
     * The resource content is returned directly, so be aware that requesting a
     * <code>.jsp</code> page returns the JSP source code. Use a
     * <code>RequestDispatcher</code> instead to include results of an
     * execution.
     * <p>
     * This method has a different purpose than
     * <code>java.lang.Class.getResource</code>, which looks up resources based
     * on a class loader. This method does not use class loaders.
     *
     * @param path
     *            a <code>String</code> specifying the path to the resource
     * @return the resource located at the named path, or <code>null</code> if
     *         there is no resource at that path
     * @exception MalformedURLException
     *                if the pathname is not given in the correct form
     */
    public URL getResource(String path) throws MalformedURLException;

    /**
     * Returns the resource located at the named path as an
     * <code>InputStream</code> object.
     * <p>
     * The data in the <code>InputStream</code> can be of any type or length.
     * The path must be specified according to the rules given in
     * <code>getResource</code>. This method returns <code>null</code> if no
     * resource exists at the specified path.
     * <p>
     * Meta-information such as content length and content type that is
     * available via <code>getResource</code> method is lost when using this
     * method.
     * <p>
     * The servlet container must implement the URL handlers and
     * <code>URLConnection</code> objects necessary to access the resource.
     * <p>
     * This method is different from
     * <code>java.lang.Class.getResourceAsStream</code>, which uses a class
     * loader. This method allows servlet containers to make a resource
     * available to a servlet from any location, without using a class loader.
     *
     * @param path
     *            a <code>String</code> specifying the path to the resource
     * @return the <code>InputStream</code> returned to the servlet, or
     *         <code>null</code> if no resource exists at the specified path
     */
    public InputStream getResourceAsStream(String path);

    /**
     * Returns a {@link RequestDispatcher} object that acts as a wrapper for the
     * resource located at the given path. A <code>RequestDispatcher</code>
     * object can be used to forward a request to the resource or to include the
     * resource in a response. The resource can be dynamic or static.
     * <p>
     * The pathname must begin with a "/" and is interpreted as relative to the
     * current context root. Use <code>getContext</code> to obtain a
     * <code>RequestDispatcher</code> for resources in foreign contexts. This
     * method returns <code>null</code> if the <code>ServletContext</code>
     * cannot return a <code>RequestDispatcher</code>.
     *
     * @param path
     *            a <code>String</code> specifying the pathname to the resource
     * @return a <code>RequestDispatcher</code> object that acts as a wrapper for
     *         the resource at the specified path, or <code>null</code> if the
     *         <code>ServletContext</code> cannot return a
     *         <code>RequestDispatcher</code>
     * @see RequestDispatcher
     * @see ServletContext#getContext
     */
    public RequestDispatcher getRequestDispatcher(String path);

    /**
     * Returns a {@link RequestDispatcher} object that acts as a wrapper for the
     * named servlet.
     * <p>
     * Servlets (and JSP pages also) may be given names via server
     * administration or via a web application deployment descriptor. A servlet
     * instance can determine its name using
     * {@link ServletConfig#getServletName}.
     * <p>
     * This method returns <code>null</code> if the <code>ServletContext</code>
     * cannot return a <code>RequestDispatcher</code> for any reason.
     *
     * @param name
     *            a <code>String</code> specifying the name of a servlet to wrap
     * @return a <code>RequestDispatcher</code> object that acts as a wrapper for
     *         the named servlet, or <code>null</code> if the
     *         <code>ServletContext</code> cannot return a
     *         <code>RequestDispatcher</code>
     * @see RequestDispatcher
     * @see ServletContext#getContext
     * @see ServletConfig#getServletName
     */
    public RequestDispatcher getNamedDispatcher(String name);

    /**
     * Do not use. This method was originally defined to retrieve a servlet from
     * a <code>ServletContext</code>. In this version, this method always
     * returns <code>null</code> and remains only to preserve binary
     * compatibility. This method will be permanently removed in a future
     * version of the Java Servlet API.
     * <p>
     * In lieu of this method, servlets can share information using the
     * <code>ServletContext</code> class and can perform shared business logic
     * by invoking methods on common non-servlet classes.
     *
     * @param name Not used
     *
     * @return Always <code>null</code>
     *
     * @throws ServletException never
     *
     * @deprecated As of Java Servlet API 2.1, with no direct replacement.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Servlet getServlet(String name) throws ServletException;

    /**
     * Do not use. This method was originally defined to return an
     * <code>Enumeration</code> of all the servlets known to this servlet
     * context. In this version, this method always returns an empty enumeration
     * and remains only to preserve binary compatibility. This method will be
     * permanently removed in a future version of the Java Servlet API.
     *
     * @return Always and empty Enumeration
     *
     * @deprecated As of Java Servlet API 2.0, with no replacement.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Enumeration<Servlet> getServlets();

    /**
     * Do not use. This method was originally defined to return an
     * <code>Enumeration</code> of all the servlet names known to this context.
     * In this version, this method always returns an empty
     * <code>Enumeration</code> and remains only to preserve binary
     * compatibility. This method will be permanently removed in a future
     * version of the Java Servlet API.
     *
     * @return Always and empty Enumeration
     *
     * @deprecated As of Java Servlet API 2.1, with no replacement.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public Enumeration<String> getServletNames();

    /**
     * Writes the specified message to a servlet log file, usually an event log.
     * The name and type of the servlet log file is specific to the servlet
     * container.
     *
     * @param msg
     *            a <code>String</code> specifying the message to be written to
     *            the log file
     */
    public void log(String msg);

    /**
     * Do not use.
     * @param exception The exception to log
     * @param msg       The message to log with the exception
     * @deprecated As of Java Servlet API 2.1, use
     *             {@link #log(String message, Throwable throwable)} instead.
     *             <p>
     *             This method was originally defined to write an exception's
     *             stack trace and an explanatory error message to the servlet
     *             log file.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public void log(Exception exception, String msg);

    /**
     * Writes an explanatory message and a stack trace for a given
     * <code>Throwable</code> exception to the servlet log file. The name and
     * type of the servlet log file is specific to the servlet container,
     * usually an event log.
     *
     * @param message
     *            a <code>String</code> that describes the error or exception
     * @param throwable
     *            the <code>Throwable</code> error or exception
     */
    public void log(String message, Throwable throwable);

    /**
     * Returns a <code>String</code> containing the real path for a given
     * virtual path. For example, the path "/index.html" returns the absolute
     * file path on the server's filesystem would be served by a request for
     * "http://host/contextPath/index.html", where contextPath is the context
     * path of this ServletContext..
     * <p>
     * The real path returned will be in a form appropriate to the computer and
     * operating system on which the servlet container is running, including the
     * proper path separators. This method returns <code>null</code> if the
     * servlet container cannot translate the virtual path to a real path for
     * any reason (such as when the content is being made available from a
     * <code>.war</code> archive).
     *
     * @param path
     *            a <code>String</code> specifying a virtual path
     * @return a <code>String</code> specifying the real path, or null if the
     *         translation cannot be performed
     */
    public String getRealPath(String path);

    /**
     * Returns the name and version of the servlet container on which the
     * servlet is running.
     * <p>
     * The form of the returned string is
     * <i>servername</i>/<i>versionnumber</i>. For example, the JavaServer Web
     * Development Kit may return the string
     * <code>JavaServer Web Dev Kit/1.0</code>.
     * <p>
     * The servlet container may return other optional information after the
     * primary string in parentheses, for example,
     * <code>JavaServer Web Dev Kit/1.0 (JDK 1.1.6; Windows NT 4.0 x86)</code>.
     *
     * @return a <code>String</code> containing at least the servlet container
     *         name and version number
     */
    public String getServerInfo();

    /**
     * Returns a <code>String</code> containing the value of the named
     * context-wide initialization parameter, or <code>null</code> if the
     * parameter does not exist.
     * <p>
     * This method can make available configuration information useful to an
     * entire "web application". For example, it can provide a webmaster's email
     * address or the name of a system that holds critical data.
     *
     * @param name
     *            a <code>String</code> containing the name of the parameter
     *            whose value is requested
     * @return a <code>String</code> containing the value of the initialization
     *         parameter
     * @see ServletConfig#getInitParameter
     */
    public String getInitParameter(String name);

    /**
     * Returns the names of the context's initialization parameters as an
     * <code>Enumeration</code> of <code>String</code> objects, or an empty
     * <code>Enumeration</code> if the context has no initialization parameters.
     *
     * @return an <code>Enumeration</code> of <code>String</code> objects
     *         containing the names of the context's initialization parameters
     * @see ServletConfig#getInitParameter
     */

    public Enumeration<String> getInitParameterNames();

    /**
     * Set the given initialisation parameter to the given value.
     * @param name  Name of initialisation parameter
     * @param value Value for initialisation parameter
     * @return <code>true</code> if the call succeeds or <code>false</code> if
     *         the call fails because an initialisation parameter with the same
     *         name has already been set
     * @throws IllegalStateException If initialisation of this ServletContext
     *         has already completed
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public boolean setInitParameter(String name, String value);

    /**
     * Returns the servlet container attribute with the given name, or
     * <code>null</code> if there is no attribute by that name. An attribute
     * allows a servlet container to give the servlet additional information not
     * already provided by this interface. See your server documentation for
     * information about its attributes. A list of supported attributes can be
     * retrieved using <code>getAttributeNames</code>.
     * <p>
     * The attribute is returned as a <code>java.lang.Object</code> or some
     * subclass. Attribute names should follow the same convention as package
     * names. The Java Servlet API specification reserves names matching
     * <code>java.*</code>, <code>javax.*</code>, and <code>sun.*</code>.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute
     * @return an <code>Object</code> containing the value of the attribute, or
     *         <code>null</code> if no attribute exists matching the given name
     * @see ServletContext#getAttributeNames
     */
    public Object getAttribute(String name);

    /**
     * Returns an <code>Enumeration</code> containing the attribute names
     * available within this servlet context. Use the {@link #getAttribute}
     * method with an attribute name to get the value of an attribute.
     *
     * @return an <code>Enumeration</code> of attribute names
     * @see #getAttribute
     */
    public Enumeration<String> getAttributeNames();

    /**
     * Binds an object to a given attribute name in this servlet context. If the
     * name specified is already used for an attribute, this method will replace
     * the attribute with the new to the new attribute.
     * <p>
     * If listeners are configured on the <code>ServletContext</code> the
     * container notifies them accordingly.
     * <p>
     * If a null value is passed, the effect is the same as calling
     * <code>removeAttribute()</code>.
     * <p>
     * Attribute names should follow the same convention as package names. The
     * Java Servlet API specification reserves names matching
     * <code>java.*</code>, <code>javax.*</code>, and <code>sun.*</code>.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute
     * @param object
     *            an <code>Object</code> representing the attribute to be bound
     */
    public void setAttribute(String name, Object object);

    /**
     * Removes the attribute with the given name from the servlet context. After
     * removal, subsequent calls to {@link #getAttribute} to retrieve the
     * attribute's value will return <code>null</code>.
     * <p>
     * If listeners are configured on the <code>ServletContext</code> the
     * container notifies them accordingly.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute to
     *            be removed
     */
    public void removeAttribute(String name);

    /**
     * Returns the name of this web application corresponding to this
     * ServletContext as specified in the deployment descriptor for this web
     * application by the display-name element.
     *
     * @return The name of the web application or null if no name has been
     *         declared in the deployment descriptor.
     * @since Servlet 2.3
     */
    public String getServletContextName();

    /**
     * Register a servlet implementation for use in this ServletContext.
     * @param servletName The name of the servlet to register
     * @param className   The implementation class for the servlet
     * @return The registration object that enables further configuration
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public ServletRegistration.Dynamic addServlet(String servletName, String className);

    /**
     * Register a servlet instance for use in this ServletContext.
     * @param servletName The name of the servlet to register
     * @param servlet     The Servlet instance to register
     * @return The registration object that enables further configuration
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public ServletRegistration.Dynamic addServlet(String servletName, Servlet servlet);

    /**
     * Add servlet to context.
     * @param   servletName  Name of servlet to add
     * @param   servletClass Class of servlet to add
     * @return  <code>null</code> if the servlet has already been fully defined,
     *          else a {@link javax.servlet.ServletRegistration.Dynamic} object
     *          that can be used to further configure the servlet
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public ServletRegistration.Dynamic addServlet(String servletName,
            Class<? extends Servlet> servletClass);

    /**
     * TODO SERVLET3 - Add comments
     * @param <T> TODO
     * @param c   TODO
     * @return TODO
     * @throws ServletException TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public <T extends Servlet> T createServlet(Class<T> c)
            throws ServletException;

    /**
     * Obtain the details of the named servlet.
     *
     * @param servletName   The name of the Servlet of interest
     *
     * @return  The registration details for the named Servlet or
     *          <code>null</code> if no Servlet has been registered with the
     *          given name
     *
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     *
     * @since Servlet 3.0
     */
    public ServletRegistration getServletRegistration(String servletName);

    /**
     * TODO SERVLET3 - Add comments
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public Map<String, ? extends ServletRegistration> getServletRegistrations();

    /**
     * Add filter to context.
     * @param   filterName  Name of filter to add
     * @param   className Name of filter class
     * @return  <code>null</code> if the filter has already been fully defined,
     *          else a {@link javax.servlet.FilterRegistration.Dynamic} object
     *          that can be used to further configure the filter
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @since Servlet 3.0
     */
    public FilterRegistration.Dynamic addFilter(String filterName, String className);

    /**
     * Add filter to context.
     * @param   filterName  Name of filter to add
     * @param   filter      Filter to add
     * @return  <code>null</code> if the filter has already been fully defined,
     *          else a {@link javax.servlet.FilterRegistration.Dynamic} object
     *          that can be used to further configure the filter
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @since Servlet 3.0
     */
    public FilterRegistration.Dynamic addFilter(String filterName, Filter filter);

    /**
     * Add filter to context.
     * @param   filterName  Name of filter to add
     * @param   filterClass Class of filter to add
     * @return  <code>null</code> if the filter has already been fully defined,
     *          else a {@link javax.servlet.FilterRegistration.Dynamic} object
     *          that can be used to further configure the filter
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @since Servlet 3.0
     */
    public FilterRegistration.Dynamic addFilter(String filterName,
            Class<? extends Filter> filterClass);

    /**
     * TODO SERVLET3 - Add comments
     * @param <T> TODO
     * @param c   TODO
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws ServletException TODO
     * @since Servlet 3.
     */
    public <T extends Filter> T createFilter(Class<T> c) throws ServletException;

    /**
     * TODO SERVLET3 - Add comments
     * @param filterName TODO
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public FilterRegistration getFilterRegistration(String filterName);

    /**
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public Map<String, ? extends FilterRegistration> getFilterRegistrations();

    /**
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public SessionCookieConfig getSessionCookieConfig();

    /**
     * Configures the available session tracking modes for this web application.
     * @param sessionTrackingModes The session tracking modes to use for this
     *        web application
     * @throws IllegalArgumentException
     *             If sessionTrackingModes specifies
     *             {@link SessionTrackingMode#SSL} in combination with any other
     *             {@link SessionTrackingMode}
     * @throws IllegalStateException
     *             If the context has already been initialised
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public void setSessionTrackingModes(
            Set<SessionTrackingMode> sessionTrackingModes);

    /**
     * Obtains the default session tracking modes for this web application.
     * By default {@link SessionTrackingMode#URL} is always supported, {@link
     * SessionTrackingMode#COOKIE} is supported unless the <code>cookies</code>
     * attribute has been set to <code>false</code> for the context and {@link
     * SessionTrackingMode#SSL} is supported if at least one of the connectors
     * used by this context has the attribute <code>secure</code> set to
     * <code>true</code>.
     * @return The set of default session tracking modes for this web
     *         application
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public Set<SessionTrackingMode> getDefaultSessionTrackingModes();

    /**
     * Obtains the currently enabled session tracking modes for this web
     * application.
     * @return The value supplied via {@link #setSessionTrackingModes(Set)} if
     *         one was previously set, else return the defaults
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public Set<SessionTrackingMode> getEffectiveSessionTrackingModes();

    /**
     * TODO SERVLET3 - Add comments
     * @param className TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public void addListener(String className);

    /**
     * TODO SERVLET3 - Add comments
     * @param <T> TODO
     * @param t   TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public <T extends EventListener> void addListener(T t);

    /**
     * TODO SERVLET3 - Add comments
     * @param listenerClass TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public void addListener(Class<? extends EventListener> listenerClass);

    /**
     * TODO SERVLET3 - Add comments
     * @param <T> TODO
     * @param c TODO
     * @return TODO
     * @throws ServletException TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0
     */
    public <T extends EventListener> T createListener(Class<T> c)
            throws ServletException;

    /**
     * @return TODO
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public JspConfigDescriptor getJspConfigDescriptor();

    /**
     * Get the web application class loader associated with this ServletContext.
     *
     * @return The associated web application class loader
     *
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws SecurityException if access to the class loader is prevented by a
     *         SecurityManager
     * @since Servlet 3.0
     */
    public ClassLoader getClassLoader();

    /**
     * Add to the declared roles for this ServletContext.
     * @param roleNames The roles to add
     * @throws UnsupportedOperationException    If called from a
     *    {@link ServletContextListener#contextInitialized(ServletContextEvent)}
     *    method of a {@link ServletContextListener} that was not defined in a
     *    web.xml file, a web-fragment.xml file nor annotated with
     *    {@link javax.servlet.annotation.WebListener}. For example, a
     *    {@link ServletContextListener} defined in a TLD would not be able to
     *    use this method.
     * @throws IllegalArgumentException If the list of roleNames is null or
     *         empty
     * @throws IllegalStateException If the ServletContext has already been
     *         initialised
     * @since Servlet 3.0
     */
    public void declareRoles(String... roleNames);

    /**
     * Get the primary name of the virtual host on which this context is
     * deployed. The name may or may not be a valid host name.
     *
     * @return The primary name of the virtual host on which this context is
     *         deployed
     * @since Servlet 3.1
     */
    public String getVirtualServerName();
}
```

create a Servlet

### GenericServlet



```java
/**
 * Defines a generic, protocol-independent servlet. To write an HTTP servlet for
 * use on the Web, extend {@link javax.servlet.http.HttpServlet} instead.
 * <p>
 * <code>GenericServlet</code> implements the <code>Servlet</code> and
 * <code>ServletConfig</code> interfaces. <code>GenericServlet</code> may be
 * directly extended by a servlet, although it's more common to extend a
 * protocol-specific subclass such as <code>HttpServlet</code>.
 * <p>
 * <code>GenericServlet</code> makes writing servlets easier. It provides simple
 * versions of the lifecycle methods <code>init</code> and <code>destroy</code>
 * and of the methods in the <code>ServletConfig</code> interface.
 * <code>GenericServlet</code> also implements the <code>log</code> method,
 * declared in the <code>ServletContext</code> interface.
 * <p>
 * To write a generic servlet, you need only override the abstract
 * <code>service</code> method.
 */
public abstract class GenericServlet implements Servlet, ServletConfig,
        java.io.Serializable {

    private static final long serialVersionUID = 1L;

    private transient ServletConfig config;

    /**
     * Does nothing. All of the servlet initialization is done by one of the
     * <code>init</code> methods.
     */
    public GenericServlet() {
        // NOOP
    }

    /**
     * Called by the servlet container to indicate to a servlet that the servlet
     * is being taken out of service. See {@link Servlet#destroy}.
     */
    @Override
    public void destroy() {
        // NOOP by default
    }

    /**
     * Returns a <code>String</code> containing the value of the named
     * initialization parameter, or <code>null</code> if the parameter does not
     * exist. See {@link ServletConfig#getInitParameter}.
     * <p>
     * This method is supplied for convenience. It gets the value of the named
     * parameter from the servlet's <code>ServletConfig</code> object.
     *
     * @param name
     *            a <code>String</code> specifying the name of the
     *            initialization parameter
     * @return String a <code>String</code> containing the value of the
     *         initialization parameter
     */
    @Override
    public String getInitParameter(String name) {
        return getServletConfig().getInitParameter(name);
    }

    /**
     * Returns the names of the servlet's initialization parameters as an
     * <code>Enumeration</code> of <code>String</code> objects, or an empty
     * <code>Enumeration</code> if the servlet has no initialization parameters.
     * See {@link ServletConfig#getInitParameterNames}.
     * <p>
     * This method is supplied for convenience. It gets the parameter names from
     * the servlet's <code>ServletConfig</code> object.
     *
     * @return Enumeration an enumeration of <code>String</code> objects
     *         containing the names of the servlet's initialization parameters
     */
    @Override
    public Enumeration<String> getInitParameterNames() {
        return getServletConfig().getInitParameterNames();
    }

    /**
     * Returns this servlet's {@link ServletConfig} object.
     *
     * @return ServletConfig the <code>ServletConfig</code> object that
     *         initialized this servlet
     */
    @Override
    public ServletConfig getServletConfig() {
        return config;
    }

    /**
     * Returns a reference to the {@link ServletContext} in which this servlet
     * is running. See {@link ServletConfig#getServletContext}.
     * <p>
     * This method is supplied for convenience. It gets the context from the
     * servlet's <code>ServletConfig</code> object.
     *
     * @return ServletContext the <code>ServletContext</code> object passed to
     *         this servlet by the <code>init</code> method
     */
    @Override
    public ServletContext getServletContext() {
        return getServletConfig().getServletContext();
    }

    /**
     * Returns information about the servlet, such as author, version, and
     * copyright. By default, this method returns an empty string. Override this
     * method to have it return a meaningful value. See
     * {@link Servlet#getServletInfo}.
     *
     * @return String information about this servlet, by default an empty string
     */
    @Override
    public String getServletInfo() {
        return "";
    }

    /**
     * Called by the servlet container to indicate to a servlet that the servlet
     * is being placed into service. See {@link Servlet#init}.
     * <p>
     * This implementation stores the {@link ServletConfig} object it receives
     * from the servlet container for later use. When overriding this form of
     * the method, call <code>super.init(config)</code>.
     *
     * @param config
     *            the <code>ServletConfig</code> object that contains
     *            configuration information for this servlet
     * @exception ServletException
     *                if an exception occurs that interrupts the servlet's
     *                normal operation
     * @see UnavailableException
     */
    @Override
    public void init(ServletConfig config) throws ServletException {
        this.config = config;
        this.init();
    }

    /**
     * A convenience method which can be overridden so that there's no need to
     * call <code>super.init(config)</code>.
     * <p>
     * Instead of overriding {@link #init(ServletConfig)}, simply override this
     * method and it will be called by
     * <code>GenericServlet.init(ServletConfig config)</code>. The
     * <code>ServletConfig</code> object can still be retrieved via
     * {@link #getServletConfig}.
     *
     * @exception ServletException
     *                if an exception occurs that interrupts the servlet's
     *                normal operation
     */
    public void init() throws ServletException {
        // NOOP by default
    }

    /**
     * Writes the specified message to a servlet log file, prepended by the
     * servlet's name. See {@link ServletContext#log(String)}.
     *
     * @param msg
     *            a <code>String</code> specifying the message to be written to
     *            the log file
     */
    public void log(String msg) {
        getServletContext().log(getServletName() + ": " + msg);
    }

    /**
     * Writes an explanatory message and a stack trace for a given
     * <code>Throwable</code> exception to the servlet log file, prepended by
     * the servlet's name. See {@link ServletContext#log(String, Throwable)}.
     *
     * @param message
     *            a <code>String</code> that describes the error or exception
     * @param t
     *            the <code>java.lang.Throwable</code> error or exception
     */
    public void log(String message, Throwable t) {
        getServletContext().log(getServletName() + ": " + message, t);
    }

    /**
     * Called by the servlet container to allow the servlet to respond to a
     * request. See {@link Servlet#service}.
     * <p>
     * This method is declared abstract so subclasses, such as
     * <code>HttpServlet</code>, must override it.
     *
     * @param req
     *            the <code>ServletRequest</code> object that contains the
     *            client's request
     * @param res
     *            the <code>ServletResponse</code> object that will contain the
     *            servlet's response
     * @exception ServletException
     *                if an exception occurs that interferes with the servlet's
     *                normal operation occurred
     * @exception IOException
     *                if an input or output exception occurs
     */
    @Override
    public abstract void service(ServletRequest req, ServletResponse res)
            throws ServletException, IOException;

    /**
     * Returns the name of this servlet instance. See
     * {@link ServletConfig#getServletName}.
     *
     * @return the name of this servlet instance
     */
    @Override
    public String getServletName() {
        return config.getServletName();
    }
}
```



### HttpServlet

```java

/**
 * Provides an abstract class to be subclassed to create
 * an HTTP servlet suitable for a Web site. A subclass of
 * <code>HttpServlet</code> must override at least
 * one method, usually one of these:
 *
 * <ul>
 * <li> <code>doGet</code>, if the servlet supports HTTP GET requests
 * <li> <code>doPost</code>, for HTTP POST requests
 * <li> <code>doPut</code>, for HTTP PUT requests
 * <li> <code>doDelete</code>, for HTTP DELETE requests
 * <li> <code>init</code> and <code>destroy</code>,
 * to manage resources that are held for the life of the servlet
 * <li> <code>getServletInfo</code>, which the servlet uses to
 * provide information about itself
 * </ul>
 *
 * <p>There's almost no reason to override the <code>service</code>
 * method. <code>service</code> handles standard HTTP
 * requests by dispatching them to the handler methods
 * for each HTTP request type (the <code>do</code><i>Method</i>
 * methods listed above).
 *
 * <p>Likewise, there's almost no reason to override the
 * <code>doOptions</code> and <code>doTrace</code> methods.
 *
 * <p>Servlets typically run on multithreaded servers,
 * so be aware that a servlet must handle concurrent
 * requests and be careful to synchronize access to shared resources.
 * Shared resources include in-memory data such as
 * instance or class variables and external objects
 * such as files, database connections, and network
 * connections.
 * See the
 * <a href="http://java.sun.com/Series/Tutorial/java/threads/multithreaded.html">
 * Java Tutorial on Multithreaded Programming</a> for more
 * information on handling multiple threads in a Java program.
 */
public abstract class HttpServlet extends GenericServlet {

    private static final long serialVersionUID = 1L;

    private static final String METHOD_DELETE = "DELETE";
    private static final String METHOD_HEAD = "HEAD";
    private static final String METHOD_GET = "GET";
    private static final String METHOD_OPTIONS = "OPTIONS";
    private static final String METHOD_POST = "POST";
    private static final String METHOD_PUT = "PUT";
    private static final String METHOD_TRACE = "TRACE";

    private static final String HEADER_IFMODSINCE = "If-Modified-Since";
    private static final String HEADER_LASTMOD = "Last-Modified";

    private static final String LSTRING_FILE =
        "javax.servlet.http.LocalStrings";
    private static final ResourceBundle lStrings =
        ResourceBundle.getBundle(LSTRING_FILE);


    /**
     * Does nothing, because this is an abstract class.
     */
    public HttpServlet() {
        // NOOP
    }


    /**
     * Called by the server (via the <code>service</code> method) to
     * allow a servlet to handle a GET request.
     *
     * <p>Overriding this method to support a GET request also
     * automatically supports an HTTP HEAD request. A HEAD
     * request is a GET request that returns no body in the
     * response, only the request header fields.
     *
     * <p>When overriding this method, read the request data,
     * write the response headers, get the response's writer or
     * output stream object, and finally, write the response data.
     * It's best to include content type and encoding. When using
     * a <code>PrintWriter</code> object to return the response,
     * set the content type before accessing the
     * <code>PrintWriter</code> object.
     *
     * <p>The servlet container must write the headers before
     * committing the response, because in HTTP the headers must be sent
     * before the response body.
     *
     * <p>Where possible, set the Content-Length header (with the
     * {@link javax.servlet.ServletResponse#setContentLength} method),
     * to allow the servlet container to use a persistent connection
     * to return its response to the client, improving performance.
     * The content length is automatically set if the entire response fits
     * inside the response buffer.
     *
     * <p>When using HTTP 1.1 chunked encoding (which means that the response
     * has a Transfer-Encoding header), do not set the Content-Length header.
     *
     * <p>The GET method should be safe, that is, without
     * any side effects for which users are held responsible.
     * For example, most form queries have no side effects.
     * If a client request is intended to change stored data,
     * the request should use some other HTTP method.
     *
     * <p>The GET method should also be idempotent, meaning
     * that it can be safely repeated. Sometimes making a
     * method safe also makes it idempotent. For example,
     * repeating queries is both safe and idempotent, but
     * buying a product online or modifying data is neither
     * safe nor idempotent.
     *
     * <p>If the request is incorrectly formatted, <code>doGet</code>
     * returns an HTTP "Bad Request" message.
     *
     * @param req   an {@link HttpServletRequest} object that
     *                  contains the request the client has made
     *                  of the servlet
     *
     * @param resp  an {@link HttpServletResponse} object that
     *                  contains the response the servlet sends
     *                  to the client
     *
     * @exception IOException   if an input or output error is
     *                              detected when the servlet handles
     *                              the GET request
     *
     * @exception ServletException  if the request for the GET
     *                                  could not be handled
     *
     * @see javax.servlet.ServletResponse#setContentType
     */
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


    /**
     * Returns the time the <code>HttpServletRequest</code>
     * object was last modified,
     * in milliseconds since midnight January 1, 1970 GMT.
     * If the time is unknown, this method returns a negative
     * number (the default).
     *
     * <p>Servlets that support HTTP GET requests and can quickly determine
     * their last modification time should override this method.
     * This makes browser and proxy caches work more effectively,
     * reducing the load on server and network resources.
     *
     * @param req   the <code>HttpServletRequest</code>
     *                  object that is sent to the servlet
     *
     * @return  a <code>long</code> integer specifying
     *              the time the <code>HttpServletRequest</code>
     *              object was last modified, in milliseconds
     *              since midnight, January 1, 1970 GMT, or
     *              -1 if the time is not known
     */
    protected long getLastModified(HttpServletRequest req) {
        return -1;
    }


    /**
     * <p>Receives an HTTP HEAD request from the protected
     * <code>service</code> method and handles the
     * request.
     * The client sends a HEAD request when it wants
     * to see only the headers of a response, such as
     * Content-Type or Content-Length. The HTTP HEAD
     * method counts the output bytes in the response
     * to set the Content-Length header accurately.
     *
     * <p>If you override this method, you can avoid computing
     * the response body and just set the response headers
     * directly to improve performance. Make sure that the
     * <code>doHead</code> method you write is both safe
     * and idempotent (that is, protects itself from being
     * called multiple times for one HTTP HEAD request).
     *
     * <p>If the HTTP HEAD request is incorrectly formatted,
     * <code>doHead</code> returns an HTTP "Bad Request"
     * message.
     *
     * @param req   the request object that is passed to the servlet
     *
     * @param resp  the response object that the servlet
     *                  uses to return the headers to the client
     *
     * @exception IOException   if an input or output error occurs
     *
     * @exception ServletException  if the request for the HEAD
     *                                  could not be handled
     */
    protected void doHead(HttpServletRequest req, HttpServletResponse resp)
        throws ServletException, IOException {

        if (DispatcherType.INCLUDE.equals(req.getDispatcherType())) {
            doGet(req, resp);
        } else {
            NoBodyResponse response = new NoBodyResponse(resp);
            doGet(req, response);
            response.setContentLength();
        }
    }


    /**
     * Called by the server (via the <code>service</code> method)
     * to allow a servlet to handle a POST request.
     *
     * The HTTP POST method allows the client to send
     * data of unlimited length to the Web server a single time
     * and is useful when posting information such as
     * credit card numbers.
     *
     * <p>When overriding this method, read the request data,
     * write the response headers, get the response's writer or output
     * stream object, and finally, write the response data. It's best
     * to include content type and encoding. When using a
     * <code>PrintWriter</code> object to return the response, set the
     * content type before accessing the <code>PrintWriter</code> object.
     *
     * <p>The servlet container must write the headers before committing the
     * response, because in HTTP the headers must be sent before the
     * response body.
     *
     * <p>Where possible, set the Content-Length header (with the
     * {@link javax.servlet.ServletResponse#setContentLength} method),
     * to allow the servlet container to use a persistent connection
     * to return its response to the client, improving performance.
     * The content length is automatically set if the entire response fits
     * inside the response buffer.
     *
     * <p>When using HTTP 1.1 chunked encoding (which means that the response
     * has a Transfer-Encoding header), do not set the Content-Length header.
     *
     * <p>This method does not need to be either safe or idempotent.
     * Operations requested through POST can have side effects for
     * which the user can be held accountable, for example,
     * updating stored data or buying items online.
     *
     * <p>If the HTTP POST request is incorrectly formatted,
     * <code>doPost</code> returns an HTTP "Bad Request" message.
     *
     *
     * @param req   an {@link HttpServletRequest} object that
     *                  contains the request the client has made
     *                  of the servlet
     *
     * @param resp  an {@link HttpServletResponse} object that
     *                  contains the response the servlet sends
     *                  to the client
     *
     * @exception IOException   if an input or output error is
     *                              detected when the servlet handles
     *                              the request
     *
     * @exception ServletException  if the request for the POST
     *                                  could not be handled
     *
     * @see javax.servlet.ServletOutputStream
     * @see javax.servlet.ServletResponse#setContentType
     */
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


    /**
     * Called by the server (via the <code>service</code> method)
     * to allow a servlet to handle a PUT request.
     *
     * The PUT operation allows a client to
     * place a file on the server and is similar to
     * sending a file by FTP.
     *
     * <p>When overriding this method, leave intact
     * any content headers sent with the request (including
     * Content-Length, Content-Type, Content-Transfer-Encoding,
     * Content-Encoding, Content-Base, Content-Language, Content-Location,
     * Content-MD5, and Content-Range). If your method cannot
     * handle a content header, it must issue an error message
     * (HTTP 501 - Not Implemented) and discard the request.
     * For more information on HTTP 1.1, see RFC 2616
     * <a href="http://www.ietf.org/rfc/rfc2616.txt"></a>.
     *
     * <p>This method does not need to be either safe or idempotent.
     * Operations that <code>doPut</code> performs can have side
     * effects for which the user can be held accountable. When using
     * this method, it may be useful to save a copy of the
     * affected URL in temporary storage.
     *
     * <p>If the HTTP PUT request is incorrectly formatted,
     * <code>doPut</code> returns an HTTP "Bad Request" message.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     * @param resp  the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              PUT request
     *
     * @exception ServletException  if the request for the PUT
     *                                  cannot be handled
     */
    protected void doPut(HttpServletRequest req, HttpServletResponse resp)
        throws ServletException, IOException {

        String protocol = req.getProtocol();
        String msg = lStrings.getString("http.method_put_not_supported");
        if (protocol.endsWith("1.1")) {
            resp.sendError(HttpServletResponse.SC_METHOD_NOT_ALLOWED, msg);
        } else {
            resp.sendError(HttpServletResponse.SC_BAD_REQUEST, msg);
        }
    }


    /**
     * Called by the server (via the <code>service</code> method)
     * to allow a servlet to handle a DELETE request.
     *
     * The DELETE operation allows a client to remove a document
     * or Web page from the server.
     *
     * <p>This method does not need to be either safe
     * or idempotent. Operations requested through
     * DELETE can have side effects for which users
     * can be held accountable. When using
     * this method, it may be useful to save a copy of the
     * affected URL in temporary storage.
     *
     * <p>If the HTTP DELETE request is incorrectly formatted,
     * <code>doDelete</code> returns an HTTP "Bad Request"
     * message.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     *
     * @param resp  the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              DELETE request
     *
     * @exception ServletException  if the request for the
     *                                  DELETE cannot be handled
     */
    protected void doDelete(HttpServletRequest req,
                            HttpServletResponse resp)
        throws ServletException, IOException {

        String protocol = req.getProtocol();
        String msg = lStrings.getString("http.method_delete_not_supported");
        if (protocol.endsWith("1.1")) {
            resp.sendError(HttpServletResponse.SC_METHOD_NOT_ALLOWED, msg);
        } else {
            resp.sendError(HttpServletResponse.SC_BAD_REQUEST, msg);
        }
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


    /**
     * Called by the server (via the <code>service</code> method)
     * to allow a servlet to handle a OPTIONS request.
     *
     * The OPTIONS request determines which HTTP methods
     * the server supports and
     * returns an appropriate header. For example, if a servlet
     * overrides <code>doGet</code>, this method returns the
     * following header:
     *
     * <p><code>Allow: GET, HEAD, TRACE, OPTIONS</code>
     *
     * <p>There's no need to override this method unless the
     * servlet implements new HTTP methods, beyond those
     * implemented by HTTP 1.1.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     * @param resp  the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              OPTIONS request
     *
     * @exception ServletException  if the request for the
     *                                  OPTIONS cannot be handled
     */
    protected void doOptions(HttpServletRequest req,
            HttpServletResponse resp)
        throws ServletException, IOException {

        Method[] methods = getAllDeclaredMethods(this.getClass());

        boolean ALLOW_GET = false;
        boolean ALLOW_HEAD = false;
        boolean ALLOW_POST = false;
        boolean ALLOW_PUT = false;
        boolean ALLOW_DELETE = false;
        boolean ALLOW_TRACE = true;
        boolean ALLOW_OPTIONS = true;

        // Tomcat specific hack to see if TRACE is allowed
        Class<?> clazz = null;
        try {
            clazz = Class.forName("org.apache.catalina.connector.RequestFacade");
            Method getAllowTrace = clazz.getMethod("getAllowTrace", (Class<?>[]) null);
            ALLOW_TRACE = ((Boolean) getAllowTrace.invoke(req, (Object[]) null)).booleanValue();
        } catch (ClassNotFoundException | NoSuchMethodException | SecurityException |
                IllegalAccessException | IllegalArgumentException | InvocationTargetException e) {
            // Ignore. Not running on Tomcat. TRACE is always allowed.
        }
        // End of Tomcat specific hack

        for (int i=0; i<methods.length; i++) {
            Method m = methods[i];

            if (m.getName().equals("doGet")) {
                ALLOW_GET = true;
                ALLOW_HEAD = true;
            }
            if (m.getName().equals("doPost"))
                ALLOW_POST = true;
            if (m.getName().equals("doPut"))
                ALLOW_PUT = true;
            if (m.getName().equals("doDelete"))
                ALLOW_DELETE = true;
        }

        String allow = null;
        if (ALLOW_GET)
            allow=METHOD_GET;
        if (ALLOW_HEAD)
            if (allow==null) allow=METHOD_HEAD;
            else allow += ", " + METHOD_HEAD;
        if (ALLOW_POST)
            if (allow==null) allow=METHOD_POST;
            else allow += ", " + METHOD_POST;
        if (ALLOW_PUT)
            if (allow==null) allow=METHOD_PUT;
            else allow += ", " + METHOD_PUT;
        if (ALLOW_DELETE)
            if (allow==null) allow=METHOD_DELETE;
            else allow += ", " + METHOD_DELETE;
        if (ALLOW_TRACE)
            if (allow==null) allow=METHOD_TRACE;
            else allow += ", " + METHOD_TRACE;
        if (ALLOW_OPTIONS)
            if (allow==null) allow=METHOD_OPTIONS;
            else allow += ", " + METHOD_OPTIONS;

        resp.setHeader("Allow", allow);
    }


    /**
     * Called by the server (via the <code>service</code> method)
     * to allow a servlet to handle a TRACE request.
     *
     * A TRACE returns the headers sent with the TRACE
     * request to the client, so that they can be used in
     * debugging. There's no need to override this method.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     * @param resp  the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              TRACE request
     *
     * @exception ServletException  if the request for the
     *                                  TRACE cannot be handled
     */
    protected void doTrace(HttpServletRequest req, HttpServletResponse resp)
        throws ServletException, IOException
    {

        int responseLength;

        String CRLF = "\r\n";
        StringBuilder buffer = new StringBuilder("TRACE ").append(req.getRequestURI())
            .append(" ").append(req.getProtocol());

        Enumeration<String> reqHeaderEnum = req.getHeaderNames();

        while( reqHeaderEnum.hasMoreElements() ) {
            String headerName = reqHeaderEnum.nextElement();
            buffer.append(CRLF).append(headerName).append(": ")
                .append(req.getHeader(headerName));
        }

        buffer.append(CRLF);

        responseLength = buffer.length();

        resp.setContentType("message/http");
        resp.setContentLength(responseLength);
        ServletOutputStream out = resp.getOutputStream();
        out.print(buffer.toString());
        out.close();
        return;
    }


    /**
     * Receives standard HTTP requests from the public
     * <code>service</code> method and dispatches
     * them to the <code>do</code><i>Method</i> methods defined in
     * this class. This method is an HTTP-specific version of the
     * {@link javax.servlet.Servlet#service} method. There's no
     * need to override this method.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     * @param resp  the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              HTTP request
     *
     * @exception ServletException  if the HTTP request
     *                                  cannot be handled
     *
     * @see javax.servlet.Servlet#service
     */
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


    /*
     * Sets the Last-Modified entity header field, if it has not
     * already been set and if the value is meaningful.  Called before
     * doGet, to ensure that headers are set before response data is
     * written.  A subclass might have set this header already, so we
     * check.
     */
    private void maybeSetLastModified(HttpServletResponse resp,
                                      long lastModified) {
        if (resp.containsHeader(HEADER_LASTMOD))
            return;
        if (lastModified >= 0)
            resp.setDateHeader(HEADER_LASTMOD, lastModified);
    }


    /**
     * Dispatches client requests to the protected
     * <code>service</code> method. There's no need to
     * override this method.
     *
     * @param req   the {@link HttpServletRequest} object that
     *                  contains the request the client made of
     *                  the servlet
     *
     * @param res   the {@link HttpServletResponse} object that
     *                  contains the response the servlet returns
     *                  to the client
     *
     * @exception IOException   if an input or output error occurs
     *                              while the servlet is handling the
     *                              HTTP request
     *
     * @exception ServletException  if the HTTP request cannot
     *                                  be handled
     *
     * @see javax.servlet.Servlet#service
     */
    @Override
    public void service(ServletRequest req, ServletResponse res)
        throws ServletException, IOException {

        HttpServletRequest  request;
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


/*
 * A response wrapper for use in (dumb) "HEAD" support.
 * This just swallows that body, counting the bytes in order to set
 * the content length appropriately.  All other methods delegate to the
 * wrapped HTTP Servlet Response object.
 */
// file private
class NoBodyResponse extends HttpServletResponseWrapper {
    private final NoBodyOutputStream noBody;
    private PrintWriter writer;
    private boolean didSetContentLength;

    // file private
    NoBodyResponse(HttpServletResponse r) {
        super(r);
        noBody = new NoBodyOutputStream();
    }

    // file private
    void setContentLength() {
        if (!didSetContentLength) {
            if (writer != null) {
                writer.flush();
            }
            super.setContentLength(noBody.getContentLength());
        }
    }


    // SERVLET RESPONSE interface methods

    @Override
    public void setContentLength(int len) {
        super.setContentLength(len);
        didSetContentLength = true;
    }

    @Override
    public void setContentLengthLong(long len) {
        super.setContentLengthLong(len);
        didSetContentLength = true;
    }

    @Override
    public void setHeader(String name, String value) {
        super.setHeader(name, value);
        checkHeader(name);
    }

    @Override
    public void addHeader(String name, String value) {
        super.addHeader(name, value);
        checkHeader(name);
    }

    @Override
    public void setIntHeader(String name, int value) {
        super.setIntHeader(name, value);
        checkHeader(name);
    }

    @Override
    public void addIntHeader(String name, int value) {
        super.addIntHeader(name, value);
        checkHeader(name);
    }

    private void checkHeader(String name) {
        if ("content-length".equalsIgnoreCase(name)) {
            didSetContentLength = true;
        }
    }

    @Override
    public ServletOutputStream getOutputStream() throws IOException {
        return noBody;
    }

    @Override
    public PrintWriter getWriter() throws UnsupportedEncodingException {

        if (writer == null) {
            OutputStreamWriter w;

            w = new OutputStreamWriter(noBody, getCharacterEncoding());
            writer = new PrintWriter(w);
        }
        return writer;
    }
}


/*
 * Servlet output stream that gobbles up all its data.
 */

// file private
class NoBodyOutputStream extends ServletOutputStream {

    private static final String LSTRING_FILE =
        "javax.servlet.http.LocalStrings";
    private static final ResourceBundle lStrings =
        ResourceBundle.getBundle(LSTRING_FILE);

    private int contentLength = 0;

    // file private
    NoBodyOutputStream() {
        // NOOP
    }

    // file private
    int getContentLength() {
        return contentLength;
    }

    @Override
    public void write(int b) {
        contentLength++;
    }

    @Override
    public void write(byte buf[], int offset, int len) throws IOException {
        if (buf == null) {
            throw new NullPointerException(
                    lStrings.getString("err.io.nullArray"));
        }

        if (offset < 0 || len < 0 || offset+len > buf.length) {
            String msg = lStrings.getString("err.io.indexOutOfBounds");
            Object[] msgArgs = new Object[3];
            msgArgs[0] = Integer.valueOf(offset);
            msgArgs[1] = Integer.valueOf(len);
            msgArgs[2] = Integer.valueOf(buf.length);
            msg = MessageFormat.format(msg, msgArgs);
            throw new IndexOutOfBoundsException(msg);
        }

        contentLength += len;
    }

    @Override
    public boolean isReady() {
        // TODO SERVLET 3.1
        return false;
    }

    @Override
    public void setWriteListener(javax.servlet.WriteListener listener) {
        // TODO SERVLET 3.1
    }
}
```


## Request/Response

### ServletRequest

```java
/**
 * Defines an object to provide client request information to a servlet. The
 * servlet container creates a <code>ServletRequest</code> object and passes it
 * as an argument to the servlet's <code>service</code> method.
 * <p>
 * A <code>ServletRequest</code> object provides data including parameter name
 * and values, attributes, and an input stream. Interfaces that extend
 * <code>ServletRequest</code> can provide additional protocol-specific data
 * (for example, HTTP data is provided by
 * {@link javax.servlet.http.HttpServletRequest}.
 *
 * @see javax.servlet.http.HttpServletRequest
 */
public interface ServletRequest {

    /**
     * Returns the value of the named attribute as an <code>Object</code>, or
     * <code>null</code> if no attribute of the given name exists.
     * <p>
     * Attributes can be set two ways. The servlet container may set attributes
     * to make available custom information about a request. For example, for
     * requests made using HTTPS, the attribute
     * <code>javax.servlet.request.X509Certificate</code> can be used to
     * retrieve information on the certificate of the client. Attributes can
     * also be set programmatically using {@link ServletRequest#setAttribute}.
     * This allows information to be embedded into a request before a
     * {@link RequestDispatcher} call.
     * <p>
     * Attribute names should follow the same conventions as package names.
     * Names beginning with <code>java.*</code> and <code>javax.*</code> are
     * reserved for use by the Servlet specification. Names beginning with
     * <code>sun.*</code>, <code>com.sun.*</code>, <code>oracle.*</code> and
     * <code>com.oracle.*</code>) are reserved for use by Oracle Corporation.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute
     * @return an <code>Object</code> containing the value of the attribute, or
     *         <code>null</code> if the attribute does not exist
     */
    public Object getAttribute(String name);

    /**
     * Returns an <code>Enumeration</code> containing the names of the
     * attributes available to this request. This method returns an empty
     * <code>Enumeration</code> if the request has no attributes available to
     * it.
     *
     * @return an <code>Enumeration</code> of strings containing the names of the
     *         request's attributes
     */
    public Enumeration<String> getAttributeNames();

    /**
     * Returns the name of the character encoding used in the body of this
     * request. This method returns <code>null</code> if the request does not
     * specify a character encoding
     *
     * @return a <code>String</code> containing the name of the character
     *         encoding, or <code>null</code> if the request does not specify a
     *         character encoding
     */
    public String getCharacterEncoding();

    /**
     * Overrides the name of the character encoding used in the body of this
     * request. This method must be called prior to reading request parameters
     * or reading input using getReader().
     *
     * @param env
     *            a <code>String</code> containing the name of the character
     *            encoding.
     * @throws java.io.UnsupportedEncodingException
     *             if this is not a valid encoding
     */
    public void setCharacterEncoding(String env)
            throws java.io.UnsupportedEncodingException;

    /**
     * Returns the length, in bytes, of the request body and made available by
     * the input stream, or -1 if the length is not known. For HTTP servlets,
     * same as the value of the CGI variable CONTENT_LENGTH.
     *
     * @return an integer containing the length of the request body or -1 if the
     *         length is not known or is greater than {@link Integer#MAX_VALUE}
     */
    public int getContentLength();

    /**
     * Returns the length, in bytes, of the request body and made available by
     * the input stream, or -1 if the length is not known. For HTTP servlets,
     * same as the value of the CGI variable CONTENT_LENGTH.
     *
     * @return a long integer containing the length of the request body or -1 if
     *         the length is not known
     * @since Servlet 3.1
     */
    public long getContentLengthLong();

    /**
     * Returns the MIME type of the body of the request, or <code>null</code> if
     * the type is not known. For HTTP servlets, same as the value of the CGI
     * variable CONTENT_TYPE.
     *
     * @return a <code>String</code> containing the name of the MIME type of the
     *         request, or null if the type is not known
     */
    public String getContentType();

    /**
     * Retrieves the body of the request as binary data using a
     * {@link ServletInputStream}. Either this method or {@link #getReader} may
     * be called to read the body, not both.
     *
     * @return a {@link ServletInputStream} object containing the body of the
     *         request
     * @exception IllegalStateException
     *                if the {@link #getReader} method has already been called
     *                for this request
     * @exception IOException
     *                if an input or output exception occurred
     */
    public ServletInputStream getInputStream() throws IOException;

    /**
     * Returns the value of a request parameter as a <code>String</code>, or
     * <code>null</code> if the parameter does not exist. Request parameters are
     * extra information sent with the request. For HTTP servlets, parameters
     * are contained in the query string or posted form data.
     * <p>
     * You should only use this method when you are sure the parameter has only
     * one value. If the parameter might have more than one value, use
     * {@link #getParameterValues}.
     * <p>
     * If you use this method with a multivalued parameter, the value returned
     * is equal to the first value in the array returned by
     * <code>getParameterValues</code>.
     * <p>
     * If the parameter data was sent in the request body, such as occurs with
     * an HTTP POST request, then reading the body directly via
     * {@link #getInputStream} or {@link #getReader} can interfere with the
     * execution of this method.
     *
     * @param name
     *            a <code>String</code> specifying the name of the parameter
     * @return a <code>String</code> representing the single value of the
     *         parameter
     * @see #getParameterValues
     */
    public String getParameter(String name);

    /**
     * Returns an <code>Enumeration</code> of <code>String</code> objects
     * containing the names of the parameters contained in this request. If the
     * request has no parameters, the method returns an empty
     * <code>Enumeration</code>.
     *
     * @return an <code>Enumeration</code> of <code>String</code> objects, each
     *         <code>String</code> containing the name of a request parameter;
     *         or an empty <code>Enumeration</code> if the request has no
     *         parameters
     */
    public Enumeration<String> getParameterNames();

    /**
     * Returns an array of <code>String</code> objects containing all of the
     * values the given request parameter has, or <code>null</code> if the
     * parameter does not exist.
     * <p>
     * If the parameter has a single value, the array has a length of 1.
     *
     * @param name
     *            a <code>String</code> containing the name of the parameter
     *            whose value is requested
     * @return an array of <code>String</code> objects containing the parameter's
     *         values
     * @see #getParameter
     */
    public String[] getParameterValues(String name);

    /**
     * Returns a java.util.Map of the parameters of this request. Request
     * parameters are extra information sent with the request. For HTTP
     * servlets, parameters are contained in the query string or posted form
     * data.
     *
     * @return an immutable java.util.Map containing parameter names as keys and
     *         parameter values as map values. The keys in the parameter map are
     *         of type String. The values in the parameter map are of type
     *         String array.
     */
    public Map<String, String[]> getParameterMap();

    /**
     * Returns the name and version of the protocol the request uses in the form
     * <i>protocol/majorVersion.minorVersion</i>, for example, HTTP/1.1. For
     * HTTP servlets, the value returned is the same as the value of the CGI
     * variable <code>SERVER_PROTOCOL</code>.
     *
     * @return a <code>String</code> containing the protocol name and version
     *         number
     */
    public String getProtocol();

    /**
     * Returns the name of the scheme used to make this request, for example,
     * <code>http</code>, <code>https</code>, or <code>ftp</code>. Different
     * schemes have different rules for constructing URLs, as noted in RFC 1738.
     *
     * @return a <code>String</code> containing the name of the scheme used to
     *         make this request
     */
    public String getScheme();

    /**
     * Returns the host name of the server to which the request was sent. It is
     * the value of the part before ":" in the <code>Host</code> header value,
     * if any, or the resolved server name, or the server IP address.
     *
     * @return a <code>String</code> containing the name of the server
     */
    public String getServerName();

    /**
     * Returns the port number to which the request was sent. It is the value of
     * the part after ":" in the <code>Host</code> header value, if any, or the
     * server port where the client connection was accepted on.
     *
     * @return an integer specifying the port number
     */
    public int getServerPort();

    /**
     * Retrieves the body of the request as character data using a
     * <code>BufferedReader</code>. The reader translates the character data
     * according to the character encoding used on the body. Either this method
     * or {@link #getInputStream} may be called to read the body, not both.
     *
     * @return a <code>BufferedReader</code> containing the body of the request
     * @exception java.io.UnsupportedEncodingException
     *                if the character set encoding used is not supported and
     *                the text cannot be decoded
     * @exception IllegalStateException
     *                if {@link #getInputStream} method has been called on this
     *                request
     * @exception IOException
     *                if an input or output exception occurred
     * @see #getInputStream
     */
    public BufferedReader getReader() throws IOException;

    /**
     * Returns the Internet Protocol (IP) address of the client or last proxy
     * that sent the request. For HTTP servlets, same as the value of the CGI
     * variable <code>REMOTE_ADDR</code>.
     *
     * @return a <code>String</code> containing the IP address of the client
     *         that sent the request
     */
    public String getRemoteAddr();

    /**
     * Returns the fully qualified name of the client or the last proxy that
     * sent the request. If the engine cannot or chooses not to resolve the
     * hostname (to improve performance), this method returns the dotted-string
     * form of the IP address. For HTTP servlets, same as the value of the CGI
     * variable <code>REMOTE_HOST</code>.
     *
     * @return a <code>String</code> containing the fully qualified name of the
     *         client
     */
    public String getRemoteHost();

    /**
     * Stores an attribute in this request. Attributes are reset between
     * requests. This method is most often used in conjunction with
     * {@link RequestDispatcher}.
     * <p>
     * Attribute names should follow the same conventions as package names.
     * Names beginning with <code>java.*</code> and <code>javax.*</code> are
     * reserved for use by the Servlet specification. Names beginning with
     * <code>sun.*</code>, <code>com.sun.*</code>, <code>oracle.*</code> and
     * <code>com.oracle.*</code>) are reserved for use by Oracle Corporation.
     * <br>
     * If the object passed in is null, the effect is the same as calling
     * {@link #removeAttribute}. <br>
     * It is warned that when the request is dispatched from the servlet resides
     * in a different web application by <code>RequestDispatcher</code>, the
     * object set by this method may not be correctly retrieved in the caller
     * servlet.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute
     * @param o
     *            the <code>Object</code> to be stored
     */
    public void setAttribute(String name, Object o);

    /**
     * Removes an attribute from this request. This method is not generally
     * needed as attributes only persist as long as the request is being
     * handled.
     * <p>
     * Attribute names should follow the same conventions as package names.
     * Names beginning with <code>java.*</code> and <code>javax.*</code> are
     * reserved for use by the Servlet specification. Names beginning with
     * <code>sun.*</code>, <code>com.sun.*</code>, <code>oracle.*</code> and
     * <code>com.oracle.*</code>) are reserved for use by Oracle Corporation.
     *
     * @param name
     *            a <code>String</code> specifying the name of the attribute to
     *            remove
     */
    public void removeAttribute(String name);

    /**
     * Returns the preferred <code>Locale</code> that the client will accept
     * content in, based on the Accept-Language header. If the client request
     * doesn't provide an Accept-Language header, this method returns the
     * default locale for the server.
     *
     * @return the preferred <code>Locale</code> for the client
     */
    public Locale getLocale();

    /**
     * Returns an <code>Enumeration</code> of <code>Locale</code> objects
     * indicating, in decreasing order starting with the preferred locale, the
     * locales that are acceptable to the client based on the Accept-Language
     * header. If the client request doesn't provide an Accept-Language header,
     * this method returns an <code>Enumeration</code> containing one
     * <code>Locale</code>, the default locale for the server.
     *
     * @return an <code>Enumeration</code> of preferred <code>Locale</code>
     *         objects for the client
     */
    public Enumeration<Locale> getLocales();

    /**
     * Returns a boolean indicating whether this request was made using a secure
     * channel, such as HTTPS.
     *
     * @return a boolean indicating if the request was made using a secure
     *         channel
     */
    public boolean isSecure();

    /**
     * Returns a {@link RequestDispatcher} object that acts as a wrapper for the
     * resource located at the given path. A <code>RequestDispatcher</code>
     * object can be used to forward a request to the resource or to include the
     * resource in a response. The resource can be dynamic or static.
     * <p>
     * The pathname specified may be relative, although it cannot extend outside
     * the current servlet context. If the path begins with a "/" it is
     * interpreted as relative to the current context root. This method returns
     * <code>null</code> if the servlet container cannot return a
     * <code>RequestDispatcher</code>.
     * <p>
     * The difference between this method and
     * {@link ServletContext#getRequestDispatcher} is that this method can take
     * a relative path.
     *
     * @param path
     *            a <code>String</code> specifying the pathname to the resource.
     *            If it is relative, it must be relative against the current
     *            servlet.
     * @return a <code>RequestDispatcher</code> object that acts as a wrapper for
     *         the resource at the specified path, or <code>null</code> if the
     *         servlet container cannot return a <code>RequestDispatcher</code>
     * @see RequestDispatcher
     * @see ServletContext#getRequestDispatcher
     */
    public RequestDispatcher getRequestDispatcher(String path);

    /**
     * @param path The virtual path to be converted to a real path
     * @return {@link ServletContext#getRealPath(String)}
     * @deprecated As of Version 2.1 of the Java Servlet API, use
     *             {@link ServletContext#getRealPath} instead.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public String getRealPath(String path);

    /**
     * Returns the Internet Protocol (IP) source port of the client or last
     * proxy that sent the request.
     *
     * @return an integer specifying the port number
     * @since Servlet 2.4
     */
    public int getRemotePort();

    /**
     * Returns the host name of the Internet Protocol (IP) interface on which
     * the request was received.
     *
     * @return a <code>String</code> containing the host name of the IP on which
     *         the request was received.
     * @since Servlet 2.4
     */
    public String getLocalName();

    /**
     * Returns the Internet Protocol (IP) address of the interface on which the
     * request was received.
     *
     * @return a <code>String</code> containing the IP address on which the
     *         request was received.
     * @since Servlet 2.4
     */
    public String getLocalAddr();

    /**
     * Returns the Internet Protocol (IP) port number of the interface on which
     * the request was received.
     *
     * @return an integer specifying the port number
     * @since Servlet 2.4
     */
    public int getLocalPort();

    /**
     * @return TODO
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public ServletContext getServletContext();

    /**
     * @return TODO
     * @throws IllegalStateException If async is not supported for this request
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public AsyncContext startAsync() throws IllegalStateException;

    /**
     * @param servletRequest    The ServletRequest with which to initialise the
     *                          asynchronous context
     * @param servletResponse   The ServletResponse with which to initialise the
     *                          asynchronous context
     * @return TODO
     * @throws IllegalStateException If async is not supported for this request
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public AsyncContext startAsync(ServletRequest servletRequest,
            ServletResponse servletResponse) throws IllegalStateException;

    /**
     * @return TODO
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public boolean isAsyncStarted();

    /**
     * @return TODO
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public boolean isAsyncSupported();

    /**
     * Get the current AsyncContext.
     *
     * @return The current AsyncContext
     *
     * @throws IllegalStateException if the request is not in asynchronous mode
     *         (i.e. @link #isAsyncStarted() is {@code false})
     *
     * @since Servlet 3.0
     */
    public AsyncContext getAsyncContext();

    /**
     * @return TODO
     * @since Servlet 3.0 TODO SERVLET3 - Add comments
     */
    public DispatcherType getDispatcherType();
}
```



### HttpServletRequest

```java
/**
 * Extends the {@link javax.servlet.ServletRequest} interface to provide request
 * information for HTTP servlets.
 * <p>
 * The servlet container creates an <code>HttpServletRequest</code> object and
 * passes it as an argument to the servlet's service methods
 * (<code>doGet</code>, <code>doPost</code>, etc).
 */
public interface HttpServletRequest extends ServletRequest {

    /**
     * String identifier for Basic authentication. Value "BASIC"
     */
    public static final String BASIC_AUTH = "BASIC";
    /**
     * String identifier for Form authentication. Value "FORM"
     */
    public static final String FORM_AUTH = "FORM";
    /**
     * String identifier for Client Certificate authentication. Value
     * "CLIENT_CERT"
     */
    public static final String CLIENT_CERT_AUTH = "CLIENT_CERT";
    /**
     * String identifier for Digest authentication. Value "DIGEST"
     */
    public static final String DIGEST_AUTH = "DIGEST";

    /**
     * Returns the name of the authentication scheme used to protect the
     * servlet. All servlet containers support basic, form and client
     * certificate authentication, and may additionally support digest
     * authentication. If the servlet is not authenticated <code>null</code> is
     * returned.
     * <p>
     * Same as the value of the CGI variable AUTH_TYPE.
     *
     * @return one of the static members BASIC_AUTH, FORM_AUTH, CLIENT_CERT_AUTH,
     *         DIGEST_AUTH (suitable for == comparison) or the
     *         container-specific string indicating the authentication scheme,
     *         or <code>null</code> if the request was not authenticated.
     */
    public String getAuthType();

    /**
     * Returns an array containing all of the <code>Cookie</code> objects the
     * client sent with this request. This method returns <code>null</code> if
     * no cookies were sent.
     *
     * @return an array of all the <code>Cookies</code> included with this
     *         request, or <code>null</code> if the request has no cookies
     */
    public Cookie[] getCookies();

    /**
     * Returns the value of the specified request header as a <code>long</code>
     * value that represents a <code>Date</code> object. Use this method with
     * headers that contain dates, such as <code>If-Modified-Since</code>.
     * <p>
     * The date is returned as the number of milliseconds since January 1, 1970
     * GMT. The header name is case insensitive.
     * <p>
     * If the request did not have a header of the specified name, this method
     * returns -1. If the header can't be converted to a date, the method throws
     * an <code>IllegalArgumentException</code>.
     *
     * @param name
     *            a <code>String</code> specifying the name of the header
     * @return a <code>long</code> value representing the date specified in the
     *         header expressed as the number of milliseconds since January 1,
     *         1970 GMT, or -1 if the named header was not included with the
     *         request
     * @exception IllegalArgumentException
     *                If the header value can't be converted to a date
     */
    public long getDateHeader(String name);

    /**
     * Returns the value of the specified request header as a
     * <code>String</code>. If the request did not include a header of the
     * specified name, this method returns <code>null</code>. If there are
     * multiple headers with the same name, this method returns the first head
     * in the request. The header name is case insensitive. You can use this
     * method with any request header.
     *
     * @param name
     *            a <code>String</code> specifying the header name
     * @return a <code>String</code> containing the value of the requested
     *         header, or <code>null</code> if the request does not have a
     *         header of that name
     */
    public String getHeader(String name);

    /**
     * Returns all the values of the specified request header as an
     * <code>Enumeration</code> of <code>String</code> objects.
     * <p>
     * Some headers, such as <code>Accept-Language</code> can be sent by clients
     * as several headers each with a different value rather than sending the
     * header as a comma separated list.
     * <p>
     * If the request did not include any headers of the specified name, this
     * method returns an empty <code>Enumeration</code>. The header name is case
     * insensitive. You can use this method with any request header.
     *
     * @param name
     *            a <code>String</code> specifying the header name
     * @return an <code>Enumeration</code> containing the values of the requested
     *         header. If the request does not have any headers of that name
     *         return an empty enumeration. If the container does not allow
     *         access to header information, return null
     */
    public Enumeration<String> getHeaders(String name);

    /**
     * Returns an enumeration of all the header names this request contains. If
     * the request has no headers, this method returns an empty enumeration.
     * <p>
     * Some servlet containers do not allow servlets to access headers using
     * this method, in which case this method returns <code>null</code>
     *
     * @return an enumeration of all the header names sent with this request; if
     *         the request has no headers, an empty enumeration; if the servlet
     *         container does not allow servlets to use this method,
     *         <code>null</code>
     */
    public Enumeration<String> getHeaderNames();

    /**
     * Returns the value of the specified request header as an <code>int</code>.
     * If the request does not have a header of the specified name, this method
     * returns -1. If the header cannot be converted to an integer, this method
     * throws a <code>NumberFormatException</code>.
     * <p>
     * The header name is case insensitive.
     *
     * @param name
     *            a <code>String</code> specifying the name of a request header
     * @return an integer expressing the value of the request header or -1 if the
     *         request doesn't have a header of this name
     * @exception NumberFormatException
     *                If the header value can't be converted to an
     *                <code>int</code>
     */
    public int getIntHeader(String name);

    /**
     * Returns the name of the HTTP method with which this request was made, for
     * example, GET, POST, or PUT. Same as the value of the CGI variable
     * REQUEST_METHOD.
     *
     * @return a <code>String</code> specifying the name of the method with
     *         which this request was made
     */
    public String getMethod();

    /**
     * Returns any extra path information associated with the URL the client
     * sent when it made this request. The extra path information follows the
     * servlet path but precedes the query string and will start with a "/"
     * character.
     * <p>
     * This method returns <code>null</code> if there was no extra path
     * information.
     * <p>
     * Same as the value of the CGI variable PATH_INFO.
     *
     * @return a <code>String</code>, decoded by the web container, specifying
     *         extra path information that comes after the servlet path but
     *         before the query string in the request URL; or <code>null</code>
     *         if the URL does not have any extra path information
     */
    public String getPathInfo();

    /**
     * Returns any extra path information after the servlet name but before the
     * query string, and translates it to a real path. Same as the value of the
     * CGI variable PATH_TRANSLATED.
     * <p>
     * If the URL does not have any extra path information, this method returns
     * <code>null</code> or the servlet container cannot translate the virtual
     * path to a real path for any reason (such as when the web application is
     * executed from an archive). The web container does not decode this string.
     *
     * @return a <code>String</code> specifying the real path, or
     *         <code>null</code> if the URL does not have any extra path
     *         information
     */
    public String getPathTranslated();

    /**
     * Returns the portion of the request URI that indicates the context of the
     * request. The context path always comes first in a request URI. The path
     * starts with a "/" character but does not end with a "/" character. For
     * servlets in the default (root) context, this method returns "". The
     * container does not decode this string.
     *
     * @return a <code>String</code> specifying the portion of the request URI
     *         that indicates the context of the request
     */
    public String getContextPath();

    /**
     * Returns the query string that is contained in the request URL after the
     * path. This method returns <code>null</code> if the URL does not have a
     * query string. Same as the value of the CGI variable QUERY_STRING.
     *
     * @return a <code>String</code> containing the query string or
     *         <code>null</code> if the URL contains no query string. The value
     *         is not decoded by the container.
     */
    public String getQueryString();

    /**
     * Returns the login of the user making this request, if the user has been
     * authenticated, or <code>null</code> if the user has not been
     * authenticated. Whether the user name is sent with each subsequent request
     * depends on the browser and type of authentication. Same as the value of
     * the CGI variable REMOTE_USER.
     *
     * @return a <code>String</code> specifying the login of the user making
     *         this request, or <code>null</code> if the user login is not known
     */
    public String getRemoteUser();

    /**
     * Returns a boolean indicating whether the authenticated user is included
     * in the specified logical "role". Roles and role membership can be defined
     * using deployment descriptors. If the user has not been authenticated, the
     * method returns <code>false</code>.
     *
     * @param role
     *            a <code>String</code> specifying the name of the role
     * @return a <code>boolean</code> indicating whether the user making this
     *         request belongs to a given role; <code>false</code> if the user
     *         has not been authenticated
     */
    public boolean isUserInRole(String role);

    /**
     * Returns a <code>java.security.Principal</code> object containing the name
     * of the current authenticated user. If the user has not been
     * authenticated, the method returns <code>null</code>.
     *
     * @return a <code>java.security.Principal</code> containing the name of the
     *         user making this request; <code>null</code> if the user has not
     *         been authenticated
     */
    public java.security.Principal getUserPrincipal();

    /**
     * Returns the session ID specified by the client. This may not be the same
     * as the ID of the current valid session for this request. If the client
     * did not specify a session ID, this method returns <code>null</code>.
     *
     * @return a <code>String</code> specifying the session ID, or
     *         <code>null</code> if the request did not specify a session ID
     * @see #isRequestedSessionIdValid
     */
    public String getRequestedSessionId();

    /**
     * Returns the part of this request's URL from the protocol name up to the
     * query string in the first line of the HTTP request. The web container
     * does not decode this String. For example:
     * <table summary="Examples of Returned Values">
     * <tr align=left>
     * <th>First line of HTTP request</th>
     * <th>Returned Value</th>
     * <tr>
     * <td>POST /some/path.html HTTP/1.1
     * <td>
     * <td>/some/path.html
     * <tr>
     * <td>GET http://foo.bar/a.html HTTP/1.0
     * <td>
     * <td>/a.html
     * <tr>
     * <td>HEAD /xyz?a=b HTTP/1.1
     * <td>
     * <td>/xyz
     * </table>
     * <p>
     * To reconstruct an URL with a scheme and host, use
     * {@link #getRequestURL}.
     *
     * @return a <code>String</code> containing the part of the URL from the
     *         protocol name up to the query string
     * @see #getRequestURL
     */
    public String getRequestURI();

    /**
     * Reconstructs the URL the client used to make the request. The returned
     * URL contains a protocol, server name, port number, and server path, but
     * it does not include query string parameters.
     * <p>
     * Because this method returns a <code>StringBuffer</code>, not a string,
     * you can modify the URL easily, for example, to append query parameters.
     * <p>
     * This method is useful for creating redirect messages and for reporting
     * errors.
     *
     * @return a <code>StringBuffer</code> object containing the reconstructed
     *         URL
     */
    public StringBuffer getRequestURL();

    /**
     * Returns the part of this request's URL that calls the servlet. This path
     * starts with a "/" character and includes either the servlet name or a
     * path to the servlet, but does not include any extra path information or a
     * query string. Same as the value of the CGI variable SCRIPT_NAME.
     * <p>
     * This method will return an empty string ("") if the servlet used to
     * process this request was matched using the "/*" pattern.
     *
     * @return a <code>String</code> containing the name or path of the servlet
     *         being called, as specified in the request URL, decoded, or an
     *         empty string if the servlet used to process the request is
     *         matched using the "/*" pattern.
     */
    public String getServletPath();

    /**
     * Returns the current <code>HttpSession</code> associated with this request
     * or, if there is no current session and <code>create</code> is true,
     * returns a new session.
     * <p>
     * If <code>create</code> is <code>false</code> and the request has no valid
     * <code>HttpSession</code>, this method returns <code>null</code>.
     * <p>
     * To make sure the session is properly maintained, you must call this
     * method before the response is committed. If the container is using
     * cookies to maintain session integrity and is asked to create a new
     * session when the response is committed, an IllegalStateException is
     * thrown.
     *
     * @param create
     *            <code>true</code> to create a new session for this request if
     *            necessary; <code>false</code> to return <code>null</code> if
     *            there's no current session
     * @return the <code>HttpSession</code> associated with this request or
     *         <code>null</code> if <code>create</code> is <code>false</code>
     *         and the request has no valid session
     * @see #getSession()
     */
    public HttpSession getSession(boolean create);

    /**
     * Returns the current session associated with this request, or if the
     * request does not have a session, creates one.
     *
     * @return the <code>HttpSession</code> associated with this request
     * @see #getSession(boolean)
     */
    public HttpSession getSession();

    /**
     * Changes the session ID of the session associated with this request. This
     * method does not create a new session object it only changes the ID of the
     * current session.
     *
     * @return the new session ID allocated to the session
     * @see HttpSessionIdListener
     * @since Servlet 3.1
     */
    public String changeSessionId();

    /**
     * Checks whether the requested session ID is still valid.
     *
     * @return <code>true</code> if this request has an id for a valid session
     *         in the current session context; <code>false</code> otherwise
     * @see #getRequestedSessionId
     * @see #getSession
     */
    public boolean isRequestedSessionIdValid();

    /**
     * Checks whether the requested session ID came in as a cookie.
     *
     * @return <code>true</code> if the session ID came in as a cookie;
     *         otherwise, <code>false</code>
     * @see #getSession
     */
    public boolean isRequestedSessionIdFromCookie();

    /**
     * Checks whether the requested session ID came in as part of the request
     * URL.
     *
     * @return <code>true</code> if the session ID came in as part of a URL;
     *         otherwise, <code>false</code>
     * @see #getSession
     */
    public boolean isRequestedSessionIdFromURL();

    /**
     * @return {@link #isRequestedSessionIdFromURL()}
     * @deprecated As of Version 2.1 of the Java Servlet API, use
     *             {@link #isRequestedSessionIdFromURL} instead.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public boolean isRequestedSessionIdFromUrl();

    /**
     * Triggers the same authentication process as would be triggered if the
     * request is for a resource that is protected by a security constraint.
     *
     * @param response  The response to use to return any authentication
     *                  challenge
     * @return <code>true</code> if the user is successfully authenticated and
     *         <code>false</code> if not
     *
     * @throws IOException if the authentication process attempted to read from
     *         the request or write to the response and an I/O error occurred
     * @throws IllegalStateException if the authentication process attempted to
     *         write to the response after it had been committed
     * @throws ServletException if the authentication failed and the caller is
     *         expected to handle the failure
     * @since Servlet 3.0
     */
    public boolean authenticate(HttpServletResponse response)
            throws IOException, ServletException;

    /**
     * Authenticate the provided user name and password and then associated the
     * authenticated user with the request.
     *
     * @param username  The user name to authenticate
     * @param password  The password to use to authenticate the user
     *
     * @throws ServletException
     *             If any of {@link #getRemoteUser()},
     *             {@link #getUserPrincipal()} or {@link #getAuthType()} are
     *             non-null, if the configured authenticator does not support
     *             user name and password authentication or if the
     *             authentication fails
     * @since Servlet 3.0
     */
    public void login(String username, String password) throws ServletException;

    /**
     * Removes any authenticated user from the request.
     *
     * @throws ServletException
     *             If the logout fails
     * @since Servlet 3.0
     */
    public void logout() throws ServletException;

    /**
     * Return a collection of all uploaded Parts.
     *
     * @return A collection of all uploaded Parts.
     * @throws IOException
     *             if an I/O error occurs
     * @throws IllegalStateException
     *             if size limits are exceeded or no multipart configuration is
     *             provided
     * @throws ServletException
     *             if the request is not multipart/form-data
     * @since Servlet 3.0
     */
    public Collection<Part> getParts() throws IOException,
            ServletException;

    /**
     * Gets the named Part or null if the Part does not exist. Triggers upload
     * of all Parts.
     *
     * @param name The name of the Part to obtain
     *
     * @return The named Part or null if the Part does not exist
     * @throws IOException
     *             if an I/O error occurs
     * @throws IllegalStateException
     *             if size limits are exceeded
     * @throws ServletException
     *             if the request is not multipart/form-data
     * @since Servlet 3.0
     */
    public Part getPart(String name) throws IOException,
            ServletException;

    /**
     * Start the HTTP upgrade process and pass the connection to the provided
     * protocol handler once the current request/response pair has completed
     * processing. Calling this method sets the response status to {@link
     * HttpServletResponse#SC_SWITCHING_PROTOCOLS} and flushes the response.
     * Protocol specific headers must have already been set before this method
     * is called.
     *
     * @param <T>                     The type of the upgrade handler
     * @param httpUpgradeHandlerClass The class that implements the upgrade
     *                                handler
     *
     * @return A newly created instance of the specified upgrade handler type
     *
     * @throws IOException
     *             if an I/O error occurred during the upgrade
     * @throws ServletException
     *             if the given httpUpgradeHandlerClass fails to be instantiated
     * @since Servlet 3.1
     */
    public <T extends HttpUpgradeHandler> T upgrade(
            Class<T> httpUpgradeHandlerClass) throws java.io.IOException, ServletException;
}
```



### ServletResponse

```java
/**
 * Defines an object to assist a servlet in sending a response to the client.
 * The servlet container creates a <code>ServletResponse</code> object and
 * passes it as an argument to the servlet's <code>service</code> method.
 * <p>
 * To send binary data in a MIME body response, use the
 * {@link ServletOutputStream} returned by {@link #getOutputStream}. To send
 * character data, use the <code>PrintWriter</code> object returned by
 * {@link #getWriter}. To mix binary and text data, for example, to create a
 * multipart response, use a <code>ServletOutputStream</code> and manage the
 * character sections manually.
 * <p>
 * The charset for the MIME body response can be specified explicitly using the
 * {@link #setCharacterEncoding} and {@link #setContentType} methods, or
 * implicitly using the {@link #setLocale} method. Explicit specifications take
 * precedence over implicit specifications. If no charset is specified,
 * ISO-8859-1 will be used. The <code>setCharacterEncoding</code>,
 * <code>setContentType</code>, or <code>setLocale</code> method must be called
 * before <code>getWriter</code> and before committing the response for the
 * character encoding to be used.
 * <p>
 * See the Internet RFCs such as <a href="http://www.ietf.org/rfc/rfc2045.txt">
 * RFC 2045</a> for more information on MIME. Protocols such as SMTP and HTTP
 * define profiles of MIME, and those standards are still evolving.
 *
 * @see ServletOutputStream
 */
public interface ServletResponse {

    /**
     * Returns the name of the character encoding (MIME charset) used for the
     * body sent in this response. The character encoding may have been
     * specified explicitly using the {@link #setCharacterEncoding} or
     * {@link #setContentType} methods, or implicitly using the
     * {@link #setLocale} method. Explicit specifications take precedence over
     * implicit specifications. Calls made to these methods after
     * <code>getWriter</code> has been called or after the response has been
     * committed have no effect on the character encoding. If no character
     * encoding has been specified, <code>ISO-8859-1</code> is returned.
     * <p>
     * See RFC 2047 (http://www.ietf.org/rfc/rfc2047.txt) for more information
     * about character encoding and MIME.
     *
     * @return a <code>String</code> specifying the name of the character
     *         encoding, for example, <code>UTF-8</code>
     */
    public String getCharacterEncoding();

    /**
     * Returns the content type used for the MIME body sent in this response.
     * The content type proper must have been specified using
     * {@link #setContentType} before the response is committed. If no content
     * type has been specified, this method returns null. If a content type has
     * been specified and a character encoding has been explicitly or implicitly
     * specified as described in {@link #getCharacterEncoding}, the charset
     * parameter is included in the string returned. If no character encoding
     * has been specified, the charset parameter is omitted.
     *
     * @return a <code>String</code> specifying the content type, for example,
     *         <code>text/html; charset=UTF-8</code>, or null
     * @since 2.4
     */
    public String getContentType();

    /**
     * Returns a {@link ServletOutputStream} suitable for writing binary data in
     * the response. The servlet container does not encode the binary data.
     * <p>
     * Calling flush() on the ServletOutputStream commits the response. Either
     * this method or {@link #getWriter} may be called to write the body, not
     * both.
     *
     * @return a {@link ServletOutputStream} for writing binary data
     * @exception IllegalStateException
     *                if the <code>getWriter</code> method has been called on
     *                this response
     * @exception IOException
     *                if an input or output exception occurred
     * @see #getWriter
     */
    public ServletOutputStream getOutputStream() throws IOException;

    /**
     * Returns a <code>PrintWriter</code> object that can send character text to
     * the client. The <code>PrintWriter</code> uses the character encoding
     * returned by {@link #getCharacterEncoding}. If the response's character
     * encoding has not been specified as described in
     * <code>getCharacterEncoding</code> (i.e., the method just returns the
     * default value <code>ISO-8859-1</code>), <code>getWriter</code> updates it
     * to <code>ISO-8859-1</code>.
     * <p>
     * Calling flush() on the <code>PrintWriter</code> commits the response.
     * <p>
     * Either this method or {@link #getOutputStream} may be called to write the
     * body, not both.
     *
     * @return a <code>PrintWriter</code> object that can return character data
     *         to the client
     * @exception java.io.UnsupportedEncodingException
     *                if the character encoding returned by
     *                <code>getCharacterEncoding</code> cannot be used
     * @exception IllegalStateException
     *                if the <code>getOutputStream</code> method has already
     *                been called for this response object
     * @exception IOException
     *                if an input or output exception occurred
     * @see #getOutputStream
     * @see #setCharacterEncoding
     */
    public PrintWriter getWriter() throws IOException;

    /**
     * Sets the character encoding (MIME charset) of the response being sent to
     * the client, for example, to UTF-8. If the character encoding has already
     * been set by {@link #setContentType} or {@link #setLocale}, this method
     * overrides it. Calling {@link #setContentType} with the
     * <code>String</code> of <code>text/html</code> and calling this method
     * with the <code>String</code> of <code>UTF-8</code> is equivalent with
     * calling <code>setContentType</code> with the <code>String</code> of
     * <code>text/html; charset=UTF-8</code>.
     * <p>
     * This method can be called repeatedly to change the character encoding.
     * This method has no effect if it is called after <code>getWriter</code>
     * has been called or after the response has been committed.
     * <p>
     * Containers must communicate the character encoding used for the servlet
     * response's writer to the client if the protocol provides a way for doing
     * so. In the case of HTTP, the character encoding is communicated as part
     * of the <code>Content-Type</code> header for text media types. Note that
     * the character encoding cannot be communicated via HTTP headers if the
     * servlet does not specify a content type; however, it is still used to
     * encode text written via the servlet response's writer.
     *
     * @param charset
     *            a String specifying only the character set defined by IANA
     *            Character Sets
     *            (http://www.iana.org/assignments/character-sets)
     * @see #setContentType #setLocale
     * @since 2.4
     */
    public void setCharacterEncoding(String charset);

    /**
     * Sets the length of the content body in the response In HTTP servlets,
     * this method sets the HTTP Content-Length header.
     *
     * @param len
     *            an integer specifying the length of the content being returned
     *            to the client; sets the Content-Length header
     */
    public void setContentLength(int len);

    /**
     * Sets the length of the content body in the response In HTTP servlets,
     * this method sets the HTTP Content-Length header.
     *
     * @param length
     *            an integer specifying the length of the content being returned
     *            to the client; sets the Content-Length header
     *
     * @since Servlet 3.1
     */
    public void setContentLengthLong(long length);

    /**
     * Sets the content type of the response being sent to the client, if the
     * response has not been committed yet. The given content type may include a
     * character encoding specification, for example,
     * <code>text/html;charset=UTF-8</code>. The response's character encoding
     * is only set from the given content type if this method is called before
     * <code>getWriter</code> is called.
     * <p>
     * This method may be called repeatedly to change content type and character
     * encoding. This method has no effect if called after the response has been
     * committed. It does not set the response's character encoding if it is
     * called after <code>getWriter</code> has been called or after the response
     * has been committed.
     * <p>
     * Containers must communicate the content type and the character encoding
     * used for the servlet response's writer to the client if the protocol
     * provides a way for doing so. In the case of HTTP, the
     * <code>Content-Type</code> header is used.
     *
     * @param type
     *            a <code>String</code> specifying the MIME type of the content
     * @see #setLocale
     * @see #setCharacterEncoding
     * @see #getOutputStream
     * @see #getWriter
     */
    public void setContentType(String type);

    /**
     * Sets the preferred buffer size for the body of the response. The servlet
     * container will use a buffer at least as large as the size requested. The
     * actual buffer size used can be found using <code>getBufferSize</code>.
     * <p>
     * A larger buffer allows more content to be written before anything is
     * actually sent, thus providing the servlet with more time to set
     * appropriate status codes and headers. A smaller buffer decreases server
     * memory load and allows the client to start receiving data more quickly.
     * <p>
     * This method must be called before any response body content is written;
     * if content has been written or the response object has been committed,
     * this method throws an <code>IllegalStateException</code>.
     *
     * @param size
     *            the preferred buffer size
     * @exception IllegalStateException
     *                if this method is called after content has been written
     * @see #getBufferSize
     * @see #flushBuffer
     * @see #isCommitted
     * @see #reset
     */
    public void setBufferSize(int size);

    /**
     * Returns the actual buffer size used for the response. If no buffering is
     * used, this method returns 0.
     *
     * @return the actual buffer size used
     * @see #setBufferSize
     * @see #flushBuffer
     * @see #isCommitted
     * @see #reset
     */
    public int getBufferSize();

    /**
     * Forces any content in the buffer to be written to the client. A call to
     * this method automatically commits the response, meaning the status code
     * and headers will be written.
     *
     * @throws IOException if an I/O occurs during the flushing of the response
     *
     * @see #setBufferSize
     * @see #getBufferSize
     * @see #isCommitted
     * @see #reset
     */
    public void flushBuffer() throws IOException;

    /**
     * Clears the content of the underlying buffer in the response without
     * clearing headers or status code. If the response has been committed, this
     * method throws an <code>IllegalStateException</code>.
     *
     * @see #setBufferSize
     * @see #getBufferSize
     * @see #isCommitted
     * @see #reset
     * @since 2.3
     */
    public void resetBuffer();

    /**
     * Returns a boolean indicating if the response has been committed. A
     * committed response has already had its status code and headers written.
     *
     * @return a boolean indicating if the response has been committed
     * @see #setBufferSize
     * @see #getBufferSize
     * @see #flushBuffer
     * @see #reset
     */
    public boolean isCommitted();

    /**
     * Clears any data that exists in the buffer as well as the status code and
     * headers. If the response has been committed, this method throws an
     * <code>IllegalStateException</code>.
     *
     * @exception IllegalStateException
     *                if the response has already been committed
     * @see #setBufferSize
     * @see #getBufferSize
     * @see #flushBuffer
     * @see #isCommitted
     */
    public void reset();

    /**
     * Sets the locale of the response, if the response has not been committed
     * yet. It also sets the response's character encoding appropriately for the
     * locale, if the character encoding has not been explicitly set using
     * {@link #setContentType} or {@link #setCharacterEncoding},
     * <code>getWriter</code> hasn't been called yet, and the response hasn't
     * been committed yet. If the deployment descriptor contains a
     * <code>locale-encoding-mapping-list</code> element, and that element
     * provides a mapping for the given locale, that mapping is used. Otherwise,
     * the mapping from locale to character encoding is container dependent.
     * <p>
     * This method may be called repeatedly to change locale and character
     * encoding. The method has no effect if called after the response has been
     * committed. It does not set the response's character encoding if it is
     * called after {@link #setContentType} has been called with a charset
     * specification, after {@link #setCharacterEncoding} has been called, after
     * <code>getWriter</code> has been called, or after the response has been
     * committed.
     * <p>
     * Containers must communicate the locale and the character encoding used
     * for the servlet response's writer to the client if the protocol provides
     * a way for doing so. In the case of HTTP, the locale is communicated via
     * the <code>Content-Language</code> header, the character encoding as part
     * of the <code>Content-Type</code> header for text media types. Note that
     * the character encoding cannot be communicated via HTTP headers if the
     * servlet does not specify a content type; however, it is still used to
     * encode text written via the servlet response's writer.
     *
     * @param loc
     *            the locale of the response
     * @see #getLocale
     * @see #setContentType
     * @see #setCharacterEncoding
     */
    public void setLocale(Locale loc);

    /**
     * Returns the locale specified for this response using the
     * {@link #setLocale} method. Calls made to <code>setLocale</code> after the
     * response is committed have no effect.
     *
     * @return The locale specified for this response using the
     *          {@link #setLocale} method. If no locale has been specified, the
     *          container's default locale is returned.
     *
     * @see #setLocale
     */
    public Locale getLocale();

}
```



### HttpServletResponse

```java
/**
 * Extends the {@link ServletResponse} interface to provide HTTP-specific
 * functionality in sending a response. For example, it has methods to access
 * HTTP headers and cookies.
 * <p>
 * The servlet container creates an <code>HttpServletResponse</code> object and
 * passes it as an argument to the servlet's service methods (<code>doGet</code>, <code>doPost</code>, etc).
 *
 * @see javax.servlet.ServletResponse
 */
public interface HttpServletResponse extends ServletResponse {

    /**
     * Adds the specified cookie to the response. This method can be called
     * multiple times to set more than one cookie.
     *
     * @param cookie
     *            the Cookie to return to the client
     */
    public void addCookie(Cookie cookie);

    /**
     * Returns a boolean indicating whether the named response header has
     * already been set.
     *
     * @param name
     *            the header name
     * @return <code>true</code> if the named response header has already been
     *         set; <code>false</code> otherwise
     */
    public boolean containsHeader(String name);

    /**
     * Encodes the specified URL by including the session ID in it, or, if
     * encoding is not needed, returns the URL unchanged. The implementation of
     * this method includes the logic to determine whether the session ID needs
     * to be encoded in the URL. For example, if the browser supports cookies,
     * or session tracking is turned off, URL encoding is unnecessary.
     * <p>
     * For robust session tracking, all URLs emitted by a servlet should be run
     * through this method. Otherwise, URL rewriting cannot be used with
     * browsers which do not support cookies.
     *
     * @param url
     *            the url to be encoded.
     * @return the encoded URL if encoding is needed; the unchanged URL
     *         otherwise.
     */
    public String encodeURL(String url);

    /**
     * Encodes the specified URL for use in the <code>sendRedirect</code> method
     * or, if encoding is not needed, returns the URL unchanged. The
     * implementation of this method includes the logic to determine whether the
     * session ID needs to be encoded in the URL. Because the rules for making
     * this determination can differ from those used to decide whether to encode
     * a normal link, this method is separated from the <code>encodeURL</code>
     * method.
     * <p>
     * All URLs sent to the <code>HttpServletResponse.sendRedirect</code> method
     * should be run through this method. Otherwise, URL rewriting cannot be
     * used with browsers which do not support cookies.
     *
     * @param url
     *            the url to be encoded.
     * @return the encoded URL if encoding is needed; the unchanged URL
     *         otherwise.
     * @see #sendRedirect
     * @see #encodeUrl
     */
    public String encodeRedirectURL(String url);

    /**
     * @param url
     *            the url to be encoded.
     * @return the encoded URL if encoding is needed; the unchanged URL
     *         otherwise.
     * @deprecated As of version 2.1, use encodeURL(String url) instead
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public String encodeUrl(String url);

    /**
     * @param url
     *            the url to be encoded.
     * @return the encoded URL if encoding is needed; the unchanged URL
     *         otherwise.
     * @deprecated As of version 2.1, use encodeRedirectURL(String url) instead
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public String encodeRedirectUrl(String url);

    /**
     * Sends an error response to the client using the specified status code and
     * clears the output buffer. The server defaults to creating the response to
     * look like an HTML-formatted server error page containing the specified
     * message, setting the content type to "text/html", leaving cookies and
     * other headers unmodified. If an error-page declaration has been made for
     * the web application corresponding to the status code passed in, it will
     * be served back in preference to the suggested msg parameter.
     * <p>
     * If the response has already been committed, this method throws an
     * IllegalStateException. After using this method, the response should be
     * considered to be committed and should not be written to.
     *
     * @param sc
     *            the error status code
     * @param msg
     *            the descriptive message
     * @exception IOException
     *                If an input or output exception occurs
     * @exception IllegalStateException
     *                If the response was committed
     */
    public void sendError(int sc, String msg) throws IOException;

    /**
     * Sends an error response to the client using the specified status code and
     * clears the buffer. This is equivalent to calling {@link #sendError(int,
     * String)} with the same status code and <code>null</code> for the message.
     *
     * @param sc
     *            the error status code
     * @exception IOException
     *                If an input or output exception occurs
     * @exception IllegalStateException
     *                If the response was committed before this method call
     */
    public void sendError(int sc) throws IOException;

    /**
     * Sends a temporary redirect response to the client using the specified
     * redirect location URL. This method can accept relative URLs; the servlet
     * container must convert the relative URL to an absolute URL before sending
     * the response to the client. If the location is relative without a leading
     * '/' the container interprets it as relative to the current request URI.
     * If the location is relative with a leading '/' the container interprets
     * it as relative to the servlet container root.
     * <p>
     * If the response has already been committed, this method throws an
     * IllegalStateException. After using this method, the response should be
     * considered to be committed and should not be written to.
     *
     * @param location
     *            the redirect location URL
     * @exception IOException
     *                If an input or output exception occurs
     * @exception IllegalStateException
     *                If the response was committed or if a partial URL is given
     *                and cannot be converted into a valid URL
     */
    public void sendRedirect(String location) throws IOException;

    /**
     * Sets a response header with the given name and date-value. The date is
     * specified in terms of milliseconds since the epoch. If the header had
     * already been set, the new value overwrites the previous one. The
     * <code>containsHeader</code> method can be used to test for the presence
     * of a header before setting its value.
     *
     * @param name
     *            the name of the header to set
     * @param date
     *            the assigned date value
     * @see #containsHeader
     * @see #addDateHeader
     */
    public void setDateHeader(String name, long date);

    /**
     * Adds a response header with the given name and date-value. The date is
     * specified in terms of milliseconds since the epoch. This method allows
     * response headers to have multiple values.
     *
     * @param name
     *            the name of the header to set
     * @param date
     *            the additional date value
     * @see #setDateHeader
     */
    public void addDateHeader(String name, long date);

    /**
     * Sets a response header with the given name and value. If the header had
     * already been set, the new value overwrites the previous one. The
     * <code>containsHeader</code> method can be used to test for the presence
     * of a header before setting its value.
     *
     * @param name
     *            the name of the header
     * @param value
     *            the header value If it contains octet string, it should be
     *            encoded according to RFC 2047
     *            (http://www.ietf.org/rfc/rfc2047.txt)
     * @see #containsHeader
     * @see #addHeader
     */
    public void setHeader(String name, String value);

    /**
     * Adds a response header with the given name and value. This method allows
     * response headers to have multiple values.
     *
     * @param name
     *            the name of the header
     * @param value
     *            the additional header value If it contains octet string, it
     *            should be encoded according to RFC 2047
     *            (http://www.ietf.org/rfc/rfc2047.txt)
     * @see #setHeader
     */
    public void addHeader(String name, String value);

    /**
     * Sets a response header with the given name and integer value. If the
     * header had already been set, the new value overwrites the previous one.
     * The <code>containsHeader</code> method can be used to test for the
     * presence of a header before setting its value.
     *
     * @param name
     *            the name of the header
     * @param value
     *            the assigned integer value
     * @see #containsHeader
     * @see #addIntHeader
     */
    public void setIntHeader(String name, int value);

    /**
     * Adds a response header with the given name and integer value. This method
     * allows response headers to have multiple values.
     *
     * @param name
     *            the name of the header
     * @param value
     *            the assigned integer value
     * @see #setIntHeader
     */
    public void addIntHeader(String name, int value);

    /**
     * Sets the status code for this response. This method is used to set the
     * return status code when there is no error (for example, for the status
     * codes SC_OK or SC_MOVED_TEMPORARILY). If there is an error, and the
     * caller wishes to invoke an error-page defined in the web application, the
     * <code>sendError</code> method should be used instead.
     * <p>
     * The container clears the buffer and sets the Location header, preserving
     * cookies and other headers.
     *
     * @param sc
     *            the status code
     * @see #sendError
     */
    public void setStatus(int sc);

    /**
     * Sets the status code and message for this response.
     *
     * @param sc
     *            the status code
     * @param sm
     *            the status message
     * @deprecated As of version 2.1, due to ambiguous meaning of the message
     *             parameter. To set a status code use
     *             <code>setStatus(int)</code>, to send an error with a
     *             description use <code>sendError(int, String)</code>.
     */
    @SuppressWarnings("dep-ann")
    // Spec API does not use @Deprecated
    public void setStatus(int sc, String sm);

    /**
     * Get the HTTP status code for this Response.
     *
     * @return The HTTP status code for this Response
     *
     * @since Servlet 3.0
     */
    public int getStatus();

    /**
     * Return the value for the specified header, or <code>null</code> if this
     * header has not been set.  If more than one value was added for this
     * name, only the first is returned; use {@link #getHeaders(String)} to
     * retrieve all of them.
     *
     * @param name Header name to look up
     *
     * @return The first value for the specified header. This is the raw value
     *         so if multiple values are specified in the first header then they
     *         will be returned as a single header value .
     *
     * @since Servlet 3.0
     */
    public String getHeader(String name);

    /**
     * Return a Collection of all the header values associated with the
     * specified header name.
     *
     * @param name Header name to look up
     *
     * @return The values for the specified header. These are the raw values so
     *         if multiple values are specified in a single header that will be
     *         returned as a single header value.
     *
     * @since Servlet 3.0
     */
    public Collection<String> getHeaders(String name);

    /**
     * Get the header names set for this HTTP response.
     *
     * @return The header names set for this HTTP response.
     *
     * @since Servlet 3.0
     */
    public Collection<String> getHeaderNames();

    /*
     * Server status codes; see RFC 2068.
     */

    /**
     * Status code (100) indicating the client can continue.
     */
    public static final int SC_CONTINUE = 100;

    /**
     * Status code (101) indicating the server is switching protocols according
     * to Upgrade header.
     */
    public static final int SC_SWITCHING_PROTOCOLS = 101;

    /**
     * Status code (200) indicating the request succeeded normally.
     */
    public static final int SC_OK = 200;

    /**
     * Status code (201) indicating the request succeeded and created a new
     * resource on the server.
     */
    public static final int SC_CREATED = 201;

    /**
     * Status code (202) indicating that a request was accepted for processing,
     * but was not completed.
     */
    public static final int SC_ACCEPTED = 202;

    /**
     * Status code (203) indicating that the meta information presented by the
     * client did not originate from the server.
     */
    public static final int SC_NON_AUTHORITATIVE_INFORMATION = 203;

    /**
     * Status code (204) indicating that the request succeeded but that there
     * was no new information to return.
     */
    public static final int SC_NO_CONTENT = 204;

    /**
     * Status code (205) indicating that the agent <em>SHOULD</em> reset the
     * document view which caused the request to be sent.
     */
    public static final int SC_RESET_CONTENT = 205;

    /**
     * Status code (206) indicating that the server has fulfilled the partial
     * GET request for the resource.
     */
    public static final int SC_PARTIAL_CONTENT = 206;

    /**
     * Status code (300) indicating that the requested resource corresponds to
     * any one of a set of representations, each with its own specific location.
     */
    public static final int SC_MULTIPLE_CHOICES = 300;

    /**
     * Status code (301) indicating that the resource has permanently moved to a
     * new location, and that future references should use a new URI with their
     * requests.
     */
    public static final int SC_MOVED_PERMANENTLY = 301;

    /**
     * Status code (302) indicating that the resource has temporarily moved to
     * another location, but that future references should still use the
     * original URI to access the resource. This definition is being retained
     * for backwards compatibility. SC_FOUND is now the preferred definition.
     */
    public static final int SC_MOVED_TEMPORARILY = 302;

    /**
     * Status code (302) indicating that the resource reside temporarily under a
     * different URI. Since the redirection might be altered on occasion, the
     * client should continue to use the Request-URI for future
     * requests.(HTTP/1.1) To represent the status code (302), it is recommended
     * to use this variable.
     */
    public static final int SC_FOUND = 302;

    /**
     * Status code (303) indicating that the response to the request can be
     * found under a different URI.
     */
    public static final int SC_SEE_OTHER = 303;

    /**
     * Status code (304) indicating that a conditional GET operation found that
     * the resource was available and not modified.
     */
    public static final int SC_NOT_MODIFIED = 304;

    /**
     * Status code (305) indicating that the requested resource <em>MUST</em> be
     * accessed through the proxy given by the <code><em>Location</em></code>
     * field.
     */
    public static final int SC_USE_PROXY = 305;

    /**
     * Status code (307) indicating that the requested resource resides
     * temporarily under a different URI. The temporary URI <em>SHOULD</em> be
     * given by the <code><em>Location</em></code> field in the response.
     */
    public static final int SC_TEMPORARY_REDIRECT = 307;

    /**
     * Status code (400) indicating the request sent by the client was
     * syntactically incorrect.
     */
    public static final int SC_BAD_REQUEST = 400;

    /**
     * Status code (401) indicating that the request requires HTTP
     * authentication.
     */
    public static final int SC_UNAUTHORIZED = 401;

    /**
     * Status code (402) reserved for future use.
     */
    public static final int SC_PAYMENT_REQUIRED = 402;

    /**
     * Status code (403) indicating the server understood the request but
     * refused to fulfill it.
     */
    public static final int SC_FORBIDDEN = 403;

    /**
     * Status code (404) indicating that the requested resource is not
     * available.
     */
    public static final int SC_NOT_FOUND = 404;

    /**
     * Status code (405) indicating that the method specified in the
     * <code><em>Request-Line</em></code> is not allowed for the resource
     * identified by the <code><em>Request-URI</em></code>.
     */
    public static final int SC_METHOD_NOT_ALLOWED = 405;

    /**
     * Status code (406) indicating that the resource identified by the request
     * is only capable of generating response entities which have content
     * characteristics not acceptable according to the accept headers sent in
     * the request.
     */
    public static final int SC_NOT_ACCEPTABLE = 406;

    /**
     * Status code (407) indicating that the client <em>MUST</em> first
     * authenticate itself with the proxy.
     */
    public static final int SC_PROXY_AUTHENTICATION_REQUIRED = 407;

    /**
     * Status code (408) indicating that the client did not produce a request
     * within the time that the server was prepared to wait.
     */
    public static final int SC_REQUEST_TIMEOUT = 408;

    /**
     * Status code (409) indicating that the request could not be completed due
     * to a conflict with the current state of the resource.
     */
    public static final int SC_CONFLICT = 409;

    /**
     * Status code (410) indicating that the resource is no longer available at
     * the server and no forwarding address is known. This condition
     * <em>SHOULD</em> be considered permanent.
     */
    public static final int SC_GONE = 410;

    /**
     * Status code (411) indicating that the request cannot be handled without a
     * defined <code><em>Content-Length</em></code>.
     */
    public static final int SC_LENGTH_REQUIRED = 411;

    /**
     * Status code (412) indicating that the precondition given in one or more
     * of the request-header fields evaluated to false when it was tested on the
     * server.
     */
    public static final int SC_PRECONDITION_FAILED = 412;

    /**
     * Status code (413) indicating that the server is refusing to process the
     * request because the request entity is larger than the server is willing
     * or able to process.
     */
    public static final int SC_REQUEST_ENTITY_TOO_LARGE = 413;

    /**
     * Status code (414) indicating that the server is refusing to service the
     * request because the <code><em>Request-URI</em></code> is longer than the
     * server is willing to interpret.
     */
    public static final int SC_REQUEST_URI_TOO_LONG = 414;

    /**
     * Status code (415) indicating that the server is refusing to service the
     * request because the entity of the request is in a format not supported by
     * the requested resource for the requested method.
     */
    public static final int SC_UNSUPPORTED_MEDIA_TYPE = 415;

    /**
     * Status code (416) indicating that the server cannot serve the requested
     * byte range.
     */
    public static final int SC_REQUESTED_RANGE_NOT_SATISFIABLE = 416;

    /**
     * Status code (417) indicating that the server could not meet the
     * expectation given in the Expect request header.
     */
    public static final int SC_EXPECTATION_FAILED = 417;

    /**
     * Status code (500) indicating an error inside the HTTP server which
     * prevented it from fulfilling the request.
     */
    public static final int SC_INTERNAL_SERVER_ERROR = 500;

    /**
     * Status code (501) indicating the HTTP server does not support the
     * functionality needed to fulfill the request.
     */
    public static final int SC_NOT_IMPLEMENTED = 501;

    /**
     * Status code (502) indicating that the HTTP server received an invalid
     * response from a server it consulted when acting as a proxy or gateway.
     */
    public static final int SC_BAD_GATEWAY = 502;

    /**
     * Status code (503) indicating that the HTTP server is temporarily
     * overloaded, and unable to handle the request.
     */
    public static final int SC_SERVICE_UNAVAILABLE = 503;

    /**
     * Status code (504) indicating that the server did not receive a timely
     * response from the upstream server while acting as a gateway or proxy.
     */
    public static final int SC_GATEWAY_TIMEOUT = 504;

    /**
     * Status code (505) indicating that the server does not support or refuses
     * to support the HTTP protocol version that was used in the request
     * message.
     */
    public static final int SC_HTTP_VERSION_NOT_SUPPORTED = 505;
}
```





Servlet3.0之前1请求1线程

3.0

1. 请求被Servlet容器接受,分配线程流转Filter链
2. Servlet使用req.startAsync返回异步上下文
3. 异步线程处理完请求后拿AsyncContext写回请求方



`@WebServlet(asyncSupport = true)` 开启异步支持, `AsyncContext` start task

`AsyncListener` 设置监听响应



Servlet3.1非阻塞IO

在Servlet处理请求时，从ServletInputStream中读取请求体时是阻塞的。而我们想要的是，当数据就绪时通知我们去读取就可以了，因为这可以避免占用Servlet容器线程或者业务线程来进行阻塞读取

IO数据需要等待内核接收就绪方可,期间会阻塞容器线程



ReadListener到ServletInputStream 数据准备好后回调onDataAvailable方法

响应不同的异步

1. DeferredResult封装 代理了AsyncContext的流程
2. Callable封装 使用TaskExecutor执行





webflux

HttpHandler Adapter