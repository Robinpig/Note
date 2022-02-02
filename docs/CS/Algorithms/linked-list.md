## Introduction


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


