## Introduction


## Memory management



Memory management is the art and the process of coordinating and controlling the use of [memory (1)](https://www.memorymanagement.org/glossary/m.html#term-memory-1) in a computer system.

Memory management can be divided into three areas:

1. Memory management hardware ([MMUs](https://www.memorymanagement.org/glossary/m.html#term-mmu), [RAM](https://www.memorymanagement.org/glossary/r.html#term-ram), etc.);
2. Operating system memory management ([virtual memory](https://www.memorymanagement.org/glossary/v.html#term-virtual-memory), [protection](https://www.memorymanagement.org/glossary/p.html#term-protection));
3. Application memory management ([allocation](https://www.memorymanagement.org/glossary/a.html#term-allocate), [deallocation](https://www.memorymanagement.org/glossary/f.html#term-free-1), [garbage collection](https://www.memorymanagement.org/glossary/g.html#term-garbage-collection)).



[Garbage collection](/docs/CS/memory/GC.md) (GC), also known as automatic memory management, is the automatic recycling of dynamically allocated memory. 
Garbage collection is performed by a garbage collector which recycles memory that it can prove will never be used again. 
Systems and languages which use garbage collection can be described as garbage-collected.

Garbage collection is a tried and tested memory management technique that has been in use since its invention in the 1950s.
It avoids the need for the programmer to deallocate memory blocks explicitly, thus avoiding a number of problems: memory leaks, double frees, and premature frees.
The burden on the programmer is reduced by not having to investigate such problems, thereby increasing productivity.

Garbage collection can also dramatically simplify programs, chiefly by allowing modules to present cleaner interfaces to each other: the management of object storage between modules is unnecessary.

It is not possible, in general, for a garbage collector to determine exactly which objects are still live. 
Even if it didn’t depend on future input, there can be no general algorithm to prove that an object is live (cf. the Halting Problem).
All garbage collectors use some efficient approximation to liveness. In tracing garbage collection, the approximation is that an object can’t be live unless it is reachable.
In reference counting, the approximation is that an object can’t be live unless it is referenced. 
Hybrid algorithms are also possible. Often the term garbage collection is used narrowly to mean only tracing garbage collection.

## Links

- [Operating Systems memory](/docs/CS/OS/OS.md)

## References

1. [Memory Management Reference](https://www.memorymanagement.org/)
