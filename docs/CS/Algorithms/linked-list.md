## Introduction

An array implementation allows print_list and find to be carried out in linear time, which is as good as can be expected, and the find_kth operation takes constant time.

However, insertion and deletion are expensive.

In order to avoid the linear cost of insertion and deletion, we need to ensure that the list is not stored contiguously, 
since otherwise entire parts of the list will need to be moved.

The linked list consists of a series of structures, which are not necessarily adjacent in memory. 
Each structure contains the element and a pointer to a structure containing its successor. We call this the next pointer. 
The last cell's next pointer points to ; this value is defined by C and cannot be confused with another pointer. 
ANSI C specifies that is zero.

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


