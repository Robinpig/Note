## Introduction

HyperLogLog is an algorithm for the count-distinct problem, approximating the number of distinct elements in a multiset.
Calculating the exact cardinality of the distinct elements of a multiset requires an amount of memory proportional to the cardinality, which is impractical for very large data sets.
Probabilistic cardinality estimators, such as the HyperLogLog algorithm, use significantly less memory than this, but can only approximate the cardinality.

The basis of the HyperLogLog algorithm is the observation that the cardinality of a multiset of uniformly distributed random numbers can be estimated by calculating the maximum number of leading zeros in the binary representation of each number in the set.
If the maximum number of leading zeros observed is n, an estimate for the number of distinct elements in the set is 2n.

In the HyperLogLog algorithm, a hash function is applied to each element in the original multiset to obtain a multiset of uniformly distributed random numbers with the same cardinality as the original multiset.
The cardinality of this randomly distributed set can then be estimated using the algorithm above.

The simple estimate of cardinality obtained using the algorithm above has the disadvantage of a large variance.
In the HyperLogLog algorithm, the variance is minimised by splitting the multiset into numerous subsets,
calculating the maximum number of leading zeros in the numbers in each of these subsets, and using a harmonic mean to combine these estimates for each subset into an estimate of the cardinality of the whole set.

The HyperLogLog has three main operations: add to add a new element to the set, count to obtain the cardinality of the set and merge to obtain the union of two sets.
Some derived operations can be computed using the inclusion–exclusion principle like the cardinality of the intersection or the cardinality of the difference between two HyperLogLogs combining the merge and count operations.

The data of the HyperLogLog is stored in an array M of m counters (or "registers") that are initialized to 0. Array M initialized from a multiset S is called HyperLogLog sketch of S.

## Complexity

To analyze the complexity, the data streaming ${\displaystyle (\epsilon ,\delta )}$ model is used, which analyzes the space necessary to get a ${\displaystyle 1\pm \epsilon }$ approximation with a fixed success probability ${\displaystyle 1-\delta }$. The relative error of HLL is ${\displaystyle 1.04/{\sqrt {m}}}$ and it needs ${\displaystyle O(\epsilon ^{-2}\log \log n+\log n)}$ space, where n is the set cardinality and m is the number of registers (usually less than one byte size).

The add operation depends on the size of the output of the hash function. As this size is fixed, we can consider the running time for the add operation to be ${\displaystyle O(1)}$.

The count and merge operations depend on the number of registers m and have a theoretical cost of ${\displaystyle O(m)}$.
In some implementations ([Redis](/docs/CS/DB/Redis/HyperLogLog.md)) the number of registers is fixed and the cost is considered to be ${\displaystyle O(1)}$ in the documentation.

## Links

