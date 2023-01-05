## Introduction

Sorting is the process of rearranging a sequence of objects so as to put them in some logical order.
All computer systems have implementations of sorting algorithms, for use by the system and by users.

The sorting algorithms divide into two basic types:
those that sort in place and use no extra memory except perhaps for a small functioncall stack or a constant number of instance variables,
and those that need enough extra memory to hold another copy of the array to be sorted.

After considering the classic selection sort, insertion sort, shellsort, mergesort, quicksort, and heapsort algorithms, we will consider practical issues and applications.

Suppose you have a group of n numbers and would like to determine the kth largest. This is known as the _selection problem_.

We consider two classes of sorting algorithms. 

The first class of algorithms makes use of the structure of the elements to be sorted.
For example. if the elements to be sorted are integers in a fixed range 0 to m - 1, then we can sort a sequence of /1 elemeQts. in $O(n + m)$ time; 
if the elements to be sorted are strings over a fixed alphabet, then a sequence of strings can be sorted in time linearly proportional to the sum of the lengths of the strings.

The second class of algorithms assumes no structure on the elements to be sorted. The basic operation is a comparison between a pair of elements.
With algorithms of this nature we shall see that at least n log /1 comparisons are needed to sort a sequence of n elements. 
We give two O(nlogn) sorting algorithms-Heapsort. which is Oc(n log n) in the worst case, and Quicksort, which is $O(nlogn)$ in the expected case.

| Sort   | Avg Time | Avg Space | Best Time | Best Space | Bad Time | Bad Space |
| -------- | ---------- | ----------- | ----------- | ------------ | ---------- | ----------- |
| Bubble |          |           |           |            |          |           |
| Select |          |           |           |            |          |           |
| Insert |          |           |           |            |          |           |
| Shell  |          |           |           |            |          |           |
| Heap   |          |           |           |            |          |           |
| Merge  |          |           |           |            |          |           |
| Quick  | nlogn    | logn      | nlogn     | logn       | n^2      | n         |
| Radix  |          |           |           |            |          |           |
| Bucket |          |           |           |            |          |           |

## Selection Sort

One of the simplest sorting algorithms works as follows:

- First, find the smallest item in the array and exchange it with the first entry (itself if the first entry is already the smallest).
- Then, find the next smallest item and exchange it with the second entry.
- Continue in this way until the entire array is sorted.

Selection sort uses ~ $N^2/2$ compares and `N` exchanges to sort an array of length N.

This method is called _selection sort_ because it works by repeatedly selecting the smallest remaining item.

> [!NOTE]
>
> Selection sort is a simple sorting method that is easy to understand and to implement and is characterized by the following two signature properties:
>
> - Running time is insensitive to input.
> - Data movement is minimal.

## Insertion sort

Insertion sort uses `N^2/4` compares and `N^2/4` exchanges to sort a randomly ordered array of length N with distinct keys, on the average.
The worst case is `N^2/2` compares and `N^2/2` exchanges and the best case is N  1 compares and 0 exchanges.

The number of exchanges used by insertion sort is equal to the number of inversions in the array,
and the number of compares is at least equal to the number of inversions and at most equal to the number of inversions plus the array size minus 1.

## Shellsort

Shellsort is sometimes referred to as diminishing increment sort.

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

## Heapsort

## Mergesort

> [!NOTE]
>
> Top-down mergesort uses between ½NlgN and NlgN compares to sort any array of length N.
>
> Top-down mergesort uses at most 6NlgN array accesses to sort an array of length N.

```java
public class Merge {
    private static Comparable[] aux; // auxiliary array for merges

    public static void sort(Comparable[] a) {
        aux = new Comparable[a.length]; // Allocate space just once.
        sort(a, 0, a.length - 1);
    }

    private static void sort(Comparable[] a, int lo, int hi) { // Sort a[lo..hi].
        if (hi <= lo) return;
        int mid = lo + (hi - lo) / 2;
        sort(a, lo, mid); // Sort left half.
        sort(a, mid + 1, hi); // Sort right half.
        merge(a, lo, mid, hi); // Merge results (code on page 271).
    }
}
```

Bottom-up mergesort

> [!NOTE]
>
> Bottom-up mergesort uses between ½NlgN and NlgN compares and at most 6NlgN array accesses to sort an array of length N.

No compare-based sorting algorithm can guarantee to sort N items with fewer than lg(N!) ~ NlgN compares.

## QuickSort

Like Merge Sort, QuickSort is a Divide and Conquer algorithm.
It picks an element as a pivot and partitions the given array around the picked pivot.
There are many different versions of quickSort that pick pivot in different ways.

- Always pick the first element as a pivot.
- Always pick the last element as a pivot (implemented below)
- Pick a random element as a pivot.
- Pick median as the pivot.

The key process in quickSort is a partition(). 
The target of partitions is, given an array and an element x of an array as the pivot, put x at its correct position in a sorted array and put all smaller elements (smaller than x) before x, and put all greater elements (greater than x) after x.
All this should be done in linear time.


Partition Algorithm:
<br>
There can be many ways to do partition, following pseudo-code adopts the method given in the CLRS book. 
The logic is simple, we start from the leftmost element and keep track of the index of smaller (or equal to) elements as i.
While traversing, if we find a smaller element, we swap the current element with arr[i]. 
Otherwise, we ignore the current element.


Pseudo Code for recursive QuickSort function:
```
/* low  –> Starting index,  high  –> Ending index */
quickSort(arr[], low, high) {
    if (low < high) {
        /* pi is partitioning index, arr[pi] is now at right place */
        pi = partition(arr, low, high);
        quickSort(arr, low, pi – 1);  // Before pi
        quickSort(arr, pi + 1, high); // After pi
    }
}
```
Example:
```go
func quickSort(array []int, low int, high int) []int {
	if low < high {
		pi := partition(array, low, high)
		quickSort(array, low, pi-1)
		quickSort(array, pi+1, high)
	}
	return array
}

func partition(array []int, low int, high int) int {
	pivot := array[high]
	start := -1
	for j := low; j < high; j++ {
		if array[j] < pivot {
			start++
			if start != j {
				swap(array, start, j)
			}
		}
	}
	swap(array, start+1, high)
	return start + 1
}

func swap(array []int, i int, j int) []int {
	temp := array[j]
	array[j] = array[i]
	array[i] = temp
	return array
}

func main() {
	array := []int{33, 4, 5, 23, 43, 65, 545}
	quickSort(array, 0, len(array)-1)
	for _, v := range array {
		println(v)
	}
}
```


### Picking the Pivot

A safe course is merely to choose the pivot randomly.

Median-of-Three Partitioning


> [!NOTE]
>
> A common solution is not to use quicksort recursively for small files, but instead use a sorting algorithm that is efficient for small files, such as insertion sort.


### Randomized QuickSort
Choosing the first element of a subarray as the pivot takes only $O(1)$ time but can cause QuickSort to run in $O(n^2)$ time.
Choosing the median element as the pivot guarantees an overall running time of $O(nlogn)$ but is much more time-consuming (if still linear-time). 
Can we have the best of both worlds? Is there a simple and lightweight way to choose a pivot element that leads to a roughly balanced split of the array? The answer is yes, and the key idea is to use randomization.

> For every input array of length n $ 1, the average running time of randomized QuickSort is $O(nlogn)$.

The algorithm doesn’t spend time allocating and managing additional memory (unlike [MergeSort](/docs/CS/Algorithms/Sort.md?id=MergeSort)).

## Counting Sort

## Radix Sort

Radix sort is sometimes known as *card sort*.





## Bucket Sort

## External Sort

Sorts that cannot be performed in main memory and must be done on disk or tape are also quite important. This type of sorting, known as external sorting.

Merging is the central idea of external sorts.

### Multiway Merge



## Others

The Pancake Flipping problem is NP-hard.(see [Pancake Flipping is Hard](https://arxiv.org/pdf/1111.0434v1.pdf))

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)


[AlphaSort: A RISC Machine Sort](https://courses.cs.washington.edu/courses/cse590q/05wi/paper/p233-nyberg.pdf)