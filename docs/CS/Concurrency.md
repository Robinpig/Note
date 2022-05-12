## Introduction




## Common Concurrency Problems


### Deadlock

One reason is that in large code bases, complex dependencies arise between components.

Another reason is due to the nature of encapsulation.

#### Prevention

Circular Wait

Of course, in more complex systems, more than two locks will exist, and thus total lock ordering may be difficult to achieve (and perhaps is unnecessary anyhow).
Thus, a partial ordering can be a useful way to structure lock acquisition so as to avoid deadlock.

As you can imagine, both total and partial ordering require careful design of locking strategies and must be constructed with great care.
Further, ordering is just a convention, and a sloppy programmer can easily ignore the locking protocol and potentially cause deadlock.
Finally, lock ordering requires a deep understanding of the code base, and how various routines are called; just one mistake could result Deadlocks.


Hold-and-wait


The hold-and-wait requirement for deadlock can be avoided by acquiring all locks at once, atomically.

Note that the solution is problematic for a number of reasons.
As before, encapsulation works against us: when calling a routine, this approach requires us to know exactly which locks must be held and to acquire them ahead of time.
This technique also is likely to decrease concurrency as all locks must be acquired early on (at once) instead of when they are truly needed.

No Preemption


```c
trylock
```

One new problem does arise, however: livelock.

There are solutions to the livelock problem, too: for example, one could add a random delay before looping back and trying the entire thing over again, thus decreasing the odds of repeated interference among competing threads.


Mutual Exclusion

The idea behind these lock-free (and related wait-free) approaches here is simple: using powerful hardware instructions, you can build data structures in a manner that does not require explicit locking.

In this manner, no lock is acquired, and no deadlock can arise (though livelock is still a possibility).

#### Deadlock Avoidance

Further, such approaches can limit concurrency, as we saw in the second example above. Thus, avoidance of deadlock via scheduling is not a widely-used general-purpose solution.

#### Detect and Recover

Many database systems employ deadlock detection and recovery techniques. A deadlock detector runs periodically, building a resource graph and checking it for cycles.
In the event of a cycle (deadlock), the system needs to be restarted. If more intricate repair of data structures is first required, a human being may be involved to ease the process.


### Atomicity-Violation

The formal definition of an atomicity violation is this: “The desired serializability among multiple memory accesses is violated (i.e. a code region is intended to be atomic, but the atomicity is not enforced during execution)”.

### Order-Violation

The formal definition of an order violation is this: “The desired order between two (groups of) memory accesses is flipped (i.e., A should always be executed before B, but the order is not enforced during execution)”.

The fix to this type of bug is generally to enforce ordering. As we discussed in detail previously, using condition variables is an easy and robust way to add this style of synchronization into modern code bases.


## Event-based

A different style of concurrent programming is often used in both GUI-based applications as well as some types of internet servers. 
This style, known as event-based concurrency, has become popular in some modern systems, including server-side frameworks such as node.js.

The problem that event-based concurrency addresses is two-fold. 

- The first is that managing concurrency correctly in multi-threaded applications can be challenging; as we’ve discussed, missing locks, deadlock, and other nasty problems can arise. 
- The second is that in a multi-threaded application, the developer has little or no control over what is scheduled at a given moment in time; 
  rather, the programmer simply creates threads and then hopes that the underlying OS schedules them in a reasonable manner across available CPUs. 
  Given the difficulty of building a generalpurpose scheduler that works well in all cases for all workloads, sometimes the OS will schedule work in a manner that is less than optimal.

How can we build a concurrent server without using threads, and thus retain control over concurrency as well as avoid some of the problems that seem to plague multi-threaded applications?

The basic approach we’ll use, as stated above, is called event-based concurrency. 
The approach is quite simple: you simply wait for something (i.e., an “event”) to occur; when it does, you check what type of event it is and do the small amount of work it requires (which may include issuing I/O requests, or scheduling other events for future handling, etc.).

Such applications are based around a simple construct known as the event loop. Pseudocode for an event loop looks like this:
```c
while (1) {
    events = getEvents();
    for (e in events)
        processEvent(e);
}
```
The main loop simply waits for something to do(by calling getEvents() in the code above) and then, for each event returned, processes them, one at a time; the code that processes each event is known as an **event handler**. 
Importantly, when a handler processes an event, it is the only activity taking place in the system; thus, deciding which event to handle next is equivalent to scheduling. 
This explicit control over scheduling is one of the fundamental advantages of the event-based approach.


With that basic event loop in mind, we next must address the question of how to receive events. In most systems, a basic API is available, via either the select() or poll() system calls.

With a single CPU and an event-based application, the problems found in concurrent programs are no longer present. 
Specifically, because only one event is being handled at a time, there is no need to acquire or release locks; the event-based server cannot be interrupted by another thread because it is decidedly single threaded. 
Thus, concurrency bugs common in threaded programs do not manifest in the basic event-based approach.

### Blocking System Calls

> [!NOTE]
> Event-based servers enable fine-grained control over scheduling of tasks.
> However, to maintain such control, no call that blocks the execution of the caller can ever be made; failing to obey this design tip will result in a blocked event-based server.

To overcome this limit, many modern operating systems have introduced new ways to issue I/O requests to the disk system, referred to generically as asynchronous I/O.

### State Managements

Another issue with the event-based approach is that such code is generally more complicated to write than traditional thread-based code. 
The reason is as follows: when an event handler issues an asynchronous I/O, it must package up some program state for the next event handler to use when the I/O finally completes; 
this additional work is not needed in thread-based programs, as the state the program needs is on the stack of the thread. 
Adya et al. call this work **manual stack management**, and it is fundamental to event-based programming.

The solution, as described by Adya et al., is to use an old programming language construct known as a continuation. 
Though it sounds complicated, the idea is rather simple: basically, record the needed information to finish processing this event in some data structure; when the event happens (i.e., when the disk I/O completes), look up the needed information and process the event.

### Other Problems

There are a few other difficulties with the event-based approach that we should mention. 

- For example, when systems moved from a single CPU to multiple CPUs, some of the simplicity of the event-based approach disappeared.
- Another problem with the event-based approach is that it does not integrate well with certain kinds of systems activity, such as paging.
- A third issue is that event-based code can be hard to manage over time, as the exact semantics of various routines changes. 

Finally, though asynchronous disk I/O is now possible on most platforms, it has taken a long time to get there, and it never quite integrates with asynchronous network I/O in as simple and uniform a manner as you might think. 
For example, while one would simply like to use the select() interface to manage all outstanding I/Os, usually some combination of select() for networking and the AIO calls for disk I/O are required.




## Links

