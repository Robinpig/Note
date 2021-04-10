# Object



> “We cut nature up, organize it into concepts, and ascribe significances as we do, largely because we are parties to an agreement that holds throughout our speech community and is codified in the patterns of our language ... we cannot talk at all except by subscribing to the organization and classification of data which the agreement decrees.” Benjamin Lee Whorf (1897-1941)

**Object-oriented programming OOP**

> - **Everything is an object**
> - **A program is a bunch of objects telling each other what to do by sending messages**
> - **Each object has its own memory made up of other objects**
> - **Every object has a type**
> - **All objects of a particular type can receive the same messages**



**`An object has state, behavior and identity.`**

This means that an object can have internal data (which gives it state), methods (to produce behavior), and each object can be uniquely distinguished from every other object—to put this in a concrete sense, each object has a unique address in memory.

## Access Control 

### Reason

- `keep client programmers’ hands off portions they shouldn’t touch—parts that are necessary for the internal operation of the data type but not part of the interface that users need in order to solve their particular problems.`
- `allow the library designer to change the internal workings of the class without worrying about how it will affect the client programmer.`



### Access specifier

Java uses three explicit keywords to set the boundaries in a class: **public**, **private**, and **protected**. Their use and meaning are quite straightforward. These *access specifiers* determine who can use the definitions that follow.

-  **public** means the following element is available to everyone. 
- The **private** keyword, on the other hand, means that no one can access that element except you, the creator of the type, inside methods of that type. **private** is a brick wall between you and the client programmer. Someone who tries to access a **private** member will get a compile-time error. 
- The **protected** keyword acts like **private**, with the exception that an inheriting class has access to **protected** members, but not **private** members. Inheritance will be introduced shortly. 
- Java also has a “**default**” access, which comes into play if you don’t use one of the aforementioned specifiers. This is usually called ***package* *access*** because classes can access the members of other classes in the same package, but outside of the package those same members appear to be **private**. 



Java object identifiers are *actually* “object references.” **And everything is actually pass by value**. So you’re not passing by reference, you’re “passing an object reference by value.



## Method

### identify

The return type is the type of the value that pops out of the method after you call it. The argument list gives the types and names for the information you want to pass into the method.

 **`The method name and argument list together uniquely identify the method.`**

Reason :  You can not use return value types to distinguish **overloaded methods**.



###  Overload & Override

**Overload**

Same class and method name with different argument lists 

**Override**

Class override method in superclass with same method name and argument list.

 

## Polymorphism

Type
- compile type 
- runtime type



## Object

`Class Object is the root of the class hierarchy. Every class has Object as a superclass. All objects, including arrays, implement the methods of this class.`



### registerNatives

```java
private static native void registerNatives();
static {
    registerNatives();
}
```



> Returns the runtime class of this Object. The returned Class object is the object that is locked by **static synchronized methods** of the represented class.
>
> The actual result type is Class<? extends |X|> where |X| is the erasure of the static type of the expression on which getClass is called. 
>
> For example, no cast is required in this code fragment:
> Number n = 0;  Class<? extends Number> c = n.getClass(); 

```java
public final native Class<?> getClass();
```



Indicates whether some other object is "equal to" this one.
The equals method implements an equivalence relation on non-null object references:

- It is reflexive: for any non-null reference value x, x.equals(x) should return true.
- It is symmetric: for any non-null reference values x and y, x.equals(y) should return true if and only if y.equals(x) returns true.
- It is transitive: for any non-null reference values x, y, and z, if x.equals(y) returns true and y.equals(z) returns true, then x.equals(z) should return true.
- It is consistent: for any non-null reference values x and y, multiple invocations of x.equals(y) consistently return true or consistently return false, provided no information used in equals comparisons on the objects is modified.
- For any non-null reference value x, x.equals(null) should return false.

The equals method for class Object implements the most discriminating possible equivalence relation on objects; that is, for any non-null reference values x and y, this method returns true if and only if x and y refer to the same object (x == y has the value true).
Note that it is generally necessary to override the hashCode method whenever this method is overridden, so as to maintain the general contract for the hashCode method, which states that equal objects must have equal hash codes.

```java
public boolean equals(Object obj) {
     return (this == obj);
}
```

use java.util.Objects#equals invoid NullPointerException



### hashCode

`if override equals(), must override hashcode() too.`

Returns a hash code value for the object. This method is supported for the benefit of hash tables such as those provided by **java.util.HashMap**.

The general contract of hashCode is:

- Whenever it is invoked on the same object more than once during an execution of a Java application, the hashCode method must **consistently return the same integer**, provided no information used in equals comparisons on the object is modified. This integer need not remain consistent from one execution of an application to another execution of the same application.
- If two objects are equal according to the equals(Object) method, then calling the hashCode method on each of the two objects must produce the same integer result.
- It is not required that if two objects are unequal according to the equals(Object) method, then calling the hashCode method on each of the two objects must produce distinct integer results. However, the programmer should be aware that producing distinct integer results for unequal objects may improve the performance of hash tables.

As much as is reasonably practical, the hashCode method defined by class Object does return distinct integers for distinct objects. (This is typically implemented by converting the internal address of the object into an integer, but this implementation technique is not required by the Java™ programming language.)

```java
public native int hashCode();
```



### clone

```java
protected native Object clone() throws CloneNotSupportedException;
```



```java
public String toString() {
    return getClass().getName() + "@" + Integer.toHexString(hashCode());
}
```

```java
protected void finalize() throws Throwable { }
```


create a object

- static first, then dynamic
- superclass first, then class
- fields first, then block and constructor



### wait & notify

See [Thread](https://github.com/Robinpig/Note/raw/master/CS/Java/JDK/Concurrency/Thread.md)
