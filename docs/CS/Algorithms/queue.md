## Introduction

A queue is a data structure used for storing data (similar to Linked Lists and Stacks). In queue, the order in which data arrives is important.
In general, a queue is a line of people or things waiting to be served in sequential order starting at the beginning of the line or sequence.

A queue is an ordered list in which insertions are done at one end (rear) and deletions are done at other end (front).
The first element to be inserted is the first one to be deleted. Hence, it is called First in First out (**FIFO**) or Last in Last out (**LILO**) list.


Similar to Stacks, special names are given to the two changes that can be made to a queue.
When an element is inserted in a queue, the concept is called EnQueue, and when an element is removed from the queue, the concept is called DeQueue. 
DeQueueing an empty queue is called underflow and EnQueuing an element in a full queue is called overflow. 
Generally, we treat them as exceptions.



队列跟栈一样，也是一种**操作受限的线性表数据结构**

作为一种非常基础的数据结构，队列的应用也非常广泛，特别是一些具有某些额外特性的队列，比如循环队列、阻塞队列、并发队列。它们在很多偏底层系统、框架、中间件的开发中，起着关键性的作用。比如高性能队列Disruptor、Linux环形缓存，都用到了循环并发队列；Java concurrent并发包利用ArrayBlockingQueue来实现公平锁等

 

跟栈一样，队列可以用数组来实现，也可以用链表来实现。用数组实现的栈叫作顺序栈，用链表实现的栈叫作链式栈。同样，用数组实现的队列叫作**顺序队列**，用链表实现的队列叫作**链式队列**。

 

使用阻塞队列，轻松实现一个“生产者-消费者模型”！

线程安全的队列我们叫作**并发队列**。最简单直接的实现方式是直接在enqueue()、dequeue()方法上加锁，但是锁粒度大并发度会比较低，同一时刻仅允许一个存或者取操作。实际上，基于数组的循环队列，利用CAS原子操作，可以实现非常高效的并发队列。这也是循环队列比链式队列应用更加广泛的原因


## Queue ADT
The following operations make a queue an ADT. Insertions and deletions in the queue must follow the FIFO scheme. For simplicity we assume the elements are integers.

**Main Queue Operations**

- EnQueuefint data): Inserts an element at the end of the queue
- int DeQueue(): Removes and returns the element at the front of the queue

**Auxiliary Queue Operations**

- int Front(): Returns the element at the front without removing it
- int QueueSize(): Returns the number of elements stored in the queue
- int IsEmptyQueue(): Indicates whether no elements are stored in the queue or not

**Exceptions**

Similar to other ADTs, executing DeQueue on an empty queue throws an “Empty Queue Exception” and executing EnQueue on a full queue throws a “Full Queue Exception”.

## Applications

Following are the some of the applications that use queues.

Direct Applications
- Operating systems schedule jobs (with equal priority) in the order of arrival (e.g., a print queue).
- Simulation of real-world queues such as lines at a ticket counter or any other first- come first-served scenario requires a queue.
- Multiprogramming.
- Asynchronous data transfer (file IO, pipes, sockets).
- Waiting times of customers at call center.
- Determining number of cashiers to have at a supermarket.

Indirect Applications
- Auxiliary data structure for algorithms
- Component of other data structures



## Implementation

There are many ways (similar to Stacks) of implementing queue operations and some of the commonly used methods are listed below.
- Simple circular array based implementation
- Dynamic circular array based implementation
- Linked list implementation

**Why Circular Arrays?**

First, let us see whether we can use simple arrays for implementing queues as we have done for stacks. 
We know that, in queues, the insertions are performed at one end and deletions are performed at the other end. 
After performing some insertions and deletions the process becomes easy to understand. In the example shown below, it can be seen clearly that the initial slots of the array are getting wasted. 
So, simple array implementation for queue is not efficient. To solve this problem we assume the arrays as circular arrays. 
That means, we treat the last element and the first array elements as contiguous.
With this representation, if there are any free slots at the beginning, the rear pointer can easily go to its next free slot.
With this representation, if there are any free slots at the beginning, the rear pointer can easily go to its next free slot.

> [!Note]
> 
> The simple circular array and dynamic circular array implementations are very similar to stack array implementations.

### Simple Circular Array Implementation

This simple implementation of Queue ADT uses an array.
In the array, we add elements circularly and use two variables to keep track of the start element and end element. 
Generally, front is used to indicate the start element and rear is used to indicate the end element in the queue. 
The array storing the queue elements may become full. An EnQueue operation will then throw a full queue exception. 
Similarly, if we try deleting an element from an empty queue it will throw empty queue exception.


Initially, both front and rear points to -1 which indicates that the queue is empty.

**Limitations:**
The maximum size of the queue must be defined as prior and cannot be changed. Trying to EnQueue a new element into a full queue causes an implementation-specific exception.



## Doubly End Queue

双端队列是支持在头尾两端进行pop和push操作





## Deque










## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [list](/docs/CS/Algorithms/list.md)
- [stack](/docs/CS/Algorithms/stack.md)


## References

1. [Dynamic Circular Work-Stealing Deque](http://www.dre.vanderbilt.edu/~schmidt/PDF/work-stealing-dequeue.pdf)