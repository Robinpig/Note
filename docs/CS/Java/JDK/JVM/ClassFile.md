## Introduction

Class 文件是 Java 「一次编写，到处运行」的载体：编译器把 Java 源码编译成与平台无关的字节码，JVM 再把字节码翻译成本地机器码。理解 class 文件的结构，等于理解了 JVM 的输入格式。

## 版本基线

> [!NOTE]
> **版本口径**：class 文件格式由《Java SE 规范》锁定，整体结构长期稳定，**主版本号随版本递进**：
>
> | Java | major | Java | major |
> | :-- | :--: | :-- | :--: |
> | 7 | 51 | 17 | 61 |
> | 8 | 52 | 21 | 65 |
> | 9 | 53 | 25 | 69 |
> | 11 | 55 | | |
>
> 前两位是 `0xCAFE BABE`（cafebabe），次两位是 minor，第三、四位是 major。本篇的常量池与属性表结构适用于近年版本。JVM 域的新特性记录见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=版本基线)。

## 整体结构

class 文件是一段**紧凑的二进制流**，没有对齐要求：

```text
ClassFile {
    u4             magic;              // 0xCAFEBABE
    u2             minor_version;
    u2             major_version;
    u2             constant_pool_count;
    cp_info        constant_pool[constant_pool_count-1];   // 索引 1 开始
    u2             access_flags;
    u2             this_class;
    u2             super_class;
    u2             interfaces_count;
    u2             interfaces[interfaces_count];
    u2             fields_count;
    field_info     fields[fields_count];
    u2             methods_count;
    method_info    methods[methods_count];
    u2             attributes_count;
    attribute_info attributes[attributes_count];
}
```

> [!TIP]
> 常量池下标从 **1** 开始，`0` 保留作「不存在」的占位（如 `super_class` 为 0 表示 `java.lang.Object`）；`constant_pool_count` 记录的是**实际条目数 + 1**。这两个「反直觉」的约定是手写 class 文件工具时最常见的 bug 来源。

用 [jclasslib bytecode editor](https://github.com/ingokegel/jclasslib) 可以直观查看 class 文件的每个字段。

## access flags

`access_flags` 描述类/接口的访问级别与特性，是 16 位掩码：

| 标志 | 含义 |
| :-- | :-- |
| `ACC_PUBLIC` (0x0001) | public |
| `ACC_PRIVATE` / `ACC_PROTECTED` / `ACC_PACKAGE` | 访问级别（三者互斥） |
| `ACC_STATIC` | static（接口方法不允许） |
| `ACC_FINAL` | final |
| `ACC_SUPER` / `ACC_SYNCHRONIZED` | 同步相关 |
| `ACC_VOLATILE` / `ACC_BRIDGE` | 协变返回的桥接方法 |
| `ACC_VARARGS` | 可变参数（`...`） |
| `ACC_INTERFACE` | 标志这是接口 |
| `ACC_ABSTRACT` | 抽象类/方法 |
| `ACC_SYNTHETIC` | 编译器生成（非源码） |
| `ACC_ANNOTATION` | 标志这是注解类型 |
| `ACC_ENUM` | 标志这是枚举 |
| `ACC_MODULE` (0x8000) | 这是 `module-info` |

> [!NOTE]
> `ACC_SUPER` 是历史包袱：JDK 1.0.2 之前没有它，用于改变 `invokespecial` 对 `super` 的处理语义。现在几乎所有编译产物都置上它，**判断一个类是不是「老式」时可以看这个位**。

## Constant Pool

常量池是 class 文件的**核心**：它既是「符号表」，又承载了字面量。

- **字面量（Literal）**：`int`、`long`、`float`、`double`、`String` 的值
- **符号引用（Symbolic Reference）**：类名与全限定名、字段名与方法名、字段与方法的类型描述符

常量池条目通过 `tag` 区分类型：

| tag | 类型 | 用途 |
| :-- | :-- | :-- |
| 1 | `CONSTANT_Utf8` | UTF-8 字符串，是其它所有引用的**基础** |
| 3 | `CONSTANT_Integer` | int 字面量 |
| 4 | `CONSTANT_Float` | float 字面量 |
| 5 | `CONSTANT_Long` | long 字面量（**占两个槽**） |
| 6 | `CONSTANT_Double` | double 字面量（**占两个槽**） |
| 7 | `CONSTANT_Class` | 类引用，指向一个 Utf8（内部形式是 `java/lang/String`） |
| 8 | `CONSTANT_String` | String 字面量，指向一个 Utf8 |
| 9 | `CONSTANT_Fieldref` | 字段引用（类名 + 字段名 + 描述符） |
| 10 | `CONSTANT_Methodref` | 方法引用 |
| 11 | `CONSTANT_InterfaceMethodref` | 接口方法引用 |
| 12 | `CONSTANT_NameAndType` | 字段名 + 描述符 |
| 15 | `CONSTANT_MethodHandle` | 方法句柄（invokedynamic 用） |
| 16 | `CONSTANT_MethodType` | 方法类型签名 |
| 17 | `CONSTANT_Dynamic` | 动态计算常量 |
| 18 | `CONSTANT_InvokeDynamic` | 动态调用点（Lambda 的实现基础） |
| 19 | `CONSTANT_Module` / 20 `CONSTANT_Package` | 模块化（9+） |

> [!WARNING]
> **`long` 和 `double` 各占两个常量池槽位**。所以遍历常量池时索引不能简单 `i++`，必须按 tag 判断是否跳过下一项——否则会错位。这是解析 class 文件时的高频 bug。规范上槽位 1 也不能被 long/double 占用（为了兼容早期实现）。

## 方法调用指令

class 文件里最关键的一组字节码是方法调用，它们决定了方法分派走哪条路：

| 指令 | 何时用 | 特点 |
| :-- | :-- | :-- |
| `invokevirtual` | public/protected 的非 static、非 final 方法 | 需运行时**虚方法表（vtable）**分派 |
| `invokeinterface` | 接口方法 | 需先拿到 `this` 对象的 `Klass` 再查接口方法表 |
| `invokespecial` | private 方法、构造器 `<init>`、以及 `super.` 调用 | **不走虚表**，编译期直接绑定（JEP 181 起不再用于私有接口方法） |
| `invokestatic` | static 方法 | 无 `this`，同样不走虚表 |
| `invokedynamic` | Lambda、字符串拼接（9+）、record 的 `equals/hashCode` 等 | 首次执行时把**引导方法**链接到实际目标 |

对应的 vtable/itable 机制见 [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)。

> [!TIP]
> [JEP 181](https://openjdk.org/jeps/181)（Nest-Based Access Control，Release **11**）**放宽**了这条历史约束，方向与直觉相反：Java 8 起允许接口私有方法后，规范一度要求它们用 `invokespecial` 调用；JEP 181 明确取消该限制，改为**私有接口方法可以用 `invokeinterface`**（私有构造器仍用 `invokespecial`，私有非接口方法可用 `invokevirtual`）。该 JEP 同时引入 `NestHost` / `NestMembers` 属性，允许同一 nest 的类互相访问私有成员，从而让编译器不必再生成「访问桥接方法」。**注意这套规则需要足够新的 class 文件版本才会被 JVM 启用。**

## 字节码与调试属性

`Code` 属性里除了字节码指令，还常挂两类调试信息属性：

- **`LineNumberTable`** —— 字节码偏移量到**源码行号**的映射，异常栈回溯能打出「第 N 行」靠它；
- **`LocalVariableTable`** —— 槽位到**变量名与类型**的映射，调试器显示局部变量名靠它。

这两者都**不影响语义**，可以用 `-g:none` 省略以减小体积；但生产环境排查问题时，缺失它们会让栈信息变得很难读。

## 类加载与方法链接

class 文件只是「原料」，从它到可执行代码要经过 [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md) 的三阶段：

- **加载（load）**：把字节流读成 `Class` 的内部表示（对应 [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md) 的 Klass 层级）；
- **链接（link）**：验证字节码、准备静态字段、把常量池中的符号引用**解析**为直接引用；
- **初始化（initialize）**：执行 `<clinit>()`，给静态字段赋真实值。

## Links

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)
- [Javac](/docs/CS/Java/JDK/JVM/Javac.md)
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [JMH](/docs/CS/Java/JDK/JVM/JMH.md)
