## Introduction

搜索问题


线性搜索是一种简单的搜索策略 通过循环遍历每个元素的方式直到找到目标

## Binary Search

二分搜索适用于有序数组 相比于线性查找 可以在每次查询时成倍缩小查询范围 将时间复杂度降低到 $O(logN)$


```java
public class BinarySearchUtil {

    public static void main(String[] args) {
        int[] array = {1, 3, 5, 7, 9, 11, 13, 15, 17, 19};
        int target = 7;
        int index = binarySearch(array, target);
        if (index != -1) {
            System.out.println("Target found at index: " + index);
        } else {
            System.out.println("Target not found in the array.");
        }
    }
}
```
middle取值为 middle = left + (right - left) >> 2, 等同于 (right + left)/2 作用是防止溢出

将比较的三种情况独立出来而不是用 <= 这样的处理 首先是更清楚 其次能够支持更多问题变体
下一个右区间的的 left = middle + 1


二分搜索需要注意的地方是 left 和 right 的判断和 middle 的取值, 而这与区间的取值有关 [left, right] 或是 [left, right) 或是 (left, right)

- [left, right], while(left <= right), 下一个左区间的 right = middle - 1, left = mid + 1
- [left, right), while(left < right), 下一个左区间的 right = middle, left = mid + 1
- (left, right), while(left + 1 < right), 下一个左区间的 right = middle, left = mid, left 初始值为 -1



三种实现

<!-- tabs:start -->

###### **左闭右闭**

```java
public class BinarySearchUtil {

    /**
     * 二分查找算法，使用左闭右闭区间 [left, right]。
     */
    public static int binarySearch(int[] array, int target) {
        int left = 0; // 左边界初始为 0，表示左闭区间
        int right = array.length - 1; // 右边界初始为数组长度减一，表示右闭区间

        while (left <= right) { // 当左边界小于等于右边界时继续循环
            int mid = left + (right - left) / 2; // 计算中间位置，防止溢出

            if (array[mid] == target) {
                return mid; // 找到目标值，返回索引
            } else if (array[mid] < target) {
                left = mid + 1; // 目标值在右半部分，更新左边界
            } else {
                right = mid - 1; // 目标值在左半部分，更新右边界
            }
        }

        return -1; // 未找到目标值，返回 -1
    }
}
```



###### **左闭右开**

```java
public class BinarySearchUtil {

    /**
     * 二分查找算法，使用左闭右开区间 [left, right)。
     */
    public static int binarySearch(int[] array, int target) {
        int left = 0;
        int right = array.length; // 右边界是开区间，所以初始值为数组长度

        while (left < right) { // 当左边界小于右边界时继续循环
            int mid = left + (right - left) / 2; // 计算中间位置，防止溢出

            if (array[mid] == target) {
                return mid; // 找到目标值，返回索引
            } else if (array[mid] < target) {
                left = mid + 1; // 目标值在右半部分，更新左边界
            } else {
                right = mid; // 目标值在左半部分，更新右边界
            }
        }

        return -1; // 未找到目标值，返回 -1
    }
}
```



###### **左开右开**

```java
public class BinarySearchUtil {

    /**
     * 二分查找算法，使用左开右开区间 (left, right)。
     */
    public static int binarySearch(int[] array, int target) {
        int left = -1; // 左边界初始为 -1，表示左开区间
        int right = array.length; // 右边界初始为数组长度，表示右开区间

        while (left + 1 < right) { // 当区间内还有元素时继续循环
            int mid = left + (right - left) / 2; // 计算中间位置，防止溢出

            if (array[mid] == target) {
                return mid; // 找到目标值，返回索引
            } else if (array[mid] < target) {
                left = mid; // 目标值在右半部分，更新左边界
            } else {
                right = mid; // 目标值在左半部分，更新右边界
            }
        }

        return -1; // 未找到目标值，返回 -1
    }
}
```

<!-- tabs:end -->



### 二分搜索变体




**应用:**

Kafka 的 索引文件







## Graph Search

### DFS

DFS 全称是 *Depth First Search*，中文名是深度优先搜索，是一种用于遍历或搜索树或图的算法
“二叉树”的前序、中序和后序遍历都属于深度优先搜索

所谓深度优先，就是说每次都尝试向更深的节点走

DFS 最显著的特征在于其 **递归调用自身**

DFS 会对其访问过的点打上访问标记，在遍历图时跳过已打过标记的点，以确保 **每个点仅访问一次**。符合以上两条规则的函数，便是广义上的 DFS

DFS 天然符合回溯法的使用场景 常规做法是使用递归来实现


### BFS

BFS 全称是 *Breadth First Search*，中文名是宽度优先搜索，也叫广度优先搜索。所谓宽度优先。就是每次都尝试访问同一层的节点。 
如果同一层都访问完了，再访问下一层 这样做的结果是，BFS 算法找到的路径是从起点开始的 最短合法路径
换言之，这条路径所包含的边数最小 在 BFS 结束时，每个节点都是通过从起点到该点的最短路径访问的

BFS 是从源点向外逐层推进 没遍历一层都需要使用上一层的节点 所以需要使用一个容器存储上一层的元素用来依次遍历 通常是使用一个FIFO的队列

这样的方式适合于树的层序遍历 如果有特殊的搜索退出条件 例如最短路径问题时 并不需要遍历所有的路径

对元素判重复能防止重复的搜索 同时在图搜时能避免搜索无法结束(图有环)



二者的时间复杂度没有太大差别 假设有个图 $G(V, E)$ 
BFS 需要对顶点出入队一次 复杂度是 $O(V+E)$ DFS 是 $O(E)$ 
实际复杂网络中 一般 V 远小于 E  两者都近似为 $O((E)$

两者在实际的适用场景还是有些区别的 在求最短路径时 例如迷宫 BFS 最早搜索到终点时就是最短路径 可以提前结束 而DFS需要递归完整个搜索空间 找出所有可能路径进行比较 
若已知搜索空间很大 搜索路径不会特别长时 BFS 可能会比 DFS 更快一些

DFS 实现起来比 BFS 更简单，且由于递归栈的存在，让我们可以很方便地在递归函数的参数中记录路径，所以需要输出路径的题目用 DFS 会比较合适



## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)