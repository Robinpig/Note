## Introduction

[Project Valhalla](https://openjdk.java.net/projects/valhalla/) 计划用值对象和用户定义的原始类型来增强 Java 对象模型，将面向对象编程的抽象与简单原始类型的性能特性结合起来。
这些特性将伴随着 Java 泛型的变更，以通过通用 API 保持性能提升。

## Hidden Classes

根据字节创建一个隐藏类或接口，返回对新创建的类或接口的 Lookup。

通常，类或接口 C 由类加载器创建，类加载器要么直接定义 C，要么委托给另一个类加载器。类加载器通过调用 ClassLoader::defineClass 直接定义 C，这导致 Java 虚拟机从类文件格式的表示形式派生出 C。在不适合使用类加载器的情况下，可以通过此方法代替创建类或接口 C。此方法能够定义 C 并由此创建它，而无需调用 ClassLoader::defineClass。相反，此方法通过安排 Java 虚拟机从类文件格式的表示形式派生出非数组类或接口 C 来定义 C，使用以下规则：

- 此 Lookup 的查找模式必须包括完全权限访问。需要此级别的访问权限才能在此 Lookup 的查找类的模块中创建 C。
- 字节中的表示形式必须是受支持的主次版本的 ClassFile 结构。主次版本可能与此 Lookup 的查找类的类文件版本不同。
- this_class 的值必须是 constant_pool 表中的有效索引，并且该索引处的条目必须是有效的 CONSTANT_Class_info 结构。设 N 为此结构指定的内部形式编码的二进制名称。N 必须表示与查找类相同包中的类或接口。
- 设 CN 为字符串 N + "." + <suffix>，其中 <suffix> 是非限定名称。
  设 newBytes 为 bytes 给出的 ClassFile 结构，并在 constant_pool 表中添加一个额外的条目，指示 CN 的 CONSTANT_Utf8_info 结构，并且由 this_class 指示的 CONSTANT_Class_info 结构指向新的 CONSTANT_Utf8_info 结构。
  设 L 为此 Lookup 的查找类的定义类加载器。
  C 使用名称 CN、类加载器 L 和表示形式 newBytes 按照 JVMS 的规则派生，并进行以下调整：
    - this_class 指示的常量允许指定包含单个"."字符的名称，即使这不是有效的内部形式二进制类或接口名称。
    - Java 虚拟机将 L 标记为 C 的定义类加载器，但没有类加载器被记录为 C 的发起类加载器。
    - C 被视为与此 Lookup 的查找类具有相同的运行时包、模块和保护域。
    - 设 GN 为通过取 N（内部形式编码的二进制名称）并将 ASCII 正斜杠替换为 ASCII 句点而获得的二进制名称。对于表示 C 的 Class 实例：
        - Class.getName() 返回字符串 GN + "/" + <suffix>，即使这不是有效的二进制类或接口名称。
        - Class.descriptorString() 返回字符串 "L" + N + "." + <suffix> + ";"，即使这不是有效的类型描述符名称。
        - Class.describeConstable() 返回空的 optional，因为 C 无法以名义形式描述。

```java
public Lookup defineHiddenClass(byte[] bytes, boolean initialize, ClassOption... options)
                throws IllegalAccessException
   {
		...
    return makeHiddenClassDefiner(bytes.clone(), Set.of(options), false).defineClassAsLookup(initialize);
}

Lookup defineClassAsLookup(boolean initialize) {
    Class<?> c = defineClass(initialize, null);
    return new Lookup(c, null, FULL_POWER_MODES);
}
```

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
