## Introduction



| Sort   | Avg Time | Avg Space | Best Time | Best Space | Bad Time | Bad Space |
| ------ | -------- | --------- | ---- | ---- | ---- | --- |
| Bubble |          |           |      |      |      |     |
| Select |          |           |      |      |      ||
| Insert |          |           |      |      |      ||
| Shell  |          |           |      |      |      ||
| Heap   |          |           |      |      |      ||
| Merge  |          |           |      |      |      ||
| Quick  | nlogn    | logn      | nlogn | logn | n^2 |n|
| Radix  |          |           |      |      |      ||
| Bucket |          |           |      |      |      ||



## Bubble Sort





```java
public static void swap (int[] A, int i, int j) {
	A[i] ^= A[j];
	A[j] ^= A[i];
	A[i] ^= A[j];
}
```


Several algorithms that can sort n numbers in *O(nlgn)* time. 
Merge sort and heapsort achieve this upper bound in the worst case; quicksort achieves it on average.
These algorithms share an interesting property: the sorted order they determine is based only on comparisons between the input elements.
We call such sorting algorithms ***comparison sorts***.

Any comparison sort must make *O(nlgn)*
comparisons in the worst case to sort *n* elements. 
Thus, merge sort and heapsort are asymptotically optimal, and no comparison sort exists that is faster by more than a constant factor.


We examine three sorting algorithms—counting sort, radix sort, and bucket sort—that run in linear time. 
Of course, these algorithms use operations other than comparisons to determine the sorted order. 
Consequently, the *O(nlgn)* lower bound does not apply to them.

## Quick Sort

```cpp
int Pa
```

## Counting Sort


## Radix Sort

## Bucket Sort
