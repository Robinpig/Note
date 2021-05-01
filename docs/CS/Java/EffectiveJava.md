# Effective Java 



## Chapter 2: Creating and Destroying Objects 

### Item 1: Consider static factory methods instead of constructors

usually use valueOf method to create objects rather than constructors

- Advantages:  
  - unlike constructors, they have names. 
  - unlike constructors,they are not required to create a new object each time they’re invoked  
  - unlike constructors,
    they can return an object of any subtype of their return type. 
  - the class of the returned
    object can vary from call to call as a function of the input parameters  
  - the class of the returned object
    need not exist when the class containing the method is written  

- Shortcoming:
  - classes without public or protected constructors cannot be subclassed  
  - they are hard for
    programmers to find  



### Item 2: Consider a builder when faced with many constructor parameters  

Static factories and constructors share a limitation: they do not scale well to large
numbers of optional parameters  

常用手动创建对象时普遍采用新建对象然后set属性，其在构造过程中可能处于不一致状态，存在线程安全问题

use builder

- Advantages :
  - 比JavaBeans线程安全，属性赋值在创建对象时，而非创建完后调用set方法
  - 当参数可选或是类型相同时，较使用可伸缩构造器更加灵活，便于拓展与理解

- Shortcoming:
  - In order to create an object,
    you must first create its builder  
  - 代码较冗长



### Item 3: Enforce the singleton property with a private constructor or an enum type  

枚举单例可以防止序列化和反射，但当其必须扩展自一个超类而不是枚举时不便于使用



### Item 4: Enforce noninstantiability with a private constructor  

抽象类可以通过继承实例化子类，且抽象容易被误导成需要继承

通过私有化构造器防止其被继承可能



### Item 5: Prefer dependency injection to hardwiring resources  



### Item 6: Avoid creating unnecessary objects  

在数据运算时优先使用基本类型，避免无意识的自动装箱

轻量级对象回收，JVM的垃圾回收器可做到



### Item 7: Eliminate obsolete object references  

内存泄漏问题，引用对象当不再被使用，例如一个数组存放对象的引用，当其只有一部分对象需要被引用时，其余不被使用的对象的引用仍存放在数组中，内存泄漏于是发生

变量定义在最小作用域

**内存泄漏来源**：

- 一个类自己管理它的内存时	要小心内存泄露问题， 元素被释放了，这个元素包含的所有引用都应该清空 
- 缓存	常用的缓存方式是WeakHashMap，当缓存的键引用过期后，将会自动被清除
-  监听器和其它调用 



###  Item 8: Avoid finalizers and cleaners   

- 不可预知性过强

  在Java 9中，终结方法已经被遗弃了，但它们仍被Java类库使用，相应用来替代终结方法的是清理方法（cleaner）。比起终结方法，清理方法相对安全点，但仍是不可以预知的，运行慢的，而且一般情况下是不必要的

- 导致严重的性能损失

  它会阻碍有效的垃圾回收，降低性能

- 使类暴露在finalizer attack下

  终结方法攻击的背后机制很简单：如果一个异常从构造器或者序列化中抛出（对于序列化，主要是readObject和readResolve方法，见12章），恶意子类的终结方法可以运行在本应夭折的只构造了部分的对象上。终结方法可以在一个静态属性上记录对象的应用，从而阻止这个对象被垃圾回收。一旦记录了有缺陷的对象，就可以简单地调用该对象上的任意方法，而这些方法本来就不应该允许存在。 可以final 修饰 finalizer方法

finalizer和cleaner用途：

- 用作安全网，提示需要调用资源的close方法

- 清理方法的第二种合法用途与对象的本地对等体（native peer）有关。

  本地对等体是指非Java实现的本地对象，普通对象通过本地方法代理给本地对象。由于本地对等体不是普通的对象，垃圾回收器并不知道它的存在进而当Java对等体被回收时也不会去回收它。而清理方法或终结方法正是适合完成这件事的工具，但前提条件是接受其性能并且本地对等体不持有关键资源。假如性能问题无法接受或者本地对等体持有的资源必须被及时回收，那么我们的类还是应该实现一个*close*方法，就如我们一开始提到。 



### Item 9: Prefer try-with-resources to try-finally  

try-finally在实际中可能嵌套多层而导致问题定位不清楚

try-with-resources代码更简短清晰，便于定位异常，其需要实现AutoCloseable接口，在close中抛出异常将被抑制



## Chapter 3. Methods Common to All Objects  

### Item 10: Obey the general contract when overriding equals  

- **类的每个实例本质上都是独一无二的**
- **无需为类提供"逻辑相等”测试**
- **若超类已经覆盖equals方法，那么超类的行为对于子类也是适用的**
- **一个类是私有的或者是包私有的，可以通过重写equals方法抛出异常拒绝调用**

当一个类需要有值的逻辑比较时需要覆盖equals方法



### Item 11: Always override hashCode when you override equals  



### Item 12: Always override toString  

toString方法需要提供类里面所有有用的东西



### Item 13: Override clone judiciously  



### Item 14: Consider implementing Comparable





## Chapter 4. Classes and Interfaces  

### Item 15: Minimize the accessibility of classes and members  

信息隐藏（information hiding） or 封装（encapsulation）





### Item 16: In public classes, use accessor methods, not public fields  

公有类不应暴露可变域

包级私有类或私有嵌套类可以暴露域，当你需要使用时



### Item 17: Minimize mutability  



### Item 18: Favor composition over inheritance  

Unlike method invocation, inheritance violates encapsulation  



### Item 19: Design and document for inheritance or else prohibit it  



### Item 20: Prefer interfaces to abstract classes



### Item 21: Design interfaces for posterity  



### Item 22: Use interfaces only to define types  



### Item 23: Prefer class hierarchies to tagged classes  





### Item 24: Favor static member classes over nonstatic  



### Item 25: Limit source files to a single top-level class  



## Chapter 5. Generics  

### Item 26: Don’t use raw types  



### Item 27: Eliminate unchecked warnings  

If you can’t eliminate a warning, but you can prove that the code that
provoked the warning is typesafe, then (and only then) suppress the
warning with an @SuppressWarnings("unchecked") annotation  

### Item 28: Prefer lists to arrays  



### Item 29: Favor generic types  



### Item 30: Favor generic methods  



### Item 31: Use bounded wildcards to increase API flexibility  



### Item 32: Combine generics and varargs judiciously  



### Item 33: Consider typesafe heterogeneous containers  



## Chapter 6. Enums and Annotations  

### Item 34: Use enums instead of int constants  

### Item 35: Use instance fields instead of ordinals  

### Item 36: Use EnumSet instead of bit fields  

### Item 37: Use EnumMap instead of ordinal indexing  

### Item 38: Emulate extensible enums with interfaces  

### Item 39: Prefer annotations to naming patterns  

### Item 40: Consistently use the Override annotation  

### Item 41: Use marker interfaces to define types  

## Chapter 7. Lambdas and Streams  

### Item 42: Prefer lambdas to anonymous classes  

### Item 43: Prefer method references to lambdas  

### Item 44: Favor the use of standard functional interfaces  

### Item 45: Use streams judiciously  

### Item 46: Prefer side-effect-free functions in streams  

### Item 47: Prefer Collection to Stream as a return type

### Item 48: Use caution when making streams parallel  

## Chapter 8. Methods  

### Item 49: Check parameters for validity  

### Item 50: Make defensive copies when needed  

### Item 51: Design method sign  atures carefully  

### Item 52: Use overloading judiciously  

### Item 53: Use varargs judiciously  

### Item 54: Return empty collections or arrays, not nulls  

### Item 55: Return optionals judiciously  

### Item 56: Write doc comments for all exposed API elements  

## Chapter 9. General Programming  

### Item 57: Minimize the scope of local variables  

### Item 58: Prefer for-each loops to traditional for loops  

### Item 59: Know and use the libraries  

### Item 60: Avoid float and double if exact answers are required  

### Item 61: Prefer primitive types to boxed primitives  

### Item 62: Avoid strings where other types are more appropriate  

### Item 63: Beware the performance of string concatenation  

### Item 64: Refer to objects by their interfaces  

### Item 65: Prefer interfaces to reflection  

### Item 66: Use native methods judiciously  

### Item 67: Optimize judiciously  

### Item 68: Adhere to generally accepted naming conventions  

## Chapter 10. Exceptions  



### Item 69: Use exceptions only for exceptional conditions  

### Item 70: Use checked exceptions for recoverable conditions and runtime exceptions for programming errors  

### Item 71: Avoid unnecessary use of checked exceptions  

### Item 72: Favor the use of standard exceptions  

### Item 73: Throw exceptions appropriate to the abstraction  

### Item 74: Document all exceptions thrown by each method  

### Item 75: Include failure-capture information in detail messages  

### Item 76: Strive for failure atomicity  

### Item 77: Don’t ignore exceptions  

## Chapter 11. Concurrency   

### Item 78: Synchronize access to shared mutable data  

### Item 79: Avoid excessive synchronization  

### Item 80: Prefer executors, tasks, and streams to threads  

### Item 81: Prefer concurrency utilities to wait and notify  

### Item 82: Document thread safety  

### Item 83: Use lazy initialization judiciously  

### Item 84: Don’t depend on the thread scheduler  

## Chapter 12. Serialization  

### Item 85: Prefer alternatives to Java serialization  

### Item 86: Implement Serializable with great caution  

### Item 87: Consider using a custom serialized form  

### Item 88: Write readObject methods defensively  

### Item 89: For instance control, prefer enum types to readResolve  

### Item 90: Consider serialization proxies instead of serialized instances  















