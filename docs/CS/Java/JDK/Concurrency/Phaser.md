## Introduction

A reusable synchronization barrier, similar in functionality to CyclicBarrier and CountDownLatch but supporting more flexible usage.



```java
public Phaser() {
    this(null, 0);
}

public Phaser(Phaser parent, int parties) {
  if (parties >>> PARTIES_SHIFT != 0)
    throw new IllegalArgumentException("Illegal number of parties");
  int phase = 0;
  this.parent = parent;
  if (parent != null) {
    final Phaser root = parent.root;
    this.root = root;
    this.evenQ = root.evenQ;
    this.oddQ = root.oddQ;
    if (parties != 0)
      phase = parent.doRegister(1);
  }
  else {
    this.root = this;
    this.evenQ = new AtomicReference<QNode>();
    this.oddQ = new AtomicReference<QNode>();
  }
  this.state = (parties == 0) ? (long)EMPTY :
  ((long)phase << PHASE_SHIFT) |
    ((long)parties << PARTIES_SHIFT) |
    ((long)parties);
}
```



Registration. Unlike the case for other barriers, the number of parties registered to synchronize on a phaser may vary over time. Tasks may be registered at any time (using methods register, bulkRegister, or forms of constructors establishing initial numbers of parties), and optionally deregistered upon any arrival (using arriveAndDeregister). As is the case with most basic synchronization constructs, registration and deregistration affect only internal counts; they do not establish any further internal bookkeeping, so tasks cannot query whether they are registered. (However, you can introduce such bookkeeping by subclassing this class.)

Synchronization. Like a CyclicBarrier, a Phaser may be repeatedly awaited. Method arriveAndAwaitAdvance has effect analogous to CyclicBarrier.await. Each generation of a phaser has an associated phase number. The phase number starts at zero, and advances when all parties arrive at the phaser, wrapping around to zero after reaching Integer.MAX_VALUE. The use of phase numbers enables independent control of actions upon arrival at a phaser and upon awaiting others, via two kinds of methods that may be invoked by any registered party:

Arrival. Methods arrive and arriveAndDeregister record arrival. These methods do not block, but return an associated arrival phase number; that is, the phase number of the phaser to which the arrival applied. When the final party for a given phase arrives, an optional action is performed and the phase advances. These actions are performed by the party triggering a phase advance, and are arranged by overriding method onAdvance(int, int), which also controls termination. Overriding this method is similar to, but more flexible than, providing a barrier action to a CyclicBarrier.

Waiting. Method awaitAdvance requires an argument indicating an arrival phase number, and returns when the phaser advances to (or is already at) a different phase. Unlike similar constructions using CyclicBarrier, method awaitAdvance continues to wait even if the waiting thread is interrupted. Interruptible and timeout versions are also available, but exceptions encountered while tasks wait interruptibly or with timeout do not change the state of the phaser. If necessary, you can perform any associated recovery within handlers of those exceptions, often after invoking forceTermination. Phasers may also be used by tasks executing in a ForkJoinPool. Progress is ensured if the pool's parallelism level can accommodate the maximum number of simultaneously blocked parties.



Termination. A phaser may enter a termination state, that may be checked using method isTerminated. Upon termination, all synchronization methods immediately return without waiting for advance, as indicated by a negative return value. Similarly, attempts to register upon termination have no effect. Termination is triggered when an invocation of onAdvance returns true. The default implementation returns true if a deregistration has caused the number of registered parties to become zero. As illustrated below, when phasers control actions with a fixed number of iterations, it is often convenient to override this method to cause termination when the current phase number reaches a threshold. Method forceTermination is also available to abruptly release waiting threads and allow them to terminate.

Tiering. Phasers may be tiered (i.e., constructed in tree structures) to reduce contention. Phasers with large numbers of parties that would otherwise experience heavy synchronization contention costs may instead be set up so that groups of sub-phasers share a common parent. This may greatly increase throughput even though it incurs greater per-operation overhead.
In a tree of tiered phasers, registration and deregistration of child phasers with their parent are managed automatically. Whenever the number of registered parties of a child phaser becomes non-zero (as established in the Phaser(Phaser, int) constructor, register, or bulkRegister), the child phaser is registered with its parent. Whenever the number of registered parties becomes zero as the result of an invocation of arriveAndDeregister, the child phaser is deregistered from its parent.

Monitoring. While synchronization methods may be invoked only by registered parties, the current state of a phaser may be monitored by any caller. At any given moment there are getRegisteredParties parties in total, of which getArrivedParties have arrived at the current phase (getPhase). When the remaining (getUnarrivedParties) parties arrive, the phase advances. The values returned by these methods may reflect transient states and so are not in general useful for synchronization control. Method toString returns snapshots of these state queries in a form convenient for informal monitoring.



## Sample usages
A Phaser may be used instead of a CountDownLatch to control a one-shot action serving a variable number of parties. The typical idiom is for the method setting this up to first register, then start all the actions, then deregister, as in:
```java
 void runTasks(List<Runnable> tasks) {
   Phaser startingGate = new Phaser(1); // "1" to register self
   // create and start threads
   for (Runnable task : tasks) {
     startingGate.register();
     new Thread(() -> {
       startingGate.arriveAndAwaitAdvance();
       task.run();
     }).start();
   }

   // deregister self to allow threads to proceed
   startingGate.arriveAndDeregister();
 }
```

One way to cause a set of threads to repeatedly perform actions for a given number of iterations is to override onAdvance:
```java
 void startTasks(List<Runnable> tasks, int iterations) {
   Phaser phaser = new Phaser() {
     protected boolean onAdvance(int phase, int registeredParties) {
       return phase >= iterations - 1 || registeredParties == 0;
     }
   };
   phaser.register();
   for (Runnable task : tasks) {
     phaser.register();
     new Thread(() -> {
       do {
         task.run();
         phaser.arriveAndAwaitAdvance();
       } while (!phaser.isTerminated());
     }).start();
   }
   // allow threads to proceed; don't wait for them
   phaser.arriveAndDeregister();
 }
If the main task must later await termination, it may re-register and then execute a similar loop:

   // ...
   phaser.register();
   while (!phaser.isTerminated())
     phaser.arriveAndAwaitAdvance();
Related constructions may be used to await particular phase numbers in contexts where you are sure that the phase will never wrap around Integer.MAX_VALUE. For example:

 void awaitPhase(Phaser phaser, int phase) {
   int p = phaser.register(); // assumes caller not already registered
   while (p < phase) {
     if (phaser.isTerminated())
       // ... deal with unexpected termination
     else
       p = phaser.arriveAndAwaitAdvance();
   }
   phaser.arriveAndDeregister();
 }
```
To create a set of n tasks using a tree of phasers, you could use code of the following form, assuming a Task class with a constructor accepting a Phaser that it registers with upon construction. After invocation of build(new Task[n], 0, n, new Phaser()), these tasks could then be started, for example by submitting to a pool:
```java
 void build(Task[] tasks, int lo, int hi, Phaser ph) {
   if (hi - lo > TASKS_PER_PHASER) {
     for (int i = lo; i < hi; i += TASKS_PER_PHASER) {
       int j = Math.min(i + TASKS_PER_PHASER, hi);
       build(tasks, i, j, new Phaser(ph));
     }
   } else {
     for (int i = lo; i < hi; ++i)
       tasks[i] = new Task(ph);
       // assumes new Task(ph) performs ph.register()
   }
 }
```

The best value of TASKS_PER_PHASER depends mainly on expected synchronization rates. A value as low as four may be appropriate for extremely small per-phase task bodies (thus high rates), or up to hundreds for extremely large ones.
Implementation notes: This implementation restricts the maximum number of parties to 65535. Attempts to register additional parties result in IllegalStateException. However, you can and should create tiered phasers to accommodate arbitrarily large sets of participants.