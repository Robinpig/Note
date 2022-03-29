## Introduction


I/O multiplexing is typically used in networking applications in the following scenarios:
- When a client is handling multiple descriptors (normally interactive input and a network socket), I/O multiplexing should be used.
- It is possible, but rare, for a client to handle multiple sockets at the same time.
- If a TCP server handles both a listening socket and its connected sockets, I/O multiplexing is normally used.
- If a server handles both TCP and UDP, I/O multiplexing is normally used.
- If a server handles multiple services and perhaps multiple protocols, I/O multiplexing is normally used.

I/O multiplexing is not limited to network programming. Many nontrivial applications find a need for these techniques.

## I/O Models

Before describing select and poll, we need to step back and look at the bigger picture, examining the basic differences in the five I/O models that are available to us
under Unix:
- blocking I/O
- nonblocking I/O
- I/O multiplexing (select and poll)
- signal driven I/O (SIGIO)
- asynchronous I/O (the POSIX aio_ functions)


Figure from UNP:

![Comparison of the five I/O models](./images/Comparison%20of%20the%20five%20IO%20models.png)


There are normally two distinct phases for an input operation:
1. Waiting for the data to be ready
2. Copying the data from the kernel to the process

For an input operation on a socket, the first step normally involves waiting for data to arrive on the network. 
When the packet arrives, it is copied into a buffer within the kernel. The second step is copying this data from the kernel’s buffer into our application buffer.

The main difference between the first four models is the first phase, as the second phase in the first four models is the same: the process is blocked in a call to recvfrom while the data is copied from the kernel to the caller’s buffer. 
Asynchronous I/O, however, handles both phases and is different from the first four.

> [!NOTE]
> 
> POSIX defines these two terms as follows:
> - A synchronous I/O operation causes the requesting process to be blocked until that I/O operation completes.
> - An asynchronous I/O operation does not cause the requesting process to be blocked.

Using these definitions, the first four I/O models—blocking, nonblocking, I/O multiplexing, and signal-driven I/O—are all synchronous because the actual I/O operation(recvfrom) blocks the process. 
Only the asynchronous I/O model matches the asynchronous I/O definition.


## select



## Links
- [Computer Network](/docs/CS/CN/CN.md)