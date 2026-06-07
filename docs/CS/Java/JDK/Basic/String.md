## Introduction

String 类表示字符串。Java 程序中的所有字符串字面量都是此类的实例。
**字符串是常量；它们的值在创建后不能更改。**

String 就是这样一个类——但这依赖于对无害数据竞争的微妙推理，需要深入理解 Java 内存模型。
字符串缓冲区支持可变字符串。由于 String 对象是不可变的，它们可以被共享。
大小写映射基于 Character 类指定的 Unicode 标准版本。

Java 语言为字符串连接运算符（+）以及将其他对象转换为字符串提供了特殊支持。
字符串连接通过 `StringBuilder`（或 `StringBuffer`）类及其 append 方法实现。
字符串连接运算符的实现由 Java 编译器自行决定，只要编译器最终符合 Java 语言规范即可。
例如，javac 编译器可能根据 JDK 版本使用 `StringBuffer`、`StringBuilder` 或 `java.lang.invoke.StringConcatFactory` 来实现该运算符。
字符串转换的实现通常通过 toString 方法，该方法由 Object 定义并被 Java 中所有类继承。

String 以 **UTF-16** 格式表示字符串，其中补充字符由代理对表示（有关更多信息，请参见 Character 类中的 Unicode Character Representations 部分）。
索引值引用 char 代码单元，因此补充字符在 String 中占用两个位置。

避免使用字符串代替其他更合适的类型：

- 字符串是其他值类型的糟糕替代品。
- 字符串是枚举类型的糟糕替代品。
- 字符串是聚合类型的糟糕替代品。

## structure

### value

```java
public final class String
```

String 类被声明为 final，因此不能被继承。

### intern

String 类维护一个字符串池，最初为空。

当调用 intern 方法时，如果池中已经包含一个等于此 String 对象的字符串（由 equals 方法确定），则返回池中的字符串。否则，将此 String 对象添加到池中，并返回对此 String 对象的引用。

因此，对于任意两个字符串 s 和 t，s.intern() == t.intern() 为 true 当且仅当 s.equals(t) 为 true。

所有字面量字符串和字符串值常量表达式都会被内部化。

```java
public native String intern();
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
