## Lambda



### Anonymous Inner Class



- new Anonymous Inner Class
- invokespecial

```java
public static void main(String[] args) {
     Thread thread = new Thread(new Runnable() {
        @Override
        public void run() {
            System.out.println("Hello World!");
        }
    });

}
```

```java
public static void main(java.lang.String[]);
    Code:
       0: new           #2                  // class java/lang/Thread
       3: dup
       4: new           #3                  // class com/yh/base/ArrayTest$1
       7: dup
       8: invokespecial #4                  // Method com/yh/base/ArrayTest$1."<init>":()V
      11: invokespecial #5                  // Method java/lang/Thread."<init>":(Ljava/lang/Runnable;)V
      14: astore_1
      15: return
```



### invokedynamic


```java
 public static void main(String[] args) {
         Thread thread = new Thread(() -> System.out.println("Hello World!"));

    }
```

```
 public static void main(java.lang.String[]);
    Code:
       0: new           #2                  // class java/lang/Thread
       3: dup
       4: invokedynamic #3,  0              // InvokeDynamic #0:run:()Ljava/lang/Runnable;
       9: invokespecial #4                  // Method java/lang/Thread."<init>":(Ljava/lang/Runnable;)V
      12: astore_1
      13: return
```

javap
```
InnerClasses:
  public static final #58= #57 of #61;    // Lookup=class java/lang/invoke/MethodHandles$Lookup of class java/lang/invoke/MethodHandles
BootstrapMethods:
  0: #29 REF_invokeStatic java/lang/invoke/LambdaMetafactory.metafactory:(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)Ljava/lang/invoke/CallSite;
    Method arguments:
      #30 ()V
      #31 REF_invokeStatic com/yh/framework/netty/thread/FastThreadLocalTest.lambda$main$0:()V
      #30 ()V
```

CallSite

java.lang.invoke.CallSite

1. 使用invokedynamic指令，运行时调用LambdaMetafactory.metafactory动态的生成内部类，实现了接口，
2. 内部类里的调用方法块并不是动态生成的，只是在原class里已经编译生成了一个静态的方法，内部类只需要调用该静态方法

Compare

- Anonymous Inner Class create object every time and GC immediately
- Lambda in need not to load Class



## Functional Interface

*There are some interfaces in Java that have only a single method but aren’t normally meant to be implemented by lambda expressions. For example, they might assume that the object has internal state and be interfaces with a single method only coincidentally. A couple of good examples are **java.lang.Comparable** and **java.io.Closeable**.*

*In contrast to Closeable and Comparable, all the new interfaces introduced in order to provide Stream interoperability are expected to be implemented by lambda expressions. They are really there to **bundle up blocks of code as data**. Consequently, they have the @FunctionalInterface annotation applied.*



| Functional Interface | Parameter Type | Return Type | Scence |
| -------------------- | -------------- | ----------- | ------ |
| Consumer             | T              | void        |        |
| Supplier             | -              | T           |        |
| Function<T,R>        | T              | R           |        |
| Predicate            | T              | boolean     |        |



| Functional Interface | Parameter Type | Return Type | Scence                |
| -------------------- | -------------- | ----------- | --------------------- |
| Comparator<T>        | T              | int         | A comparison function |
|                      |                |             |                       |
|                      |                |             |                       |
|                      |                |             |                       |
|                      |                |             |                       |
|                      |                |             |                       |





## Stream

*A Stream is a tool for building up complex operations on collections using a functional approach.*

### Iterator & Stream

*Counting London-based artists using a for loop*

```java
int count = 0;
for (Artist artist : allArtists) {
    if (artist.isFrom("London")) {
        count++;
    }
}
```

*Looking under the covers a little bit, the for loop is actually syntactic sugar that wraps up the iteration and hides it. It’s worth taking a moment to look at what’s going on under the hood here. The first step in this process is a call to the iterator method, which creates a new **Iterator** object in order to control the iteration process. We call this **external iteration**. The iteration then proceeds by explicitly calling the hasNext and next methods on this Iterator.*

*Counting London-based artists using an iterator*

```java
int count = 0;
Iterator<Artist> iterator = allArtists.iterator();
while(iterator.hasNext()) {
    Artist artist = iterator.next();
    if (artist.isFrom("London")) {
        count++;
    }
}
```



![External Iteration](../images/Stream-External-Iteration.png)



*Counting London-based artists using internal iteration*

```java
long count = allArtists.stream()
                       .filter(artist -> artist.isFrom("London"))
                       .count();
```



![Internal Iteration](../images/Stream-Internal-Iteration.png)

It’s very easy to figure out whether an operation is eager or lazy: **look at what it returns.**

- If it gives you back a Stream, it’s lazy
- if it gives you back another value or void, then it’s eager

*This makes sense because the preferred way of using these methods is to form a sequence of lazy operations chained together and then to have a single eager operation at the end that generates your result.*



1. 过滤器因为支持在迭代过程中结束处理，所以有很大的性能优势
2. 即使都要处理整个数据集，一个过滤器还是要比一个迭代器稍微快些
3. 多个过滤器有些开销，所以要确保编写好用的过滤器



### Generate Stream

#### Collection

*Collection provide a **default method** to avert all third-party collections libraries being broken.*

*default methods are designed primarily to allow binary compatible API evolution. Allowing classes to win over any default methods simplifies a lot of Hierarchy scenarios.*

#### Arrays

#### Stream 

of()

empty()

iterate() generate()





###  Parallel

Returns an equivalent stream that is parallel. May return itself, either because the stream was already parallel, or because the underlying stream state was modified to be parallel.
This is an intermediate operation.

```java
// BaseStream
S parallel();

// AbstractPipeline
@Override
@SuppressWarnings("unchecked")
public final S parallel() {
  sourceStage.parallel = true;
  return (S) this;
}
```



```java
// Stream
T reduce(T identity, BinaryOperator<T> accumulator);

// ReferencePipeline extends AbstractPipeline implements Stream
@Override
public final P_OUT reduce(final P_OUT identity, final BinaryOperator<P_OUT> accumulator) {
  return evaluate(ReduceOps.makeRef(identity, accumulator, accumulator)); // ReduceOps
}

final <R> R evaluate(TerminalOp<E_OUT, R> terminalOp) {
    assert getOutputShape() == terminalOp.inputShape();
    if (linkedOrConsumed)
        throw new IllegalStateException(MSG_STREAM_LINKED);
    linkedOrConsumed = true;

    return isParallel()
           ? terminalOp.evaluateParallel(this, sourceSpliterator(terminalOp.getOpFlags()))
           : terminalOp.evaluateSequential(this, sourceSpliterator(terminalOp.getOpFlags()));
}
```



ReduceTask is a [ForkJoinTask](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md) for performing a parallel reduce operation.

based on `ForkJoinPool.commonPool()`

```java
// ReduceOps
@Override
public <P_IN> R evaluateParallel(PipelineHelper<T> helper,
                                 Spliterator<P_IN> spliterator) {
    return new ReduceTask<>(this, helper, spliterator).invoke().get();
}
```


#### Use caution when making streams parallel

As a rule, performance gains from parallelism are best on streams over ArrayList, HashMap, HashSet, and ConcurrentHashMap instances; arrays; int ranges; and long ranges. What these data structures have in common is that they can all be accurately and cheaply split into subranges of any desired sizes, which makes it easy to divide work among parallel threads.

Another important factor that all of these data structures have in common is that they provide good-to-excellent locality of reference when processed sequentially: sequential element references are stored together in memory.

Not only can parallelizing a stream lead to poor performance, including liveness failures; it can lead to incorrect results and unpredictable behavior (`safety failures`).




### Method

**collect(toList)**

*collect(toList()) is an eager operation that generates a list from the values in a Stream.*

**map**

*If you’ve got a function that converts a value of one type into another, map lets you apply this function to a stream of values, producing another stream of the new values.*



**filter**

*Any time you’re looping over some data and checking each element, you might want to think about using the new filter method on Stream.*

use Predicate interface

**flatMap**

*flatMap lets you replace a value with a Stream and concatenates all the streams together.*



### Key Points

*Whenever you pass lambda expressions into the higher-order functions on the Stream interface, you should seek to **avoid side effects**. The only exception to this is the **forEach** method, which is a terminal operation.*



*A significant performance advantage can be had by **using primitive specialized lambda expressions and streams** such as IntStream.*



## Reference

1. [底层原理之旅—带你看透Lambda表达式的本质](https://juejin.cn/post/6966839856421044237)