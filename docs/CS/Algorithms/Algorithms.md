## Introduction



1900年 大卫希尔伯特提出了著名的希尔伯特之23个问题 第10个问题是 通过有限多次运算 测试多项式是否有整数根



1936年 图灵提出《论数学计算在决断难题中之应用》 提出图灵机的概念





以下涉及的都是计算机算法


算法应用


社会

推荐算法
- 衣食住行 买东西

路径规划算法


人工智能算法





## Data Structures

Data structure is a particular way of storing and organizing data in a computer so that it can be used efficiently.
A data structure is a special format for organizing and storing data. 
General data structure types include arrays, files, linked lists, stacks, queues, trees, graphs and so on.
<br>
Depending on the organization of the elements, data structures are classified into two types:

1) Linear data structures: Elements are accessed in a sequential order but it is not compulsory to store all elements sequentially (say, Linked Lists).
   Examples: Linked Lists, Stacks and Queues.
2) Non – linear data structures: Elements of this data structure are stored / accessed in a non-linear order. Examples: Trees and graphs.

An abstract data type (ADT) is a set of operations.
Abstract data types are mathematical abstractions; nowhere in an ADT's definition is there any mention of how the set of operations is implemented.
This can be viewed as an extension of modular design.

Commonly used ADTs include: Linked Lists, Stacks, Queues, Priority Queues, Binary Trees, Dictionaries, Disjoint Sets (Union and Find), Hash Tables, Graphs, and many others.
For example, stack uses a LIFO (Last-In-First-Out) mechanism while storing the data in data structures.
The last element inserted into the stack is the first element that gets deleted.
Common operations are: creating the stack, pushing an element onto the stack, popping an element from the stack, finding the current top of the stack, finding the number of elements in the stack, etc.

While defining the ADTs do not worry about the implementation details.
They come into the picture only when we want to use them.
Different kinds of ADTs are suited to different kinds of applications, and some are highly specialized to specific tasks.
We will go through many of them and you will be in a position to relate the data structures to the kind of problems they solve.

### Lists, Stacks, and Queues

[Lists](/docs/CS/Algorithms/list.md), [stacks](/docs/CS/Algorithms/stack.md), and [queues](/docs/CS/Algorithms/queue.md) are perhaps the three fundamental data structures in all of computer science.

[Arrays and Linked Lists](/docs/CS/Algorithms/linked-list.md)

One of the basic rules concerning programming is that no routine should ever exceed a page.
This is accomplished by breaking the program down into modules. Each module is a logical unit and does a specific job.
Its size is kept small by calling other modules. Modularity has several advantages.

- First, it is much easier to debug small routines than large routines.
- Second, it is easier for several people to work on a modular program simultaneously.
- Third, a well-written modular program places certain dependencies in only one routine, making changes easier.

For instance, if output needs to be written in a certain format, it is certainly important to have one routine to do this.
If printing statements are scattered throughout the program, it will take considerably longer to make modifications.
The idea that global variables and side effects are bad is directly attributable to the idea that modularity is good.

We introduce [hash tables](/docs/CS/Algorithms/hash.md), a widely used data structure supporting the dictionary operations INSERT, DELETE, and SEARCH.
In the worst case, hash tables require Θ(n) time to perform a SEARCH operation, but the expected time for hash-table operations is $O(1)$.
We rely on probability to analyze hash-table operations, but you can understand how the operations work even without probability.

### Tree

[Trees](/docs/CS/Algorithms/tree/tree.md) in general are very useful abstractions in computer science.

- [Trie](/docs/CS/Algorithms/tree/Trie.md)
- [Red-Black Tree](/docs/CS/Algorithms/tree/Red-Black-Tree.md)

> [!NOTE]
>
> **Definition**.
> A symbol table is a data structure for key-value pairs that supports two operations: insert (put) a new pair into the table and search for (get) the value associated with a given key.

### Heap

[heaps](/docs/CS/Algorithms/heap.md)

### Graph

[Graph](/docs/CS/Algorithms/graph/graph.md)



[Disjoing Set](/docs/CS/Algorithms/Disjoint-Ser.md)

[BloomFilter](/docs/CS/Algorithms/BloomFilter.md)





### Page Replacement Algorithms

- [LRU](/docs/CS/Algorithms/LRU.md)


| 算法规则                | 优缺点                                                                                                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OPT                     | 优先淘汰最长时间内不会被访问的页面	缺页率最小，性能最好;但无法实现                                                                                                               |
| FIFO                    | 优先淘汰最先进入内存的页面	实现简单;但性能很差，可能出现Belady异常                                                                                                               |
| LRU                     | 优先淘汰最近最久没访问的页面	性能很好;但需要硬件支持，算法开销大                                                                                                                 |
| CLOCK (NRU)             | 循环扫描各页面 第一轮淘汰访问位=0的，并将扫描过的页面访问位改为1。若第-轮没选中，则进行第二轮扫描。	实现简单，算法开销小;但未考虑页面是否被修改过。                              |
| 改进型CLOCK (改进型NRU) | 若用(访问位，修改位)的形式表述，则 第一轮:淘汰(0,0) 第二轮:淘汰(O,1)，并将扫描过的页面访问位都置为0 第三轮:淘汰(O, 0) 第四轮:淘汰(0, 1)	算法开销较小，性能也不错 PDF文档下载方式 |

### Pattern Matching

[Substring Search](/docs/CS/Algorithms/KMP.md)

## Algorithm Analysis



An *algorithm* is a finite set of instructions that, if followed, accomplishes a particular task.
In addition, all algorithms must satisfy the following criteria:

1. **Input**. There are zero or more quantities that are externally supplied.
2. **Output**. At least one quantity is produced.
3. **Definiteness**. Each instruction is clear and unambiguous.
4. **Finiteness**. If we trace out the instructions of an algorithm, then for all cases, the algorithm terminates after a finite number of steps.
5. **Effectiveness**. Every instruction must be basic enough to be carried out, in principle, by a person using only pencil and paper. 
   It is not enough that each operation be definite as in 3; it also must be feasible.

Computer algorithms solve computational problems.
We want two things from a computer algorithm: given an input to a problem, it should always produce a correct solution to the problem,
and it should use computational resources efficiently while doing so. 
Let’s examine these two desiderata in turn.

For some problems, it might be difficult or even impossible to say whether an algorithm produces a correct solution.
Sometimes we can accept that a computer algorithm might produce an incorrect answer, as long as we can control how often it does so.
Correctness is a tricky issue with another class of algorithms, called approximation algorithms. 
Approximation algorithms apply to optimization problems, in which we want to find the best solution according to some quantitative measure.
Finding the fastest route, as a GPS does, is one example, where the quantitative measure is travel time.
For some problems, we have no algorithm that finds an optimal solution in any reasonable amount of time, but we know of an approximation algorithm that,
in a reasonable amount of time, can find a solution that is almost optimal. 

What does it mean for an algorithm to use computational resources efficiently? 
Indeed, time is the primary measure of efficiency that we use to evaluate an algorithm, once we have shown that the algorithm gives a correct solution.
But it is not the only measure.
We might be concerned with how much computer memory the algorithm requires (its “memory footprint”), since an algorithm has to run within the available memory.
Other possible resources that an algorithm might use: network communication, random bits (because algorithms that make random choices need a source of random numbers),
or disk operations (for algorithms that are designed to work with disk-resident data).”



### Complexity

Algorithms can be evaluated by a variety of criteria.
Most often we shall be interested in the rate of growth of the time or space required to solve larger and larger instances of a problem.
We would like to associate with a problem an integer. called the size of the problem, which is a measure of the quantity of input data.

The time needed by an algorithm expressed as a function of the size of a problem is called the *time complexity* of the algorithm.
The limiting behavior of the compiexity as size increases is called the *asymptotic time complexity*.
Analogous definitions can be made for *space complexity* and *asymptotic space complexity*.

The asymptotic complexity of an algorithm is an important measure of the goodness of an algorithm, one that promises to become even more important with future increases in computing speed.

Despite our concentration on order-of-magnitude performance, we should realize that an algorithm with a rapid growth rate might have a smaller constant of proportionality than one with a lower growth rate.
In that case. the rapidly growing algorithm might be superior for small problems. possibly even for all problems of a size that would interest us.

If for a given size the complexity is taken as the maximum complexity over all inputs of that size, then the complexity is called the *worst-case complexity*.
If the complexity is taken as the "average" complexity over all inputs of given size. then the complexity is called the *expected complexity*.
The expected complexity of an algorithm is usually more difficult to ascertain than the worst-case complexity.
One must make some assumption about the distribution of inputs, and realistic assumptions are often not mathematically tractable.
We shall emphasize the worst case, since it is more tractable and has a universal applicability.
However. it should be borne in mind that the algorithm with the best worst-case complexity does not necessarily have the best expected complexity.

In theoretical analysis of algorithms it is common to estimate their complexity in the asymptotic sense, i.e., to estimate the complexity function for arbitrarily large input.
Big O notation, Big-omega notation and Big-theta notation are used to this end.

An abstract data type (ADT) is a data type that is organized in such a way that the specification of the objects and the specification of the operations on the objects is separated from the representation of the objects and the implementation of the operations.

> An algorithm is efficient if its running time is polynomial.

### Computation Model

Exact (not asymptotic) measures of efficiency can sometimes be computed but they usually require certain assumptions concerning the particular implementation of the algorithm, called model of computation.
A model of computation may be defined in terms of an abstract computer, e.g., Turing machine, and/or by postulating that certain operations are executed in unit time.

This model clearly has some weaknesses. Obviously, in real life, not all operations take exactly the same time.
In particular, in our model one disk read counts the same as an addition, even though the addition is typically several orders of magnitude faster.
Also, by assuming infinite memory, we never worry about page faulting, which can be a real

Euclid's algorithm is for computing the greatest common divisor.
The greatest common divisor (gcd) of two integers is the largest integer that divides both.

### Advanced Design and Analysis Techniques

Text-editing programs frequently need to find all occurrences of a pattern in the text.
Typically, the text is a document being edited, and the pattern searched for is a particular word supplied by the user.
Efficient algorithms for this problem—called “[string matching](/docs/CS/Algorithms/KMP.md)”—can greatly aid the responsiveness of the text-editing program.

- [Dynamic Programming](/docs/CS/Algorithms/DP.md)
- [Greedy Programming](/docs/CS/Algorithms/Greedy.md)
- [Amortized Analysis](/docs/CS/Algorithms/Amortized.md)
- [Randomized](/docs/CS/Algorithms/Randomized.md)
- [Backtracking](/docs/CS/Algorithms/Backtracking.md)
- [Divide and Conquer](/docs/CS/Algorithms/Divide-and-Conquer.md)

## Sorting and Order Statistics

- [Sort](/docs/CS/Algorithms/Sort.md)

### Consensus Algorithm

Paxos

Raft

### Compression Algorithms

### 

Gale–Shapley algorithm (also known as the Deferred Acceptance algorithm).
Gale Shapley Algorithm is an efficient algorithm that is used to solve the Stable Matching problem. It takes $O(N^2)$ time complexity where N is the number of people involved.

The subject called the [“NP-complete” problems](/docs/CS/Algorithms/NP.md), whose status is unknown.
No polynomial-time algorithm has yet been discovered for an NP-complete problem, nor has anyone yet been able to prove that no polynomial-time algorithm can exist for any one of them.
This so-called $P != NP$ question has been one of the deepest, most perplexing open research problems in theoretical computer science since it was first posed in 1971.

## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

1. Algorithms + Data Structures = Programs
2. Introduction to Algorithms Third Edition
2. Introduction to The Design and Analysis of Algorithms Third Edition
3. Algorithms Fourth Edition
4. Data Structures and Algorithm Analysis in C
5. The Design and Analysis of Computer Algorithms
