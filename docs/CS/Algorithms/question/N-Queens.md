## Introduction

在 n  × n 格的国际象棋盘上摆 n 个皇后，使其不能互相攻击，即任意两个皇后都不能处在同一行、同一列或同一斜线上，问有多种解法（斜线指棋盘上所有斜线）



## Backtracking

[回溯算法（Backtracking）](/docs/CS/Algorithms/Backtracking.md) 是解决N皇后问题的标准方法
该算法通过尝试在棋盘上放置皇后，当发现当前放置方案无法继续时，就撤销最近的选择，回溯到上一步并尝试其他可能性，直到找到完整解或尝试所有可能后确认无解

使用一个数组记录每行放置的皇后的列下标，依次在每一行放置一个皇后。
每次新放置的皇后都不能和已经放置的皇后之间有攻击：即新放置的皇后不能和任何一个已经放置的皇后在同一列以及同一条斜线上，并更新数组中的当前行的皇后列下标。
当 N 个皇后都放置完毕，则找到一个可能的解。当找到一个可能的解之后，将数组转换成表示棋盘状态的列表，并将该棋盘状态的列表加入返回列表。

由于每个皇后必须位于不同列，因此已经放置的皇后所在的列不能放置别的皇后。
第一个皇后有 N 列可以选择，第二个皇后最多有 N−1 列可以选择，第三个皇后最多有 N−2 列可以选择（如果考虑到不能在同一条斜线上，可能的选择数量更少），因此所有可能的情况不会超过 N! 种，遍历这些情况的时间复杂度是 O(N!)



```java
public class Solution {
 int GRID_SIZE = 8;

    void placeQueens(int row, Integer[] columns, ArrayList<Integer[]> results) {
        if (row == GRID_SIZE) { // 找到有效摆法
            results.add(columns.clone());
        } else {
            for (int col = 0; col < GRID_SIZE; col++) {
                if (checkValid(columns, row, col)) {
                    columns[row] = col; // 摆放皇后
                    placeQueens(row + 1, columns, results);
                }
            }
        }
    }

    /* 检查(row1, column1)可否摆放皇后，做法是检查
     * 有无其他皇后位于同一列或对角线。不必检查是否
     * 在同一行上，因为调用 placeQueen时，一次只会
     * 摆放一个皇后。由此可知，这一行是空的 */
    boolean checkValid(Integer[] columns, int row1, int column1) {
        for (int row2 = 0; row2 < row1; row2++) {
            int column2 = columns[row2];
            /* 检查摆放在(row2, column2)是否会
             * 让(row1, column1)变成无效 */

            /* 检查同一列是否有其他皇后 */
            if (column1 == column2) {
                return false;
            }

            /* 检查对角线：若两列的距离等于两行的
             * 距离，就表示两个皇后在同一对角线上 */
            int columnDistance = Math.abs(column2 - column1);

            /* row1 > row2，不用取绝对值 */
            int rowDistance = row1 - row2;
            if (columnDistance == rowDistance) {
                return false;
            }
        }
        return true;
    }

}
```



复杂度分析

- 时间复杂度：$O(n!)$，其中 n*n* 是皇后数量。
- 空间复杂度：O(n2)*O*(*n*2)，其中 n*n* 是皇后数量。递归调用层数不会超过 n*n*，每个棋盘的空间复杂度为 O(n2)*O*(*n*2)，所以空间复杂度为 O(n2)*O*(*n*2)。





## Links

- [Backtracking](/docs/CS/Algorithms/Backtracking.md)
