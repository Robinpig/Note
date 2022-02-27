## Introduction

[Project Loom](https://cr.openjdk.java.net/~rpressler/loom/Loom-Proposal.html) is to intended to explore, incubate and deliver Java VM features and APIs built on top of them for the purpose of supporting easy-to-use, high-throughput lightweight concurrency and new programming models on the Java platform. This is accomplished by the addition of the following constructs:

- Virtual threads
- Delimited continuations
- Tail-call elimination

Project Loom will introduce fibers as lightweight, efficient threads managed by the Java Virtual Machine, that let developers use the same simple abstraction but with better performance and lower footprint.
A fiber is made of two components — a continuation and a scheduler.
As Java already has an excellent scheduler in the form of `ForkJoinPool`, fibers will be implemented by adding continuations to the JVM.

## What Threads Are

Currently, the thread construct offered by the Java platform is the [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md) class, which is implemented by a kernel thread; it relies on the OS for the implementation of both the continuation and the scheduler.

## Continuations

The motivation for adding continuations to the Java platform is for the implementation of fibers, but continuations have some other interesting uses, and so it is a secondary goal of this project to provide continuations as a public API.

## Fibers

Fibers are, then, what we call Java's planned user-mode threads.

## Schedulers

As mentioned above, work-stealing schedulers like `ForkJoinPools` are particularly well-suited to scheduling threads that tend to block often and communicate over IO or with other threads. Fibers, however, will have pluggable schedulers, and users will be able to write their own ones (the SPI for a scheduler can be as simple as that of `Executor`). Based on prior experience, it is expected that `ForkJoinPool` in asynchronous mode can serve as an excellent default fiber scheduler for most uses, but we may want to explore one or two simpler designs, as well, such as a pinned-scheduler, that always schedules a given fiber to a specific kernel thread (which is assumed to be pinned to a processor).


## Demo

```java

public class ThreadDemo {

    public static void main(String[] args) throws InterruptedException {
        Thread thread = Thread.ofVirtual().start(() -> System.out.println("Hello"));
        thread.join();
    }
}
```

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)

## References
1. [Project Loom: Fibers and Continuations for the Java Virtual Machine](https://cr.openjdk.java.net/~rpressler/loom/Loom-Proposal.html)