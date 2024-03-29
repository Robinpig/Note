## Introduction

That is, instead of creating the variable by using **new**, an “automatic” variable is created that is *not a reference*.
The variable holds the value, and it’s **placed on the stack**, so it’s much more efficient.

**Prefer primitive types to boxed primitives**.

- numeric types
  - integral types
  - floating-point types
- boolean type
- returnAddress type

#### The returnAddress Type and Values

The values of the returnAddress type are pointers to the opcodes of Java Virtual Machine instructions.
Of the primitive types, only the returnAddress type is not directly associated with a Java programming language type.

#### The boolean Type

Expressions in the Java programming language that operate on boolean values are compiled to use values of the Java Virtual Machine int data type.

The Java Virtual Machine encodes boolean array components using 1 to represent true and 0 to represent false.
Where Java programming language boolean values are mapped by compilers to values of Java Virtual Machine type int,
the compilers must use the same encoding.

### Size

Java determines the size of each primitive type. These sizes don’t change from one machine architecture to another as they do in most languages.

`This size invariance is one reason Java programs are portable.`


| **Primitive type** | **Size** | **Minimum** | **Maximum**    | **Wrapper type** |
| ------------------ | -------- | ----------- | -------------- | ---------------- |
| **boolean**        | —       | —          | —             | **Boolean**      |
| **char**           | 16-bit   | Unicode 0   | Unicode 216- 1 | **Character**    |
| **byte**           | 8-bit    | -128        | +127           | **Byte**         |
| **short**          | 16-bit   | -215        | +215—1        | **Short**        |
| **int**            | 32-bit   | -231        | +231—1        | **Integer**      |
| **long**           | 64-bit   | -263        | +263—1        | **Long**         |
| **float**          | 32-bit   | IEEE754     | IEEE754        | **Float**        |
| **double**         | 64-bit   | IEEE754     | IEEE754        | **Double**       |
| **void**           | —       | —          | —             | **Void**         |

All numeric types are **signed**, so don’t look for unsigned types.

The size of the **boolean** type is not explicitly specified; it is only defined to be able to take the literal values **true**(1) or **false**(0).

The “wrapper” classes for the primitive data types allow you to make a nonprimitive object on the heap to represent that primitive type.

#### Java has no “sizeof”

In C and C++, the sizeof( ) operator satisfies a specific need: it tells you the number of bytes allocated for data items. The most compelling need for sizeof( ) in C and C++ is portability. Different data types might be different sizes on different machines, so the programmer must find out how big those types are when performing operations that are sensitive to size. For example, one computer might store integers in 32 bits, whereas another might store integers as 16 bits. Programs could store larger values in integers on the first machine. As you might imagine, portability is a huge headache for C and C++ programmers.

*Java does not need a sizeof( ) operator for this purpose, because all the data types are the same size on all machines.*You do not need to think about portability on this level—it is designed into the language.

### Default values

When a primitive data type is a member of a class, it is guaranteed to get a default value if you do not initialize it:


| **Primitive type** | **Default**           |
| ------------------ | --------------------- |
| **boolean**        | **false**             |
| **char**           | **‘\u0000’ (null)** |
| **byte**           | **(byte)0**           |
| **short**          | **(short)0**          |
| **int**            | **0**                 |
| **long**           | **0L**                |
| **float**          | **0.0f**              |
| **double**         | **0.0d**              |

## Wrapper Class

All Integer wrapper class must use equals to compare values.

## FlyWeight

IntegerCache

```
-XX:AutoBoxCacheMax = 
```

### The `boolean` Type and boolean Values

The `boolean` type has two values, represented by the *boolean literals* `true` and `false`, formed from ASCII letters.

私有属性

```java
private final boolean value;
```

implements Compare

```java
public static int compare(boolean x, boolean y) {
    return (x == y) ? 0 : (x ? 1 : -1);
}
```

构造器:可传入原始类型或String忽略大小写判断是否为true

```java
 public static boolean parseBoolean(String s) {
        return ((s != null) && s.equalsIgnoreCase("true"));
    }
```

通过valueOf方法始终返回的是静态常量，即同一对象，减少开销

```java
public static Boolean valueOf(boolean b) {
    return (b ? TRUE : FALSE);
}
```

override hashCode()

public static int hashCode(boolean value) {
        return value ? 1231 : 1237;
    }
add logicAnd\logicOr\logicXor methods since 1.8

#### implement by int

### Integer

Cache

属性值：

```java
@Native public static final int   MIN_VALUE = 0x80000000;
@Native public static final int   MAX_VALUE = 0x7fffffff;
//hashCode返回value
private final int value;
@Native public static final int SIZE = 32;
//4bytes
public static final int BYTES = SIZE / Byte.SIZE;
final static char[] digits = {
        '0' , '1' , '2' , '3' , '4' , '5' ,
        '6' , '7' , '8' , '9' , 'a' , 'b' ,
        'c' , 'd' , 'e' , 'f' , 'g' , 'h' ,
        'i' , 'j' , 'k' , 'l' , 'm' , 'n' ,
        'o' , 'p' , 'q' , 'r' , 's' , 't' ,
        'u' , 'v' , 'w' , 'x' , 'y' , 'z'
    };
```
```java
public static int highestOneBit(int i) {
    // HD, Figure 3-1
    i |= (i >>  1);
    i |= (i >>  2);
    i |= (i >>  4);
    i |= (i >>  8);
    i |= (i >> 16);
    return i - (i >>> 1);
}
```
## Float

**Avoid float and double if exact answers are required**.

### BigDecimal

use `compareTo()` rather than `equals()`

`equals()` compares this BigDecimal with the specified Object for equality. Unlike compareTo, this method considers two BigDecimal objects equal only if they are **equal in value and scale** (thus 2.0 is not equal to 2.00 when compared by this method).

```java
@Override
public boolean equals(Object x) {
    if (!(x instanceof BigDecimal))
        return false;
    BigDecimal xDec = (BigDecimal) x;
    if (x == this)
        return true;
    if (scale != xDec.scale) // compare scale
        return false;
    long s = this.intCompact;
    long xs = xDec.intCompact;
    if (s != INFLATED) {
        if (xs == INFLATED)
            xs = compactValFor(xDec.intVal);
        return xs == s;
    } else if (xs != INFLATED)
        return xs == compactValFor(this.intVal);

    return this.inflated().equals(xDec.inflated());
}


public int compareTo(BigDecimal val) {
  // Quick path for equal scale and non-inflated case.
  if (scale == val.scale) {
    long xs = intCompact;
    long ys = val.intCompact;
    if (xs != INFLATED && ys != INFLATED)
      return xs != ys ? ((xs > ys) ? 1 : -1) : 0;
  }
  int xsign = this.signum();
  int ysign = val.signum();
  if (xsign != ysign)
    return (xsign > ysign) ? 1 : -1;
  if (xsign == 0)
    return 0;
  int cmp = compareMagnitude(val);
  return (xsign > 0) ? cmp : -cmp;
}
```
use **BigDecimal(String)**  create object param must be notBlank

### BigInteger

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
