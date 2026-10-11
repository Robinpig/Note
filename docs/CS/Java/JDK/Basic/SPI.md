## Introduction

Java 6 introduced a feature for discovering and loading implementations matching a given interface: **Service Provider Interface** (SPI).
An *extensible* application can be extended without modifying its original code base — new plug-ins or modules add functionality by dropping a JAR onto the class path or into an extension directory.

SPI 的本质是将接口实现类的全限定名配置在文件中，并由服务加载器读取配置文件、加载实现类，从而在运行时动态为接口替换实现。核心原理可总结为：**基于接口的编程 + 策略模式 + 配置文件 + 反射机制**。

## Terminology

- **Service** — a set of programming interfaces and classes providing access to a specific feature. It defines the interfaces for the functionality and a way to retrieve an implementation, but does not implement it.
- **Service Provider Interface (SPI)** — the set of public interfaces and abstract classes that a service defines.
- **Service Provider** — a class that implements the SPI. Extensible applications let vendors and customers add providers without modifying the original code.

## Mechanism

The `java.util.ServiceLoader` class finds, loads, and uses service providers. It is `final` — you cannot subclass it or override its loading algorithm.

```java
public final class ServiceLoader<S> implements Iterable<S> {
    private static final String PREFIX = "META-INF/services/";

    // The class or interface representing the service being loaded
    private final Class<S> service;

    // The class loader used to locate, load, and instantiate providers
    private final ClassLoader loader;

    // The access control context taken when the ServiceLoader is created
    private final AccessControlContext acc;

    // Cached providers, in instantiation order
    private LinkedHashMap<String,S> providers = new LinkedHashMap<>();
}
```

### load

`load` creates a loader using the current thread's context class loader. Note it only *initializes* the `ServiceLoader` — no provider class is loaded yet.

```java
@CallerSensitive
public static <S> ServiceLoader<S> load(Class<S> service) {
    ClassLoader cl = Thread.currentThread().getContextClassLoader();
    return new ServiceLoader<>(Reflection.getCallerClass(), service, cl);
}
```

The constructor defers to the system class loader when none is set, and enforces a boot-time restriction: before the VM has booted, only code in `java.base` may use `ServiceLoader`.

```java
private ServiceLoader(Class<?> caller, Class<S> svc, ClassLoader cl) {
    Objects.requireNonNull(svc);
    if (VM.isBooted()) {
        checkCaller(caller, svc);
        if (cl == null) cl = ClassLoader.getSystemClassLoader();
    } else {
        // only code in java.base may use ServiceLoader during VM init
        Module callerModule = caller.getModule();
        Module base = Object.class.getModule();
        Module svcModule = svc.getModule();
        if (callerModule != base || svcModule != base)
            fail(svc, "not accessible to " + callerModule + " during VM init");
        cl = null;
    }
    this.service = svc;
    this.serviceName = svc.getName();
    this.layer = null;
    this.loader = cl;
    this.acc = (System.getSecurityManager() != null)
            ? AccessController.getContext() : null;
}
```

### Lazy Loading

Providers are located and instantiated **on demand**. A service loader maintains a cache of loaded providers; each `iterator()` first yields the cached ones in instantiation order, then lazily locates and instantiates new ones.

The classpath lookup iterator skips classes in **named modules** (they are resolved through the module system instead):

```java
private boolean hasNextService() {
    while (nextProvider == null && nextError == null) {
        try {
            Class<?> clazz = nextProviderClass();
            if (clazz == null) return false;
            if (clazz.getModule().isNamed()) {
                continue; // ignore class if in named module
            }
            if (service.isAssignableFrom(clazz)) {
                Class<? extends S> type = (Class<? extends S>) clazz;
                Constructor<? extends S> ctor = getConstructor(clazz);
                nextProvider = new ProviderImpl<>(service, type, ctor, acc);
            } else {
                fail(service, clazz.getName() + " not a subtype");
            }
        } catch (ServiceConfigurationError e) {
            nextError = e;
        }
    }
    return true;
}
```

For module layers, a separate iterator walks the `ModuleLayer` stack depth-first:

```java
private final class LayerLookupIterator<T> implements Iterator<Provider<T>> {
    Deque<ModuleLayer> stack = new ArrayDeque<>();
    Set<ModuleLayer> visited = new HashSet<>();
    Iterator<ServiceProvider> iterator;
    LayerLookupIterator() { visited.add(layer); stack.push(layer); }
}
```

`next()` instantiates the provider through its public no-args constructor (or a `public static` factory method named `provider()` if present):

```java
private Provider<T> nextService() {
    if (!hasNextService()) throw new NoSuchElementException();
    Provider<T> provider = nextProvider;
    if (provider != null) { nextProvider = null; return provider; }
    throw nextError; // deferred ServiceConfigurationError
}
```

A `Provider<S>` wraps the class and defers instantiation, exposing `get()` and `type()`:

```java
private static class ProviderImpl<S> implements Provider<S> {
    final Class<S> service;
    final Class<? extends S> type;
    final Method factoryMethod;  // factory method or null
    final Constructor<? extends S> ctor; // public no-args constructor or null
}
```

## Configuration File

A provider is declared by a file named after the fully-qualified service interface, located at `META-INF/services/`:

```
META-INF/services/dictionary.spi.Dictionary
```

The file is UTF-8, one fully-qualified implementation class name per line. Whitespace and lines beginning with `#` are ignored. The class must be public, have a public no-args constructor, and be assignable to the service type.

```
# default English dictionary
dictionary.GeneralDictionary
dictionary.ExtendedDictionary
```

## Module System Integration

Under JPMS, classpath-based `META-INF/services` still works, but modules should declare providers in the **module descriptor** instead, which the `LayerLookupIterator` then resolves:

```java
// module-info.java
module com.example.app {
    uses dictionary.spi.Dictionary;                 // the SPI the module consumes
}
module com.example.dict {
    provides dictionary.spi.Dictionary             // the SPI implemented
        with com.example.dict.ExtendedDictionary;  // concrete provider
}
```

`ServiceLoader.load(ModuleLayer)` (or `load(Layer, Class)`) scopes discovery to a layer, enabling isolation in container/plugin architectures. A provider in a named module is **not** found via the classpath scanner — only through `provides ... with`.

## Lazy Loading and Errors

- **Laziness**: nothing is loaded until `iterator().hasNext()`/`next()` is called, and each provider is instantiated at most once and cached.
- **`ServiceConfigurationError`**: thrown when a provider class cannot be found, is not assignable, lacks a public no-args constructor, or throws during instantiation. The error is *deferred* — it surfaces on the `next()` call that would return that provider, so it does not abort iteration over other providers.
- **No caching of failures**: a provider that errors on first access can be retried on a later `next()` without being permanently blacklisted within the same loader.

## Usage Example

```java
// service interface
package dictionary.spi;
public interface Dictionary { String getDefinition(String word); }

// retrieve all providers
ServiceLoader<Dictionary> loader = ServiceLoader.load(Dictionary.class);
for (Dictionary d : loader) {
    String def = d.getDefinition("book");
    if (def != null) { /* use first match */ break; }
}
```

The standard library itself uses SPI heavily: `java.sql.Driver` (JDBC), `java.nio.charset.spi.CharsetProvider`, `java.text.spi`, and `java.util.spi` are all SPI-based.

## Third-party SPI

- **Dubbo** extends the idea with `@SPI` (extensible interface), `@Adaptive` (generated adaptive proxy), and `@Activate` (conditional activation). See [Dubbo SPI](/docs/CS/Framework/Dubbo/SPI.md).
- **Spring** historically used `META-INF/spring.factories` (`SpringFactoriesLoader`); since 2.7 it migrates to `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` for auto-configuration.
- **Netty / MyBatis / Hadoop** likewise publish providers via `META-INF/services`.

## Limitations

1. Eagerly loading all implementations (`for` over the iterator) instantiates every provider, which can be costly or have side effects.
2. Provider ordering across JARs is **not guaranteed**.
3. A malformed provider triggers `ServiceConfigurationError` rather than a clean typed exception.
4. The built-in `ServiceLoader` is not designed for highly concurrent reconfiguration; modification during iteration throws `ConcurrentModificationException` (detected via a `reloadCount`).
5. It requires a public no-args constructor (or a `provider()` factory), limiting dependency-injected providers — frameworks add their own DI-aware loaders on top.

## Links

- [Java basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Module system](/docs/CS/Java/JDK/Basic/module.md)
- [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)
- [Dubbo SPI](/docs/CS/Framework/Dubbo/SPI.md)

## References

1. [ServiceLoader (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ServiceLoader.html)
2. [JLS 7.7.4 (Service Loading)](https://docs.oracle.com/javase/specs/jls/se25/html/jls-7.html#jls-7.7.4)
3. [JPMS: The `uses` and `provides` directives](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/ModuleLayer.html)
