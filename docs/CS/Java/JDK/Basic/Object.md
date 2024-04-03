## Introduction

**What is an Object?**<br>
An object is a software bundle of related state and behavior. Software objects are often used to model the real-world objects that you find in everyday life.

**What Is a Class?**<br>
A class is a blueprint or prototype from which objects are created.

**What Is Inheritance?**<br>
Inheritance provides a powerful and natural mechanism for organizing and structuring your software.

**What Is an Interface?**<br>
An interface is a contract between a class and the outside world. When a class implements an interface, it promises to provide the behavior published by that interface.

## What is an Object?

> “We cut nature up, organize it into concepts, and ascribe significances as we do, largely because we are parties to an agreement that holds throughout our speech community and is codified in the patterns of our language ... we cannot talk at all except by subscribing to the organization and classification of data which the agreement decrees.” Benjamin Lee Whorf (1897-1941)

Alan Kay summarized five basic characteristics of SmallTalk, the first successful object-oriented language and a language that inspired Java.
These characteristics represent a pure approach to object-oriented programming:

- **Everything is an object**
- **A program is a bunch of objects telling each other what to do by sending messages**
- **Each object has its own memory made up of other objects**
- **Every object has a type**
- **All objects of a particular type can receive the same messages**

Grady Booch offers an even more succinct description of an object:

> *An object has state, behavior and identity.*

This means that an object can have internal data (which gives it state), methods (to produce behavior), and each object can be uniquely distinguished from every other object—to put this in a concrete sense, each object has a unique address in memory.

### Access Control

We can break up the playing field into class creators (those who create new data types) and client programmers (the class consumers who use the data types in their applications).
The goal of the client programmer is to collect a toolbox full of classes to use for rapid application development.
The goal of the class creator is to build a class that exposes only what’s necessary to the client programmer and keeps everything else hidden.<br>
Why? Because if it’s hidden, the client programmer can’t access it, which means the class creator can change the hidden portion at will without worrying about the impact on anyone else.
The hidden portion usually represents the tender insides of an object that could easily be corrupted by a careless or uninformed client programmer, so hiding the implementation reduces program bugs.

All relationships need boundaries, respected by all parties involved.
When you create a library, you establish a relationship with the client programmer, who is also a programmer, but one who is putting together an application by using your library, possibly to build a bigger library.
If all members of a class are available to everyone, the client programmer can do anything with that class and there’s no way to enforce rules.
Even though you might prefer that the client programmer not directly manipulate some of the members of your class, without access control there’s no way to prevent it.
Everything’s naked to the world.

- The first reason for access control is to keep client programmers’ hands off portions they shouldn’t touch—parts that are necessary for the internal operation of the data type but not part of the interface that users need in order to solve their particular problems.
- The second reason for access control is to enable the library designer to change the internal workings of the class without worrying about how it will affect the client programmer.

Java uses three explicit keywords to set the boundaries in a class: **public**, **private**, and **protected**. Their use and meaning are quite straightforward. These *access specifiers* determine who can use the definitions that follow.

- **public** means the following element is available to everyone.
- The **private** keyword, on the other hand, means that no one can access that element except you, the creator of the type, inside methods of that type. **private** is a brick wall between you and the client programmer. Someone who tries to access a **private** member will get a compile-time error.
- The **protected** keyword acts like **private**, with the exception that an inheriting class has access to **protected** members, but not **private** members. Hierarchy will be introduced shortly.
- Java also has a “**default**” access, which comes into play if you don’t use one of the aforementioned specifiers. This is usually called ***package* *access*** because classes can access the members of other classes in the same package, but outside of the package those same members appear to be **private**.

Java object identifiers are *actually* “object references.” **And everything is actually pass by value**. So you’re not passing by reference, you’re “passing an object reference by value.

### Inheritance

#### 'this' pointer

To understand ‘this’ pointer, it is important to know how objects look at functions and data members of a class.

1. Each object gets its own copy of the data member.
2. All-access the same function definition as present in the code segment.

Meaning each object gets its own copy of data members and all objects share a single copy of member functions.
Then now question is that if only one copy of each member function exists and is used by multiple objects, how are the proper data members are accessed and updated?

The compiler supplies an implicit pointer along with the names of the functions as ‘this’.
The ‘this’ pointer is passed as a hidden argument to all nonstatic member function calls and is available as a local variable within the body of all nonstatic functions.
‘this’ pointer is not available in static member functions as static member functions can be called without any object (with class name).

Most of the time, you will not need to access it directly, but you can if needed.
It’s worth noting that “this” is a const pointer -- you can change the value of the underlying object it points to, but you can not make it point to something else!
By having functions that would otherwise return void return *this instead, you can make those functions chainable.

### Polymorphism

To solve the problem, object-oriented languages use the concept of *late binding*.
When you send a message to an object, the code called isn’t determined until run time.
The compiler does ensure that the method exists and performs type checking on the arguments and return value, but it doesn’t know the exact code to execute.

To perform late binding, Java uses a special bit of code in lieu of the absolute call.
This code calculates the address of the method body, using information stored in the object.
Thus, each object behaves differently according to the contents of that special bit of code.
When you send a message to an object, the object actually does figure out what to do with that message.

In some languages you must explicitly grant a method the flexibility of late-binding properties.
For example, C++ uses the *virtual* keyword.
In such languages, methods are not dynamically bound by default.
In Java, dynamic binding is the default behavior and you don’t need extra keywords to produce polymorphism.


Abstract Class vs Interface


|                 | Abstract Class     | Interface                                          |
| --------------- | ------------------ | -------------------------------------------------- |
| Abstract Method | public/protected   | public                                             |
| Fields          | all                | public static final                                |
| Constructor     | Has                | no constructor                                     |
| Hierarchy       | only one           | multiple implement                                 |
| Method & Block  | all                | only default/static/public static method, no block |
| For             | template by extend | add function                                       |
|                 | is a               | like a                                             |



### The Singly-Rooted Hierarchy

An OOP issue that has become especially prominent since the introduction of C++ is whether all classes should by default be inherited from a single base class.
In Java (as with virtually all other OOP languages except for C++) the answer is yes, and the name of this ultimate base class is simply Object.

There are many benefits to a singly-rooted hierarchy.
All objects have a common interface, so they are all ultimately the same fundamental type.
The alternative (provided by C++) is that you don’t know that everything is the same basic type.
From a backward-compatibility standpoint this fits the model of C better and can be thought of as less restrictive, but for full-on object-oriented programming you must build your own hierarchy to provide the same convenience that’s built into other OOP languages.

And in any new class library you acquire, some other incompatible interface is used. It requires effort to work the new interface into your design.
Is the extra “flexibility” of C++ worth it?
If you need it—if you have a large investment in C—it’s quite valuable.
If you’re starting from scratch, alternatives such as Java can be more productive.

A singly rooted hierarchy makes it much easier to implement a garbage collector, one of the fundamental improvements of Java over C++.
And since information about the type of an object is guaranteed to be in all objects, you’ll never end up with an object whose type you cannot determine.
This is especially important with system-level operations, such as exception handling (a language mechanism for reporting errors), and to allow greater flexibility in programming.



Three rules:

1. Any class wins over any interface. So if there’s a method with a body, or an abstract declaration, in the superclass chain, we can ignore the interfaces completely.
2. Subtype wins over supertype. If we have a situation in which two interfaces are competing to provide a default method and one interface extends the other, the subclass wins.
3. No rule 3. If the previous two rules don’t give us the answer, the subclass must either implement the method or declare it abstract.

*Rule 1 is what brings us compatibility with old code.*



## Method

Check parameters for validity. In other words, failure to validate parameters, can result in a violation of failure atomicity.

- Use varargs judiciously
- Return empty collections or arrays, not nulls
- Return optionals judiciously
- Write doc comments for all exposed API elements

### identify

The return type is the type of the value that pops out of the method after you call it. The argument list gives the types and names for the information you want to pass into the method.

**`The method name and argument list together uniquely identify the method.`**

Reason :  You can not use return value types to distinguish **overloaded methods**.

### Overload & Override

Selection among overloaded methods is static, while selection among overridden methods is dynamic.

**Overload**

Same class and method name with different argument lists

The choice of which overloading to invoke is made at compile time.

You can always give methods different names instead of overloading them.

**Override**

Class override method in superclass with same method name and argument list.




## Object Class

Class Object is the root of the class hierarchy. Every class has Object as a superclass. All objects, including arrays, implement the methods of this class.

### newInstance

create a object

- static first, then dynamic
- superclass first, then class
- fields first, then block and constructor

Consider a builder when faced with many constructor parameters

Enforce the singleton property with a private constructor or an enum type
Enforce noninstantiability with a private constructor

Prefer dependency injection to hardwiring resources


Because constructors allow you to guarantee proper initialization and cleanup (the compiler will not allow an object to be created without the proper constructor calls), you get complete control and safety.


### registerNatives

```java
private static native void registerNatives();
static {
    registerNatives();
}
```

### getClass

> Returns the runtime class of this Object. The returned Class object is the object that is locked by **static synchronized methods** of the represented class.
>
> The actual result type is Class<? extends |X|> where |X| is the erasure of the static type of the expression on which getClass is called.
>
> For example, no cast is required in this code fragment:
> Number n = 0;  Class<? extends Number> c = n.getClass();

```java
public final native Class<?> getClass();
```

### equals

Indicates whether some other object is "equal to" this one.
**Obey the general contract when overriding equals**. The equals method implements an equivalence relation on non-null object references:

- It is reflexive: for any non-null reference value x, x.equals(x) should return true.
- It is symmetric: for any non-null reference values x and y, x.equals(y) should return true if and only if y.equals(x) returns true.
- It is transitive: for any non-null reference values x, y, and z, if x.equals(y) returns true and y.equals(z) returns true, then x.equals(z) should return true.
- It is consistent: for any non-null reference values x and y, multiple invocations of x.equals(y) consistently return true or consistently return false, provided no information used in equals comparisons on the objects is modified.
- For any non-null reference value x, x.equals(null) should return false.

The equals method for class Object implements the most discriminating possible equivalence relation on objects; that is: For **any non-null reference values** x and y, this method **returns true if and only if x and y refer to the same object** (x == y has the value true).

**Always override hashCode when you override equals**. *Note that it is generally necessary to override the hashCode method whenever this method is overridden, so as to maintain the general contract for the hashCode method, which states that equal objects must have equal hash codes.*

```java
public boolean equals(Object obj) {
     return (this == obj);
}
```

use java.util.Objects#equals avoid NullPointerException

### hashCode

`if override equals(), must override hashcode() too.`

Returns a hash code value for the object. This method is supported for the benefit of hash tables such as those provided by **java.util.HashMap**.

The general contract of hashCode is:

- Whenever it is invoked on the same object more than once during an execution of a Java application, the hashCode method must **consistently return the same integer**, provided no information used in equals comparisons on the object is modified. This integer need not remain consistent from one execution of an application to another execution of the same application.
- If two objects are equal according to the equals(Object) method, hashCode method must produce the same integer result.
- It is not required that if two objects are unequal according to the equals(Object) method, then calling the hashCode method on each of the two objects must produce distinct integer results. However, the programmer should be aware that producing distinct integer results for unequal objects may improve the performance of hash tables.

As much as is reasonably practical, the hashCode method defined by class Object does return distinct integers for distinct objects. (This is typically implemented by converting the internal address of the object into an integer, but this implementation technique is not required by the Java™ programming language.)

```java
// return Identify Hash Code
public native int hashCode();
```

call `Object::hashCode()` will use [ObjectSynchronizer::inflate()](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=inflate)

**return 0 if object is NULL**

```cpp
//jvm.cpp
JVM_ENTRY(jint, JVM_IHashCode(JNIEnv* env, jobject handle))
  JVMWrapper("JVM_IHashCode");
  // as implemented in the classic virtual machine; return 0 if object is NULL
  return handle == NULL ? 0 : ObjectSynchronizer::FastHashCode (THREAD, JNIHandles::resolve_non_null(handle)) ;
JVM_END
```

```cpp
//synchronizer.cpp
// hashCode() generation :
//
// Possibilities:
// * MD5Digest of {obj,stwRandom}
// * CRC32 of {obj,stwRandom} or any linear-feedback shift register function.
// * A DES- or AES-style SBox[] mechanism
// * One of the Phi-based schemes, such as:
//   2654435761 = 2^32 * Phi (golden ratio)
//   HashCodeValue = ((uintptr_t(obj) >> 3) * 2654435761) ^ GVars.stwRandom ;
// * A variation of Marsaglia's shift-xor RNG scheme.
// * (obj ^ stwRandom) is appealing, but can result
//   in undesirable regularity in the hashCode values of adjacent objects
//   (objects allocated back-to-back, in particular).  This could potentially
//   result in hashtable collisions and reduced hashtable efficiency.
//   There are simple ways to "diffuse" the middle address bits over the
//   generated hashCode values:

intptr_t ObjectSynchronizer::FastHashCode(Thread * Self, oop obj) {
  if (UseBiasedLocking) {
    // NOTE: many places throughout the JVM do not expect a safepoint
    // to be taken here, in particular most operations on perm gen
    // objects. However, we only ever bias Java instances and all of
    // the call sites of identity_hash that might revoke biases have
    // been checked to make sure they can handle a safepoint. The
    // added check of the bias pattern is to avoid useless calls to
    // thread-local storage.
    if (obj->mark()->has_bias_pattern()) {
      // Handle for oop obj in case of STW safepoint
      Handle hobj(Self, obj);
      // Relaxing assertion for bug 6320749.
      assert(Universe::verify_in_progress() ||
             !SafepointSynchronize::is_at_safepoint(),
             "biases should not be seen by VM thread here");
      BiasedLocking::revoke_and_rebias(hobj, false, JavaThread::current());
      obj = hobj();
      assert(!obj->mark()->has_bias_pattern(), "biases should be revoked by now");
    }
  }

  // hashCode() is a heap mutator ...
  // Relaxing assertion for bug 6320749.
  assert(Universe::verify_in_progress() || DumpSharedSpaces ||
         !SafepointSynchronize::is_at_safepoint(), "invariant");
  assert(Universe::verify_in_progress() || DumpSharedSpaces ||
         Self->is_Java_thread() , "invariant");
  assert(Universe::verify_in_progress() || DumpSharedSpaces ||
         ((JavaThread *)Self)->thread_state() != _thread_blocked, "invariant");

  ObjectMonitor* monitor = NULL;
  markOop temp, test;
  intptr_t hash;
  markOop mark = ReadStableMark(obj);

  // object should remain ineligible for biased locking
  assert(!mark->has_bias_pattern(), "invariant");

  if (mark->is_neutral()) {
    hash = mark->hash();              // this is a normal header
    if (hash) {                       // if it has hash, just return it
      return hash;
    }
    hash = get_next_hash(Self, obj);  // allocate a new hash code
    temp = mark->copy_set_hash(hash); // merge the hash code into header
    // use (machine word version) atomic operation to install the hash
    test = obj->cas_set_mark(temp, mark);
    if (test == mark) {
      return hash;
    }
    // If atomic operation failed, we must inflate the header
    // into heavy weight monitor. We could add more code here
    // for fast path, but it does not worth the complexity.
  } else if (mark->has_monitor()) {
    monitor = mark->monitor();
    temp = monitor->header();
    assert(temp->is_neutral(), "invariant");
    hash = temp->hash();
    if (hash) {
      return hash;
    }
    // Skip to the following code to reduce code size
  } else if (Self->is_lock_owned((address)mark->locker())) {
    temp = mark->displaced_mark_helper(); // this is a lightweight monitor owned
    assert(temp->is_neutral(), "invariant");
    hash = temp->hash();              // by current thread, check if the displaced
    if (hash) {                       // header contains hash code
      return hash;
    }
    // WARNING:
    //   The displaced header is strictly immutable.
    // It can NOT be changed in ANY cases. So we have
    // to inflate the header into heavyweight monitor
    // even the current thread owns the lock. The reason
    // is the BasicLock (stack slot) will be asynchronously
    // read by other threads during the inflate() function.
    // Any change to stack may not propagate to other threads
    // correctly.
  }
```

[Inflate the monitor](/docs/CS/Java/JDK/Concurrency/synchronized.md?id=inflate) to set hash code

```cpp
  monitor = ObjectSynchronizer::inflate(Self, obj, inflate_cause_hash_code);
  // Load displaced header and check it has hash code
  mark = monitor->header();
  assert(mark->is_neutral(), "invariant");
  hash = mark->hash();
  if (hash == 0) {
```

[get_next_hash](/docs/CS/Java/JDK/Basic/Object.md?id=get_next_hash) and merge into [markWord](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=MarkWord)

```cpp
    hash = get_next_hash(Self, obj);
    temp = mark->copy_set_hash(hash); // merge hash code into header
    assert(temp->is_neutral(), "invariant");
    test = Atomic::cmpxchg(temp, monitor->header_addr(), mark);
    if (test != mark) {
      // The only update to the header in the monitor (outside GC)
      // is install the hash code. If someone add new usage of
      // displaced header, please update this code
      hash = test->hash();
      assert(test->is_neutral(), "invariant");
      assert(hash != 0, "Trivial unexpected object/monitor header usage.");
    }
  }
  // We finally get the hash
  return hash;
}
```

#### get_next_hash

```cpp
static inline intptr_t get_next_hash(Thread * Self, oop obj) {
  intptr_t value = 0;
  if (hashCode == 0) {
    // This form uses global Park-Miller RNG.
    // On MP system we'll have lots of RW access to a global, so the
    // mechanism induces lots of coherency traffic.
    value = os::random();
  } else if (hashCode == 1) {
    // This variation has the property of being stable (idempotent)
    // between STW operations.  This can be useful in some of the 1-0
    // synchronization schemes.
    intptr_t addrBits = cast_from_oop<intptr_t>(obj) >> 3;
    value = addrBits ^ (addrBits >> 5) ^ GVars.stwRandom;
  } else if (hashCode == 2) {
    value = 1;            // for sensitivity testing
  } else if (hashCode == 3) {
    value = ++GVars.hcSequence;
  } else if (hashCode == 4) {
    value = cast_from_oop<intptr_t>(obj);
  } else {
    // Marsaglia's xor-shift scheme with thread-specific state
    // This is probably the best overall implementation -- we'll
    // likely make this the default in future releases.
    unsigned t = Self->_hashStateX;
    t ^= (t << 11);
    Self->_hashStateX = Self->_hashStateY;
    Self->_hashStateY = Self->_hashStateZ;
    Self->_hashStateZ = Self->_hashStateW;
    unsigned v = Self->_hashStateW;
    v = (v ^ (v >> 19)) ^ (t ^ (t >> 8));
    Self->_hashStateW = v;
    value = v;
  }

  value &= markOopDesc::hash_mask;
  if (value == 0) value = 0xBAD;
  assert(value != markOopDesc::no_hash, "invariant");
  return value;
}
```

Use `-XX:hashCode=N` choose algorithm of generate hashCode, default 5

```shell
java -XX:+PrintFlagsFinal -version | grep hashCode
intx hashCode                                  = 5                                   {product}
```

See [Xorshift RNGs](https://www.jstatsoft.org/article/view/v008i14)



### clone

```java
protected native Object clone() throws CloneNotSupportedException;
```

### toString

**Always override toString**. Providing a good toString implementation makes your class much more pleasant to use and makes systems using the class easier to debug.

```java
public String toString() {
    return getClass().getName() + "@" + Integer.toHexString(hashCode());
}
```

### finalize

**Avoid finalizers and cleaners.**

see [load Class](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=rewrite_Object_init) when override finalizer

```java
protected void finalize() throws Throwable { }
```

Since finalizers can run in a thread(Finalizer Thread) managed by the JVM, any state accessed by a finalizer will be accessed by more than one thread and therefore must be accessed with synchronization.
Finalizers offer no guarantees on when or even if they run, and they impose a significant performance cost on objects with nontrivial finalizers.
They are also extremely difficult to write correctly.
In most cases, the combination of `finally blocks` and explicit close methods does a better job of resource management than finalizers;
the sole exception is when you need to manage objects that hold resources acquired by native methods.

### wait & notify

Prefer concurrency utilities to wait and notify . See [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md?id=Order)

## Serialization

Deserialization of untrusted streams can result in remote code execution (RCE), denial-of-service (DoS), and a range of other exploits. Applications can be vulnerable to these attacks even if they did nothing wrong.

**The best way to avoid serialization exploits is never to deserialize anything**.

**There is no reason to use Java serialization in any new system you write**.

If you can’t avoid Java serialization entirely, perhaps because you’re working in the context of a legacy system that requires it, your next best alternative is to **never deserialize untrusted data**.

Implement Serializable with great caution:

1. A major cost of implementing Serializable is that it decreases the flexibility to change a class’s implementation once it has been released.
2. A second cost of implementing Serializable is that it increases the likelihood of bugs and security holes.
3. A third cost of implementing Serializable is that it increases the testing burden associated with releasing a new version of a class.

Write readObject methods defensively. For instance control, prefer [enum](/docs/CS/Java/JDK/Basic/enum.md?id=Serialization) types to.

## Classes

## Nested Classes

The Java programming language allows you to define a class within another class. Such a class is called a nested class and is illustrated here:

```java
class OuterClass {
    //...
    class NestedClass {
        //...
    }

    static class StaticNestedClass {
        //...
    }
}
```

### Inner classes

Nested classes are divided into two categories: non-static and static. Non-static nested classes are called *inner classes*.
Nested classes that are declared static are called *static nested classes*.

A nested class is a member of its enclosing class.

- Non-static nested classes (inner classes) have access to other members of the enclosing class, even if they are declared private.
  Also, because an inner class is associated with an instance, it cannot define any static members itself.
- Static nested classes do not have access to other members of the enclosing class.
  And like static class methods, a static nested class cannot refer directly to instance variables or methods defined in its enclosing class: it can use them only through an object reference

As a member of the OuterClass, a nested class can be declared private, public, protected, or package private.
(Recall that outer classes can only be declared public or package private.)

**Serialization of inner classes, including local and anonymous classes, is strongly discouraged.**
When the Java compiler compiles certain constructs, such as inner classes, it creates synthetic constructs; these are classes, methods, fields, and other constructs that do not have a corresponding construct in the source code.
Synthetic constructs enable Java compilers to implement new Java language features without changes to the JVM.
However, synthetic constructs can vary among different Java compiler implementations, which means that files can vary among different implementations as well.
Consequently, you may have compatibility issues if you serialize an inner class and then deserialize it with a different JRE implementation.
See the section Implicit and Synthetic Parameters in the section Obtaining Names of Method Parameters for more information about the synthetic constructs generated when an inner class is compiled..class

### Local Classes

Local classes are classes that are defined in a block, which is a group of zero or more statements between balanced braces. You typically find local classes defined in the body of a method.
You can define a local class inside any block (see Expressions, Statements, and Blocks for more information).
For example, you can define a local class in a method body, a for loop, or an if clause.
The following example, LocalClassExample, validates two phone numbers. It defines the local class PhoneNumber in the method validatePhoneNumber:

```java
public class LocalClassExample {

    static String regularExpression = "[^0-9]";

    public static void validatePhoneNumber(
            String phoneNumber1, String phoneNumber2) {

        final int numberLength = 10;

        int numberLength = 10;

        class PhoneNumber {

            String formattedPhoneNumber = null;

            PhoneNumber(String phoneNumber) {
                // numberLength = 7;
                String currentNumber = phoneNumber.replaceAll(
                        regularExpression, "");
                if (currentNumber.length() == numberLength)
                    formattedPhoneNumber = currentNumber;
                else
                    formattedPhoneNumber = null;
            }

            public String getNumber() {
                return formattedPhoneNumber;
            }

            public void printOriginalNumbers() {
                System.out.println("Original numbers are " + phoneNumber1 +
                        " and " + phoneNumber2);
            }
        }

        PhoneNumber myNumber1 = new PhoneNumber(phoneNumber1);
        PhoneNumber myNumber2 = new PhoneNumber(phoneNumber2);

        myNumber1.printOriginalNumbers();

        if (myNumber1.getNumber() == null)
            System.out.println("First number is invalid");
        else
            System.out.println("First number is " + myNumber1.getNumber());
        if (myNumber2.getNumber() == null)
            System.out.println("Second number is invalid");
        else
            System.out.println("Second number is " + myNumber2.getNumber());

    }

    public static void main(String... args) {
        validatePhoneNumber("123-456-7890", "456-7890");
    }
}
```

A local class has access to the members of its enclosing class.
In addition, a local class has access to local variables. However, a local class can only access local variables that are declared final.
When a local class accesses a local variable or parameter of the enclosing block, it captures that variable or parameter.
However, starting in Java SE 8, a local class can access local variables and parameters of the enclosing block that are final or effectively final.
A variable or parameter whose value is never changed after it is initialized is effectively final.

Local classes are similar to inner classes because they cannot define or declare any static members. Local classes in static methods, such as the class , which is defined in the static method , can only refer to static members of the enclosing class.
For example, if you do not define the member variable as static, then the Java compiler generates an error similar to "non-static variable cannot be referenced from a static context.

Local classes are non-static because they have access to instance members of the enclosing block. Consequently, they cannot contain most kinds of static declarations.
You cannot declare an interface inside a block; interfaces are inherently static.
You cannot declare static initializers or member interfaces in a local class.
A local class can have static members provided that they are constant variables. (A constant variable is a variable of primitive type or type that is declared final and initialized with a compile-time constant expression. A compile-time constant expression is typically a string or an arithmetic expression that can be evaluated at compile time

Declarations of a type (such as a variable) in a local class [shadow](/docs/CS/Java/JDK/Basic/Object.md?id=Shadowing) declarations in the enclosing scope that have the same name.

### Anonymous Classes

Anonymous classes enable you to make your code more concise. They enable you to declare and instantiate a class at the same time. They are like local classes except that they do not have a name. Use them if you need to use a local class only once.

While local classes are class declarations, anonymous classes are expressions, which means that you define the class in another expression.
The syntax of an anonymous class expression is like the invocation of a constructor, except that there is a class definition contained in a block of code.
Consider the instantiation of the object:frenchGreeting

```java
 HelloWorld frenchGreeting = new HelloWorld() {
            String name = "tout le monde";
            public void greet() {
                greetSomeone("tout le monde");
            }
            public void greetSomeone(String someone) {
                name = someone;
                System.out.println("Salut " + name);
            }
        };
```

The anonymous class expression consists of the following:

- The operator new
- The name of an interface to implement or a class to extend. In this example, the anonymous class is implementing the interface .HelloWorld
- Parentheses that contain the arguments to a constructor, just like a normal class instance creation expression. Note: When you implement an interface, there is no constructor, so you use an empty pair of parentheses, as in this example.
- A body, which is a class declaration body. More specifically, in the body, method declarations are allowed but statements are not.

Because an anonymous class definition is an expression, it must be part of a statement.
In this example, the anonymous class expression is part of the statement that instantiates the object. (This explains why there is a semicolon after the closing brace.)

Like local classes, anonymous classes can capture variables; they have the same access to local variables of the enclosing scope:

- An anonymous class has access to the members of its enclosing class.
- An anonymous class cannot access local variables in its enclosing scope that are not declared as or effectively final.final
- Like a nested class, a declaration of a type (such as a variable) in an anonymous class [shadows](/docs/CS/Java/JDK/Basic/Object.md?id=Shadowing) any other declarations in the enclosing scope that have the same name.

Anonymous classes also have the same restrictions as local classes with respect to their members:

- You cannot declare static initializers or member interfaces in an anonymous class.
- An anonymous class can have static members provided that they are constant variables.

Note that you can declare the following in anonymous classes:

- Fields
- Extra methods (even if they do not implement any methods of the supertype)
- Instance initializers
- Local classes

However, you cannot declare constructors in an anonymous class.

Anonymous classes are ideal for implementing an interface that contains two or more methods
When using an interface that contains only one abstract method, you can use [lambda expressions](/docs/CS/Java/JDK/Basic/Lambda.md?id=lambda-expressions) instead of anonymous class expressions.

### Shadowing

If a declaration of a type (such as a member variable or a parameter name) in a particular scope (such as an inner class or a method definition) has the same name as another declaration in the enclosing scope, then the declaration shadows the declaration of the enclosing scope.
You cannot refer to a shadowed declaration by its name alone.
The following example, ShadowTest, demonstrates this:

```java
public class ShadowTest {
    public int x = 0;

    class FirstLevel {
        public int x = 1;

        void methodInFirstLevel(int x) {
            System.out.println("x = " + x);
            System.out.println("this.x = " + this.x);
            System.out.println("ShadowTest.this.x = " + ShadowTest.this.x);
        }
    }

    public static void main(String... args) {
        ShadowTest st = new ShadowTest();
        ShadowTest.FirstLevel fl = st.new FirstLevel();
        fl.methodInFirstLevel(23);
    }
}
```

The following is the output of this example:

```
x = 23
this.x = 1
ShadowTest.this.x = 0
```

This example defines three variables named : the member variable of the class , the member variable of the inner class , and the parameter in the method .
The variable defined as a parameter of the method shadows the variable of the inner class . Consequently, when you use the variable in the method , it refers to the method parameter.
To refer to the member variable of the inner class , use the keyword to represent the enclosing scope:

```
System.out.println("this.x = " + this.x);
```

Refer to member variables that enclose larger scopes by the class name to which they belong. For example, the following statement accesses the member variable of the class from the method:

```
System.out.println("ShadowTest.this.x = " + ShadowTest.this.x);
```

### Why Use Nested Classes?

Compelling reasons for using nested classes include the following:

- **It is a way of logically grouping classes that are only used in one place:** If a class is useful to only one other class, then it is logical to embed it in that class and keep the two together.
  Nesting such "helper classes" makes their package more streamlined.
- **It increases encapsulation:** Consider two top-level classes, A and B, where B needs access to members of A that would otherwise be declared.
  By hiding class B within class A, A's members can be declared private and B can access them. In addition, B itself can be hidden from the outside world.private
- **It can lead to more readable and maintainable code:** Nesting small classes within top-level classes places the code closer to where it is used.

Nested classes enable you to logically group classes that are only used in one place, increase the use of encapsulation, and create more readable and maintainable code.
Local classes, anonymous classes, and lambda expressions also impart these advantages; however, they are intended to be used for more specific situations:

- **Local class:**
  Use it if you need to create more than one instance of a class, access its constructor, or introduce a new, named type (because, for example, you need to invoke additional methods later).
- **Anonymous class:**
  Use it if you need to declare fields or additional methods.
- **Lambda expression:**
  Use it if you are encapsulating a single unit of behavior that you want to pass to other code.
  For example, you would use a lambda expression if you want a certain action performed on each element of a collection, when a process is completed, or when a process encounters an error.
  Use it if you need a simple instance of a functional interface and none of the preceding criteria apply (for example, you do not need a constructor, a named type, fields, or additional methods).
- **Nested class:**
  Use it if your requirements are similar to those of a local class, you want to make the type more widely available, and you don't require access to local variables or method parameters.
  Use a non-static nested class (or inner class) if you require access to an enclosing instance's non-public fields and methods. Use a static nested class if you don't require this access.

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
