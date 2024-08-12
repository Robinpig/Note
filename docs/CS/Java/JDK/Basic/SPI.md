## Introduction

Java 6 has introduced a feature for discovering and loading implementations matching a given interface: **Service Provider Interface** (SPI).

An *extensible* application is one that you can extend without modifying its original code base.
You can enhance its functionality with new plug-ins or modules. Developers, software vendors, and customers can add new functionality or application programming interfaces (APIs) by adding a new Java Archive (JAR) file onto the application class path or into an application-specific extension directory.

SPI 的本质是将接口实现类的全限定名配置在文件中，并由服务加载器读取配置文件，加载实现类。这样可以在运行时，动态为接口替换实现类。
正因此特性，我们可以很容易的通过 SPI 机制为我们的程序提供拓展功能。
SPI的核心原理可以总结为：基于接口的编程 + 策略模式 + 配置文件 + 反射机制

The following are terms and definitions important to understand extensible applications:

- Service
  A set of programming interfaces and classes that provide access to some specific application functionality or feature. 
  The service can define the interfaces for the functionality and a way to retrieve an implementation. 
  In the word-processor example, a dictionary service can define a way to retrieve a dictionary and the definition of a word, but it does not implement the underlying feature set. 
  Instead, it relies on a *service provider* to implement that functionality.
- Service provider interface (SPI)
  The set of public interfaces and abstract classes that a service defines. The SPI defines the classes and methods available to your application.
- Service Provider
  Implements the SPI. An application with extensible services enable you, vendors, and customers to add service providers without modifying the original application.



## ServiceLoader

The `java.util.ServiceLoader` class helps you find, load, and use service providers. 
It searches for service providers on your application's class path or in your runtime environment's extensions directory.
It loads them and enables your application to use the provider's APIs.
If you add new providers to the class path or runtime extension directory, the `ServiceLoader` class finds them. 
If your application knows the provider interface, it can find and use different implementations of that interface. 
**You can use the first loadable instance of the interface or iterate through all the available interfaces**.

The `ServiceLoader` class is final, which means that you cannot make it a subclass or override its loading algorithms. 
**You cannot, for example, change its algorithm to search for services from a different location**.

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

    // The current lazy-lookup iterator
    private LazyIterator lookupIterator;
}
```



From the perspective of the `ServiceLoader` class, all services have a single type, which is usually a single interface or abstract class. 
The provider itself contains one or more concrete classes that extend the service type with an implementation specific to its purpose.
The `ServiceLoader` class requires that the single exposed provider type has a default constructor, which requires no arguments. 
This enables the `ServiceLoader` class to easily instantiate the service providers that it finds.

Providers are located and instantiated on demand. 
A service loader maintains a cache of the providers that were loaded. 
Each invocation of the loader's `iterator` method returns an iterator that first yields all of the elements of the cache, in instantiation order. 
The service loader then locates and instantiates any new providers, adding each one to the cache in turn. 
You can clear the provider cache with the `reload` method.

To create a loader for a specific class, provide the class itself to the `load` or `loadInstalled` method. 
You can use default class loaders or provide your own `ClassLoader` subclass.

The `loadInstalled` method searches the runtime environment's extension directory of installed runtime providers. 
The default extension location is your runtime environment's `jre/lib/ext` directory. 
You should use the extension location only for well-known, trusted providers because this location becomes part of the class path for all applications. 



对`ServiceLoader`源码的分析，有下面几个重要结论：

1. `ServiceLoader`在获取实现类的过程，可以分为初始化、解析、加载和实例化四步。
2. `ServiceLoader`的初始化：通过`ServiceLoader.load`实现。注意这里并没有加载实现类，只是初始化了`ServiceLoader`，方法名字容易让人误解。
3. 实现类的解析：是在调用`iterator.hasNext()`方法时完成的。
4. 实现类的加载和实例化：是在调用`iterator.next()`完成的。

### load
Creates a new service loader for the given service type, using the current thread's context class loader.

```java
@CallerSensitive
public static <S> ServiceLoader<S> load(Class<S> service) {
    ClassLoader cl = Thread.currentThread().getContextClassLoader();
    return new ServiceLoader<>(Reflection.getCallerClass(), service, cl);
}
```


获取SystemClassLoader 
```java
private ServiceLoader(Class<?> caller, Class<S> svc, ClassLoader cl) {
    Objects.requireNonNull(svc);

    if (VM.isBooted()) {
        checkCaller(caller, svc);
        if (cl == null) {
            cl = ClassLoader.getSystemClassLoader();
        }
    } else {

        // if we get here then it means that ServiceLoader is being used
        // before the VM initialization has completed. At this point then
        // only code in the java.base should be executing.
        Module callerModule = caller.getModule();
        Module base = Object.class.getModule();
        Module svcModule = svc.getModule();
        if (callerModule != base || svcModule != base) {
            fail(svc, "not accessible to " + callerModule + " during VM init");
        }

        // restricted to boot loader during startup
        cl = null;
    }

    this.service = svc;
    this.serviceName = svc.getName();
    this.layer = null;
    this.loader = cl;
    this.acc = (System.getSecurityManager() != null)
            ? AccessController.getContext()
            : null;
}
```

### LayerLookupIterator

iterator



```java
public Iterator<S> iterator() {

    // create lookup iterator if needed
    if (lookupIterator1 == null) {
        lookupIterator1 = newLookupIterator();
    }

    return new Iterator<S>() {

        // record reload count
        final int expectedReloadCount = ServiceLoader.this.reloadCount;

        // index into the cached providers list
        int index;

        /**
         * Throws ConcurrentModificationException if the list of cached
         * providers has been cleared by reload.
         */
        private void checkReloadCount() {
            if (ServiceLoader.this.reloadCount != expectedReloadCount)
                throw new ConcurrentModificationException();
        }

        @Override
        public boolean hasNext() {
            checkReloadCount();
            if (index < instantiatedProviders.size())
                return true;
            return lookupIterator1.hasNext();
        }

        @Override
        public S next() {
            checkReloadCount();
            S next;
            if (index < instantiatedProviders.size()) {
                next = instantiatedProviders.get(index);
            } else {
                next = lookupIterator1.next().get();
                instantiatedProviders.add(next);
            }
            index++;
            return next;
        }

    };
}
```



```java
private static class ProviderImpl<S> implements Provider<S> {
    final Class<S> service;
    final Class<? extends S> type;
    final Method factoryMethod;  // factory method or null
    final Constructor<? extends S> ctor; // public no-args constructor or null
    @SuppressWarnings("removal")
    final AccessControlContext acc;

    ProviderImpl(Class<S> service,
                 Class<? extends S> type,
                 Method factoryMethod,
                 @SuppressWarnings("removal") AccessControlContext acc) {
        this.service = service;
        this.type = type;
        this.factoryMethod = factoryMethod;
        this.ctor = null;
        this.acc = acc;
    }
}
```



```java
private final class LayerLookupIterator<T>
    implements Iterator<Provider<T>>
{
    Deque<ModuleLayer> stack = new ArrayDeque<>();
    Set<ModuleLayer> visited = new HashSet<>();
    Iterator<ServiceProvider> iterator;

    Provider<T> nextProvider;
    ServiceConfigurationError nextError;

    LayerLookupIterator() {
        visited.add(layer);
        stack.push(layer);
    }
}
```

### hasNext

在hasNextService里做解析文件处理

```java
    private final class LazyClassPathLookupIterator<T>
        implements Iterator<Provider<T>>
    {
@SuppressWarnings("removal")
        @Override
        public boolean hasNext() {
            if (acc == null) {
                return hasNextService();
            } else {
                PrivilegedAction<Boolean> action = new PrivilegedAction<>() {
                    public Boolean run() { return hasNextService(); }
                };
                return AccessController.doPrivileged(action, acc);
            }
        }

private boolean hasNextService() {
    while (nextProvider == null && nextError == null) {
        try {
            Class<?> clazz = nextProviderClass();
            if (clazz == null)
                return false;

            if (clazz.getModule().isNamed()) {
                // ignore class if in named module
                continue;
            }

            if (service.isAssignableFrom(clazz)) {
                Class<? extends S> type = (Class<? extends S>) clazz;
                Constructor<? extends S> ctor
                    = (Constructor<? extends S>)getConstructor(clazz);
                ProviderImpl<S> p = new ProviderImpl<S>(service, type, ctor, acc);
                nextProvider = (ProviderImpl<T>) p;
            } else {
                fail(service, clazz.getName() + " not a subtype");
            }
        } catch (ServiceConfigurationError e) {
            nextError = e;
        }
    }
    return true;
}
    }
```

### next





```java
private Provider<T> nextService() {
    if (!hasNextService())
        throw new NoSuchElementException();

    Provider<T> provider = nextProvider;
    if (provider != null) {
        nextProvider = null;
        return provider;
    } else {
        ServiceConfigurationError e = nextError;
        assert e != null;
        nextError = null;
        throw e;
    }
}
```





## Implementation

- [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)
- Log
- Spring
- [Dubbo](/docs/CS/Framework/Dubbo/SPI.md)
- Netty
- MyBatis
- Hadoop

## Sample



### Define the Service Provider Interface

```java
package dictionary.spi;

public interface Dictionary {
    public String getDefinition(String word);
}
```



### Define the Service That Retrieves the Service Provider Implementations

```java
package dictionary;

import dictionary.spi.Dictionary;
import java.util.Iterator;
import java.util.ServiceConfigurationError;
import java.util.ServiceLoader;

public class DictionaryService {

    private static DictionaryService service;
    private ServiceLoader<Dictionary> loader;

  /**
   * load class by java.util.ServiceLoader
   */
    private DictionaryService() {
        loader = ServiceLoader.load(Dictionary.class);
    }

    public static synchronized DictionaryService getInstance() {
        if (service == null) {
            service = new DictionaryService();
        }
        return service;
    }


    public String getDefinition(String word) {
        String definition = null;

        try {
            Iterator<Dictionary> dictionaries = loader.iterator();
            while (definition == null && dictionaries.hasNext()) {
                Dictionary d = dictionaries.next();
                definition = d.getDefinition(word);
            }
        } catch (ServiceConfigurationError serviceError) {
            definition = null;
            serviceError.printStackTrace();

        }
        return definition;
    }
}
```



### Implement the Service Provider

```java
package dictionary;

import dictionary.spi.Dictionary;
import java.util.SortedMap;
import java.util.TreeMap;

public class GeneralDictionary implements Dictionary {

    private SortedMap<String, String> map;
    
    public GeneralDictionary() {
        map = new TreeMap<String, String>();
        map.put(
            "book",
            "a set of written or printed pages, usually bound with " +
                "a protective cover");
        map.put(
            "editor",
            "a person who edits");
    }

    @Override
    public String getDefinition(String word) {
        return map.get(word);
    }

}
```



```java
package dictionary;

import dictionary.spi.Dictionary;
import java.util.SortedMap;
import java.util.TreeMap;

public class ExtendedDictionary implements Dictionary {

        private SortedMap<String, String> map;

    public ExtendedDictionary() {
        map = new TreeMap<String, String>();
        map.put(
            "xml",
            "a document standard often used in web services, among other " +
                "things");
        map.put(
            "REST",
            "an architecture style for creating, reading, updating, " +
                "and deleting data that attempts to use the common " +
                "vocabulary of the HTTP protocol; Representational State " +
                "Transfer");
    }

    @Override
    public String getDefinition(String word) {
        return map.get(word);
    }

}
```



### Create a Client That Uses the Service and Service Providers

```java
package dictionary;

import dictionary.DictionaryService;

public class DictionaryDemo {

  public static void main(String[] args) {

    DictionaryService dictionary = DictionaryService.getInstance();
    System.out.println(DictionaryDemo.lookup(dictionary, "book"));
    System.out.println(DictionaryDemo.lookup(dictionary, "editor"));
    System.out.println(DictionaryDemo.lookup(dictionary, "xml"));
    System.out.println(DictionaryDemo.lookup(dictionary, "REST"));
  }

  public static String lookup(DictionaryService dictionary, String word) {
    String outputString = word + ": ";
    String definition = dictionary.getDefinition(word);
    if (definition == null) {
      return outputString + "Cannot find definition for this word.";
    } else {
      return outputString + definition;
    }
  }
}
```



## Summary



1. Load all implemetions
2. Less extensions
3. exception not quite evidently
4. not supported concurrency



## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)