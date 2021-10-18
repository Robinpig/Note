## OOP

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
- The **protected** keyword acts like **private**, with the exception that an inheriting class has access to **protected** members, but not **private** members. Hierarchy will be introduced shortly. 
- Java also has a “**default**” access, which comes into play if you don’t use one of the aforementioned specifiers. This is usually called ***package* *access*** because classes can access the members of other classes in the same package, but outside of the package those same members appear to be **private**. 



Java object identifiers are *actually* “object references.” **And everything is actually pass by value**. So you’re not passing by reference, you’re “passing an object reference by value.



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



###  Overload & Override

Selection among overloaded methods is static, while selection among overridden methods is dynamic.

**Overload**

Same class and method name with different argument lists 

The choice of which overloading to invoke is made at compile time.

You can always give methods different names instead of overloading them.

**Override**

Class override method in superclass with same method name and argument list.

 

## Polymorphism

Type
- compile type 
- runtime type



### Abstract Class vs Interface

|                 | Abstract Class     | Interface                                          |
| --------------- | ------------------ | -------------------------------------------------- |
| Abstract Method | public/protected   | public                                             |
| Fields          | all                | public static final                                |
| Constructor     | Has                | no constructor                                     |
| Hierarchy       | only one           | multiple implement                                 |
| Method & Block  | all                | only default/static/public static method, no block |
| For             | template by extend | add function                                       |
|                 | is a               | like a                                             |



## Multiple Hierarchy

Three rules:

1. *Any class wins over any interface. So if there’s a method with a body, or an abstract declaration, in the superclass chain, we can ignore the interfaces completely.*
2. *Subtype wins over supertype. If we have a situation in which two interfaces are competing to provide a default method and one interface extends the other, the subclass wins.*
3. *No rule 3. If the previous two rules don’t give us the answer, the subclass must either implement the method or declare it abstract.*

*Rule 1 is what brings us compatibility with old code.*



## Object Class

`Class Object is the root of the class hierarchy. Every class has Object as a superclass. All objects, including arrays, implement the methods of this class.`

### newInstance

create a object

- static first, then dynamic
- superclass first, then class
- fields first, then block and constructor

Consider a builder when faced with many constructor parameters

Enforce the singleton property with a private constructor or an enum type  
Enforce noninstantiability with a private constructor

Prefer dependency injection to hardwiring resources


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
public native int hashCode();
```

will use [**ObjectSynchronizer::inflate**]()

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

  // Inflate the monitor to set hash code
  monitor = ObjectSynchronizer::inflate(Self, obj, inflate_cause_hash_code);
  // Load displaced header and check it has hash code
  mark = monitor->header();
  assert(mark->is_neutral(), "invariant");
  hash = mark->hash();
  if (hash == 0) {
    hash = get_next_hash(Self, obj);// get hash
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
**Avoid finalizers and cleaners**.


Since finalizers can run in a thread(Finalizer Thread) managed by the JVM, any state accessed by a finalizer will be accessed by more than one thread and therefore must be accessed with synchronization. Finalizers offer no guarantees on when or even if they run, and they impose a significant performance cost on objects with nontrivial finalizers. They are also extremely difficult to write correctly. In most cases, the combination of `finally blocks` and explicit close methods does a better job of resource management than finalizers; the sole exception is when you need to manage objects that hold resources acquired by native methods.
```java
protected void finalize() throws Throwable { }
```




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
