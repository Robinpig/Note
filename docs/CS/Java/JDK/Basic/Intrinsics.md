## Introduction

An intrinsic function is a function that has special handling by the compiler or interpreter for our programming language. More specifically, it’s a special case where the compiler or interpreter can replace the function with an alternative implementation for various reasons.

The programming language typically handles this by understanding that a specific method call is special, and whenever we call this method, then the resulting behavior is different. 
This then allows our code to look no different from normal, but the programming language’s implementation can intervene in special cases to give additional benefits.

The exact way that it works varies between programming languages and also between operating systems and hardware. However, because these are handled for us, we typically don’t need to know any of these details.

Intrinsics can give various benefits. 
Replacing particular algorithms with native code can make them perform better or even leverage the operating system’s specific features or underlying hardware.

The JVM implements intrinsics by replacing the exact method call on an exact class with an alternative version. 
The JVM handles this itself, so it will only work for core classes and particular architectures. 
It also allows only certain methods to be swapped out, rather than entire classes.

Exactly how this works will vary between JVMs. This includes not only different versions of the JVM – Java 8 vs. Java 11, for example. 
This also includes different JVM targets – Linux vs. Windows, for example – and especially JVM vendors – Oracle vs. IBM. 
In some cases, certain command-line flags passed to the JVM can affect them.

This variety means that there’s no way to determine, based only on the application, which methods will be replaced with intrinsic and which won’t. 
It’ll be different based on the JVM running the application. 
But this can lead to surprising results in some cases – including significant performance benefits achieved simply by changing the JVM used.


## Performance Benefits
Intrinsics are often used to implement a more efficient version of the same code, for example, by leveraging implementation details of the running OS or CPU. 
Sometimes this is because it can use a more efficient implementation, and other times it can go as far as using hardware-specific functionality.

For example, the HotSpot JDK has an intrinsic implementation for many of the methods in java.lang.Math. Depending on the exact JVM, these are potentially implemented using CPU instructions to do the exact calculations required.

For example, take `java.lang.Math.sqrt()`. We can write a test:
```
for (int a = 0; a < 100000; ++a) {
    double result = Math.sqrt(a);
}
```
This test is performing a square root operation 100,000 times, which takes approx 123ms. 
However, if we replace this code with a copy of the implementation of `Math.sqrt()` instead:
```
double result = StrictMath.sqrt(a);
```
This code does the same thing but executes in 166ms instead. That’s an increase of 35% by copying the implementation instead of allowing the JVM to replace it with the intrinsic version.



There is, unfortunately, no guaranteed way to identify methods that might be replaced with intrinsic versions. 
This is because different JVMs or even the same JVM on different platforms will do this for different methods.

However, when using Hotspot JVM as of Java 9, the `@HotSpotIntrinsicCandidate` annotation is used on all methods that may be replaced. 
Adding this annotation doesn’t automatically cause the method to be replaced. 
In reality, that happens within the underlying JVM. 
Instead, JVM developers know that these methods are special and to be careful with them.

**What is the difference between Java intrinsic and native methods?**

- The [JIT](/docs/CS/Java/JDK/JVM/JIT.md) knows about intrinsics, so it can inline the relevant machine instruction into the code it's JITing, and optimize around it as part of a hot loop.
- A `JNI` function is a 100% black box for the compiler, with significant call/return overhead (especially if you use it for just a scalar).


## Links

- [JNI](/docs/CS/Java/JDK/Basic/JNI.md)
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)


## References

