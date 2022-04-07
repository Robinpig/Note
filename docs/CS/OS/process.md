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


## Links

- [Linux Process](/docs/CS/OS/Linux/process.md)