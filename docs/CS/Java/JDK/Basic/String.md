## Introduction
*The **String class represents character strings. All string literals in Java programs are implemented as instances of this class**.*
**Strings are constant; their values cannot be changed after they are created.**

String is such a class ‐ but this relies on delicate reasoning about benign data races that requires a deep understanding of the Java Memory Model.

*String buffers support mutable strings. Because String objects are immutable they can be shared.* 

Case mapping is **based on the Unicode Standard version specified by the Character class**.
The Java language provides special support for the string concatenation operator ( + ), and for conversion of other objects to strings. **String concatenation is implemented through the StringBuilder(or StringBuffer) class and its append method**.

A String represents a string in the **UTF-16** format in which supplementary characters are represented by surrogate pairs (see the section Unicode Character Representations in the Character class for more information). Index values refer to char code units, so a supplementary character uses two positions in a String.


The implementation of the string concatenation operator is left to the discretion of a Java compiler, as long as the compiler ultimately conforms to The Java Language Specification. For example, the javac compiler may implement the operator with `StringBuffer`, `StringBuilder`, or `java.lang.invoke.StringConcatFactory` depending on the JDK version. The implementation of string conversion is typically through the method toString, defined by Object and inherited by all classes in Java.

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

    /**
     * If String compaction is disabled, the bytes in {@code value} are
     * always encoded in UTF16.
     *
     * For methods with several possible implementation paths, when String
     * compaction is disabled, only one code path is taken.
     *
     * The instance field value is generally opaque to optimizing JIT
     * compilers. Therefore, in performance-sensitive place, an explicit
     * check of the static boolean {@code COMPACT_STRINGS} is done first
     * before checking the {@code coder} field since the static boolean
     * {@code COMPACT_STRINGS} would be constant folded away by an
     * optimizing JIT compiler. The idioms for these cases are as follows.
     *
     * For code such as:
     *
     *    if (coder == LATIN1) { ... }
     *
     * can be written more optimally as
     *
     *    if (coder() == LATIN1) { ... }
     *
     * or:
     *
     *    if (COMPACT_STRINGS && coder == LATIN1) { ... }
     *
     * An optimizing JIT compiler can fold the above conditional as:
     *
     *    COMPACT_STRINGS == true  => if (coder == LATIN1) { ... }
     *    COMPACT_STRINGS == false => if (false)           { ... }
     *
     * @implNote
     * The actual value for this field is injected by JVM. The static
     * initialization block is used to set the value here to communicate
     * that this static final field is not statically foldable, and to
     * avoid any possible circular dependency during vm initialization.
     */
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
*Returns a hash code for this string. The hash code for a String object is computed as*

       *s[0]*31^(n-1) + s[1]*31^(n-2) + ... + s[n-1]*

*using int arithmetic, where s[i] is the ith character of the string, n is the length of the string, and ^ indicates exponentiation. (The hash value of the empty string is zero.)*

Why use 31?

1. avoid hash collision
2. Easy to calculate
3. The hash is uniform, there is no risk of overflowing like 199



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

#### equals
```java
    /**
     * Compares this string to the specified object.  The result is {@code
     * true} if and only if the argument is not {@code null} and is a {@code
     * String} object that represents the same sequence of characters as this
     * object.
     *
     * <p>For finer-grained String comparison, refer to
     * {@link java.text.Collator}.
     *
     * @param  anObject
     *         The object to compare this {@code String} against
     *
     * @return  {@code true} if the given object represents a {@code String}
     *          equivalent to this string, {@code false} otherwise
     *
     * @see  #compareTo(String)
     * @see  #equalsIgnoreCase(String)
     */
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



## String Pool



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

oop StringTable::do_intern(Handle string_or_null_h, const jchar* name,
                           int len, uintx hash, TRAPS) {
  HandleMark hm(THREAD);  // cleanup strings created
  Handle string_h;

  if (!string_or_null_h.is_null()) {
    string_h = string_or_null_h;
  } else {
    string_h = java_lang_String::create_from_unicode(name, len, CHECK_NULL);
  }

  // Deduplicate the string before it is interned. Note that we should never
  // deduplicate a string after it has been interned. Doing so will counteract
  // compiler optimizations done on e.g. interned string literals.
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



HashTable 

1. JDK1.8 60013
2. JDK15 65536



```
-XX:+PrintStringTableStatistics
-XX:StringTableSize=N
```

```shell
jcmd <pid> VM.stringtable
```



## String Deduplication

[JEP 192: String Deduplication in G1](http://openjdk.java.net/jeps/192)

call `G1StringDedup::enqueue_from_evacuation()` when `G1ParScanThreadState::copy_to_survivor_space()`
call `G1StringDedup::enqueue_from_mark()` when `G1FullGCMarker::mark_object()`

```cpp
// g1StringDedup.cpp
void G1StringDedup::enqueue_from_evacuation(bool from_young, bool to_young, uint worker_id, oop java_string) {
  assert(is_enabled(), "String deduplication not enabled");
  if (is_candidate_from_evacuation(from_young, to_young, java_string)) {
    G1StringDedupQueue::push(worker_id, java_string);
  }
}

bool G1StringDedup::is_candidate_from_evacuation(bool from_young, bool to_young, oop obj) {
  if (from_young && java_lang_String::is_instance_inlined(obj)) {
    if (to_young && obj->age() == StringDeduplicationAgeThreshold) {
      // Candidate found. String is being evacuated from young to young and just
      // reached the deduplication age threshold.
      return true;
    }
    if (!to_young && obj->age() < StringDeduplicationAgeThreshold) {
      // Candidate found. String is being evacuated from young to old but has not
      // reached the deduplication age threshold, i.e. has not previously been a
      // candidate during its life in the young generation.
      return true;
    }
  }

  // Not a candidate
  return false;
}


void G1StringDedup::enqueue_from_mark(oop java_string, uint worker_id) {
  assert(is_enabled(), "String deduplication not enabled");
  if (is_candidate_from_mark(java_string)) {
    G1StringDedupQueue::push(worker_id, java_string);
  }
}

bool G1StringDedup::is_candidate_from_mark(oop obj) {
  if (java_lang_String::is_instance_inlined(obj)) {
    bool from_young = G1CollectedHeap::heap()->heap_region_containing(obj)->is_young();
    if (from_young && obj->age() < StringDeduplicationAgeThreshold) {
      // Candidate found. String is being evacuated from young to old but has not
      // reached the deduplication age threshold, i.e. has not previously been a
      // candidate during its life in the young generation.
      return true;
    }
  }

  // Not a candidate
  return false;
}
```

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

String#intern() cache instance of String
Deduplication remove cache of char/byte array in String instance