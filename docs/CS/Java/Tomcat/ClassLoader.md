## Introduction

Every time you create an instance of a Java class, the class must first be loaded into memory.
The [system class loader](/docs/CS/Java/JDK/JVM/ClassLoader.md) is the default class loader and searches the directories and JAR files specified in the CLASSPATH environment variable.

A servlet container needs a customized loader and cannot simply use the system's class loader because it should not trust the servlets it is running.
If it were to load all servlets and other classes needed by the servlets using the system's class loader, as we did in the previous chapters, then a servlet would be able to access any class and library included in the CLASSPATH environment variable of the running Java Virtual Machine (JVM),
This would be a breach of security.
A servlet is only allowed to load classes in the WEB-INF/classes directory and its subdirectories and from the libraries deployed into the WEB-INF/lib directory.
That's why a servlet container requires a loader of its own.
Each web application (context) in a servlet container has its own loader.
A loader employs a class loader that applies certain rules to loading classes.
In Catalina, a loader is represented by the org.apache.catalina.Loader interface.

Another reason why Tomcat needs its own loader is to support automatic reloading whenever a class in the WEB-INF/classes or WEB-INF/lib directories has been modified.
The class loader in the Tomcat loader implementation uses a separate thread that keeps checking the time stamps of the servlet and supporting class files.
To support automatic reloading, a class loader must implement the org.apache.catalina.loader.Reloader interface.

The reasons why Tomcat needs a custom class loader also include the following:

- To specify certain rules in loading classes.
- To cache the previously loaded classes.
- To pre-load classes so they are ready to use.

A Tomcat loader implementation is usually associated with a context, and the getContainer and setContainer methods of the Loader interface are used for building this association.
A loader can also supports reloading, if one or more classes in a context have been modified.
This way, a servlet programmer can recompile a servlet or a supporting class and the new class will be reloaded without restarting Tomcat.
For the reloading purpose, the Loader interface has the modified method.
In a loader implementation, the modified method must return true if one or more classes in its repositories have been modified, and therefore reloading is required.
A loader does not do the reloading itself, however. Instead, it calls the Context interface's reload method.
Two other methods, setReloadable and getReloadable, are used to determine if reloading is enabled in the Loader.
By default, in the standard implementation of Context, reloading is not enabled.
Therefore, to enable reloading of a context, you need to add a Context element for that context in your server.xml file, such as the following:

```xml
<Context path="/myApp" docBase="myApp" debug="0" reloadable="true"/>
```

Note Whenever the container associated with a loader needs a servlet class, i.e. when its invoke method is called, the container first calls the loader's getClassLoader method to obtain the class loader.
The container then calls the loadClass method of the class loader to load the servlet class.

## ClassLoader hierarchy

When Tomcat is started, it creates a set of class loaders that are organized into the following parent-child relationships, where the parent class loader is above the child class loader:

```
      Bootstrap
          |
       System
          |
       Common
       /     \
  Webapp1   Webapp2 ...

```

A more complex class loader hierarchy may also be configured. See the diagram below.
By default, the Server and Shared class loaders are not defined and the simplified hierarchy shown above is used.
This more complex hierarchy may be use by defining values for the `server.loader` and/or `shared.loader` properties in `conf/catalina.properties`.

```
  Bootstrap
      |
    System
      |
    Common
     /  \
Server  Shared
         /  \
   Webapp1  Webapp2 ...

```

- The Server class loader is only visible to Tomcat internals and is completely invisible to web applications.
- The Shared class loader is visible to all web applications and may be used to shared code across all web applications. However, any updates to this shared code will require a Tomcat restart.

The Common class loader contains additional classes that are made visible to both Tomcat internal classes and to all web applications.
Normally, application classes should NOT be placed here.
The locations searched by this class loader are defined by the `common.loader` property in `$CATALINA_BASE/conf/catalina.properties`.

The Webapp class loader is created for each web application that is deployed in a single Tomcat instance.
All unpacked classes and resources in the `/WEB-INF/classes` directory of your web application, plus classes and resources in JAR files under the `/WEB-INF/lib` directory of your web application, are made visible to this web application, but not to other ones.

As mentioned above, the web application class loader diverges from the default [Java delegation model](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=Delegation-model).
When a request to load a class from the web application's WebappX class loader is processed, this class loader will look in the local repositories first, instead of delegating before looking.
There are exceptions. Classes which are part of the JRE base classes cannot be overridden.
There are some exceptions such as the XML parser components which can be overridden using the upgradeable modules feature.
Lastly, the web application class loader will always delegate first for Jakarta EE API classes for the specifications implemented by Tomcat (Servlet, JSP, EL, WebSocket).
All other class loaders in Tomcat follow the usual delegation pattern.

Therefore, from the perspective of a web application, class or resource loading looks in the following repositories, in this order:

- Bootstrap classes of your JVM
- /WEB-INF/classes of your web application
- /WEB-INF/lib/*.jar of your web application
- System class loader classes
- Common class loader classes

If the web application class loader is configured with `<Loader delegate="true"/>` then the order becomes:

- Bootstrap classes of your JVM
- System class loader classes
- Common class loader classes
- /WEB-INF/classes of your web application
- /WEB-INF/lib/*.jar of your web application

WebappClassLoader was designed for optimization and security in mind.
For example, it caches the previously loaded classes to enhance performance.
It also caches the names of classes it has failed to find, so that the next time the same classes are requested to be loaded, the class loader can throw the ClassNotFoundException without first trying to find them.
WebappClassLoader searches for classes in the list of repositories as well as the specified JAR files.

## CommonLoader

### initClassLoaders

Bootstrap loader for Catalina. 
This application constructs a class loader for use in loading the Catalina internal classes 
(by accumulating all of the JAR files found in the "server" directory under "catalina.home"), 
and starts the regular execution of the container.
The purpose of this roundabout approach is to keep the Catalina internal classes (and any other classes they depend on, 
such as an XML parser) out of the system class path and therefore not visible to application level classes.


```java
// Bootstrap
public final class Bootstrap {

    ClassLoader commonLoader = null;
    ClassLoader catalinaLoader = null;
    ClassLoader sharedLoader = null;

    private void initClassLoaders() {
        try {
            commonLoader = createClassLoader("common", null);
            if (commonLoader == null) {
                // no config file, default to this loader - we might be in a 'single' env.
                commonLoader = this.getClass().getClassLoader();
            }
            catalinaLoader = createClassLoader("server", commonLoader);
            sharedLoader = createClassLoader("shared", commonLoader);
        } catch (Throwable t) {
            System.exit(1);
        }
    }

    private ClassLoader createClassLoader(String name, ClassLoader parent)
            throws Exception {

        String value = CatalinaProperties.getProperty(name + ".loader");
        if ((value == null) || (value.equals("")))
            return parent;

        value = replace(value);

        List<Repository> repositories = new ArrayList<>();

        String[] repositoryPaths = getPaths(value);

        for (String repository : repositoryPaths) {
            // Check for a JAR URL repository
            try {
                @SuppressWarnings("unused")
                URL url = new URL(repository);
                repositories.add(new Repository(repository, RepositoryType.URL));
                continue;
            } catch (MalformedURLException e) {
                // Ignore
            }

            // Local repository
            if (repository.endsWith("*.jar")) {
                repository = repository.substring
                        (0, repository.length() - "*.jar".length());
                repositories.add(new Repository(repository, RepositoryType.GLOB));
            } else if (repository.endsWith(".jar")) {
                repositories.add(new Repository(repository, RepositoryType.JAR));
            } else {
                repositories.add(new Repository(repository, RepositoryType.DIR));
            }
        }

        return ClassLoaderFactory.createClassLoader(repositories, parent);
    }
}
```

## WebappClassLoader


```java
public class WebappLoader extends LifecycleMBeanBase
    implements Loader, PropertyChangeListener {
    private boolean delegate = false;
    
    /**
     * The Java class name of the ClassLoader implementation to be used.
     * This class should extend WebappClassLoaderBase, otherwise, a different
     * loader implementation must be used.
     */
    private String loaderClass = ParallelWebappClassLoader.class.getName();
} 

public class ParallelWebappClassLoader extends WebappClassLoaderBase {
    
}
```

### WebappClassLoaderBase

Specialized web application class loader.
This class loader is a full reimplementation of the URLClassLoader from the JDK. 
It is designed to be fully compatible with a normal URLClassLoader, although its internal behavior may be completely different.

- IMPLEMENTATION NOTE - By default, this class loader follows the delegation model required by the specification. The system class loader will be queried first, then the local repositories, and only then delegation to the parent class loader will occur. This allows the web application to override any shared class except the classes from J2SE. Special handling is provided from the JAXP XML parser interfaces, the JNDI interfaces, and the classes from the servlet API, which are never loaded from the webapp repositories. The delegate property allows an application to modify this behavior to move the parent class loader ahead of the local repositories.
- IMPLEMENTATION NOTE - Due to limitations in Jasper compilation technology, any repository which contains classes from the servlet API will be ignored by the class loader.
- IMPLEMENTATION NOTE - The class loader generates source URLs which include the full JAR URL when a class is loaded from a JAR file, which allows setting security permission at the class level, even when a class is contained inside a JAR.
- IMPLEMENTATION NOTE - Local repositories are searched in the order they are added via the initial constructor.
- IMPLEMENTATION NOTE - No check for sealing violations or security is made unless a security manager is present.
- IMPLEMENTATION NOTE - As of 8.0, this class loader implements InstrumentableClassLoader, permitting web application classes to instrument other classes in the same web application. It does not permit instrumentation of system or container classes or classes in other web apps.

```java
public abstract class WebappClassLoaderBase extends URLClassLoader
        implements Lifecycle, InstrumentableClassLoader, WebappProperties, PermissionCheck {
    /**
     * Should this class loader delegate to the parent class loader
     * <strong>before</strong> searching its own repositories (i.e. the
     * usual Java2 delegation model)?  If set to <code>false</code>,
     * this class loader will search its own repositories first, and
     * delegate to the parent only if the class or resource is not
     * found locally. Note that the default, <code>false</code>, is
     * the behavior called for by the servlet specification.
     */
    protected boolean delegate = false;

}
```


#### loadClass

Load the class with the specified name, searching using the following algorithm until it finds and returns the class.

1. If the class cannot be found, returns ClassNotFoundException.
2. Call findLoadedClass(String) to check if the class has already been loaded. If it has, the same Class object is returned.
3. If the delegate property is set to true, call the loadClass() method of the parent class loader, if any.
4. Call findClass() to find this class in our locally defined repositories.
5. Call the loadClass() method of our parent class loader, if any.
6. If the class was found using the above steps, and the resolve flag is true, this method will then call resolveClass(Class) on the resulting Class object.

```java
public abstract class WebappClassLoaderBase extends URLClassLoader
        implements Lifecycle, InstrumentableClassLoader, WebappProperties, PermissionCheck {
    @Override
    public Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {

        synchronized (JreCompat.isGraalAvailable() ? this : getClassLoadingLock(name)) {
            Class<?> clazz = null;

            // Log access to stopped class loader
            checkStateForClassLoading(name);

            // (0) Check our previously loaded local class cache
            clazz = findLoadedClass0(name);
            if (clazz != null) {
                if (resolve) {
                    resolveClass(clazz);
                }
                return clazz;
            }

            // (0.1) Check our previously loaded class cache
            clazz = JreCompat.isGraalAvailable() ? null : findLoadedClass(name);
            if (clazz != null) {
                if (resolve) {
                    resolveClass(clazz);
                }
                return clazz;
            }

            // (0.2) Try loading the class with the system class loader, to prevent
            //       the webapp from overriding Java SE classes. This implements
            //       SRV.10.7.2
            String resourceName = binaryNameToPath(name, false);

            ClassLoader javaseLoader = getJavaseClassLoader();
            boolean tryLoadingFromJavaseLoader;
            try {
                // Use getResource as it won't trigger an expensive
                // ClassNotFoundException if the resource is not available from
                // the Java SE class loader. However (see
                // https://bz.apache.org/bugzilla/show_bug.cgi?id=58125 for
                // details) when running under a security manager in rare cases
                // this call may trigger a ClassCircularityError.
                // See https://bz.apache.org/bugzilla/show_bug.cgi?id=61424 for
                // details of how this may trigger a StackOverflowError
                // Given these reported errors, catch Throwable to ensure any
                // other edge cases are also caught
                URL url;
                if (securityManager != null) {
                    PrivilegedAction<URL> dp = new PrivilegedJavaseGetResource(resourceName);
                    url = AccessController.doPrivileged(dp);
                } else {
                    url = javaseLoader.getResource(resourceName);
                }
                tryLoadingFromJavaseLoader = (url != null);
            } catch (Throwable t) {
                // Swallow all exceptions apart from those that must be re-thrown
                ExceptionUtils.handleThrowable(t);
                // The getResource() trick won't work for this class. We have to
                // try loading it directly and accept that we might get a
                // ClassNotFoundException.
                tryLoadingFromJavaseLoader = true;
            }

            if (tryLoadingFromJavaseLoader) {
                try {
                    clazz = javaseLoader.loadClass(name);
                    if (clazz != null) {
                        if (resolve) {
                            resolveClass(clazz);
                        }
                        return clazz;
                    }
                } catch (ClassNotFoundException e) {
                    // Ignore
                }
            }

            // (0.5) Permission to access this class when using a SecurityManager
            if (securityManager != null) {
                int i = name.lastIndexOf('.');
                if (i >= 0) {
                    try {
                        securityManager.checkPackageAccess(name.substring(0, i));
                    } catch (SecurityException se) {
                        String error = sm.getString("webappClassLoader.restrictedPackage", name);
                        log.info(error, se);
                        throw new ClassNotFoundException(error, se);
                    }
                }
            }

            boolean delegateLoad = delegate || filter(name, true);

            // (1) Delegate to our parent if requested
            if (delegateLoad) {
                try {
                    clazz = Class.forName(name, false, parent);
                    if (clazz != null) {
                        if (resolve) {
                            resolveClass(clazz);
                        }
                        return clazz;
                    }
                } catch (ClassNotFoundException e) {
                    // Ignore
                }
            }

            // (2) Search local repositories
            try {
                clazz = findClass(name);
                if (clazz != null) {
                    if (resolve) {
                        resolveClass(clazz);
                    }
                    return clazz;
                }
            } catch (ClassNotFoundException e) {
                // Ignore
            }

            // (3) Delegate to parent unconditionally
            if (!delegateLoad) {
                try {
                    clazz = Class.forName(name, false, parent);
                    if (clazz != null) {
                        if (resolve) {
                            resolveClass(clazz);
                        }
                        return clazz;
                    }
                } catch (ClassNotFoundException e) {
                    // Ignore
                }
            }
        }

        throw new ClassNotFoundException(name);
    }
}
```



## Links

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)

## References

1. [Class Loader How-To](https://tomcat.apache.org/tomcat-10.1-doc/class-loader-howto.html)
