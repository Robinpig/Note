## Introduction

Hadoop 分布式文件系统（HDFS）是一个设计运行在商用硬件上的分布式文件系统。
它与现有的分布式文件系统有许多相似之处，但与其他分布式文件系统的差异也很显著。
HDFS 具有高容错性，专为部署在低成本硬件上而设计。
HDFS 为应用程序数据提供高吞吐量访问，适用于拥有大规模数据集的应用程序。
HDFS 放宽了部分 POSIX 要求，以支持对文件系统数据的流式访问。

HDFS 应用程序需要文件的一次写入多次读取访问模型。
文件一旦创建、写入并关闭后，除了追加和截断外不需要更改。
支持在文件末尾追加内容，但不能在任意位置更新。
这一假设简化了数据一致性问题，并实现了高吞吐量数据访问。
MapReduce 应用或网络爬虫应用非常适合该模型。

## Architecture

HDFS 采用主/从架构。
一个 HDFS 集群包含一个 NameNode（管理文件系统命名空间并调节客户端对文件访问的主服务器）和多个 DataNode（通常在集群中的每个节点上运行一个，管理其所运行节点的存储）。
HDFS 暴露文件系统命名空间，允许用户数据以文件形式存储。
在内部，一个文件被分割成一个或多个块，这些块存储在一组 DataNode 上。
NameNode 执行文件系统命名空间操作，如打开、关闭、重命名文件和目录，并确定块到 DataNode 的映射。
DataNode 负责处理来自文件系统客户端的读写请求，并根据 NameNode 的指令执行块的创建、删除和复制。

![HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/images/hdfsarchitecture.png)

NameNode 和 DataNode 是设计在商用机器上运行的软件。
这些机器通常运行 GNU/Linux 操作系统。
HDFS 使用 Java 语言构建；任何支持 Java 的机器都可以运行 NameNode 或 DataNode 软件。
使用高度可移植的 Java 语言意味着 HDFS 可以部署在各种机器上。
典型部署中有一台专用机器仅运行 NameNode 软件，集群中的其他机器各运行一个 DataNode 实例。
该架构不排除在同一台机器上运行多个 DataNode，但在实际部署中很少出现。

集群中存在单个 NameNode 大大简化了系统架构。
NameNode 是所有 HDFS 元数据的仲裁者和存储库。
系统的设计保证了用户数据从不会流经 NameNode。

### Namespace

HDFS 支持传统的分层文件组织。
用户或应用程序可以创建目录并在其中存储文件。
文件系统命名空间层次结构与大多数现有文件系统类似；用户可以创建和删除文件、将文件从一个目录移动到另一个目录或重命名文件。
HDFS 尚未实现用户配额，也不支持硬链接或软链接。
不过，HDFS 架构并不排除实现这些功能。

NameNode 维护文件系统命名空间。
文件系统命名空间或其属性的任何更改都由 NameNode 记录。
应用程序可以指定 HDFS 应维护的文件副本数，这个数字称为文件的复制因子。
这些信息由 NameNode 存储。

## Replication

HDFS 设计用于在大型集群中的多台机器上可靠地存储非常大的文件。
它将每个文件存储为一系列块；文件中除最后一个块外的所有块大小相同。
文件的块会被复制以实现容错。
块大小和复制因子可按文件配置。
应用程序可以指定文件的副本数。
复制因子可以在文件创建时指定，之后也可以修改。
HDFS 中的文件一次写入，且任何时候都只有一个写入者。

NameNode 负责所有关于块复制的决策。
它会定期从集群中的每个 DataNode 接收心跳和块报告。
收到心跳表示 DataNode 正常运行。
块报告包含 DataNode 上所有块的列表。

## Metadata

HDFS 命名空间由 NameNode 存储。
NameNode 使用一个称为 EditLog 的事务日志来持久记录文件系统元数据的每次更改。
例如，在 HDFS 中创建新文件会导致 NameNode 在 EditLog 中插入一条记录；同样，更改文件的复制因子也会在 EditLog 中插入新记录。
NameNode 使用其本地主机的 OS 文件系统中的一个文件来存储 EditLog。
整个文件系统命名空间，包括块到文件的映射和文件系统属性，都存储在一个名为 FsImage 的文件中。
FsImage 也存储在 NameNode 的本地文件系统中。

NameNode 在内存中保存整个文件系统命名空间和文件 Blockmap 的映像。
这一关键元数据项设计得紧凑，使得拥有 4GB RAM 的 NameNode 足以支持大量文件和目录。
当 NameNode 启动时，它从磁盘读取 FsImage 和 EditLog，将 EditLog 中的所有事务应用到内存中的 FsImage 表示，然后将这个新版本刷新到磁盘上的新 FsImage。
之后可以截断旧的 EditLog，因为其事务已应用于持久化的 FsImage。
这个过程称为 checkpoint。
在当前实现中，checkpoint 仅在 NameNode 启动时发生，未来计划支持定期 checkpoint。

DataNode 将 HDFS 数据存储在其本地文件系统的文件中。
DataNode 对 HDFS 文件没有概念，它将 HDFS 数据的每个块存储在本地文件系统的单独文件中。
DataNode 不会在同一目录中创建所有文件，而是使用启发式方法确定每个目录的最佳文件数并适当创建子目录。
将所有本地文件放在同一目录中并不理想，因为本地文件系统可能无法有效支持单个目录中的大量文件。
当 DataNode 启动时，它会扫描本地文件系统，生成与每个本地文件对应的所有 HDFS 数据块列表，并将此报告发送给 NameNode：这就是 Blockreport。

## Links

- [Hadoop](/docs/CS/Java/Hadoop/Hadoop.md)
- [GFS](/docs/CS/Distributed/GFS.md)

## References

1. [HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html)
2. [Apache Hadoop Goes Realtime at Facebook](https://www.cse.fau.edu/~xqzhu/courses/Resources/Apachehadoop.pdf)
3. [HDFS scalability: the limits to growth](http://c59951.r51.cf2.rackcdn.com/5424-1908-shvachko.pdf)
4. [The Hadoop Distributed File System](https://storageconference.us/2010/Papers/MSST/Shvachko.pdf)
5. [The Hadoop Distributed File System: Architecture and Design](https://www.ics.uci.edu/~cs237/reading/Hadoop.pdf)
