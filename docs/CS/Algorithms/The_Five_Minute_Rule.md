## Introduction

1987 年，Jim Gray 和 Gianfranco Putzolu 发表了著名的五分钟规则，用于权衡内存和 I/O 容量。
他们的计算比较了将记录（或页面）永久保存在内存中的成本与每次访问记录（或页面）时执行磁盘 I/O 的成本，
使用了 RAM 芯片和磁盘驱动器的适当比例价格。
这条规则的名称指的是访问之间的盈亏平衡间隔。
**如果一条记录（或页面）被更频繁地访问，则应保留在内存中；否则，应保留在磁盘上，并在需要时读取。**

## The Five-Minute Rule

> 每五分钟被引用一次的页面应该常驻内存。

这条规则适用于随机访问的页面。
一分钟规则适用于像排序这样的两遍顺序算法中使用的页面。

## The Five-Byte Rule

> 花费 5 字节主内存来节省每秒 1 条指令。

与 1987 年相比，最根本的变化可能是 CPU 能力不应以指令数来衡量，而应以缓存行替换来衡量。
在具有多级内存层次结构的环境中，用空间换取时间似乎是一个新问题。

## References

1. [The 5 Minute Rule for Trading Memory for Disc Accesses and the 5 Byte Rule for Trading Memory for CPU Time](http://notes.stephenholiday.com/Five-Minute-Rule.pdf)
2. [The Five-Minute Rule Ten Years Later, and Other Computer Storage Rules of Thumb](http://notes.stephenholiday.com/Five-Minute-Rule-10-Years-Later.pdf)
3. [The Five-Minute Rule 20 Years Later (and How Flash Memory Changes the Rules)](http://notes.stephenholiday.com/Five-Minute-Rule-20-Years-Later.pdf)
