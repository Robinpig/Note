## Introduction

本篇聚焦 **CAT 客户端（cat-client）** 的设计机理：为什么它能做到「任何场景下都不影响业务性能」，以及埋点上下文、通信与 Message-ID 的具体实现。代码事实基于 **dianping/cat tag 3.1.0** 源码，讲解直接贴真实源码，不标注行号。服务端实时分析见 [CAT 服务端实时分析](/docs/CS/Distributed/Tracing/CAT/Consumer.md)，整体架构见 [CAT](/docs/CS/Distributed/Tracing/CAT.md)。

## ThreadLocal Message Context

CAT 客户端设计的核心约束是：**API 简单、高可靠、绝不拖慢业务**——监控只是核心业务流程的旁路。它利用 **ThreadLocal（线程局部变量）** 把一次请求的监控上下文存为线程内的**监控树**：

- Web 容器（Tomcat / Jetty）或 RPC 服务端（Dubbo / Pigeon）都基于线程池，业务逻辑基本在同一线程内调用后端服务、DB、缓存；把监控对象存入线程副本非常自然。
- 实现上，`DefaultMessageManager`（`cat-client/src/main/java/com/dianping/cat/message/internal/DefaultMessageManager.java`）持有一个 `ThreadLocal<Context> m_context`：

```java
	private ThreadLocal<Context> m_context = new ThreadLocal<Context>();
```

`getThreadLocalMessageTree()` 在首次调用时惰性 `setup()` 出一个 `Context`，其 `m_tree` 就是当前线程的 `MessageTree`：

```java
	@Override
	public MessageTree getThreadLocalMessageTree() {
		Context ctx = m_context.get();

		if (ctx == null) {
			setup();
		}
		ctx = m_context.get();

		return ctx.m_tree;
	}
```

`Context` 构造时即以 domain/hostName/ip 填充树的基本信息：

```java
	class Context {
		private MessageTree m_tree;

		private Stack<Transaction> m_stack;
		// ...

		public Context(String domain, String hostName, String ipAddress) {
			m_tree = new DefaultMessageTree();
			m_stack = new Stack<Transaction>();

			Thread thread = Thread.currentThread();
			String groupName = thread.getThreadGroup().getName();

			m_tree.setThreadGroupName(groupName);
			m_tree.setThreadId(String.valueOf(thread.getId()));
			m_tree.setThreadName(thread.getName());

			m_tree.setDomain(domain);
			m_tree.setHostName(hostName);
			m_tree.setIpAddress(ipAddress);
			m_length = 1;
			m_knownExceptions = new HashSet<Throwable>();
		}
		// ...
	}
```
- 业务线程结束时，把整棵监控树 `flush` 进**异步内存队列**；CAT 另起一个消费线程（见下文 `TcpSocketSender`）把队列数据异步发往服务端。
- 因为只有跨边界行为（HTTP / RPC / MQ / Job / Cache / DAL）才产生 Transaction 节点，监控树天然贴合「一次请求内干了什么」。

由此带来的两个工程教训（来自美团踩过的坑）：内存上，ThreadLocal 内的监控树可能因业务方滥用（如 for 循环几万店铺）膨胀导致 Old GC；CPU 上，本地 MappedByteBuffer 在机器 IO 瓶颈时会 block，优化方向是**把序列化、传输、任何可能延迟的操作全部异步化**。

## Communication

- **Netty NIO TCP**：客户端通过 **Netty** 以 NIO 把序列化后的消息树发往服务端。默认 TCP 端口 **2280**（HTTP 端口 80 走不同通道），由 `Cat.initializeByDomain` 固定（`cat-client/src/main/java/com/dianping/cat/Cat.java`）：

```java
	public static void initializeByDomain(String domain, String... servers) {
		initializeByDomain(domain, 2280, 80, servers);
	}
```

- 发送器 `TcpSocketSender`（`cat-client/src/main/java/com/dianping/cat/message/io/TcpSocketSender.java`）实现 `Task, MessageSender`，内部持有两个内存队列；`send(MessageTree tree)` 决定采样/入队，`sendInternal` 经 `m_codec.encode(tree)` 编码为 `ByteBuf` 后由 Netty channel 写出：

```java
@Named
public class TcpSocketSender implements Task, MessageSender, LogEnabled {
	// ...
	private MessageCodec m_codec = new NativeMessageCodec();
	// ...
	private MessageQueue m_queue = new DefaultMessageQueue(SIZE);

	private MessageQueue m_atomicQueue = new DefaultMessageQueue(SIZE);

	private ChannelManager m_channelManager;
	// ...
	@Override
	public void send(MessageTree tree) {
		if (!m_configManager.isBlock()) {
			double sampleRatio = m_configManager.getSampleRatio();

			if (tree.canDiscard() && sampleRatio < 1.0 && (!tree.isHitSample())) {
				processTreeInClient(tree);
			} else {
				offer(tree);
			}
		}
	}
	// ...
	public void sendInternal(ChannelFuture channel, MessageTree tree) {
		if (tree.getMessageId() == null) {
			tree.setMessageId(m_factory.getNextId());
		}

		ByteBuf buf = m_codec.encode(tree);

		int size = buf.readableBytes();

		channel.channel().writeAndFlush(buf);

		if (m_statistics != null) {
			m_statistics.onBytes(size);
		}
	}
```

底层连接由 `ChannelManager` 管理（`cat-client/src/main/java/com/dianping/cat/message/io/ChannelManager.java`），使用 Netty 的 `Bootstrap` / `NioEventLoopGroup` / `NioSocketChannel`：

```java
	public ChannelManager(Logger logger, List<InetSocketAddress> serverAddresses, ClientConfigManager configManager,
							MessageIdFactory idFactory) {
		m_logger = logger;
		m_configManager = configManager;
		m_idFactory = idFactory;

		EventLoopGroup group = new NioEventLoopGroup(1, new ThreadFactory() {
			@Override
			public Thread newThread(Runnable r) {
				Thread t = new Thread(r);
				t.setDaemon(true);
				return t;
			}
		});

		Bootstrap bootstrap = new Bootstrap();
		bootstrap.group(group).channel(NioSocketChannel.class);
		bootstrap.option(ChannelOption.SO_KEEPALIVE, true);
		// ...
		m_bootstrap = bootstrap;
		// ...
	}
```
- **自定义二进制序列化**：相比通用协议（JSON / Protobuf）更省字节，在「每天千亿级消息」的实时场景里收益显著。
- **全程异步**：队列实现 `DefaultMessageQueue`（`cat-client/src/main/java/com/dianping/cat/message/io/DefaultMessageQueue.java`）内部就是一个 `ArrayBlockingQueue<MessageTree>`，序列化、传输、IO 全部异步化——这是「监控挂了业务也不能受影响」承诺的实现基础：

```java
public class DefaultMessageQueue implements MessageQueue {

	private BlockingQueue<MessageTree> m_queue;

	public DefaultMessageQueue(int size) {
		m_queue = new ArrayBlockingQueue<MessageTree>(size);
	}
	// ...
	@Override
	public MessageTree poll() {
		try {
			return m_queue.poll(5, TimeUnit.MILLISECONDS);
		} catch (InterruptedException e) {
			return null;
		}
	}
```

## Message-ID Design

CAT 给每条消息一个客户端生成的唯一 ID，用于后续按 ID 查内容、并在 RPC 边界串联：

```
ShopWeb-0a010680-375030-2
└应用名─┘ └IP 十六进制┘ └时间/小时取整┘ └小时自增序号┘
```

ID 由 `MessageIdFactory.getNextId()` 生成（`cat-client/src/main/java/com/dianping/cat/message/internal/MessageIdFactory.java`），结构为 `m_idPrefix + index`：

```java
	public String getNextId() {
		long timestamp = getTimestamp();

		if (timestamp != m_timestamp) {
			synchronized (this) {
				if (timestamp != m_timestamp) {
					resetCounter(timestamp);
				}
			}
		}

		int index = m_index.getAndIncrement();
		StringBuilder sb = new StringBuilder(64);

		if (Cat.isMultiInstanceEnabled()) {
			sb.append(m_idPrefixOfMultiMode).append(index);
		} else {
			sb.append(m_idPrefix).append(index);
		}

		return sb.toString();
	}
```

- 前缀 `m_idPrefix` = `domain-ipAddress-timestamp-`：`domain` 为应用名；`ipAddress` 取本机 IP 的**十六进制**（`genIpHex()`）；`timestamp` 是 `System.currentTimeMillis() / HOUR`，即「按小时取整」（源码注释标 `// version 2`）：

```java
	protected long getTimestamp() {
		long timestamp = System.currentTimeMillis();

		return timestamp / HOUR; // version 2
	}

	String genIpHex() {
		String ip = NetworkInterfaceManager.INSTANCE.getLocalHostAddress();
		List<String> items = Splitters.by(".").noEmptyItem().split(ip);
		byte[] bytes = new byte[4];

		for (int i = 0; i < 4; i++) {
			bytes[i] = (byte) Integer.parseInt(items.get(i));
		}

		StringBuilder sb = new StringBuilder(bytes.length / 2);
		// ...
	}
```

- 后缀 `index` 是 `AtomicInteger m_index` 在**当前小时内的自增序号**，跨小时由 `resetCounter` 归零重建前缀：

```java
	private void resetCounter(long timestamp) {
		m_index.set(0);
		// ...
		m_idPrefix = initIdPrefix(timestamp, false);
		m_idPrefixOfMultiMode = initIdPrefix(timestamp, true);
	}
```

因此同一小时内、同一进程发出的消息 ID 单调递增、全局可按 `domain + ipHex + 小时` 反推来源——这正是示例 `ShopWeb-0a010680-375030-2` 的来历。

**跨进程串联**：`MessageTree` 接口（`cat-client/src/main/java/com/dianping/cat/message/spi/MessageTree.java`）携带三个 ID 字段：

```java
	public String getMessageId();

	public void setMessageId(String messageId);
	// ...
	public String getParentMessageId();

	public void setParentMessageId(String parentMessageId);

	public String getRootMessageId();

	public void setRootMessageId(String rootMessageId);
```

A 调用 B 时，A 把自身的 `rootMessageId` + 新建的 `parentMessageId` 通过上下文传给 B；B 执行期间把这些 ID 写进自己的树，从而把一次跨服务调用串到同一棵树上——这与 [Pinpoint 的 TX_ID 传播](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md)、[SkyWalking 的 TraceSegmentRef](/docs/CS/Distributed/Tracing/SkyWalking/Agent.md) 目标一致，但 ID 构造与传递机制不同（CAT 用「domain-ipHex-小时-序号」而非 UUID/agentId 体系）。

## Multi-language Support

Java 是核心客户端；官方/社区还提供 C/C++、.NET、Node.js、Python、Go 客户端，使 CAT 能跨语言采集——这一点比 Pinpoint（Java 为主、PHP/Python 较弱）覆盖更广。

## Links

- [CAT 服务端实时分析](/docs/CS/Distributed/Tracing/CAT/Consumer.md) — 消息分发与增量报表
- [CAT 存储](/docs/CS/Distributed/Tracing/CAT/Storage.md) — 本地文件 + MySQL + HDFS 写路径
- [CAT](/docs/CS/Distributed/Tracing/CAT.md) — 枢纽页：四消息模型与双存储
- [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md) — 对照字节码插桩路线

## References

- CAT GitHub（dianping/cat），tag 3.1.0：https://github.com/dianping/cat
- 美团技术团队《深度剖析开源分布式监控 CAT》：https://tech.meituan.com/2018/11/01/cat-in-depth-java-application-monitoring.html
- CAT 源码基线（已克隆并 codegraph 索引）：`E:/Projects/cat-3.1.0`
