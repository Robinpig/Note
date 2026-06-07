## Introduction

Class 类的实例代表正在运行的 Java 应用程序中的类和接口。enum 是一种类，annotation 是一种接口。每个数组也属于一个被反射为 Class 对象的类，所有具有相同元素类型和维数的数组共享同一个 Class 对象。Java 基本类型（boolean、byte、char、short、int、long、float 和 double）以及关键字 void 也被表示为 Class 对象。
Class 没有公共构造方法。相反，Class 对象由 Java 虚拟机在类加载时自动构建，并通过调用类加载器中的 defineClass 方法构建。

- Class
- Constructor
- Field
- Method

Get Class Object

1. ClassName.class
2. Class.forName()
3. Instance.getClass()
4. ClassLoader.loadClass()

1. `getName()` 返回由此 Class 对象表示的实体（类、接口、数组类、基本类型或 void）的名称，以 String 形式返回。
2. `getSimpleName()` 返回源代码中给定底层类的简单名称。如果底层类是匿名的，则返回空字符串。
3. `getCanonicalName()` 返回 Java 语言规范定义的底层类的规范名称。如果底层类没有规范名称（即，如果它是局部或匿名类，或者是组件类型没有规范名称的数组），则返回 null。

| Class           | getName             | getSimpleName | getCanonicalName    |
| --------------- | ------------------- | ------------- | ------------------- |

```java
public class Student {
    // fields, constructors, methods...
}
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
