# Spring MVC



DispatcherServlet

ContextLoaderListener

HandlerMapper

HandlerAdapter



ModelAndView

### ContextLoaderListener

Bootstrap listener to start up and shut down Spring's root WebApplicationContext. Simply delegates to ContextLoader as well as to ContextCleanupListener.
As of Spring 3.1, ContextLoaderListener supports injecting the root web application context via the ContextLoaderListener(WebApplicationContext) constructor, allowing for programmatic configuration in Servlet 3.0+ environments. See org.springframework.web.WebApplicationInitializer for usage examples.

```java
public class ContextLoaderListener extends ContextLoader implements ServletContextListener {

   /**
    * Create a new {@code ContextLoaderListener} that will create a web application
    * context based on the "contextClass" and "contextConfigLocation" servlet
    * context-params. See {@link ContextLoader} superclass documentation for details on
    * default values for each.
    * <p>This constructor is typically used when declaring {@code ContextLoaderListener}
    * as a {@code <listener>} within {@code web.xml}, where a no-arg constructor is
    * required.
    * <p>The created application context will be registered into the ServletContext under
    * the attribute name {@link WebApplicationContext#ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE}
    * and the Spring application context will be closed when the {@link #contextDestroyed}
    * lifecycle method is invoked on this listener.
    * @see ContextLoader
    * @see #ContextLoaderListener(WebApplicationContext)
    * @see #contextInitialized(ServletContextEvent)
    * @see #contextDestroyed(ServletContextEvent)
    */
   public ContextLoaderListener() {
   }

   /**
    * Create a new {@code ContextLoaderListener} with the given application context. This
    * constructor is useful in Servlet 3.0+ environments where instance-based
    * registration of listeners is possible through the {@link javax.servlet.ServletContext#addListener}
    * API.
    * <p>The context may or may not yet be {@linkplain
    * org.springframework.context.ConfigurableApplicationContext#refresh() refreshed}. If it
    * (a) is an implementation of {@link ConfigurableWebApplicationContext} and
    * (b) has <strong>not</strong> already been refreshed (the recommended approach),
    * then the following will occur:
    * <ul>
    * <li>If the given context has not already been assigned an {@linkplain
    * org.springframework.context.ConfigurableApplicationContext#setId id}, one will be assigned to it</li>
    * <li>{@code ServletContext} and {@code ServletConfig} objects will be delegated to
    * the application context</li>
    * <li>{@link #customizeContext} will be called</li>
    * <li>Any {@link org.springframework.context.ApplicationContextInitializer ApplicationContextInitializer org.springframework.context.ApplicationContextInitializer ApplicationContextInitializers}
    * specified through the "contextInitializerClasses" init-param will be applied.</li>
    * <li>{@link org.springframework.context.ConfigurableApplicationContext#refresh refresh()} will be called</li>
    * </ul>
    * If the context has already been refreshed or does not implement
    * {@code ConfigurableWebApplicationContext}, none of the above will occur under the
    * assumption that the user has performed these actions (or not) per his or her
    * specific needs.
    * <p>See {@link org.springframework.web.WebApplicationInitializer} for usage examples.
    * <p>In any case, the given application context will be registered into the
    * ServletContext under the attribute name {@link
    * WebApplicationContext#ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE} and the Spring
    * application context will be closed when the {@link #contextDestroyed} lifecycle
    * method is invoked on this listener.
    * @param context the application context to manage
    * @see #contextInitialized(ServletContextEvent)
    * @see #contextDestroyed(ServletContextEvent)
    */
   public ContextLoaderListener(WebApplicationContext context) {
      super(context);
   }


   /**
    * Initialize the root web application context.
    */
   @Override
   public void contextInitialized(ServletContextEvent event) {
      initWebApplicationContext(event.getServletContext());
   }


   /**
    * Close the root web application context.
    */
   @Override
   public void contextDestroyed(ServletContextEvent event) {
      closeWebApplicationContext(event.getServletContext());
      ContextCleanupListener.cleanupAttributes(event.getServletContext());
   }

}
```



```java
/**
 * Initialize Spring's web application context for the given servlet context,
 * using the application context provided at construction time, or creating a new one
 * according to the "{@link #CONTEXT_CLASS_PARAM contextClass}" and
 * "{@link #CONFIG_LOCATION_PARAM contextConfigLocation}" context-params.
 */
public WebApplicationContext initWebApplicationContext(ServletContext servletContext) {
   if (servletContext.getAttribute(WebApplicationContext.ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE) != null) {
      throw new IllegalStateException("");
   }

   servletContext.log("Initializing Spring root WebApplicationContext");
   try {
      // Store context in local instance variable, to guarantee that
      // it is available on ServletContext shutdown.
      if (this.context == null) {
         this.context = createWebApplicationContext(servletContext);
      }
      if (this.context instanceof ConfigurableWebApplicationContext) {
         ConfigurableWebApplicationContext cwac = (ConfigurableWebApplicationContext) this.context;
         if (!cwac.isActive()) {
            // The context has not yet been refreshed -> provide services such as
            // setting the parent context, setting the application context id, etc
            if (cwac.getParent() == null) {
               // The context instance was injected without an explicit parent ->
               // determine parent for root web application context, if any.
               ApplicationContext parent = loadParentContext(servletContext);
               cwac.setParent(parent);
            }
            configureAndRefreshWebApplicationContext(cwac, servletContext);
         }
      }
      servletContext.setAttribute(WebApplicationContext.ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE, this.context);

      ClassLoader ccl = Thread.currentThread().getContextClassLoader();
      if (ccl == ContextLoader.class.getClassLoader()) {
         currentContext = this.context;
      }
      else if (ccl != null) {
         currentContextPerThread.put(ccl, this.context);
      }
      return this.context;
   }
   catch (RuntimeException | Error ex) {
      servletContext.setAttribute(WebApplicationContext.ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE, ex);
      throw ex;
   }
}
```



#### createWebApplicationContext

```java
/**
 * Instantiate the root WebApplicationContext for this loader, either the
 * default context class or a custom context class if specified.
 * <p>This implementation expects custom contexts to implement the
 * {@link ConfigurableWebApplicationContext} interface.
 * Can be overridden in subclasses.
 * <p>In addition, {@link #customizeContext} gets called prior to refreshing the
 * context, allowing subclasses to perform custom modifications to the context.
 */
protected WebApplicationContext createWebApplicationContext(ServletContext sc) {
   Class<?> contextClass = determineContextClass(sc);
   if (!ConfigurableWebApplicationContext.class.isAssignableFrom(contextClass)) {
      throw new ApplicationContextException("");
   }
   return (ConfigurableWebApplicationContext) BeanUtils.instantiateClass(contextClass);
}
```

```java
/**
 * Return the WebApplicationContext implementation class to use, either the
 * default XmlWebApplicationContext or a custom context class if specified.
 * @param servletContext current servlet context
 * @return the WebApplicationContext implementation class to use
 * @see #CONTEXT_CLASS_PARAM
 * @see org.springframework.web.context.support.XmlWebApplicationContext
 */
protected Class<?> determineContextClass(ServletContext servletContext) {
   String contextClassName = servletContext.getInitParameter(CONTEXT_CLASS_PARAM);
   if (contextClassName != null) {
      try {
         return ClassUtils.forName(contextClassName, ClassUtils.getDefaultClassLoader());
      }
      catch (ClassNotFoundException ex) {
         throw new ApplicationContextException("");
      }
   }
   else {
      contextClassName = defaultStrategies.getProperty(WebApplicationContext.class.getName());
      try {
         return ClassUtils.forName(contextClassName, ContextLoader.class.getClassLoader());
      }
      catch (ClassNotFoundException ex) {
         throw new ApplicationContextException(
               "Failed to load default context class [" + contextClassName + "]", ex);
      }
   }
}
```



```java
protected void configureAndRefreshWebApplicationContext(ConfigurableWebApplicationContext wac, ServletContext sc) {
   if (ObjectUtils.identityToString(wac).equals(wac.getId())) {
      // The application context id is still set to its original default value
      // -> assign a more useful id based on available information
      String idParam = sc.getInitParameter(CONTEXT_ID_PARAM);
      if (idParam != null) {
         wac.setId(idParam);
      }
      else {
         // Generate default id...
         wac.setId(ConfigurableWebApplicationContext.APPLICATION_CONTEXT_ID_PREFIX +
               ObjectUtils.getDisplayString(sc.getContextPath()));
      }
   }

   wac.setServletContext(sc);
   String configLocationParam = sc.getInitParameter(CONFIG_LOCATION_PARAM);
   if (configLocationParam != null) {
      wac.setConfigLocation(configLocationParam);
   }

   // The wac environment's #initPropertySources will be called in any case when the context
   // is refreshed; do it eagerly here to ensure servlet property sources are in place for
   // use in any post-processing or initialization that occurs below prior to #refresh
   ConfigurableEnvironment env = wac.getEnvironment();
   if (env instanceof ConfigurableWebEnvironment) {
      ((ConfigurableWebEnvironment) env).initPropertySources(sc, null);
   }

   customizeContext(sc, wac);
   wac.refresh();
}
```

### XmlWebApplicationContext

```java
public class XmlWebApplicationContext extends AbstractRefreshableWebApplicationContext {

   /** Default config location for the root context. */
   public static final String DEFAULT_CONFIG_LOCATION = "/WEB-INF/applicationContext.xml";

   /** Default prefix for building a config location for a namespace. */
   public static final String DEFAULT_CONFIG_LOCATION_PREFIX = "/WEB-INF/";

   /** Default suffix for building a config location for a namespace. */
   public static final String DEFAULT_CONFIG_LOCATION_SUFFIX = ".xml";


   /**
    * Loads the bean definitions via an XmlBeanDefinitionReader.
    * @see org.springframework.beans.factory.xml.XmlBeanDefinitionReader
    * @see #initBeanDefinitionReader
    * @see #loadBeanDefinitions
    */
   @Override
   protected void loadBeanDefinitions(DefaultListableBeanFactory beanFactory) throws BeansException, IOException {
      // Create a new XmlBeanDefinitionReader for the given BeanFactory.
      XmlBeanDefinitionReader beanDefinitionReader = new XmlBeanDefinitionReader(beanFactory);

      // Configure the bean definition reader with this context's
      // resource loading environment.
      beanDefinitionReader.setEnvironment(getEnvironment());
      beanDefinitionReader.setResourceLoader(this);
      beanDefinitionReader.setEntityResolver(new ResourceEntityResolver(this));

      // Allow a subclass to provide custom initialization of the reader,
      // then proceed with actually loading the bean definitions.
      initBeanDefinitionReader(beanDefinitionReader); // do nothing
      loadBeanDefinitions(beanDefinitionReader);
   }
 
  
	/**
	 * Initialize the bean definition reader used for loading the bean
	 * definitions of this context. Default implementation is empty.
	 * Can be overridden in subclasses, e.g. for turning off XML validation
	 * or using a different XmlBeanDefinitionParser implementation.
	 */
	protected void initBeanDefinitionReader(XmlBeanDefinitionReader beanDefinitionReader) {
	}

	/**
	 * Load the bean definitions with the given XmlBeanDefinitionReader.
	 * <p>The lifecycle of the bean factory is handled by the refreshBeanFactory method;
	 * therefore this method is just supposed to load and/or register bean definitions.
	 * <p>Delegates to a ResourcePatternResolver for resolving location patterns
	 * into Resource instances.
	 */
	protected void loadBeanDefinitions(XmlBeanDefinitionReader reader) throws IOException {
		String[] configLocations = getConfigLocations();
		if (configLocations != null) {
			for (String configLocation : configLocations) {
				reader.loadBeanDefinitions(configLocation);
			}
		}
	}

	/**
	 * The default location for the root context is "/WEB-INF/applicationContext.xml",
	 * and "/WEB-INF/test-servlet.xml" for a context with the namespace "test-servlet"
	 * (like for a DispatcherServlet instance with the servlet-name "test").
	 */
	@Override
	protected String[] getDefaultConfigLocations() {
		if (getNamespace() != null) {
			return new String[] {DEFAULT_CONFIG_LOCATION_PREFIX + getNamespace() + DEFAULT_CONFIG_LOCATION_SUFFIX};
		}
		else {
			return new String[] {DEFAULT_CONFIG_LOCATION};
		}
	}
}
```



### DispatcherServlet

```java
/**
 * Service dispatcher Servlet.
 */
public class DispatcherServlet extends HttpServlet {

    private static final long serialVersionUID = 5766349180380479888L;
    private static final Map<Integer, HttpHandler> HANDLERS = new ConcurrentHashMap<Integer, HttpHandler>();
    private static DispatcherServlet INSTANCE;

    public DispatcherServlet() {
        DispatcherServlet.INSTANCE = this;
    }

    public static void addHttpHandler(int port, HttpHandler processor) {
        HANDLERS.put(port, processor);
    }

    public static void removeHttpHandler(int port) {
        HANDLERS.remove(port);
    }

    public static DispatcherServlet getInstance() {
        return INSTANCE;
    }

    @Override
    protected void service(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        HttpHandler handler = HANDLERS.get(request.getLocalPort());
        if (handler == null) {// service not found.
            response.sendError(HttpServletResponse.SC_NOT_FOUND, "Service not found.");
        } else {
            handler.handle(request, response);
        }
    }

}
```

WebServiceProtocol  set DispatchServlet to `org.apache.cxf.transport.servlet.SerlvetController`

SerlvetController invoke DispatchServlet#service()



```java
public boolean invoke(HttpServletRequest request, HttpServletResponse res, boolean returnErrors)
    throws ServletException {
    try {
        String pathInfo = request.getPathInfo() == null ? "" : request.getPathInfo();
        AbstractHTTPDestination d = destinationRegistry.getDestinationForPath(pathInfo, true);

        if (d == null) {
            if (!isHideServiceList && (request.getRequestURI().endsWith(serviceListRelativePath)
                || request.getRequestURI().endsWith(serviceListRelativePath + "/")
                || StringUtils.isEmpty(pathInfo)
                || "/".equals(pathInfo))) {
                if (isAuthServiceListPage) {
                    setAuthServiceListPageAttribute(request);
                }
                setBaseURLAttribute(request);
                serviceListGenerator.service(request, res);
            } else {
                d = destinationRegistry.checkRestfulRequest(pathInfo);
                if (d == null || d.getMessageObserver() == null) {
                    if (returnErrors) {
                        LOG.warning("Can't find the request for "
                            + request.getRequestURL() + "'s Observer ");
                        generateNotFound(request, res);
                    }
                    return false;
                }
            }
        }
        if (d != null && d.getMessageObserver() != null) {
            Bus bus = d.getBus();
            ClassLoaderHolder orig = null;
            try {
                if (bus != null) {
                    ClassLoader loader = bus.getExtension(ClassLoader.class);
                    if (loader == null) {
                        ResourceManager manager = bus.getExtension(ResourceManager.class);
                        if (manager != null) {
                            loader = manager.resolveResource("", ClassLoader.class);
                        }
                    }
                    if (loader != null) {
                        //need to set the context classloader to the loader of the bundle
                        orig = ClassLoaderUtils.setThreadContextClassloader(loader);
                    }
                }
                updateDestination(request, d);
                invokeDestination(request, res, d);
            } finally {
                if (orig != null) { 
                    orig.reset();
                }
            }
        }
    } catch (IOException e) {
        throw new ServletException(e);
    }
    return true;
}
```





### Dubbo TomcatHttpServer

```java
// org.apache.dubbo.remoting.http.tomcat.TomcatHttpServer
public TomcatHttpServer(URL url, final HttpHandler handler) {
    super(url, handler);

    this.url = url;
    DispatcherServlet.addHttpHandler(url.getPort(), handler);
    String baseDir = new File(System.getProperty("java.io.tmpdir")).getAbsolutePath();
    tomcat = new Tomcat();

    Connector connector = tomcat.getConnector();
    connector.setPort(url.getPort());
    connector.setProperty("maxThreads", String.valueOf(url.getParameter(THREADS_KEY, DEFAULT_THREADS)));
    connector.setProperty("maxConnections", String.valueOf(url.getParameter(ACCEPTS_KEY, -1)));
    connector.setProperty("URIEncoding", "UTF-8");
    connector.setProperty("connectionTimeout", "60000");
    connector.setProperty("maxKeepAliveRequests", "-1");

    tomcat.setBaseDir(baseDir);
    tomcat.setPort(url.getPort());

    Context context = tomcat.addContext("/", baseDir);
    Tomcat.addServlet(context, "dispatcher", new DispatcherServlet());
    // Issue : https://github.com/apache/dubbo/issues/6418
    // addServletMapping method will be removed since Tomcat 9
    // context.addServletMapping("/*", "dispatcher");
    context.addServletMappingDecoded("/*", "dispatcher");
    ServletManager.getInstance().addServletContext(url.getPort(), context.getServletContext());

    // tell tomcat to fail on startup failures.
    System.setProperty("org.apache.catalina.startup.EXIT_ON_INIT_FAILURE", "true");

    try {
        tomcat.start();
    } catch (LifecycleException e) {
        throw new IllegalStateException("Failed to start tomcat server at " + url.getAddress(), e);
    }
}
```
