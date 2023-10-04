## Introduction

- Concurrent
- Tracing
- Compacting
- Single generation
-
- Region-based
- NUMA-aware
- Load barriers
- Colored pointers

A core design principle/choice in ZGC is the use of **load barriers** in combination with **colored object pointers** (i.e., colored oops).

the colored-pointers scheme offers some very attractive properties. In particular:

- It allows us to reclaim and reuse memory during the relocation/compaction phase, before pointers pointing into the reclaimed/reused regions have been fixed.
  This helps keep the general heap overhead down. It also means that there is no need to implement a separate mark-compact algorithm to handle a full GC.
- It allows us to have relatively few and simple GC barriers. This helps keep the runtime overhead down.
  It also means that it's easier to implement, optimize and maintain the GC barrier code in our interpreter and JIT compilers.
- We currently store marking and relocation related information in the colored pointers.
  However, the versatile nature of this scheme allows us to store any type of information (as long as we can fit it into the pointer) and let the load barrier take any action it wants to based on that information.
  We believe this will lay the foundation for many future features.
  To pick one example, in a heterogeneous memory environment, this could be used to track heap access patterns to guide GC relocation decisions to move rarely used objects to cold storage.

From [ZGC The Next Generation Low-Latency Garbage Collector](http://cr.openjdk.java.net/~pliden/slides/ZGC-OracleDevLive-2020.pdf)

![](img/ZGC-Concurrent.png)

Regions

- Small 2MB for < 256KB
- Medium 32MB for 256KB <= <= 4MB
- Large N * 2MB

Colored Pointer/Tag Pointer/Version Pointer

- Pause Mark Start Scan thread stacks
- Concurrent Mark/Remap Walk object graph
- Pause Mark End Synchronization point
- Concurrent Prepare for Reloc. Reference processing Class unloading Relocation set selection
- Pause Relocate Start Scan thread stacks
- Concurrent Relocate Compact heap

### Colored Pointers

- Core design concept in ZGC
- Metadata stored in unused bits in 64-bit pointers

![](img/ZGC-Colored-Pointer.png)

### Load Barrier

A small piece of code injected by the JIT in strategic places

- When loading an **object reference** from the heap

Checks if the loaded object reference has a bad color

- If so, take action and heal it

Like

```java
String n = person.name;
```

### Generational ZGC

Young/Old Generation

- Exploit the fact that most objects are short-lived
  Benefits
- Withstand higher allocation rates
- Lower heap headroom
- Lower CPU usage

Applications running with Generational ZGC should enjoy

- Lower risks of allocations stalls,
- Lower required heap memory overhead, and
- Lower garbage collection CPU overhead.

In a future release we intend to make Generational ZGC the default, at which point `-XX:-ZGenerational` will select non-generational ZGC.

```shell
java -XX:+UseZGC -XX:+ZGenerational
```

Non-generational ZGC uses both colored pointers and load barriers.
Generational ZGC also uses store barriers to efficiently keep track of references from objects in one generation to objects in another generation.

A store barrier is a fragment of code injected by ZGC into the application wherever the application stores references into object fields.
Generational ZGC adds new metadata bits to colored pointers so that store barriers can determine if the field being written has already been recorded as potentially containing an inter-generational pointer.
Colored pointers make Generational ZGC's store barriers more efficient than traditional generational store barriers.
The addition of store barriers allows Generational ZGC to move the work of marking reachable objects from load barriers to store barriers.
That is, store barriers can use the metadata bits in colored pointers to efficiently determine if the object previously referred to by the field, prior to the store, needs to be marked.

Moving marking out of load barriers makes it easier to optimize them, which is important because load barriers are often more frequently executed than store barriers.
Now when a load barrier interprets a colored pointer it need only update the object address, if the object was relocated, and update the metadata to indicate that the address is known to be correct.
Subsequent load barriers will interpret this metadata and not check again whether the object has been relocated.

Generational ZGC uses distinct sets of marking and relocation metadata bits in colored pointers, so that the generations can be collected independently.

The remaining sections describe important design concepts that distinguish Generational ZGC from non-generational ZGC, and from other garbage collectors:

- No multi-mapped memory
- Optimized barriers
- Double-buffered remembered sets
- Relocations without additional heap memory
- Dense heap regions
- Large objects
- Full garbage collections

## References

1. [ZGC - by RednaxelaFX](https://www.zhihu.com/question/287945354/answer/458761494)
2. [The Pauseless GC Algorithm](https://www.usenix.org/legacy/events/vee05/full_papers/p46-click.pdf)
3. [The Z Garbage Collector Scalable Low-Latency GC in JDK 11](http://cr.openjdk.java.net/~pliden/slides/ZGC-OracleCodeOne-2018.pdf)
4. [JEP 333: ZGC: A Scalable Low-Latency Garbage Collector (Experimental)](https://openjdk.org/jeps/333)
5. [JEP 376: ZGC: Concurrent Thread-Stack Processing](https://openjdk.java.net/jeps/376)
6. [JEP 377: ZGC: A Scalable Low-Latency Garbage Collector (Production)](https://openjdk.java.net/jeps/377)
7. [JEP 439: Generational ZGC](https://openjdk.org/jeps/439)
