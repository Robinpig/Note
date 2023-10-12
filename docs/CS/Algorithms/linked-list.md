## Introduction

An array implementation allows print_list and find to be carried out in linear time, which is as good as can be expected, and the find_kth operation takes constant time.
However, insertion and deletion are expensive.

In order to avoid the linear cost of insertion and deletion, we need to ensure that the list is not stored contiguously,
since otherwise entire parts of the list will need to be moved.

The linked list consists of a series of structures, which are not necessarily adjacent in memory.
Each structure contains the element and a pointer to a structure containing its successor. We call this the next pointer.
The last cell's next pointer points to ; this value is defined by C and cannot be confused with another pointer.
ANSI C specifies that is zero.

## Arrays Overview

One memory block is allocated for the entire array to hold elements of the array.
The array elements can be accessed in constant time by using the index of the particular element as the subscript.

To access an array element, the address of an element is computed as an offset from the base address of the array and one multiplication
is needed to compute what is supposed to be added to the base address to get the memory address of the element.
First, the size of an element of that data type is calculated and then it is multiplied with the index of the element to get the value to be added to the base address.
This process takes one multiplication and one addition.
Since these two operations take constant time, we can say the array access can be performed in constant time.

**Advantages of Arrays**

- Simple and easy to use
- Faster access to the elements (constant access)

**Disadvantages of Arrays**

- Preallocates all needed memory up front and wastes memory space for indices in the array that are empty.
- Fixed size: The size of the array is static (specify the array size before using it).
- One block allocation: To allocate the array itself at the beginning, sometimes it may not be possible to get the memory for the complete array (if the array size is big).
- Complex position-based insertion: To insert an element at a given position, we may need to shift the existing elements.
  This will create a position for us to insert the new element at the desired position.
  If the position at which we want to add an element is at the beginning, then the shifting operation is more expensive.

### Dynamic Arrays

Dynamic array (also called growable array, resizable array, dynamic table, or array list) is a random access, variable-size list data structure that allows elements to be added or removed.
One simple way of implementing dynamic arrays is to initially start with some fixed size array.
As soon as that array becomes full, create the new array double the size of the original array.
Similarly, reduce the array size to half if the elements in the array are less than half the size.

Note: We will see the implementation for dynamic arrays in the Stacks, Queues and Hashing chapters.

## Linked Lists Overview

A linked list is a data structure used for storing collections of data A linked list has the following properties.

- Successive elements are connected by pointers
- The last element points to NULL
- Can grow or shrink in size during execution of a program
- Can be made just as long as required (until systems memory exhausts)
- Does not waste memory space (but takes some extra memory for pointers). It allocates memory as list grows.

### Linked Lists ADT

The following operations make linked lists an ADT:

**Main Linked Lists Operations**

- Insert: inserts an element into the list
- Delete: removes and returns the specified position element from the list

**Auxiliary Linked Lists Operations**

- Delete List: removes all elements of the list (dispose of the list)
- Count: returns the number of elements in the list
- Find nth node from the end of the list

**Advantages of Linked Lists**

Linked lists have both advantages and disadvantages. The advantage of linked lists is that they can be expanded in constant time.
To create an array, we must allocate memory for a certain number of elements.
To add more elements to the array when full, we must create a new array and copy the old array into the new array. This can take a lot of time.

We can prevent this by allocating lots of space initially but then we might allocate more than we need and waste memory.
With a linked list, we can start with space for just one allocated element and add on new elements easily without the need to do any copying and reallocating.

**Issues with Linked Lists (Disadvantages)**

There are a number of issues with linked lists. The main disadvantage of linked lists is access time to individual elements.
Array is random-access, which means it takes O(1) to access any element in the array.
Linked lists take O(n) for access to an element in the list in the worst case.
Another advantage of arrays in access time is spacial locality in memory.
Arrays are defined as contiguous blocks of memory, and so any array element will be physically near its neighbors.
This greatly benefits from modern CPU caching methods.

Although the dynamic allocation of storage is a great advantage, the overhead with storing and retrieving data can make a big difference.
Sometimes linked lists are hard to manipulate. If the last item is deleted, the last but one must then have its pointer changed to hold a NULL reference.
This requires that the list is traversed to find the last but one link, and its pointer set to a NULL reference.
Finally, linked lists waste memory in terms of extra reference points.

## Comparison of Linked Lists with Arrays

<p style="text-align: center;">
Tab.1 Comparison of Linked Lists with Arrays
</p>

<div style="text-align: center;">

| Parameter                       | Linked List          | Array                                                   | Dynamic Array                                             |
| ------------------------------- | -------------------- | ------------------------------------------------------- | --------------------------------------------------------- |
| Indexing                        | $O(n)$               | $O(1)$                                                  | $O(1)$                                                    |
| Inserting/deletion at beginning | $O(1)$               | $O(n)$, if array is not full(for shifting the elements) | $O(n)$                                                    |
| Insertion at ending             | $O(n)$               | $O(1)$, if array is not full                            | $O(1)$, if array is not full<br/>$O(n)$, if array is full |
| Deletion at ending              | $O(n)$               | $O(1)$                                                  | $O(n)$                                                    |
| Insertion in middle             | $O(n)$               | $O(n)$, if array is not full(for shifting the elements) | $O(n)$                                                    |
| Deletion in middle              | $O(n)$               | $O(n)$, if array is not full(for shifting the elements) | $O(n)$                                                    |
| Wasted space                    | $O(n)$(for pointers) | 0                                                       | $O(n)$                                                    |

</div>

## Singly Linked Lists

Generally “linked list” means a singly linked list.
This list consists of a number of nodes in which each node has a next pointer to the following element.
The link of the last node in the list is NULL, which indicates the end of the list.

## Doubly Linked Lists

Sometimes it is convenient to traverse lists backwards. The standard implementation does not help here, but the solution is simple.
Merely add an extra field to the data structure, containing a pointer to the previous cell.
The cost of this is an extra link, which adds to the space requirement and also doubles the cost of insertions and deletions because there are more pointers to fix.
On the other hand, it simplifies deletion, because you no longer have to refer to a key by using a pointer to the previous cell; this information is now at hand.

## Circularly Linked Lists

A popular convention is to have the last cell keep a pointer back to the first.
This can be done with or without a header (if the header is present, the last cell points to it), and can also be done with doubly linked lists (the first cell's previous pointer points to the last cell).
This clearly affects some of the tests, but the structure is popular in some applications.

For large amounts of input, the linear access time of linked lists is prohibitive.

## Skip Lists

Binary trees can be used for representing abstract data types such as dictionaries and ordered lists.
They work well when the elements are inserted in a random order.
Some sequences of operations, such as inserting the elements in order, produce degenerate data structures that give very poor performance.
If it were possible to randomly permute the list of items to be inserted, trees would work well with high probability for any input sequence.
In most cases queries must be answered on-line, so randomly permuting the input is impractical.
Balanced tree algorithms rearrange the tree as operations are performed to maintain certain balance conditions and assure good performance.

Skip lists are a probabilistic alternative to balanced trees.
Skip list is a data structure that can be used as an alternative to [balanced binary trees](/docs/CS/Algorithms/tree.md).
As compared to a binary tree, skip lists allow quick search, insertion and deletion of elements.
This is achieved by using probabilistic balancing rather than strictly enforce balancing.
It is basically a linked list with additional pointers such that intermediate nodes can be skipped.
It uses a random number generator to make some decisions.

In an ordinary sorted linked list, search, insert, and delete are in $O(n)$ because the list must be scanned node-by-node from the head to find the relevant node.
If somehow we could scan down the list in bigger steps (skip down, as it were), we would reduce the cost of scanning.
This is the fundamental idea behind Skip Lists.

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
-

## References

1. [Skip Lists: A Probabilistic Alternative to Balanced Trees](https://dl.acm.org/doi/pdf/10.1145/78973.78977)
