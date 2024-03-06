## Introduction

Virtual threads are lightweight threads that dramatically reduce the effort of writing, maintaining, and observing high-throughput concurrent applications.


A platform thread is implemented as a thin wrapper around an operating system (OS) thread.
A platform thread runs Java code on its underlying OS thread, and the platform thread captures its OS thread for the platform thread's entire lifetime. 
Consequently, the number of available platform threads is limited to the number of OS threads.

Platform threads typically have a large thread stack and other resources that are maintained by the operating system. 
They are suitable for running all types of tasks but may be a limited resource.


Like a platform thread, a virtual thread is also an instance of `java.lang.Thread`. 
However, a virtual thread isn't tied to a specific OS thread. A virtual thread still runs code on an OS thread. 
However, when code running in a virtual thread calls a blocking I/O operation, the Java runtime suspends the virtual thread until it can be resumed. 
The OS thread associated with the suspended virtual thread is now free to perform operations for other virtual threads.

Virtual threads are implemented in a similar way to virtual memory.
To simulate a lot of memory, an operating system maps a large virtual address space to a limited amount of RAM. 
Similarly, to simulate a lot of threads, the Java runtime maps a large number of virtual threads to a small number of OS threads.

Unlike platform threads, virtual threads typically have a shallow call stack, performing as few as a single HTTP client call or a single JDBC query.
Although virtual threads support thread-local variables and inheritable thread-local variables,
you should carefully consider using them because a single JVM might support millions of virtual threads.

Virtual threads are suitable for running tasks that spend most of the time blocked, often waiting for I/O operations to complete.
However, they aren't intended for long-running CPU-intensive operations.

Use virtual threads in high-throughput concurrent applications, especially those that consist of a great number of concurrent tasks that spend much of their time waiting. 
Server applications are examples of high-throughput applications because they typically handle many client requests that perform blocking I/O operations such as fetching resources.

Virtual threads are not faster threads; they do not run code any faster than platform threads.
They exist to provide scale (higher throughput), not speed (lower latency).



## Links

- [Java Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)


## References

1. [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)