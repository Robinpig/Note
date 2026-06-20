## Introduction



A synchronization point at which threads can pair and swap elements within pairs.
An Exchanger allows two threads to exchange objects at a rendezvous point, and is useful in several pipeline designs.

Each thread presents some object on entry to the exchange method, matches with a partner thread, and receives its partner's object on return. 
An Exchanger may be viewed as a bidirectional form of a **SynchronousQueue**. 
Exchangers may be useful in applications such as genetic algorithms and pipeline designs.
Sample Usage: Here are the highlights of a class that uses an Exchanger to swap buffers between threads so that the thread filling the buffer gets a freshly emptied one when it needs it,
handing off the filled one to the thread emptying the buffer.



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
       } catch (InterruptedException ex) { ... handle ... }
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
       } catch (InterruptedException ex) { ... handle ...}
     }
   }

   void start() {
     new Thread(new FillingLoop()).start();
     new Thread(new EmptyingLoop()).start();
   }
 }
```

**Memory consistency effects**: For each pair of threads that successfully exchange objects via an Exchanger, actions prior to the exchange() in each thread happen-before those subsequent to a return from the corresponding exchange() in the other thread.