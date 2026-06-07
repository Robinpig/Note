## Introduction

一个同步点，线程可以在该点配对并交换对内的元素。
Exchanger 允许两个线程在交汇点交换对象，这在多种管道设计中很有用。

每个线程在进入 exchange 方法时呈现一些对象，与伙伴线程匹配，并在返回时接收其伙伴的对象。
Exchanger 可以看作是一种双向形式的 **SynchronousQueue**。
Exchanger 可能用于诸如遗传算法和管道设计等应用中。
示例用法：以下是一个使用 Exchanger 在线程之间交换缓冲区的类的要点，以便填充缓冲区的线程在需要时可以获得一个刚清空的缓冲区，
并将已填充的缓冲区交给清空缓冲区的线程。

```java
 class FillAndEmpty {
   Exchanger<DataBuffer> exchanger = new Exchanger<>();
   DataBuffer initialEmptyBuffer = ... a made-up type
   DataBuffer initialFullBuffer = ...

   class FillingLoop implements Runnable {
     public void run() {
       DataBuffer currentBuffer = initialEmptyBuffer;
       try {
         while (currentBuffer != null) {
           addToBuffer(currentBuffer);
           if (currentBuffer.isFull())
             currentBuffer = exchanger.exchange(currentBuffer);
         }
       } catch (InterruptedException ex) { ... }
     }
   }

   class EmptyingLoop implements Runnable {
     public void run() {
       DataBuffer currentBuffer = initialFullBuffer;
       try {
         while (currentBuffer != null) {
           takeFromBuffer(currentBuffer);
           if (currentBuffer.isEmpty())
             currentBuffer = exchanger.exchange(currentBuffer);
         }
       } catch (InterruptedException ex) { ... }
     }
   }

   void start() {
     new Thread(new FillingLoop()).start();
     new Thread(new EmptyingLoop()).start();
   }
 }
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
