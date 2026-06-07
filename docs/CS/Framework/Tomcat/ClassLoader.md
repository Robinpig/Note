## Introduction

每次创建 Java 类的实例时，该类必须首先被加载到内存中。
[system class loader](/docs/CS/Java/JDK/JVM/ClassLoader.md) 是默认的类加载器，搜索 CLASSPATH 环境变量中指定的目录和 JAR 文件。

Servlet 容器需要自定义的加载器，不能简单地使用系统类加载器，因为它不应该信任它所运行的 servlet。
如果它使用系统类加载器加载所有 servlet 和 servlet 所需的其他类（如前面章节中所述），那么 servlet 将能够访问运行中的 Java 虚拟机（JVM）的 CLASSPATH 环境变量中包含的任何类和库，这将构成安全漏洞。
Servlet 只允许加载 WEB-INF/classes 目录及其子目录中的类，以及部署在 WEB-INF/lib 目录中的库。
这就是 servlet 容器需要自己的加载器的原因。
Servlet 容器中的每个 Web 应用（context）都有自己的加载器。
加载器使用一个类加载器，该加载器应用特定规则来加载类。
在 Catalina 中，加载器由 org.apache.catalina.Loader 接口表示。

Tomcat 需要自己的加载器的另一个原因是为了支持自动重新加载——当 WEB-INF/classes 或 WEB-INF/lib 目录中的类被修改时。
Tomcat 加载器实现中的类加载器使用一个单独的线程，持续检查 servlet 和支持类文件的时间戳。
为了支持自动重新加载，类加载器必须实现 org.apache.catalina.loader.Reloader 接口。

Tomcat 需要自定义类加载器的原因还包括：

- 指定加载类的特定规则。
- 缓存先前加载的类。
- 预加载类以便随时可用。

Tomcat 加载器实现通常与 context 关联，Loader 接口的 getContainer 和 setContainer 方法用于建立这种关联。
加载器还可以支持重新加载，如果 context 中的一个或多个类被修改。
这样，servlet 程序员可以重新编译 servlet 或支持类，新类将在不重启 Tomcat 的情况下重新加载。
为此，Loader 接口提供了 modified 方法。
在加载器实现中，如果其仓库中的一个或多个类已被修改，modified 方法必须返回 true，因此需要重新加载。
然而，加载器本身不执行重新加载，而是调用 Context 接口的 reload 方法。
另外两个方法 setReloadable 和 getReloadable 用于确定加载器中是否启用了重新加载。
默认情况下，在 Context 的标准实现中，重新加载是禁用的。
因此，要启用 context 的重新加载，需要在 server.xml 文件中为该 context 添加 Context 元素，如下所示：

```xml
<Context path="/myApp" docBase="myApp" debug="0" reloadable="true"/>
```

注意：当与加载器关联的容器需要 servlet 类时（即调用其 invoke 方法时），容器首先调用加载器的 getClassLoader 方法获取类加载器，然后调用类加载器的 loadClass 方法加载 servlet 类。

## ClassLoader hierarchy

当 Tomcat 启动时，它会创建一组类加载器，组织成以下父子关系，其中父类加载器在子类加载器之上：

```
      Bootstrap
          |
       System
          |
       Common
        /     \
  Webapp1   Webapp2 ...
```

也可以配置更复杂的类加载器层次结构，如下图所示。
默认情况下，Server 和 Shared 类加载器未定义，使用上述简化层次结构。
通过在 `conf/catalina.properties` 中为 `server.loader` 和/或 `shared.loader` 属性设置值，可以使用此更复杂的层次结构。

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

- Server 类加载器仅对 Tomcat 内部可见，对 Web 应用完全不可见。
- Shared 类加载器对所有 Web 应用可见，可用于在所有 Web 应用间共享代码。但是，对此共享代码的任何更新都需要重启 Tomcat。

Common 类加载器包含对 Tomcat 内部类和所有 Web 应用都可见的附加类。
通常，应用程序类不应放置在此处。
此类加载器搜索的位置由 `$CATALINA_BASE/conf/catalina.properties` 中的 `common.loader` 属性定义。

Webapp 类加载器是为部署在单个 Tomcat 实例中的每个 Web 应用创建的。
Web 应用的 `/WEB-INF/classes` 目录中的所有解压类和资源，以及 `/WEB-INF/lib` 目录下 JAR 文件中的类和资源，对该 Web 应用可见，但对其他 Web 应用不可见。

如上所述，Web 应用类加载器不同于默认的 [Java 委派模型](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=Delegation-model)。
当处理从 Web 应用的 WebappX 类加载器加载类的请求时，该类加载器将首先在本地仓库中查找，而不是先委派再查找。
但也有例外：JRE 基础类部分的类不能被覆盖。
还有一些例外，如 XML 解析器组件，可以使用可升级模块功能进行覆盖。
最后，Web 应用类加载器对于 Tomcat 实现的 Jakarta EE API 类（Servlet、JSP、EL、WebSocket）将始终首先委派。
Tomcat 中的所有其他类加载器遵循通常的委派模式。

因此，从 Web 应用的角度来看，类和资源加载按以下顺序查找：

- JVM 的 Bootstrap 类
- Web 应用的 /WEB-INF/classes
- Web 应用的 /WEB-INF/lib/*.jar
- System 类加载器类
- Common 类加载器类

如果 Web 应用类加载器配置了 `<Loader delegate="true"/>`，则顺序变为：

- JVM 的 Bootstrap 类
- System 类加载器类
- Common 类加载器类
- Web 应用的 /WEB-INF/classes
- Web 应用的 /WEB-INF/lib/*.jar

WebappClassLoader 的设计考虑了优化和安全性。
例如，它缓存先前加载的类以提升性能。
它还缓存了查找失败的类名，以便下次请求加载相同类时，类加载器可以直接抛出 ClassNotFoundException，而无需再次尝试查找。
WebappClassLoader 在仓库列表以及指定的 JAR 文件中搜索类。

CommonClassLoader 能加载的类都可以被 CatalinaClassLoader 和 SharedClassLoader 使用，而 CatalinaClassLoader 和 SharedClassLoader 能加载的类则与对方相互隔离。
WebAppClassLoader 可以使用 SharedClassLoader 加载到的类，但各个 WebAppClassLoader 实例之间相互隔离。

共享的第三方 JAR 包加载特定 Web 应用的类是通过设置 WebClassLoader 到线程上下文加载器来解决。

## CommonLoader

### initClassLoaders

Catalina 的 Bootstrap 加载器。
此应用程序构造一个类加载器用于加载 Catalina 内部类（通过累积 "catalina.home" 下 "server" 目录中的所有 JAR 文件），并启动容器的常规执行。
这种迂回方法的目的是将 Catalina 内部类（以及它们依赖的任何其他类，如 XML 解析器）排除在系统类路径之外，从而使其对应用程序级别的类不可见。

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

专门的 Web 应用类加载器。
此类加载器是 JDK 中 URLClassLoader 的完全重新实现。
它设计为与普通的 URLClassLoader 完全兼容，尽管其内部行为可能完全不同。

- 实现说明 - 默认情况下，此类加载器遵循规范要求的委派模型。将首先查询系统类加载器，然后是本地仓库，最后才委派给父类加载器。这允许 Web 应用覆盖任何共享类（J2SE 的类除外）。JAXP XML 解析器接口、JNDI 接口和 servlet API 中的类有特殊处理，它们永远不会从 Web 应用仓库中加载。delegate 属性允许应用程序修改此行为，将父类加载器放到本地仓库之前。
- 实现说明 - 由于 Jasper 编译技术的限制，任何包含 servlet API 类的仓库将被类加载器忽略。
- 实现说明 - 当从 JAR 文件加载类时，类加载器会生成包含完整 JAR URL 的源 URL，这允许在类级别设置安全权限，即使类包含在 JAR 内部。
- 实现说明 - 按初始构造函数中添加的顺序搜索本地仓库。
- 实现说明 - 除非存在 security manager，否则不会检查密封违规或安全性。
- 实现说明 - 从 8.0 开始，此类加载器实现了 InstrumentableClassLoader，允许 Web 应用类检测同一 Web 应用中的其他类。它不允许检测系统或容器类，或其他 Web 应用中的类。

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

默认 loadClass 方法是双亲委派机制。
先用 WebClass Loader，绕过常用的 AppClassLoader，然后到 Ext 和 Bootstrap 对核心类库加载，最后用 AppClassLoader。

使用以下算法加载指定名称的类，直到找到并返回该类。
如果找不到该类，则返回 ClassNotFoundException。

- 调用 findLoadedClass(String) 检查该类是否已加载。如果已加载，返回相同的 Class 对象。
- 如果 delegate 属性设置为 true（**默认为 false**），调用父类加载器的 loadClass() 方法（如果有）。
- 调用 findClass() 在我们的本地仓库中查找此类。
- 调用父类加载器的 loadClass() 方法（如果有）。

如果通过上述步骤找到了类，并且 resolve 标志为 true，则此方法将调用结果 Class 对象上的 resolveClass(Class)。

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
            // ... (remainder of method)
        }

        throw new ClassNotFoundException(name);
    }
}
```

## Links

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)

## References

1. [Class Loader How-To](https://tomcat.apache.org/tomcat-10.1-doc/class-loader-howto.html)
