## Introduction

> [!NOTE]
> Java is a blue collar language. It’s not PhD thesis material but a language for a job.
>
> -- by James Gosling



Every programming language manipulates elements in memory. 
Sometimes the programmer must be constantly aware of that manipulation.
Do you manipulate the element directly, or use an indirect representation that requires special syntax (for example, pointers in C or C++)?

Java simplifies the issue by [considering everything an object](/docs/CS/Java/JDK/Basic/Object.md), using a single consistent syntax. 
Although you treat everything as an object, the identifier you manipulate is actually a “reference” to an object.

In one book I read that it was “completely wrong to say that Java supports pass by reference,” because Java object identifiers(according to that author) are actually “object references.”
And everything is actually pass by value. <br>
**So you’re not passing by reference, you’re “passing an object reference by value.”** 


[Basics of Java](/docs/CS/Java/JDK/Basic/Basic.md)



## Collection

The [Collection](/docs/CS/Java/JDK/Collection/Collection.md) in Java is a framework that provides an architecture to store and manipulate the group of objects.

## Concurrency

[Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)  is a process of executing multiple threads simultaneously.

## JVM

[JVM (Java Virtual Machine)](/docs/CS/Java/JDK/JVM/JVM.md) is an abstract machine. It is a specification that provides runtime environment in which java bytecode can be executed.

## Projects

- Amber
- Coin
- Graal
- jigsaw
- Kulla
- Panama
- Shenandoah
- Sumatra
- Tsan
- ZGC

### Valhalla

[Project Valhalla](/docs/CS/Java/JDK/Valhalla.md) plans to augment the Java object model with value objects and user-defined primitives, combining the abstractions of object-oriented programming with the performance characteristics of simple primitives.
These features will be complemented with changes to Java’s generics to preserve performance gains through generic APIs.

### Loom

[Project Loom](/docs/CS/Java/JDK/Loom.md)'s mission is to make it easier to write, debug, profile and maintain concurrent applications meeting today's requirements.

## Performance

The truth is that performance analysis is a weird blend of hard empiricism and squishy human psychology.
What matters is, at one and the same time, the absolute numbers of observable metrics and how the end users and stakeholders feel about them.

- No magic “go faster” switches for the JVM
- No “tips and tricks” to make Java run faster
- No secret algorithms that have been hidden from you

### Performance Metrics

One common basic set of performance metrics is:

- Throughput
- Latency
- Capacity
- Utilization
- Efficiency
- Scalability
- Degradation

#### Capacity

Capacity is usually quoted as the processing available at a given value of latency or throughput.

#### Efficiency

Dividing the throughput of a system by the utilized resources gives a measure of the overall efficiency of the system.
It is also possible, when one is dealing with larger systems, to use a form of cost accounting to measure efficiency.

#### Scalability

The holy grail of system scalability is to have throughput change exactly in step with resources.

#### Degradation

If we increase the load on a system, either by increasing the number of requests (or clients) or by increasing the speed requests arrive at, then we may see a change in the observed latency and/or throughput.
If the system is underutilized, then there should be some slack before observables change, but if resources are fully utilized then we would expect to see throughput stop increasing, or latency increase.
These changes are usually called the degradation of the system under additional load.

In rare cases, additional load can cause counterintuitive results.
For example, if the change in load causes some part of the system to switch to a more resource-intensive but higher-performance mode(such as JIT),
then the overall effect can be to reduce latency, even though more requests are being received.

`performance elbow`

## References

1. [The Java Language Environment: Contents A White Paper](https://www.oracle.com/java/technologies/language-environment.html)
2. [Java Performance Tuning](http://www.javaperformancetuning.com/)
3. [The Java Tutorial](https://docs.oracle.com/javase/tutorial/)
