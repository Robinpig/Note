## Introduction

一种同步辅助工具，允许**一组线程**全部等待彼此到达一个共同的屏障点。
CyclicBarrier 是一个可重置的多路同步点，在某些并行编程风格中很有用。

CyclicBarrier 在涉及固定大小的线程组且这些线程必须偶尔相互等待的程序中非常有用。
该 barrier 被称为 cyclic，因为它可以在等待线程被释放后重新使用。
CyclicBarrier 支持一个可选的 Runnable 命令，该命令在每个屏障点运行一次，在组中最后一个线程到达之后、
但在任何线程被释放之前。此屏障操作用于在任何线程继续之前更新共享状态。
示例用法：以下是在并行分解设计中使用 barrier 的示例：

```java
 class Solver {
   final int N;
   final float[][] data;
   final CyclicBarrier barrier;

   class Worker implements Runnable {
     int myRow;
     Worker(int row) { myRow = row; }
     public void run() {
       while (!done()) {
         processRow(myRow);

         try {
           barrier.await();
         } catch (InterruptedException ex) {
           return;
         } catch (BrokenBarrierException ex) {
           return;
         }
       }
     }
   }

   public Solver(float[][] matrix) {
     data = matrix;
     N = matrix.length;
     barrier = new CyclicBarrier(N,
                                 new Runnable() {
                                   public void run() {
                                     mergeRows(...);
                                   }
                                 });
     for (int i = 0; i < N; ++i) {
       new Thread(new Worker(i)).start();
     }
     waitUntilDone();
   }
 }
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
