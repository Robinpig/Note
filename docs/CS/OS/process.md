## Introduction

The most central concept in any operating system is the process: an abstraction of a running program.
A process is just an instance of an executing program, including the current values of the program counter, registers, and variables.
Conceptually, each process has its own virtual CPU.
In reality, of course, the real CPU switches back and forth from process to process.
This rapid switching back and forth is called *multiprogramming*.


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

## Links

- [Linux Process](/docs/CS/OS/Linux/process.md)