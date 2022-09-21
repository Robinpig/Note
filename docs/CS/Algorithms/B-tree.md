## Introduction

As B-trees have been around for so long, it’s not surprising that many optimizations have been developed over the years.
To mention just a few:

- Instead of overwriting pages and maintaining a WAL for crash recovery, some databases (like LMDB) use a copy-on-write scheme.
  A modified page is written to a different location, and a new version of the parent pages in the tree is created, pointing at the new location. This approach is also useful for concurrency control.
- We can save space in pages by not storing the entire key, but abbreviating it.
  Especially in pages on the interior of the tree, keys only need to provide enough information to act as boundaries between key ranges.
  Packing more keys into a page allows the tree to have a higher branching factor, and thus fewer levels.
- In general, pages can be positioned anywhere on disk; there is nothing requiring pages with nearby key ranges to be nearby on disk.
  If a query needs to scan over a large part of the key range in sorted order, that page-by-page layout can be inefficient, because a disk seek may be required for every page that is read.
  Many Btree implementations therefore try to lay out the tree so that leaf pages appear in sequential order on disk.
  However, it’s difficult to maintain that order as the tree grows.
  By contrast, since LSM-trees rewrite large segments of the storage in one go during merging, it’s easier for them to keep sequential keys close to each other on disk.
- Additional pointers have been added to the tree.
  For example, each leaf page may have references to its sibling pages to the left and right, which allows scanning keys in order without jumping back to parent pages.
- B-tree variants such as fractal trees borrow some log-structured ideas to reduce disk seeks (and they have nothing to do with fractals).





## Links

- [Trees](/docs/CS/Algorithms/tree.md?id=B-Trees)

## References

1. [Performance of B+ tree concurrency control algorithms](https://minds.wisconsin.edu/bitstream/handle/1793/59428/TR999.pdf)
2. [Concurrency of operations on B-trees]()
3. [Concurrent B-trees with Lock-free Techniques](http://www.cs.umanitoba.ca/~hacamero/Research/BtreeTechrpt2011.pdf)
4. [Efficient Locking for Concurrent Operations on B-Trees](https://www.cs.utexas.edu/users/dsb/cs386d/Readings/ConcurrencyControl/Lehman-Yao.pdf)
