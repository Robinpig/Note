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
For example. if the elements to be sorted are integers in a fixed range 0 to m - 1, then we can sort a sequence of /1 eleme Qts. in $O(n + m)$ time;
if the elements to be sorted are strings over a fixed alphabet, then a sequence of strings can be sorted in time linearly proportional to the sum of the lengths of the strings.

The second class of algorithms assumes no structure on the elements to be sorted. The basic operation is a comparison between a pair of elements.
With algorithms of this nature we shall see that at least n log /1 comparisons are needed to sort a sequence of n elements.
We give two $O(nlogn)$ sorting algorithms-Heapsort. which is $O(nlogn)$ in the worst case, and Quicksort, which is $O(nlogn)$ in the expected case.

## Classification of Sorting Algorithms

Sorting algorithms are generally categorized based on the following parameters.

**By Number of Comparisons**

In this method, sorting algorithms are classified based on the number of comparisons. For comparison based sorting algorithms, best case behavior is O(nlogn) and worst case behavior is $O(n^2)$.
Comparison-based sorting algorithms evaluate the elements of the list by key comparison operation and need at least O(nlogn) comparisons for most inputs.
Later in this chapter we will discuss a few non – comparison (linear) sorting algorithms like Counting sort, Bucket sort, Radix sort, etc. Linear Sorting algorithms impose few restrictions on the inputs to improve the complexity

**By Number of Swaps**

In this method, sorting algorithms are categorized by the number of swaps (also called inversions).

**By Memory Usage**

Some sorting algorithms are “in place” and they need O(1) or O(logn) memory to create auxiliary locations for sorting the data temporarily.

**By Recursion**

Sorting algorithms are either recursive [quick sort] or non-recursive [selection sort, and insertion sort], and there are some algorithms which use both (merge sort).

**By Stability**

Sorting algorithm is stable if for all indices i and j such that the key A[i] equals key A[j], if record R[i] precedes record R[j] in the original file, record R[i] precedes record R[j] in the sorted list. Few sorting algorithms maintain the relative order of elements with equal keys (equivalent elements retain their relative positions even after sorting).

**By Adaptability**

With a few sorting algorithms, the complexity changes based on pre-sortedness [quick sort]: pre- sortedness of the input affects the running time. Algorithms that take this into account are known to be adaptive.

Another method of classifying sorting algorithms is:

- Internal Sort
  Sort algorithms that use main memory exclusively during the sort are called internal sorting algorithms. This kind of algorithm assumes high-speed random access to all memory.
- External Sort
  Sorting algorithms that use external memory, such as tape or disk, during the sort come under this category.


| Sort   | Avg Time   | Avg Space  | Best Time  | Best Space | Bad Time   | Bad Space |
|--------| ---------- | ---------- | ---------- | ---------- |------------|-----------|
| Bubble | $O(n^2)$   | $O(1)$     | $O(n)$     | $O(1)$     | $O(n^2)$   | $O(1)$    |
| Select | $O(n^2)$   | $O(1)$     | $O(n^2)$   | $O(1)$     | $O(n^2)$   | $O(1)$    |
| Insert | $O(n^2)$   | $O(n^2)$   | $O(n)$     | $O(1)$     | $O(n^2)$   | $O(n^2)$  |
| Shell  |   $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Heap   |    $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Merge  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Quick  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n^2)$   | $O(n)$    |
| Radix  |     $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Bucket |       $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Tree   |       $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |

## Bubble Sort

Bubble sort is the simplest sorting algorithm. It works by iterating the input array from the first element to the last, comparing each pair of elements and swapping them if needed.
Bubble sort continues its iterations until no more swaps are needed.
The algorithm gets its name from the way smaller elements “bubble” to the top of the list.
Generally, insertion sort has better performance than bubble sort.
Some researchers suggest that we should not teach bubble sort because of its simplicity and high time complexity.
The only significant advantage that bubble sort has over other implementations is that it can detect whether the input list is already sorted or not.

```java
public static void swap (int[] A, int i, int j) {
	A[i] ^= A[j];
	A[j] ^= A[i];
	A[i] ^= A[j];
}
```

Several algorithms that can sort n numbers in $O(nlogn)$ time.
Merge sort and heapsort achieve this upper bound in the worst case; quicksort achieves it on average.
These algorithms share an interesting property: the sorted order they determine is based only on comparisons between the input elements.
We call such sorting algorithms *comparison sorts*.

Any comparison sort must make $O(nlogn)$ comparisons in the worst case to sort *n* elements.
Thus, merge sort and heapsort are asymptotically optimal, and no comparison sort exists that is faster by more than a constant factor.

We examine three sorting algorithms—counting sort, radix sort, and bucket sort—that run in linear time.
Of course, these algorithms use operations other than comparisons to determine the sorted order.
Consequently, the $O(nlogn)$ lower bound does not apply to them.

## Selection Sort

Selection sort is an in-place sorting algorithm. Selection sort works well for small files.
It is used for sorting the files with very large values and small keys.
This is because selection is made based on keys and swaps are made only when required.
This algorithm is called *selection sort* since it repeatedly selects the smallest element.

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

Insertion sort is a simple and efficient comparison sort.
In this algorithm, each iteration removes an element from the input data and inserts it into the correct position in the list being sorted.
The choice of the element being removed from the input is random and this process is repeated until all input elements have gone through.

Insertion sort uses `N^2/4` compares and `N^2/4` exchanges to sort a randomly ordered array of length N with distinct keys, on the average.
The worst case is `N^2/2` compares and `N^2/2` exchanges and the best case is N  1 compares and 0 exchanges.

The number of exchanges used by insertion sort is equal to the number of inversions in the array,
and the number of compares is at least equal to the number of inversions and at most equal to the number of inversions plus the array size minus 1.

## Shell Sort

Shell sort (also called diminishing increment sort) was invented by Donald Shell.
This sorting algorithm is a generalization of insertion sort. Insertion sort works efficiently on input that is already almost sorted.
Shell sort is also known as n-gap insertion sort.
Instead of comparing only the adjacent pair, shell sort makes several passes and uses various gaps between adjacent elements (ending with the gap of 1 or classical insertion sort).
In insertion sort, comparisons are made between the adjacent elements.
At most 1 inversion is eliminated for each comparison done with insertion sort.
The variation used in shell sort is to avoid comparing adjacent elements until the last step of the algorithm.
So, the last step of shell sort is effectively the insertion sort algorithm.
It improves insertion sort by allowing the comparison and exchange of elements that are far away.
This is the first algorithm which got less than quadratic complexity among comparison sort algorithms.

## Heapsort

Time complexity: As we remove the elements from the heap, the values become sorted (since maximum elements are always root only).
Since the time complexity of both the insertion algorithm and deletion algorithm is $O(logn)$ (where n is the number of items in the heap), the time complexity of the heap sort algorithm is $O(nlogn)$.

## Merge Sort

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

Similar to Counting sort and Bucket sort, this sorting algorithm also assumes some kind of information about the input elements.
Suppose that the input values to be sorted are from base d. That means all numbers are d-digit numbers.

In Radix sort, first sort the elements based on the last digit [the least significant digit].
These results are again sorted by second digit [the next to least significant digit].
Continue this process for all digits until we reach the most significant digits. Use some stable sort to sort them by last digit.
Then stable sort them by the second least significant digit, then by the third, etc.
If we use Counting sort as the stable sort, the total time is $O(nd) ≈ O(n)$.
Radix sort is sometimes known as *card sort*.

Algorithm:

1. Take the least significant digit of each element.
2. Sort the list of elements based on that digit, but keep the order of elements with the same digit (this is the definition of a stable sort).
3. Repeat the sort with each more significant digit.

The speed of Radix sort depends on the inner basic operations. If the operations are not efficient enough, Radix sort can be slower than other algorithms such as Quick sort and Merge sort.
These operations include the insert and delete functions of the sub-lists and the process of isolating the digit we want.
If the numbers are not of equal length then a test is needed to check for additional digits that need sorting.
This can be one of the slowest parts of Radix sort and also one of the hardest to make efficient.

Since Radix sort depends on the digits or letters, it is less flexible than other sorts.
For every different type of data, Radix sort needs to be rewritten, and if the sorting order changes, the sort needs to be rewritten again.
In short, Radix sort takes more time to write, and it is very difficult to write a general purpose Radix sort that can handle all kinds of data.

For many programs that need a fast sort, Radix sort is a good choice.
Still, there are faster sorts, which is one reason why Radix sort is not used as much as some other sorts.

Time Complexity: $O(nd) ≈ O(n)$, if d is small.

## Bucket Sort

## Tree Sort

Tree sort uses a binary search tree. It involves scanning each element of the input and placing it into its proper position in a binary search tree.
This has two phases:

- First phase is creating a binary search tree using the given array elements.
- Second phase is traversing the given binary search tree in inorder, thus resulting in a sorted array.

The average number of comparisons for this method is $O(nlogn)$.
But in worst case, the number of comparisons is reduced by $O(n^2)$, a case which arises when the sort tree is skew tree.

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
