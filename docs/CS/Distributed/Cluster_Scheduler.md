## Introduction

Cluster schedulers are an important component of modern infrastructure.
Their architecture has moved from monolithic designs to much more flexible, disaggregated and distributed designs.
Scheduling is an important topic because it directly affects the cost of operating a cluster: a poor scheduler results in low utilization, which costs money as expensive machines are left idle.
High utilization, however, is not sufficient on its own: antagonistic workloads interfere with other workloads unless the decisions are made carefully.

## Architectural Evolution

Figure 1 visualises the different approaches: a gray square corresponds to a machine, a coloured circle to a task, and a rounded rectangle with an "S" inside corresponds to a scheduler.
Arrows indicate placement decisions made by schedulers, and the three colours correspond to different workloads (e.g., web serving, batch analytics, and machine learning).

![Fig.1. Cluster scheduler architectures](./img/Cluster_Scheduler_Arch.png)

### Monolithic Scheduling

Many cluster schedulers – such as most high-performance computing (HPC) schedulers, the [Borg scheduler](/docs/CS/Distributed/Borg.md?id=scheduling), various early [Hadoop schedulers]() and the [Kubernetes scheduler](/docs/CS/Container/k8s/K8s.md?id=scheduling) – are **monolithic**.
A single scheduler process runs on one machine (e.g., the `JobTracker` in Hadoop v1, and `kube-scheduler` in Kubernetes) and assigns tasks to machines.
**All workloads are handled by the same scheduler, and all tasks run through the same scheduling logic**(see Figure 1a).
This is simple and uniform, and has led to increasingly sophisticated schedulers being developed.
As an example, see the [Paragon](http://dl.acm.org/citation.cfm?id=2451125) and [Quasar](http://dl.acm.org/citation.cfm?id=2541941) schedulers, which use a machine learning approach to avoid negative interference between workloads competing for resources.

Most clusters run different types of applications today (as opposed to, say, just [Hadoop MapReduce](/docs/CS/Java/Hadoop/MapReduce.md) jobs in the early days).
However, maintaining a single scheduler implementation that handles mixed (heterogeneous) workloads can be tricky, for several reasons:

1. It is quite reasonable to expect a scheduler to treat long-running service jobs and batch analytics jobs differently.
2. Since different applications have different needs, supporting them all keeps adding features to the scheduler, increasing the complexity of its logic and implementation.
3. The order in which the scheduler processes tasks becomes an issue: queueing effects (e.g., head-of-line blocking) and backlog can become an issue unless the scheduler is carefully designed.

Overall, this sounds like the makings of an engineering nightmare – and the never-ending lists of feature requests that scheduler maintainers receive attests to this.[1](http://www.firmament.io/blog/scheduler-architectures.html#fn1)

### Secondary Scheduling

Two-level scheduling architectures address this problem by separating the concerns of **resource allocation** and  **task placement** .
This allows the task placement logic to be tailored towards specific applications, but also maintains the ability to share the cluster between them.

The [Mesos](/docs/CS/Distributed/Cluster_Scheduler.md?id=Mesos) cluster manager pioneered this approach, and [YARN](http://dl.acm.org/citation.cfm?id=2523633) supports a limited version of it.
In Mesos, resources are *offered* to application-level schedulers (which may pick and choose from them), while YARN allows the application-level schedulers to *request*resources (and receive allocations in  return).
Figure 1b shows the general idea: workload-specific schedulers (S0–S2) interact with a resource manager that carves out dynamic partitions of the cluster resources for each workload.
This is a very flexible approach that allows for custom, workload-specific scheduling policies.

Yet, the separation of concerns in two-level architectures comes with a drawback: the application-level schedulers lose omniscience, i.e., they cannot see *all* the possible placement options any more.
Instead, they merely see those options that correspond to resources offered (Mesos) or allocated (YARN) by the resource manager component.
This has several disadvantages:

1. Priority preemption(higher priority tasks kick out lower priority ones) becomes difficult to implement: in an offer-based model,
   the resources occupied by running tasks aren't visible to the upper-level schedulers; in a request-based model, the lower-level resource manager must understand the preemption policy (which may be application-dependent).
2. Schedulers are unable to consider interference from running workloads that may degrade resource quality (e.g., "noisy neighbours" that saturate I/O bandwidth), since they cannot see them.
3. Application-specific schedulers care about many different aspects of the underlying resources, but their only means of choosing resources is the offer/request interface with the resource manager.
   This interface can easily become quite complex.

### Shared-state Scheduling

Shared-state architectures address this by moving to a semi-distributed model, in which multiple replicas of cluster state are independently updated by application-level schedulers, as shown in Figure 1c.
After the change is applied locally, the scheduler issues an optimistically concurrent transaction to update the shared cluster state.
This transaction may fail, of course: another scheduler may have made a conflicting change in the meantime.

The most prominent examples of shared-state designs are [Omega](http://dl.acm.org/citation.cfm?id=2465386) at Google, and [Apollo](https://www.usenix.org/conference/osdi14/technical-sessions/presentation/boutin) at Microsoft, as well as the [Nomad](https://www.nomadproject.io/docs/internals/scheduling.html) container scheduler by Hashicorp.
All of these materialise the *shared cluster state* in a single location: the "cell state" in Omega, the "resource monitor" in Apollo, and the "plan queue" in Nomad.
Apollo differs from the other two as its shared-state is read-only, and the scheduling transactions are submitted directly to the cluster machines.
The machines themselves check for conflicts and accept or reject the changes. This allows Apollo to make progress even if the shared-state is temporarily unavailable.

A "logical" shared-state design can also be achieved without materialising the full cluster state anywhere.
In this approach (somewhat similar to what Apollo does), each machine maintains its own state and sends updates to different interested agents such as schedulers, machine health monitors, and resource monitoring systems.
Each machine's local view of its state now forms a "shard" of the global shared-state.

However, shared-state architectures have some drawbacks, too: they must work with stale information (unlike a centralized scheduler), and may experience degraded scheduler performance under high contention (although this can apply to other architectures as well).

### Fully-distributed Scheduling

Fully-distributed architectures take the disaggregation even further: they have no coordination between schedulers at all, and use many independent schedulers to service the incoming workload, as shown in Figure 1d.
Each of these schedulers works purely with its local, partial, and often out-of-date view of the cluster.
Jobs can typically be submitted to any scheduler, and each scheduler may place tasks anywhere in the cluster.
Unlike with two-level schedulers, there are no partitions that each scheduler is responsible for. Instead, the overall schedule and resource partitioning are emergent consequences of statistical multiplexing and randomness in workload and scheduler decisions – similar to shared-state schedulers, albeit without any central control at all.

The recent distributed scheduler movement probably started with the [Sparrow](http://dl.acm.org/citation.cfm?id=2522716) paper, although the underlying concept (power of multiple random choices) [first appeared in 1996](http://www.eecs.harvard.edu/~michaelm/postscripts/mythesis.pdf).
The key premise of Sparrow is a hypothesis that the tasks we run on clusters are becoming ever shorter in duration, supported by [an argument](http://dl.acm.org/citation.cfm?id=2490497) that fine-grained tasks have many benefits.
Consequently, the authors assume that tasks are becoming more numerous, meaning that a higher decision throughput must be supported by the scheduler.
Since a single scheduler may not be able to keep up with this throughput (assumed to be a million tasks per second!), Sparrow spreads the load across many schedulers.

This makes perfect sense: and the lack of central control can be conceptually appealing, and it suits some workloads very well – more on this in a future post.
For the moment, it suffices to note that since the distributed schedulers are uncoordinated, they apply significantly simpler logic than advanced monolithic, two-level, or shared-state schedulers.
For example:

1. Distributed schedulers are typically based on a simple "slot" concept that chops each machine into *n* uniform slots, and places up to *n* parallel tasks.
   This simplifies over the fact that tasks' resource requirements are not uniform.
2. They also use worker-side queues with simple service disciplines (e.g., FIFO in Sparrow), which restricts scheduling flexibility, as the scheduler can merely choose at which machine to enqueue a task.
3. Distributed schedulers have difficulty enforcing global invariants (e.g., fairness policies or strict priority precedence), since there is no central control.
4. Since they are designed for rapid decisions based on minimal knowledge, distributed schedulers cannot support or afford complex or application-specific scheduling policies.
   Avoiding interference between tasks, for example, becomes tricky.

### Hybrid Scheduling

Hybrid architectures are a recent (mostly academic) invention that seeks to address these drawbacks of fully distributed architectures by combining them with monolithic or shared-state designs.
The way this typically works – e.g., in [Tarcil](http://dl.acm.org/citation.cfm?id=2806779), [Mercury](https://www.usenix.org/conference/atc15/technical-session/presentation/karanasos), and [Hawk](https://www.usenix.org/conference/atc15/technical-session/presentation/delgado) – is that there really are two scheduling paths: a distributed one for part of the workload (e.g., very short tasks, or low-priority batch workloads), and a centralized one for the rest.
Figure 1e illustrates this design.
The behaviour of each constituent part of a hybrid scheduler  is identical to the part's architecture described above.

## Scheduler Comparison

Figure 2 shows an overview of a selection of open-source orchestration frameworks, their architecture and the features supported by their schedulers.
At the bottom of the table, We also include closed-source systems at Google and Microsoft for reference.
The resource granularity column indicates whether the scheduler assigns tasks to fixed-size slots, or whether it allocates resources in multiple dimensions (e.g., CPU, memory, disk I/O bandwidth, network bandwidth, etc.).

![Fig.2. Cluster Scheduler Comparison](img/Cluster_Scheduler_Comparison.png)

One key aspect that helps determine an appropriate scheduler architecture is whether your cluster runs a *heterogeneous* (i.e., mixed) workload.
This is the case, for example, when combining production front-end services (e.g., load-balanced web servers and memcached) with batch data analytics (e.g., MapReduce or Spark).
Such combinations make sense in order to improve utilization, but the different applications have different scheduling needs.
In a mixed setting, a monolithic scheduler likely results in sub-optimal assignments, since the logic cannot be diversified on a per-application basis.
A two-level or shared-state scheduler will likely offer benefits here.

Most user-facing service workloads run with resource allocations sized to serve peak demand expected of each container, but in practice they typically under-utilize their allocations substantially.
**In this situation, being able to opportunistically over-subscribe the resources with lower-priority workloads (while maintaining QoS guarantees) is the key to an efficient cluster.**
Mesos is currently the only open-source system that ships support for such over-subscription, although Kubernetes has [a fairly mature proposal](http://kubernetes.io/v1.1/docs/proposals/resource-qos.html) for adding it.

Finally, specific analytics and OLAP-style applications (for example, Dremel or SparkSQL queries) can benefit from fully-distributed schedulers.
However, fully-distributed schedulers (like e.g., Sparrow) come with fairly restricted feature sets, and thus work best when the workload is homogeneous (i.e., all tasks run for roughly the same time),
set-up times are low (i.e., tasks are scheduled to long-running workers, as e.g., with MapReduce application-level tasks in YARN), and task churn is very high (i.e., many scheduling decisions must be made in a short time).
Distributed schedulers are substantially simpler than others, and do not support multiple resource dimensions, over-subscription, or re-scheduling.

## Mesos

Mesos is a thin resource sharing layer that enables fine-grained sharing across diverse cluster computing frameworks, by giving frameworks a common interface for accessing cluster resources.

Mesos introduces a distributed **two-level scheduling mechanism** called resource offers.
Mesos decides how many resources to offer each framework, while frameworks decide which resources to accept and which computations to run on them.

![Mesos architecture](./img/Mesos.png)

Mesos consists of a *master* process that manages *slave* daemons running on each cluster node, and *frameworks* that run *tasks* on these slaves.

The master implements fine-grained sharing across frameworks using *resource offers*. 
Each resource offer is a list of free resources on multiple slaves. 
The master decides how many resources to offer to each framework according to an organizational policy, such as fair sharing or priority. 
To support a diverse set of inter-framework allocation policies, Mesos lets organizations define their own policies via a pluggable allocation module.

Each framework running on Mesos consists of two components: a *scheduler* that registers with the master to be offered resources, and an *executor* process that is launched on slave nodes to run the framework’s tasks.
While the master determines how many resources to offer to each framework, the frameworks’ schedulers select which of the offered resources to use.
When a framework accepts offered resources, it passes Mesos a description of the tasks it wants to launch on them.

Pushing control to the frameworks has two benefits.

- First, it allows frameworks to implement diverse approaches to various problems in the cluster (e.g., achieving data locality, dealing with faults), and to evolve these solutions independently.
- Second, it keeps Mesos simple and minimizes the rate of change required of the system, which makes it easier to keep Mesos scalable and robust.

Since all the frameworks depend on the Mesos master, it is critical to make the master fault-tolerant.
To achieve this, we have designed the master to be soft state, so that a new master can completely reconstruct its internal state from information held by the slaves and the framework schedulers.
In particular, the master’s only state is the list of active slaves, active frameworks, and running tasks.
This information is sufficient to compute how many resources each framework is using and run the allocation policy.
We run multiple masters in a hot-standby configuration using [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) for leader election.
When the active master fails, the slaves and schedulers connect to the next elected master and repopulate its state.

Aside from handling master failures, Mesos reports node failures and executor crashes to frameworks’ schedulers.
Frameworks can then react to these failures using the policies of their choice.

Finally, to deal with scheduler failures, Mesos allows a framework to register multiple schedulers such that when one fails, another one is notified by the Mesos master to take over.
Frameworks must use their own mechanisms to share state between their schedulers.

We have identified three limitations of the distributed model:

- **Fragmentation.** 
  The wasted space due to suboptimal bin packing is bounded by the ratio between the largest task size and the node size.
- **Interdependent framework constraints.**
  It is possible to construct scenarios where, because of esoteric interdependencies between frameworks (e.g., certain tasks from two frameworks cannot be colocated), only a single global allocation of the cluster performs well.
- **Framework complexity.**
  Using resource offers may make framework scheduling more complex.
  Mesos must use frameworks preferences to decide which offers to accept.
  Many scheduling policies for existing frameworks are online algorithms, because frameworks cannot predict task times and must be able to handle failures and stragglers.



## Omega

## Apollo

- To balance scalability and scheduling quality, Apollo adopts a distributed and (loosely) coordinated scheduling framework, in which independent scheduling decisions are made in an optimistic and coordinated manner by incorporating synchronized cluster utilization information.
- To achieve high-quality scheduling decisions, Apollo schedules each task on a server that minimizes the task completion time.
  The estimation model incorporates a variety of factors and allows a scheduler to perform a weighted decision, rather than solely considering data locality or server load.
  The data parallel nature of computation allows Apollo to refine the estimates of task execution time continuously based on observed runtime statistics from similar tasks during job execution.
- To supply individual schedulers with cluster information, Apollo introduces a lightweight hardwareindependent mechanism to advertise load on servers.
  When combined with a local task queue on each server, the mechanism provides a near-future view of resource availability on all the servers, which is used by the schedulers in decision making.
- To cope with unexpected cluster dynamics, suboptimal estimations, and other abnormal runtime behaviors, which are facts of life in large-scale clusters, Apollo is made robust through a series of correction mechanisms that dynamically adjust and rectify suboptimal decisions at runtime.
  We present a unique deferred correction mechanism that allows resolving conflicts between independent schedulers only if they have a significant impact, and show that such an approach works well in practice.
- To drive high cluster utilization while maintaining low job latencies, Apollo introduces opportunistic scheduling, which effectively creates two classes of tasks: regular tasks and opportunistic tasks.
  Apollo ensures low latency for regular tasks, while using the opportunistic tasks for high utilization to fill in the slack left by regular tasks.
- To ensure no service disruption or performance regression when we roll out Apollo to replace a previous scheduler deployed in production, we designed Apollo to support staged rollout to production clusters and validation at scale.
  Those constraints have received little attention in research, but are nevertheless crucial in practice and we share our experiences in achieving those demanding goals.

Below figure provides an overview of Apollo’s architecture.
A Job Manager (JM), also called a scheduler, is assigned to manage the life cycle of each job.
The global cluster load information used by each JM is provided through the cooperation of two additional entities in the Apollo framework: a Resource Monitor (RM) for each cluster and a Process Node (PN) on each server.
A PN process running on each server is responsible for managing the local resources on that server and performing local scheduling, while the RM aggregates load information from PNs across the cluster continuously,
providing a global view of the cluster status for each JM to make informed scheduling decisions.

![Apollo Architecture](./img/Apollo.png)

While treated as a single logical entity, the RM can be implemented physically in different configurations
with different mechanisms, as it essentially addresses the well-studied problem of monitoring dynamically changing state of a collection of distributed resources at a large scale.
For example, it can use a tree hierarchy or a directory service with an eventually consistent gossip protocol.
Apollo’s architecture can accommodate any of such configurations. We implemented the RM in a master-slave configuration using [Paxos](/docs/CS/Distributed/Paxos.md).
The RM is never on the performance critical path: Apollo can continue to make scheduling decisions (at a degraded quality) even when the RM is temporarily unavailable, for example, during a transient master-slave switch due to a machine failure.
In addition, once a task is scheduled to a PN, the JM obtains up-to-date load information directly from the PN via frequent status updates.

To better predict resource utilization in the near future and to optimize scheduling quality,
each PN maintains a local queue of tasks assigned to the server and advertises its future resource availability in the form of a wait-time matrix inferred from the queue.
Apollo thereby adopts an estimation-based approach to making task scheduling decisions.
Specifically, Apollo considers the wait-time matrices, aggregated by the RM, together with the individual characteristics of tasks to be scheduled, such as the location of inputs.
However, cluster dynamics pose many challenges in practice; for example, the wait-time matrices might be stale, estimates might be suboptimal, and the cluster environment might sometimes be unpredictable.
Apollo therefore incorporates correction mechanisms for robustness and dynamically adjusts scheduling decisions at runtime.
Finally, there is an inherent tension between providing guaranteed resources to jobs (e.g., to ensure SLAs) and achieving high cluster utilization, because both the load on a cluster and the resource needs of a job fluctuate constantly.
Apollo resolves this tension through opportunistic scheduling, which creates secondclass tasks to use idle resources.

## Firmament

Firmament achieves low latency by using multiple MCMF algorithms, by solving the problem incrementally, and via problem-specific optimizations.

Below figure gives an overview of the Firmament scheduler architecture.

![Firmament Architecture](./img/Firmament.png)

Firmament, like Quincy, models the scheduling problem as a min-cost max-flow (MCMF) optimization over a flow network.
The flow network is a directed graph whose structure is defined by the scheduling policy.
In response to events and monitoring information, the flow network is modified according to the scheduling policy, and submitted to an MCMF solver to find an optimal (i.e., min-cost) flow.
Once the solver completes, it returns the optimal flow, from which Firmament extracts the implied task placements.
In the following, we first explain the basic structure of the flow network, and then discuss how to make the solver fast.

### Scheduling policies

- Load-spreading policy
- Quincy policy
- Network-aware policy

## References

1. [The evolution of cluster scheduler architectures](https://www.codetd.com/en/article/14158427)
2. [Omega: flexible, scalable schedulers for large compute clusters](https://web.eecs.umich.edu/~mosharaf/Readings/Omega.pdf)
3. [Apollo: Scalable and Coordinated Scheduling for Cloud-Scale Computing](https://www.usenix.org/system/files/conference/osdi14/osdi14-paper-boutin_0.pdf)
4. [Firmament: Fast, Centralized Cluster Scheduling at Scale](https://www.usenix.org/system/files/conference/osdi16/osdi16-gog.pdf)
5. [Mesos: A Platform for Fine-Grained Resource Sharing in the Data Center](http://static.usenix.org/events/nsdi11/tech/full_papers/Hindman_new.pdf)