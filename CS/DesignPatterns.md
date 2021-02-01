# Design Patterns



https://www.oodesign.com



## Design Principles



### Open Close Principle

#### Intent

Software entities like classes, modules and functions should be **open for extension** but **closed for modifications**.





### Dependency Inversion Principle

#### Intent

- High-level modules should not depend on low-level modules. Both should depend on abstractions.
- Abstractions should not depend on details. Details should depend on abstractions.

using interface as a abstract layer, and Factory Method, Abstract Factory, Prototype





### Single Responsibility Principle

##### Intent

A class should have only one reason to change.







### Liskov's Substitution Principle

#### Intent

Derived types must be completely substitutable for their base types.



This principle is just an extension of the Open Close Principle and it means that we must make sure that new derived classes are extending the base classes without changing their behavior.



### Interface Segregation Principle

#### Intent

Clients should not be forced to depend upon interfaces that they don't use.



If the design is already done fat interfaces can be segregated using the Adapter pattern.



## Creational Patterns



### Singleton

#### Intent

- Ensure that only one instance of a class is created.
- Provide a global point of access to the object.



- Protected constructor

- **Multithreading** - A special care should be taken when singleton has to be used in a multithreading application.
- **Serialization** - When Singletons are implementing Serializable interface they have to implement readResolve method in order to avoid having 2 different objects.
- **Classloaders** - If the Singleton class is loaded by 2 different class loaders we'll have 2 different classes, one for each class loader.
- **Global Access Point represented by the class name** - The singleton instance is obtained using the class name. At the first view this is an easy way to access it, but it is not very flexible. If we need to replace the Sigleton class, all the references in the code should be changed accordinglly.


#### Example



```java
public class Singleton {
    public static final Singleton INSTANCE = new Singleton();
    private Singleton() { ... }
    public static Singleton getInstance(){
      return INSTANCE;
    }
}
```



Double Check Lock

```java
public class Singleton {
    private volatile static Singleton instance;
    private Singleton() { ... }
    public static Singleton getInstance() {
        if (instance == null) {
            synchronized (Singleton.class) {
                if (instance == null)
                    instance = new Singleton();
            }
        }
        return instance;
    }
}
```



```java
// Enum singleton - the preferred approach
public enum Singleton { 
    INSTANCE;
}
```





### Prototype



### Factory



### Factory Method



### Abstract Factory



### Builder

step by step to build a object

⼀一些基本物料料不不会变，⽽而其组合经常变化的时候



### Object Pool




## Behavioral Patterns



### Memento



### Mediator



### Observer



### Null Object



### Visitor



### Interpreter



### Iterator



### Strategy



### Command



### Template Method





### Chain of Responsibility



## Structural Patterns


### Adapter 



### Proxy



### Composite



### Decorator



### Flyweight



### Bridge





