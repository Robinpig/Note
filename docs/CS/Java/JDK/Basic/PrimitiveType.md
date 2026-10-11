## Introduction

Java 有 **8 种基本类型（primitive type）** 加 `void`（9 种，但 `void` 不可用于变量声明）。基本类型变量**持有值本身而非引用**，且大小由语言规范固定（不随平台变化，这是 Java 可移植性的来源之一）。它们与对应的包装类（wrapper class）之间由自动装箱/拆箱（autoboxing/unboxing）桥接。

基本类型在 JVM 中并非一等公民：`boolean`、`byte`、`char`、`short` 在栈帧局部变量区与 `int`/`reference` 占用相同的存储单元，只在字段与数组元素上才按值域宽度存储。

## Categories

基本类型分为两类：**数值类型（numeric）** 与 **`boolean`**。`returnAddress` 只存在于 JVM 层面（指向 `jsr/ret` 指令的操作码），Java 语言中没有对应类型，现代 JVM 已不再使用。

| **Primitive type** | **Size** | **Minimum** | **Maximum**    | **Wrapper type** |
| ------------------ | -------- | ----------- | -------------- | ---------------- |
| **boolean**        | —       | —          | —             | **Boolean**      |
| **char**           | 16-bit   | Unicode 0   | Unicode 2¹⁶-1 | **Character**    |
| **byte**           | 8-bit    | -128        | +127           | **Byte**         |
| **short**           | 16-bit   | -2¹⁵        | +2¹⁵-1        | **Short**        |
| **int**            | 32-bit   | -2³¹        | +2³¹-1        | **Integer**      |
| **long**           | 64-bit   | -2⁶³        | +2⁶³-1        | **Long**         |
| **float**          | 32-bit   | IEEE754     | IEEE754        | **Float**        |
| **double**         | 64-bit   | IEEE754     | IEEE754        | **Double**      |

所有数值类型都是**有符号**的，Java 没有无符号整数类型（仅通过 JDK 8 起的无符号工具方法模拟，见 [Unsigned API](#unsigned-api)）。`boolean` 的大小**未被规范明确定义**，只规定取值为 `true`/`false`。

## Size and Default Values

当基本类型是类成员且未显式初始化时，JVM 保证其得到默认值；局部变量无默认值，必须显式赋值后才能使用（否则编译错误）。

| Primitive type | Range | Default | JVM Sign |
| -------------- | ----- | ------- | -------- |
| boolean  | {false, true} | false | Z |
| char     | [0, 65535]    | '\u0000' | C |
| byte     | [-128, 127]   | (byte)0  | B |
| short    | [-32768, 32767] | (short)0 | S |
| int      | [-2³¹, 2³¹-1] | 0 | I |
| long     | [-2⁶³, 2⁶³-1] | 0L | J |
| float    | ~[-3.4E38, 3.4E38] | 0.0f | F |
| double   | ~[-1.8E308, 1.8E308] | 0.0d | D |

`char` 默认是非负的，因此常被用来做数组索引（索引值 >= 0）。

### Stack vs Heap Representation

JVM 每调用一个 Java 方法就创建一个栈帧，其局部变量区等价于一个数组。除 `long`、`double` 值需用**两个数组单元**存储外，其他基本类型及引用类型均占用一个单元。即 `boolean`、`byte`、`char`、`short` 在栈上占用的空间与 `int`、`reference` 相同——32 位 HotSpot 占 4 字节，64 位占 8 字节。**这种"放大"只发生在栈上的局部变量，不出现在堆中的字段或数组元素上**：`byte`/`char`/`short` 字段或数组单元在堆上分别占 1/2/2 字节，与值域吻合。

- 存储到更小字段时会被**截断/掩码**（`i2b` 取低 8 位）；
- 从较小类型加载到操作数栈时用**零扩展**（`i2c`/`i2b`）或**符号扩展**（`i2s`）填充高位。

## Autoboxing and Unboxing

**Autoboxing** 是 Java 5 引入的编译器语法糖：在需要包装类对象的上下文里出现基本类型值时，编译器自动插入 `Integer.valueOf(int)` 之类的调用；**unboxing** 反之，在需要基本类型的上下文里出现包装类时插入 `intValue()` 等。

```java
List<Integer> list = new ArrayList<>();
list.add(5);          // autobox: Integer.valueOf(5)
int x = list.get(0);  // unbox: list.get(0).intValue()
```

### Caching Ranges

`valueOf` 对部分范围做了**对象缓存（flyweight）**，符合 JLS §5.1.7 的"值在特定区间内时返回既有对象"规定：

| Wrapper | 缓存区间 | 说明 |
| ------- | -------- | ---- |
| `Boolean` | `TRUE`/`FALSE` | 仅两个常量 |
| `Byte` | 全部 [-128,127] | 值域内全缓存 |
| `Short` | [-128,127] | |
| `Integer` | [-128,127] | 上限可由 `-XX:AutoBoxCacheMax=` 调大（下限固定 -128） |
| `Long` | [-128,127] | |
| `Character` | [0,127] | |
| `Float` / `Double` | **不缓存** | 每次 `valueOf` 返回新对象 |

```java
Integer a = 127, b = 127;   // 同一缓存对象
Integer c = 128, d = 128;   // 两个不同对象
System.out.println(a == b); // true
System.out.println(c == d); // false
```

### == vs equals

这是基本类型与包装类最易踩的坑：

- **基本类型用 `==` 比较的是值**；
- **包装类用 `==` 比较的是引用**（即使值相等也可能为 `false`，除非命中缓存）；
- 包装类的值相等必须用 `equals` 比较。

```java
Integer x = 1000, y = 1000;
x == y;          // false（未命中缓存，两个对象）
x.equals(y);    // true
int m = 1000, n = 1000;
m == n;         // true（基本类型比较值）
```

**拆箱 NPE**：对 `null` 的包装类做 unboxing（如 `int i = (Integer) someNull`）会抛 `NullPointerException`。`BigDecimal` 等数值类型同理——用 `compareTo()` 而非 `equals()` 比较数值（见 [Floating Point](#floating-point)）。

## Numeric Promotion

表达式求值时 JVM 会按规则做**数值提升（numeric promotion）**：

- **一元数值提升**：`+`、`-`、`~` 操作数若为 `byte`/`short`/`char` 先提升为 `int`；`++`/`--` 同样。
- **二元数值提升**：双目算术运算（`+ - * / %`、位运算、比较、条件 `?:`）中，若任一操作数是 `double`/`float`/`long`，另一被提升到对应类型；否则两操作数都提升为 `int`。

```java
short s = 1;
s = s + 1;   // 编译错误：s+1 结果是 int，不能赋回 short
s++;         // 合法：复合赋值内含隐式窄化转换 (s = (short)(s + 1))
```

提升是**整数溢出陷阱**的来源之一：`int` 相乘若结果超出 2³¹ 会静默环绕，应在运算前转 `long`：

```java
long millis = 24 * 60 * 60 * 1000;        // 溢出，结果为负数
long millis2 = 24L * 60 * 60 * 1000;      // 正确
```

字符串拼接 `+` 中，若任一操作数是 `String`，其余基本类型也按提升规则转字符串。

## Floating Point

`float`/`double` 遵循 IEEE 754（Java SE 15 起采用 2019 版）。规范要求支持正负零、正负无穷与 NaN（Not-a-Number，表示无效运算如 `0.0/0.0`）。

**`strictfp` 已成 no-op**：JEP 306（**JDK 17**）让**所有**浮点表达式默认严格求值，旧的"非严格"语义被移除——`strictfp` 关键字仍语法有效但不再改变行为（编译器发警告），未来版本将移除该关键字。在 JDK 17 之前，`strictfp` 用于保证跨平台浮点结果一致；之后无需再写。

```java
// JDK 17 起这行会触发警告：[strictfp] as of release 17 ... 'strictfp' is not required
public strictfp double sum(double a, double b) { return a + b; }
```

### BigDecimal

需要精确小数运算（货币、税率）时**不要**用 `float`/`double`，改用 `BigDecimal`，且**必须用 `String` 构造器**避免 `double` 字面量的固有误差：

```java
new BigDecimal(0.1);  // 实际是 0.1000000000000000055...（double 近似）
new BigDecimal("0.1"); // 精确的 0.1
```

`BigDecimal.equals` 同时比较**值与标度（scale）**——`2.0` 与 `2.00` 因 scale 不同而 `equals` 为 `false`；数值比较应一律用 `compareTo()`。

```java
@Override
public boolean equals(Object x) {
    if (!(x instanceof BigDecimal)) return false;
    BigDecimal xDec = (BigDecimal) x;
    if (x == this) return true;
    if (scale != xDec.scale) return false;   // 比 scale
    // ... 比 intCompact / intVal
}
public int compareTo(BigDecimal val) {
    if (scale == val.scale) { /* 同 scale 直接比 */ }
    int xsign = this.signum(), ysign = val.signum();
    if (xsign != ysign) return (xsign > ysign) ? 1 : -1;
    if (xsign == 0) return 0;
    return (xsign > 0) ? compareMagnitude(val) : -compareMagnitude(val);
}
```

`BigInteger` 用于任意精度整数，是不可变的，运算都返回新对象。

## Atomicity and Visibility

JLS §17.7 规定：**对非 `volatile` 的 `long`/`double` 字段的读写，允许作为两个独立的 32 位操作进行**，因此在 32 位 JVM 上可能读到"撕裂"的部分写结果（一个高 32 位来自新值、低 32 位来自旧值）。

- 用 `volatile` 修饰 `long`/`double` 字段可强制其读写为**单次的 64 位原子操作**；
- 所有 32 位基本类型（`int`/`float`/`char`/`short`/`byte`/`boolean`）的字段读写本来就保证原子性；
- 原子性 ≠ 可见性：`volatile` 同时提供可见性有序性语义，但**不保证复合操作（如 `i++`）的原子性**——`i++` 仍是非原子的读-改-写，需 `AtomicLong` 或 `synchronized`。详见 [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)。

## Unsigned API

Java 无原生无符号整数类型，但 JDK 8 在 `Integer`/`Long` 上新增了一组无符号工具方法，处理以无符号语义解读有符号位模式：

```java
Integer.toUnsignedString(-1);      // "4294967295"
Integer.compareUnsigned(-1, 1);    // >0（-1 作为无符号是最大正整数）
Integer.divideUnsigned(0xFFFFFFFF, 2);  // 2147483647（无符号除法）
Integer.parseUnsignedInt("4294967295"); // 返回 -1 的位模式
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [enum](/docs/CS/Java/JDK/Basic/enum.md) — 基于 int 的常量替换为枚举
- [semantics](/docs/CS/Java/JDK/Basic/semantics.md) — 装箱/拆箱与 == 的语义纪律
- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md) — 64 位字段的原子性保障

## References

1. [JLS §4.2 Primitive Types and Values](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.2)
2. [JLS §5.1.7 Boxing Conversion](https://docs.oracle.com/javase/specs/jls/se25/html/jls-5.html#jls-5.1.7)
3. [JLS §17.7 Non-atomic Treatment of double and long](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.7)
4. [JEP 306: Restore Always-Strict Floating-Point Semantics](https://openjdk.org/jeps/306)
