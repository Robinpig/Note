## Introduction

Before generic classes were added to Java, generic programming was achieved with inheritance.
The `ArrayList` class simply maintained an array of `Object` references:

```java
public class ArrayList // before generic classes
{
    private Object[] elementData;

    public Object get(int i) { /* ... */ }

    public void add(Object o) { /* ... */ }
}
```

This approach has two problems. A cast is necessary whenever you retrieve a value:

```java
ArrayList files = new ArrayList();
String filename = (String) files.get(0);
```

Moreover, there is no error checking. You can add values of any class:

```java
files.add(new File("..."));
```

This call compiles and runs without error. Elsewhere, casting the result of `get` to a `String` will cause a `ClassCastException`.
Generics offer a better solution: type parameters. The `ArrayList` class now has a type parameter that indicates the element type:

```java
var files = new ArrayList<String>();
```

This makes your code easier to read. You can tell right away that this particular array list contains `String` objects.

Generics means parameterized types — allowing a type (`Integer`, `String`, … and user-defined types) to be a parameter to methods, classes, and interfaces.
The idea is similar to templates in C++, but **Java uses type erasure (code sharing) while C++ and C# use code specialization** — a single erased class backs all instantiations.

> At the heart of generics is **type safety**: the compiler guarantees that if correct types are used in correct places, there should be no `ClassCastException` at runtime.
> A use case: declaring `List<Integer>` lets the compiler detect and report any attempt to insert a non-`Integer` value.

## Type Erasasure

Whenever you define a generic type, a corresponding raw type is automatically provided. The name of the raw type is simply the name of the generic type, with the type parameters removed.
The type variables are erased and replaced by their bounding types (or `Object` for variables without bounds).

Type erasure is a mapping from types (possibly including parameterized types and type variables) to types (that are never parameterized types or type variables).
We write `|T|` for the erasure of type `T`. The erasure mapping is defined as follows (JLS 4.6):

- The erasure of a parameterized type `G<T1,...,Tn>` is `|G|`.
- The erasure of a nested type `T.C` is `|T|.C`.
- The erasure of an array type `T[]` is `|T|[]`.
- The erasure of a type variable is the erasure of its leftmost bound.
- The erasure of every other type is the type itself.

Type erasure also maps the signature of a constructor or method to a signature that has no parameterized types or type variables.
Generics do not exist in the JVM — there is only `List.class`, never `List<Integer>.class`.

```java
// after erasure, both are the same class
List<String>  a = new ArrayList<>();
List<Integer> b = new ArrayList<>();
System.out.println(a.getClass() == b.getClass()); // true: both ArrayList.class
```

## Type Parameters and Bounds

A type variable can be bounded to constrain the allowed replacements:

```java
public class Pair<T extends Comparable<T> & Serializable> {
    // T must implement Comparable<T> AND be Serializable
}
```

Multiple bounds are allowed; the first bound (a class, if present) becomes the erasure target, the rest must be interfaces.
If no bound is given, the erasure target is `Object`.

## Wildcards

Wildcards (`?`) express family relationships between parameterized types:

- **Unbounded**: `List<?>` — a list of unknown element type, can only read as `Object`, cannot add (except `null`).
- **Upper bound**: `List<? extends Number>` — producer of `Number` (read as `Number`).
- **Lower bound**: `List<? super Integer>` — consumer of `Integer` (can add `Integer` and subtypes).

```java
List<? extends Number>  src = List.of(1, 2.0);
Number n = src.get(0);          // OK: anything is a Number
// src.add(3);                   // ERROR: type unknown

List<? super Integer> dst = new ArrayList<Number>();
dst.add(3);                      // OK: Integer is acceptable
// Number m = dst.get(0);        // ERROR: only known to be Object
```

## PECS Principle

From *Effective Java* (Joshua Bloch): **P**roducer **E**xtends, **C**onsumer **S**uper.

- Use `<? extends T>` for a parameter that **produces** `T` (you only read from it).
- Use `<? super T>` for a parameter that **consumes** `T` (you only write to it).

```java
// copy produces from src, consumes into dst
public static <T> void copy(List<? super T> dst, List<? extends T> src) {
    for (T item : src) dst.add(item);
}
```

`Collections.max` is the canonical producer example: `public static <T extends Object & Comparable<? super T>> T max(Collection<? extends T> coll)`.
The `? super T` bound on `Comparable` is what lets `List<Integer>` be compared even though `Integer implements Comparable<Integer>` directly.

## Generic Methods

A method can declare its own type variables, independent of the enclosing class:

```java
public static <T> T[] toArray(Collection<T> c, T[] a) { /* ... */ }
```

Type arguments are usually inferred from the actual arguments, so callers write `toArray(list, new String[0])` without `<String>`.
Explicit type witnesses (`ClassName.<String>method(...)`) are only needed when no argument carries the type.

## Bridge Methods

Type erasure introduces a subtle consequence: **the JVM needs bridge methods to preserve overriding semantics** when a generic method overrides a non-generic (erased) one.

```java
class Node<T> {
    public void setData(T data) { /* ... */ }
}
class IntNode extends Node<Integer> {
    @Override public void setData(Integer data) { /* ... */ }
}
```

After erasure, `Node.setData(Object)` exists in the parent, but `IntNode` only overrode `setData(Integer)`.
The compiler synthesizes a bridge:

```java
// compiler-generated bridge in IntNode
public void setData(Object data) { setData((Integer) data); }
```

Bridge methods are `ACC_BRIDGE | ACC_SYNTHETIC` in the bytecode and are invisible to source code.
They are the reason `method.getReturnType()` can differ from the erased signature you wrote, and why generics cannot be distinguished by the runtime.

## Restrictions and Limitations

Most of these restrictions are a consequence of type erasure.

### Cannot Instantiate with Primitive Types
There is no `Pair<double>`, only `Pair<Double>`. After erasure, fields are of type `Object`, which cannot hold a `double`.

### Runtime Type Inquiry Only Works with Raw Types

```java
if (a instanceof Pair<String>)  // ERROR
if (a instanceof Pair<T>)       // ERROR
Pair<String> p = (Pair<String>) a; // unchecked warning
```

`a.getClass()` always returns the raw type `Pair.class`.

### Cannot Instantiate Arrays of Parameterized Types

```java
var table = new Pair<String>[10]; // ERROR
```

An array carries a reified component type used by the VM to check stores; that type is erased for generics.

### Type Variables Not Valid in Static Contexts
You cannot use a type variable in a static field or method of a generic class, because there is no `this` type at class level.

### Cannot Throw or Catch Generic Class Instances

```java
public class Problem<T> extends Exception { /* ERROR -- can't extend Throwable */ }
```

But a type variable is allowed in a `throws` clause (`throws T`), which is how `Throwable` helper methods rethrow checked exceptions as unchecked.

## Valhalla and Specialization

Project Valhalla aims to lift the "one erased class" limitation via **reified generics / specialization** (distinct class files per primitive specialization, e.g. `List<int>` with flattened layout).
As of JDK 25 this remains a preview/experimental effort — see [Valhalla](/docs/CS/Java/JDK/Valhalla.md) for the current status.
The current language still relies entirely on erasure described above.

## Links

- [Java basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Valhalla](/docs/CS/Java/JDK/Valhalla.md)
- [Collections](/docs/CS/Java/JDK/Collection/Collection.md)

## References

1. [The Java Language Specification, Chapter 4 (Types, Values, and Variables)](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html)
2. [JLS 4.6 (Type Erasure)](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.6)
3. [Bloch, J. Effective Java, 3rd Ed. — Item 31: Use bounded wildcards to increase API flexibility](https://www.oreilly.com/library/view/effective-java-3rd/9780134686097/)
