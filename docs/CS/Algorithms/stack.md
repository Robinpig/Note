## Introduction

A stack is a simple data structure used for storing data (similar to [Linked Lists](/docs/CS/Algorithms/linked-list.md)).
A stack is an ordered list in which insertion and deletion are done at one end, called top. 
The last element inserted is the first one to be deleted.
Hence, it is called the Last in First out (LIFO) or First in Last out (FILO) list.

Special names are given to the two changes that can be made to a stack. 
When an element is inserted in a stack, the concept is called *push*, and when an element is removed from the stack, the concept is called *pop*.
Trying to pop out an empty stack is called *underflow* and trying to push an element in a full stack is called *overflow*.
Generally, we treat them as exceptions.


## Stack ADT

The following operations make a stack an ADT.
For simplicity, assume the data is an integer type.

**Main stack operations**

- Push (int data): Inserts data onto stack.
- int Pop(): Removes and returns the last inserted element from the stack.

**Auxiliary stack operations**

- int Top(): Returns the last inserted element without removing it.
- int Size(): Returns the number of elements stored in the stack.
- int IsEmptyStack(): Indicates whether any elements are stored in the stack or not.
- int IsFullStack(): Indicates whether the stack is full or not.

**Exceptions**

Attempting the execution of an operation may sometimes cause an error condition, called an exception.
Exceptions are said to be “thrown” by an operation that cannot be executed.
In the Stack ADT, operations pop and top cannot be performed if the stack is empty. Attempting the execution of pop (top) on an empty stack throws an exception.
Trying to push an element in a full stack throws an exception.

## Applications

Following are some of the applications in which stacks play an important role.

**Direct applications**

- Balancing of symbols
- Infix-to-postfix conversion
- Evaluation of postfix expression
- Implementing function calls (including recursion)
- Finding of spans (finding spans in stock markets, refer to Problems section)
- Page-visited history in a Web browser [Back Buttons]
- Undo sequence in a text editor
- Matching Tags in HTML and XML

**Indirect applications**

- Auxiliary data structure for other algorithms (Example: Tree traversal algorithms)
- Component of other data structures (Example: [Simulating queues]())

## Implementation

There are many ways of implementing stack ADT; given below are the commonly used methods.

- Simple array based implementation
- Dynamic array based implementation
- Linked lists implementation

### Comparison of Implementations

**Comparing Incremental Strategy and Doubling Strategy**

We compare the incremental strategy and doubling strategy by analyzing the total time T(n) needed to perform a series of n push operations.
We start with an empty stack represented by an array of size 1.
We call amortized time of a push operation is the average time taken by a push over the series of operations, that is, $T(n)/n$.

**Incremental Strategy**

The amortized time (average time per operation) of a push operation is $O(n)$ $[O(n2)/n]$.

**Doubling Strategy**

In this method, the amortized time of a push operation is $O(1)$ $[O(n)/n]$.

Comparing Array Implementation and Linked List Implementation

Array Implementation

- Operations take constant time.
- Expensive doubling operation every once in a while.
- Any sequence of n operations (starting from empty stack) - “amortized” bound takes time proportional to n.

Linked List Implementation

- Grows and shrinks gracefully.
- Every operation takes constant time O(1).
- Every operation uses extra space and time to deal with references.

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [list](/docs/CS/Algorithms/list.md)
- [queue](/docs/CS/Algorithms/queue.md)
