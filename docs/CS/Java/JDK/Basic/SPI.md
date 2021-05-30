# SPI



## Introduction

Java 6 has introduced a feature for discovering and loading implementations matching a given interface: **Service Provider Interface** (SPI).

An *extensible* application is one that you can extend without modifying its original code base. You can enhance its functionality with new plug-ins or modules. Developers, software vendors, and customers can add new functionality or application programming interfaces (APIs) by adding a new Java Archive (JAR) file onto the application class path or into an application-specific extension directory.

The following are terms and definitions important to understand extensible applications:

- Service

  A set of programming interfaces and classes that provide access to some specific application functionality or feature. The service can define the interfaces for the functionality and a way to retrieve an implementation. In the word-processor example, a dictionary service can define a way to retrieve a dictionary and the definition of a word, but it does not implement the underlying feature set. Instead, it relies on a *service provider* to implement that functionality.

- Service provider interface (SPI)

  The set of public interfaces and abstract classes that a service defines. The SPI defines the classes and methods available to your application.

- Service Provider

  Implements the SPI. An application with extensible services enable you, vendors, and customers to add service providers without modifying the original application.



## ServiceLoader

The `java.util.ServiceLoader` class helps you find, load, and use service providers. It searches for service providers on your application's class path or in your runtime environment's extensions directory. **It loads them and enables your application to use the provider's APIs.** If you add new providers to the class path or runtime extension directory, the `ServiceLoader` class finds them. If your application knows the provider interface, it can find and use different implementations of that interface. **You can use the first loadable instance of the interface or iterate through all the available interfaces**.

The `ServiceLoader` class is final, which means that you cannot make it a subclass or override its loading algorithms. **You cannot, for example, change its algorithm to search for services from a different location**.

```java
public final class ServiceLoader<S>
    implements Iterable<S>
{

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
...
}
```



From the perspective of the `ServiceLoader` class, all services have a single type, which is usually a single interface or abstract class. The provider itself contains one or more concrete classes that extend the service type with an implementation specific to its purpose. The `ServiceLoader` class requires that the single exposed provider type has a default constructor, which requires no arguments. This enables the `ServiceLoader` class to easily instantiate the service providers that it finds.

Providers are located and instantiated on demand. A service loader maintains a cache of the providers that were loaded. Each invocation of the loader's `iterator` method returns an iterator that first yields all of the elements of the cache, in instantiation order. The service loader then locates and instantiates any new providers, adding each one to the cache in turn. You can clear the provider cache with the `reload` method.

To create a loader for a specific class, provide the class itself to the `load` or `loadInstalled` method. You can use default class loaders or provide your own `ClassLoader` subclass.

The `loadInstalled` method searches the runtime environment's extension directory of installed runtime providers. The default extension location is your runtime environment's `jre/lib/ext` directory. You should use the extension location only for well-known, trusted providers because this location becomes part of the class path for all applications. In this article, providers do not use the extension directory but will instead depend on an application-specific class path.



## Code



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

