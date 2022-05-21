## Introduction

A procedure that calls itself, directly or indirectly, is said to be *recursive*.
The use of recursion often permits more lucid and concise descriptions of algorithms than would be possible without recursion.




These considerations lead to the first two fundamental rules of recursion:
1. Base cases. You must always have some base cases, which can be solved without recursion.
2. Making progress. For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.


When writing recursive routines, it is crucial to keep in mind the four basic rules of recursion:
1. Base cases. You must always have some base cases, which can be solved without recursion.
2. Making progress. For the cases that are to be solved recursively, the recursive call must always be to a case that makes progress toward a base case.
3. Design rule. Assume that all the recursive calls work.
4. Compound interest rule. Never duplicate work by solving the same instance of a problem in separate recursive calls.


## References

1. []