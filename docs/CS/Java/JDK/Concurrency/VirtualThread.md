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

## Links

- [Java Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)