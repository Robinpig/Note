## Introduction


Almost all the algorithms we have studied thus far have been *polynomial-time algorithms*: on inputs of size n, their worst-case running time is $O(n^k)$ for some constant k.
You might wonder whether all problems can be solved in polynomial time. The answer is no.
For example, there are problems, such as Turing’s famous “Halting Problem,” that cannot be solved by any computer, no matter how long you’re willing to wait for an answer.
There are also problems that can be solved, but not in O(nk) time for any constant k.
Generally, we think of problems that are solvable by polynomial-time algorithms as being tractable, or “easy,” and problems that require superpolynomial time as being intractable, or "hard".



The implication of this "rating scheme" is that problems _having polynomial-time-bounded algorithms are tractable. 
But bear in mind that although an exponential function such as 2" grows faster than any polynomial function of 11, for small values of n an $0(2")$-time-bounded algorithm can be more efficient than many polynomial-time-bounded algorithms.
For example. 2" itself does not overtaken'° until /1 reaches 59. 
Nevertheless, the growth rate of an exponential function is so explosive that we say a problem is intractable if all algorithms to solve that problem are of at least exponential time complexity.


A certain class of problems, the class cf nondeterministic polynomial-time complete ("NP-complete" for short) problems, is quite likely to contain only intractable problems. 
This class of problems includes many "classical" problems in combinatorics, such as the traveling salesman problem, the Hamilton circuit problem, and integer linear programming, and all problems in the class can be shown "equivalent,"in the sense that if one problem is tractable, then all are. 
Since many of these problems have been studied by mathematicians and computer scientists for decades, and no polynomial-time-bounded algorithm has been found for even one of them, 
it is natural to conjecture that no such polynomial algorithms exist, and consequently, to regard all the problems in this class as being intractable.

A second class of problems, called the "polynomialspace complete" problems, which are at least as hard as the NP-complete
problems, yet still not provably intractable.


The key notion behind the theory of NP-complete problems is the nondeterministic Turing machine.






## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
