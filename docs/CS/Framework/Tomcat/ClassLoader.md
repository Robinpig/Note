## Introduction

Every time you create an instance of a Java class, the class must first be loaded into memory.
The [system class loader](/docs/CS/Java/JDK/JVM/ClassLoader.md) is the default class loader and searches the directories and JAR files specified in the CLASSPATH environment variable.

A servlet container needs a customized loader and cannot simply use the system's class loader because it should not trust the servlets it is running.
If it were to load all servlets and other classes needed by the servlets using the system's class loader, then a servlet would be able to access any class and library included in the CLASSPATH environment variable of the running JVM.
This would be a breach of security.
A servlet is only allowed to load classes in the WEB-INF/classes directory and its subdirectories and from the libraries deployed into the WEB-INF/lib directory.
That's why a servlet container requires a loader of its own.
Each web application (context) in a servlet container has its own loader.
A loader employs a class loader that applies certain rules to loading classes.
In Catalina, a loader is represented by the `org.apache.catalina.Loader` interface.

Tomcat 的自定义 class loader 还要解决规范层面的两个问题：**每个应用能加载自己版本的 API 实现**（同一个 JVM 里两个应用各带一份不同版本的库），以及**改一个类不用重启进程**。后者在 11 的实现方式与旧资料差别最大，见 [Reloading](/docs/CS/Framework/Tomcat/ClassLoader.md?id=reloading)。

The reasons why Tomcat needs a custom class loader also include the following:

- To specify certain rules in loading classes.
- To cache the previously loaded classes.
- To pre-load classes so they are ready to use.

> [!WARNING]
>
> 旧版这一段说「the `getContainer` and `setContainer` methods of the Loader interface are used for building this association」以及「a class loader must implement the `org.apache.catalina.loader.Reloader` interface」。**`Reloader` 接口在 11.0.26 已被整体删除**（`catalina/loader/Reloader.java` 不存在，全树查不到该类型），`Loader` 与容器的绑定也不再是泛化的 `Container`，而是收紧成 `getContext()` / `setContext(Context)`。

## Loader interface

11.0.26 的 `org.apache.catalina.Loader` 只有这些方法（`catalina/Loader.java`）：

```java
void backgroundProcess();                                     // :46
ClassLoader getClassLoader();                                 // :54
Context getContext();                                         // :62
void setContext(Context context);                             // :70
boolean getDelegate();                                        // :78
void setDelegate(boolean delegate);                           // :86
void addPropertyChangeListener(PropertyChangeListener l);     // :94
boolean modified();                                           // :103
void removePropertyChangeListener(PropertyChangeListener l);  // :111
```

三个值得注意的收敛：

1. **没有 `getContainer()`/`setContainer()`**。Loader 只服务于 `Context`，接口签名直接写死 `Context`——旧版那个「Loader 可以挂在任意 Container 上」的抽象早已名存实亡。
2. **没有 `getReloadable()`/`setReloadable()`**。`reloadable` 现在是 **`Context` 的属性**而不是 Loader 的，判断在 `WebappLoader.backgroundProcess()` 里做（见下）。所以 `<Context reloadable="true">` 是对的写法，`<Loader reloadable="true"/>` 从来就不该写。
3. **没有 `getLoaderClass()`/`setLoaderClass()` 在接口上**——它们只存在于实现 `WebappLoader` 里（`:98`），因为换 loader 实现类是标准实现细节，不是契约。

`modified()` 仍在接口上，这保证了「实现自己判断有没有变」的语义；但触发方是容器的后台线程，不是 Loader 自己。

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

A more complex class loader hierarchy may also be configured.
By default, the Server and Shared class loaders are not defined and the simplified hierarchy shown above is used.
This more complex hierarchy may be used by defining values for the `server.loader` and/or `shared.loader` properties in `conf/catalina.properties`.

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
- The Shared class loader is visible to all web applications and may be used to share code across all web applications. However, any updates to this shared code will require a Tomcat restart.

The Common class loader contains additional classes that are made visible to both Tomcat internal classes and to all web applications.
Normally, application classes should NOT be placed here.
The locations searched by this class loader are defined by the `common.loader` property in `$CATALINA_BASE/conf/catalina.properties`.

The Webapp class loader is created for each web application that is deployed in a single Tomcat instance.
All unpacked classes and resources in the `/WEB-INF/classes` directory of your web application, plus classes and resources in JAR files under the `/WEB-INF/lib` directory, are made visible to this web application, but not to other ones.

As mentioned above, the web application class loader diverges from the default [Java delegation model](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=delegation-model).
When a request to load a class from the web application's WebappX class loader is processed, this class loader will look in the local repositories first, instead of delegating before looking.
There are exceptions. Classes which are part of the JRE base classes cannot be overridden.
Lastly, the web application class loader will always delegate first for Jakarta EE API classes for the specifications implemented by Tomcat (Servlet, JSP, EL, WebSocket, Authentication, Annotations) — 这条硬规则由 `filter()` 实现，见 [Forced delegation](/docs/CS/Framework/Tomcat/ClassLoader.md?id=forced-delegation)。
All other class loaders in Tomcat follow the usual delegation pattern.

因此，从 web 应用视角看，类与资源的查找次序是：

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

⚠️ 上面这个次序表里「System class loader classes」的位置需要修正一处认知：**`delegate="false"` 时 Java SE 类依然最先被查**（`loadClass` 的 `(0.2)` 步），所以「本地优先」不包括 JDK 类。旧资料常把它简化成「完全反双亲委派」，会误导排查。

WebappClassLoader was designed for optimization and security in mind.
For example, it caches the previously loaded classes to enhance performance.
It also caches the names of classes it has failed to find, so that the next time the same classes are requested, the class loader can throw the ClassNotFoundException without first trying to find them.
两个缓存的具体结构在 11 已经换掉，见 [Resource cache](/docs/CS/Framework/Tomcat/ClassLoader.md?id=resource-cache)。

CommonClassLoader 能加载的类都可以被 CatalinaClassLoader 和 SharedClassLoader 用，而 CatalinaClassLoader 和 SharedClassLoader 能加载的类则与对方相互隔离。
WebAppClassLoader 可以使用 SharedClassLoader 加载到的类，但各个 WebAppClassLoader 实例之间相互隔离。

共享的第三方 JAR 包加载特定 Web 应用的类，是通过把该应用的 `WebappClassLoader` 设为线程上下文类加载器（TCCL）来解决的——这一步发生在 `StandardContext.bind()` / `unbind()` 里，见 [Container](/docs/CS/Framework/Tomcat/Container.md)。

## CommonLoader

### initClassLoaders

Bootstrap loader for Catalina.
This application constructs a class loader for use in loading the Catalina internal classes
(by accumulating all of the JAR files found in the "server" directory under "catalina.home"),
and starts the regular execution of the container.
The purpose of this roundabout approach is to keep the Catalina internal classes (and any other classes they depend on,
such as an XML parser) out of the system class path and therefore not visible to application level classes.

```java
// Bootstrap.java:134-151
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
```

三个 loader 字段的名字值得记：`catalinaLoader` 对应配置项 `server.loader`（历史原因，Server 层在代码里叫 catalina）。它们建好后立刻被反射用来加载 `Catalina` 类，从而把容器内部实现从 system classpath 里隔离出去——这一步在 [Start 的 Bootstrap 一节](/docs/CS/Framework/Tomcat/Start.md?id=bootstrap)里讲。

`createClassLoader()` 在 11 有两处变化，一处是 API 现代化，一处是实质语义：

```java
// Bootstrap.java:159-195
private ClassLoader createClassLoader(String name, ClassLoader parent) throws Exception {

    String value = CatalinaProperties.getProperty(name + ".loader");
    if ((value == null) || (value.isEmpty())) {
        return parent;
    }

    value = replace(value);

    List<Repository> repositories = new ArrayList<>();

    String[] repositoryPaths = getPaths(value);

    for (String repository : repositoryPaths) {
        // Check for a JAR URL repository
        try {
            URI uri = new URI(repository);
            @SuppressWarnings("unused")
            URL url = uri.toURL();
            repositories.add(new Repository(repository, RepositoryType.URL));
            continue;
        } catch (IllegalArgumentException | MalformedURLException | URISyntaxException e) {
            // Ignore
        }

        // Local repository
        if (repository.endsWith("*.jar")) {
            repository = repository.substring(0, repository.length() - "*.jar".length());
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

**其一**：URL 探测从 `new URL(repository)` 改成 `new URI(repository).toURL()`，异常也从单一 `MalformedURLException` 变成 `IllegalArgumentException | MalformedURLException | URISyntaxException`。原因是 `java.net.URL(String)` 构造器在新 JDK 里已被标记废弃（协议处理器查找方式不安全），Tomcat 作为长期维护的项目必须避开它。副作用是判定标准变了：`URI` 的语法比 `URL` 更严格，某些历史上被当作 URL 的怪写法现在会落到本地仓库分支。

**其二**：`value.equals("")` 换成 `value.isEmpty()`，纯风格。

`return parent` 这一行是「默认不启用 Server/Shared 层」的实现机制：属性为空时**不建新 loader，直接把父级返回**，于是 `catalinaLoader == sharedLoader == commonLoader`，三层图退化成两层。这也是为什么文档说「默认简化层级」——不是特判，而是同一份代码的自然结果。

四种仓库类型（`URL` / `GLOB` / `JAR` / `DIR`）对应 `catalina.properties` 里的写法：`*.jar` 结尾是 GLOB（展开目录里的所有 jar），单个 `.jar` 是 JAR，其余是 DIR。

## WebappClassLoader

```java
// WebappLoader.java:84, :98
public class WebappLoader extends LifecycleMBeanBase
        implements Loader, PropertyChangeListener {

    private boolean delegate = false;

    /**
     * The Java class name of the ClassLoader implementation to be used.
     * This class should extend WebappClassLoaderBase, otherwise, a different
     * loader implementation must be used.
     */
    private String loaderClass = ParallelWebappClassLoader.class.getName();

    @Override
    public boolean modified() {                       // :293
        return classLoader != null && classLoader.modified();
    }
}

// ParallelWebappClassLoader.java:28
public class ParallelWebappClassLoader extends WebappClassLoaderBase {
```

`loaderClass` 默认是 `ParallelWebappClassLoader`（`:98`）——这个默认值从 8.0 起就没变过，但今天它已经**不代表「并行加载」**：`ParallelWebappClassLoader` 只剩 73 行，类体里几乎没有逻辑，因为并行加载所需的 `getClassLoadingLock(name)` 早已上提到 JDK `ClassLoader`（Java 7u25+）并由 `WebappClassLoaderBase` 无条件使用。留着这个类只是为了兼容 `<Loader loaderClass="...">` 的历史配置。看到线程名或类名里带 Parallel 就以为开了并行加载，是没有依据的。

## WebappClassLoaderBase

Specialized web application class loader.
This class loader is a full reimplementation of the `URLClassLoader` from the JDK.
It is designed to be fully compatible with a normal `URLClassLoader`, although its internal behavior may be completely different.

11.0.26 的类声明去掉了 `PermissionCheck`：

```java
// WebappClassLoaderBase.java:106-107
public abstract class WebappClassLoaderBase extends URLClassLoader
        implements Lifecycle, InstrumentableClassLoader, WebappProperties {
```

`PermissionCheck` 接口随 SecurityManager 支持一起删除，所以这里少了一个 implements——旧版这一行的第四个接口现在不存在了。

类注释里的 IMPLEMENTATION NOTE 也少了一条。11 剩五条，第一条的措辞变了：

> **IMPLEMENTATION NOTE** - By default, this class loader follows the delegation model required by the specification. **The bootstrap class loader** will be queried first, then the local repositories, and only then delegation to the parent class loader will occur. This allows the web application to override any shared class except the classes from J2SE. Special handling is provided from the JAXP XML parser interfaces, the JNDI interfaces, and the classes from the servlet API, which are never loaded from the webapp repositories. The `delegate` property allows an application to modify this behavior to move the parent class loader ahead of the local repositories.

其余四条（Jasper 限制会忽略含 servlet API 的仓库、生成含完整 JAR URL 的 source URL、本地仓库按构造顺序搜索、8.0 起实现 `InstrumentableClassLoader`）仍在。被删掉的那条是：

> ~~IMPLEMENTATION NOTE - No check for sealing violations or security is made unless a security manager is present.~~

它连同实现一起消失了——没有 SecurityManager，就没有「有没有 SM」这个分支前提。

```java
// WebappClassLoaderBase.java:257
protected boolean delegate = false;
```

### Resource cache

这是 11 相对 9.x/10.0 变化最大、也最容易写错的一块。**旧版那个「`ResourceEntry[]` 数组 + 按访问序的 LinkedHashMap + `cacheMaxSize` 可调 LRU」已经整体不存在**，取而代之是两个职责分离的结构：

```java
// WebappClassLoaderBase.java:244-248
/**
 * The cache of ResourceEntry for classes and resources we have loaded, keyed by resource path, not binary name.
 * Path is used as the key since resources may be requested by binary name (classes) or path (other resources such
 * as property files) and the mapping from binary name to path is unambiguous but the reverse mapping is ambiguous.
 */
protected final Map<String,ResourceEntry> resourceEntries = new ConcurrentHashMap<>();

// WebappClassLoaderBase.java:359-364
/*
 * Class resources are not cached since they are loaded on first use and the resource is then no longer required. It
 * does help, however, to cache classes that are not found as in some scenarios the same class will be searched for
 * many times and the greater the number of JARs/classes, the longer that lookup will take.
 */
private final ConcurrentLruCache<String> notFoundClassResources = new ConcurrentLruCache<>(1000);
```

三点要记住：

1. **键是资源路径而不是二进制类名**。注释给了理由：同一个缓存要同时服务类（按 `a.b.C` 请求）和普通资源（按 `a/b/C.properties` 请求），类名→路径的映射是单射，反向不是，所以统一存路径。`findLoadedClass0()` 因此要先做一次转换：

```java
// WebappClassLoaderBase.java:2367-2376
protected Class<?> findLoadedClass0(String name) {

    String path = binaryNameToPath(name, true);

    ResourceEntry entry = resourceEntries.get(path);
    if (entry != null) {
        return entry.loadedClass;
    }
    return null;
}
```

2. **正向缓存是无界的 `ConcurrentHashMap`**，不再是 LRU。类只会被加载一次且必须一直留着（否则同一 Class 会被重复定义），所以对它做淘汰本来就没有意义；旧版的 `cacheMaxSize`/`setCacheMaxSize` 因此被删掉了（11 源码里查不到这两个符号）。
3. **负向缓存才是 LRU，默认 1000 条**，且只缓存「没找到」。它现在有自己的调优入口：

```java
// WebappClassLoaderBase.java:374-375
public void setNotFoundClassResourceCacheSize(int notFoundClassResourceCacheSize) {
    notFoundClassResources.setLimit(notFoundClassResourceCacheSize);
}
```

这个负缓存的实际价值在 `WEB-INF/lib` jar 很多的时候：一个不存在的类（例如某个可选依赖的探测）会被反复请求，每次都全量扫 jar 代价极高，所以 `findResource` 路径上用 `notFoundClassResources.contains(path)`（`:761`）直接短路。

## Forced delegation

`delegate="false"` 时本地优先，但有一批包**永远强制先委派给父级**，由 `filter()` 决定：

```java
// WebappClassLoaderBase.java:2387-2408
protected boolean filter(String name, boolean isClassName) {

    if (name == null) {
        return false;
    }

    char ch;
    if (name.startsWith("jakarta")) {
        /* 7 == length("jakarta") */
        if (name.length() == 7) {
            return false;
        }
        ch = name.charAt(7);
        if (isClassName && ch == '.') {
            /* 8 == length("jakarta.") */
            if (name.startsWith("servlet.jsp.jstl.", 8)) {
                return false;
            }
            if (name.startsWith("annotation.", 8) || name.startsWith("el.", 8) || name.startsWith("servlet.", 8) ||
                    name.startsWith("websocket.", 8) || name.startsWith("security.auth.message.", 8)) {
                return true;
            }
        } else if (!isClassName && ch == '/') {
            /* ... 同样的判断，分隔符换成 '/' */
```

读这段代码要注意三个细节：

- 前缀是 `jakarta.`——这是 10.x 迁移的直接后果，9.x 时代这批名字是 `javax.servlet.` 等，所以旧版讲 filter 的笔记整段作废。
- 判断用的是 `charAt(7)` 而不是 `startsWith("jakarta.")`，为的是省一次字符串比较；代价是必须单独处理 `name.length() == 7`（恰好等于 `jakarta`）的边界。
- `jakarta.servlet.jsp.jstl.*` 被**显式排除**在强制委派之外（`return false`），因为 JSTL 实现是允许应用自带一份的（JSP 标准标签库的实现类不属于容器必须独占的 API）。

强制委派的清单正好对应「Tomcat 实现了哪些 Jakarta EE 规范」：Servlet、EL、WebSocket、Authentication（`security.auth.message.`）、Annotations。应用里如果打包了这些 API 的 jar，会发现「明明带了却加载不到自己的版本」，根因就在这里，而不是 classpath 顺序。

## loadClass

默认 loadClass 方法是双亲委派机制；Tomcat 反过来：先查自己的仓库，再委派给父级。

11.0.26 的算法（类注释 `:1148-1166`）：

- Call `findLoadedClass(String)` to check if the class has already been loaded. If it has, the same `Class` object is returned.
- If the `delegate` property is set to `true`(**default false**), call the `loadClass()` method of the parent class loader, if any.
- Call `findClass()` to find this class in our locally defined repositories.
- Call the `loadClass()` method of our parent class loader, if any.

If the class was found using the above steps, and the `resolve` flag is true, this method will then call `resolveClass(Class)` on the resulting Class object.

```java
// WebappClassLoaderBase.java:1170-1249
@Override
public Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {

    synchronized (JreCompat.isGraalAvailable() ? this : getClassLoadingLock(name)) {
        if (log.isTraceEnabled()) {
            log.trace("loadClass(" + name + ", " + resolve + ")");
        }
        Class<?> clazz;

        // Log access to stopped class loader
        checkStateForClassLoading(name);

        // (0) Check our previously loaded local class cache
        clazz = findLoadedClass0(name);
        if (clazz != null) {
            if (log.isTraceEnabled()) {
                log.trace("  Returning class from cache");
            }
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

        /*
         * (0.2) Try loading the class with the bootstrap class loader, to prevent the webapp from overriding Java
         * SE classes. This implements SRV.10.7.2
         */
        String resourceName = binaryNameToPath(name, false);

        ClassLoader javaseLoader = getJavaseClassLoader();
        boolean tryLoadingFromJavaseLoader;
        try {
            /*
             * Use getResource as it won't trigger an expensive ClassNotFoundException if the resource is not
             * available from the Java SE class loader.
             *
             * See https://bz.apache.org/bugzilla/show_bug.cgi?id=61424 for details of how this may trigger a
             * StackOverflowError.
             *
             * Given these reported errors, catch Throwable to ensure all edge cases are caught.
             */
            URL url = javaseLoader.getResource(resourceName);
            tryLoadingFromJavaseLoader = url != null;
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

        boolean delegateLoad = delegate || filter(name, true);
```

`(0.2)` 这一步是整段最巧的地方，也是最容易被误读的：**它用 `getResource()` 而不是 `loadClass()` 来试探某个类是否属于 Java SE**。理由写在注释里——`loadClass` 失败会抛 `ClassNotFoundException`，那是个昂贵的构造（要填栈轨迹）；而 `getResource()` 返回 null 即可判定。所以「先探资源再决定要不要委派」是一个性能技巧。注释里保留的 bugzilla 链接（61424）说明这个技巧本身也有坑（会触发 StackOverflowError），因此 catch 的是 `Throwable`。

旧版这一段的三处 SecurityManager 代码在 11 全部消失：

1. `if (securityManager != null) { ... new PrivilegedJavaseGetResource(resourceName) ... AccessController.doPrivileged(dp) }` → 现在只剩一行 `javaseLoader.getResource(resourceName)`。`PrivilegedJavaseGetResource` 这个私有内部类已不存在。
2. 注释里关于 bugzilla **58125**（「在 security manager 下这个调用可能触发 ClassCircularityError」）的整段说明被删——前提没了，说明也不再需要。
3. 紧随其后的 `(0.5)` 步（`securityManager.checkPackageAccess(...)` 与 `webappClassLoader.restrictedPackage` 报错）整块删除。**这意味着「受限包」不再由类加载器拦截**：旧版那种「SM 下访问 `sun.misc.*` 会抛 ClassNotFoundException(restrictedPackage)」的行为在 11 不复存在。

`(0)` 与 `(0.1)` 两级缓存的顺序也不能换：`(0)` 查 Tomcat 自己的 `resourceEntries`（只含本 loader 加载的），`(0.1)` 查 JVM 的 `findLoadedClass`。GraalVM 下 `(0.1)` 被跳过并直接返回 null（`JreCompat.isGraalAvailable()`），同时锁也退化成 `this`——因为 Graal 的 native-image 不支持 `getClassLoadingLock` 的并行语义。

```java
        // (1) Delegate to our parent if requested
        if (delegateLoad) {
            if (log.isTraceEnabled()) {
                log.trace("  Delegating to parent classloader1 " + parent);
            }
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
        if (log.isTraceEnabled()) {
            log.trace("  Searching local repositories");
        }
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
            if (log.isTraceEnabled()) {
                log.trace("  Delegating to parent classloader at end: " + parent);
            }
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

    if (log.isDebugEnabled()) {
        log.debug(ToStringUtil.classPathForCNFE(this));
    }
    throw new ClassNotFoundException(name);
}
```

步骤 (1) 与 (3) 是同一个动作的两个入口，靠 `delegateLoad` 这个布尔保证只走一边——所以「本地优先」并不是不委派，只是把委派挪到了后面。

**最后一行之前有个 11 新增的排障利器**：抛出 `ClassNotFoundException` 前，如果 debug 级别开着，会把本 loader 的完整 classpath 打出来（`ToStringUtil.classPathForCNFE(this)`）。这意味着「应用报 CNFE 却看不出它到底找了哪些 jar」这个老问题，现在只要把 `org.apache.catalina.loader.WebappClassLoaderBase` 的级别调到 DEBUG 就能看到搜索路径，不必再靠翻 `WEB-INF/lib` 猜。日志架构见 [Tomcat 的 Log 一节](/docs/CS/Framework/Tomcat/Tomcat.md?id=log)。

## Reloading

`reloadable` 仍然可用，但实现方式与旧资料描述的不是一回事。旧文说「a class loader uses a separate thread that keeps checking the time stamps」并要求实现 `Reloader` 接口——**`Reloader` 接口在 11 已被删除**，也没有任何专用线程。

现在的机制是搭容器后台处理线程的顺风车：

```java
// WebappLoader.java:229-243
@Override
public void backgroundProcess() {
    Context context = getContext();
    if (context != null) {
        if (context.getReloadable() && modified()) {
            Thread currentThread = Thread.currentThread();
            ClassLoader originalTccl = currentThread.getContextClassLoader();
            try {
                currentThread.setContextClassLoader(WebappLoader.class.getClassLoader());
                context.reload();
            } finally {
                currentThread.setContextClassLoader(originalTccl);
            }
        }
    }
}
```

四个要点：

1. 检查由 `ContainerBase` 的后台线程周期性调用 `Loader.backgroundProcess()` 触发（该线程与调度拓扑见 [memory](/docs/CS/Framework/Tomcat/memory.md) 与 [Container](/docs/CS/Framework/Tomcat/Container.md)），不是独立线程。
2. 判定条件 `context.getReloadable() && modified()`：`reloadable` 是 **Context** 属性；`WebappLoader.modified()`（`:293`）只是转发给 `classLoader.modified()`，由类加载器比对 `WEB-INF/classes` 与 `WEB-INF/lib` 里各类文件的最后修改时间。
3. reload 之前把 **TCCL 换成 `WebappLoader.class.getClassLoader()`**（容器侧 loader）再执行 `context.reload()`——因为重建应用类加载器时不能让正在被丢弃的那个 loader 参与加载。`finally` 里必须还原，否则会把后台线程的上下文永久留在错误的 loader 上。
4. 重载会丢弃整个旧 `WebappClassLoader` 及其 `resourceEntries` 缓存，因此**这是内存泄漏的高发点**：静态字段、线程、JDBC driver 注册都可能把旧 loader 钉住。生产环境不开 `reloadable`，改用 [Deployment](/docs/CS/Framework/Tomcat/Deployment.md) 里的重新部署流程。

## What changed in 11

本页按 11.0.26 重写，相对旧摘录的差异汇总：

| 位置 | 11.0.26 的现实 |
| :-- | :-- |
| `WebappClassLoaderBase` 类声明 | 不再 implements `PermissionCheck` |
| 类注释 IMPLEMENTATION NOTE | 少一条（sealing 检查需 SM）；首条措辞从 "system class loader" 改为 "**bootstrap** class loader" |
| `loadClass` `(0.2)` | `securityManager != null` 分支与 `PrivilegedJavaseGetResource` 删除，只剩 `javaseLoader.getResource()` |
| `loadClass` `(0.5)` | `checkPackageAccess` 整块删除，受限包不再由 loader 拦截 |
| 类缓存 | `ResourceEntry[]` + LRU 换成 `ConcurrentHashMap` **按资源路径**为键；`cacheMaxSize` 属性消失 |
| 负缓存 | 新增 `ConcurrentLruCache notFoundClassResources`（默认 1000）与 `setNotFoundClassResourceCacheSize()` |
| `filter()` | 强制委派前缀从 `javax.*` 换成 `jakarta.*`，清单含 Authentication/Annotations |
| `CNFE` 抛出前 | 新增 `ToStringUtil.classPathForCNFE(this)` 的 debug 输出 |
| `Loader` 接口 | 无 `getContainer`/`setContainer`（改 `getContext`/`setContext`）、无 `getReloadable`/`setReloadable` |
| `Reloader` 接口 | **已删除**；重载由 `WebappLoader.backgroundProcess()` 承担 |
| `Bootstrap.createClassLoader` | URL 探测改 `new URI(...).toURL()`（`URL(String)` 已废弃） |

## Links

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Container](/docs/CS/Framework/Tomcat/Container.md)
- [Deployment](/docs/CS/Framework/Tomcat/Deployment.md)
- [Start](/docs/CS/Framework/Tomcat/Start.md)
- [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)

## References

1. [Tomcat 11.0 Class Loader How-To](https://tomcat.apache.org/tomcat-11.0-doc/class-loader-howto.html)
2. [Tomcat 11.0 API: WebappClassLoaderBase](https://tomcat.apache.org/tomcat-11.0-doc/api/org/apache/catalina/loader/WebappClassLoaderBase.html)
