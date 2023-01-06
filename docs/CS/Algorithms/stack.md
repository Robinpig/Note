## Introduction

A stack is a list with the restriction that inserts and deletes can be performed in only one position, namely the end of the list called the top.
The fundamental operations on a stack are push, which is equivalent to an insert, and pop, which deletes the most recently inserted element.
The most recently inserted element can be examined prior to performing a pop by use of the top routine.
A pop or top on an empty stack is generally considered an error in the stack ADT.
On the other hand, running out of space when performing a push is an implementation error but not an ADT error.

Stacks are sometimes known as LIFO (last in, first out) lists.
The usual operations to make empty stacks and test for emptiness are part of the repertoire, but essentially all that you can do to a stack is push and pop.

## Implementation

There are many ways of implementing stack ADT; given below are the commonly used methods.

- Simple array based implementation
- Dynamic array based implementation
- Linked lists implementation

## Applications

Reverse Polish Notation(RPN)

### Balancing Symbols

### Postfix Expressions

### Function Calls

The information saved is called either an activation record or stack frame.

Tail recursion refers to a recursive call at the last line.
Tail recursion can be mechanically eliminated by changing the recursive call to a goto preceded by one assignment per function argument.

Although nonrecursive programs are certainly generally faster than recursive programs, the speed advantage rarely justifies the lack of clarity that results from removing the recursion.

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [list](/docs/CS/Algorithms/list.md)
- [queue](/docs/CS/Algorithms/queue.md)
