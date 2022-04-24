## Introduction

The role of the operating system in computer I/O is to manage and control I/O operations and I/O devices.

The device drivers present a uniform deviceaccess interface to the I/O subsystem, much as system calls provide a standard interface between the application and the operating system.



## Principles of I/O Hardware

### I/O Devices

I/O devices can be roughly divided into two categories: *block devices* and *character devices*.

### Device Controllers

### Memory-Mapped I/O


### DMA





## Principles of I/O Software

### Goals of the I/O Software

A key concept in the design of I/O software is known as *device independence*.

Closely related to device independence is the goal of uniform naming.

Another important issue for I/O software is error handling.

Still another important issue is that of synchronous (blocking) vs. asynchronous (interrupt-driven) transfers.


Another issue for the I/O software is buffering. Often data that come off a device cannot be stored directly in their final destination. 
For example, when a packet comes in off the network, the operating system does not know where to put it until it has stored the packet somewhere and examined it. 
Also, some devices have severe real-time constraints (for example, digital audio devices), so the data must be put into an output buffer in advance to decouple the rate at which the buffer is filled from the rate at which it is emptied, in order to avoid buffer underruns. 
Buffering involves considerable copying and often has a major impact on I/O performance.


There are three fundamentally different ways that I/O can be performed.

#### Programmed I/O

The simplest form of I/O is to have the CPU do all the work. This method is called *programmed I/O*.

The essential aspect of programmed I/O, is that after outputting a character, the CPU continuously polls the device to see if it is ready to accept another one. 
This behavior is often called *polling* or *busy waiting*.


#### Interrupt-Driven I/O

If IO not completed, the interrupt handler takes some action to unblock the user. 
Otherwise, acknowledges the interrupt, and returns to the process that was running just before the interrupt, which continues from where it left off.

#### I/O Using DMA

An obvious disadvantage of interrupt-driven I/O is that interrupts take time, so this scheme wastes a certain amount of CPU time. A solution is to use DMA.
In essence, DMA is programmed I/O, only with the DMA controller doing all the work, instead of the main CPU. 
This strategy requires special hardware (the DMA controller) but frees up the CPU during the I/O to do other work.

If the DMA controller is not capable of driving the device at full speed, or the CPU usually has nothing to do anyway while waiting for the DMA interrupt, then interrupt-driven I/O or even programmed I/O may be better. 
Most of the time, though, DMA is worth it.

## I/O Software

I/O software is typically organized in four layers. Each layer has a well-defined function to perform and a well-defined interface to the adjacent layers.

![I/O Software Layers](./img/IO%20Software%20Layers.png)


## Links

- [Operating Systems](/docs/CS/OS/OS.md)
