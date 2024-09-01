## Introduction

The Hadoop Distributed File System (HDFS) is a distributed file system designed to run on commodity hardware. It has many similarities with existing distributed file systems.
However, the differences from other distributed file systems are significant.
HDFS is highly fault-tolerant and is designed to be deployed on low-cost hardware.
HDFS provides high throughput access to application data and is suitable for applications that have large data sets.
HDFS relaxes a few POSIX requirements to enable streaming access to file system data.

HDFS applications need a write-once-read-many access model for files.
A file once created, written, and closed need not be changed except for appends and truncates.
Appending the content to the end of the files is supported but cannot be updated at arbitrary point.
This assumption simplifies data coherency issues and enables high throughput data access.
A MapReduce application or a web crawler application fits perfectly with this model.

## Architecture

HDFS has a master/slave architecture. An HDFS cluster consists of a single NameNode, a master server that manages the file system namespace and regulates access to files by clients.
In addition, there are a number of DataNodes, usually one per node in the cluster, which manage storage attached to the nodes that they run on.
HDFS exposes a file system namespace and allows user data to be stored in files. Internally, a file is split into one or more blocks and these blocks are stored in a set of DataNodes.
The NameNode executes file system namespace operations like opening, closing, and renaming files and directories. It also determines the mapping of blocks to DataNodes.
The DataNodes are responsible for serving read and write requests from the file system’s clients. The DataNodes also perform block creation, deletion, and replication upon instruction from the NameNode.

![HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/images/hdfsarchitecture.png)

The NameNode and DataNode are pieces of software designed to run on commodity machines.
These machines typically run a GNU/Linux operating system (OS).
HDFS is built using the Java language; any machine that supports Java can run the NameNode or the DataNode software.
Usage of the highly portable Java language means that HDFS can be deployed on a wide range of machines.
A typical deployment has a dedicated machine that runs only the NameNode software.
Each of the other machines in the cluster runs one instance of the DataNode software.
The architecture does not preclude running multiple DataNodes on the same machine but in a real deployment that is rarely the case.

The existence of a single NameNode in a cluster greatly simplifies the architecture of the system.
The NameNode is the arbitrator and repository for all HDFS metadata.
The system is designed in such a way that user data never flows through the NameNode.

### Namespace

HDFS supports a traditional hierarchical file organization. A user or an application can create directories and store files inside these directories.
The file system namespace hierarchy is similar to most other existing file systems; one can create and remove files, move a file from one directory to another, or rename a file.
HDFS does not yet implement user quotas. HDFS does not support hard links or soft links. However, the HDFS architecture does not preclude implementing these features.

The NameNode maintains the file system namespace.
Any change to the file system namespace or its properties is recorded by the NameNode.
An application can specify the number of replicas of a file that should be maintained by HDFS.
The number of copies of a file is called the replication factor of that file.
This information is stored by the NameNode.

## Replication

HDFS is designed to reliably store very large files across machines in a large cluster. It stores each file as a sequence of blocks; all blocks in a file except the last block are the same size.
The blocks of a file are replicated for fault tolerance.
The block size and replication factor are configurable per file.
An application can specify the number of replicas of a file.
The replication factor can be specified at file creation time and can be changed later. F
iles in HDFS are write-once and have strictly one writer at any time.

The NameNode makes all decisions regarding replication of blocks. It periodically receives a Heartbeat and a Blockreport from each of the DataNodes in the cluster.
Receipt of a Heartbeat implies that the DataNode is functioning properly. A Blockreport contains a list of all blocks on a DataNode.

## Metadata

The HDFS namespace is stored by the NameNode. The NameNode uses a transaction log called the EditLog to persistently record every change that occurs to file system metadata.
For example, creating a new file in HDFS causes the NameNode to insert a record into the EditLog indicating this.
Similarly, changing the replication factor of a file causes a new record to be inserted into the EditLog.
The NameNode uses a file in its local host OS file system to store the EditLog.
The entire file system namespace, including the mapping of blocks to files and file system properties, is stored in a file called the FsImage.
The FsImage is stored as a file in the NameNode’s local file system too.

The NameNode keeps an image of the entire file system namespace and file Blockmap in memory.
This key metadata item is designed to be compact, such that a NameNode with 4 GB of RAM is plenty to support a huge number of files and directories.
When the NameNode starts up, it reads the FsImage and EditLog from disk, applies all the transactions from the EditLog to the in-memory representation of the FsImage, and flushes out this new version into a new FsImage on disk.
It can then truncate the old EditLog because its transactions have been applied to the persistent FsImage.
This process is called a checkpoint. In the current implementation, a checkpoint only occurs when the NameNode starts up.
Work is in progress to support periodic checkpointing in the near future.

The DataNode stores HDFS data in files in its local file system.
The DataNode has no knowledge about HDFS files.
It stores each block of HDFS data in a separate file in its local file system.
The DataNode does not create all files in the same directory.
Instead, it uses a heuristic to determine the optimal number of files per directory and creates subdirectories appropriately.
It is not optimal to create all local files in the same directory because the local file system might not be able to efficiently support a huge number of files in a single directory.
When a DataNode starts up, it scans through its local file system, generates a list of all HDFS data blocks that correspond to each of these local files and sends this report to the NameNode: this is the Blockreport.

## Links

- [Hadoop](/docs/CS/Java/Hadoop/Hadoop.md)
- [GFS](/docs/CS/Distributed/GFS.md)

## References

1. [HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html)
2. [Apache Hadoop Goes Realtime at Facebook](https://www.cse.fau.edu/~xqzhu/courses/Resources/Apachehadoop.pdf)
3. [HDFS scalability: the limits to growth](http://c59951.r51.cf2.rackcdn.com/5424-1908-shvachko.pdf)
4. [The Hadoop Distributed File System](https://storageconference.us/2010/Papers/MSST/Shvachko.pdf)
5. [The Hadoop Distributed File System: Architecture and Design](https://www.ics.uci.edu/~cs237/reading/Hadoop.pdf)
