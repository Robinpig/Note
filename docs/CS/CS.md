## Introduction

### Computer Organization

[Computer Organization](/docs/CS/CO/CO.md)

### Operating System

[Operating System](/docs/CS/OS/OS.md) is a software above the hardware and  below applications.

### Algorithms

We describe [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures), methods of organizing large amounts of data, and [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis), the estimation of the running time of algorithms.

### Network

A [computer network](/docs/CS/CN/CN.md) is a set of computers sharing resources located on or provided by network nodes.

### DataBase

[DataBases](/docs/CS/DB/DB.md)

### Distributed Systems

A [distributed system](/docs/CS/Distributed/Distributed_Systems.md) is one in which components located at networked computers communicate and coordinate their actions only by passing messages.
This definition leads to the following especially significant characteristics of distributed systems:
concurrency of components, lack of a global clock and independent failures of components.

[Transaction](/docs/CS/SE/Transaction.md)

### MQ

[MQ](/docs/CS/MQ/MQ.md)

## Cloud Native

Cloud native practices empower organizations to develop, build, and deploy workloads in computing environments (public, private, hybrid cloud) to meet their organizational needs at scale in a programmatic and repeatable manner. It **is characterized by loosely coupled systems that interoperate in a manner that is secure, resilient, manageable, sustainable, and observable.**

Cloud native technologies and architectures typically consist of some combination of [containers](/docs/CS/Container/Container.md), service meshes, multi-tenancy, microservices, immutable infrastructure, serverless, and declarative APIs — this list is non-exhaustive.

### Programming Languages


| Programming Language                | Compile Type | Usage |
|-------------------------------------|--------------|-------|
| [C](/docs/CS/C/C.md)                |              |       |
| [C++](/docs/CS/C++/C++.md)          |              |       |
| [Golang](/docs/CS/Go/Go.md)         |              |       |
| [Java](/docs/CS/Java/JDK/JDK.md)    |              |       |
| [Python](/docs/CS/Python/Python.md) |              |       |
| [Rust](/docs/CS/Rust/Rust.md)       |              |       |
| [Scala](/docs/CS/Scala/Scala.md)    |              |       |
| [Flutter](/docs/CS/Flutter.md)      |              |       |



### Frameworks

[etcd](/docs/CS/Framework/etcd/etcd.md)

##### Quartz

[Quartz](/docs/CS/Framework/Quartz/Quartz.md) can be used to create simple or complex schedules for executing tens, hundreds, or even tens-of-thousands of jobs.

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

## Other Topics

[Concurrency](/docs/CS/SE/Concurrency.md)

[Cache](/docs/CS/SE/Cache.md)

[Lock](/docs/CS/SE/Lock.md)

[Limiter](/docs/CS/RateLimiter)

[Circuit Breaker](/docs/CS/SE/CircuitBreaker.md)

[Encoding](/docs/CS/Security/Encoding.md)

[Browser](/docs/CS/Browser.md)

Ints are not Integers, Floats are not Reals.

IEEE Standard 754 Floating Point Numbers

IEEE 754 has 3 basic components:

1. **The Sign of Mantissa**
   This is as simple as the name. 0 represents a positive number while 1 represents a negative number.
2. **The Biased exponent**
   The exponent field needs to represent both positive and negative exponents. A bias is added to the actual exponent in order to get the stored exponent.
3. **The Normalised Mantissa**
   The mantissa is part of a number in scientific notation or a floating-point number, consisting of its significant digits.
   Here we have only 2 digits, i.e. O and 1. So a normalised mantissa is one with only one 1 to the left of the decimal.
   IEEE 754 numbers are divided into two based on the above three components: single precision and double precision.

Number Systems

## Data Compression

Compressing data can reduce the amount of data to be sent or stored by partially eliminating inherent redundancy. Redundancy is created when we produce data.
Through data compression, we make transmission and storage more efficient, and at the same time, we preserve the integrity of the data.

### Lossless Data Compression

In lossless data compression, the integrity of the data is preserved.
The original data and the data after compression and decompression are exactly the same because, in these methods, the compression and decompression algorithms are exact inverses of each other: no part of the data is lost in the process.
Redundant data is removed in compression and added during decompression.

Lossless compression methods are normally used when we cannot afford to lose any data. For example, we must not lose data when we compress a text file or an application program.

We discuss three lossless compression methods in this section: run-length encoding, Huffman coding, and the Lempel Ziv algorithm.

Run-length encoding is probably the simplest method of compression. It can be used to compress data made of any combination of symbols.
It does not need to know the frequency of occurrence of symbols (as is necessary for Huffman coding) and can be very efficient if data is represented as 0s and 1s.

Huffman coding assigns shorter codes to symbols that occur more frequently and longer codes to those that occur less frequently.

Lempel Ziv (LZ) encoding, named after its inventors (Abraham Lempel and Jacob Ziv), is an example of a category of algorithms called dictionary-based encoding.
The idea is to create a dictionary (a table) of strings used during the communication session.
If both the sender and the receiver have a copy of the dictionary, then previously encountered strings can be substituted by their index in the dictionary to reduce the amount of information transmitted.

### Lossy Data Compression

## Security

As an asset, information needs to be secured from attacks.
To be secure, information needs to be hidden from unauthorized access (*confidentiality*), protected from unauthorized change(*integrity*), and available to an authorized entity when it is needed (*availability*).

### Attacks

In general, two types of attacks threaten the confidentiality of information: snooping and traffic analysis.

The integrity of data can be threatened by several kinds of attacks: modification, masquerading, replaying, and repudiation.

We mention only one attack threatening availability: *denial of service*.

### Services and techniques

ITU-T defines some security services to achieve security goals and prevent attacks.
Each of these services is designed to prevent one or more attacks while maintaining security goals. The actual implementation of security goals needs some techniques.
Two techniques are prevalent today: one is very general (cryptography) and one is specific (steganography).

#### Cryptography

Cryptography, a word with Greek origins, means ‘secret writing’. However, we use the term to refer to the science and art of transforming messages to make them secure and immune to attacks.
Although in the past cryptography referred only to the encryption and decryption of messages using secret keys, today it is defined as involving three distinct mechanisms: symmetric-key encipherment, asymmetric-key encipherment, and hashing.

#### Steganography

The word steganography, with origins in Greek, means ‘covered writing’, in contrast to cryptography, which means ‘secret writing’.
Cryptography means concealing the contents of a message by enciphering; steganography means concealing the message itself by covering it with something else.

### Confidentiality

Confidentiality can be achieved using ciphers. Ciphers can be divided into two broad categories: symmetric-key and asymmetric-key.

### Message integrity

One way to preserve the integrity of a document is through the use of a *fingerprint*.
To preserve the integrity of a message, the message is passed through an algorithm called a **cryptographic hash function**.
The function creates a compressed image of the message, called a digest, that can be used like a fingerprint.

> The message digest needs to be safe from change.

A MAC provides message integrity and message authentication using a combination of a hash function and a secret key.

### Digital signature

A digital signature uses a pair of private–public keys.

### 故障演练

故障模拟

故障主要分三类

- **中间件服务故障**，如模拟hsf调用方异常，tddl调用异常等。
- **机器故障**，如网络延迟，网络丢包等。
- **第三方故障**，如mysql响应延迟等。

故障演练的范围可以细化到应用，机房，甚至某个具体虚拟机。

参考alibaba Monkeyking

## Theory of Computation

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
