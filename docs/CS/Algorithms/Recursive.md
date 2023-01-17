## Introduction

A procedure that calls itself, directly or indirectly, is said to be *recursive*.
The use of recursion often permits more lucid and concise descriptions of algorithms than would be possible without recursion.

These considerations lead to the first two fundamental rules of recursion:

1. Base cases. You must always have some base cases, which can be solved without recursion.
2. Making progress. For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.

A recursive function performs a task in part by calling itself to perform the subtasks.
At some point, the function encounters a subtask that it can perform without calling itself.
This case, where the function does not recur, is called the base case.
The former, where the function calls itself to perform a subtask, is referred to as the recursive case.
We can write all recursive functions using the format:

```
if(test for the base case)
	return some base case value
else if(test for another base case)
	return some other base case value
// the recursive case
else
	return (some work and then a recursive call)
```

When writing recursive routines, it is crucial to keep in mind the four basic rules of recursion:

1. Base cases. You must always have some base cases, which can be solved without recursion.
2. Making progress. For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.
3. Design rule. Assume that all the recursive calls work.
4. Compound interest rule. Never duplicate work by solving the same instance of a problem in separate recursive calls.

Each recursive call makes a new copy of that method (actually only the variables) in memory.
Once a method ends (that is, returns some data), the copy of that returning method is removed from memory.
The recursive solutions look simple but visualization and tracing takes time.

## Recursion versus Iteration

While discussing recursion, the basic question that comes to mind is: which way is better? – iteration or recursion?
The answer to this question depends on what we are trying to do. A recursive approach mirrors the problem that we are trying to solve.
A recursive approach makes it simpler to solve a problem that may not have the most obvious of answers.
But, recursion adds overhead for each recursive call (needs space on the stack frame).

Recursion

* Terminates when a base case is reached.
* Each recursive call requires extra space on the stack frame (memory).
* If we get infinite recursion, the program may run out of memory and result in stack overflow.
* Solutions to some problems are easier to formulate recursively.

Iteration

* Terminates when a condition is proven to be false.
* Each iteration does not require any extra space.
* An infinite loop could loop forever since there is no extra memory being created.
* Iterative solutions to a problem may not always be as obvious as a recursive solution.

**Notes on Recursion**

* Recursive algorithms have two types of cases, recursive cases and base cases.
* Every recursive function case must terminate at a base case.
* Generally, iterative solutions are more efficient than recursive solutions [due to the overhead of function calls].
* A recursive algorithm can be implemented without recursive function calls using a stack, but it’s usually more trouble than its worth.
  That means any problem that can be solved recursively can also be solved iteratively.
* For some problems, there are no obvious iterative algorithms.
* Some problems are best suited for recursive solutions while others are not.

## Example Algorithms of Recursion

* Fibonacci Series, Factorial Finding
* Merge Sort, Quick Sort
* Binary Search
* Tree Traversals and many Tree Problems: InOrder, PreOrder PostOrder
* Graph Traversals: DFS [Depth First Search] and BFS [Breadth First Search]
* [Dynamic Programming Examples](/docs/CS/Algorithms/DP.md)
* Divide and Conquer Algorithms
* Towers of Hanoi
* [Backtracking Algorithms](/docs/CS/Algorithms/Backtracking.md)

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

## References
