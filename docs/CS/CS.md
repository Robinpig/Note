## Introduction

## Computer Organization

[Computer Organization](/docs/CS/CO/CO.md)

## Operating System

[Operating System](/docs/CS/OS/OS.md) is a software above the hardware and  below applications.

## Algorithms

We describe [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures), methods of organizing large amounts of data, and [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis), the estimation of the running time of algorithms.

## Network

A [computer network](/docs/CS/CN/CN.md) is a set of computers sharing resources located on or provided by network nodes.

## DataBase

[DataBases](/docs/CS/DB/DB.md)

## Distributed Systems

A [distributed system](/docs/CS/Distributed/Distributed) is one in which components located at networked computers communicate and coordinate their actions only by passing messages.
This definition leads to the following especially significant characteristics of distributed systems:
concurrency of components, lack of a global clock and independent failures of components.


## MQ

[MQ](/docs/CS/MQ/MQ.md)

## Cloud Native

Cloud native practices empower organizations to develop, build, and deploy workloads in computing environments (public, private, hybrid cloud) to meet their organizational needs at scale in a programmatic and repeatable manner. It **is characterized by loosely coupled systems that interoperate in a manner that is secure, resilient, manageable, sustainable, and observable.**

Cloud native technologies and architectures typically consist of some combination of [containers](/docs/CS/Container/Container.md), service meshes, multi-tenancy, microservices, immutable infrastructure, serverless, and declarative APIs — this list is non-exhaustive.

## Programming Languages


| Programming Language                | Compile Type | Memory Management | Func Call |
| ----------------------------------- | ------------ | ----------------- | --------- |
| [C](/docs/CS/C/C.md)                |              |                   | Register  |
| [C++](/docs/CS/C++/C++.md)          |              |                   |           |
| [Golang](/docs/CS/Go/Go.md)         |              | GC                | Stack     |
| [Java](/docs/CS/Java/JDK/JDK.md)    |              | GC                | Stack     |
| [Python](/docs/CS/Python/Python.md) |              | GC                |           |
| [Rust](/docs/CS/Rust/Rust.md)       |              |                   |           |
| [Scala](/docs/CS/Scala/Scala.md)    |              |                   |           |
| [Flutter](/docs/CS/Flutter.md)      |              |                   |           |

不同语言的函数调用耗时有较大差异


## Frameworks

[etcd](/docs/CS/Framework/etcd/etcd.md)

##### Quartz

[Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md) can be used to create simple or complex schedules for executing tens, hundreds, or even tens-of-thousands of jobs.

##### Spring Framework

The [Spring Framework](/docs/CS/Framework/Spring/Spring.md) provides a comprehensive programming and configuration model for modern Java-based enterprise applications -
on any kind of deployment platform. makes programming Java quicker, easier, and safer for everybody.
Spring’s focus on speed, simplicity, and productivity has made it the world's most popular Java framework.

[Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md) makes it easy to create stand-alone, production-grade Spring based Applications that you can "just run".

[Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md) provides tools for developers to quickly build some of the common patterns in distributed systems
(e.g. configuration management, service discovery, circuit breakers, intelligent routing, micro-proxy, control bus,
one-time tokens, global locks, leadership election, distributed sessions, cluster state).

##### Netty

[Netty](/docs/CS/Framework/Netty/Netty.md) is a NIO client server framework which enables quick and easy development of network applications such as protocol servers and clients.
It greatly simplifies and streamlines network programming such as TCP and UDP socket server.

##### MyBatis

[MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md) is a first class persistence framework with support for custom SQL, stored procedures and advanced mappings.
MyBatis eliminates almost all of the JDBC code and manual setting of parameters and retrieval of results.
MyBatis can use simple XML or Annotations for configuration and map primitives, Map interfaces and Java POJOs (Plain Ordinary Java Objects) to database records.

##### Dubbo

[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) is a high-performance, java based open source RPC framework.

##### Tomcat

[The Apache Tomcat® software](/docs/CS/Framework/Tomcat/Tomcat.md) is an open source implementation of the Jakarta Servlet, Jakarta Server Pages,
Jakarta Expression Language, Jakarta WebSocket, Jakarta Annotations and Jakarta Authentication specifications.
These specifications are part of the Jakarta EE platform.

##### ZooKeeper

[Apache ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) is an effort to develop and maintain an open-source server which enables highly reliable distributed coordination.


##### Flink

[Flink](/docs/CS/Framework/Flink/Flink.md)


## Software Engineering

[Software Engineering](/docs/CS/SE/Engineering.md)

[Concurrency](/docs/CS/SE/Concurrency.md)

[Cache](/docs/CS/SE/Cache.md)

[Lock](/docs/CS/SE/Lock.md)

[Transaction](/docs/CS/SE/Transaction.md)


[Limiter](/docs/CS/SE/RateLimiter.md)

[Circuit Breaker](/docs/CS/SE/CircuitBreaker.md)



## Other Topics



[Browser](/docs/CS/Browser/Browser.md)


## The Turing Machine

A Turing machine is made of three components: a tape, a controller, and a read/write head.

The controller is the theoretical counterpart of the central processing unit (CPU) in modern computers. It is a finite state automaton, a machine that has a predetermined finite number of states and moves from one state to another based on the input.
At any moment, it can be in one of these states.

> The Church–Turing Thesis
>
> If an algorithm exists to do a symbol manipulation task, then a Turing machine exists to do that task.

Based on this claim, any symbol-manipulation task that can be done by writing an algorithm to do so can also be done by a Turing machine.
Note that this is only a thesis, not a theorem. A theorem can be proved mathematically, a thesis cannot. Although this thesis probably can never be proved, there are strong arguments in its favor.

- First, no algorithms have been found that cannot be simulated using a Turing machine.
- Second, it has been proven that all computing models that have been mathematically proved are equivalent to the Turing machine model.

In theoretical computer science, an unsigned number is assigned to every program that can be written in a specific language. This is usually referred to as the Gödel number, named after the Austrian mathematician Kurt Gödel.

> The halting problem is unsolvable.

Complexity of solvable problems:

- Polynomial problems
- Non polynomial problems

## Artificial Intelligence

Artificial intelligence is the study of programmed systems that can simulate, to some extent, human activities such as perceiving, thinking, learning, and acting.

### The Turing test

In 1950, Alan Turing proposed the Turing Test, which provides a definition of intelligence in a machine.
The test simply compares the intelligent behavior of a human being with that of a computer.
An interrogator asks a set of questions that are forwarded to both a computer and a human being.
The interrogator receives two sets of responses, but does not know which set comes from the human and which set from the computer.
After careful examination of the two sets, if the interrogator cannot definitely tell which set has come from the computer and which from the human, the computer has passed the Turing test for intelligent behavior.

## References

1. [Foundations of Computer Science]()
2. [CS自学指南](https://csdiy.wiki/)
