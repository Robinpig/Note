## Introduction

Processes are one of the oldest and most important abstractions that operating systems provide.
We will go into considerable detail about processes and their first cousins, threads.


> [!TIP]
> Separate Policy and Mechanism
>
> Separating the two allows one easily to change policies without having to rethink the mechanism and is thus a form of modularity, a general software design principle.


## Processes

The most central concept in any operating system is the process: **an abstraction of a running program**.
A process is just an instance of an executing program, including the current values of the program counter, registers, and variables.
Conceptually, each process has its own virtual CPU.
In reality, of course, the real CPU switches back and forth from process to process.
This rapid switching back and forth is called *multiprogramming*.

When multiprogramming is used, the CPU utilization can be improved.

A better model is to look at CPU usage from a probabilistic viewpoint. Suppose that a process spends a fraction p of its time waiting for I/O to complete. 
With n processes in memory at once, the probability that all n processes are waiting for I/O (in which case the CPU will be idle) is pn. The CPU utilization is then given by the formula

```tex
CPU utilization = 1 − p^n
```

With the CPU switching back and forth among the processes, the rate at which a process performs its computation will not be uniform and probably not even reproducible if the same processes are run again.
Thus, processes must not be programmed with built-in assumptions about timing.

A process is an activity of some kind. It has a program, input, output, and a state.
A single processor may be shared among several processes, with some scheduling algorithm being accustomed to determine when to stop work on one process and service a different one.
In contrast, a program is something that may be stored on disk, not doing anything.


### Process Creation

Four principal events cause processes to be created:
1. System initialization.
2. Execution of a process-creation system call by a running process.
3. A user request to create a new process.
4. Initiation of a batch job

Technically, in all these cases, a new process is created by having an existing process execute a process creation system call.
This system call tells the operating system to create a new process and indicates, directly or indirectly, which program to run in it.

In UNIX, there is only one system call to create a new process: fork. This call creates an exact clone of the calling process.
After the fork, the two processes, the parent and the child, have the same memory image, the same environment strings, and the same open files. That is all there is.
Usually, the child process then executes execve or a similar system call to change its memory image and run a new program.

In both UNIX and Windows systems, after a process is created, the parent and child have their own distinct address spaces.
If either process changes a word in its address space, the change is not visible to the other process.
In UNIX, the child’s initial address space is a copy of the parent’s, but there are definitely two distinct address spaces involved; no writable memory is shared.
Some UNIX implementations share the program text between the two since that cannot be modified.
Alternatively, the child may share all of the parent’s memory, but in that case the memory is shared *copy-on-write*, which means that whenever either of the two wants to modify part of the memory,
that chunk of memory is explicitly copied first to make sure the modification occurs in a private memory area.
Again, no writable memory is shared.
It is, however, possible for a newly created process to share some of its creator’s other resources, such as open files.
In Windows, the parent’s and child’s address spaces are different from the start.


### Process Termination

The new process will terminate, usually due to one of the following conditions:
1. Normal exit (voluntary).
2. Error exit (voluntary).
3. Fatal error (involuntary).
4. Killed by another process (involuntary).


### Process Hierarchies

In UNIX, a process and all of its children and further descendants together form a process group. 
When a user sends a signal from the keyboard, the signal is delivered to all members of the process group currently associated with the keyboard (usually all active processes that were created in the current window).
Individually, each process can catch the signal, ignore the signal, or take the default action, which is to be killed by the signal.
All the processes in the whole system belong to a single tree, with *init* at the root.
Processes in UNIX cannot disinherit their children.

Windows has no concept of a process hierarchy. All processes are equal.
The only hint of a process hierarchy is that when a process is created, the parent is given a special token (called a handle) that it can use to control the child.
However, it is free to pass this token to some other process, thus invalidating the hierarchy. 


### Process States

we see a state diagram showing the three states a process may be in:
1. Running (actually using the CPU at that instant).
2. Ready (runnable; temporarily stopped to let another process run).
3. Blocked (unable to run until some external event happens).

Logically, the first two states are similar. 
In both cases the process is willing to run, only in the second one, there is temporarily no CPU available for it. 
The third state is fundamentally different from the first two in that the process cannot run, even if the CPU is idle and has nothing else to do.

![Process State](./img/Process%20State.png)

Four transitions are possible among these three states, as shown.

- Transition 1 occurs when the operating system discovers that a process cannot continue right now.
- Transitions 2 and 3 are caused by the process scheduler, a part of the operating system, without the process even knowing about them.
- Transition 4 occurs when the external event for which a process was waiting(such as the arrival of some input) happens. 
  If no other process is running at that instant, transition 3 will be triggered and the process will start running. 
  Otherwise it may have to wait in ready state for a little while until the CPU is available and its turn comes.


Sometimes a system will have an **initial** state that the process is in when it is being created.
Also, a process could be placed in a **final** state where it has exited but has not yet been cleaned up (in UNIX-based systems, this is called the **zombie** state). 
This final state can be useful as it allows other processes(usually the parent that created the process) to examine the return code of the process and see if the just-finished process executed successfully
(usually, programs return zero in UNIX-based systems when they have accomplished a task successfully, and non-zero otherwise). 
When finished, the parent will make one final call (`wait()`) to wait for the completion of the child, and to also indicate to the OS that it can clean up any relevant data structures that referred to the now-extinct process.

### Process Control Block

To understand what constitutes a process, we thus have to understand its machine state: what a program can read or update when it is running.
At any given time, what parts of the machine are important to the execution of this program?

One obvious component of machine state that comprises a process is its memory.
Also part of the process’s machine state are registers;

To implement the process model, the operating system maintains a table (an array of structures), called the *process table*, with one entry per process. (Some authors call these entries *process control blocks*.)
This entry contains important information about the process’ state, including its program counter, stack pointer, memory allocation, the status of its open files, its accounting and scheduling information, 
and everything else about the process that must be saved when the process is switched from *running* to *ready* or *blocked* state so that it can be restarted later as if it had never been stopped.


Associated with each I/O class is a location (typically at a fixed location near the bottom of memory) called the interrupt vector. It contains the address of the interrupt service procedure. 
Suppose that user process 3 is running when a disk interrupt happens. 
User process 3’s program counter, program status word, and sometimes one or more registers are pushed onto the (current) stack by the interrupt hardware. The computer then jumps to the address specified in the interrupt vector. 
That is all the hardware does. From here on, it is up to the software, in particular, the interrupt service procedure.

All interrupts start by saving the registers, often in the process table entry for the current process. 
Then the information pushed onto the stack by the interrupt is removed and the stack pointer is set to point to a temporary stack used by the process handler. 
Actions such as saving the registers and setting the stack pointer cannot even be expressed in high-level languages such as C, so they are performed by a small assembly-language routine, 
usually the same one for all interrupts since the work of saving the registers is identical, no matter what the cause of the interrupt is.

When this routine is finished, it calls a C procedure to do the rest of the work for this specific interrupt type. (We assume the operating system is written in C, the usual choice for all real operating systems.) 
When it has done its job, possibly making some process now ready, the scheduler is called to see who to run next.
After that, control is passed back to the assembly-language code to load up the registers and memory map for the now-current process and start it running.
Interrupt handling and scheduling are summarized below. It is worth noting that the details vary somewhat from system to system.

1. Hardware stacks program counter, etc.
2. Hardware loads new program counter from interrupt vector.
3. Assembly-language procedure saves registers.
4. Assembly-language procedure sets up new stack.
5. C interrupt service runs (typically reads and buffers input).
6. Scheduler decides which process is to run next.
7. C procedure returns to the assembly code.
8. Assembly-language procedure starts up new current process.

A process may be interrupted thousands of times during its execution, but the key idea is that after each interrupt the interrupted process returns to precisely the same state it was in before the interrupt occurred.


## Threads

- The main reason for having threads is that in many applications, multiple activities are going on at once. Some of these may block from time to time. 
  By decomposing such an application into multiple sequential threads that run in quasi-parallel, the programming model becomes simpler.
- A second argument for having threads is that since they are lighter weight than processes, they are easier (i.e., faster) to create and destroy than processes.
  When the number of threads needed changes dynamically and rapidly, this property is useful to have.
- A third reason for having threads is also a performance argument.
- Finally, threads are useful on systems with multiple CPUs, where real parallelism is possible.


### The Classical Thread Model

The process model is based on two independent concepts: resource grouping and execution. Sometimes it is useful to separate them; this is where threads come in.

A process has is a thread of execution, usually shortened to just thread. The thread has a program counter that keeps track of which instruction to execute next. 
It has registers, which hold its current working variables. It has a stack, which contains the execution history, with one frame for each procedure called but not yet returned from. 
Although a thread must execute in some process, the thread and its process are different concepts and can be treated separately. 
Processes are used to group resources together; threads are the entities scheduled for execution on the CPU.

What threads add to the process model is to allow multiple executions to take place in the same process environment, to a large degree independent of one another.
Because threads have some of the properties of processes, they are sometimes called *lightweight processes*.
The term *multithreading* is also used to describe the situation of allowing multiple threads in the same process.


### Implementing  of Threads

There are two main places to implement threads: user space and the kernel.
The choice is a bit controversial, and a hybrid implementation is also possible.

#### User Space

The method is to put the threads package entirely in user space. The kernel knows nothing about them. As far as the kernel is concerned, it is managing ordinary, single-threaded processes. 

When threads are managed in user space, each process needs its own private thread table to keep track of the threads in that process.
This table is analogous to the kernel’s process table, except that it keeps track only of the per-thread properties, such as each thread’s program counter, stack pointer, registers, state, and so forth.
The thread table is managed by the run-time system.
When a thread is moved to ready state or blocked state, the information needed to restart it is stored in the thread table, exactly the same way as the kernel stores information about processes in the process table.

- The first, and most obvious, advantage is that a user-level threads package can be implemented on an operating system that does not support threads.
- The procedure that saves the thread’s state and the scheduler are just local procedures, so invoking them is much more efficient than making a kernel call.
  Among other issues, no trap is needed, no context switch is needed, the memory cache need not be flushed, and so on. This makes thread scheduling very fast.
- They allow each process to have its own customized scheduling algorithm.

Despite their better performance, user-level threads packages have some major problems.
- First among these is the problem of how blocking system calls are implemented.
- Somewhat analogous to the problem of blocking system calls is the problem of page faults.
- Another problem with user-level thread packages is that threads running forever.
- Programmers generally want threads precisely in applications where the threads block often.



#### In the Kernel

The kernel has a thread table that keeps track of all the threads in the system. 
When a thread wants to create a new thread or destroy an existing thread, it makes a kernel call, which then does the creation or destruction by updating the kernel thread table.

All calls that might block a thread are implemented as system calls, at considerably greater cost than a call to a run-time system procedure.
Kernel threads do not require any new, nonblocking system calls. 
In addition, if one thread in a process causes a page fault, the kernel can easily check to see if the process has any other runnable threads, and if so, run one of them while waiting for the required page to be brought in from the disk. 
Their main disadvantage is that the cost of a system call is substantial, so if thread operations (creation, termination, etc.) a common, much more overhead will be incurred.


#### Hybrid Implementations

Use kernel-level threads and then multiplex user-level threads onto some or all of them.
When this approach is used, the programmer can determine how many kernel threads to use and how many user-level threads to multiplex on each one. This model gives the ultimate in flexibility.


#### Scheduler Activations

The goals of the scheduler activation work are to mimic the functionality of kernel threads, but with the better performance and greater flexibility usually associated with threads packages implemented in user space.

The basic idea that makes this scheme work is that when the kernel knows that a thread has blocked (e.g., by its having executed a blocking system call or caused a page fault), 
the kernel notifies the process’ run-time system, passing as parameters on the stack the number of the thread in question and a description of the event that occurred. 
The notification happens by having the kernel activate the run-time system at a known starting address, roughly analogous to a signal in UNIX. 
This mechanism is called an **upcall**.
An objection to scheduler activations is the fundamental reliance on upcalls, a concept that violates the structure inherent in any layered system.


### Multithreaded


Conflicts between threads over the use of a global variable.
And various solutions to this problem are possible. 
- One is to prohibit global variables altogether.
- Another is to assign each thread its own private global variables.

The next problem in turning a single-threaded program into a multithreaded one is that many library procedures are not reentrant. -- Synchronization Mechanism

Next, consider signals. Some signals are logically thread specific, whereas others are not.

Last problem introduced by threads is stack management.


## InterProcess Communication

Processes frequently need to communicate with other processes.
We will look at some of the issues related to this **InterProcess Communication**, or **IPC**.

There are three issues here. 
- How one process can pass information to another.
- The second has to do with making sure two or more processes do not get in each other’s way.
- The third concerns proper sequencing when dependencies are present.

It is also important to mention that two of these issues apply equally well to threads. 
The first one—passing information—is easy for threads since they share a common address space (threads in different address spaces that need to communicate fall under the heading of communicating processes). 
However, the other two—keeping out of each other’s hair and proper sequencing—apply equally well to threads.
The same problems exist and the same solutions apply.

### Race Conditions

Where two or more processes are reading or writing some shared data and the final result depends on who runs precisely when, are called **race conditions**.

### Critical Regions

How do we avoid race conditions?
What we need is **mutual exclusion**, that is, some way of making sure that if one process is using a shared variable or file, the other processes will be excluded from doing the same thing.
Sometimes a process has to access shared memory or files, or do other critical things that can lead to races. 
That part of the program where the shared memory is accessed is called the **critical region** or **critical section**. 
If we could arrange matters such that no two processes were ever in their critical regions at the same time, we could avoid races.

Although this requirement avoids race conditions, it is not sufficient for having parallel processes cooperate correctly and efficiently using shared data. 
We need four conditions to hold to have a good solution:
1. No two processes may be simultaneously inside their critical regions.
2. No assumptions may be made about speeds or the number of CPUs.
3. No process running outside its critical region may block any process.
4. No process should have to wait forever to enter its critical region.

### Mutual Exclusion with Busy Waiting


#### Disabling Interrupts

#### Lock Variables

#### Strict Alternation

Continuously testing a variable until some value appears is called*busy waiting*. 
It should usually be avoided, since it wastes CPU time. Only when there is a reasonable expectation that the wait will be short is busy waiting used. 
A lock that uses busy waiting is called a **spin lock**.


#### Peterson’s Solution


#### The TSL Instruction

An alternative instruction to TSL is XCHG, which exchanges the contents of two locations atomically, for example, a register and a memory word.
All Intel x86 CPUs use XCHG instruction for low-level synchronization.

### Sleep and Wakeup

Both Peterson’s solution and the solutions using TSL or XCHG are correct, but both have the defect of requiring busy waiting.

Consider a computer with two processes, H, with high priority, and L, with low priority. The scheduling rules are such that H is run whenever it is in ready state. 
At a certain moment, with L in its critical region, H becomes ready to run(e.g., an I/O operation completes). 
H now begins busy waiting, but since L is never scheduled while H is running, L never gets the chance to leave its critical region, so H loops forever. 
This situation is sometimes referred to as the **priority inversion problem**.


#### The Producer-Consumer Problem

Let us consider the **producer-consumer problem** (also known as the **bounded-buffer problem**).


### Semaphores

A semaphore could have the value 0, indicating that no wakeups were saved, or some positive value if one or more wakeups were pending.

Dijkstra proposed having two operations on semaphores, now usually called down and up (generalizations of sleep and wakeup, respectively). 
The down operation on a semaphore checks to see if the value is greater than 0. 
If so, it decrements the value (i.e., uses up one stored wakeup) and just continues. 
If the value is 0, the process is put to sleep without completing the down for the moment. 
Checking the value, changing it, and possibly going to sleep, are all done as a single, indivisible atomic action. 
It is guaranteed that once a semaphore operation has started, no other process can access the semaphore until the operation has completed or blocked. 
This atomicity is absolutely essential to solving synchronization problems and avoiding race conditions. 
Atomic actions, in which a group of related operations are either all performed without interruption or not performed at all, are extremely important in many other areas of computer science as well.


### Mutexes

When the semaphore’s ability to count is not needed, a simplified version of the semaphore, called a mutex, is sometimes used.
A mutex is a shared variable that can be in one of two states: unlocked or locked.
Consequently, only 1 bit is required to represent it, but in practice an integer often is used, with 0 meaning unlocked and all other values meaning locked.

When *enter_region* fails to enter the critical region, it keeps testing the lock repeatedly (busy waiting).
When the *mutex lock* fails to acquire a lock, it calls thread yield to give up the CPU to another thread. Consequently there is no busy waiting. When the thread runs the next time, it tests the lock again.

#### Futexs

A futex(fast user space mutex) is a feature of Linux that implements basic locking (much like a mutex) but avoids dropping into the kernel unless it really has to.

A futex consists of two parts: a kernel service and a user library. The kernel service provides a ‘‘wait queue’’ that allows multiple processes to wait on a lock. 
They will not run, unless the kernel explicitly unblocks them.
In the absence of contention, the futex works completely in user space.

If the lock is held by another thread, our thread has to wait. 
In that case, the futex library does not spin, but uses a system call to put the thread on the wait queue in the kernel. 
When a thread is done with the lock, it releases the lock with an atomic ‘‘increment and test’’ and checks the result to see if any processes are still blocked on the kernel wait queue. 
If so, it will let the kernel know that it may unblock one or more of these processes. 
If there is no contention, the kernel is not involved at all.

#### Mutexes in Pthreads

Pthreads provides a number of functions that can be used to synchronize threads. 
The basic mechanism uses a mutex variable, which can be locked or unlocked, to guard each critical region.
If multiple threads are waiting on the same mutex, when it is unlocked, only one of them is allowed to continue and relock it. 
These locks are not mandatory. It is up to the programmer to make sure threads use them correctly.

Pthreads offers a second synchronization mechanism: **condition variables**.
Condition variables allow threads to block due to some condition not being met.
Condition variables and mutexes are always used together. The pattern is for one thread to lock a mutex, then wait on a conditional variable when it cannot get what it needs.

### Monitors

Monitors have an important property that makes them useful for achieving mutual exclusion: only one process can be active in a monitor at any instant.

Monitors are a programming-language construct, so the compiler knows they are special and can handle calls to monitor procedures differently from other procedure calls.
Typically, when a process calls a monitor procedure, the first few instructions of the procedure will check to see if any other process is currently active within the monitor. 
If so, the calling process will be suspended until the other process has left the monitor. If no other process is using the monitor, the calling process may enter.

Although monitors provide an easy way to achieve mutual exclusion, we also need a way for processes to block when they cannot proceed.
The solution lies in the introduction of condition variables, along with two operations on them, *wait* and *signal*.

Condition variables are not counters. They do not accumulate signals for later use the way semaphores do. 
Thus, if a condition variable is signaled with no one waiting on it, the signal is lost forever. In other words, the wait must come before the signal.

The operations wait and signal look similar to sleep and wakeup, which we saw earlier had fatal race conditions. 
Well, they are very similar, but with one crucial difference: sleep and wakeup failed because while one process was trying to go to sleep, the other one was trying to wake it up. 
With monitors, that cannot happen. 
The automatic mutual exclusion on monitor procedures guarantees that if, say, the producer inside a monitor procedure discovers that the buffer is full, 
it will be able to complete the wait operation without having to worry about the possibility that the scheduler may switch to the consumer just before the wait completes. 
The consumer will not even be let into the monitor at all until the wait is finished and the producer has been marked as no longer runnable.


By adding the keyword [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) to a method declaration, Java guarantees that once any thread has started executing that method, no other thread will be allowed to start executing any other synchronized method of that object.
Synchronized methods in Java differ from classical monitors in an essential way: Java does not have condition variables built in. Instead, it offers two procedures, wait and notify, 
which are the equivalent of sleep and wakeup except that when they are used inside synchronized methods, they are not subject to race conditions.


### Message Passing

Message passing uses two primitives, *send* and *receive*, which, like semaphores and unlike monitors, are system calls rather than language constructs.


Message-passing systems have many problems and design issues that do not arise with semaphores or with monitors, especially if the communicating processes are on different machines connected by a network. 

For example, messages can be lost by the network.
It is essential that the receiver be able to distinguish a new message from the retransmission of an old one. Usually, this problem is solved by putting consecutive sequence numbers in each original message.

Authentication is also an issue in message systems.

Last of these is performance.

### Barriers

Our last synchronization mechanism is intended for groups of processes rather than two-process producer-consumer type situations. 
Some applications are divided into phases and have the rule that no process may proceed into the next phase until all processes are ready to proceed to the next phase. 
This behavior may be achieved by placing a **barrier** at the end of each phase.


### Avoiding Locks

RCU (Read-Copy-Update) decouples the removal and reclamation phases of the update.


### IPC Problems

#### The Dining Philosophers Problem

DeadLock

All the programs continue to run indefinitely but fail to make any progress, is called starvation.


#### The Readers and Writers Problem





## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux Process](/docs/CS/OS/Linux/process.md)