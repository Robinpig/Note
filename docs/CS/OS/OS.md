## Introduction

There is a body of software, in fact, that is responsible for making it easy to run programs, allowing programs to share memory, enabling programs to interact with devices, and other fun stuff like that. 
That body of software is called the operating system (OS), as it is in charge of making sure the system operates correctly and efficiently in an easy-to-use manner.
An operating system (OS) is a software program that serves as the interface between other applications and the hardware on a computer or mobile device.
 
- Kernel
- Shell


- Abstract
- Multiplex, sharing and isolation
- Security
- Performance

### Implementation Strategies

Currently, there are two main paradigms on which the implementation of operating systems is based:

1. Microkernels — In these, only the most elementary functions are implemented directly in a central kernel — the microkernel.
   All other functions are delegated to autonomous processes that communicate with the central kernel via clearly defined communication interfaces — for example, various filesystems, memory management, and so on.
   (Of course, the most elementary level of memory management that controls communication with the system itself is in the microkernel. However, handling on the system call level is implemented in external servers.)
   Theoretically, this is a very elegant approach because the individual parts are clearly segregated from each other, and this forces programmers to use ‘‘clean‘‘ programming techniques.
   Other benefits of this approach are dynamic extensibility and the ability to swap important components at run time.
   However, owing to the additional CPU time needed to support complex communication between the components, microkernels have not really established themselves in practice although they have been the subject of active and varied research for some time now.
2. Monolithic Kernels — They are the alternative, traditional concept.
   Here, the entire code of the kernel — including all its subsystems such as memory management, filesystems, or device drivers — is packed into a single file.
   Each function has access to all other parts of the kernel; this can result in elaborately nested source code if programming is not done with great care.

Because, at the moment, the performance of monolithic kernels is still greater than that of microkernels, Linux was and still is implemented according to this paradigm.
However, one major innovation has been introduced.
Modules with kernel code that can be inserted or removed while the system is up-and-running support the dynamic addition of a whole range of functions to the kernel, thus compensating for some of the disadvantages of monolithic kernels.
This is assisted by elaborate means of communication between the kernel and userland that allows for implementing hotplugging and dynamic loading of modules.

## Virtualization

The primary way the OS does this is through a general technique that we call virtualization.
That is, the OS takes a physical resource (such as the processor, or memory, or a disk) and transforms it into a more general, powerful, and easy-to-use virtual form of itself.
Thus, we sometimes refer to the operating system as a virtual machine.

In order to virtualize the CPU, the operating system needs to somehow share the physical CPU among many jobs running seemingly at the same time.
The basic idea is simple: run one process for a little while, then run another one, and so forth. By time sharing the CPU in this manner, virtualization is achieved.

There are a few challenges, however, in building such virtualization machinery.

- The first is performance how can we implement virtualization without adding excessive overhead to the system?
- The second is control: how can we run processes efficiently while retaining control over the CPU?

> THE CRUX:
> HOW TO EFFICIENTLY VIRTUALIZE THE CPU WITH CONTROL
> The OS must virtualize the CPU in an efficient manner while retaining control over the system.

### How to Perform Restricted Operations?

A process must be able to perform I/O and some other restricted operations, but without giving the process complete control over the system.
How can the OS and hardware work together to do so?

- Thus, the approach we take is to introduce a new processor mode, known as **user mode**; code that runs in user mode is restricted in what it can do.
- In contrast to user mode is **kernel mode**, which the operating system(or kernel) runs in.
  In this mode, code that runs can do what it likes, including privileged operations such as issuing I/O requests and executing all types of restricted instructions.

To allow a user process do when it wishes to perform some kind of privileged operation, virtually all modern hardware provides the ability for user programs to perform a **system call**.
Special instructions to trap into the kernel and return-from-trap back to user-mode programs are also provided, as well as instructions that allow the OS to tell the hardware where the trap table resides in memory

The kernel does so by setting up a **trap table** at boot time.
When the machine boots up, it does so in privileged (kernel) mode, and thus is free to configure machine hardware as need be.
One of the first things the OS thus does is to tell the hardware what code to run when certain exceptional events occur.

### How to regain control of the CPU

A Cooperative Approach: Wait For System Calls

A Non-Cooperative Approach: The OS Takes Control

#### How to regain control without cooperation

The addition of a timer interrupt gives the OS the ability to run again on a CPU even if processes act in a non-cooperative fashion.

During the boot sequence, the OS must start the timer, which is of course a privileged operation.
Once the timer has begun, the OS can thus feel safe in that control will eventually be returned to it, and thus the OS is free to run user programs.
The timer can also be turned off (also a privileged operation).

Note that the hardware has some responsibility when an interrupt occurs, in particular to save enough of the state of the program that was running when the interrupt occurred such that a subsequent return-fromtrap instruction will be able to resume the running program correctly.
This set of actions is quite similar to the behavior of the hardware during an explicit system-call trap into the kernel, with various registers thus getting saved (e.g., onto a kernel stack) and thus easily restored by the return-from-trap instruction.

Now that the OS has regained control, whether cooperatively via a system call, or more forcefully via a timer interrupt, a decision has to be made: whether to continue running the currently-running process, or switch to a different one.
This decision is made by a part of the operating system known as the scheduler.

##### Context Switch

If the decision is made to switch, the OS then executes a low-level piece of code which we refer to as a **context switch**.
A context switch is conceptually simple: all the OS has to do is save a few register values for the currently-executing process (onto its kernel stack, for example) and restore a few for the soon-to-be-executing process (from its kernel stack).
By doing so, the OS thus ensures that when the return-from-trap instruction is finally executed, instead of returning to the process that was running, the system resumes execution of another process.

To save the context of the currently-running process, the OS will execute some low-level assembly code to save the general purpose registers, PC, and the kernel stack pointer of the currently-running process, and then restore said registers, PC, and switch to the kernel stack for the soon-to-be-executing process.
By switching stacks, the kernel enters the call to the switch code in the context of one process (the one that was interrupted) and returns in the context of another (the soon-to-be-executing one).
When the OS then finally executes a return-from-trap instruction, the soon-to-be-executing process becomes the currently-running process.
And thus the context switch is complete.

> [!TIP]
>
> Reboot is Useful
>
> The only solution to infinite loops (and similar behaviors) under cooperative preemption is to reboot the machine.
>
> - Specifically, reboot is useful because it moves software back to a known and likely more tested state.
> - Reboots also reclaim stale or leaked resources (e.g., memory) which may otherwise be hard to handle.
> - Finally, reboots are easy to automate.

## Architecture

- [Processes and Threads](/docs/CS/OS/process.md)
- [Memory Management](/docs/CS/OS/memory/memory.md)
- [File Systems](/docs/CS/OS/file.md)
- [Input/Output](/docs/CS/OS/IO.md)
- [Security](/docs/CS/OS/Security.md)

> *Adding more code adds more bugs.*

> [!TIP]
>
> *Don’t hide power.*

System Structure

Layered Systems

Exokernels

Microkernels

Extensible Systems

Top-Down vs. Bottom-Up

While it is best to design the system top down, in theory it can be implemented top down or bottom up.
The problem with this approach is that it is hard to test anything with only the top-level procedures available.
For this reason, many dev elopers find it more practical to actually build the system bottom up.

Synchronous vs. Asynchronous Communication

Other operating systems build their interprocess communication using asynchronous primitives. In a way, asynchronous communication is even simpler than its synchronous cousin.
A client process sends a message to a server, but rather than wait for the message to be delivered or a reply to be sent back, it just continues executing.
Of course, this means that it also receives the reply asynchronously and should remember which request corresponded to it when it arrives.
The server typically processes the requests (events) as a single thread in an event loop.

Whenever the request requires the server to contact other servers for further proc essing it sends an asynchronous message of its own and, rather than block, continues with the next request.
Multiple threads are not needed. With only a single thread processing events, the problem of multiple threads accessing shared data structures cannot occur.
On the other hand, a long-running event handler makes the single-threaded server’s response sluggish.

Whether threads or events are the better programming model is a long-standing controversial issue that has stirred the hearts of zealots on either side ever since John Ousterhout’s classic paper:
‘Why threads are a bad idea (for most purposes)’’(1996).
Ousterhout argues that threads make everything needlessly complicated:locking, debugging, callbacks, performance—you name it. Of course, it would not be a controversy if everybody agreed.
A few years after Ousterhout’s paper, Von Behren et al. (2003) published a paper titled ‘‘Why events are a bad idea (for high concurrency servers).’’
Thus, deciding on the right programming model is a hard, but important decision for system designers. There is no slam-dunk winner.
Web servers like apache firmly embrace synchronous communication and threads, but others like lighttpd are based on the ev ent-driven paradigm. Both are very popular.
In our opinion, events are often easier to understand and debug than threads.
As long as there is no need for per-core concurrency, they are probably a good choice.

## Lifecycle

[BootLoader](/docs/CS/OS/BootLoader.md)


## Kernel Compile





[Linux](/docs/CS/OS/Linux/Linux.md) is an operating system.



[MacOS](/docs/CS/OS/mac/mac.md)

## Performance

Performance metrics are selected statistics generated by the system, applications, or additional tools that measure activity of interest.
They are studied for performance analysis and monitoring, either numerically at the command line or graphically using visualizations.

Common types of system performance metrics include:

- **Throughput:** Either operations or data volume per second
- **IOPS:** I/O operations per second
- **Utilization:** How busy a resource is, as a percentage
- **Latency:** Operation time, as an average or percentile

The usage of throughput depends on its context. Database throughput is usually a measure of queries or requests (operations) per second.
Network throughput is a measure of bits or bytes (volume) per second.

IOPS is a throughput measurement for I/O operations only (reads and writes). Again, context matters, and definitions can vary.

Performance metrics are not free; at some point, CPU cycles must be spent to gather and store them.
This causes overhead, which can negatively affect the performance of the target of measurement.
This is called the _observer effect_.

You might assume that a software vendor has provided metrics that are well chosen, are bug-free, and provide complete visibility.
In reality, metrics can be confusing, complicated, unreliable, inaccurate, and even plain wrong (due to bugs).
Sometimes a metric was correct in one software version but did not get updated to reflect the addition of new code and code paths.

## Others

[Containerization](/docs/CS/Container/Container.md) is the packaging of software code with just the operating system (OS) libraries and dependencies required to 
run the code to create a single lightweight executable—called a container—that runs consistently on any infrastructure.

## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [Operating Systems: Three Easy Pieces](https://pages.cs.wisc.edu/~remzi/OSTEP/)
2. [Operating Systems Concepts]()
3. [Modern Operating Systems](https://media.pearsoncmg.com/bc/abp/cs-resources/products/product.html#product,isbn=013359162X)
