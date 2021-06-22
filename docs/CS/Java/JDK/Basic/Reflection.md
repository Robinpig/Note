# Reflection



## Introduction

Instances of the class Class represent classes and interfaces in a running Java application. An enum is a kind of class and an annotation is a kind of interface. Every array also belongs to a class that is reflected as a Class object that is shared by all arrays with the same element type and number of dimensions. The primitive Java types (boolean, byte, char, short, int, long, float, and double), and the keyword void are also represented as Class objects.
Class has no public constructor. Instead Class objects are constructed automatically by the Java Virtual Machine as classes are loaded and by calls to the defineClass method in the class loader.

- Class
- Constructor
- Field
- Method



Get Class Object

1. ClassName.class
2. Class.forName()
3. Instance.getClass()
4. ClassLoader.loadClass()



1. `getName()` Returns the name of the entity (class, interface, array class, primitive type, or void) represented by this Class object, as a String.
2. `getSimpleName()` Returns the simple name of the underlying class as given in the source code. Returns an empty string if the underlying class is anonymous.
3. `getCanonicalName()` Returns the canonical name of the underlying class as defined by the Java Language Specification. Returns null if the underlying class does not have a canonical name (i.e., if it is a local or anonymous class or an array whose component type does not have a canonical name).


| Class           | getName             | getSimpleName | getCanonicalName    |
| --------------- | ------------------- | ------------- | ------------------- |
| int.class       | int                 | int           | int                 |
| int[].class     | [I                  | int[]         | int[]               |
| int[][].class   | [[I                 | int[][]       | int[][]             |
| String.class    | java.lang.String    | String        | java.lang.String    |
| String[].class  | [Ljava.lang.String; | String[]      | java.lang.String[]  |
| ArrayList.class | java.util.ArrayList | ArrayList     | java.util.ArrayList |



性能消耗 benchmark





## Proxy

Proxy InnvocationHandler

MethodInterceptor Enhancer



newProxyInstance

```java
/**
 * Returns an instance of a proxy class for the specified interfaces
 * that dispatches method invocations to the specified invocation
 * handler.
 *
 * <p>{@code Proxy.newProxyInstance} throws
 * {@code IllegalArgumentException} for the same reasons that
 * {@code Proxy.getProxyClass} does.
 *
 * @param   loader the class loader to define the proxy class
 * @param   interfaces the list of interfaces for the proxy class
 *          to implement
 * @param   h the invocation handler to dispatch method invocations to
 * @return  a proxy instance with the specified invocation handler of a
 *          proxy class that is defined by the specified class loader
 *          and that implements the specified interfaces
 * @throws  IllegalArgumentException if any of the restrictions on the
 *          parameters that may be passed to {@code getProxyClass}
 *          are violated
 * @throws  SecurityException if a security manager, <em>s</em>, is present
 *          and any of the following conditions is met:
 *          <ul>
 *          <li> the given {@code loader} is {@code null} and
 *               the caller's class loader is not {@code null} and the
 *               invocation of {@link SecurityManager#checkPermission
 *               s.checkPermission} with
 *               {@code RuntimePermission("getClassLoader")} permission
 *               denies access;</li>
 *          <li> for each proxy interface, {@code intf},
 *               the caller's class loader is not the same as or an
 *               ancestor of the class loader for {@code intf} and
 *               invocation of {@link SecurityManager#checkPackageAccess
 *               s.checkPackageAccess()} denies access to {@code intf};</li>
 *          <li> any of the given proxy interfaces is non-public and the
 *               caller class is not in the same {@linkplain Package runtime package}
 *               as the non-public interface and the invocation of
 *               {@link SecurityManager#checkPermission s.checkPermission} with
 *               {@code ReflectPermission("newProxyInPackage.{package name}")}
 *               permission denies access.</li>
 *          </ul>
 * @throws  NullPointerException if the {@code interfaces} array
 *          argument or any of its elements are {@code null}, or
 *          if the invocation handler, {@code h}, is
 *          {@code null}
 */
@CallerSensitive
public static Object newProxyInstance(ClassLoader loader,
                                      Class<?>[] interfaces,
                                      InvocationHandler h)
    throws IllegalArgumentException
{
    Objects.requireNonNull(h);

    final Class<?>[] intfs = interfaces.clone();
    final SecurityManager sm = System.getSecurityManager();
    if (sm != null) {
        checkProxyAccess(Reflection.getCallerClass(), loader, intfs);
    }

    /*
     * Look up or generate the designated proxy class.
     */
    Class<?> cl = getProxyClass0(loader, intfs);

    /*
     * Invoke its constructor with the designated invocation handler.
     */
    try {
        if (sm != null) {
            checkNewProxyPermission(Reflection.getCallerClass(), cl);
        }

        final Constructor<?> cons = cl.getConstructor(constructorParams);
        final InvocationHandler ih = h;
        if (!Modifier.isPublic(cl.getModifiers())) {
            AccessController.doPrivileged(new PrivilegedAction<Void>() {
                public Void run() {
                    cons.setAccessible(true);
                    return null;
                }
            });
        }
        return cons.newInstance(new Object[]{h});
    } catch (IllegalAccessException|InstantiationException e) {
        throw new InternalError(e.toString(), e);
    } catch (InvocationTargetException e) {
        Throwable t = e.getCause();
        if (t instanceof RuntimeException) {
            throw (RuntimeException) t;
        } else {
            throw new InternalError(t.toString(), t);
        }
    } catch (NoSuchMethodException e) {
        throw new InternalError(e.toString(), e);
    }
}
```



```java
/**
 * Generate a proxy class.  Must call the checkProxyAccess method
 * to perform permission checks before calling this.
 */
private static Class<?> getProxyClass0(ClassLoader loader,
                                       Class<?>... interfaces) {
    if (interfaces.length > 65535) {
        throw new IllegalArgumentException("interface limit exceeded");
    }

    // If the proxy class defined by the given loader implementing
    // the given interfaces exists, this will simply return the cached copy;
    // otherwise, it will create the proxy class via the ProxyClassFactory
    return proxyClassCache.get(loader, interfaces);
}
```



```java
/**
 * Look-up the value through the cache. This always evaluates the
 * {@code subKeyFactory} function and optionally evaluates
 * {@code valueFactory} function if there is no entry in the cache for given
 * pair of (key, subKey) or the entry has already been cleared.
 *
 * @param key       possibly null key
 * @param parameter parameter used together with key to create sub-key and
 *                  value (should not be null)
 * @return the cached value (never null)
 * @throws NullPointerException if {@code parameter} passed in or
 *                              {@code sub-key} calculated by
 *                              {@code subKeyFactory} or {@code value}
 *                              calculated by {@code valueFactory} is null.
 */
public V get(K key, P parameter) {
    Objects.requireNonNull(parameter);

    expungeStaleEntries();

    Object cacheKey = CacheKey.valueOf(key, refQueue);

    // lazily install the 2nd level valuesMap for the particular cacheKey
    ConcurrentMap<Object, Supplier<V>> valuesMap = map.get(cacheKey);
    if (valuesMap == null) {
        ConcurrentMap<Object, Supplier<V>> oldValuesMap
            = map.putIfAbsent(cacheKey,
                              valuesMap = new ConcurrentHashMap<>());
        if (oldValuesMap != null) {
            valuesMap = oldValuesMap;
        }
    }

    // create subKey and retrieve the possible Supplier<V> stored by that
    // subKey from valuesMap
    Object subKey = Objects.requireNonNull(subKeyFactory.apply(key, parameter));
    Supplier<V> supplier = valuesMap.get(subKey);
    Factory factory = null;

    while (true) {
        if (supplier != null) {
            // supplier might be a Factory or a CacheValue<V> instance
            V value = supplier.get();
            if (value != null) {
                return value;
            }
        }
        // else no supplier in cache
        // or a supplier that returned null (could be a cleared CacheValue
        // or a Factory that wasn't successful in installing the CacheValue)

        // lazily construct a Factory
        if (factory == null) {
            factory = new Factory(key, parameter, subKey, valuesMap);
        }

        if (supplier == null) {
            supplier = valuesMap.putIfAbsent(subKey, factory);
            if (supplier == null) {
                // successfully installed Factory
                supplier = factory;
            }
            // else retry with winning supplier
        } else {
            if (valuesMap.replace(subKey, supplier, factory)) {
                // successfully replaced
                // cleared CacheEntry / unsuccessful Factory
                // with our Factory
                supplier = factory;
            } else {
                // retry with current supplier
                supplier = valuesMap.get(subKey);
            }
        }
    }
}
```



```java
@Override
public Class<?> apply(ClassLoader loader, Class<?>[] interfaces) {

    Map<Class<?>, Boolean> interfaceSet = new IdentityHashMap<>(interfaces.length);
    for (Class<?> intf : interfaces) {
        /*
         * Verify that the class loader resolves the name of this
         * interface to the same Class object.
         */
        Class<?> interfaceClass = null;
        try {
            interfaceClass = Class.forName(intf.getName(), false, loader);
        } catch (ClassNotFoundException e) {
        }
        if (interfaceClass != intf) {
            throw new IllegalArgumentException(
                intf + " is not visible from class loader");
        }
        /*
         * Verify that the Class object actually represents an
         * interface.
         */
        if (!interfaceClass.isInterface()) {
            throw new IllegalArgumentException(
                interfaceClass.getName() + " is not an interface");
        }
        /*
         * Verify that this interface is not a duplicate.
         */
        if (interfaceSet.put(interfaceClass, Boolean.TRUE) != null) {
            throw new IllegalArgumentException(
                "repeated interface: " + interfaceClass.getName());
        }
    }

    String proxyPkg = null;     // package to define proxy class in
    int accessFlags = Modifier.PUBLIC | Modifier.FINAL;

    /*
     * Record the package of a non-public proxy interface so that the
     * proxy class will be defined in the same package.  Verify that
     * all non-public proxy interfaces are in the same package.
     */
    for (Class<?> intf : interfaces) {
        int flags = intf.getModifiers();
        if (!Modifier.isPublic(flags)) {
            accessFlags = Modifier.FINAL;
            String name = intf.getName();
            int n = name.lastIndexOf('.');
            String pkg = ((n == -1) ? "" : name.substring(0, n + 1));
            if (proxyPkg == null) {
                proxyPkg = pkg;
            } else if (!pkg.equals(proxyPkg)) {
                throw new IllegalArgumentException(
                    "non-public interfaces from different packages");
            }
        }
    }

    if (proxyPkg == null) {
        // if no non-public proxy interfaces, use com.sun.proxy package
        proxyPkg = ReflectUtil.PROXY_PACKAGE + ".";
    }

    /*
     * Choose a name for the proxy class to generate.
     */
    long num = nextUniqueNumber.getAndIncrement();
    String proxyName = proxyPkg + proxyClassNamePrefix + num;

    /*
     * Generate the specified proxy class.
     */
    byte[] proxyClassFile = ProxyGenerator.generateProxyClass(
        proxyName, interfaces, accessFlags);
    try {
        return defineClass0(loader, proxyName,
                            proxyClassFile, 0, proxyClassFile.length);
    } catch (ClassFormatError e) {
        /*
         * A ClassFormatError here means that (barring bugs in the
         * proxy class generation code) there was some other
         * invalid aspect of the arguments supplied to the proxy
         * class creation (such as virtual machine limitations
         * exceeded).
         */
        throw new IllegalArgumentException(e.toString());
    }
}
```