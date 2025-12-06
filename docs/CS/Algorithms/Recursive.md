## Introduction

A procedure that calls itself, directly or indirectly, is said to be *recursive*.
The use of recursion often permits more lucid and concise descriptions of algorithms than would be possible without recursion.

When writing recursive routines, it is crucial to keep in mind the four basic rules of recursion:

1. *Base cases.* You must always have some base cases, which can be solved without recursion.
2. *Making progress.* For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.
3. *Design rule.* Assume that all the recursive calls work.
4. *Compound interest rule.* Never duplicate work by solving the same instance of a problem in separate recursive calls.

Each recursive call makes a new copy of that method (actually only the variables) in memory.
Once a method ends (that is, returns some data), the copy of that returning method is removed from memory.
The recursive solutions look simple but visualization and tracing takes time.

写递归代码的关键是，只要遇到递归，我们就把它抽象成一个递推公式，不用想一层层的调用关系，不要试图用人脑去分解递归的每个步骤

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


## Tail Call

尾部递归是指递归函数在调用自身后直接传回其值，而不对其再加运算，效率将会极大的提高。
如果一个函数中所有递归形式的调用都出现在函数的末尾，我们称这个递归函数是尾递归的。当递归调用是整个函数体中最后执行的语句且它的返回值不属于表达式的一部分时，这个递归调用就是尾递归。尾递归函数的特点是在回归过程中不用做任何操作，这个特性很重要，因为大多数现代的编译器会利用这种特点自动生成优化的代码。— 来自百度百科。
尾递归函数，部分高级语言编译器会进行优化，减少不必要的堆栈生成，使得程序栈维持固定的层数，不会出现栈溢出的情况



## Example Algorithms of Recursion

* Fibonacci Series, Factorial Finding
* Merge Sort, Quick Sort
* Binary Search
* Tree Traversals and many Tree Problems: InOrder, PreOrder PostOrder
* Graph Traversals: DFS [Depth First Search] and BFS [Breadth First Search]
* [Dynamic Programming Examples](/docs/CS/Algorithms/DP/DP.md)
* Divide and Conquer Algorithms
* Towers of Hanoi
* [Backtracking Algorithms](/docs/CS/Algorithms/Backtracking.md)

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

## References
