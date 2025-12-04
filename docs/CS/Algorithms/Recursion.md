## Introduction

递归（Recursion），在数学和计算机科学中是指在函数的定义中使用函数自身的方法，在计算机科学中还额外指一种通过重复将问题分解为同类的子问题而解决问题的方法

递归的基本思想是某个函数直接或者间接地调用自身，这样原问题的求解就转换为了许多性质相同但是规模更小的子问题
求解时只需要关注如何把原问题划分成符合条件的子问题，而不需要过分关注这个子问题是如何被解决的
写递归代码的关键是，只要遇到递归，我们就把它抽象成一个递推公式，不用想一层层的调用关系，不要试图用人脑去分解递归的每个步骤

递归代码最重要的两个特征：结束条件和自我调用。自我调用是在解决子问题，而结束条件定义了最简子问题的答案


When writing recursive routines, it is crucial to keep in mind the four basic rules of recursion:

1. *Base cases.* You must always have some base cases, which can be solved without recursion.
2. *Making progress.* For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.
3. *Design rule.* Assume that all the recursive calls work.
4. *Compound interest rule.* Never duplicate work by solving the same instance of a problem in separate recursive calls.


在程序执行中，递归是利用堆栈来实现的。每当进入一个函数调用，栈就会增加一层栈帧，每次函数返回，栈就会减少一层栈帧
而栈不是无限大的，当递归层数过多时，就会造成 栈溢出 的后果


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


## 递归优化

比较初级的递归实现可能递归次数太多，容易超时。这时需要对递归进行优化

分治（Divide and Conquer），字面上的解释是「分而治之」，就是把一个复杂的问题分成两个或更多的相同或相似的子问题，直到最后子问题可以简单的直接求解，原问题的解即子问题的解的合并

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
* [Dynamic Programming Examples](/docs/CS/Algorithms/DP.md)
* Divide and Conquer Algorithms
* Towers of Hanoi
* [Backtracking Algorithms](/docs/CS/Algorithms/Backtracking.md)

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

## References
