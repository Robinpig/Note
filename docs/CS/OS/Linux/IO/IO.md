## Introduction



unbuffered I/O

open read write lseek close

Most file I/O on a UNIX system can be performed using only five functions: open, read, write, lseek, and close.
These functions are often referred to as unbuffered I/O.


## BIO

Blocking system calls

Read/write



## NIO



select/poll/epoll



only support network sockets and pipes



Databases  **`O_DIRECT`**

Direct IO, don't use os page cache

Zero-Copy IO







## AIO
Native IO
[Design Notes on Asynchronous I/O (aio) for Linux](http://lse.sourceforge.net/io/aionotes.txt)

libaio

- ony support Direct IO





Io_uring


bypass IO