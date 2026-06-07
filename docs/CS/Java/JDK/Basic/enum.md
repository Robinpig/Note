## Introduction

**`enum` 关键字在 Java 5 中引入。** 它表示一种特殊类型的类，**总是继承 *java.lang.Enum* 类。**
**Java enum**，也称为 Java *枚举类型*，是一种其**字段由一组固定的常量组成**的类型。
enum 的根本目的是**强制执行编译时类型安全**。

当你创建 enum 时，编译器会为你生成一个关联的类。
这个类自动继承自 java.lang.Enum，它提供了某些能力：

ordinal() 方法生成一个 int，指示每个 enum 实例的声明顺序，从零开始。
你始终可以安全地使用 == 比较 enum 实例，并且 equals() 和 hashCode() 会自动为你创建。
Enum 类实现了 Comparable，因此有一个 compareTo() 方法，并且它也是 Serializable 的。

如果你在 enum 实例上调用 getDeclaringClass()，你将找到封闭的 enum 类。
name() 方法生成与其声明完全相同的名称，这也是 toString() 返回的结果。
valueOf() 是 Enum 的静态成员，生成与传递给它的 String 名称对应的 enum 实例，如果没有匹配项则抛出异常。

虽然 enums 看起来像是一种新的数据类型，但该关键字只是在生成 enum 的类时产生一些编译器行为，因此在许多方面你可以将 enum 视为任何其他类。
事实上，enums 就是类，并且有自己的方法。

一个特别好的特性是 enums 可以在 switch 语句中使用。
由于 switch 旨在从有限的一组可能性中进行选择，因此它是 enum 的理想匹配。注意 enum 名称如何能产生更清晰的意图表达。
通常，你可以将 enum 用作创建数据类型的另一种方式，然后将结果投入使用。

**使用 "==" 而非 equals 来比较枚举类型。**

**使用 enums 替代 int 常量。**

`finalize` is final

### Serialization

```java
/**
 * prevent default deserialization
 */
private void readObject(ObjectInputStream in) throws IOException,
    ClassNotFoundException {
    throw new InvalidObjectException("can't deserialize enum");
}

private void readObjectNoData() throws ObjectStreamException {
    throw new InvalidObjectException("can't deserialize enum");
}
```

```java
// Writes given enum constant to stream. only write Enum.name
private void writeEnum(Enum<?> en,
                       ObjectStreamClass desc,
                       boolean unshared)
    throws IOException
{
    bout.writeByte(TC_ENUM);
    ObjectStreamClass sdesc = desc.getSuperDesc();
    writeClassDesc((sdesc.forClass() == Enum.class) ? desc : sdesc, false);
    handles.assign(unshared ? null : en);
    writeString(en.name(), false);
}
```

~~~java
/** ObjectInputStream
 * Reads in and returns enum constant, or null if enum type is
 * unresolvable.  Sets passHandle to enum constant's assigned handle.
 */
private Enum<?> readEnum(boolean unshared) throws IOException {
  ...
    Enum<?> en = Enum.valueOf((Class)cl, name); // use name Enum.valueOf()
 		result = en;
  ```
    return result;
}
~~~

## EnumSet and EnumMap

### EnumSet

*EnumSet* 是一个专门的 *Set* 实现，旨在与 *Enum* 类型一起使用。

与 *HashSet* 相比，由于内部使用了 *位向量表示*，它是特定 *Enum* 常量 *Set* 的一种非常高效和紧凑的表示。它提供了传统的基于 *int* 的"位标志"的类型安全替代方案，允许我们编写更简洁、更易读和可维护的代码。

*EnumSet* 是一个抽象类，有两个实现称为 *RegularEnumSet* 和 *JumboEnumSet*，在实例化时根据 enum 中常量的数量选择其中一个。

因此，在大多数需要处理 enum 常量集合的场景中（如子集、添加、删除以及批量操作如 *containsAll* 和 *removeAll*），使用此 Set 通常是个好主意；如果只想迭代所有可能的常量，则使用 *Enum.values()*。

### EnumMap

*EnumMap* 是一个专门的 *Map* 实现，旨在使用 enum 常量作为键。与对应的 *HashMap* 相比，它是一种高效和紧凑的实现，内部表示为数组：

## Constant-Specific Methods

### Chain of Responsibility with enums

在责任链设计模式中，你创建多种不同的方式来解决问题，并将它们链接在一起。
当请求发生时，它沿着链传递，直到某个解决方案可以处理该请求。

你可以使用常量特定方法轻松实现简单的责任链。
考虑一个邮局的模型，它试图以尽可能通用的方式处理每件邮件，但必须继续尝试，直到最终将邮件视为死信。
每次尝试可以被认为是一个 Strategy（另一种设计模式），整个列表一起构成一个责任链。

我们从描述一件邮件开始。
所有感兴趣的不同特征都可以使用 enums 来表达。
由于 Mail 对象是随机生成的，降低（例如）一件邮件被给予 GeneralDelivery 的 YES 概率的最简单方法是创建更多的非 YES 实例，所以 enum 定义一开始看起来有点奇怪。

### State Machines with enums

枚举类型可以成为创建状态机的理想选择。
状态机可以处于有限数量的特定状态。
机器通常根据输入从一个状态移动到下一个状态，但也有瞬态状态；机器一旦完成任务就会离开这些状态。

每个状态都有某些允许的输入，不同的输入将机器的状态改变为不同的新状态。
因为 enums 限制了可能情况的集合，它们对于枚举不同的状态和输入非常有用。
每个状态通常也有某种关联的输出。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
