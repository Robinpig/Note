## Introduction

本页是 `docs/CS/` 的**总纲**，回答两件事：计算机科学的各门学科分别研究什么，以及该按什么顺序往下读。

<div class="kb-home">

内容分三层：**Learning Paths** 给三条主干路线；**Topic Map** 是入口卡片速查；其后的**分组学科小节**逐门说明研究对象、核心子主题与枢纽页；最后的 **Directory** 展开全部主题目录与速查页。站点首页只做七大领域的总入口，CS 的主题清单**只在本页维护一份**。

## Learning Paths

<div class="kb-grid">

<div class="kb-card">

### Kernel Track

<div class="kb-route">

[Operating System](/docs/CS/OS/OS.md) → [Linux](/docs/CS/OS/Linux/Linux.md) → [Process](/docs/CS/OS/Linux/proc/process.md) → [Scheduler](/docs/CS/OS/Linux/proc/fair.md) → [Locks](/docs/CS/OS/Linux/Lock/README.md) → [Memory Management](/docs/CS/OS/Linux/mm/README.md)

</div>

从 `task_struct` 一路读到调度器、同步原语与内存管理，全程对照内核源码。

</div>

<div class="kb-card">

### Backend Track

<div class="kb-route">

[Computer Network](/docs/CS/CN/CN.md) → [Database](/docs/CS/DB/DB.md) → [Distributed Systems](/docs/CS/Distributed/Distributed.md) → [Message Queue](/docs/CS/MQ/MQ.md) → [Cloud Native](/docs/CS/Container/Container.md)

</div>

服务端工程师的主干路径，覆盖协议、存储、一致性到部署。

</div>

<div class="kb-card">

### AI Track

<div class="kb-route">

[Artificial Intelligence](/docs/CS/AI/AI.md) → [LLM](/docs/CS/AI/LLM/LLM.md) → [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) → [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) → [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)

</div>

从机器学习基础到 LLM 应用与 Agent 工程实践。

</div>

</div>

## Topic Map

<div class="kb-grid kb-grid-sm">

<div class="kb-card">

### [Operating System](/docs/CS/OS/OS.md)

进程、调度、内存、文件系统、同步原语

</div>

<div class="kb-card">

### [Database](/docs/CS/DB/DB.md)

索引与存储引擎、事务与隔离级别、分布式数据库

</div>

<div class="kb-card">

### [Frameworks and Middleware](/docs/CS/Framework/README.md)

Spring、Netty、Tomcat、Dubbo、ZooKeeper、etcd、Consul，按技术栈分层导航

</div>

<div class="kb-card">

### [Algorithms](/docs/CS/Algorithms/Algorithms.md)

数据结构、复杂度分析、经典题型

</div>

<div class="kb-card">

### [Distributed Systems](/docs/CS/Distributed/Distributed.md)

一致性、共识、分布式事务、追踪与可观测性

</div>

<div class="kb-card">

### [Computer Network](/docs/CS/CN/CN.md)

TCP/IP、HTTP、DNS、Socket 与高性能 IO

</div>

<div class="kb-card">

### [Software Engineering](/docs/CS/SE/Engineering.md)

架构、并发、缓存、限流熔断、工程实践

</div>

<div class="kb-card">

### [Artificial Intelligence](/docs/CS/AI/AI.md)

LLM、Agent、RAG、MCP 与机器学习基础

</div>

<div class="kb-card">

### [Message Queue](/docs/CS/MQ/MQ.md)

Kafka、RocketMQ、Pulsar 与消息语义

</div>

<div class="kb-card">

### [Cloud Native](/docs/CS/Container/Container.md)

Docker、Kubernetes、CNI、Ingress、Helm

</div>

<div class="kb-card">

### [Java and JVM](/docs/CS/Java/JDK/JDK.md)

JDK 源码、集合与并发、虚拟线程、内存与 GC

</div>

<div class="kb-card">

### [Programming Languages](/docs/CS/Languages.md)

各语言入口、特性速览与适用场景的横向对比

</div>

</div>

## Theory and Foundations

### Algorithms and Data Structures

算法研究**如何把问题变成可执行的步骤、这些步骤要花多少资源**；数据结构研究**如何组织数据，才能让这些步骤花得少**。两者共用同一套度量语言——渐进复杂度。

入口 [Algorithms](/docs/CS/Algorithms/Algorithms.md)：[Data Structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)（线性表、树、堆、图、页置换）与[Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)是主干，按范式展开 [Dynamic Programming](/docs/CS/Algorithms/DP/DP.md)、[Greedy](/docs/CS/Algorithms/Greedy.md)、[Divide and Conquer](/docs/CS/Algorithms/Divide-and-Conquer.md)、[Backtracking](/docs/CS/Algorithms/Backtracking.md)、[Randomized](/docs/CS/Algorithms/Randomized.md)、[Amortized Analysis](/docs/CS/Algorithms/Amortized.md)，另有 [Sort](/docs/CS/Algorithms/sort.md)、[Hash](/docs/CS/Algorithms/hash.md) 与工程向专题（[LRU](/docs/CS/Algorithms/LRU.md)、[PageRank](/docs/CS/Algorithms/PageRank.md)、[HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md)、[Timing Wheel](/docs/CS/Algorithms/TimingWheel.md)）。

### Computability and Complexity

先问**能不能算**，再问**算得快不快**。图灵机把「算法」形式化，Church-Turing 论题给出「有效可计算」的判据，停机问题则证明存在**判定不了的性质**——这就是为什么编译器和静态分析只能做保守近似。可判定问题内部再按资源分层为 P、NP 与 NP-complete。

见 [Computability](/docs/CS/Algorithms/Computability.md) 与 [NP](/docs/CS/Algorithms/NP.md)。离散与数理逻辑基础（集合、关系、一阶逻辑、可计算性）在 [Mathematics](/docs/Mathematics/Mathematics.md)。

### Programming Languages

语言研究**如何把计算表达得既被人读懂、又被机器执行**：类型系统、内存模型、并发原语、运行时与工具链。判断两门语言是否等价只看图灵完备性，真正的差异在表达力与运行特性——横向对比统一见 [Languages](/docs/CS/Languages.md)。

本库展开最深的三门：**Java** 的语言入口与目录地图是 [Java](/docs/CS/Java/Java.md)（OOP、连接池、诊断工具，以及 [Guava_Cache](/docs/CS/Java/Guava_Cache.md)、[Jackson](/docs/CS/Java/Jackson.md)、[Disruptor](/docs/CS/Java/Disruptor.md)、[JUnit](/docs/CS/Java/JUnit.md) 等生态库），JDK 与 JVM 机制从 [JDK](/docs/CS/Java/JDK/JDK.md) 读起（[Loom](/docs/CS/Java/JDK/Loom.md)、[Valhalla](/docs/CS/Java/JDK/Valhalla.md)、[sche](/docs/CS/Java/JDK/sche.md)、[ASM](/docs/CS/Java/JDK/ASM.md)、[Agent](/docs/CS/Java/JDK/Agent.md)、[Upgrade](/docs/CS/Java/JDK/Upgrade.md)）；**Go** 从 [Go](/docs/CS/Go/Go.md) 进入，重点是运行时：[runtime](/docs/CS/Go/runtime.md)、[GC](/docs/CS/Go/GC.md)、[sysmon](/docs/CS/Go/sysmon.md)、[netpoller](/docs/CS/Go/netpoller.md)、[timer](/docs/CS/Go/timer.md)、[Pointer](/docs/CS/Go/Pointer.md)、[Reflection](/docs/CS/Go/Reflection.md)、[pprof](/docs/CS/Go/pprof.md)；**Python** 从 [Python](/docs/CS/Python/Python.md) 进入，同样以运行时为骨架——[GIL](/docs/CS/Python/GIL.md)（含 3.13/3.14 的 free-threading）、[Memory](/docs/CS/Python/Memory.md)（引用计数与分代回收）、[Bytecode](/docs/CS/Python/Bytecode.md)（特化解释器与实验性 JIT）、[Import](/docs/CS/Python/Import.md)、[Data Model](/docs/CS/Python/Data_Model.md)、[Asyncio](/docs/CS/Python/Asyncio.md)、[Concurrency](/docs/CS/Python/Concurrency.md)，工程层是 [Typing](/docs/CS/Python/Typing.md)、[Packaging](/docs/CS/Python/Packaging.md)、[Exceptions](/docs/CS/Python/Exceptions.md)、[Performance](/docs/CS/Python/Performance.md)，生态见 [Ecosystem](/docs/CS/Python/Ecosystem.md) 与 [NumPy](/docs/CS/Python/NumPy.md)。C / [C++](/docs/CS/C++/C++.md) / [Rust](/docs/CS/Rust/Rust.md) / [Scala](/docs/CS/Scala/Scala.md) / [TypeScript](/docs/CS/TypeScript/TypeScript.md) / [Dart](/docs/CS/Dart/Dart.md) 各有一页，跨端见 [Flutter](/docs/CS/Flutter.md)。

## Systems and Low Level

### Computer Organization

组成原理讲**程序为什么在硬件上跑出这个速度**：逻辑门与指令集、寻址方式、流水线与分支预测（[BranchPrediction](/docs/CS/OS/BranchPrediction.md)）、异常与中断、以及由寄存器到外存的**存储层次**——缓存一致性与局部性决定了上层所有性能优化的上限。入口 [CO](/docs/CS/CO/CO.md)，系统视角的入门读法见 [CSAPP](/docs/CS/OS/CSAPP.md)；动手跑指令与启动实验用 [Bochs](/docs/CS/OS/Bochs.md) 与 [qemu](/docs/CS/OS/qemu.md)。

### Operating System

操作系统是硬件之上、应用之下的**资源管理者**，主线只有五条：进程与调度、内存管理、文件系统、I/O、同步原语，再加从固件到 `init` 的启动链。通用理论见 [OS](/docs/CS/OS/OS.md)（[process](/docs/CS/OS/process.md)、[scheduling](/docs/CS/OS/scheduling.md)、[memory](/docs/CS/OS/memory.md)、[file](/docs/CS/OS/file.md)、[IO](/docs/CS/OS/IO.md)、[Deadlocks](/docs/CS/OS/Deadlocks.md)、[VM](/docs/CS/OS/VM.md)、[Parallel](/docs/CS/OS/Parallel.md)）。

本库以 Linux 内核为主线对照源码，[Linux](/docs/CS/OS/Linux/Linux.md) 是该子树**唯一枢纽**，各子系统有独立地图：[proc](/docs/CS/OS/Linux/proc/README.md)、[mm](/docs/CS/OS/Linux/mm/README.md)、[fs](/docs/CS/OS/Linux/fs/README.md)、[net](/docs/CS/OS/Linux/net/README.md)、[IO](/docs/CS/OS/Linux/IO/README.md)、[Lock](/docs/CS/OS/Linux/Lock/README.md)、[boot](/docs/CS/OS/Linux/boot/README.md)、[dev](/docs/CS/OS/Linux/dev/README.md)、[struct](/docs/CS/OS/Linux/struct/README.md)、[module](/docs/CS/OS/Linux/module/README.md)、[cgroup](/docs/CS/OS/Linux/cgroup/README.md)、[PM](/docs/CS/OS/Linux/PM/README.md)、[Distribution](/docs/CS/OS/Linux/Distribution/README.md)。横切机制留在根目录：[Interrupt](/docs/CS/OS/Linux/Interrupt.md)、[Calls](/docs/CS/OS/Linux/Calls.md)、[timer](/docs/CS/OS/Linux/timer.md)、[workqueue](/docs/CS/OS/Linux/workqueue.md)、[namespace](/docs/CS/OS/Linux/namespace.md)、[Swap](/docs/CS/OS/Linux/Swap.md)、[ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)、[KVM](/docs/CS/OS/Linux/KVM.md)、[performance](/docs/CS/OS/Linux/performance.md)、[SELinux](/docs/CS/OS/Linux/SELinux.md)、[build](/docs/CS/OS/Linux/build.md)。

其余血统各有入口：[Unix](/docs/CS/OS/unix/Unix.md)、[Windows](/docs/CS/OS/Windows/Windows.md)、[mac](/docs/CS/OS/mac/mac.md)、[Android](/docs/CS/OS/Android/Android.md)、[Fuchsia](/docs/CS/OS/Fuchsia/Fuchsia.md)，教学与合作内核 [xv6](/docs/CS/OS/xv6/xv6.md)、[rCore](/docs/CS/OS/rCore.md)、[osask](/docs/CS/OS/osask.md)；早期版本 [0.11](/docs/CS/OS/Linux/0.11.md) 是现代内核的直系祖先。

### Compiler and Toolchain

编译器把源码逐层降到 IR、机器码与可执行文件，链接与加载再把它们变成进程：阶段与优化见 [Compiler](/docs/CS/Compiler/Compiler.md)，工具链见 [GCC](/docs/CS/Compiler/GCC.md)，产物格式见 [ELF](/docs/CS/Compiler/ELF.md)，最低层的表达是 [assembly](/docs/CS/assembly/assembly.md)。程序运行时的真实内存由分配器决定，见 [memory](/docs/CS/memory/memory.md)（[GC](/docs/CS/memory/GC.md)、[jemalloc](/docs/CS/memory/jemalloc.md)）与 [glibc](/docs/CS/C/glibc.md)；工具与许可证背景见 [GNU](/docs/CS/GNU/GNU.md)。这条链与 [Computability](/docs/CS/Algorithms/Computability.md) 相接：语义等价性不可判定，所以优化必须保守。

## Networks and Data

### Computer Network

计算机网络是**共享位于网络节点上的资源**的一组计算机，工程上表现为一个分层协议栈：链路与 IP 层（[IP](/docs/CS/CN/IP.md)、[ARP](/docs/CS/CN/ARP.md)、[ICMP](/docs/CS/CN/ICMP.md)、[DHCP](/docs/CS/CN/DHCP.md)）、传输层（UDP、[SCTP](/docs/CS/CN/SCTP.md)、可靠传输与拥塞控制）、应用层（[DNS](/docs/CS/CN/DNS.md)、[WebSocket](/docs/CS/CN/WebSocket.md)、[TLS](/docs/CS/CN/TLS.md)、[SMTP](/docs/CS/CN/SMTP.md)、[FTP](/docs/CS/CN/FTP.md)、[MIME](/docs/CS/CN/MIME.md)）。

编程侧是 [Socket](/docs/CS/CN/Socket.md) 与高性能 IO：[C10k](/docs/CS/CN/C10k.md)、[MultiIO](/docs/CS/CN/MultiIO.md)、[VPN](/docs/CS/CN/VPN.md)；工程实现见 [Pingora](/docs/CS/CN/Pingora.md) 与 [Caddy](/docs/CS/CN/Caddy.md)，对抗面见 [Attack](/docs/CS/CN/Attack.md) 与 [Security](/docs/CS/CN/Security.md)。入口 [CN](/docs/CS/CN/CN.md)，内核侧协议栈实现见 [net](/docs/CS/OS/Linux/net/README.md)。

### Database

数据库研究**存得下、找得快、改得安全**：存储引擎与索引决定读写路径，事务与隔离级别决定并发下的正确性，复制与分片决定规模上限。不同用途差别极大——热数据、冷存储、分析查询、键值访问、时序与大对象各有各的答案，选型方法与全景见 [DB](/docs/CS/DB/DB.md)。

机制页：[Index](/docs/CS/DB/Index.md)、[BLink-Tree](/docs/CS/DB/BLink-Tree.md)、[WAL](/docs/CS/DB/WAL.md)、[Shard](/docs/CS/DB/Shard.md)。家族按模型分：关系型 [MySQL](/docs/CS/DB/MySQL/MySQL.md)、[PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)、[Oracle](/docs/CS/DB/Oracle/Oracle.md)、国产分布式 [TiDB](/docs/CS/DB/TiDB.md)、[OceanBase](/docs/CS/DB/OceanBase.md)、[PolarDB](/docs/CS/DB/PolarDB/PolarDB.md)；键值与缓存 [Redis](/docs/CS/DB/Redis/Redis.md)、[Memcached](/docs/CS/DB/Memcached.md)、[RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)、[LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)；文档 [MongoDB](/docs/CS/DB/MongoDB.md)、宽表 [HBase](/docs/CS/DB/HBase.md)、[Cassandra](/docs/CS/DB/Cassandra.md)；OLAP [ClickHouse](/docs/CS/DB/ClickHouse.md)、[Doris](/docs/CS/DB/Doris.md)、[Druid](/docs/CS/DB/Druid.md)、[Presto](/docs/CS/DB/Presto.md)；[vector](/docs/CS/DB/vector.md) 与 [graph](/docs/CS/DB/graph/graph.md) 是 AI 与关系建模的新战场；中间件层 [ShardingSphere](/docs/CS/DB/ShardingSphere.md)、[TDDL](/docs/CS/DB/TDDL.md)、[canal](/docs/CS/DB/canal.md)。离线与大规模计算见 [BigData](/docs/CS/BigData/BigData.md)。

### Message Queue

消息队列用**异步投递 + 缓冲**解耦生产与消费，代价是引入一套新的正确性问题：投递语义（最多一次 / 至少一次 / 恰好一次）、顺序保证、幂等与去重、积压与削峰、事务消息与延迟消息、以及元数据存储。横向对比与共性机制见 [MQ](/docs/CS/MQ/MQ.md)。

各 broker：[Kafka](/docs/CS/MQ/Kafka/Kafka.md)、[RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)、[Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)、[RabbitMQ](/docs/CS/MQ/RabbitMQ.md)、[NATS](/docs/CS/MQ/NATS.md)、[NSQ](/docs/CS/MQ/NSQ.md)、[ActiveMQ](/docs/CS/MQ/ActiveMQ.md)、[ZeroMQ](/docs/CS/MQ/ZeroMQ.md)。Redis 当队列用的边界见 [Redis](/docs/CS/DB/Redis/Redis.md)。

## Distributed and Cloud Native

### Distributed Systems

分布式系统是**组件位于不同机器、只能靠传递消息来协调**的系统。这个定义直接带来三个本质困难：组件并发、没有全局时钟、部件独立失效——所有共识、复制、一致性与容错设计都是对这三点的回应。入口 [Distributed](/docs/CS/Distributed/Distributed.md)。

理论：[CAP](/docs/CS/Distributed/CAP.md)、[Byzantine](/docs/CS/Distributed/Byzantine.md)、[Time](/docs/CS/Distributed/Time.md)、[Replica](/docs/CS/Distributed/Replica.md)、[Partition](/docs/CS/Distributed/Partition.md)、[Id](/docs/CS/Distributed/Id.md)。工程：[Service](/docs/CS/Distributed/Service.md)、[Middleware](/docs/CS/Distributed/Middleware.md)、[Architecture](/docs/CS/Distributed/Architecture.md)、[Dapper](/docs/CS/Distributed/Dapper.md)、[Cluster_Scheduler](/docs/CS/Distributed/Cluster_Scheduler.md)。 gossip 成员管理与高可用范式已并入 [Distributed](/docs/CS/Distributed/Distributed.md) 的 `### Gossip` 与 `## Leader Election` 章节。论文线以 Google 为主：[GFS](/docs/CS/Distributed/GFS.md)、[MapReduce](/docs/CS/Distributed/MapReduce.md)、[Bigtable](/docs/CS/Distributed/Bigtable.md)、[Spanner](/docs/CS/Distributed/Spanner.md)、[Dynamo](/docs/CS/Distributed/Dynamo.md)，脉络见 [Google](/docs/CS/Distributed/Google.md)。共识与协调的具体实现（[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)、[etcd](/docs/CS/Framework/etcd/etcd.md)）在框架一节。

### Cloud Native

云原生让组织在公有云、私有云、混合云环境中**以可编程、可重复的方式大规模开发、构建与部署工作负载**；其特征是松耦合、可互操作，并且安全、有韧性、可管理、可持续、可观测。技术组合是容器、服务网格、多租户、微服务、不可变基础设施、Serverless 与声明式 API。

入口 [Container](/docs/CS/Container/Container.md)：[Docker](/docs/CS/Container/Docker/Docker.md) 与容器网络，[K8s](/docs/CS/Container/k8s/K8s.md) 侧从 [Architecture](/docs/CS/Container/k8s/Architecture.md)、[Pod](/docs/CS/Container/k8s/Pod.md)、[scheduler](/docs/CS/Container/k8s/scheduler.md) 读到 [Service](/docs/CS/Container/k8s/Service.md)、[Ingress](/docs/CS/Container/k8s/Ingress.md)、[Storage](/docs/CS/Container/k8s/Storage.md)，再到 [Helm](/docs/CS/Container/k8s/Helm.md)、[client-go](/docs/CS/Container/k8s/client-go.md)、[containerd](/docs/CS/Container/k8s/containerd.md) 与 [Eviction](/docs/CS/Container/k8s/Eviction.md)。隔离与限额的真实机制回到内核：[namespace](/docs/CS/OS/Linux/namespace.md)、[cgroup](/docs/CS/OS/Linux/cgroup/README.md)、[LXC](/docs/CS/OS/Linux/LXC.md)；网格与入口见 [Istio](/docs/CS/Framework/Istio/Istio.md)、[Higress](/docs/CS/Framework/Higress/Higress.md)；云产品与事件规范见 [Cloud](/docs/CS/Cloud/Cloud.md)、[CloudEvent](/docs/CS/Cloud/CloudEvent.md)；无服务器形态见 [Serverless](/docs/CS/SE/Serverless.md)。安全与密码学基础独立成篇：[Security](/docs/CS/Security/Security.md)。

## Engineering and Frameworks

### Software Engineering

软件工程关心**如何让系统长期可演进**，而不是一次跑通：先用 [Architecture](/docs/CS/SE/Architecture.md) 与 [DDD](/docs/CS/SE/DDD.md) 建模，再处理 [Concurrency](/docs/CS/SE/Concurrency.md)、[Lock](/docs/CS/SE/Lock.md)、[Transaction](/docs/CS/SE/Transaction.md) 这些正确性机制，然后用 [Cache](/docs/CS/SE/Cache.md)（[Caffeine](/docs/CS/SE/Caffeine.md)、[JetCache](/docs/CS/SE/JetCache.md)）、[RateLimiter](/docs/CS/SE/RateLimiter.md)、[CircuitBreaker](/docs/CS/SE/CircuitBreaker.md)、[Workflow](/docs/CS/SE/Workflow.md)、[Scheduled_Task](/docs/CS/SE/Scheduled_Task.md) 撑起规模与可靠性，最后由 [Test](/docs/CS/SE/Test.md)、[Stress_testing](/docs/CS/SE/Stress_testing.md)、[APM](/docs/CS/SE/APM.md) 与 [Debug](/docs/CS/SE/Debug.md) 提供反馈回路。入口 [Engineering](/docs/CS/SE/Engineering.md)，综合演练见 [SystemDesign](/docs/CS/SE/SystemDesign.md)，代码层面的取舍见 [Clean_Code](/docs/CS/SE/Clean_Code.md) 与 [Refactoring](/docs/CS/SE/Refactoring.md)。

跨语言视角（谁实现了什么、各层差异）集中在 [Scheduled_Task](/docs/CS/SE/Scheduled_Task.md) 这类总览页；Java 源码级细节留在 [JDK/sche](/docs/CS/Java/JDK/sche.md)，两边不重复叙述。

### Frameworks and Middleware

框架替应用承担**横切关注点**（依赖注入、事务、序列化、连接与线程模型、服务治理），中间件则是可独立部署的共享能力。按技术栈分层导航见 [Framework](/docs/CS/Framework/README.md)。

- **Application Frameworks**：[Spring](/docs/CS/Framework/Spring/Spring.md)（[IoC](/docs/CS/Framework/Spring/IoC.md)、[AOP](/docs/CS/Framework/Spring/AOP.md)、[MVC](/docs/CS/Framework/Spring/MVC.md)、[Reactive](/docs/CS/Framework/Spring/Reactive.md)）、[Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)、[Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- **Networking and Containers**：[Netty](/docs/CS/Framework/Netty/Netty.md)（[EventLoop](/docs/CS/Framework/Netty/EventLoop.md)、[ByteBuf](/docs/CS/Framework/Netty/ByteBuf.md)）、[Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)、[Jetty](/docs/CS/Framework/Jetty/Jetty.md)、[Undertow](/docs/CS/Framework/Undertow/Undertow.md)
- **RPC and Data Access**：[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)、[HSF](/docs/CS/Framework/HSF/HSF.md)、[gRPC](/docs/CS/Framework/gRPC/gRPC.md)、[MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)、[Hibernate](/docs/CS/Framework/Hibernate/Hibernate.md)
- **Coordination and Registry**：[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)、[etcd](/docs/CS/Framework/etcd/etcd.md)、[Consul](/docs/CS/Framework/consul/Consul.md)、[Nacos](/docs/CS/Framework/nacos/Nacos.md)、[Eureka](/docs/CS/Framework/eureka/Eureka.md)、[SOFARegistry](/docs/CS/Framework/SOFARegistry.md)
- **Stability Governance**：[Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)、[Seata](/docs/CS/Framework/Seata/Seata.md)、[Hippo4j](/docs/CS/Framework/Hippo4j.md)、[BooKeeper](/docs/CS/Framework/BooKeeper/BooKeeper.md)
- **Compute and Storage Engines**：[Flink](/docs/CS/Framework/Flink/Flink.md)、[Spark](/docs/CS/Framework/Spark/Spark.md)、[Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)、[ES](/docs/CS/Framework/ES/ES.md)
- **Job Scheduling**：[Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md)、[xxl-job](/docs/CS/Framework/Job/xxl-job.md)、[ElasticJob](/docs/CS/Framework/Job/ElasticJob.md)、[PowerJob](/docs/CS/Framework/Job/PowerJob.md)、[DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler.md)
- **Go / Python**：[gorm](/docs/CS/Framework/gorm.md)、[kitex](/docs/CS/Framework/kitex.md)、[evio](/docs/CS/Framework/evio.md)、[Netpoll](/docs/CS/Framework/Netpoll.md)、[FastAPI](/docs/CS/Framework/FastAPI.md)

### Developer Tooling

工具不直接产生业务价值，但决定**反馈回路的长度**。构建与依赖见 [BuildTools](/docs/CS/BuildTool/BuildTools.md)（Maven、Gradle、make/CMake）；版本控制见 [VCS](/docs/CS/VCS/VCS.md) 与 [Git](/docs/CS/VCS/Git.md)；日志与指标见 [Log](/docs/CS/log/Log.md)；压缩原理见 [Compress](/docs/CS/compress/Compress.md)；结构套路见 [DesignPatterns](/docs/CS/DesignPatterns/DesignPatterns.md)。编辑器与命令行习惯见 [Vim](/docs/CS/Tool/Vim.md)，内核侧调试与性能采样工具见 [Tools](/docs/CS/OS/Linux/Tools/README.md)。Web 一侧由 [Nodejs](/docs/CS/front-end/Nodejs.md)、[Webpack](/docs/CS/front-end/Webpack.md)、[Electron](/docs/CS/front-end/Electron.md) 与 [Browser](/docs/CS/Browser/Browser.md) 构成。

## Intelligence and Applications

### Artificial Intelligence

人工智能研究让机器**表现出感知、推理、学习与决策能力**的程序。方法层级是 [ML](/docs/CS/AI/ML/ML.md)（从数据中学规律）→ [DL](/docs/CS/AI/DL/DL.md)（多层网络做表示学习）→ [LLM](/docs/CS/AI/LLM/LLM.md)（预训练 + 上下文），分界线是 2017 年的 [Transformer](/docs/CS/AI/Transformer.md)：self-attention 取代顺序递推，使训练可大规模并行。学科地图与三范式对比见 [AI](/docs/CS/AI/AI.md)，应用方向见 [NLP](/docs/CS/AI/NLP/NLP.md)、[CV](/docs/CS/AI/CV.md)、[RAG](/docs/CS/AI/RAG.md)，训练与推理框架见 [PyTorch](/docs/CS/AI/PyTorch.md)。

「机器能否思考」的可操作判据及其限度，见 [The Turing Test](/docs/CS/AI/AI.md?id=the-turing-test)。

LLM 应用与 Agent 工程是独立子树：[Overview](/docs/CS/AI/LLM/Model/Overview.md)（模型总览）、[Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)（理论）、协议层 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 与 [A2A](/docs/CS/AI/LLM/Protocol/A2A.md)、平台形态 [Platform](/docs/CS/AI/LLM/Platform/Platform.md)（Dify、Coze 等）、编排框架 [LangTools](/docs/CS/AI/LangTools.md)（LangChain、[LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)、Deep Agents、LangSmith）。

### Recommender Systems

推荐系统是**信息过滤系统**：在候选量远大于注意力的前提下预测用户偏好并给出排序，属于「搜索、推荐、广告」技术栈。它建立在机器学习之上，而不是 AI 的一个分支——工程上更关心链路与指标。入口 [RecommenderSystem](/docs/CS/RecommenderSystem/RecommenderSystem.md)。

链路：[UserProfile](/docs/CS/RecommenderSystem/UserProfile.md) → [Recall](/docs/CS/RecommenderSystem/Recall.md)（[CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)、[ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)）→ [Ranking](/docs/CS/RecommenderSystem/Ranking.md) → [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md) → [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)，整体拓扑与在线架构见 [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md) 与 [Architecture](/docs/CS/RecommenderSystem/Architecture.md)；场景化问题与商业化见 [Scenario](/docs/CS/RecommenderSystem/Scenario.md) 与 [Advertising](/docs/CS/RecommenderSystem/Advertising.md)。

## Directory

<details>
<summary>Expand the full topic directory</summary>

**Overview and Quick Reference** —— [Glossary](/docs/CS/term.md) · [Languages](/docs/CS/Languages.md)

**Theory and Algorithms** —— [Algorithms](/docs/CS/Algorithms/Algorithms.md) · [Computability](/docs/CS/Algorithms/Computability.md) · [NP](/docs/CS/Algorithms/NP.md) · [DesignPatterns](/docs/CS/DesignPatterns/DesignPatterns.md) · [Mathematics](/docs/Mathematics/Mathematics.md)

**Systems and Low Level** —— [Operating System](/docs/CS/OS/OS.md) · [Linux](/docs/CS/OS/Linux/Linux.md) · [Computer Organization](/docs/CS/CO/CO.md) · [memory](/docs/CS/memory/memory.md) · [assembly](/docs/CS/assembly/assembly.md) · [Compiler](/docs/CS/Compiler/Compiler.md) · [GNU](/docs/CS/GNU/GNU.md)

**Programming Languages** —— [Java](/docs/CS/Java/Java.md) · [JDK](/docs/CS/Java/JDK/JDK.md) · [Go](/docs/CS/Go/Go.md) · [C](/docs/CS/C/C.md) · [C++](/docs/CS/C++/C++.md) · [Rust](/docs/CS/Rust/Rust.md) · [Python](/docs/CS/Python/Python.md) · [Scala](/docs/CS/Scala/Scala.md) · [TypeScript](/docs/CS/TypeScript/TypeScript.md) · [Dart](/docs/CS/Dart/Dart.md) · [Flutter](/docs/CS/Flutter.md)

**Networks and Distributed** —— [Computer Network](/docs/CS/CN/CN.md) · [Distributed Systems](/docs/CS/Distributed/Distributed.md) · [Message Queue](/docs/CS/MQ/MQ.md) · [Security](/docs/CS/Security/Security.md)

**Data and Storage** —— [Database](/docs/CS/DB/DB.md) · [BigData](/docs/CS/BigData/BigData.md) · [Blockchain](/docs/CS/Blockchain/Blockchain.md)

**Cloud Native and Deployment** —— [Cloud Native](/docs/CS/Container/Container.md) · [Cloud](/docs/CS/Cloud/Cloud.md)

**Engineering and Tooling** —— [Frameworks and Middleware](/docs/CS/Framework/README.md) · [Software Engineering](/docs/CS/SE/Engineering.md) · [BuildTools](/docs/CS/BuildTool/BuildTools.md) · [Vim](/docs/CS/Tool/Vim.md) · [Log](/docs/CS/log/Log.md) · [VCS](/docs/CS/VCS/VCS.md) · [Compress](/docs/CS/compress/Compress.md) · [Nodejs](/docs/CS/front-end/Nodejs.md) · [Browser](/docs/CS/Browser/Browser.md)

**Intelligence and Applications** —— [Artificial Intelligence](/docs/CS/AI/AI.md) · [LLM](/docs/CS/AI/LLM/LLM.md) · [Recommender System](/docs/CS/RecommenderSystem/RecommenderSystem.md)

</details>

</div>

## Links

- [Containers Map](/docs/CS/Container/README.md)
- [Set Theory and Logic](/docs/Mathematics/Set_Theory_Logic.md)

## References

1. [CS 自学指南](https://csdiy.wiki/)
2. Computer Science: An Overview
3. Foundations of Computer Science
