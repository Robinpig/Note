## Introduction

在泛型类添加到 Java 之前，泛型编程是通过继承实现的。
ArrayList 类简单地维护了一个 Object 引用的数组：

```java
public class ArrayList // before generic classes
{
    private Object[] elementData;

    public Object get(int i) { //... 
    /}

    public void add(Object o) { //...
        // }
    }
}
```

这种方法有两个问题。每次检索值时都需要进行强制转换：

```java
ArrayList files = new ArrayList();
String filename = (String) files.get(0);

```

此外，没有错误检查。你可以添加任何类的值：

```java
files.add(new File("..."));
```

此调用编译并运行无误。在其他地方，将 get 的结果强制转换为 String 将导致错误。
泛型提供了更好的解决方案：类型参数。ArrayList 类现在有一个指示元素类型的类型参数：

```java
var files = new ArrayList<String>();
```

这使得你的代码更易于阅读。你可以立即知道这个特定的数组列表包含 String 对象。

泛型意味着参数化类型。

其思想是允许类型（Integer、String 等以及用户定义的类型）作为方法、类和接口的参数。使用泛型，可以创建适用于不同数据类型的类。

诸如类、接口或方法等操作参数化类型的实体称为泛型实体。

Object 是所有其他类的超类，Object 引用可以引用任何类型对象。这些特性缺乏类型安全。泛型增加了类型安全特性。

Java 中的泛型类似于 C++ 中的模板。例如，像 HashSet、ArrayList、HashMap 等类很好地使用了泛型。两种方法在泛型类型之间存在一些根本差异。

如何实现泛型？

- Code specialization
- Code sharing

`C++ and C# use Code specialization while Java use Code sharing.`

> "In layman,s term, generics force type safety in java language."
>
> "Generics add stability to your code by making more of your bugs detectable at compile time."

泛型的核心是"**类型安全**"。
类型安全到底是什么？这只是编译器的一个保证，如果正确的类型在正确的位置使用，那么在运行时就不应该有任何 `ClassCastException`。
一个用例可以是 `Integer` 的列表，即 `List<Integer>`。如果你在 Java 中声明像 `List<Integer>` 这样的列表，那么 Java 保证它会检测并报告任何尝试将非整数类型插入上述列表的行为。

Java 泛型中另一个重要的术语是"**类型擦除**"。
它本质上意味着使用泛型添加到源代码中的所有额外信息将从生成的字节码中删除。
在字节码内部，它将是你完全不使用泛型时得到的旧 Java 语法。这有助于生成和执行 Java 5 之前（当时语言中尚未添加泛型）编写的代码。

## Type Erasure

每当你定义泛型类型时，会自动提供一个相应的原始类型。原始类型的名称就是泛型类型的名称，并去掉了类型参数。
类型变量被擦除并替换为其边界类型（对于无边界的变量替换为 Object）。

类型擦除是从类型（可能包括参数化类型和类型变量）到类型（永远不会是参数化类型或类型变量）的映射。
我们用 |T| 表示类型 T 的擦除。擦除映射定义如下：

- 参数化类型 G`<`T1,...,Tn`>` 的擦除是 |G|。
- 嵌套类型 T`.`C 的擦除是 |T|.C。
- 数组类型 T`[]` 的擦除是 |T|`[]`。
- 类型变量的擦除是其最左边边界的擦除。
- 所有其他类型的擦除就是类型本身。

类型擦除还将构造方法或方法的签名映射为没有参数化类型或类型变量的签名。
构造方法或方法签名 s 的擦除是由相同名称的签名以及 s 中给出的所有形式参数类型的擦除组成的。

方法返回类型和泛型方法或构造方法的类型参数在方法或构造方法的签名被擦除时也经历擦除。

泛型方法的签名擦除没有类型参数。

generics not exist in JVM,only have List.class not List<Integer>.class

## Type Expression

通常参数：

- E - Element  use in Collection
- T - Type
- K - Key in Map
- V - Value in Map
- ? - Type not sure

## Restrictions and Limitations

在接下来的章节中，我将讨论在使用 Java 泛型时需要考虑的一些限制。
这些限制大多数是类型擦除的结果。

类型参数不能用基本类型实例化

你不能用基本类型替换类型参数。因此，没有 Pair<double>，只有 Pair<Double>。
原因当然是类型擦除。擦除后，Pair 类有 Object 类型的字段，你不能用它们来存储 double 值。
这确实有点烦人，但它与 Java 语言中基本类型的独立状态是一致的。
这不是一个致命的缺陷——只有八种基本类型，当包装类型不是可接受的替代品时，你总是可以用单独的类和方法来处理它们。

运行时类型查询仅适用于原始类型

虚拟机中的对象总是具有特定的非泛型类型。
因此，所有类型查询都只产生原始类型。
例如，

```
if (a instanceof Pair<String>) // ERROR
```

只能测试 a 是否是任何类型的 Pair。测试也是如此

```
if (a instanceof Pair<T>) // ERROR
```

或强制转换

```
Pair<String> p = (Pair<String>) a; // warning--can only test that a is a Pair
```

为了提醒你风险，当你尝试查询对象是否属于泛型类型时，你会收到编译器错误（对于 instanceof）或警告（对于强制转换）。
同样，getClass 方法总是返回原始类型。
例如：

```
Pair<String> stringPair = . . .;
Pair<Employee> employeePair = . . .;
if (stringPair.getClass() == employeePair.getClass()) // they are equal
```

比较返回 true，因为两次调用 getClass 都返回 Pair.class。

你不能实例化参数化类型的数组，例如

```
var table = new Pair<String>[10]; // ERROR"
```

你不能在像 new T(...) 这样的表达式中使用类型变量。
例如，下面的 Pair<T> 构造方法是非法的：

```
public Pair() { first = new T(); second = new T(); } // ERROR"
```

正如你不能实例化单个泛型实例一样，你也不能实例化数组。
原因不同——数组毕竟是用 null 值填充的，这似乎可以安全地构造。
但数组也携带一个类型，用于监视虚拟机中的数组存储。
那个类型被擦除了。

类型变量在泛型类的静态上下文中无效

你不能抛出或捕获泛型类的实例

你既不能抛出也不能捕获泛型类的对象。实际上，泛型类扩展 Throwable 甚至是不合法的。
例如，下面的定义将无法编译：

```
public class Problem<T> extends Exception { /* . . . */ }
      // ERROR--can't extend Throwable
```

你不能在 catch 子句中使用类型变量。例如，下面的方法将无法编译：

```java
    public static <T extends Throwable> void doWork(Class<T> t) {
        try {
            do work
        } catch (T e) // ERROR--can't catch type variable
        {
            Logger.global.info(. . .);
        }
    }
```

但是，在异常规范中使用类型变量是可以的。下面的方法是合法的：

```java
    public static <T extends Throwable> void doWork(T t) throws T // OK
    {
        try {
            do work
        } catch (Throwable realCause) {
            t.initCause(realCause);
            throw t;
        }
    }
```

你可以绕过受检异常检查

Java 异常处理的一个基本原则是必须为所有受检异常提供处理器。
你可以使用泛型来绕过这个规则。关键要素是这个方法：

```
SuppressWarnings("unchecked")
static <T extends Throwable> void throwAs(Throwable t) throws T{      
    throw (T) t;
}
```

## Valhalla

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
