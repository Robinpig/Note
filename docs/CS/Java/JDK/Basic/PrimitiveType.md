## Introduction

也就是说，不使用 **new** 创建变量，而是创建一个"自动"变量，它*不是一个引用*。
该变量保存值，并且被**放置在栈上**，因此效率更高。

**优先使用基本类型而不是装箱基本类型。**

- numeric types
  - integral types
  - floating-point types
- boolean type
- returnAddress type

#### The returnAddress Type and Values

returnAddress 类型的值是指向 Java 虚拟机指令操作码的指针。
在基本类型中，只有 returnAddress 类型不与任何 Java 编程语言类型直接关联。

#### The boolean Type

Java 编程语言中对 boolean 值进行操作的表达式被编译为使用 Java 虚拟机 int 数据类型的值。

Java 虚拟机使用 1 表示 true，0 表示 false 来编码 boolean 数组组件。
当 Java 编程语言的 boolean 值由编译器映射到 Java 虚拟机 int 类型的值时，
编译器必须使用相同的编码。

### Size

Java 确定每种基本类型的大小。这些大小不会像在大多数语言中那样随着机器架构的变化而变化。

### Literals

```java
// 十六进制
int hex = 0x1F;
// 八进制
int oct = 017;
// 二进制
int bin = 0b1010;
// 数字分隔符
int underscore = 1_000_000;
```

基本类型位于栈上（而对象位于堆上）。

装箱基本类型有值，而无基本类型则没有；装箱基本类型可以有 null 值。

```java
Integer i = null; // 合法
int j = null; // 非法
```

装箱基本类型比基本类型占用更多内存。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
