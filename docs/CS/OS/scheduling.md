## Introduction

Workload Assumptions


### Scheduling Metrics

Beyond making workload assumptions, we also need one more thing to enable us to compare different scheduling policies: a scheduling metric.

The **turnaround time** of a job is defined as the time at which the job completes minus the time at which the job arrived in the system.
More formally, the turnaround time Tturnaround is:
```tex
T_{turnaround} = T_{completion} − T_{arrival}
```

Because we have assumed that all jobs arrive at the same time, for now Tarrival = 0 and hence Tturnaround = Tcompletion.
This fact will change as we relax the aforementioned assumptions.

Another metric of interest is fairness.

Performance and fairness are often at odds in scheduling; a scheduler, for example, may optimize performance but at the cost of preventing a few jobs from running, thus decreasing fairness.





When a computer is multiprogrammed, it frequently has multiple processes or threads competing for the CPU at the same time.
This situation occurs whenever two or more of them are simultaneously in the ready state.
If only one CPU is available, a choice has to be made which process to run next.
The part of the operating system that makes the choice is called the **scheduler**, and the algorithm it uses is called the **scheduling algorithm**.

Many of the same issues that apply to process scheduling also apply to thread scheduling, although some are different.
When the kernel manages threads, scheduling is usually done per thread, with little or no regard to which process the thread belongs.


Nearly all processes alternate bursts of computing with (disk or network) I/O requests.
I/O is when a process enters the blocked state waiting for an external device to complete its work.
If an I/O-bound process wants to run, it should get a chance quickly so that it can issue its disk request and keep the disk busy.


### When to Schedule

A key issue related to scheduling is when to make scheduling decisions.
It turns out that there are a variety of situations in which scheduling is needed.
- First, when a new process is created, a decision needs to be made whether to run the parent process or the child process.
- Second, a scheduling decision must be made when a process exits.
- Third, when a process blocks on I/O, on a semaphore, or for some other reason, another process has to be selected to run.
- Fourth, when an I/O interrupt occurs, a scheduling decision may be made.
- If a hardware clock provides periodic interrupts at 50 or 60 Hz or some other frequency, a scheduling decision can be made at each clock interrupt or at every kth clock interrupt.


## Scheduling Algorithm Goals

All systems
- Fairness - giving each process a fair share of the CPU
- Policy enforcement - seeing that stated policy is carried out
- Balance - keeping all parts of the system busy

Batch systems
- Throughput - maximize jobs per hour
- Turnaround time - minimize time between submission and termination
- CPU utilization - keep the CPU busy all the time

Interactive systems
- Response time - respond to requests quickly
- Propor tionality - meet users’ expectations

Real-time systems
- Meeting deadlines - avoid losing data
- Predictability - avoid quality degradation in multimedia systems

### Scheduling in Batch Systems

Probably the simplest of all scheduling algorithms ever devised is nonpreemptive first-come, first-served.

#### Shortest job first
Shortest job first is a nonpreemptive batch algorithm that assumes the run times are known in advance.

#### Shortest remaining time next

A preemptive version of shortest job first is shortest remaining time next.

### Scheduling in Interactive Systems

One of the oldest, simplest, fairest, and most widely used algorithms is round robin.
Each process is assigned a time interval, called its quantum, during which it is allowed to run.
If the process is still running at the end of the quantum, the CPU is preempted and given to another process.
If the process has blocked or finished before the quantum has elapsed, the CPU switching is done when the process blocks, of course. Round robin is easy to implement.
All the scheduler needs to do is maintain a list of runnable processes.
When the process uses up its quantum, it is put on the end of the list.

Setting the quantum too short causes too many process switches and lowers the CPU efficiency, but setting it too long may cause poor response to short interactive requests.
A quantum around 20–50 msec is often a reasonable compromise.

The basic idea of priority scheduling is straightforward: each process is assigned a priority, and the runnable process with the highest priority is allowed to run.

Schedulers want accepting any input from user processes about scheduling decisions to make the best choice.
The solution to this problem is to separate the *scheduling mechanism* from the *scheduling policy*.
What this means is that the scheduling algorithm is parameterized in some way, but the parameters can be filled in by user processes. Let us consider the database example once again.
Suppose that the kernel uses a priority-scheduling algorithm but provides a system call by which a process can set (and change) the priorities of its children.
In this way, the parent can control how its children are scheduled, even though it itself does not do the scheduling.
Here the mechanism is in the kernel but policy is set by a user process. Policy-mechanism separation is a key idea.




## Scheduling Algorithms

What the scheduler should optimize for is not the same in all systems. Three environments worth distinguishing are:
1. Batch.
2. Interactive.
3. Real time.

Consequently, nonpreemptive algorithms, or preemptive algorithms with long time periods for each process, are often acceptable in batch systems.

In an environment with interactive users, preemption is essential to keep one process from hogging the CPU and denying service to the others.

In systems with real-time constraints, preemption is, oddly enough, sometimes not needed because the processes know that they may not run for long periods of time and usually do their work and block quickly.
The difference with interactive systems is that real-time systems run only programs that are intended to further the application at hand.
Interactive systems are general purpose and may run arbitrary programs that are not cooperative and even possibly malicious.



The most basic algorithm we can implement is known as First In, First Out (FIFO) scheduling or sometimes First Come, First Served (FCFS).
FIFO has a number of positive properties: it is clearly simple and thus easy to implement.

This problem is generally referred to as the **convoy effect**, where a number of relatively-short potential consumers of a resource get queued behind a heavyweight resource consumer.

### SJF

This new scheduling discipline is known as Shortest Job First (SJF), and the name should be easy to remember because it describes the policy quite completely: it runs the shortest job first, then the next shortest, and so on.
SJF performs much better with regards to average turnaround time.


Shortest Job First represents a general scheduling principle that can be applied to any system where the perceived turnaround time per customer(or, in our case, a job) matters.
Think of any line you have waited in: if the establishment in question cares about customer satisfaction, it is likely they have taken SJF into account.
For example, grocery stores commonly have a “ten-items-or-less” line to ensure that shoppers with only a few things to purchase don’t get stuck behind the family preparing for some upcoming nuclear winter.


SJF is a non-preemptive scheduler.

### STCF

Fortunately, there is a scheduler which does exactly that: add preemption to SJF, known as the Shortest Time-to-Completion First (STCF) or Preemptive Shortest Job First (PSJF) scheduler.





Now users would sit at a terminal and demand interactive performance from the system as well. And thus, a new metric was born: **response time**.

We define response time as the time from when the job arrives in a system to the first time it is scheduled3.
More formally:

```tex
T_{response} = T_{firstrun} − T_{arrival}
```

STCF and related disciplines are not particularly good for response time.
While great for turnaround time, this approach is quite bad for response time and interactivity.



RR

The basic idea is simple: instead of running jobs to completion, RR runs a job for a time slice (sometimes called a scheduling quantum) and then switches to the next job in the run queue.

RR is sometimes called time-slicing. Note that the length of a time slice must be a multiple of the timer-interrupt period.

As you can see, the length of the time slice is critical for RR. The shorter it is, the better the performance of RR under the response-time metric.
However, making the time slice too short is problematic: suddenly the cost of context switching will dominate overall performance.
Thus, deciding on the length of the time slice presents a trade-off to a system designer, making it long enough to amortize the cost of switching without making it so long that the system is no longer responsive.

> [!TIP]
> AMORTIZATION CAN REDUCE COSTS
>
> The general technique of amortization is commonly used in systems when there is a fixed cost to some operation.
> By incurring that cost less often (i.e., by performing the operation fewer times), the total cost to the system is reduced.

Note that the cost of context switching does not arise solely from the OS actions of saving and restoring a few registers.
When programs run, they build up a great deal of state in CPU caches, TLBs, branch predictors, and other on-chip hardware.
Switching to another job causes this state to be flushed and new state relevant to the currently-running job to be brought in, which may exact a noticeable performance cost.

More generally, any policy (such as RR) that is fair, i.e., that evenly divides the CPU among active processes on a small time scale, will perform poorly on metrics such as turnaround time.
Indeed, this is an inherent trade-off: if you are willing to be unfair, you can run shorter jobs to completion, but at the cost of response time; if you instead value fairness, response time is lowered, but at the cost of turnaround time.
This type of trade-off is common in systems.

TIP: OVERLAP ENABLES HIGHER UTILIZATION
When possible, overlap operations to maximize the utilization of systems.
Overlap is useful in many different domains, including when performing disk I/O or sending messages to remote machines;
in either case, starting the operation and then switching to other work is a good idea, and improves the overall utilization and efficiency of the system.

### MLFQ

TIP: LEARN FROM HISTORY
The multi-level feedback queue is an excellent example of a system that
learns from the past to predict the future. Such approaches are common in operating systems (and many other places in Computer Science,
including hardware branch predictors and caching algorithms). Such
approaches work when jobs have phases of behavior and are thus predictable; of course, one must be careful with such techniques, as they can
easily be wrong and drive a system to make worse decisions than they
would have with no knowledge at all.


In our treatment, the MLFQ has a number of distinct queues, each assigned a different priority level. At any given time, a job that is ready to run is on a single queue.
MLFQ uses priorities to decide which job should run at a given time: a job with higher priority (i.e., a job on a higher queue) is chosen to run.

Of course, more than one job may be on a given queue, and thus have the same priority. In this case, we will just use round-robin scheduling among those jobs.

Thus, we arrive at the first two basic rules for MLFQ:
- Rule 1: If Priority(A) > Priority(B), A runs (B doesn’t).
- Rule 2: If Priority(A) = Priority(B), A & B run in RR.


#### How To Change Priority

The key to MLFQ scheduling therefore lies in how the scheduler sets priorities.
Rather than giving a fixed priority to each job, MLFQ varies the priority of a job based on its *observed behavior*.
If, for example, a job repeatedly relinquishes the CPU while waiting for input from the keyboard, MLFQ will keep its priority high, as this is how an interactive process might behave.
If, instead, a job uses the CPU intensively for long periods of time, MLFQ will reduce its priority.
In this way, MLFQ will try to learn about processes as they run, and thus use the history of the job to predict its future behavior.

Here is our first attempt at a priorityadjustment algorithm:
- Rule 3: When a job enters the system, it is placed at the highest priority (the topmost queue).
- Rule 4a: If a job uses up an entire time slice while running, its priority is reduced (i.e., it moves down one queue).
- Rule 4b: If a job gives up the CPU before the time slice is up, it stays at the same priority level.

First, there is the problem of starvation: if there are “too many” interactive jobs in the system, they will combine to consume all CPU time, and thus long-running jobs will never receive any CPU time (they starve).

Second, a smart user could rewrite their program to game the scheduler.
Gaming the scheduler generally refers to the idea of doing something sneaky to trick the scheduler into giving you more than your fair share of the resource.

The simple idea here is to periodically boost the priority of all the jobs in system.
There are many ways to achieve this, but let’s just do something simple: throw them all in the topmost queue; hence, a new rule:
- Rule 5: After some time period S, move all the jobs in the system to the topmost queue.

Our new rule solves two problems at once. First, processes are guaranteed not to starve: by sitting in the top queue, a job will share the CPU with other high-priority jobs in a round-robin fashion, and thus eventually receive service.
Second, if a CPU-bound job has become interactive, the scheduler treats it properly once it has received the priority boost.


We now have one more problem to solve: how to prevent gaming of our scheduler?
We thus rewrite Rules 4a and 4b to the following single rule:
- Rule 4: Once a job uses up its time allotment at a given level (regardless of how many times it has given up the CPU), its priority is reduced (i.e., it moves down one queue).

> [!TIP]
> TIP: AVOID VOO-DOO CONSTANTS (OUSTERHOUT’S LAW)
>
> Avoiding voo-doo constants is a good idea whenever possible. Unfortunately, as in the example above, it is often difficult. One could try to
make the system learn a good value, but that too is not straightforward.
The frequent result: a configuration file filled with default parameter values that a seasoned administrator can tweak when something isn’t quite
working correctly. As you can imagine, these are often left unmodified,
and thus we are left to hope that the defaults work well in the field. This
tip brought to you by our old OS professor, John Ousterhout, and hence
we call it Ousterhout’s Law.


MQMS






#### Multiple Queues

Shortest Process Next

Guaranteed Scheduling

### Lottery Scheduling

The basic idea is to give processes lottery tickets for various system resources, such as CPU time.
Whenever a scheduling decision has to be made, a lottery ticket is chosen at random, and the process holding that ticket gets the resource.
When applied to CPU scheduling, the system might hold a lottery 50 times a second, with each winner getting 20 msec of CPU time as a prize.


### Fair-Share Scheduling


### Scheduling in Real-Time Systems

Real-time systems are generally categorized as hard real time, meaning there are absolute deadlines that must be met—or else!— and soft real time, meaning that missing an occasional deadline is undesirable, but nevertheless tolerable.
In both cases, real-time behavior is achieved by dividing the program into a number of processes, each of whose behavior is predictable and known in advance.
These processes are generally short lived and can run to completion in well under a second.
When an external event is detected, it is the job of the scheduler to schedule the processes in such a way that all deadlines are met.

The events that a real-time system may have to respond to can be further categorized as periodic (meaning they occur at regular intervals) or aperiodic (meaning they occur unpredictably).
A system may have to respond to multiple periodicev ent streams.
Depending on how much time each event requires for processing, handling all of them may not even be possible.


## Thread Scheduling

Scheduling in such systems differs substantially depending on whether user-level threads or kernel-level threads (or both) are supported.

Let us consider user-level threads first.
Since the kernel is not aware of the existence of threads, it operates as it always does, picking a process.
Since there are no clock interrupts to multiprogram threads, this thread may continue running as long as it wants to. If it uses up the process’ entire quantum, the kernel will select another process to run.

A major difference between user-level threads and kernel-level threads is the performance. Doing a thread switch with user-level threads takes a handful of machine instructions.
With kernel-level threads it requires a full context switch, changing the memory map and invalidating the cache, which is several orders of magnitude slower.
On the other hand, with kernel-level threads, having a thread block on I/O does not suspend the entire process as it does with user-level threads.


Another important factor is that user-level threads can employ an application-specific thread scheduler.
In general, however, application-specific thread schedulers can tune an application better than the kernel can.



## Links

- [OS processes](/docs/CS/OS/process.md)