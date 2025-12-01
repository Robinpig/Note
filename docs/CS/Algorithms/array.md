## Introduction

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


动态数组支持自动扩容 通常不实现自动缩容





## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
