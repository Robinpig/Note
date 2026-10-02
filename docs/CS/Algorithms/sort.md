## Introduction

Sorting is the process of rearranging a sequence of objects so as to put them in some logical order.
All computer systems have implementations of sorting algorithms, for use by the system and by users.

The sorting algorithms divide into two basic types:
those that sort in place and use no extra memory except perhaps for a small functioncall stack or a constant number of instance variables, and those that need enough extra memory to hold another copy of the array to be sorted.


## Classification of Sorting Algorithms

Sorting algorithms are generally categorized based on the following parameters.

**By Number of Comparisons**

In this method, sorting algorithms are classified based on the number of comparisons.
For comparison based sorting algorithms, best case behavior is O(nlogn) and worst case behavior is $O(n^2)$.
Comparison-based sorting algorithms evaluate the elements of the list by key comparison operation and need at least O(nlogn) comparisons for most inputs.
Later in this chapter we will discuss a few non – comparison (linear) sorting algorithms like Counting sort, Bucket sort, Radix sort, etc.
Linear Sorting algorithms impose few restrictions on the inputs to improve the complexity

**By Number of Swaps**

In this method, sorting algorithms are categorized by the number of swaps (also called inversions).

**By Memory Usage**

Some sorting algorithms are “in place” and they need O(1) or O(logn) memory to create auxiliary locations for sorting the data temporarily.

**By Recursion**

Sorting algorithms are either recursive quick sort or non-recursive selection sort, and insertion sort, and there are some algorithms which use both (merge sort).

**By Stability**

稳定性是指相等的元素经过排序之后相对顺序是否发生了改变。
拥有稳定性这一特性的算法会让原本有相等键值的纪录维持相对次序，即如果一个排序算法是稳定的，当有两个相等键值的纪录 𝑅 和 𝑆，且在原本的列表中 𝑅 出现在 𝑆 之前，在排序过的列表中 𝑅 也将会是在 𝑆 之前。

基数排序、计数排序、插入排序、冒泡排序、归并排序是稳定排序。
选择排序、堆排序、快速排序、希尔排序不是稳定排序



**By Adaptability**

With a few sorting algorithms, the complexity changes based on pre-sortedness quick sort: pre- sortedness of the input affects the running time. 
Algorithms that take this into account are known to be adaptive.

Another method of classifying sorting algorithms is:

- Internal Sort
  Sort algorithms that use main memory exclusively during the sort are called internal sorting algorithms. This kind of algorithm assumes high-speed random access to all memory.
- External Sort
  Sorting algorithms that use external memory, such as tape or disk, during the sort come under this category.


| Sort   | Avg Time   | Avg Space  | Best Time  | Best Space | Bad Time   | Bad Space |
| ------ | ---------- | ---------- | ---------- | ---------- | ---------- | --------- |
| Bubble | $O(n^2)$   | $O(1)$     | $O(n)$     | $O(1)$     | $O(n^2)$   | $O(1)$    |
| Select | $O(n^2)$   | $O(1)$     | $O(n^2)$   | $O(1)$     | $O(n^2)$   | $O(1)$    |
| Insert | $O(n^2)$   | $O(n^2)$   | $O(n)$     | $O(1)$     | $O(n^2)$   | $O(n^2)$  |
| Shell  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Heap   | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Merge  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Quick  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n^2)$   | $O(n)$    |
| Radix  | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Bucket | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |
| Tree   | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(nlogn)$ | $O(n)$    |




After considering the classic [selection sort](/docs/CS/Algorithms/sort.md?id=selection-sort) [insertion sort](/docs/CS/Algorithms/sort.md?id=insertion-sort),
[shellsort](/docs/CS/Algorithms/sort.md?id=shell-sort), [mergesort](/docs/CS/Algorithms/sort.md?id=merge-sort), 
[quicksort](/docs/CS/Algorithms/sort.md?id=quick-sort), and [heapsort](/docs/CS/Algorithms/sort.md?id=heap-sort) algorithms, we will consider practical issues and applications.

Suppose you have a group of n numbers and would like to determine the kth largest. This is known as the _selection problem_.

We consider two classes of sorting algorithms.

The first class of algorithms makes use of the structure of the elements to be sorted.
For example. if the elements to be sorted are integers in a fixed range 0 to m - 1, then we can sort a sequence of /1 eleme Qts. in $O(n + m)$ time;
if the elements to be sorted are strings over a fixed alphabet, then a sequence of strings can be sorted in time linearly proportional to the sum of the lengths of the strings.

The second class of algorithms assumes no structure on the elements to be sorted. The basic operation is a comparison between a pair of elements.

With algorithms of this nature we shall see that at least n log /1 comparisons are needed to sort a sequence of n elements.
We give two $O(nlogn)$ sorting algorithms-Heapsort. which is $O(nlogn)$ in the worst case, and Quicksort, which is $O(nlogn)$ in the expected case.


## Bubble Sort

Bubble sort is the simplest sorting algorithm. It works by iterating the input array from the first element to the last, comparing each pair of elements and swapping them if needed.
Bubble sort continues its iterations until no more swaps are needed.
The algorithm gets its name from the way smaller elements “bubble” to the top of the list.
Generally, insertion sort has better performance than bubble sort.
Some researchers suggest that we should not teach bubble sort because of its simplicity and high time complexity.
The only significant advantage that bubble sort has over other implementations is that it can detect whether the input list is already sorted or not.

```
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

```java
for(int i = 0; i < nums.length; i++){
  for(int j nums.length; j > i; j--){
  		// swap into nums[i]
	}
}
```





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







## Heap Sort

Time complexity: As we remove the elements from the heap, the values become sorted (since maximum elements are always root only).
Since the time complexity of both the insertion algorithm and deletion algorithm is $O(logn)$ (where n is the number of items in the heap), 
the time complexity of the heap sort algorithm is $O(nlogn)$.

## Merge Sort

> [!NOTE]
>
> Top-down mergesort uses between $½NlgN$ and $NlgN$ compares to sort any array of length N.
>
> Top-down mergesort uses at most $6NlgN$ array accesses to sort an array of length N.

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

## Quick Sort

Like Merge Sort, QuickSort is a Divide and Conquer algorithm.
It picks an element as a pivot and partitions the given array around the picked pivot.
There are many different versions of quickSort that pick pivot in different ways.

- Always pick the first element as a pivot.
- Always pick the last element as a pivot (implemented below)
- Pick a random element as a pivot.
- Pick median as the pivot.

The key process in quickSort is a partition().
The target of partitions is, given an array and an element x of an array as the pivot, 
put x at its correct position in a sorted array and put all smaller elements (smaller than x) before x, and put all greater elements (greater than x) after x.
All this should be done in linear time.

Partition Algorithm:
<br>
There can be many ways to do partition, following pseudo-code adopts the method given in the CLRS book.
The logic is simple, we start from the leftmost element and keep track of the index of smaller (or equal to) elements as i.
While traversing, if we find a smaller element, we swap the current element with arr[i].
Otherwise, we ignore the current element.

Pseudo Code for recursive QuickSort function:

```python
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

The algorithm doesn’t spend time allocating and managing additional memory (unlike [MergeSort](/docs/CS/Algorithms/sort.md?id=merge-sort)).

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



## Tim Sort

Timsort 由 Python 核心开发者 Tim Peters 于 2002 年设计，并应用于 Python 语言，其巧妙结合了插入排序和归并排序的优点，针对数据集中的有序性进行了精确的优化，尤其适合处理包含大量部分有序子序列的数据集

Timsort 的核心思想是通过识别和利用数据集中已有的有序性，提高排序效率，其主要包括以下步骤：

1. **识别 Run**：扫描待排序数组，识别出有序的连续子序列（Run）。
2. **扩展 Run**：如果识别的 Run 长度小于 `MIN_RUN`，则使用插入排序对其进行扩展。
3. **归并 Run**：Timsort 维护一个特殊的栈，采用特定的归并策略将栈中已有的 Run 合并成更大的有序序列



首先，Timsort 会从左向右扫描数组，识别出连续的有序序列，这些有序序列被称为 Run：

- **升序 Run**：如果后一个元素大于等于前一个元素，则继续扩展 Run。
- **降序 Run**：如果后一个元素小于前一个元素，则继续扩展 Run，随后将该 Run 反转为升序

为了提高小规模数据的排序效率，Timsort 引入了一个 Run 最小的长度 `MIN_RUN`。其值一般根据待排序数组的长度动态计算，通常为 3232![32](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 至 6464![64](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 之间。

- 如果识别的 Run 长度大于等于 `MIN_RUN`，则不需要额外操作，直接将 Run 压入栈中。
- 如果识别的 Run 长度小于 `MIN_RUN`，则使用二分插入排序将该 Run 的后续元素插入到 Run 中，直到 Run 的长度达到 `MIN_RUN`，然后将其压入栈中。



在 Timsort 中，归并排序是通过 **栈** 来管理和控制的。栈中保存了已经识别出的有序的 Run，并通过特定的归并规则控制栈中 Run 的合并，其目的是在合并时保持序列的平衡性和稳定性

Timsort 是一种稳定的排序算法，即相同元素在排序后仍然保持原有的相对顺序。为确保这一点，Timsort 在归并时只会合并相邻的、连续的 Run，而不会直接合并非相邻的 Run。因为非相邻的 Run 之间可能存在相同的元素，直接合并很有可能会打乱它们的相对顺序

同时，为了确保合并的平衡性，Timsort 引入了特定的归并规则。在每次合并操作之前，算法会检查栈顶的三个 Run X、Y 和 Z，以确保满足以下两个条件：

- **条件一**：`len(Z) > len(Y) + len(X)`
- **条件二**：`len(Y) > len(X)`

如果栈顶的三个 Run 不满足上述条件，Timsort 会将 Y 与 X 或 Z 中较小的一个进行合并，然后再次检查条件。一旦条件满足，则开始继续搜索新的 Run，将其添加到栈中并开始下一轮的归并

为了在归并不同长度的 Run 时提高效率并减少空间开销，Timsort 在归并前会通过二分查找精确定位需要处理的元素范围，只对需要移动的部分进行归并，具体方式为：

1. **确定插入点**：使用二分查找，找到第二个 Run 的第一个元素在第一个 Run 中的插入位置，以及第一个 Run 的最后一个元素在第二个 Run 中的插入位置。这样，可以缩小需要归并的范围，只对需要移动的元素进行处理。
2. **临时缓冲区**：传统的原地合并算法效率太低，需要大量的元素移动。为了减少这种开销，Timsort 使用一个临时缓冲区，将长度较小的 Run 复制到缓冲区中，然后逐步将元素从缓冲区复制回原数组。

为进一步提升归并效率，Timsort 引入了 **加速模式（Galloping Mode）**。在标准的归并过程中，算法会逐一比较两个 Run 中的元素，将较小的元素放入结果数组。然而，如果一侧的 Run 中有大量连续元素比另一侧的当前元素要小，逐一比较会造成不必要的开销。

为了解决这一问题，Timsort 设定了一个阈值 `Min_Gallop`（默认值为 77![7](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)）。当一侧 Run 中的元素连续比较胜利的次数达到 `Min_Gallop` 时，算法会进入加速模式，快速定位元素位置，其具体步骤如下：

1. **指数查找**：从当前位置开始，算法以指数增长的步长 (1,2,4,8,…)(1,2,4,8,…)![(1, 2, 4, 8, \dots)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 在一侧的 Run 中查找，直到找到一个区间，使得目标元素位于该区间内。
2. **二分查找**：一旦确定了包含目标元素的区间，算法会在该区间内使用二分查找，精确定位目标元素的位置。

通过这种方式，Timsort 可以跳过大量不必要的比较，快速处理一侧 Run 中连续的、较小（或较大）的元素，将它们批量移动到合并结果中。

然而，加速模式并非在所有情况下都更高效。在某些数据分布下，加速模式可能导致更多的比较次数。为此，Timsort 采用了动态调整策略：

- **阈值调整**：维护一个可变的 `Min_Gallop` 参数。当加速模式表现良好（即连续多次从同一 Run 中选取元素）时，`Min_Gallop` 减 11![1](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)，鼓励继续使用加速模式；当加速模式效果不佳（频繁在两个 Run 之间切换）时，`Min_Gallop` 加 11![1](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)，降低加速模式的使用频率。

通过动态调整 `Min_Gallop` 的值，算法能够根据实际数据情况，在普通归并模式和加速模式之间取得平衡。对于部分有序或高度有序的数据，加速模式可以显著提高效率，使 Timsort 的性能接近 𝑂(𝑛)O(n)![O(n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)；而对于随机数据，算法会逐渐倾向于使用普通归并，从而保证 𝑂(𝑛log⁡𝑛)O(nlog⁡n)![O(n \log n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 的时间复杂度

Timsort 的时间复杂度取决于数据的有序性：

- 最优情况：$𝑂(𝑛)$
  - 当数据已经有序或近似有序时，算法识别出的 Run 长度接近 𝑛n![n](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)，归并次数减少，复杂度趋近于 𝑂(𝑛)O(n)![O(n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)。
- 最坏情况：$𝑂(𝑛log⁡𝑛)$
  - 在数据完全无序的情况下，每一个 Run 的长度都接近 11![1](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)，因此需要 𝑂(log⁡𝑛)O(log⁡n)![O(\log n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 次归并，每次归并的代价为 𝑂(𝑛)O(n)![O(n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)，总复杂度为 𝑂(𝑛log⁡𝑛)O(nlog⁡n)![O(n \log n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7)。



对于空间复杂度，由于 Timsort 大致需要额外的 𝑂(𝑛)O(n)![O(n)](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 空间用于存储栈和临时缓冲区，因此总的空间复杂度为 𝑂(𝑛)





## Bucket Sort







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

## 

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

外部排序的步骤:

- 部分排序 根据内存大小 将待排序的文件拆成多个部分 选择合适的内排序算法对这些文件 输出到外部临时文件中
- 归并阶段 对这些排序后的文件进行多路归并 当存储不足时可以分多次归并

相比于内部排序 外部排序有个较大的时间消耗在IO上 归并阶段时每次归并都是遍历全部的文件 为了减少IO次数 可以通过增加更多的归并路数, 从而降低归并层数

构建二叉堆记录出最近



### Multiway Merge

## Others

The Pancake Flipping problem is NP-hard.(see [Pancake Flipping is Hard](https://arxiv.org/pdf/1111.0434v1.pdf))

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

## References

1. [AlphaSort: A RISC Machine Sort](https://courses.cs.washington.edu/courses/cse590q/05wi/paper/p233-nyberg.pdf)
