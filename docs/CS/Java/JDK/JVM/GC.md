## Introduction 

Almost all modern programming languages make use of dynamic memory allocation.
This allows objects to be allocated and deallocated even if their total size was not known at the time that the program was compiled, 
and if their lifetime may exceed that of the subroutine activation1 that allocated them. 
A dynamically allocated object is stored in a heap, 
rather than on the `stack` (in the `activation record` or `stack frame` of the procedure that allocated it) 
or `statically` (whereby the name of an object is bound to a storage location known at compile or link time). 

Heap allocation is particularly important because it allows the programmer:
- to choose dynamically the size of new objects (thus avoiding program failure through exceeding hard-coded limits on arrays);
- to define and use recursive data structures such as lists, trees and maps;
- to return newly created objects to the parent procedure (allowing, for example, factory methods);
- to return a function as the result of another function (for example, closures or suspensions in functional languages).

Heap allocated objects are accessed through `references`. 
Typically, a reference is a pointer to the object (that is, the address in memory of the object). 
However, a reference may alternatively refer to an object only indirectly, for instance through a handle which in turn points to the object. 
Handles offer the advantage of allowing an object to be relocated (updating its handle) without having to change every reference to that object/handle throughout the program.

Memory used by heap objects can be reclaimed using *explicit deallocation* (for example, with C's `free` or C++'s `delete` operator) or automatically by the run-time system,
using reference counting or a tracing garbage collector.

### Explicit deallocation

Manual reclamation risks programming errors; these may arise in two ways.
- Memory may be freed prematurely, while there are still references to it. Such a reference is called a `dangling pointer`.
- The second kind of error is that the programmer may fail to free an object no longer required by the program, leading to a `memory leak`.

The issue is more fundamental than simply being a matter of programmers needing to take more care. Difficulties of correct memory management are often inherent to the programming problem in question.
More generally, safe deallocation of an object is complex because, as Wilson points out, "**liveness is a global property**", whereas the decision to call `free` on a variable is a local one.

So how do programmers cope in languages not supported by automatic dynamic memory management?
The key advice has been to be consistent in the way that they manage the `ownership` of objects. 

Belotsky and others offer several possible strategies for C++.
- First, programmers should avoid heap allocation altogether, wherever possible. For example, objects can be allocated on the stack instead. 
  When the objects' creating method returns, the popping of the stack will free these objects automatically. 
- Secondly, programmers should pass and return objects by value, by copying the full contents of a parameterIresult rather than by passing references. 
  Clearly both of these approaches remove all allocation/deallocation errors but they do so at the cost of both increased memory pressure and the loss of sharing.
- In some circumstances it may be appropriate to use custom allocators, for example, that manage a pool of objects. 
  At the end of a program phase, the entire pool can be freed as a whole.
  




### Automatic dynamic memory management
Automatic dynamic memory management resolves many of these issues.
`Garbage collection`(GC) prevents dangling pointers being created: an object is reclaimed only when there is no pointer to it from a reachable object. 
Conversely, in principle all garbage is guaranteed to be freed - any object that is unreachable will eventually be reclaimed by the collector - with two caveats. 
- The first is that `tracing collection` uses a definition of 'garbage' that is decidable and may not include all objects that will never be accessed again. 
- The second is that in practice, garbage collector implementations may choose for efficiency reasons not to reclaim some objects. 
Only the collector releases objects so the `double-freeing` problem cannot arise. 
All reclamation decisions are deferred to the collector, which has global knowledge of the structure of objects in the heap and the threads that can access them. 
The problems of explicit deallocation were largely due to the difficulty of making a global decision in a local context. 
Automatic dynamic memory management simply finesses this problem

Above all, memory management is a software engineering issue. 
Well-designed programs are built from components (in the loosest sense of the term) that are highly cohesive and loosely coupled.
Increasing the cohesion of modules makes programs easier to maintain. 
Ideally, a programmer should be able to understand the behaviour of a module from the code of that module alone, or at worst a few closely related modules. 
Reducing the coupling between modules means that the behaviour of one module is not dependent on the implementation of another module. 
As far as correct memory management is concerned, this means that modules should not have to know the rules of the memory management game played by other modules. 
In contrast, *explicit memory management* goes against sound software engineering principles of minimal communication between components;
it clutters interfaces, either explicitly through additional parameters to communicate ownership rights, or implicitly by requiring programmers to conform to particular idioms. 
Requiring code to understand the rules of engagement limits the reusability of components.

The key argument in favour of garbage collection is not just that it **simplifies coding** - which it does - 
but that it uncouples the problem of memory management from interfaces, rather than scattering it throughout the code. **It improves reusability.**

We do not claim that garbage collection is a silver bullet that will eradicate all memoryrelated programming errors or that it is applicable in all situations.
Although garbage collection tends to reduce the chance of memory leaks, it does not guarantee to eliminate them.
It has no answer to the problem of a data structure that is still reachable, 
but grows without limit (for example, if a programmer repeatedly adds data to a cache but never removes objects from that cache), 
or that is reachable and simply never accessed again.

Automatic dynamic memory management is designed to do just what it says.
Nevertheless, the problem of *general resource management* in a garbage collected language is a substantial one. 
With explicitly-managed systems there is a straightforward and natural coupling between memory reclamation and the disposal of other resources. 
Automatic memory management introduces the problem of how to structure resource management in the absence of a natural coupling. 
However, it is interesting to observe that many resource release scenarios require something akin to a collector in order to detect whether the resource is still in use(reachable) from the rest of the program.


### Comparing garbage collection algorithms
Unfortunately, it is never possible to identify a 'best' collector for all configurations.
Comparisons are difficult in both principle and practice.
Details of implementation, locality and the practical significance of the constants in algorithmic complexity formulae make them less than perfect guides to practice.
Moreover, the metrics are not independent variables.
Not only does the performance of an algorithm depend on the topology and volume of objects in the heap, but also on the access patterns of the application.
Worse, the tuning options in production virtual machines are inter-connected.

- Safety
- Throughput
- Completeness and promptness
- Pause time
- Space overhead
- Optimisations for specific languages
- Scalability and portability

### performance

Nevertheless, a long running criticism of garbage collection has been that it is slow compared to explicit memory management and imposes unacceptable overheads, 
both in terms of overall throughput and in pauses for garbage collection. 
While it is true that automatic memory management does impose a performance penalty on the program, it is not as much as is commonly assumed.

Although, as expected, results varied between both collectors and explicit allocators, Hertz *et al* found garbage collectors could match the
execution time performance of explicit allocation provided they were given a sufficiently large heap (five times the minimum required). 
For more typical heap sizes, the garbage collection overhead increased to 17% on average.




## Algorithms
All garbage collection schemes are based on one of four fundamental approaches: marksweep collection, copying collection, mark-compact collection or reference counting. 
Different collectors may combine these approaches in different ways, for example, by collecting one region of the heap with one method and another part of the heap with a second method.
The next four chapters focus on these four basic styles of collection.

The goal of an ideal garbage collector is to reclaim the space used by every object that will no longer be used by the program. 
Any automatic memory management system has three tasks:
1. to allocate space for new objects;
2. to identify live objects; and
3. to reclaim the space occupied by dead objects. 
   
These tasks are not independent. In particular, the way space is reclaimed affects how fresh space is allocated.

### The tricolour abstraction

It is very convenient to have a concise way to describe the state of objects during a collection (have they been marked, are they in the work list, and so on). 
The tricolour abstraction is a useful characterisation of tracing collectors that permits reasoning about collector correctness in terms of invariants that the collector must preserve.
Under the tricolour abstraction, tracing collection partitions the object graph into black(presumed live) and white (possibly dead) objects. 
Initially, every node is white; when a node is first encountered during tracing it is coloured grey; 
when it has been scanned and its children identified, it is shaded black. 
Conceptually, an object is black if the collector has finished processing it, and grey if the collector knows about it but has not yet finished processing it (or needs to process it again). 
By analogy with object colour, fields can also be given a colour: grey when the collector first encounters them, and black once traced by the collector. 
This analogy also allows reasoning about the mutator roots as if the mutator were an object. 
A grey mutator has roots that have not yet been scanned by the collector. 
A black mutator has roots that have already been scanned by the collector(and do not need to be scanned again). 
Tracing makes progress through the heap by moving the collector wavefront (the grey objects) separating black objects from white objects until all reachable objects have been traced black.

### Bitmap marking
Space for a mark-bit can usually be found in an object header word. 
Alternatively, markbits can be stored in a separate bitmap table to the side of the heap, with a bit associated with every address at which an object might be allocated.
Instead of a bitmap, byte-maps are commonly used (at the cost of an 8-fold increase in space), thereby making marking races benign.
Alternatively, a bitmap must use a synchronised operation to set a bit.

Mark bitmaps have a number of potential advantages.

A bitmap stores marks much more densely than if they are stored in object headers.
With a bitmap, marking will not modify any object, but will only read pointer fields of live objects.
Bitmap marking is likely to modify fewer words, and to dirty fewer cache lines so less data needs to be written back to memory.

Bitmap marking was originally adopted for a *conservative collector* designed to provide automatic memory management for uncooperative languages like C and C++.

Bitmap marking was also motivated by the concern to minimise the amount of paging caused by the collector.
It allows the mark-bits of clusters of objects to be tested and cleared in groups as the common case will be that either every bit/byte is set or every bit/byte is clear in a map word.
A corollary is that it is simple from the bitmap to determine whether a complete block of objects is garbage, thus allowing the whole block to be returned to the allocator.


Many memory managers use a block structured heap (for example, Boehm and Weiser). 
A straightforward implementation might reserve a prefix of each block for its bitmap. 
As previously discussed this leads to unnecessary cache conflicts and page accesses, so collectors tend to store bitmaps separately from user data blocks.

### Mark-sweep

It is a straightforward embodiment of the recursive definition of pointer reachability. Collection
operates in two phases. 
- First, the collector traverses the graph of objects, starting from the roots (registers, thread stacks, global variables) through 
which the program might immediately access objects and then following pointers and marking each object that it finds. 
Such a traversal is called `tracing`. 
- In the second, sweeping phase, the collector examines every object in the heap: any unmarked object is deemed to be garbage and its space reclaimed.

Mark-sweep is an indirect collection algorithm. It does not detect garbage per se, but rather identifies all the live objects and then concludes that anything else must be garbage.
Note that it needs to recalculate its estimate of the set of live objects at each invocation.

Note that the mark-sweep collector imposes constraints upon the heap layout. 
- First, this collector does not move objects.
The memory manager must therefore be careful to try to reduce the chance that the heap becomes so fragmented that the allocator finds it difficult to meet new requests, 
which would lead to the collector being called too frequently, or in the worst case, preventing the allocation of new memory at all. 
- Second, the sweeper must be able to find each node in the heap.
  In practice, given a node, sweep must be able to find the next node even in the presence of padding introduced between objects in order to observe alignment requirements.


#### Lazy sweeping
The complexity of the mark phase is O(L), where L is the size of the live data in the heap;
the complexity of the sweep phase is O(H) where H is the size of the heap. Since H > L, at
first sight it might seem that the mark-sweep algorithm is dominated by the cost of sweeping.
However, in practice, this is not the case. Chasing pointers in the mark phase leads
to unpredictable memory access patterns, whereas sweep behaviour is more predictable.
Further, the cost of sweeping an object tends to be much less than the cost of tracing it.

One way to improve the cache behaviour of the sweep phase is to prefetch objects. 
In order to avoid fragmentation, allocators supporting mark-sweep collectors typically lay out objects of the same size consecutively leading to a fixed stride as a block of same-sized objects is swept. 
Not only does this pattern allow software prefetching, but it is also ideal for the hardware prefetching mechanisms found in modem processors.

Lazy sweeping offers a number of benefits. It has good locality: object slots tend to be used soon after they are swept. 
It reduces the algorithmic complexity of mark-sweep to be proportional to the size of the live data in the heap, the same as semispace copying collection. 
In particular, Boehm suggests that mark and lazy sweep will perform best in the same circumstance that copying performs best:
when most of the heap is empty, as the lazy sweep's search for unmarked objects will terminate quickly. 
In practice, the mutator's cost of initialising objects is likely to dominate the cost of sweeping and allocation.

Mark-sweep has significantly better space usage than approaches based on semispace copying. 
It also potentially has better space usage than reference counting algorithms.

However, mark-sweep is a **tracing algorithm**. Like other tracing algorithms, it must identify all live objects in a space before it can reclaim the memory used by any dead objects. 
This is an expensive operation and so should be done infrequently. This means that tracing collectors must be given some headroom in which to operate in the heap. 
If the live objects occupy too large a proportion of the heap, and the allocators allocate too fast, then a `mark-sweep collector` will be called too often: it will thrash. 
For moderate to large heaps, the headroom necessary may be between 20% and 50% of the heap though Hertz and Berger show that, in order to provide the same throughput,
Java programs managed by mark-sweep collection may need a heap several times larger than if it were to be managed by explicit deallocation.


### Mark-compact

The major benefit of a compacted heap is that it allows very fast, sequential allocation, 
simply by testing against a heap limit and 'bumping' a free pointer by the size of the allocation request.

Mark-compact algorithms operate in a number of phases. The first phase is always a
marking phase, which we discussed in the previous chapter. Then, further compacting
phases compact the live data by relocating objects and updating the pointer values of all
live references to objects that have moved. The number of passes over the heap, the order
in which these are executed and the way in which objects are relocated varies from algorithm to algorithm. The compaction order has locality implications. Any moving collector
may rearrange objects in the heap in one of three ways.

- Arbitrary: objects are relocated without regard for their original order or whether they
point to one another.
- Linearising: objects are relocated so that they are adjacent to related objects, such as ones
to which they refer, which refer to them, which are siblings in a data structure, and
so on, as far as this is possible.
- Sliding: objects are slid to one end of the heap, squeezing out garbage, thereby maintaining their original allocation order in the heap

Most compacting collectors of which we are aware use arbitrary or sliding orders.
All modern mark-compact collectors implement sliding compaction, which does not interfere with mutator locality by changing the relative order of object placement.

All compaction algorithms are invoked as follows:
```
atomic collect():
    markFromRoots()
    compact()
```
Mark-compact collectors eliminate fragmentation and support very fast, 'bump a pointer' allocation but require multiple passes over live objects, and significantly increase collection times.


### Copying

Basic copying collectors divide the heap into two, equally sized semispaces, called *fromspace* and *tospace*.

Unlike most mark-compact collectors, semispace copying does not require any extra space in object headers.


### References Counting

Reference counting maintains a simple invariant: an object is presumed to be live if and only if the number of references to that object is greater than zero.
*Reference listing algorithms*, commonly used by distributed systems such as Java's RMI libraries, 
modify this invariant so that an object is deemed to be live if and only if the set of clients believed to be holding a reference to the object is non-empty. 
This offers certain fault tolerance benefits, for example, set insertion or deletion is idempotent, unlike counter arithmetic.

Potentially, reference counting can recycle memory as soon as an object becomes garbage (but we shall see below why this may not always be desirable). 
Consequently, it may continue to operate satisfactorily in a nearly full heap, unlike tracing collectors which need some headroom. 
Since reference counting operates directly on the sources and targets of pointers, the locality of a reference counting algorithm may be no worse than that of its client program. 
Client programs can use destructive updates rather than copying objects if they can prove that an object is not shared. 
Reference counting can be implemented without assistance from or knowledge of the run-time system. 
In particular, it is not necessary to know the roots of the program. Reference counting can reclaim some memory even if parts of the system are unavailable: this is particularly useful in distributed systems.


Unfortunately, there are also a number of disadvantages to reference counting. 

First, reference counting imposes a time overhead on the mutator. 
In contrast to the tracing algorithms we considered in earlier chapters, algorithm redefined all pointer Read and Write operations in order to manipulate reference counts. 
Even non-destructive operations such as iteration require the reference counts of each element in the list to be incremented and then decremented as a pointer moves across a data structure such as a list.
From a performance point of view, it is particularly undesirable to add overhead to operations that manipulate registers or thread stack slots. 
For this reason alone, this naive algorithm is impractical for use as a general purpose, high volume, high performance memory manager. 
Fortunately, as we shall see, the cost of reference counted pointer manipulations can be reduced substantially.

Second, both the reference count manipulations and the pointer load or store must be a single atomic action 
in order to prevent races between mutator threads which would risk premature reclamation of objects.

Third, naive reference counting turns read-only operations into ones requiring stores to memory (to update reference counts).
Similarly, it requires reading and writing the old referent of a pointer field when changing that field to refer to a different object. 
These writes 'pollute' the cache and induce extra memory traffic

Fourth, reference counting cannot reclaim cyclic data structures (that is, data structures that contain references to themselves).

Fifth, in the worst case, the number of references to an object could be equal to the number of objects in the heap.
This means that the reference count field must be pointer sized, that is, a whole slot.

Finally, reference counting may still induce pauses.

we can resolve two of the major problems facing reference counting: the cost of reference count manipulations and collecting cyclic garbage.
It turns out that common solutions to both of these problems involve a stop-the-world pause.


Manipulating reference counts is expensive compared with the cost to the mutator of simple tracing algorithms.
Reference counting is attractive for the promptness with which it reclaims garbage objects and its good locality properties.
- Simple reference counting can reclaim the space occupied by an object as soon as the last pointer to that object is removed. 
  Its operation involves only the targets of old and new pointers read or written, unlike tracing collection which visits every live object in the heap. 
  However, these strengths are also the weaknesses of simple reference counting. 
  Because it cannot reclaim an object until the last pointer to that object has been removed, it cannot reclaim cycles of garbage. 
- Reference counting taxes every pointer read and write operation and thus imposes a much larger tax on throughput than tracing does. 
- Furthermore, multithreaded applications require the manipulation of reference counts and updating of pointers to be expensively synchronised. 
  This tight coupling of mutator actions and memory manager risks some fragility, especially if 'unnecessary' reference count updates are optimised away by hand. 
- Finally, reference counts increase the sizes of objects.

## Generational Garbage Collection
The goal of a collector is to find dead objects and reclaim the space they occupy. 
Tracing collectors (and copying collectors in particular) are most efficient if the space they manage contains few live objects. 
On the other hand, long-lived objects are handled poorly if the collector processes them repeatedly, 
either marking and sweeping or copying them again and again from one semispace to another. 
Long-lived objects tend to accumulate in the bottom of a heap managed by a mark-compact collector, and that some collectors avoid compacting this dense prefix. 
While this eliminates the cost of relocating these objects, they must still be traced and all references they contain must be updated.

Generational collectors extend this idea by not considering the oldest objects whenever possible. 
By concentrating reclamation effort on the youngest objects in order to exploit the weak generational hypothesis that most objects die young, 
they hope to maximise yield(recovered space) while minimising effort.
Generational collectors segregate objects by age into generations, typically physically distinct areas of the heap. 
Younger generations are collected in preference to older ones, 
and objects that survive long enough are promoted(or tenured) from the generation being collected to an older one.

Most generational collectors manage younger generations by copying. 
If, as expected, few objects are live in the generation being collected, 
then the mark/cons ratio between the volume of data processed by the collector and the volume allocated for that collection will be low. 
The time taken to collect the youngest generation (or nursery) will in general depend on its size. 
By tuning its size, we can control the expected pause times for collection of a generation. 
Young generation pause times for a well configured collector (running an application that conforms to the weak generational hypothesis) are typically of the order of ten milliseconds on current hardware. 
Provided the interval between collections is sufficient, such a collector will be unobtrusive to many applications.

Occasionally a generational collector must collect the whole heap, 
for example when the allocator runs out of space and the collector estimates that insufficient space would be recovered by collecting only the younger generations. 
Generational collection therefore improves only expected pause times, not the worst case. On its own, it is not sufficient for real-time systems.

Generational collection can also improve throughput by avoiding repeatedly processing long-lived objects. 
However, there are costs to pay. Any garbage in an old generation cannot be reclaimed by collection of younger generations: collection of long-lived objects that become garbage is not prompt. 
In order to be able to collect one generation without collecting others, 
generational collectors impose a bookkeeping overhead on mutators in order to track references that span generations, 
an overhead hoped to be small compared to the benefits of generational collection. 
Tuning generational collectors to meet throughput and pause-time goals simultaneously is a subtle art.



### Generational hypotheses
The weak generational hypothesis, that most objects die young, appears to be widely valid, regardless of programming paradigm or implementation language.

Generation see https://dl.acm.org/doi/10.1145/800020.80826

Generational garbage collectors need to keep track of references from older to younger generations so that younger generations can be garbage-collected without inspecting every object in the older generation(s). The set of locations potentially containing pointers to newer objects is often called the `remembered set`. 

At every store, the system must ensure that the updated location is added to the `remembered set` if the store creates a reference from an older to a newer object. This mechanism is usually referred to as a `write barrier` or `store check`.

On the other hand, there is much less evidence for the `strong generational hypothesis` that, even for objects that are not newly-created, younger objects will have a lower survival rate than older ones.

1. Card Marking
2. Two-Instruction





### Young Generation
Newly created objects start in the Young Generation. The Young Generation is further subdivided into:
- Eden space - all new objects start here, and initial memory is allocated to them
- Survivor spaces (FromSpace and ToSpace) - objects are moved here from Eden after surviving one garbage collection cycle.

When objects are garbage collected from the Young Generation, it is a `minor garbage collection` event.

When Eden space is filled with objects, a Minor GC is performed. 
All the dead objects are deleted, and all the live objects are moved to one of the survivor spaces. 
Minor GC also checks the objects in a survivor space, and moves them to the other survivor space.

Take the following sequence as an example:
- Eden has all objects (live and dead)
- Minor GC occurs - all dead objects are removed from Eden. All live objects are moved to S1 (FromSpace). Eden and S2 are now empty.
- New objects are created and added to Eden. Some objects in Eden and S1 become dead.
- Minor GC occurs - all dead objects are removed from Eden and S1. All live objects are moved to S2 (ToSpace). Eden and S1 are now empty.

So, at any time, one of the survivor spaces is always empty. When the surviving objects reach a certain threshold of moving around the survivor spaces, they are moved to the Old Generation.

You can use the `-Xmn` flag to set the size of the Young Generation.



default old/young=2:1

Eden:from:to=8:1:1


#### Handle Promotion


### Old Generation

Objects that are long-lived are eventually moved from the Young Generation to the Old Generation. 
This is also known as Tenured Generation, and contains objects that have remained in the survivor spaces for a long time.

When objects are garbage collected from the Old Generation, it is a `major garbage collection` event.

You can use the -Xms and -Xmx flags to set the size of the initial and maximum size of the Heap memory.


### Intergenerational Reference Hypothesis

Remembered Set
- bits
- objects
- Card Table



False Sharing
```
  product(bool, UseCondCardMark, false,                                     \
          "Check for already marked card before updating card table")       \
```

## Allocation

There are two fundamental strategies, `sequential allocation` and `free-list allocation`. 
We then take up the more complex case of allocation from `multiplefree-lists`.

### Sequential allocation
Sequential allocation uses a large free chunk of memory. Given a request for n bytes, it
allocates that much from one end of the free chunk. The data structure for sequential
allocation is quite simple, consisting of a free pointer and a limit pointer. Algorithm 7.1
shows pseudocode for allocation that proceeds from lower addresses to higher ones, and Figure 7.1 illustrates the technique. Sequential allocation is colloquially called bump pointer
allocation because of the way it 'bumps' the free pointer. It is also sometimes called linear
allocation because the sequence of allocation addresses is linear for a given chunk. See
Section 7.6 and Algorithm 7.8 for details concerning any necessary alignment and padding
when allocating. The properties of sequential allocation include the following.
- It is simple.
- It is efficient, although Blackburn *et al* have shown that the fundamental performance difference between sequential allocation and segregated-fits free-list allocation (see Section 7.4) for a Java system is on the order of 1% of total execution time.
- It appears to result in better cache locality than does free-list allocation, especially for initial allocation of objects in moving collectors.
- It may be less suitable than free-list allocation for non-moving collectors, if uncollected objects break up larger chunks of space into smaller ones, 
  resulting in many small sequential allocation chunks as opposed to one or a small number of large ones.

```
sequentialAllocate():
    result <- free
    newFree <- result + n
    if newFree > limit
        return null
    free <- newFree
    return result
```
![](../images/SequentialAllocation.png)

### Free-list allocation
The alternative to sequential allocation is free-list allocation. 
In free-list allocation, a data structure records the location and size of free cells of memory. 
Strictly speaking, the data structure describes a set of free cells, and some organisations are in fact not list-like, 
but w e will use the traditional term 'free-list' for them anyway. 
One can think of sequential allocation as a degenerate case of free-list allocation, but its special properties and simple implementation distinguish it in practice.

### Fragmentation

At the beginning an allocation system generally has one, or a small number, of large cells of contiguous free memory. 
As a program runs, allocating and freeing cells, it typically produces a larger number of free cells, which can individually be small. 
This dispersal of free memory across a possibly large number of small free cells is called fragmentation.
Fragmentation has at least two negative effects in an allocation system:
- It can prevent allocation from succeeding. There can be enough free memory, in total, to satisfy a request, but not enough in any particular free cell. 
  In non-garbage collected systems this generally forces a program to terminate. 
  In a garbage collected system, it may trigger collection sooner than would otherwise be necessary.
- Even if there is enough memory to satisfy a request, fragmentation may cause a program to use more address space, more resident pages and more cache lines than it would otherwise.
  It is impractical to avoid fragmentation altogether. 

For one thing, the allocator usually cannot know what the future request sequence will be. 
For another, even given a known request sequence, optimal allocation - that is, 
using the smallest amount of space necessary for an entire sequence of allocate and free requests to succeed - is NP-hard. 
However, some approaches tend to be better than others; while we cannot eliminate fragmentation, we have some hope of managing it. 
Generally speaking, we should expect a rough trade-off between allocation speed and fragmentation, while also expecting that fragmentation is quite difficult to predict in any given case

For example, best-fit intuitively seems good with respect to fragmentation, but it can lead to a number of quite small fragments scattered through the heap. 
First-fit can also lead to a large number of small fragments, which tend to cluster near the beginning of the free-list. 
Next-fit will tend to distribute small fragments more evenly across the heap, but that is not necessarily better. 
**The only total solution to fragmentation is compaction or copying collection.**

### Additional considerations
Actual allocators often must take into account some additional considerations. 
We now discuss these: alignment, size constraints, boundary tags, heap parsability, locality, wilderness preservation and crossing maps.

## When an instance is dead？
### Reference Counting



### Reachability Analysis


**GC Roots:**


Examples of such Garbage Collection roots are:

- Classes loaded by system class loader (not custom class loaders) `ClassLoaderDataGraph::roots_cld_do`
- Live threads `Threads::possibly_parallel_oops_do`
- Local variables and parameters of the currently executing methods
- Local variables and parameters of JNI methods
- Global JNI reference `JNIHandles::oops_do`
- Objects used as a monitor for synchronization
- Objects held from garbage collection by JVM for its purposes
- CodeCache `CodeCache::blobs_do`


See [G1 Roots](/docs/CS/Java/JDK/JVM/G1.md?id=roots)

Tri-color Marking

#### Incremental Update

CMS

#### Snapshot At The Beginning

G1 Shenandoah


### References
Link: [References](/docs/CS/Java/JDK/Basic/Ref.md)




### Recycle


interceptor and JIT use Write Barrier to maintain Card Table

Premature Promotion

Promotion Failure


gcCause.cpp


### mark
- at oop like serial
- bitMap out of object like G1 Shenandoah
- Colored Pointer like ZGC


## MetaSpace
Starting with Java 8, the MetaSpace memory space replaces the PermGen space. The implementation differs from the PermGen and this space of the heap is now automatically resized.

This avoids the problem of applications running out of memory due to the limited size of the PermGen space of the heap. The Metaspace memory can be garbage collected and the classes that are no longer used can be automatically cleaned when the Metaspace reaches its maximum size.

-Xnoclassgc -verbose:class -XX:+TraceClassLoading -XX:+TraceClassUnLoading

### Young GC 问题

```
-XX:+UsePSAdaptiveSurvivorSizePolicy

-XX:SurvivorRatio

-XX:TargetSurvivorRatio
```

Card Table

write barrier
```
CARD_TABLE [this address >> 9] = DIRTY;
```
-XX:+UseCondCardMark



####  YGC耗时异常 

- toot对象扫描+标记时间过长                
- 存活对象copy耗时较大                
- 等待各线程到达安全点时间较长                
- GC日志对GC时间的影响                
- 操作系统活动影响（内存swap等）                

### Full GC 问题

 FGC频次异常 

- 老年代空间不足                
- 内存碎片化                
- 永久代/元空间 空间不足                
- 对象预估和担保                
- 堆大小动态调整          


## Collectors

Following Dijkstra *et al*, a garbage-collected program is divided into two semiindependent parts.
- The mutator executes application code, which allocates new objects and mutates the object graph by changing reference fields so that they refer to different destination objects.
  These reference fields may be contained in heap objects as well as other places known as roots, such as static variables, thread stacks, and so on.
  As a result of such reference updates, any object can end up disconnected from the roots, that is, unreachable by following any sequence of edges from the roots.
- The collector executes garbage collection code, which discovers unreachable objects and reclaims their storage.

A program may have more than one mutator thread, but the threads together can usually
be thought of as a single actor over the heap. Equally, there may be one or more collector
threads.

- [CMS](/docs/CS/Java/JDK/JVM/CMS.md)
- [G1](/docs/CS/Java/JDK/JVM/G1.md)
- [Shenandoah](/docs/CS/Java/JDK/JVM/Shenandoah.md)
- [ZGC](/docs/CS/Java/JDK/JVM/ZGC.md)


```cpp
// share/gc/shared/gcConfiguration.cpp
GCName GCConfiguration::young_collector() const {
  if (UseG1GC) {
    return G1New;
  }

  if (UseParallelGC) {
    return ParallelScavenge;
  }

  if (UseConcMarkSweepGC) {
    return ParNew;
  }

  if (UseZGC || UseShenandoahGC) {
    return NA;
  }

  return DefNew;
}

GCName GCConfiguration::old_collector() const {
  if (UseG1GC) {
    return G1Old;
  }

  if (UseConcMarkSweepGC) {
    return ConcurrentMarkSweep;
  }

  if (UseParallelOldGC) {
    return ParallelOld;
  }

  if (UseZGC) {
    return Z;
  }

  if (UseShenandoahGC) {
    return Shenandoah;
  }

  return SerialOld;
}
```

### Comparing garbage collectors
- Throughput
- Pause time
- Space
- Implementation
- Adaptive systems

From [JVM](https://book.douban.com/subject/34907497/):
![Our Collectors](../images/our-collectors.png)

And

![GC Collector](../images/GC-collector.png)

[JEP 173: Retire Some Rarely-Used GC Combinations](https://openjdk.java.net/jeps/173)

CMS only with ParNew since [JEP 214: Remove GC Combinations Deprecated in JDK 8](https://openjdk.java.net/jeps/214)


| GC | Optimized For |
| --- | --- |
| Serial | Memory Footprint |
| Parallel | Throughput |
| G1 | Throughput/Latency Balance |
| ZGC/Shenandoah | Low Latency |

- Footprint
- Throughput
- Latency


[JEP 304: Garbage Collector Interface](https://openjdk.java.net/jeps/304)

[JEP 312: Thread-Local Handshakes](https://openjdk.java.net/jeps/312)

### Epsilon


Epsilon is a do-nothing (no-op) garbage collector that was released as part of JDK 11( see [JEP 318: Epsilon: A No-Op Garbage Collector](https://openjdk.java.net/jeps/318)).
It handles memory allocation but does not implement any actual memory reclamation mechanism.
Once the available Java heap is exhausted, the JVM shuts down.


### Serial
The serial collector uses a single thread to perform all garbage collection work, which makes it relatively efficient because there is no communication overhead between threads.

It's best-suited to single processor machines because it can't take advantage of multiprocessor hardware, although it can be useful on multiprocessors for applications with small data sets (up to approximately 100 MB). 
The serial collector is selected by default on certain hardware and operating system configurations, or can be explicitly enabled with the option `-XX:+UseSerialGC`.

#### Serial Old
- with Parallel JDK5
- CMS Concurrent Mode Failure


### Parallel Scavenge
The parallel collector is also known as throughput collector, it's a generational collector similar to the serial collector. 
The primary difference between the serial and parallel collectors is that the parallel collector has multiple threads that are used to speed up garbage collection.

The parallel collector is intended for applications with medium-sized to large-sized data sets that are run on multiprocessor or multithreaded hardware. 
You can enable it by using the `-XX:+UseParallelGC` option.

Parallel Scavenge and Parallel Old
```
- GCTimeRatio                               = 99
- MaxGCPauseMillis                          = 18446744073709551615


- UseParallelGC                            := true
- UseParallelOldGC                          = true
- UseAdaptiveGCBoundary                     = false
```

see [Garbage Collector Ergonomics](https://docs.oracle.com/javase/7/docs/technotes/guides/vm/gc-ergonomics.html)


### Concurrent
The mostly concurrent collector trades processor resources (which would otherwise be available to the application) for shorter major collection pause times. The most visible overhead is the use of one or more processors during the concurrent parts of the collection. On an N processor system, the concurrent part of the collection will use K/N of the available processors, where 1<=K<=ceiling{N/4}. (Note that the precise choice of and bounds on K are subject to change.) In addition to the use of processors during concurrent phases, additional overhead is incurred to enable concurrency. Thus while garbage collection pauses are typically much shorter with the concurrent collector, application throughput also tends to be slightly lower than with the other collectors.

On a machine with more than one processing core, processors are available for application threads during the concurrent part of the collection, so the concurrent garbage collector thread does not "pause" the application. This usually results in shorter pauses, but again fewer processor resources are available to the application and some slowdown should be expected, especially if the application uses all of the processing cores maximally. As N increases, the reduction in processor resources due to concurrent garbage collection becomes smaller, and the benefit from concurrent collection increases. The section Concurrent Mode Failure in Concurrent Mark Sweep (CMS) Collector discusses potential limits to such scaling.

Because at least one processor is used for garbage collection during the concurrent phases, the concurrent collectors do not normally provide any benefit on a uniprocessor (single-core) machine. However, there is a separate mode available for CMS (not G1) that can achieve low pauses on systems with only one or two processors; see Incremental Mode in Concurrent Mark Sweep (CMS) Collector for details. This feature is being deprecated in Java SE 8 and may be removed in a later major release.

### CMS

[JEP 291: Deprecate the Concurrent Mark Sweep (CMS) Garbage Collector](https://openjdk.java.net/jeps/291)

### G1


Low-Latency Garbage Collector

Low-Pause-Time garbage Collector


### shenandoah
Shenandoah is a new GC that was released as part of JDK 12. 
Shenandoah’s key advantage over G1 is that it does more of its garbage collection cycle work concurrently with the application threads. 
G1 can evacuate its heap regions only when the application is paused, while Shenandoah can relocate objects concurrently with the application.

Shenandoah can compact live objects, clean garbage, and release RAM back to the OS almost immediately after detecting free memory. 
Since all of this happens concurrently while the application is running, Shenandoah is more CPU intensive.

The JVM argument to use the Epsilon Garbage Collector is `-XX:+UnlockExperimentalVMOptions -XX:+UseShenandoahGC`.

[JEP 189: Shenandoah: A Low-Pause-Time Garbage Collector (Experimental)](https://openjdk.java.net/jeps/189)


**Connection Matrix** for InterRegional Reference Hypothesis



### ZGC
[JEP 333: ZGC: A Scalable Low-Latency Garbage Collector (Experimental)](https://openjdk.java.net/jeps/333)

The Z Garbage Collector (ZGC) is a scalable low latency garbage collector. ZGC performs all expensive work concurrently, without stopping the execution of application threads.

ZGC is intended for applications which require low latency (less than 10 ms pauses) and/or use a very large heap (multi-terabytes). You can enable is by using the -XX:+UseZGC option.

ZGC is available as an experimental feature, starting with JDK 11 and has been improved in JDK 12. It is intended for applications which require low latency (less than 10 ms pauses) and/or use a very large heap (multi-terabytes).

The primary goals of ZGC are low latency, scalability, and ease of use. To achieve this, ZGC allows a Java application to continue running while it performs all garbage collection operations. By default, ZGC uncommits unused memory and returns it to the operating system.

The JVM argument to use the Epsilon Garbage Collector is `-XX:+UnlockExperimentalVMOptions -XX:+UseZGC`.






## Performance

If a system is exhibiting high levels of system CPU usage, then it is definitely not spending a significant amount of its time in GC, 
as GC activity burns user space CPU cycles and does not impact kernel space utilization.

On the other hand, if a JVM process is using 100% (or close to that) of CPU in user space, then garbage collection is often the culprit. 
When analyzing a performance problem, if simple tools (such as vmstat) show consistent 100% CPU usage, but with almost all cycles being consumed by user space, 
then we should ask, “Is it the JVM or user code that is responsible for this utilization?” 
In almost all cases, high user space utilization by the JVM is caused by the GC subsystem, so a useful rule of thumb is to check the GC log and see how often new entries are being added to it.


### Performance Testing

- Latency test
What is the end-to-end transaction time?
- Throughput test
How many concurrent transactions can the current system capacity deal with?
- Load test
Can the system handle a specific load?
- Stress test
What is the breaking point of the system?
- Endurance test
What performance anomalies are discovered when the system is run for an extended period?
- Capacity planning test
Does the system scale as expected when additional resources are added?
- Degradation
  What happens when the system is partially failed? `Chaos Monkey`
  


### Tuning

It is generally best to stick to the defaults as much as possible to avoid surprises, and only specify non-default behavior when there is a clear benefit. 
This also reduces dependencies on a specific JVM offering or version, making ongoing maintenance simpler and less risky.


## Links
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)


## References
1. [Unnecessary GCLocker-initiated young GCs](https://bugs.openjdk.java.net/browse/JDK-8048556)
2. [Exploiting the Weak Generational Hypothesis for Write Reduction and Object Recycling](https://openscholarship.wustl.edu/eng_etds/169/)
3. [Java Platform, Standard Edition HotSpot Virtual Machine Garbage Collection Tuning Guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/toc.html)
4. [Our Collectors](https://blogs.oracle.com/jonthecollector/our-collectors)
5. [Garbage Collection in Java – What is GC and How it Works in the JVM](https://www.freecodecamp.org/news/garbage-collection-in-java-what-is-gc-and-how-it-works-in-the-jvm/)
6. [HotSpot Virtual Machine Garbage Collection Tuning Guide - JDK11](https://docs.oracle.com/en/java/javase/11/gctuning/index.html)