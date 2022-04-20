## Introduction


OS 

- Kernel
- Shell


## Architecture

- [Processes and Threads](/docs/CS/OS/process.md)
- [Memory Management](/docs/CS/OS/memory.md)
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






## Linux

[Linux](/docs/CS/OS/Linux/Linux.md) is an operating system.


## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Network](/docs/CS/CN/CN.md)


## References

1. [Operating Systems: Three Easy Pieces](https://pages.cs.wisc.edu/~remzi/OSTEP/)
2. [Operating Systems Concepts]()
3. [Modern Operating Systems](https://media.pearsoncmg.com/bc/abp/cs-resources/products/product.html#product,isbn=013359162X)