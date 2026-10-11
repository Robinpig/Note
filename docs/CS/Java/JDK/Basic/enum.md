## Introduction

**The `enum` keyword was introduced in Java 5.** It denotes a special type of class that **always extends the `java.lang.Enum` class.**
An enum, also called an *enumeration type*, is a type whose **fields consist of a fixed set of constants**; its very purpose is to **enforce compile-time type safety**—the replacement for the error-prone `int` constants pattern.

When you declare an enum, the compiler generates a `final` class that extends `Enum<E>` and adds the constants as `public static final` fields. In many ways you can treat an enum as a class: it can have fields, methods, constructors, even implement interfaces—but it cannot extend another class (`Enum` 已是父类) nor be subclassed (隐式 `final`)。

`Enum` 基类提供了：`ordinal()`（声明次序，从 0 起）、`name()`（声明名，同 `toString()`）、`compareTo()`（按 ordinal）、`valueOf(Class, String)`（按名取常量）。`Enum` 同时是 `Comparable` 与 `Serializable`。`Enum.finalize()` 被声明为 `final`，阻止枚举实例被 finalization 破坏。

### Compile-time Generation

编译器为每个枚举注入两个静态方法：

- `values()`：**返回当前所有常量的数组拷贝**（`Arrays.clone()`），每次调用都新建数组（防御性拷贝，修改返回值不影响枚举）——这也是枚举可被遍历的原因；
- `valueOf(String)`：编译器生成的静态方法，委托 `Enum.valueOf(Class, name)`；若名字无匹配常量抛 `IllegalArgumentException`（**不是** `NoSuchElementException`）。

```java
enum Color { RED, GREEN, BLUE }
for (Color c : Color.values()) {        // 每次都是新数组
    System.out.println(c.name() + "=" + c.ordinal());
}
Color x = Color.valueOf("RED");         // OK
Color y = Color.valueOf("PURPLE");      // IllegalArgumentException
```

### Constant-Specific Methods

每个常量可以**覆写**枚举上声明的 `abstract` 或具体方法，实现"常量相关行为"——这是枚举替代策略/状态机模式的核心手段：

```java
enum Operation {
    PLUS   { double apply(double x, double y) { return x + y; } },
    MINUS  { double apply(double x, double y) { return x - y; } };
    abstract double apply(double x, double y);
}
```

配合 `switch` 也可实现状态机（每个状态是枚举常量，输入驱动状态迁移）。

### Implementing Interfaces

枚举可以 `implements` 接口（从而让常量以接口类型被统一引用），但不能 `extends` 其它类。构造器**隐式 `private`**（显式写 `private` 也行，写 `public`/`protected` 编译报错），因此枚举常量只能在声明处实例化。

### Enum Singleton

Effective Java 第 3 条：实现单例**首选枚举**。一个单元素枚举（`enum Singleton { INSTANCE }`）天然获得：

- **无偿的序列化安全**：枚举反序列化不会创建新实例（见 [Serialization](#serialization)），无需写 `readResolve`；
- **防止反射攻击**：`Constructor.newInstance` 对枚举类型直接抛 `IllegalArgumentException`（`"Cannot reflectively create enum objects"`）；
- **防止克隆攻击**：`Enum.clone()` 直接抛 `CloneNotSupportedException`。

```java
public enum Elvis { INSTANCE; public void leaveTheBuilding() { ... } }
```

### ordinal Pitfall

`ordinal()` 反映**声明次序**，重构（增删常量、调序）会悄悄改变其值——**绝不可用于持久化、协议字段或任何跨版本依赖**。需要稳定的关联整数时，应自行声明字段：

```java
enum Planet {
    MERCURY(1), VENUS(2), EARTH(3);   // 用独立字段而非 ordinal()
    private final int id;
    Planet(int id) { this.id = id; }
}
```

## EnumSet and EnumMap

### EnumSet

`EnumSet` is a specialized `Set` for enum constants. It uses a **bit-vector** representation (one bit per constant), making it far more compact and faster than `HashSet` for the same purpose; it is a type-safe alternative to traditional `int` bit-flags.

`EnumSet` is `abstract` with two implementations, `RegularEnumSet` (a single `long`, holds ≤ 64 constants) and `JumboEnumSet` (a `long[]`), chosen by constant count at instantiation. Since **JDK 21** the class is `sealed` (`permits JumboEnumSet, RegularEnumSet`), so it can no longer be subclassed outside `java.util`. See [Set](/docs/CS/Java/JDK/Collection/Set.md?id=enumset) for the bit-vector internals and the 64-constant threshold.

### EnumMap

`EnumMap` is a specialized `Map` with enum constants as keys, internally backed by an array (`keyUniverse` + `vals`) rather than a hash table—O(1) lookup, no hashing, no boxing of keys. See [Map](/docs/CS/Java/JDK/Collection/Map.md?id=enummap) for the layout.

## Serialization

枚举的序列化与普通对象**根本不同**：序列化只写常量名（`TC_ENUM` + `name`），反序列化用 `Enum.valueOf` 按名取回既有单例，绝不会新建对象。

```java
// ObjectOutputStream.writeEnum: 只写 name
private void writeEnum(Enum<?> en, ObjectStreamClass desc, boolean unshared) throws IOException {
    bout.writeByte(TC_ENUM);
    ObjectStreamClass sdesc = desc.getSuperDesc();
    writeClassDesc((sdesc.forClass() == Enum.class) ? desc : sdesc, false);
    handles.assign(unshared ? null : en);
    writeString(en.name(), false);
}
```

```java
// ObjectInputStream.readEnum: 用 Enum.valueOf 取回既有实例
private Enum<?> readEnum(boolean unshared) throws IOException {
    // ...
    Enum<?> en = Enum.valueOf((Class) cl, name);
    return en;
}
```

自定义 `readObject`/`readObjectNoData` 应直接拒绝，进一步加固（防止畸形流触发构造）：

```java
private void readObject(ObjectInputStream in) throws IOException, ClassNotFoundException {
    throw new InvalidObjectException("can't deserialize enum");
}
private void readObjectNoData() throws ObjectStreamException {
    throw new InvalidObjectException("can't deserialize enum");
}
```

## Switch on Enum

`switch` 与枚举是天作之合（有限候选集）。在早期 JDK 中，枚举 switch 被编译为**合成类（synthetic `$SwitchMap$...`）+ 以 `ordinal()` 为索引的整数查表**，避免字符串比较；因此调整枚举常量声明顺序**不会**破坏既有 switch（编译器会重新生成映射表），但若某分支常量被删除，会落入 `default`。

JDK 14–21 引入的**模式匹配 switch**（JEP 441，JDK 21 final）对枚举也适用，底层改用 `EnumDesc` 等运行时描述符，并与 `sealed` 类型的穷尽性检查配合——编译器可在枚举所有可能常量都已覆盖时省略 `default` 而不报"不穷尽"。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [PrimitiveType](/docs/CS/Java/JDK/Basic/PrimitiveType.md) — 枚举替换 int 常量
- [Set](/docs/CS/Java/JDK/Collection/Set.md) — EnumSet 位向量实现
- [Map](/docs/CS/Java/JDK/Collection/Map.md) — EnumMap 数组实现
- [serialize](/docs/CS/Java/JDK/Basic/serialize.md) — 枚举序列化与普通对象差异

## References

1. [JLS §8.9 Enum Types](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.9)
2. [Effective Java, 3rd Edition (Bloch)](https://www.oreilly.com/library/view/effective-java-3rd/9780134686097/) — Item 3 (Singleton), 34 (Enums), 36 (Use EnumMap/EnumSet)
3. [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441)
