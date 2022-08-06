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

## Links

- [Hadoop](/docs/CS/Java/Hadoop/Hadoop.md)
- [GFS](/docs/CS/Distributed/GFS.md)

## References

1. [HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html)
2. [Apache Hadoop Goes Realtime at Facebook](https://www.cse.fau.edu/~xqzhu/courses/Resources/Apachehadoop.pdf)
2. [HDFS scalability: the limits to growth](http://c59951.r51.cf2.rackcdn.com/5424-1908-shvachko.pdf)