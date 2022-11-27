## Introduction

“Before generic classes were added to Java, generic programming was achieved with inheritance.
The ArrayList class simply maintained an array of Object references:

```java
public class ArrayList // before generic classes
{
    private Object[] elementData;

    public Object get(int i) { //... 
    /}

    public void add(Object o) { //...
        // }
    }
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

This call compiles and runs without error. Elsewhere, casting the result of get to a String will cause an error.
Generics offer a better solution: type parameters. The ArrayList class now has a type parameter that indicates the element type:

```java
var files = new ArrayList<String>();
```

This makes your code easier to read. You can tell right away that this particular array list contains String objects.

Generics means parameterized types.

The idea is to allow type (Integer, String, … etc, and user-defined types) to be a parameter to methods, classes, and interfaces. Using Generics, it is possible to create classes that work with different data types.

An entity such as class, interface, or method that operates on a parameterized type is called generic entity.

Object is the superclass of all other classes and Object reference can refer to any type object. These features lack type safety. Generics adds that type safety feature. We will discuss that type safety feature in later examples.

Generics in Java is similar to templates in C++. For example, classes like HashSet, ArrayList, HashMap, etc use generics very well. There are some fundamental differences between the two approaches to generic types.

How to implement generics?

- Code specialization
- Code sharing

`C++ and C# use Code specialization while Java use Code sharing.`

> “In layman,s term, generics force type safety in java language.”
>
> “Generics add stability to your code by making more of your bugs detectable at compile time.”

In the heart of generics is “[**type safety**](https://en.wikipedia.org/wiki/Type_safety)“.
What exactly is type safety? It’s just a guarantee by compiler that if correct Types are used in correct places then there should not be any `ClassCastException` in runtime.
A usecase can be list of `Integer` i.e. `List<Integer>`. If you declare a list in java like `List<Integer>`, then java guarantees that it will detect and report you any attempt to insert any non-integer type into above list.

Another important term in java generics is “[**type erasure**](https://en.wikipedia.org/wiki/Type_erasure)“.
It essentially means that all the extra information added using generics into source code will be removed from bytecode generated from it.
Inside bytecode, it will be old java syntax which you will get if you don’t use generics at all. This necessarily helps in generating and executing code written prior to java 5 when generics were not added in language.

## Type Erasure

Whenever you define a generic type, a corresponding raw type is automatically provided. The name of the raw type is simply the name of the generic type, with the type parameters removed.
The type variables are erased and replaced by their bounding types (or Object for variables without bounds).

Type erasure is a mapping from types (possibly including parameterized types and type variables) to types (that are never parameterized types or type variables).
We write |T| for the erasure of type T. The erasure mapping is defined as follows:

- The erasure of a parameterized type ([§4.5](https://docs.oracle.com/javase/specs/jls/se8/html/jls-4.html#jls-4.5)) G`<`T1,...,Tn`>` is |G|.
- The erasure of a nested type T`.`C is |T|.C.
- The erasure of an array type T`[]` is |T|`[]`.
- The erasure of a type variable ([§4.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-4.html#jls-4.4)) is the erasure of its leftmost bound.
- The erasure of every other type is the type itself.

Type erasure also maps the signature ([§8.4.2](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.2)) of a constructor or method to a signature that has no parameterized types or type variables.
The erasure of a constructor or method signature s is a signature consisting of the same name as s and the erasures of all the formal parameter types given in s.

The return type of a method ([§8.4.5](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.5)) and the type parameters of a generic method or constructor ([§8.4.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.4), [§8.8.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.8.4)) also undergo erasure if the method or constructor's signature is erased.

The erasure of the signature of a generic method has no type parameters.

generics not exist in JVM,only have List.class not List<Integer>.class

## Type Expression

Usually Parameters :

- E - Element  use in Collection
- T - Type
- K - Key in Map
- V - Value in Map
- ? - Type not sure

## Restrictions and Limitations

In the following sections, I discuss a number of restrictions that you need to consider when working with Java generics.
Most of these restrictions are a consequence of type erasure.

Type Parameters Cannot Be Instantiated with Primitive Types

You cannot substitute a primitive type for a type parameter. Thus, there is no Pair<double>, only Pair<Double>.
The reason is, of course, type erasure. After erasure, the Pair class has fields of type Object, and you can’t use them to store double values.
This is an annoyance, to be sure, but it is consistent with the separate status of primitive types in the Java language. 
It is not a fatal flaw—there are only eight primitive types, and you can always handle them with separate classes and methods when wrapper types are not an acceptable substitute.

Runtime Type Inquiry Only Works with Raw Types

Objects in the virtual machine always have a specific nongeneric type. 
Therefore, all type inquiries yield only the raw type. 
For example,

```
if (a instanceof Pair<String>) // ERROR
```

could only test whether a is a Pair of any type. The same is true for the test

```
if (a instanceof Pair<T>) // ERROR
```

or the cast

```

Pair<String> p = (Pair<String>) a; // warning--can only test that a is a Pair
```

To remind you of the risk, you will get a compiler error (with instanceof) or warning (with casts) when you try to inquire whether an object belongs to a generic type.
In the same spirit, the getClass method always returns the raw type. 
For example:

```
Pair<String> stringPair = . . .;
Pair<Employee> employeePair = . . .;
if (stringPair.getClass() == employeePair.getClass()) // they are equal
```

The comparison yields true because both calls to getClass return Pair.class.

You cannot instantiate arrays of parameterized types, such as

```
var table = new Pair<String>[10]; // ERROR”
```

You cannot use type variables in an expression such as new T(. . .).
For example, the following Pair<T> constructor is illegal:

```
public Pair() { first = new T(); second = new T(); } // ERROR”
```

Just as you cannot instantiate a single generic instance, you cannot instantiate an array.
The reasons are different—an array is, after all, filled with null values, which would seem safe to construct.
But an array also carries a type, which is used to monitor array stores in the virtual machine.
That type is erased.

Type Variables Are Not Valid in Static Contexts of Generic Classes

You Cannot Throw or Catch Instances of a Generic Class

You can neither throw nor catch objects of a generic class. In fact, it is not even legal for a generic class to extend Throwable.
For example, the following definition will not compile:

```
public class Problem<T> extends Exception { /* . . . */ }
      // ERROR--can't extend Throwable
```

You cannot use a type variable in a catch clause. For example, the following method will not compile:

```java
    public static <T extends Throwable> void doWork(Class<T> t) {
        try {
            do work
        } catch (T e) // ERROR--can't catch type variable
        {
            Logger.global.info(. . .);
        }
    }
```

However, it is OK to use type variables in exception specifications. The following method is legal:

```java
    public static <T extends Throwable> void doWork(T t) throws T // OK
    {
        try {
            do work
        } catch (Throwable realCause) {
            t.initCause(realCause);
            throw t;
        }
    }
```

You Can Defeat Checked Exception Checking

A bedrock principle of Java exception handling is that you must provide a handler for all checked exceptions.
You can use generics to defeat this scheme. The key ingredient is this method:

```
SuppressWarnings("unchecked")
static <T extends Throwable> void throwAs(Throwable t) throws T{      
    throw (T) t;
}
```

## Valhalla

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
