## Introduction

"`Zero-copy`" describes computer operations in which the CPU does not perform the task of copying data from one memory area to another or in which unnecessary data copies are avoided.
This is frequently used to save CPU cycles and memory bandwidth in many time consuming tasks, such as when transmitting a file at high speed over a network, etc., thus improving the performance of programs (processes) executed by a computer.

Zero-copy programming techniques can be used when exchanging data within a user space process (i.e. between two or more threads, etc.) and/or between two or more processes (see also producer–consumer problem) and/or when data has to be accessed / copied / moved inside kernel space or between a user space process and kernel space portions of operating systems (OS).

Usually when a user space process has to execute system operations like reading or writing data from/to a device (i.e. a disk, a NIC, etc.) through their high level software interfaces or like moving data from one device to another, etc., it has to perform one or more system calls that are then executed in kernel space by the operating system.

If data has to be copied or moved from source to destination and both are located inside kernel space (i.e. two files, a file and a network card, etc.) then unnecessary data copies, from kernel space to user space and from user space to kernel space, can be avoided by using special (zero-copy) system calls, usually available in most recent versions of popular operating systems.

Zero-copy versions of operating system elements, such as device drivers, file systems, network protocol stacks, etc., greatly increase the performance of certain application programs (that become processes when executed) and more efficiently utilize system resources.
Performance is enhanced by allowing the CPU to move on to other tasks while data copies / processing proceed in parallel in another part of the machine.
Also, zero-copy operations reduce the number of time-consuming context switches between user space and kernel space.
System resources are utilized more efficiently since using a sophisticated CPU to perform extensive data copy operations, which is a relatively simple task, is wasteful if other simpler system components can do the copying.

As an example, reading a file and then sending it over a network the traditional way requires 2 extra data copies (1 to read from kernel to user space + 1 to write from user to kernel space) and 4 context switches per read/write cycle. Those extra data copies use the CPU.

Sending that file by using mmap of file data and a cycle of write calls, reduces the context switches to 2 per write call and avoids those previous 2 extra user data copies.

Sending the same file via zero copy reduces the context switches to 2 per sendfile call and eliminates all CPU extra data copies (both in user and in kernel space).

Zero-copy protocols are especially important for very high-speed networks in which the capacity of a network link approaches or exceeds the CPU's processing capacity.
In such a case the CPU may spend nearly all of its time copying transferred data, and thus becomes a bottleneck which limits the communication rate to below the link's capacity.
A rule of thumb used in the industry is that roughly one CPU clock cycle is needed to process one bit of incoming data.

Techniques for creating zero-copy software include the use of `direct memory access` (DMA)-based copying and memory-mapping through a memory management unit (MMU).
These features require specific hardware support and usually involve particular memory alignment requirements.

A newer approach used by the Heterogeneous System Architecture (HSA) facilitates the passing of pointers between the CPU and the GPU and also other processors.
This requires a unified address space for the CPU and the GPU.

## Program interfaces

Several operating systems support zero-copying of user data and file contents through specific APIs.
Here are listed only a few well known system calls / APIs available in most popular OSs.

The Linux kernel supports zero-copy through various system calls, such as:

- sendfile;
- splice;
- tee;
- vmsplice;
- process_vm_readv;
- process_vm_writev;
- copy_file_range;
- raw sockets with packet mmap or AF_XDP.

FreeBSD, NetBSD, OpenBSD, DragonFly BSD, etc. support zero-copy through at least these system calls:

- sendfile;
- write, writev + mmap when writing data to a network socket.

Java input streams can support zero-copy through the java.nio.channels.FileChannel's transferTo() method if the underlying operating system also supports zero copy.

RDMA (Remote Direct Memory Access) protocols deeply rely on zero-copy techniques.


## mmap

In computing, mmap(2) is a POSIX-compliant Unix system call that maps files or devices into memory. 
It is a method of memory-mapped file I/O. 
It implements demand paging because file contents are not immediately read from disk and initially use no physical RAM at all. 
The actual reads from disk are performed after a specific location is accessed, in a lazy manner. 


The mmap system call has been used in various database implementations as an alternative for implementing a buffer pool, although this created a different set of problems that could realistically only be fixed using a buffer pool.

> [Are You Sure You Want to Use MMAP in Your Database Management System?](https://db.cs.cmu.edu/papers/2022/cidr2022-p13-crotty.pdf)

## sendfile

The sendfile system call was introduced to simplify the transmission of data over the network and between two local files.
Introduction of sendfile not only reduces data copying, it also reduces context switches.


## References

1. [Zero Copy I: User-Mode Perspective](https://www.linuxjournal.com/article/6345?page=0,0)
