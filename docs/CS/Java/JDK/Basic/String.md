## Introduction

*The **String class represents character strings. All string literals in Java programs are implemented as instances of this class**.*
  `Strings are constant; their values cannot be changed after they are created. `

*String buffers support mutable strings. Because String objects are immutable they can be shared.* 

*Case mapping is **based on the Unicode Standard version specified by the Character class**.*
*The Java language provides special support for the string concatenation operator ( + ), and for conversion of other objects to strings. **String concatenation is implemented through the StringBuilder(or StringBuffer) class and its append method**.*

*A String represents a string in the **UTF-16** format in which supplementary characters are represented by surrogate pairs (see the section Unicode Character Representations in the Character class for more information). Index values refer to char code units, so a supplementary character uses two positions in a String.*




```java
public final class String
    implements java.io.Serializable, Comparable<String>, CharSequence {
    /** The value is used for character storage. */
    private final char value[];

    /** Cache the hash code for the string */
    private int hash; // Default to 0
  //...
}
```




`From JDK11, value change to byte[].`

The value is used for character storage.
Implementation Note:
This field is trusted by the VM, and is a subject to constant folding if String instance is constant. Overwriting this field after construction will cause problems. Additionally, it is marked with Stable to trust the contents of the array. No other facility in JDK provides this functionality (yet). Stable is safe here, because value is never null.

```java
public final class String
    implements java.io.Serializable, Comparable<String>, CharSequence,
               Constable, ConstantDesc {

    /**
     * The value is used for character storage.
     *
     * @implNote This field is trusted by the VM, and is a subject to
     * constant folding if String instance is constant. Overwriting this
     * field after construction will cause problems.
     *
     * Additionally, it is marked with {@link Stable} to trust the contents
     * of the array. No other facility in JDK provides this functionality (yet).
     * {@link Stable} is safe here, because value is never null.
     */
    @Stable
    private final byte[] value;

/**
 * The identifier of the encoding used to encode the bytes in
 * {@code value}. The supported values in this implementation are
 *
 * LATIN1
 * UTF16
 *
 * @implNote This field is trusted by the VM, and is a subject to
 * constant folding if String instance is constant. Overwriting this
 * field after construction will cause problems.
 */
private final byte coder;

/** Cache the hash code for the string */
private int hash; // Default to 0

/**
 * Cache if the hash has been calculated as actually being zero, enabling
 * us to avoid recalculating this.
 */
private boolean hashIsZero; // Default to false;
...     
}
```



We usually use long or int to replace String in order to reduce
network transmission consumption.

## API





首先字符串的内容是由一个字符数组 char[] 来存储的，由于数组的长度及索引是整数，且String类中返回字符串长度的方法length() 的返回值也是int ，所以通过查看java源码中的类Integer我们可以看到Integer的最大范围是2^31 -1,由于数组是从0开始的，所以数组的最大长度可以使【0~2^31-1】通过计算是大概4GB。

但是通过翻阅java虚拟机手册对class文件格式的定义以及常量池中对String类型的结构体定义我们可以知道对于索引定义了u2，就是无符号占2个字节，2个字节可以表示的最大范围是2^16 -1 = 65535。
其实是65535，但是由于JVM需要1个字节表示结束指令，所以这个范围就为65534了。超出这个范围在编译时期是会报错的，但是运行时拼接或者赋值的话范围是在整形的最大范围。



### hashCode



*Returns a hash code for this string. The hash code for a String object is computed as*

       *s[0]*31^(n-1) + s[1]*31^(n-2) + ... + s[n-1]*


*using int arithmetic, where s[i] is the ith character of the string, n is the length of the string, and ^ indicates exponentiation. (The hash value of the empty string is zero.)*

Why use 31?

1. 碰撞概率小
2. 计算方便
3. 散列均匀,不会有199这样会溢出的风险

```java
public int hashCode() {
    // The hash or hashIsZero fields are subject to a benign data race,
    // making it crucial to ensure that any observable result of the
    // calculation in this method stays correct under any possible read of
    // these fields. Necessary restrictions to allow this to be correct
    // without explicit memory fences or similar concurrency primitives is
    // that we can ever only write to one of these two fields for a given
    // String instance, and that the computation is idempotent and derived
    // from immutable state
    int h = hash;
    if (h == 0 && !hashIsZero) {
        h = isLatin1() ? StringLatin1.hashCode(value)
                       : StringUTF16.hashCode(value);
        if (h == 0) {
            hashIsZero = true;
        } else {
            hash = h;
        }
    }
    return h;
}
```

 



## StringBuilder



Reuse StringBuilder object if not know the length new stringBuilder 

```java
public void setLength(int newLength) {
    if (newLength < 0)
        throw new StringIndexOutOfBoundsException(newLength);
    ensureCapacityInternal(newLength);

    if (count < newLength) {
        Arrays.fill(value, count, newLength, '\0');
    }

    count = newLength;
}
```



```java
public AbstractStringBuilder delete(int start, int end) {
    if (start < 0)
        throw new StringIndexOutOfBoundsException(start);
    if (end > count)
        end = count;
    if (start > end)
        throw new StringIndexOutOfBoundsException();
    int len = end - start;
    if (len > 0) {
        System.arraycopy(value, start+len, value, start, count-end);
        count -= len;
    }
    return this;
}
```