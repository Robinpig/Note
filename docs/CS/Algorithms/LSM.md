## Introduction

The Log-Structured Merge-tree (LSM-tree) is a disk-based data structure designed to provide low-cost indexing for a file experiencing a high rate of record inserts (and deletes) over an extended period.
The LSM-tree uses an algorithm that defers and batches index changes, cascading the changes from a memory-based component through one or more disk components in an efficient manner reminiscent of merge sort.
During this process all index values are continuously accessible to retrievals (aside from very short locking periods), either through the memory component or one of the disk components.
The algorithm has greatly reduced disk arm movements compared to a traditional access methods such as B-trees, and will improve costperformance in domains where disk arm costs for inserts with traditional access methods overwhelm storage media costs.
The LSM-tree approach also generalizes to operations other than insert and delete. However, indexed finds requiring immediate response will lose I/O efficiency in some cases, so the LSM-tree is most useful in applications where index inserts are more common than finds that retrieve the entries.

The LSM-tree uses an algorithm that defers and batches index changes, migrating the changes out to disk in a particularly efficient way reminiscent of merge sort.

## Components

An LSM-tree is composed of two or more tree-like component data structures.

- A two component LSM-tree has a smaller component which is entirely memory resident, known as the C0 tree (or C0 component),
- and a larger component which is resident on disk, known as the C1 tree (or C1 component).

Although the C1 component is disk resident, frequently referenced page nodes in C1 will remain in memory buffers as usual (buffers not shown), so that popular high level directory nodes of C1 can be counted on to be memory resident.

![LSM Components](./images/LSM-Component.png)

As each new History row is generated, a log record to recover this insert is first written to the sequential log file in the usual way.
The index entry for the History row is then inserted into the memory resident C0 tree, after which it will in time migrate out to the C1 tree on disk; any search for an index entry will look first in C0 and then in C1.
There is a certain amount of latency (delay) before entries in the C0 tree migrate out to the disk resident C1 tree, implying a need for recovery of index entries that don't get out to disk prior to a crash.

Recovery is discussed in Section 4, but for now we simply note that the log records that allow us to recover new inserts of History rows can be treated as logical logs;
during recovery we can reconstruct the History rows that have been inserted and simultaneously recreate any needed entries to index these rows to recapture the lost content of C0.

The C1 tree has a comparable directory structure to a B-tree, but is optimized for sequential disk access, with nodes 100% full,
and sequences of single-page nodes on each level below the root packed together in contiguous multi-page disk blocks for efficient arm use; this optimization was also used in the SB-tree.
Multi-page block I/O is used during the rolling merge and for long range retrievals, while single-page nodes are used for matching indexed finds to minimize buffering requirements.

The rolling merge acts in a series of merge steps. A read of a multi-page block containing leaf nodes of the C1 tree makes a range of entries in C1 buffer resident.
Each merge step then reads a disk page sized leaf node of the C1 tree buffered in this block, merges entries from the leaf node with entries taken from the leaf level of the C0 tree,
thus decreasing the size of C0, and creates a newly merged leaf node of the C1 tree.

The buffered multi-page block containing old C1 tree nodes prior to merge is called the emptying block, and new leaf nodes are written to a different buffered multi-page block called the filling block.
When this filling block has been packed full with newly merged leaf nodes of C1, the block is written to a new free area on disk.
The new multi-page block containing merged results is pictured in below figure as lying on the right of the former nodes.
Subsequent merge steps bring together increasing index value segments of the C0 and C1 components until the maximum values are reached and the rolling merge starts again from the smallest values.

![Rolling merge steps](./images/LSM-Rolling.png)

Newly merged blocks are written to new disk positions, so that the old blocks will not be overwritten and will be available for recovery in case of a crash.
The parent directory nodes in C1, also buffered in memory, are updated to reflect this new leaf structure, but usually remain in buffer for longer periods to minimize I/O;
the old leaf nodes from the C1 component are invalidated after the merge step is complete and are then deleted from the C1 directory.
In general, there will be leftover leaf-level entries for the merged C1 component following each merge step, since a merge step is unlikely to result in a new node just as the old leaf node empties.
The same consideration holds for multi-page blocks, since in general when the filling block has filled with newly merged nodes, there will be numerous nodes containing entries still in the shrinking block.
These leftover entries, as well as updated directory node information, remain in block memory buffers for a time without being written to disk.
To reduce reconstruction time in recovery, checkpoints of the merge process are taken periodically, forcing all buffered information to disk.

Unlike the C1 tree, the C0 tree is not expected to have a B-tree-like structure.
For one thing, the nodes could be any size: there is no need to insist on disk page size nodes since the C0 tree never sits on disk, and so we need not sacrifice CPU efficiency to minimize depth.
Thus a (2-3) tree or AVL-tree are possible alternative structures for a C0 tree.
When the growing C0 tree first reaches its threshold size, a leftmost sequence of entries is deleted from the C0 tree (this should be done in an efficient batch manner rather than one entry at a time) and reorganized into a C1 tree leaf node packed 100% full.
Successive leaf nodes are placed left-to-right in the initial pages of a buffer resident multi-page block until the block is full; then this block is written out to disk to become the first part of the C1 tree disk-resident leaf level.
A directory node structure for the C1 tree is created in memory buffers as successive leaf nodes are added.

Successive multi-page blocks of the C1 tree leaf level in ever increasing key-sequence order are written out to disk to keep the C0 tree threshold size from exceeding its threshold.
Upper level C1 tree directory nodes are maintained in separate multi-page block buffers, or else in single page buffers, whichever makes more sense from a standpoint of total memory and disk arm cost;
entries in these directory nodes contain separators that channel access to individual single-page nodes below, as in a B-tree.
The intention is to provide efficient exact-match access along a path of single page index nodes down to the leaf level, avoiding multi-page block reads in such a case to minimize memory buffer requirements.
Thus we read and write multipage blocks for the rolling merge or for long range retrievals, and single-page nodes for indexed find (exact-match) access.
Partially full multi-page blocks of C1 directory nodes are usually allowed to remain in buffer while a sequence of leaf node blocks are written out.
C1 directory nodes are forced to new positions on disk when:

- A multi-page block buffer containing directory nodes becomes full
- The root node splits, increasing the depth of the C1 tree (to a depth greater than two)
- A checkpoint is performed

In the first case, the single multi-page block which has filled is written out to disk.
In the latter two cases, all multi-page block buffers and directory node buffers are flushed to disk.

After the rightmost leaf entry of the C0 tree is written out to the C1 tree for the first time, the process starts over on the left end of the two trees,
except that now and with successive passes multi-page leaf-level blocks of the C1 tree must be read into buffer and merged with the entries in the C0 tree,
thus creating new multi-page leaf blocks of C1 to be written to disk.

Once the merge starts, the situation is more complex. We picture the rolling merge process in a
two component LSM-tree as having a conceptual cursor which slowly circulates in quantized
steps through equal key values of the C0 tree and C1 tree components, drawing indexing data out
from the C0 tree to the C1 tree on disk. The rolling merge cursor has a position at the leaf level
of the C1 tree and within each higher directory level as well. At each level, all currently
merging multi-page blocks of the C1 tree will in general be split into two blocks: the "emptying" block whose entries have been depleted but which retains information not yet reached by
the merge cursor, and the "filling" block which reflects the result of the merge up to this
moment. There will be an analogous "filling node" and "emptying node" defining the cursor
which will certainly be buffer resident. For concurrent access purposes, both the emptying block and the filling block on each level contain an integral number of page-sized nodes of the C1
tree, which simply happen to be buffer resident. (During the merge step that restructures
individual nodes, other types of concurrent access to the entries on those nodes are blocked.)
Whenever a complete flush of all buffered nodes to disk is required, all buffered information at
each level must be written to new positions on disk (with positions reflected in superior directory information, and a sequential log entry for recovery purposes). At a later point, when
the filling block in buffer on some level of the C1 tree fills and must be flushed again, it goes to
a new position. Old information that might still be needed during recovery is never overwritten
on disk, only invalidated as new writes succeed with more up-to-date information.

### Multi-Component

In general, an LSM-tree of K+1 components has components $C_0$, $C_1$, $C_2$, . . ., $C_{K-1}$ and $C_K$, which are indexed tree structures of increasing size;
the C0 component tree is memory resident and all other components are disk resident (but with popular pages buffered in memory as with any disk resident access tree).
Under pressure from inserts, there are asynchronous rolling merge processes in train between all component pairs (Ci-1, Ci), that move entries out from the smaller to the larger component each time the smaller component, Ci-1, exceeds its threshold size.
During the life of a long-lived entry inserted in an LSM-tree, it starts in the C0 tree and eventually migrates out to the CK, through a series of K asynchronous rolling merge steps.

![Multi-Component](./images/LSM-Multi-Component.png)

## Concurrency

In general, we are given an LSM-tree of K+1 components, C0, C1, C2, . . ., CK-1 and CK, of increasing size, where the C0 component tree is memory resident and all other components are disk resident.
There are asynchronous rolling merge processes in train between all component pairs (Ci-1, Ci) that move entries out from the smaller to the larger component each time the smaller component, Ci-1, exceeds its threshold size.
Each disk resident component is constructed of page-sized nodes in a B-tree type structure, except that multiple nodes in key sequence order at all levels below the root sit on multi-page blocks.
Directory information in upper levels of the tree channels access down through single page nodes and also indicates which sequence of nodes sits on a multi-page block, so that a read or write of such a block can be performed all at once.
Under most circumstances, each multi-page block is packed full with single page nodes, but as we will see there are a few situations where a smaller number of nodes exist in such a block.
In that case, the active nodes of the LSM-tree will fall on a contiguous set of pages of the multi-page block, though not necessarily the initial pages of the block.
Apart from the fact that such contiguous pages are not necessarily the initial pages on the multi-page block, the structure of an LSM-tree component is identical to the structure of the SB-tree presented in, to which the reader is referred for supporting details.

A node of a disk-based component Ci can be individually resident in a single page memory buffer, as when equal match finds are performed, or it can be memory resident within its containing multi-page block.
A multi-page block will be buffered in memory as a result of a long range find or else because the rolling merge cursor is passing through the block in question at a high rate.
In any event, all non-locked nodes of the Ci component are accessible to directory lookup at all times, and disk access will perform lookaside to locate any node in memory, even if it is resident as part of a multi-page block taking part in the rolling merge.
Given these considerations, a concurrency approach for the LSM-tree must mediate three distinct types of physical conflict.

1. A find operation should not access a node of a disk-based component at the same time that a different process performing a rolling merge is modifying the contents of the node.
2. A find or insert into the C0 component should not access the same part of the tree that a different process is simultaneously altering to perform a rolling merge out to C1.
3. The cursor for the rolling merge from Ci-1 out to Ci will sometimes need to move past the cursor for the rolling merge from Ci out to Ci+1,
   since the rate of migration out from the component Ci-1 is always at least as great as the rate of migration out from Ci and this implies a faster rate of circulation of the cursor attached to the smaller component Ci-1.
   Whatever concurrency method is adopted must permit this passage to take place without one process (migration out to Ci) being blocked behind the other at the point of intersection (migration out from Ci).

Nodes are the unit of locking used in the LSM-tree to avoid physical conflict during concurrent access to disk based components.
Nodes being updated because of rolling merge are locked in write mode and nodes being read during a find are locked in read mode; methods of directory locking to avoid deadlocks are well understood.
The locking approach taken in C0 is dependent on the data structure used.
In the case of a (2-3)-tree, for example, we could write lock a subtree falling below a single (2-3)-directory node that contains all entries in the range affected during a merge to a node of C1; simultaneously,
find operations would lock all (2-3)-nodes on their access path in read mode so that one type of access will exclude another.
Note that we are only considering concurrency at the lowest physical level of multi-level locking.
We leave to others the question of more abstract locks, such as key range locking to preserve transactional isolation, and avoid for now the problem of phantom updates.
Thus read-locks are released as soon as the entries being sought at the leaf level have been scanned.
Write locks for (all) nodes under the cursor are released following each node merged from the larger component.
This gives an opportunity for a long range find or for a faster cursor to pass a relatively slower cursor position, and thus addresses point (iii) above..

## Recovery

As new entries are inserted into the C0 component of the LSM-tree, and the rolling merge processes migrates entry information out to successively larger components, this work takes place in memory buffered multi-page blocks.
As with any such memory buffered changes, the work is not resistant to system failure until it has been written to disk.
We are faced with a classical recovery problem: to reconstruct work that has taken place in memory after a crash occurs and memory is lost.
We don't need to create special logs to recover index entries on newly created records: transactional insert logs for these new records are written out to a sequential log file in the normal course of events,
and it is a simple matter to treat these insert logs (which normally contain all field values together with the RID where the inserted record has been placed) as a logical base for reconstructing the index entries.
This new approach to recover an index must be built into the system recovery algorithm, and may have the effect of extending the time before storage reclamation for such transactional History insert logs can take place, but this is a minor consideration.

To demonstrate recovery of the LSM-tree index, it is important that we carefully define the form of a checkpoint and demonstrate that we know where to start in the sequential log file,
and how to apply successive logs, so as to deterministically replicate updates to the index that need to be recovered.
The scheme we use is as follows.
When a checkpoint is requested at time T0, we complete all merge steps in operation so that node locks are released, then postpone all new entry inserts to the LSM-tree until the checkpoint completes;
at this point we create an LSMtree checkpoint with the following actions.

- We write the contents of component C0 to a known disk location; following this, entry inserts to C0 can begin again, but merge steps continue to be deferred.
- We flush to disk all dirty memory buffered nodes of disk based components.
- We create a special checkpoint log with the following information:
  - The Log Sequence Number, LSN0, of the last inserted indexed row at time T0
  - The disk addresses of the roots of all components
  - The location of all merge cursors in the various components
  - The current information for dynamic allocation of new multi-page blocks.

Once this checkpoint information has been placed on disk, we can resume regular operations of the LSM-tree.
In the event of a crash and subsequent restart, this checkpoint can be located and the saved component C0 loaded back into memory, together with the buffered blocks of other components needed to continue rolling merges. 
Then logs starting with the first LSN after LSN0 are read into memory and have their associated index entries entered into the LSM-tree. 
As of the time of the checkpoint, the positions of all disk-based components containing all indexing information were recorded in component directories starting at the roots, whose locations are known from the checkpoint log. 
None of this information has been wiped out by later writes of multi-page disk blocks since these writes are always to new locations on disk until subsequent checkpoints make outmoded multi-page blocks unnecessary. 
As we recover logs of inserts for indexed rows, we place new entries into the C0 component; now the rolling merge starts again, overwriting any multi-page blocks written since the checkpoint, 
but recovering all new index entries, until the most recently inserted row has been indexed and recovery is complete.





## References

1. [The Log-Structured Merge-Tree (LSM-Tree)](https://www.cs.umb.edu/~poneil/lsmtree.pdf)
2. [KernelMaker: Paper笔记 The Log structured Merge-Tree](https://kernelmaker.github.io/lsm-tree)
