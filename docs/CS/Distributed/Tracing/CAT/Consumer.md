## Introduction

本篇聚焦 **CAT 服务端（cat-consumer）** 的实时分析机理：它如何把每天千亿级原始消息在秒级内聚合成报表，以及「增量计算 + 固定维度建模」的取舍。代码事实基于 **dianping/cat tag 3.1.0** 源码，讲解直接贴真实源码，不标注行号。客户端设计见 [CAT 客户端设计](/docs/CS/Distributed/Tracing/CAT/Client.md)，整体架构与存储见 [CAT](/docs/CS/Distributed/Tracing/CAT.md) / [CAT 存储](/docs/CS/Distributed/Tracing/CAT/Storage.md)。

## Real-time Analysis Pipeline

CAT 服务端对大数据的实时处理基本是**全异步**的：

1. 客户端消息经 **Netty NIO TCP :2280** 到达（见 [CAT 客户端设计](/docs/CS/Distributed/Tracing/CAT/Client.md)），收到的 `MessageTree` 先入**内存队列**。
2. 每类报表由独立的 **Analyzer** 消费自己的队列。`MessageAnalyzer` 接口（`cat-core/src/main/java/com/dianping/cat/analysis/MessageAnalyzer.java`）定义了消费入口与报表管理器等关键方法：

```java
public interface MessageAnalyzer {

	public boolean isEligable(MessageTree tree);

	public void analyze(MessageQueue queue);
	// ...
	public long getStartTime();
	// ...
	public ReportManager<?> getReportManager();
}
```

3. 每个 Analyzer 的「消费循环」由基类 `AbstractMessageAnalyzer.analyze(MessageQueue queue)` 实现（`cat-core/src/main/java/com/dianping/cat/analysis/AbstractMessageAnalyzer.java`）：**持续 drain 队列、逐树调用 `process(tree)`**，超时或失活后还有一个排空队列的收尾循环：

```java
	@Override
	public void analyze(MessageQueue queue) {
		while (!isTimeout() && isActive()) {
			MessageTree tree = queue.poll();

			if (tree != null) {
				try {
					process(tree);
				} catch (Throwable e) {
					m_errors++;

					if (m_errors == 1 || m_errors % 10000 == 0) {
						Cat.logError(e);
					}
				}
			}
		}

		while (true) {
			MessageTree tree = queue.poll();

			if (tree != null) {
				try {
					process(tree);
				} catch (Throwable e) {
					m_errors++;

					if (m_errors == 1 || m_errors % 10000 == 0) {
						Cat.logError(e);
					}
				}
			} else {
				break;
			}
		}
	}
```

4. 每个 Analyzer **每个统计周期（小时）跑一个独立的 `PeriodTask`**（`cat-core/src/main/java/com/dianping/cat/analysis/PeriodTask.java`，`implements Task`），其 `run()` 就是把队列交给 analyzer 分析。这印证了「**每报表独立线程、数据非线程安全可变、无锁低开销**」的架构选择——某个报表（如 Transaction）处理慢，可配置开启多个处理线程并发消费，不影响其他报表：

```java
public class PeriodTask implements Task, LogEnabled {

	private MessageAnalyzer m_analyzer;

	private MessageQueue m_queue;

	private long m_startTime;
	// ...
	public PeriodTask(MessageAnalyzer analyzer, MessageQueue queue, long startTime) {
		m_analyzer = analyzer;
		m_queue = queue;
		m_startTime = startTime;
	}
	// ...
	@Override
	public void run() {
		try {
			m_analyzer.analyze(m_queue);
		} catch (Exception e) {
			Cat.logError(e);
		}
	}
```
5. 原始 logview 先写**本地磁盘**，再异步上传 **HDFS**，避免强依赖 HDFS（见 [CAT 存储](/docs/CS/Distributed/Tracing/CAT/Storage.md)）。

这种「内存队列 + 每报表独立线程 + 本地磁盘缓冲」的结构，是 CAT 在 35 台物理机集群上扛住每天约 100TB、单机高峰 ~110MB/s 的基础。

## Report Types & Incremental Computation

CAT 重客户端采集的是原始 logview，服务端要实时算出丰富报表。从源码可见 cat-consumer 下一个完整 Analyzer 族（`cat-consumer/src/main/java/com/dianping/cat/consumer/`）：**Business / Cross / Dependency / Dump / Event / Heartbeat / Matrix / Problem / State / Storage / Top / Transaction**（12+ 种）。

- **增量计算**：以 `TransactionAnalyzer` 为例，它 `extends AbstractMessageAnalyzer<TransactionReport>`（`cat-consumer/src/main/java/com/dianping/cat/consumer/transaction/TransactionAnalyzer.java`），`process(MessageTree tree)` 从 `m_reportManager.getHourlyReport(...)` 取出当前小时的 `TransactionReport`，就地累加指标：

```java
	@Override
	public void process(MessageTree tree) {
		String domain = tree.getDomain();
		TransactionReport report = m_reportManager.getHourlyReport(getStartTime(), domain, true);
		List<Transaction> transactions = tree.findOrCreateTransactions();

		for (Transaction t : transactions) {
			String data = String.valueOf(t.getData());

			if (data.length() > 0 && data.charAt(0) == CatConstants.BATCH_FLAG) {
				processBatchTransaction(tree, report, t, data);
			} else {
				processTransaction(report, tree, t);
			}
		}
		// ...
	}
```

周期末在 `doCheckpoint` 里调用 `storeHourlyReports(getStartTime(), StoragePolicy.FILE_AND_DB, m_index)` 落本地文件 + MySQL：

```java
	@Override
	public synchronized void doCheckpoint(boolean atEnd) {
		if (atEnd && !isLocalMode()) {
			m_reportManager.storeHourlyReports(getStartTime(), StoragePolicy.FILE_AND_DB, m_index);
		} else {
			m_reportManager.storeHourlyReports(getStartTime(), StoragePolicy.FILE, m_index);
		}
	}
```

计数（count/sum/avg/max/min/tps/std）、计时、关系处理都在 `process` 内增量完成。
- **固定维度建模**：Transaction 报表固定 5 维（应用 / 机器 / Type / Name / 分钟级分布）组织成深度为 5 的树，访问总从根逐层下钻。全维度灵活建模开销过大，用固定维度换低开销。
- **代码生成 DAL**：报表与配置的实体 / DAO / JDBC 实现由自研 Maven 插件从 XML manifest 生成（如 `transaction-report-manifest.xml`），类型安全且减少手写。

跨机房部署时，每个机房有独立 HDFS 原始存储；cat-home 展示时跨机房调用 consumer 合并数据。路由中心按应用所在机房决定客户端上报的服务端地址（美团有广州 / 北京 / 上海三地机房）。

## Cross & Dependency

- **Cross Analyzer**：处理跨进程消息，对应 RPC 边界。`CrossAnalyzer`（`cat-consumer/src/main/java/com/dianping/cat/consumer/cross/CrossAnalyzer.java`）的 `processTransaction(...)` 用 `parseCrossTransaction` 解析出 `CrossInfo`（远端应用 / 地址 / 角色），更新本地 `CrossReport`；并在 RPC 客户端场景下同步更新对端 `targetDomain` 的 `serverReport`——靠 [客户端传递的 Message-ID 与 root/parentMessageId](/docs/CS/Distributed/Tracing/CAT/Client.md) 把一次跨服务调用串到同一棵树：

```java
	private void processTransaction(CrossReport report, MessageTree tree, Transaction t) {
		CrossInfo crossInfo = parseCrossTransaction(t, tree);

		if (crossInfo != null && crossInfo.validate()) {
			updateCrossReport(report, t, crossInfo);

			String targetDomain = crossInfo.getApp();

			if (m_serverConfigManager.isRpcClient(t.getType()) && !DEFAULT.equals(targetDomain)	&& !"null"
									.equalsIgnoreCase(targetDomain)) {
				CrossInfo serverCrossInfo = convertCrossInfo(tree.getDomain(), crossInfo);

				if (serverCrossInfo != null) {
					CrossReport serverReport = m_reportManager.getHourlyReport(getStartTime(), targetDomain, true);

					updateCrossReport(serverReport, t, serverCrossInfo);
				}
			} else {
				m_errorAppName++;
			}
		}
	}
```

- **Dependency Analyzer**：基于 Call / PigeonCall / SQL 等事件推导服务间调用依赖。`DependencyAnalyzer`（`cat-consumer/src/main/java/com/dianping/cat/consumer/dependency/DependencyAnalyzer.java`）的 `processPigeonTransaction(...)` 解析出目标服务名，更新本端与对端的 `DependencyReport`（调用方 `PigeonCall`、被调方 `PigeonService`），`processSqlTransaction(...)` 解析库名记为 `Database` 依赖；周期末同样 `storeHourlyReports(..., StoragePolicy.FILE_AND_DB, ...)`：

```java
	private void processPigeonTransaction(DependencyReport report, MessageTree tree, Transaction t, String type) {
		if ("PigeonCall".equals(type) || "Call".equals(type)) {
			String target = parseServerName(t);
			String callType = "PigeonCall";

			if (target != null && !"null".equalsIgnoreCase(target)) {
				updateDependencyInfo(report, t, target, callType);
				DependencyReport serverReport = findOrCreateReport(target);

				updateDependencyInfo(serverReport, t, tree.getDomain(), "PigeonService");
			}
		}
	}

	private void processSqlTransaction(DependencyReport report, Transaction t, String type) {
		if ("SQL".equals(type)) {
			String database = parseDatabase(t);

			if (database != null) {
				updateDependencyInfo(report, t, database, "Database");
			}
		}
	}
```

这等价于 [SkyWalking 的拓扑推导](/docs/CS/Distributed/Tracing/SkyWalking/Topology_Alarm.md)——但 CAT 的拓扑来自采样后的消息树聚合，而非全量 trace 的逐 span join。

## Alarm

**cat-alarm** 模块是实时告警引擎：对规则做评估，命中后走通知渠道。由于所有报表都按小时分片、当前小时全内存增量计算，告警能在分钟级粒度上即时触发——这是 CAT「故障发生时分钟级发现」承诺的服务端支撑。

## Links

- [CAT 客户端设计](/docs/CS/Distributed/Tracing/CAT/Client.md) — Message-ID 跨进程串联与 Netty 通信
- [CAT 存储](/docs/CS/Distributed/Tracing/CAT/Storage.md) — 本地文件 + MySQL + HDFS 写路径
- [CAT](/docs/CS/Distributed/Tracing/CAT.md) — 枢纽页：四消息模型与双存储三级报表
- [SkyWalking 拓扑与告警](/docs/CS/Distributed/Tracing/SkyWalking/Topology_Alarm.md) — 对照拓扑推导与告警链路

## References

- CAT GitHub（dianping/cat），tag 3.1.0：https://github.com/dianping/cat
- 美团技术团队《深度剖析开源分布式监控 CAT》：https://tech.meituan.com/2018/11/01/cat-in-depth-java-application-monitoring.html
- CAT 源码基线（已克隆并 codegraph 索引）：`E:/Projects/cat-3.1.0`
