## Introduction

Obviously all of these instructions can be implemented just by using an array.
Even if the array is dynamically allocated, an estimate of the maximum size of the list is required.
Usually this requires a high over-estimate, which wastes considerable space.
This could be a serious limitation, especially if there are many lists of unknown size.

In order to avoid the linear cost of insertion and deletion, we need to ensure that the list is not stored contiguously, since otherwise entire parts of the list will need to be moved.

The linked list consists of a series of structures, which are not necessarily adjacent in memory.
Each structure contains the element and a pointer to a structure containing its successor.

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [stack](/docs/CS/Algorithms/struct/stack.md)
- [queue](/docs/CS/Algorithms/struct/queue.md)
