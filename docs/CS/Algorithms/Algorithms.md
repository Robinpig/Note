## Introduction



## Data Structures
An abstract data type (ADT) is a set of operations. 
Abstract data types are mathematical abstractions; nowhere in an ADT's definition is there any mention of how the set of operations is implemented. 
This can be viewed as an extension of modular design.



### Lists, Stacks, and Queues

array
- [Linked List](/docs/CS/Algorithms/linked-list.md)

One of the basic rules concerning programming is that no routine should ever exceed a page. 
This is accomplished by breaking the program down into modules. Each module is a logical unit and does a specific job. 
Its size is kept small by calling other modules. Modularity has several advantages. 
- First, it is much easier to debug small routines than large routines. 
- Second, it is easier for several people to work on a modular program simultaneously. 
- Third, a well-written modular program places certain dependencies in only one routine, making changes easier. 

For instance, if output needs to be written in a certain format, it is certainly important to have one routine to do this. 
If printing statements are scattered throughout the program, it will take considerably longer to make modifications. 
The idea that global variables and side effects are bad is directly attributable to the idea that modularity is good.

An abstract data type (ADT) is a set of operations. 
Abstract data types are mathematical abstractions; nowhere in an ADT's definition is there any mention of how the set of operations is implemented. 
This can be viewed as an extension of modular design.


[Lists](/docs/CS/Algorithms/list.md), [stacks](/docs/CS/Algorithms/stack.md), and [queues](/docs/CS/Algorithms/queue.md) are perhaps the three fundamental data structures in all of computer science.
  
### Tree

[Trees](/docs/CS/Algorithms/tree.md) in general are very useful abstractions in computer science.
- [Trie](/docs/CS/Algorithms/Trie.md)
- [BinaryTree](/docs/CS/Algorithms/BinaryTree.md)
- [Red-Black Tree](/docs/CS/Algorithms/Red-Black-Tree.md)


A [hash](/docs/CS/Algorithms/hash.md) is a mathematical function that converts an input of arbitrary length into an encrypted output of a fixed length.


### Page Replacement Algorithms
- [LRU](/docs/CS/Algorithms/LRU.md)

## Algorithm Analysis

In computer science, the analysis of algorithms is the process of finding the computational complexity of algorithms – the amount of time, storage, or other resources needed to execute them.
Usually, this involves determining a function that relates the length of an algorithm's input to the number of steps it takes (its time complexity) or the number of storage locations it uses (its space complexity).
An algorithm is said to be efficient when this function's values are small, or grow slowly compared to a growth in the size of the input. 
Different inputs of the same length may cause the algorithm to have different behavior, so best, worst and average case descriptions might all be of practical interest. 
When not otherwise specified, the function describing the performance of an algorithm is usually an upper bound, determined from the worst case inputs to the algorithm.

In theoretical analysis of algorithms it is common to estimate their complexity in the asymptotic sense, i.e., to estimate the complexity function for arbitrarily large input. 
Big O notation, Big-omega notation and Big-theta notation are used to this end.

Exact (not asymptotic) measures of efficiency can sometimes be computed but they usually require certain assumptions concerning the particular implementation of the algorithm, called model of computation. 
A model of computation may be defined in terms of an abstract computer, e.g., Turing machine, and/or by postulating that certain operations are executed in unit time.

### Model

This model clearly has some weaknesses. Obviously, in real life, not all operations take exactly the same time. In particular, in our model one disk read counts the same as an addition, even though the addition is typically several orders of magnitude faster. Also, by assuming infinite memory, we never worry about page faulting, which can be a real


Euclid's algorithm is for computing the greatest common divisor. 
The greatest common divisor (gcd) of two integers is the largest integer that divides both.

### Advanced Design and Analysis Techniques
- [Dynamic Programming](/docs/CS/Algorithms/DP.md)
- [Greedy Programming](/docs/CS/Algorithms/Greedy.md)





## Sorting and Order Statistics

- [Sort](/docs/CS/Algorithms/Sort.md)

### Heapsort

### Quicksort

### Sorting in Linear Time

### Medians and Order Statistics

Divide-and-Conquer

## Data Structures


### Binary Search Trees

### Red-Black Trees

AVL Tree

## Advanced Design and Analysis Techniques

### Dynamic Programming

### Greedy Algorithms

### Amortized Analysis


## Advanced Data Structures

### B-Trees

### Fibonacci Heaps


## Graph Algorithms


## Advanced Design and Analysis Techniques

### Dynamic Programming

### Greedy Algorithms

### Amortized Analysis


## Advanced Data Structures

### B-Trees

### Fibonacci Heaps


## Graph Algorithms


## References
1. Introduction to Algorithms Third Edition
2. Introduction to The Design and Analysis of Algorithms Third Edition
3. Algorithms Fourth Edition