## Introduction


Java Flight Recorder (JFR) is a tool for collecting diagnostic and profiling data about a running Java application. It is integrated into the Java Virtual Machine (JVM) and causes almost no performance overhead, so it can be used even in heavily loaded production environments. When default settings are used, both internal testing and customer feedback indicate that performance impact is less than one percent. For some applications, it can be significantly lower. However, for short-running applications (which are not the kind of applications running in production environments), relative startup and warmup times can be larger, which might impact the performance by more than one percent. JFR collects data about the JVM as well as the Java application running on it.

Compared to other similar tools, JFR has the following benefits:
- Provides better data: A coherent data model used by JFR makes it easier to cross reference and filter events.
- Allows for third-party event providers: A set of APIs allow JFR to monitor third-party applications, including WebLogic Server and other Oracle products.
- Reduces total cost of ownership: JFR enables you to spend less time diagnosing and troubleshooting problems, reduces operating costs and business interrupts, provides faster resolution time when problems occur, and improves system efficiency.

JFR is primarily used for:
- Profiling
  JFR continuously saves large amounts of data about the running system. This profiling information includes thread samples (which show where the program spends its time), lock profiles, and garbage collection details.
- Black Box Analysis
  JFR continuously saves information to a circular buffer. This information can be accessed when an anomaly is detected to find the cause.
- Support and Debugging
  Data collected by JFR can be essential when contacting Oracle support to help diagnose issues with your Java application.

JFR有两种主要的概念：事件和数据流

JFR collects events that occur in the JVM when the Java application runs. These events are related to the state of the JVM itself or the state of the program. An event has a name, a timestamp, and additional information (like thread information, execution stack, and state of the heap).

There are three types of events that JFR collects:
- an instant event is logged immediately once it occurs
- a duration event is logged if its duration succeeds a specified threshold
- a sample event is used to sample the system activity

The events that JFR collects contain a huge amount of data. For this reason, by design, JFR is fast enough to not impede the program.
JFR saves data about the events in a single output file, flight.jfr.

As we know, disk I/O operations are quite expensive. Therefore, JFR uses various buffers to store the collected data before flushing the blocks of data to disk. Things might become a little bit more complex because, at the same moment, a program might have multiple registering processes with different options.

Because of this, we may find more data in the output file than requested, or it may not be in chronological order. We might not even notice this fact if we use JMC, because it visualizes the events in chronological order.

In some rare cases, JFR might fail to flush the data (for example, when there are too many events or in a case of a power outage). If this occurs, JFR tries to inform us that the output file might be missing a piece of data.

在 JVM 启动文件的路径中添加 -XX:StartFlightRecording=duration,filename=jfr_recording.jfr 参数，其中 duration 表示录制时长，单位为毫秒，filename 表示录制文件的名称

JFR本身是基于周期性对JVM虚拟机的运行状况进行采样记录的，其采样的频率可以通过其参数传入;只是需要留意的是，采样间隔越小对系统的性能干扰就越大。 和传统的JProfiler/VisualVM这些基于JMX的工具所不同的是，JFR记录的信息是近似而非精确的；当然大部分情况下这些模糊性信息就足够说明问题了

需要注意的是，JFR 录制过程中会对应用程序的性能产生一定的影响，因此需要在测试环境中进行测试，以确保不会影响生产环境中的应用程序性能。
1. JFR 的线程堆栈 dump 采集默认周期是everyChunk，也就是每次新建一个Chunk就会采集一次。默认每个Chunk大小为 12M，在线程比较多的时候，堆栈 dump 可能大于 12M，导致 JFR 一直切换新的 Chunk，然后又触发evenryChunk导致无限循环而雪崩。 
2. 对于 JFR 默认事件采集配置（位于JDK目录/lib/jfr/default.jfc），每个采集周期和Chunk相关的，都要谨慎处理，最好周期通过固定时间写死，例如每一分钟等等，不要使用Chunk作为指标，防止上面这个问题。


## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
