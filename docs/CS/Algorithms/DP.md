## Introduction

Dynamic programming, like the divide-and-conquer method, solves problems by combining the solutions to subproblems. 
(“Programming” in this context refers to a tabular method, not to writing computer code.)

Divide-and-conquer algorithms partition the problem into disjoint subproblems, solve the subproblems recursively, and then combine their solutions to solve the original problem. 
In contrast, dynamic programming applies when the subproblems overlap—that is, when subproblems share subsubproblems.
In this context, a divide-and-conquer algorithm does more work than necessary, repeatedly solving the common subsubproblems. 
A dynamic-programming algorithm solves each subsubproblem just once and then saves its answer in a table, thereby avoiding the work of recomputing the answer every time it solves each subsubproblem.

We typically apply dynamic programming to **optimization problems**. Such problems can have many possible solutions. 
Each solution has a value, and we wish to find a solution with the optimal (minimum or maximum) value. 
We call such a solution an optimal solution to the problem, as opposed to the optimal solution, since there may be several solutions that achieve the optimal value.

When developing a dynamic-programming algorithm, we follow a sequence of four steps:
1. Characterize the structure of an optimal solution.
2. Recursively define the value of an optimal solution.
3. Compute the value of an optimal solution, typically in a bottom-up fashion.
4. Construct an optimal solution from computed information.

Steps 1–3 form the basis of a dynamic-programming solution to a problem. 
If we need only the value of an optimal solution, and not the solution itself, then we can omit step 4. 
When we do perform step 4, we sometimes maintain additional information during step 3 so that we can easily construct an optimal solution.

The dynamic-programming method works as follows.
Having observed that a naive recursive solution is inefficient because it solves the same subproblems repeatedly, 
we arrange for each subproblem to be solved only once, saving its solution. 
If we need to refer to this subproblem’s solution again later, we can just look it up, rather than recompute it. 
Dynamic programming thus uses additional memory to save computation time; it serves an example of a **time-memory trade-off**. 
The savings may be dramatic: an exponential-time solution may be transformed into a polynomial-time solution. 
A dynamic-programming approach runs in polynomial time when the number of distinct subproblems involved is polynomial in the input size and we can solve each such subproblem in polynomial time。

There are usually two equivalent ways to implement a dynamic-programming approach. 

The first approach is **top-down with memoization**.
In this approach, we write the procedure recursively in a natural manner, but modified to save the result of each subproblem (usually in an array or hash table). 
The procedure now first checks to see whether it has previously solved this subproblem. 
If so, it returns the saved value, saving further computation at this level; if not, the procedure computes the value in the usual manner. 
We say that the recursive procedure has been memoized; it “remembers” what results it has computed previously.

The second approach is the **bottom-up method**. 
This approach typically depends on some natural notion of the “size” of a subproblem, such that solving any particular subproblem depends only on solving “smaller” subproblems. 
We sort the subproblems by size and solve them in size order, smallest first. 
When solving a particular subproblem, we have already solved all of the smaller subproblems its solution depends upon, and we have saved their solutions. 
We solve each subproblem only once, and when we first see it, we have already solved all of its prerequisite subproblems.

These two approaches yield algorithms with the same asymptotic running time,
except in unusual circumstances where the top-down approach does not actually recurse to examine all possible subproblems. 
The bottom-up approach often has much better constant factors, since it has less overhead for procedure calls.


### Subproblem graphs
When we think about a dynamic-programming problem, we should understand the set of subproblems involved and how subproblems depend on one another.

The subproblem graph for the problem embodies exactly this information.
The bottom-up method for dynamic programming considers the vertices of the subproblem graph in such an order that 
we solve the subproblems y adjacent to a given subproblem x before we solve subproblem x. (The adjacency relation is not necessarily symmetric.) 
In a bottom-up dynamic-programming algorithm, we consider the vertices of the subproblem graph in an order that is a “reverse topological sort”, 
or a “topological sort of the transpose” of the subproblem graph. 
In other words, no subproblem is considered until all of the subproblems it depends upon have been solved. 
Similarly, using notions from the same chapter, we can view the top-down method (with memoization) for dynamic programming as a “depth-first search” of the subproblem graph.

## Elements of dynamic programming 
We examine the two key ingredients that an optimization problem must have in order for dynamic programming to apply: optimal substructure and overlapping subproblems. 
We also revisit and discuss more fully how memoization might help us take advantage of the overlapping-subproblems property in a top-down recursive approach.

### Optimal substructure
The first step in solving an optimization problem by dynamic programming is to characterize the structure of an optimal solution. 
A problem exhibits optimal substructure if an optimal solution to the problem contains within it optimal solutions to subproblems. 
Whenever a problem exhibits optimal substructure, we have a good clue that dynamic programming might apply. 
In dynamic programming, we build an optimal solution to the problem from optimal solutions to subproblems. 
Consequently, we must take care to ensure that the range of subproblems we consider includes those used in an optimal solution

Dynamic programming often uses optimal substructure in a bottom-up fashion.
That is, we first find optimal solutions to subproblems and, having solved the subproblems, we find an optimal solution to the problem. 
Finding an optimal solution to the problem entails making a choice among subproblems as to which we will use in solving the problem. 
The cost of the problem solution is usually the subproblem costs plus a cost that is directly attributable to the choice itself.

In particular, problems to which [greedy algorithms](/docs/CS/Algorithms/Greedy.md) apply have optimal substructure. 
One major difference between greedy algorithms and dynamic programming is that instead of first finding optimal solutions to subproblems and then making an informed choice, 
greedy algorithms first make a “greedy” choice—the choice that looks best at the time—and then solve a resulting subproblem, without bothering to solve all possible related smaller subproblems.

### Overlapping subproblems
The second ingredient that an optimization problem must have for dynamic programming to apply is that the space of subproblems must be “small” in the sense
that a recursive algorithm for the problem solves the same subproblems over and over, rather than always generating new subproblems. 
Typically, the total number of distinct subproblems is a polynomial in the input size. 
When a recursive algorithm revisits the same problem repeatedly, we say that the optimization problem has overlapping subproblems. 
In contrast, a problem for which a divide-andconquer approach is suitable usually generates brand-new problems at each step of the recursion. 
Dynamic-programming algorithms typically take advantage of overlapping subproblems by solving each subproblem once and then 
storing the solution in a table where it can be looked up when needed, using constant time per lookup.


