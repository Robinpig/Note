## Introduction

本篇拆解 CAT 的**双存储写路径**：聚合报表落 **本地文件 + MySQL**，原始 logview 落 **本地磁盘 → 异步 HDFS**。代码事实基于 **dianping/cat tag 3.1.0** 源码，讲解直接贴真实源码，不标注行号。整体架构见 [CAT](/docs/CS/Distributed/Tracing/CAT.md)，服务端分析流程见 [CAT 服务端实时分析](/docs/CS/Distributed/Tracing/CAT/Consumer.md)。

CAT 不依赖外部 TSDB / 宽列存储（不像 [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md) 用 HBase）：报表走成熟的关系型 MySQL，原始明细走「本地磁盘 + HDFS」的廉价分层——这是它「简单架构就是最好架构」哲学的体现。

## Report Storage (MySQL + Local File)

每个 Analyzer 周期末调用 `storeHourlyReports(startTime, policy, index)` 落库，实现位于 `DefaultReportManager`（`cat-core/src/main/java/com/dianping/cat/report/DefaultReportManager.java`）：

- **存储策略由内嵌枚举 `StoragePolicy` 控制**：只有 `FILE_AND_DB` 与 `FILE` 两个值；`forDatabase()` 仅 `FILE_AND_DB` 为真（写 MySQL），`forFile()` 在 `FILE` 或 `FILE_AND_DB` 时为真（写本地文件）：

```java
	public static enum StoragePolicy {
		FILE,

		FILE_AND_DB;

		public boolean forDatabase() {
			return this == FILE_AND_DB;
		}

		public boolean forFile() {
			return this == FILE_AND_DB || this == FILE;
		}
	}
```

- `storeHourlyReports` 按 `startTime` 取出当前小时的内存报表，按策略分别落文件与数据库；`getHourlyReport(startTime, domain, createIfNotExist)`（同文件）按 `startTime + domain` 分片取数：

```java
	@Override
	public void storeHourlyReports(long startTime, StoragePolicy policy, int index) {
		Transaction t = Cat.newTransaction("Checkpoint", m_name);
		Map<String, T> reports = m_reports.get(startTime);
		ReportBucket bucket = null;

		try {
			// ... 校验并剔除 error domains
			m_reportDelegate.beforeSave(reports);

			if (policy.forFile()) {
				bucket = m_bucketManager.getReportBucket(startTime, m_name, index);

				try {
					storeFile(reports, bucket);
				} finally {
					m_bucketManager.closeBucket(bucket);
				}
			}

			if (policy.forDatabase()) {
				storeDatabase(startTime, reports);
			}
		}
		// ...
	}
```

- 写 MySQL 通过代码生成的 DAO：`storeDatabase` 里 `m_reportDao.insert(r)` 写报表元数据行、`m_reportContentDao.insert(content)` 写二进制报表内容——即 MySQL 的报表表与内容表（DAL 由 manifest XML 生成，见 [CAT 服务端实时分析](/docs/CS/Distributed/Tracing/CAT/Consumer.md)）：

```java
	private void storeDatabase(long startTime, Map<String, T> reports) {
		Date period = new Date(startTime);
		String ip = NetworkInterfaceManager.INSTANCE.getLocalHostAddress();

		for (T report : reports.values()) {
			try {
				String domain = m_reportDelegate.getDomain(report);
				HourlyReport r = m_reportDao.createLocal();

				r.setName(m_name);
				r.setDomain(domain);
				r.setPeriod(period);
				r.setIp(ip);
				r.setType(1);

				m_reportDao.insert(r);

				int id = r.getId();
				byte[] binaryContent = m_reportDelegate.buildBinary(report);
				HourlyReportContent content = m_reportContentDao.createLocal();

				content.setReportId(id);
				content.setContent(binaryContent);
				content.setPeriod(period);
				m_reportContentDao.insert(content);
				m_reportDelegate.createHourlyTask(report);
			} catch (Throwable e) {
				Cat.getProducer().logError(e);
			}
		}
	}
```

- 因此 Analyzer 中常见两个调用组合：`doCheckpoint(atEnd)` 时本地文件 + MySQL 双写 `storeHourlyReports(getStartTime(), StoragePolicy.FILE_AND_DB, m_index)`（如 `cat-consumer/.../transaction/TransactionAnalyzer.java`、`cat-consumer/.../cross/CrossAnalyzer.java`、`cat-consumer/.../dependency/DependencyAnalyzer.java`），非 `atEnd`（或本地模式）则只落文件 `storeHourlyReports(getStartTime(), StoragePolicy.FILE, m_index)`：

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

## Raw Logview Storage (Local Disk → HDFS)

原始 `MessageTree`（logview）不入 MySQL，而是：

- **本地磁盘**：`LocalMessageBucketManager`（`cat-consumer/.../dump/`）把消息写入**本地 bucket**（Data + Index 双文件、GZIP 分段），支持按 Message-ID 随机读与批量压缩。
- **异步 HDFS**：`cat-hadoop` 模块的 `HdfsUploader` 周期性把本地 bucket 上传到 **HDFS**，避免强依赖 HDFS 可用性。cat-home 展示时可从 HDFS 拉取历史 logview 回放。

这种「本地磁盘缓冲 + 异步上云」的结构，使 Collector 在 HDFS 抖动时仍能持续接收与展示最近数据。

## Storage Trade-offs

| 维度 | CAT（本页） | Pinpoint | SkyWalking |
| --- | --- | --- | --- |
| 聚合报表 | MySQL + 本地文件 | HBase / Pinot | BanyanDB（可换 ES/MySQL） |
| 原始明细 | 本地磁盘 + HDFS | HBase `Trace` 表 | BanyanDB Stream |
| 依赖复杂度 | 低（MySQL + HDFS） | 高（HBase 运维重） | 中（BanyanDB 较轻） |

CAT 用「**关系型 MySQL + 对象存储 HDFS**」换取部署与运维的简单性，代价是非实时、长周期明细查询依赖 HDFS 回放；这与 Pinpoint「全量 trace 进 HBase、强一致可读」、SkyWalking「统一 BanyanDB 流/度量/属性三模型」形成鲜明对照。

## Links

- [CAT 服务端实时分析](/docs/CS/Distributed/Tracing/CAT/Consumer.md) — 12+ Analyzer 与增量计算
- [CAT 客户端设计](/docs/CS/Distributed/Tracing/CAT/Client.md) — Message-ID 与 Netty :2280
- [CAT](/docs/CS/Distributed/Tracing/CAT.md) — 枢纽页：四消息模型与双存储三级报表
- [Pinpoint 存储](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md) — 对照 HBase / Pinot 路线

## References

- CAT GitHub（dianping/cat），tag 3.1.0：https://github.com/dianping/cat
- CAT 源码基线（已克隆并 codegraph 索引）：`E:/Projects/cat-3.1.0`
