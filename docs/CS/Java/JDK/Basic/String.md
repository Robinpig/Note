## Introduction

The String class represents character strings. All string literals in Java programs are implemented as instances of this class.
**Strings are constant; their values cannot be changed after they are created.**

String is such a class ‐ but this relies on delicate reasoning about benign data races that requires a deep understanding of the Java Memory Model.
String buffers support mutable strings. Because String objects are immutable they can be shared.
Case mapping is based on the Unicode Standard version specified by the Character class.

The Java language provides special support for the string concatenation operator(+), and for conversion of other objects to strings.
String concatenation is implemented through the `StringBuilder`(or `StringBuffer`) class and its append method.
The implementation of the string concatenation operator is left to the discretion of a Java compiler, as long as the compiler ultimately conforms to The Java Language Specification.
For example, the javac compiler may implement the operator with `StringBuffer`, `StringBuilder`, or `java.lang.invoke.StringConcatFactory` depending on the JDK version.
The implementation of string conversion is typically through the method toString, defined by Object and inherited by all classes in Java.

A String represents a string in the **UTF-16** format in which supplementary characters are represented by surrogate pairs (see the section Unicode Character Representations in the Character class for more information).
Index values refer to char code units, so a supplementary character uses two positions in a String.

Avoid strings where other types are more appropriate:

- Strings are poor substitutes for other value types.
- Strings are poor substitutes for enum types.
- Strings are poor substitutes for aggregate types.

## structure

### value

```java
public final class String
    implements java.io.Serializable, Comparable<String>, CharSequence {
    /** The value is used for character storage. */
    private final char value[];

}
```

`From JDK11, value change to byte[] and add byte coder.`

JDK 11中编译后的字节码和JDK 8是不一样的，不再是基于StringBuilder实现，而是基于StringConcatFactory.makeConcatWithConstants动态生成一个方法来实现。这个会比StringBuilder更快，不需要创建StringBuilder对象，也会减少一次数组拷贝
由于是内部使用的数组，用了UNSAFE.allocateUninitializedArray的方式更快分配byte[]数组。通过StringConcatFactory.makeConcatWithConstants而不是JavaC生成代码，是因为生成的代码无法使用JDK的内部方法进行优化，还有就是，如果有算法变化，存量的Lib不需要重新编译，升级新版本JDk就能提速
StringConcatFactory.makeConcatWithConstants是公开API，可以用来动态生成字符串拼接的方法，除了编译器生成字节码调用，也可以直接调用。调用生成方法一次大约需要1微秒（千分之一毫秒）

可以看出，生成的方法是通过如下步骤来实现：
1. StringConcatHelper的mix方法计算长度和字符编码 (将长度和coder组合放到一个long中)
2. 根据长度和编码构造一个byte[]
3. 然后把相关的值写入到byte[]中
4. 使用byte[]无拷贝的方式构造String对象。

这样的实现，和使用StringBuilder相比，减少了StringBuilder以及StringBuilder内部byte[]对象的分配，可以减轻GC的负担。也能避免可能产生的StringBuilder在latin1编码到UTF16时的数组拷贝。
   
StringBuilder缺省编码是LATIN1(ISO_8859_1)，如果append过程中遇到UTF16编码，会有一个将LATIN1转换为UTF16的动作，这个动作实现的方法是inflate。
如果拼接的参数如果是带中文的字符串，使用StringBuilder还会多一次数组拷贝
StringConcatFactory.makeConcatWithConstants是MethodHandles实现的。
MethodHandle可以是一个方法引用，MethodHandles可以对MethodHandle做各种转换，包括过滤参数（filterAgument），参数折叠（foldArgument）、添加参数（insertArguments），最终生成的MethodHandle可以被认为是一个语法树。
MethodHandles API功能强大，甚至可以认为它是图灵完备的。
当然也有缺点，复杂的MethodHandle TreeExpress会生成大量中的中间类，JIT的开销也较大。
   
StringConcatFactory.makeConcatWithConstants通过MethodHandles动态构建一个MethodHandle调用StringConcatHelper的方法，组装一个MethodHandle实现无拷贝的字符拼接实现
   
这种动态生成MethodHandle表达式在参数个数较多时，会遇到问题，它会生成大量中间转换类，并且生成MethodHandle消耗比较大，
极端情况下，C2优化器需要高达2G的内存来编译复杂的字符串拼接 ( https://github.com/openjdk/jdk/pull/18953 )，因此JDK 23引入了JVM启动参数java.lang.invoke.StringConcat.highArityThreshold，缺省值为20，当超过这个阈值时，使用StringBuilder实现
   
除了参数个数较多时编译消耗资源多之外，MethodHandle表达式还有启动速度比较慢的问题

```java
    /** The value is used for character storage. */
    @Stable
    private final byte[] value;

    /**
     * The identifier of the encoding used to encode the bytes in
     * {@code value}. The supported values in this implementation are
     *
     * LATIN1 UTF16
     */
    private final byte coder;
```

This field(value) is trusted by the VM, and is a subject to constant folding if String instance is constant. Overwriting this field after construction will cause problems. Additionally, it is marked with Stable to trust the contents of the array. No other facility in JDK provides this functionality (yet). Stable is safe here, because value is never null.

This field(coder) is trusted by the VM, and is a subject to constant folding if String instance is constant. Overwriting this field after construction will cause problems.

#### compact

```java
    static final boolean COMPACT_STRINGS;

    static {
        COMPACT_STRINGS = true;
    }
```

### hash

String lazily computes the hash code the first time hashCode is called and caches it in a non‐final field.

```java

    /** Cache the hash code for the string */
    private int hash; // Default to 0

    /**
     * Cache if the hash has been calculated as actually being zero, enabling
     * us to avoid recalculating this.
     */
    private boolean hashIsZero; // Default to false;
```

We usually use long or int to replace String in order to reduce network transmission consumption.

#### hashCode

Returns a hash code for this string. The hash code for a String object is computed as:

$$
*s[0]*31^(n-1) + s[1]*31^(n-2) + ... + s[n-1]*

$$

Using int arithmetic, where s[i] is the ith character of the string, n is the length of the string, and ^ indicates exponentiation. (The hash value of the empty string is zero.)

Why use 31?

1. avoid hash collision
2. Easy to calculate
3. The hash is uniform, there is no risk of overflowing like 199

```java
public int hashCode() {
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

#### equals

```java
public boolean equals(Object anObject) {
    if (this == anObject) {
        return true;
    }
    if (anObject instanceof String) {
        String aString = (String)anObject;
        if (!COMPACT_STRINGS || this.coder == aString.coder) {
            return StringLatin1.equals(value, aString.value);
        }
    }
    return false;
}
```

## memory

byte[] = 8+8=16
a String("") = 40 Bytes

byte[]

65534 when compile
Integer.Max in runtime

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

append

```java
public class StringTest {

    public static String concat(String str) {
        return str + "aa"+ "bb";
    }
}
```

JDK8
```

```

JDK9+
```
         1: invokedynamic #7,  0              // InvokeDynamic #0:makeConcatWithConstants:(Ljava/lang/String;)Ljava/lang/String;
```


## StringTable

HashTable size:

1. JDK1.8 60013
2. JDK15 65536

```
-XX:+PrintStringTableStatistics
-XX:StringTableSize=N
```

```shell
jcmd <pid> VM.stringtable
```

### intern

```cpp
// jvm.cpp
JVM_ENTRY(jstring, JVM_InternString(JNIEnv *env, jstring str))
  JVMWrapper("JVM_InternString");
  JvmtiVMObjectAllocEventCollector oam;
  if (str == NULL) return NULL;
  oop string = JNIHandles::resolve_non_null(str);
  oop result = StringTable::intern(string, CHECK_NULL); // intern
  return (jstring) JNIHandles::make_local(env, result);
JVM_END

// stringTable.cpp
// Interning
oop StringTable::intern(Symbol* symbol, TRAPS) {
  if (symbol == NULL) return NULL;
  ResourceMark rm(THREAD);
  int length;
  jchar* chars = symbol->as_unicode(length);
  Handle string;
  oop result = intern(string, chars, length, CHECK_NULL);
  return result;
}


oop StringTable::intern(Handle string_or_null_h, const jchar* name, int len, TRAPS) {
  // shared table always uses java_lang_String::hash_code
  unsigned int hash = java_lang_String::hash_code(name, len);
  oop found_string = StringTable::the_table()->lookup_shared(name, len, hash);
  if (found_string != NULL) {
    return found_string;
  }
  if (StringTable::_alt_hash) {
    hash = hash_string(name, len, true);
  }
  return StringTable::the_table()->do_intern(string_or_null_h, name, len,
                                             hash, CHECK_NULL);
}
```

#### do_intern

```cpp
oop StringTable::do_intern(Handle string_or_null_h, const jchar* name,
                           int len, uintx hash, TRAPS) {
  HandleMark hm(THREAD);  // cleanup strings created
  Handle string_h;

  if (!string_or_null_h.is_null()) {
    string_h = string_or_null_h;
  } else {
    string_h = java_lang_String::create_from_unicode(name, len, CHECK_NULL);
  }
```

**Deduplicate the string before it is interned.**
Note that we should never deduplicate a string after it has been interned.
Doing so will counteract compiler optimizations done on e.g. interned string literals.

```cpp
  Universe::heap()->deduplicate_string(string_h());

  assert(java_lang_String::equals(string_h(), name, len),
         "string must be properly initialized");
  assert(len == java_lang_String::length(string_h()), "Must be same length");

  StringTableLookupOop lookup(THREAD, hash, string_h);
  StringTableGet stg(THREAD);

  bool rehash_warning;
  do {
    if (_local_table->get(THREAD, lookup, stg, &rehash_warning)) {
      update_needs_rehash(rehash_warning);
      return stg.get_res_oop();
    }
    WeakHandle<vm_string_table_data> wh = WeakHandle<vm_string_table_data>::create(string_h);
    // The hash table takes ownership of the WeakHandle, even if it's not inserted.
    if (_local_table->insert(THREAD, lookup, wh, &rehash_warning)) {
      update_needs_rehash(rehash_warning);
      return wh.resolve();
    }
  } while(true);
}
```

## String Deduplication

[JEP 192: String Deduplication in G1](http://openjdk.java.net/jeps/192)

### is_candidate

`G1ParScanThreadState::copy_to_survivor_space()` -> `G1StringDedup::is_candidate_from_evacuation()`

Candidate selection policy for young/mixed GC.

- If to is young then age should be the new (survivor's) age.
- if to is old then age should be the age of the copied from object.

```cpp
  // G1StringDedup
  static bool is_candidate_from_evacuation(const Klass* klass,
                                           G1HeapRegionAttr from,
                                           G1HeapRegionAttr to,
                                           uint age) {
    return StringDedup::is_enabled_string(klass) &&
           from.is_young() &&
           (to.is_young() ?
            StringDedup::is_threshold_age(age) :
            StringDedup::is_below_threshold_age(age));
  }
```

`G1FullGCMarker::mark_object()` -> `G1StringDedup::is_candidate_from_mark()`

Candidate if string is being evacuated from young to old but has not reached the deduplication age threshold,
i.e. has not previously been a candidate during its life in the young generation.

```cpp
// G1StringDedup
static bool G1StringDedup::is_candidate_from_mark(oop java_string) {
  return G1CollectedHeap::heap()->heap_region_containing(java_string)->is_young() &&
         StringDedup::is_below_threshold_age(java_string->age());
}
```

### deduplicate

```cpp

void StringDedup::Table::deduplicate(oop java_string) {
  assert(java_lang_String::is_instance(java_string), "precondition");
  _cur_stat.inc_inspected();
  if ((StringTable::shared_entry_count() > 0) &&
      try_deduplicate_shared(java_string)) {
    return;                     // Done if deduplicated against shared StringTable.
  }
  typeArrayOop value = java_lang_String::value(java_string);
  uint hash_code = compute_hash(value);
  TableValue tv = find(value, hash_code);
  if (tv.is_empty()) {
    // Not in table.  Create a new table entry.
    install(value, hash_code);
  } else {
    _cur_stat.inc_known();
    typeArrayOop found = cast_from_oop<typeArrayOop>(tv.resolve());
    assert(found != nullptr, "invariant");
    // Deduplicate if value array differs from what's in the table.
    if (found != value) {
      if (deduplicate_if_permitted(java_string, found)) {
        _cur_stat.inc_deduped(found->size() * HeapWordSize);
      } else {
        // If string marked deduplication_forbidden then we can't update its
        // value.  Instead, replace the array in the table with the new one,
        // as java_string is probably in the StringTable.  That makes it a
        // good target for future deduplications as it is probably intended
        // to live for some time.
        tv.replace(value);
        _cur_stat.inc_replaced();
      }
    }
  }
}
```

### Example

```java
 /**
 * -Xmx256M -XX:+UseG1GC -XX:+PrintGCDetails -XX:+PrintGCTimeStamps
 * 
 * -XX:+UseStringDeduplication -XX:+PrintStringDeduplicationStatistics
 */
public class Main {
 
  private static final LinkedList<String> strings = new LinkedList<>();

  public static void main(String[] args) throws InterruptedException {
    int iteration = 0;
    while (true) {
      for (int i = 0; i < 100; i++) {
        for (int j = 0; j < 10; j++) {
          strings.add(new String("String " + j));
        }
      }
      iteration++;
      System.out.println("Survived Iteration: " + iteration);
      TimeUnit.MILLISECONDS.sleep(100);
    }
  }
}
```

String#intern() cache String instances

Deduplication remove char/byte array from String instances cache

## Methods

Enahncements:

- JDK9
  - [JDK-8058779 : Faster implementation of String.replace(CharSequence, CharSequence)](https://bugs.java.com/bugdatabase/view_bug.do?bug_id=8058779)


## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References
