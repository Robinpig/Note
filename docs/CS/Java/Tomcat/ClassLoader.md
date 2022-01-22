## Introduction


```
        AppClassLoader
            |
           \|/
      CommonClassLoader
            |
            +---------------------------+
           \|/                         \|/
      SharedClassLoader          CatalinaClassLoader
            |
           \|/
      WebAppClassLoader

```

WebAppClassLoader for each app


#### initClassLoaders

commonLoader is a parent(delegate) of catalinaLoader and sharedLoader

```java
//Bootstrap.java
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
            handleThrowable(t);
            log.error("Class loader creation threw exception", t);
            System.exit(1);
        }
    }


    private ClassLoader createClassLoader(String name, ClassLoader parent)
        throws Exception {

        String value = CatalinaProperties.getProperty(name + ".loader");
        if ((value == null) || (value.equals(""))) {
            return parent;
        }

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
// org.apache.catalina.loader.WebappClassLoaderBase extends URLClassLoader
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
                    securityManager.checkPackageAccess(name.substring(0,i));
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
```


Bootstrap loader for Catalina. This application constructs a class loader for use in loading the Catalina internal classes (by accumulating all of the JAR files found in the "server" directory under "catalina.home"), and starts the regular execution of the container. The purpose of this roundabout approach is to keep the Catalina internal classes (and any other classes they depend on, such as an XML parser) out of the system class path and therefore not visible to application level classes.

using new URLClassLoader()
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
            handleThrowable(t);
            log.error("Class loader creation threw exception", t);
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

WebAppClassLoader



findClass

1. 先在 Web 应用本地目录下查找要加载的类。
2. 如果没有找到，交给父加载器去查找，它的父加载器就是上面提到的系统类加载器 `AppClassLoader`。
3. 如何父加载器也没找到这个类，抛出 `ClassNotFound`异常



loadClass



主要有六个步骤：

1. 先在本地 Cache 查找该类是否已经加载过，也就是说 Tomcat 的类加载器是否已经加载过这个类。
2. 如果 Tomcat 类加载器没有加载过这个类，再看看系统类加载器是否加载过。
3. 如果都没有，就让**ExtClassLoader**去加载，这一步比较关键，目的 **防止 Web 应用自己的类覆盖 JRE 的核心类**。因为 Tomcat 需要打破双亲委托机制，假如 Web 应用里自定义了一个叫 Object 的类，如果先加载这个 Object 类，就会覆盖 JRE 里面的那个 Object 类，这就是为什么 Tomcat 的类加载器会优先尝试用 `ExtClassLoader`去加载，因为 `ExtClassLoader`会委托给 `BootstrapClassLoader`去加载，`BootstrapClassLoader`发现自己已经加载了 Object 类，直接返回给 Tomcat 的类加载器，这样 Tomcat 的类加载器就不会去加载 Web 应用下的 Object 类了，也就避免了覆盖 JRE 核心类的问题。
4. 如果 `ExtClassLoader`加载器加载失败，也就是说 `JRE`核心类中没有这类，那么就在本地 Web 应用目录下查找并加载。
5. 如果本地目录下没有这个类，说明不是 Web 应用自己定义的类，那么由系统类加载器去加载。这里请你注意，Web 应用是通过`Class.forName`调用交给系统类加载器的，因为`Class.forName`的默认加载器就是系统类加载器。
6. 如果上述加载过程全部失败，抛出 `ClassNotFound`异常。



##### SharedClassLoader



##### CatalinaClassloader



CommonClassLoader

Specialized web application class loader.
This class loader is a full reimplementation of the URLClassLoader from the JDK. It is designed to be fully compatible with a normal URLClassLoader, although its internal behavior may be completely different.
IMPLEMENTATION NOTE - By default, this class loader follows the delegation model required by the specification. The system class loader will be queried first, then the local repositories, and only then delegation to the parent class loader will occur. This allows the web application to override any shared class except the classes from J2SE. Special handling is provided from the JAXP XML parser interfaces, the JNDI interfaces, and the classes from the servlet API, which are never loaded from the webapp repositories. The delegate property allows an application to modify this behavior to move the parent class loader ahead of the local repositories.
IMPLEMENTATION NOTE - Due to limitations in Jasper compilation technology, any repository which contains classes from the servlet API will be ignored by the class loader.
IMPLEMENTATION NOTE - The class loader generates source URLs which include the full JAR URL when a class is loaded from a JAR file, which allows setting security permission at the class level, even when a class is contained inside a JAR.
IMPLEMENTATION NOTE - Local repositories are searched in the order they are added via the initial constructor.
IMPLEMENTATION NOTE - No check for sealing violations or security is made unless a security manager is present.
IMPLEMENTATION NOTE - As of 8.0, this class loader implements InstrumentableClassLoader, permitting web application classes to instrument other classes in the same web application. It does not permit instrumentation of system or container classes or classes in other web apps.



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
...
}
```

