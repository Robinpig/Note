## Introduction

A queue is a data structure used for storing data (similar to Linked Lists and Stacks). In queue, the order in which data arrives is important.
In general, a queue is a line of people or things waiting to be served in sequential order starting at the beginning of the line or sequence.

A queue is an ordered list in which insertions are done at one end (rear) and deletions are done at other end (front).
The first element to be inserted is the first one to be deleted. Hence, it is called First in First out (**FIFO**) or Last in Last out (**LILO**) list.


Similar to Stacks, special names are given to the two changes that can be made to a queue.
When an element is inserted in a queue, the concept is called EnQueue, and when an element is removed from the queue, the concept is called DeQueue. 
DeQueueing an empty queue is called underflow and EnQueuing an element in a full queue is called overflow. 
Generally, we treat them as exceptions.


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