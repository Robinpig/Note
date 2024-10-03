## Introduction

A randomized algorithm is an algorithm that employs a degree of randomness as part of its logic or procedure. 
The algorithm typically uses uniformly random "Uniform distribution (discrete)") bits as an auxiliary input to guide its behavior,
in the hope of achieving good performance in the "average case" over all possible choices of random determined by the random bits;
thus either the running time, or the output (or both) are random variables.

There is a distinction between algorithms that use the random input so that they always terminate with the correct answer, 
but where the expected running time is finite (Las Vegas algorithms, for example Quicksort), and algorithms which have a chance of producing an incorrect result 
(Monte Carlo algorithms, for example the Monte Carlo algorithm for the MFAS problem) or fail to produce a result either by signaling a failure or failing to terminate. 
In some cases, probabilistic algorithms are the only practical means of solving a problem.

In common practice, randomized algorithms are approximated using a pseudorandom number generator in place of a true source of random bits;
such an implementation may deviate from the expected theoretical behavior and mathematical guarantees which may depend on the existence of an ideal true random number generator.


## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
