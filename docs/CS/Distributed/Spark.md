## Introduction

Spark supports applications with working sets while providing similar scalability and fault tolerance properties to MapReduce.

Spark is implemented in [Scala](), a statically typed high-level programming language for the Java VM, and exposes a functional programming interface similar to DryadLINQ.

## Programming Model

Spark provides two main abstractions for parallel programming: *resilient distributed datasets* and *parallel operations* on these datasets (invoked by passing a function to apply on a dataset).
In addition, Spark supports two restricted types of *shared variables* that can be used in functions running on the cluster.

### RDD

A resilient distributed dataset (RDD) is a read-only collection of objects partitioned across a set of machines that can be rebuilt if a partition is lost.
The elements of an RDD need not exist in physical storage; instead, a handle to an RDD contains enough information to compute the RDD starting from data in reliable storage.
This means that RDDs can always be reconstructed if nodes fail.

In Spark, each RDD is represented by a Scala object.
Spark lets programmers construct RDDs in four ways:

- From a *file* in a shared file system, such as the Hadoop Distributed File System (HDFS).
- By “*parallelizing*” a Scala collection (e.g., an array) in the driver program, which means dividing it into a number of slices that will be sent to multiple nodes.
- By *transforming* an existing RDD.
- By changing the *persistence* of an existing RDD.

### Parallel Operations

Several parallel operations can be performed on RDDs:

- *reduce*
- *collect*
- *foreach*

### Shared Variables

Programmers invoke operations like map, filter and reduce by passing closures (functions) to Spark.
As is typical in functional programming, these closures can refer to variables in the scope where they are created.
Normally, when Spark runs a closure on a worker node, these variables are copied to the worker.
However, Spark also lets programmers create two restricted types of shared variables to support two simple but common usage patterns:

- *Broadcast variables*:
  If a large read-only piece of data(e.g., a lookup table) is used in multiple parallel operations, it is preferable to distribute it to the workers only once instead of packaging it with every closure.
  Spark lets the programmer create a “broadcast variable” object that wraps the value and ensures that it is only copied to each worker once.
- *Accumulators*:
  These are variables that workers can only “add” to using an associative operation, and that only the driver can read.
  They can be used to implement counters as in MapReduce and to provide a more imperative syntax for parallel sums.
  Accumulators can be defined for any type that has an “add” operation and a “zero” value. Due to their “add-only” semantics, they are easy to make fault-tolerant.

## Architecture

Spark is built on top of [Mesos](/docs/CS/Distributed/Cluster_Scheduler.md?id=Mesos), a “cluster operating system” that lets multiple parallel applications share a cluster in a fine-grained manner and provides an API for applications to launch tasks on a cluster.
This allows Spark to run alongside existing cluster computing frameworks, such as Mesos ports of Hadoop and MPI, and share data with them.
In addition, building on Mesos greatly reduced the programming effort that had to go into Spark.

The core of Spark is the implementation of resilient distributed datasets.
Each
dataset object contains a pointer to its parent and information about how the parent was transformed.
Internally, each RDD object implements the same simple interface, which consists of three operations:

- *getPartitions*, which returns a list of partition IDs.
- *getIterator(partition)*, which iterates over a partition.
- *getPreferredLocations(partition)*, which is used for task scheduling to achieve data locality.

When a parallel operation is invoked on a dataset, Spark creates a task to process each partition of the dataset and sends these tasks to worker nodes.
We try to send each task to one of its preferred locations using a technique called delay scheduling.
Once launched on a worker, each task calls getIterator to start reading its partition.

## Links

- [Mesos](/docs/CS/Distributed/Cluster_Scheduler.md?id=Mesos)
- [MapReduce](/docs/CS/Distributed/MapReduce.md)

## References

1. [Spark: Cluster Computing with Working Sets](https://people.csail.mit.edu/matei/papers/2010/hotcloud_spark.pdf)
