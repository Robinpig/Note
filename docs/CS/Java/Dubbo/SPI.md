

## [What is SPI ?](/docs/CS/Java/JDK/Basic/SPI.md)


## Introduction

![Dubbo-SPI](./images/Dubbo-SPI.png)


```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target({ElementType.TYPE})
public @interface SPI {

    /**
     * default extension name
     */
    String value() default "";

}
```

`SPI` marker for extension interface

Such as Protocol

```java
//Protocol. (API/SPI, Singleton, ThreadSafe)
@SPI("dubbo")
public interface Protocol {
...
  
  	@Adaptive
    <T> Exporter<T> export(Invoker<T> invoker) throws RpcException;
}
```



Changes on extension configuration file Use Protocol as an example, its configuration file 'META-INF/dubbo/com.xxx.Protocol' is changed from: 
       com.foo.XxxProtocol
       com.foo.YyyProtocol

to key-value pair 
       xxx=com.foo.XxxProtocol
       yyy=com.foo.YyyProtocol

 The reason for this change is:
If there's third party library referenced by static field or by method in extension implementation, its class will fail to initialize if the third party library doesn't exist. In this case, dubbo cannot figure out extension's id therefore cannot be able to map the exception information with the extension, if the previous format is used.

For example:
Fails to load Extension("mina"). When user configure to use mina, dubbo will complain the extension cannot be loaded, instead of reporting which extract extension implementation fails and the extract reason.



## ExtensionLoader

org.apache.dubbo.rpc.model.ApplicationModel, DubboBootstrap and this class are at present designed to be singleton or static (by itself totally static or uses some static fields). So the instances returned from them are of process or classloader scope. If you want to support multiple dubbo servers in a single process, you may need to refactor these three classes.
Load dubbo extensions
auto inject dependency extension
auto wrap extension in wrapper
default extension is an adaptive instance
See Also:
[Service Provider in Java 5](https://docs.oracle.com/javase/1.5.0/docs/guide/jar/jar.html#Service%20Provider) , SPI, Adaptive, Activate



```java
public class ExtensionLoader<T> {

  	private static final Pattern NAME_SEPARATOR = Pattern.compile("\\s*[,]+\\s*");

    private static final ConcurrentMap<Class<?>, ExtensionLoader<?>> EXTENSION_LOADERS = new ConcurrentHashMap<>(64);

    private static final ConcurrentMap<Class<?>, Object> EXTENSION_INSTANCES = new ConcurrentHashMap<>(64);

    private final Class<?> type;

    private final ExtensionFactory objectFactory;

    private final ConcurrentMap<Class<?>, String> cachedNames = new ConcurrentHashMap<>();

    private final Holder<Map<String, Class<?>>> cachedClasses = new Holder<>();

    private final Map<String, Object> cachedActivates = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, Holder<Object>> cachedInstances = new ConcurrentHashMap<>();
    private final Holder<Object> cachedAdaptiveInstance = new Holder<>();
    private volatile Class<?> cachedAdaptiveClass = null;
    private String cachedDefaultName;
    private volatile Throwable createAdaptiveInstanceError;

    private Set<Class<?>> cachedWrapperClasses;

    private Map<String, IllegalStateException> exceptions = new ConcurrentHashMap<>();

    // Record all unacceptable exceptions when using SPI
    private Set<String> unacceptableExceptions = new ConcurrentHashSet<>();

    private static volatile LoadingStrategy[] strategies = loadLoadingStrategies();

    public static void setLoadingStrategies(LoadingStrategy... strategies) {
        if (ArrayUtils.isNotEmpty(strategies)) {
            ExtensionLoader.strategies = strategies;
        }
    }

    // Load all prioritized Loading Strategies via ServiceLoader
    private static LoadingStrategy[] loadLoadingStrategies() {
        return stream(load(LoadingStrategy.class).spliterator(), false)
                .sorted()
                .toArray(LoadingStrategy[]::new);
    }

    // Get all Loading Strategies
    public static List<LoadingStrategy> getLoadingStrategies() {
        return asList(strategies);
    }

    private static <T> boolean withExtensionAnnotation(Class<T> type) {
        return type.isAnnotationPresent(SPI.class);
    }
  ...
}
```



### getExtensionLoader

1. getExtensionLoader
2. getAdaptiveExtension

```java
@SuppressWarnings("unchecked")
public static <T> ExtensionLoader<T> getExtensionLoader(Class<T> type) {
  	// assert type nonNull & isInterface & with @SPI
    
    ExtensionLoader<T> loader = (ExtensionLoader<T>) EXTENSION_LOADERS.get(type);
    if (loader == null) {// if no cache, new ExtensionLoader & put in cache
        EXTENSION_LOADERS.putIfAbsent(type, new ExtensionLoader<T>(type));
        loader = (ExtensionLoader<T>) EXTENSION_LOADERS.get(type);
    }
    return loader;
}

private ExtensionLoader(Class<?> type) {
        this.type = type;
        objectFactory =
                (type == ExtensionFactory.class ? null : ExtensionLoader.getExtensionLoader(ExtensionFactory.class).getAdaptiveExtension());
    }
```



### getAdaptiveExtension



1. if cachedAdaptiveInstance, return
2. Else `getAdaptiveExtensionClass`
   1. cachedAdaptiveClass = `getExtensionClasses`
      1. invoke `loadExtensionClasses`
   2. Or cachedAdaptiveClass == null, `createAdaptiveExtensionClass`
3. `injectExtension`



Use DCL get instance from `cachedAdaptiveInstance`

```java
@SuppressWarnings("unchecked")
public T getAdaptiveExtension() {
    Object instance = cachedAdaptiveInstance.get();
    if (instance == null) {
        if (createAdaptiveInstanceError != null) {
            throw new IllegalStateException("Failed to create adaptive instance: " +
                    createAdaptiveInstanceError.toString(),
                    createAdaptiveInstanceError);
        }

        synchronized (cachedAdaptiveInstance) {
            instance = cachedAdaptiveInstance.get();
            if (instance == null) {
                try {
                    instance = createAdaptiveExtension();
                    cachedAdaptiveInstance.set(instance);
                } catch (Throwable t) {
                    createAdaptiveInstanceError = t;
                    throw new IllegalStateException("Failed to create adaptive instance: " + t.toString(), t);
                }
            }
        }
    }

    return (T) instance;
}
```



#### createAdaptiveExtension

```java
@SuppressWarnings("unchecked")
private T createAdaptiveExtension() {
    try {
        return injectExtension((T) getAdaptiveExtensionClass().newInstance());
    } catch (Exception e) {
        throw new IllegalStateException("Can't create adaptive extension " + type + ", cause: " + e.getMessage(), e);
    }
}

private Class<?> getAdaptiveExtensionClass() {
    getExtensionClasses();
    if (cachedAdaptiveClass != null) {
        return cachedAdaptiveClass;
    }
    return cachedAdaptiveClass = createAdaptiveExtensionClass();
}

```



#### createAdaptiveExtensionClass

**create Dynamic Class** by [AdaptiveClassCodeGenerator](/docs/CS/Java/Dubbo/SPi.md?id=AdaptiveClassCodeGenerator)

```java
private Class<?> createAdaptiveExtensionClass() {
    String code = new AdaptiveClassCodeGenerator(type, cachedDefaultName).generate();
    ClassLoader classLoader = findClassLoader();
    org.apache.dubbo.common.compiler.Compiler compiler =
            ExtensionLoader.getExtensionLoader(org.apache.dubbo.common.compiler.Compiler.class).getAdaptiveExtension();
    return compiler.compile(code, classLoader);
}
```





#### injectExtension

objectFactory set by ExtensionLoader's constructor

```java
// ExtensionFactory
@SPI
public interface ExtensionFactory {
    // Get extension.
    <T> T getExtension(Class<T> type, String name);
}
```

Implementions:

1. AdaptiveExtensionFactory

2. SpiExtensionFactory

3. SpringExtensionFactory

   

use `setter` to inject

```java
private T injectExtension(T instance) {

    if (objectFactory == null) {
        return instance;
    }

    try {
        for (Method method : instance.getClass().getMethods()) {
            if (!isSetter(method)) {
                continue;
            }
            // Check DisableInject to see if we need auto injection for this property
            if (method.getAnnotation(DisableInject.class) != null) {
                continue;
            }
            Class<?> pt = method.getParameterTypes()[0];
            if (ReflectUtils.isPrimitives(pt)) {
                continue;
            }

            try {
                String property = getSetterProperty(method);
                Object object = objectFactory.getExtension(pt, property);
                if (object != null) {
                    method.invoke(instance, object);
                }
            } catch (Exception e) {
                logger.error("Failed to inject via method " + method.getName()
                        + " of interface " + type.getName() + ": " + e.getMessage(), e);
            }

        }
    } catch (Exception e) {
        logger.error(e.getMessage(), e);
    }
    return instance;
}

private void initExtension(T instance) {
    if (instance instanceof Lifecycle) {
        Lifecycle lifecycle = (Lifecycle) instance;
        lifecycle.initialize();
    }
}
```



#### getExtensionClasses

```java
private Map<String, Class<?>> getExtensionClasses() {
    Map<String, Class<?>> classes = cachedClasses.get();
    if (classes == null) {
        synchronized (cachedClasses) {
            classes = cachedClasses.get();
            if (classes == null) {
                classes = loadExtensionClasses();
                cachedClasses.set(classes);
            }
        }
    }
    return classes;
}
```

##### loadExtensionClasses

```java
/**
 * synchronized in getExtensionClasses
 */
private Map<String, Class<?>> loadExtensionClasses() {
    cacheDefaultExtensionName();

    Map<String, Class<?>> extensionClasses = new HashMap<>();

    for (LoadingStrategy strategy : strategies) {
        loadDirectory(extensionClasses, strategy.directory(), type.getName(), strategy.preferExtensionClassLoader(),
                strategy.overridden(), strategy.excludedPackages());
        loadDirectory(extensionClasses, strategy.directory(), type.getName().replace("org.apache", "com.alibaba"),
                strategy.preferExtensionClassLoader(), strategy.overridden(), strategy.excludedPackages());
    }

    return extensionClasses;
}

/**
 * extract and cache default extension name if exists
 */
private void cacheDefaultExtensionName() {
    final SPI defaultAnnotation = type.getAnnotation(SPI.class);
    if (defaultAnnotation == null) {
        return;
    }

    String value = defaultAnnotation.value();
    if ((value = value.trim()).length() > 0) {
        String[] names = NAME_SEPARATOR.split(value);
        if (names.length > 1) {
            throw new IllegalStateException("More than 1 default extension name on extension " + type.getName()
                    + ": " + Arrays.toString(names));
        }
        if (names.length == 1) {
            cachedDefaultName = names[0];
        }
    }
}
```



##### loadDirectory

```java
private void loadDirectory(Map<String, Class<?>> extensionClasses, String dir, String type,
                           boolean extensionLoaderClassLoaderFirst, boolean overridden, String... excludedPackages) {
    String fileName = dir + type;
    try {
        Enumeration<java.net.URL> urls = null;
        ClassLoader classLoader = findClassLoader();

        // try to load from ExtensionLoader's ClassLoader first
        if (extensionLoaderClassLoaderFirst) {
            ClassLoader extensionLoaderClassLoader = ExtensionLoader.class.getClassLoader();
            if (ClassLoader.getSystemClassLoader() != extensionLoaderClassLoader) {
                urls = extensionLoaderClassLoader.getResources(fileName);
            }
        }

        if (urls == null || !urls.hasMoreElements()) {
            if (classLoader != null) {
                urls = classLoader.getResources(fileName);
            } else {
                urls = ClassLoader.getSystemResources(fileName);
            }
        }

        if (urls != null) {
            while (urls.hasMoreElements()) {
                java.net.URL resourceURL = urls.nextElement();
                loadResource(extensionClasses, classLoader, resourceURL, overridden, excludedPackages);
            }
        }
    } catch (Throwable t) {
        logger.error("Exception occurred when loading extension class (interface: " +
                type + ", description file: " + fileName + ").", t);
    }
}
```



##### loadResource

invoke `loadClass`

```java
private void loadResource(Map<String, Class<?>> extensionClasses, ClassLoader classLoader,
                          java.net.URL resourceURL, boolean overridden, String... excludedPackages) {
    try {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(resourceURL.openStream(), StandardCharsets.UTF_8))) {
            String line;
            String clazz = null;
            while ((line = reader.readLine()) != null) {
                final int ci = line.indexOf('#');
                if (ci >= 0) {
                    line = line.substring(0, ci);
                }
                line = line.trim();
                if (line.length() > 0) {
                    try {
                        String name = null;
                        int i = line.indexOf('=');
                        if (i > 0) {
                            name = line.substring(0, i).trim();
                            clazz = line.substring(i + 1).trim();
                        } else {
                            clazz = line;
                        }
                        if (StringUtils.isNotEmpty(clazz) && !isExcluded(clazz, excludedPackages)) {
                            loadClass(extensionClasses, resourceURL, Class.forName(clazz, true, classLoader), name, overridden);
                        }
                    } catch (Throwable t) {
                        IllegalStateException e = new IllegalStateException(
                                "Failed to load extension class (interface: " + type + ", class line: " + line + ") in " + resourceURL +
                                        ", cause: " + t.getMessage(), t);
                        exceptions.put(line, e);
                    }
                }
            }
        }
    } catch (Throwable t) {
        logger.error("Exception occurred when loading extension class (interface: " +
                type + ", class file: " + resourceURL + ") in " + resourceURL, t);
    }
}

private boolean isExcluded(String className, String... excludedPackages) {
    if (excludedPackages != null) {
        for (String excludePackage : excludedPackages) {
            if (className.startsWith(excludePackage + ".")) {
                return true;
            }
        }
    }
    return false;
}
```





### loadClass

if Adaptive.class, 

```java
private void loadClass(Map<String, Class<?>> extensionClasses, java.net.URL resourceURL, Class<?> clazz, String name,
                       boolean overridden) throws NoSuchMethodException {
    if (!type.isAssignableFrom(clazz)) {
        throw new IllegalStateException("Error occurred when loading extension class (interface: " +
                type + ", class line: " + clazz.getName() + "), class "
                + clazz.getName() + " is not subtype of interface.");
    }
    if (clazz.isAnnotationPresent(Adaptive.class)) {
        cacheAdaptiveClass(clazz, overridden);
      
    } else if (isWrapperClass(clazz)) {/** 	test if clazz is a wrapper class
																						which has Constructor with given 
																						class type as its only argument*/													cacheWrapperClass(clazz);
    } else {
        clazz.getConstructor();
        if (StringUtils.isEmpty(name)) {
            name = findAnnotationName(clazz);
            if (name.length() == 0) {
                throw new IllegalStateException(
                        "No such extension name for the class " + clazz.getName() + " in the config " + resourceURL);
            }
        }

        String[] names = NAME_SEPARATOR.split(name);
        if (ArrayUtils.isNotEmpty(names)) {
            cacheActivateClass(clazz, names[0]);
            for (String n : names) {
                cacheName(clazz, n);
                saveInExtensionClass(extensionClasses, clazz, n, overridden);
            }
        }
    }
}

/**
 * cache name
 */
private void cacheName(Class<?> clazz, String name) {
    if (!cachedNames.containsKey(clazz)) {
        cachedNames.put(clazz, name);
    }
}
```



#### cacheAdaptiveClass

```java
/**
 * cache Adaptive class which is annotated with <code>Adaptive</code>
 */
private void cacheAdaptiveClass(Class<?> clazz, boolean overridden) {
    if (cachedAdaptiveClass == null || overridden) {
        cachedAdaptiveClass = clazz;
    } else if (!cachedAdaptiveClass.equals(clazz)) {
        throw new IllegalStateException("More than 1 adaptive class found: "
                + cachedAdaptiveClass.getName()
                + ", " + clazz.getName());
    }
}
```

#### cacheWrapperClass

```java
/**
 * cache wrapper class
 * <p>
 * like: ProtocolFilterWrapper, ProtocolListenerWrapper
 */
private void cacheWrapperClass(Class<?> clazz) {
    if (cachedWrapperClasses == null) {
        cachedWrapperClasses = new ConcurrentHashSet<>();
    }
    cachedWrapperClasses.add(clazz);
}
```



#### cacheActivateClass

```java
/**
 * cache Activate class which is annotated with <code>Activate</code>
 * <p>
 * for compatibility, also cache class with old alibaba Activate annotation
 */
private void cacheActivateClass(Class<?> clazz, String name) {
    Activate activate = clazz.getAnnotation(Activate.class);
    if (activate != null) {
        cachedActivates.put(name, activate);
    } else {
        // support com.alibaba.dubbo.common.extension.Activate
        com.alibaba.dubbo.common.extension.Activate oldActivate =
                clazz.getAnnotation(com.alibaba.dubbo.common.extension.Activate.class);
        if (oldActivate != null) {
            cachedActivates.put(name, oldActivate);
        }
    }
}
```


#### saveInExtensionClass

```java
/**
 * put clazz in extensionClasses
 */
private void saveInExtensionClass(Map<String, Class<?>> extensionClasses, Class<?> clazz, String name, boolean overridden) {
    Class<?> c = extensionClasses.get(name);
    if (c == null || overridden) {
        extensionClasses.put(name, clazz);
    } else if (c != clazz) {
        // duplicate implementation is unacceptable
        unacceptableExceptions.add(name);
        String duplicateMsg =
                "Duplicate extension " + type.getName() + " name " + name + " on " + c.getName() + " and " + clazz.getName();
        logger.error(duplicateMsg);
        throw new IllegalStateException(duplicateMsg);
    }
}
```



### getExtension

```java
/**
 * Find the extension with the given name. If the specified name is not found, then {@link IllegalStateException}
 * will be thrown.
 */
@SuppressWarnings("unchecked")
public T getExtension(String name) {
    return getExtension(name, true);
}

public T getExtension(String name, boolean wrap) {
    if ("true".equals(name)) {
        return getDefaultExtension();
    }
    final Holder<Object> holder = getOrCreateHolder(name);
    Object instance = holder.get();
    if (instance == null) {
        synchronized (holder) {
            instance = holder.get();
            if (instance == null) {
                instance = createExtension(name, wrap);
                holder.set(instance);
            }
        }
    }
    return (T) instance;
}
```



```java
/**
 * get the original type.
 * @param name
 * @return
 */
public T getOriginalInstance(String name) {
    getExtension(name);
    Class<?> clazz = getExtensionClasses().get(name);
    return (T) EXTENSION_INSTANCES.get(clazz);
}
```



#### getDefaultExtension

1. getExtensionClasses
2. getExtension

```java
/**
 * Return default extension, return <code>null</code> if it's not configured.
 */
public T getDefaultExtension() {
    getExtensionClasses();
    if (StringUtils.isBlank(cachedDefaultName) || "true".equals(cachedDefaultName)) {
        return null;
    }
    return getExtension(cachedDefaultName);
}
```





#### createExtension

```java
@SuppressWarnings("unchecked")
private T createExtension(String name, boolean wrap) {
    Class<?> clazz = getExtensionClasses().get(name);
    if (clazz == null || unacceptableExceptions.contains(name)) {
        throw findException(name);
    }
    try {
        T instance = (T) EXTENSION_INSTANCES.get(clazz);
        if (instance == null) {
            EXTENSION_INSTANCES.putIfAbsent(clazz, clazz.getDeclaredConstructor().newInstance());
            instance = (T) EXTENSION_INSTANCES.get(clazz);
        }
        injectExtension(instance);


        if (wrap) {

            List<Class<?>> wrapperClassesList = new ArrayList<>();
            if (cachedWrapperClasses != null) {
                wrapperClassesList.addAll(cachedWrapperClasses);
                wrapperClassesList.sort(WrapperComparator.COMPARATOR);
                Collections.reverse(wrapperClassesList);
            }

            if (CollectionUtils.isNotEmpty(wrapperClassesList)) {
                for (Class<?> wrapperClass : wrapperClassesList) {
                    Wrapper wrapper = wrapperClass.getAnnotation(Wrapper.class);
                    if (wrapper == null
                            || (ArrayUtils.contains(wrapper.matches(), name) && !ArrayUtils.contains(wrapper.mismatches(), name))) {
                        instance = injectExtension((T) wrapperClass.getConstructor(type).newInstance(instance));
                    }
                }
            }
        }

        initExtension(instance);
        return instance;
    } catch (Throwable t) {
        throw new IllegalStateException("Extension instance (name: " + name + ", class: " +
                type + ") couldn't be instantiated: " + t.getMessage(), t);
    }
}
```



```java
private static ClassLoader findClassLoader() {
    return ClassUtils.getClassLoader(ExtensionLoader.class);
}

public String getExtensionName(T extensionInstance) {
    return getExtensionName(extensionInstance.getClass());
}

public String getExtensionName(Class<?> extensionClass) {
    getExtensionClasses();// load class
    return cachedNames.get(extensionClass);
}
```





### AdaptiveClassCodeGenerator

```java
/**
 * generate and return class code
 */
public String generate() {
    // no need to generate adaptive class since there's no adaptive method found.
    if (!hasAdaptiveMethod()) {
        throw new IllegalStateException("No adaptive method exist on extension " + type.getName() + ", refuse to create the adaptive class!");
    }

    StringBuilder code = new StringBuilder();
    code.append(generatePackageInfo());
    code.append(generateImports());
    code.append(generateClassDeclaration());

    Method[] methods = type.getMethods();
    for (Method method : methods) {
        code.append(generateMethod(method));
    }
    code.append("}");

    if (logger.isDebugEnabled()) {
        logger.debug(code.toString());
    }
    return code.toString();
}
```



## Summary



|        | JDK SPI         | Dubbo SPI |
| ------ | --------------- | --------- |
| load   | must load all   |           |
| Source | only one source |           |
|        |                 |           |

 

