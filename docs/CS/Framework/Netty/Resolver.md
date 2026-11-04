## Introduction

Netty 的地址解析能力分两层：

- `resolver` 模块提供**通用名字解析抽象**（`NameResolver<T>` / `AddressResolver<T>`），把任意字符串（或 `SocketAddress`）异步解析成地址，并把回调调度到 `EventExecutor`（通常是 `EventLoop`）上执行。
- `resolver-dns` 模块在前者之上提供**完整的异步 DNS 客户端** `DnsNameResolver`，支持 A/AAAA/CNAME/MX/TXT/PTR/NS/SRV 等记录类型、EDNS0、TTL 缓存、多 DNS 服务器轮询与 `search domain` 等。

> [!NOTE]
>
> 本文所有结论均基于已检出的 `netty-4.2.19.Final` 源码；4.2 与 4.1 的部分差异已用 `> [!NOTE]` 点明。

---

#### NameResolver / SimpleNameResolver / InetNameResolver

`NameResolver<T>` 是解析器顶层接口，定义四个方法与 `close()`：

```java
// 源码：resolver/src/main/java/io/netty/resolver/NameResolver.java:37,56,72
Future<T> resolve(String inetHost);
Future<T> resolve(String inetHost, Promise<T> promise);
Future<List<T>> resolveAll(String inetHost);
Future<List<T>> resolveAll(String inetHost, Promise<List<T>> promise);
void close();
```

`SimpleNameResolver<T>` 是一个骨架实现，持有 `EventExecutor` 并把 `resolve`/`resolveAll` 转交给抽象的 `doResolve`/`doResolveAll`，所有返回的 `Future` 都绑定到该 `EventExecutor`，因此**回调天然在 `EventLoop` 线程上执行**，不会阻塞调用方：

```java
// 源码：resolver/src/main/java/io/netty/resolver/SimpleNameResolver.java:32,52,89
private final EventExecutor executor;
protected SimpleNameResolver(EventExecutor executor) { ... }
protected abstract void doResolve(String inetHost, Promise<T> promise) throws Exception;
```

`InetNameResolver` 把泛型固定为 `InetAddress`，并提供 `asAddressResolver()` 返回缓存的 `InetSocketAddressResolver`：

```java
// 源码：resolver/src/main/java/io/netty/resolver/InetNameResolver.java:27,42
public abstract class InetNameResolver extends SimpleNameResolver<InetAddress> { ... }
public AddressResolver<InetSocketAddress> asAddressResolver() { ... }
```

#### DefaultNameResolver（基于 JDK，但注意它是阻塞的）

`DefaultNameResolver` 直接调用 JDK 的 `SocketUtils.addressByName`，**在调用方线程上执行阻塞式 `InetAddress` 查找**，只是把结果包装成 `Promise` 异步返回；它并非真正的非阻塞 DNS：

```java
// 源码：resolver/src/main/java/io/netty/resolver/DefaultNameResolver.java:41,50
promise.setSuccess(SocketUtils.addressByName(inetHost));
promise.setSuccess(Arrays.asList(SocketUtils.allAddressesByName(inetHost)));
```

#### NoopAddressResolver

`NoopAddressResolver` 不做任何解析，始终把入参 `SocketAddress` 当作已解析成功返回，常用于由 pipeline 中其它 handler（如代理 handler）自行解析名字的场景：

```java
// 源码：resolver/src/main/java/io/netty/resolver/NoopAddressResolver.java:30,43
public class NoopAddressResolver extends AbstractAddressResolver<SocketAddress> { ... }
```

#### AddressResolver / AddressResolverGroup

`AddressResolver<T>` 面向 `SocketAddress`（如 `InetSocketAddress`），`AddressResolverGroup<T>` 负责**为每个 `EventExecutor` 创建并缓存一个独立的 resolver 实例**（用 `IdentityHashMap` 按 `EventExecutor` 维度隔离），并在 `EventExecutor` 终止时自动关闭对应 resolver：

```java
// 源码：resolver/src/main/java/io/netty/resolver/AddressResolverGroup.java:43,57,86
private final Map<EventExecutor, AddressResolver<T>> resolvers = new IdentityHashMap<>();
public AddressResolver<T> getResolver(final EventExecutor executor) { ... }
executor.terminationFuture().addListener(terminationListener);
```

---

## DnsNameResolver and DnsNameResolverBuilder

`DnsNameResolver` 是 `resolver-dns` 的核心异步 DNS 客户端，本身继承 `InetNameResolver`（即 `SimpleNameResolver<InetAddress>`），因此其解析结果同样绑定到构造时传入的 `EventLoop`。

通过 `DnsNameResolverBuilder` 配置，关键项与默认值如下（默认值以源码为准）：

| 配置项 | 默认值 | 说明 | 源码 |
|---|---|---|---|
| `queryTimeoutMillis` | `5s`（实际由 `DEFAULT_OPTIONS.timeout()` 决定） | builder 中为 `-1` 哨兵值，由 `DnsNameResolver` 替换为 `DEFAULT_OPTIONS.timeout()` | `DnsNameResolverBuilder.java:62`、`DnsNameResolver.java:450` |
| `resolvedAddressTypes` | 依 JVM 协议栈推导（`IPV4_ONLY` / `IPV4_PREFERRED` / `IPV6_PREFERRED`） | 见 `DEFAULT_RESOLVE_ADDRESS_TYPES` 计算逻辑 | `DnsNameResolverBuilder.java:63`、`DnsNameResolver.java:160-167` |
| `recursionDesired` | `true` | 发送 DNS 查询时置 RD 标志 | `DnsNameResolverBuilder.java:65` |
| `maxQueriesPerResolve` | `16`（由 `DEFAULT_OPTIONS.attempts()` 决定） | builder 中为 `-1` 哨兵值 | `DnsNameResolverBuilder.java:66`、`DnsNameResolver.java:453`、`UnixResolverOptions.java:74` |
| `maxPayloadSize` | `4096` | EDNS0 UDP 报文上限（字节） | `DnsNameResolverBuilder.java:68` |
| `optResourceEnabled` | `true` | 是否自动附加 OPT 记录（EDNS0） | `DnsNameResolverBuilder.java:69` |
| `minTtl` / `maxTtl` | `0` / `Integer.MAX_VALUE`（即 `Cache.MAX_SUPPORTED_TTL_SECS`） | 对服务器下发 TTL 做钳制，默认完全尊重服务器 TTL | `DnsNameResolverBuilder.java:591`、`DefaultDnsCache.java:71` |
| `negativeTtl` | `0`（禁用负缓存） | 失败查询的缓存时长 | `DnsNameResolverBuilder.java:591`、`DefaultDnsCache.java:112` |
| `ndots` | `1` | 触发绝对查询所需的最少点号数 | `UnixResolverOptions.java:72` |
| `dnsServerAddressStreamProvider` | `DnsServerAddressStreamProviders.platformDefault()` | DNS 服务器来源 | `DnsNameResolverBuilder.java:71` |

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsNameResolver.java:448-453
this.queryTimeoutMillis = queryTimeoutMillis >= 0 ? queryTimeoutMillis
        : TimeUnit.SECONDS.toMillis(DEFAULT_OPTIONS.timeout());
this.resolvedAddressTypes = resolvedAddressTypes != null ? resolvedAddressTypes : DEFAULT_RESOLVE_ADDRESS_TYPES;
this.maxQueriesPerResolve = maxQueriesPerResolve > 0 ? maxQueriesPerResolve : DEFAULT_OPTIONS.attempts();
```

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/UnixResolverOptions.java:72-74
private int ndots = 1;
private int timeout = 5;
private int attempts = 16;
```

> [!NOTE]
>
> 4.2 中地址族类型由 `InternetProtocolFamily` 迁移到 `SocketProtocolFamily`：`computeResolvedAddressTypes(InternetProtocolFamily...)` 已 `@Deprecated`，应改用 `toResolvedAddressTypes(SocketProtocolFamily...)`（源码：`DnsNameResolverBuilder.java:374,403`）。此外 4.2 新增 `datagramChannelStrategy`，默认 `DnsNameResolverChannelStrategy.ChannelPerResolver`（源码：`DnsNameResolverBuilder.java:81`）。

`resolvedAddressTypes` 的可选值定义在 `ResolvedAddressTypes` 枚举中：`IPV4_ONLY`、`IPV6_ONLY`、`IPV4_PREFERRED`、`IPV6_PREFERRED`：

```java
// 源码：resolver/src/main/java/io/netty/resolver/ResolvedAddressTypes.java:21-38
public enum ResolvedAddressTypes { IPV4_ONLY, IPV6_ONLY, IPV4_PREFERRED, IPV6_PREFERRED }
```

---

## DNS Server Address Source

DNS 服务器地址由 `DnsServerAddressStreamProvider` 接口提供，按主机名返回一个 `DnsServerAddressStream`（一组按某种策略排列的服务器地址）。

`DefaultDnsServerAddressStreamProvider` 是“兜底”实现：在非 Android/非 Windows 平台优先读取 `/etc/resolv.conf` 的 `nameserver`，失败再回退到 JNDI（`DirContextUtils`）；Windows 上直接用 JNDI。目标端口固定为 `53`：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DefaultDnsServerAddressStreamProvider.java:48,58,67
static final int DNS_PORT = 53;
defaultNameServers.addAll(ResolvConf.system().getNameservers());
DirContextUtils.addNameServers(defaultNameServers, DNS_PORT);
```

`DnsServerAddressStreamProviders.platformDefault()` 在 macOS 上尝试通过反射加载 `MacOSDnsServerAddressStreamProvider`（需 `netty-resolver-dns-native-macos` 依赖），否则回退到 `unixDefault()`；后者用一个内部 `Holder` 包裹，并**每 5 分钟刷新一次**系统 DNS 配置（与 OpenJDK 行为一致）：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsServerAddressStreamProviders.java:101,120,124
public static DnsServerAddressStreamProvider platformDefault() { ... }
private static final long REFRESH_INTERVAL = TimeUnit.MINUTES.toNanos(5);
```

服务器地址的“排列/选择策略”由以下类实现（注意：**源码中并不存在 `RoundRobinDnsServerAddressStream` 这个类**，服务器级轮询通过 `DnsServerAddresses.rotational(...)` 提供）：

- `SequentialDnsServerAddressStream`：顺序尝试。
- `ShuffledDnsServerAddressStream`：每次取出时打乱顺序。
- `SingletonDnsServerAddressStreamProvider` / `MultiDnsServerAddressStreamProvider` / `UniSequentialDnsServerAddressStreamProvider`：组合不同的 provider。
- `ThreadLocalNameServerAddressStream`：按线程隔离的地址流（builder 默认用它包裹 `provider`）。
- `DnsServerAddresses.rotational(...)`：服务器级 round-robin（源码：`DnsServerAddresses.java:126`）。

在 K8s / 容器等自定义环境，只需实现 `DnsServerAddressStreamProvider`（或组合上述 provider），通过 `DnsNameResolverBuilder.nameServerProvider(...)` 注入即可：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsNameResolverBuilder.java:531
public DnsNameResolverBuilder nameServerProvider(DnsServerAddressStreamProvider dnsServerAddressStreamProvider) { ... }
```

---

## Cache

`DnsCache` 接口与 `DefaultDnsCache` 是成功的 A/AAAA 解析结果的缓存，底层是一个 `ConcurrentMap`，按主机名（末尾补 `.`）聚合多条 `DnsCacheEntry`：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DefaultDnsCache.java:41,43
public class DefaultDnsCache implements DnsCache {
    private final Cache<DefaultDnsCacheEntry> resolveCache = new Cache<DefaultDnsCacheEntry>() { ... };
```

TTL 策略：

- 默认 `minTtl=0`、`maxTtl=Integer.MAX_VALUE`，即**完全尊重 DNS 服务器下发的 TTL**；可通过 `builder.ttl(min, max)` 对 TTL 做钳制，避免过小/过大 TTL 带来的抖动或陈旧。
- `negativeTtl` 支持**负缓存**（NXDOMAIN 等失败结果），默认 `0` 即不缓存失败结果；设为正值可在解析失败时短路，降低对故障域名的重复查询：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DefaultDnsCache.java:70,112
public DefaultDnsCache() { this(0, Cache.MAX_SUPPORTED_TTL_SECS, 0); }
public int negativeTtl() { return negativeTtl; }   // 默认 0，禁用负缓存
```

`AuthoritativeDnsServerCache` / `DefaultAuthoritativeDnsServerCache` 缓存**权威 NS 服务器**，用于加速对某一域后续查询时直接命中权威服务器、减少迭代查询跳数。另有 `NoopDnsCache` / `NoopAuthoritativeDnsServerCache` / `NoopDnsCnameCache` 表示不缓存。

缓存的价值在于：减少重复 UDP 查询、降低平均解析延迟，并通过 `maxNumConsolidation` 合并同一主机名并发在途查询（只发一次真实查询，结果级联给其余 future）。

---

## Load Balancing and Address Ordering

当一次解析返回多个地址时，排序与负载分摊由两层协作完成：

1. **地址族排序**：`PreferredAddressTypeComparator` 依据 `resolvedAddressTypes` 的首选族（IPv4 / IPv6）把同类地址排到前面：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/PreferredAddressTypeComparator.java:48-53
public int compare(InetAddress o1, InetAddress o2) {
    if (o1.getClass() == o2.getClass()) { return 0; }
    return preferredAddressType.isAssignableFrom(o1.getClass()) ? -1 : 1;
}
```

2. **客户端侧 round-robin**：`RoundRobinInetAddressResolver`（位于 `resolver` 模块）在 `resolve` 时**随机挑一个**地址，在 `resolveAll` 时**对整个列表做随机旋转**（`Collections.rotate`），从而让多个连接均匀分摊到不同 IP：

```java
// 源码：resolver/src/main/java/io/netty/resolver/RoundRobinInetAddressResolver.java:62,81
promise.setSuccess(inetAddresses.get(randomIndex(numAddresses)));
Collections.rotate(result, randomIndex(inetAddresses.size()));
```

`RoundRobinDnsAddressResolverGroup` 就是把 `DnsNameResolver` 包进 `RoundRobinInetAddressResolver` 的便捷 `AddressResolverGroup`：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/RoundRobinDnsAddressResolverGroup.java:64
return new RoundRobinInetAddressResolver(eventLoop, resolver).asAddressResolver();
```

3. **多 DNS 服务器查询**：`DatagramDnsQueryContext` 按 `DnsServerAddressStream` 顺序向各服务器发 UDP 查询，命中即返回；这与上面的地址级轮询是不同维度（一个是“问哪个 DNS 服务器”，一个是“连接哪个解析结果 IP”）。

---

## Supported Record Types

`DnsNameResolver` 既能解析成 `InetAddress`（A/AAAA，经 `resolve(String)` / `resolveAll(String)`），也能解析任意记录类型。所有记录类型常量定义在 `codec-dns` 的 `DnsRecordType` 中（含 `A`、`AAAA`、`CNAME`、`MX`、`TXT`、`PTR`、`NS`、`SRV` 等）：

```java
// 源码：codec-dns/src/main/java/io/netty/handler/codec/dns/DnsRecordType.java:125
public static final DnsRecordType SRV = new DnsRecordType(0x0021, "SRV");
```

对任意记录类型的通用解析入口返回 `List<DnsRecord>`：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsNameResolver.java:893
public final Future<List<DnsRecord>> resolveAll(DnsQuestion question) { ... }
```

> [!NOTE]
>
> 源码中**不存在** `SrvRecord` / `SrvResolver` 这样的专用类。SRV（以及 TXT、MX、PTR、CNAME 等）均以**通用 `DnsRecord`** 形式通过 `resolveAll(new DefaultDnsQuestion(name, SRV))` 返回（测试见 `resolver-dns/.../DnsNameResolverTest.java:3950`）。这与“把 SRV 解析成连接地址”不同：SRV 主要用于**服务发现**——返回 `target 主机名 + 端口 + 优先级/权重`，调用方再对 `target` 做一次 A/AAAA 解析得到可连接地址。

---

## EDNS0

EDNS0（RFC 6891）通过在查询中附加一个 OPT 伪记录来声明本端能接收的 UDP 报文大小，从而避免大响应被截断后被迫回退 TCP。`DnsNameResolver` 在 `optResourceEnabled`（默认 `true`）开启时，用 `maxPayloadSize`（默认 `4096`）作为 OPT 记录的 UDP payload size 字段构造 OPT 伪记录：

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsNameResolver.java:1463
final int payloadSize = isOptResourceEnabled() ? maxPayloadSize() : 0;
```

```java
// 源码：resolver-dns/src/main/java/io/netty/resolver/dns/DnsQueryContext.java:110-114
// Only add the extra OPT record if there is not already one ... as per RFC 6891
!hasOptRecord(additionals)) {
    optResource = new AbstractDnsOptPseudoRrRecord(maxPayLoadSize, 0, 0) { ... };
```

当响应被标记 `TC`（truncated）且已配置 `socketChannelFactory` 时，`DnsNameResolver` 会按 RFC 7766 回退到 TCP 重试。

---

## Comparison with JDK InetAddress.getByName

| 维度 | JDK `InetAddress.getByName` | Netty `DnsNameResolver` |
|---|---|---|
| 阻塞模型 | 调用线程**阻塞**直到解析完成或超时 | **非阻塞**，返回 `Future`，回调在 `EventLoop` 上 |
| 驱动线程 | 调用方线程 | 由构造传入的 `EventLoop` 驱动 I/O 与回调 |
| 超时/重试 | 依赖 JDK 内部实现，难以细配 | `queryTimeoutMillis`、`maxQueriesPerResolve` 可配 |
| 缓存 | JDK 自带且不可控 | `DnsCache`/`DefaultDnsCache` 可配 TTL 与负缓存 |
| 多地址分摊 | 无 round-robin | `RoundRobinInetAddressResolver` 随机挑选/旋转 |
| 记录类型 | 仅 A/AAAA（主机名→地址） | A/AAAA/CNAME/MX/TXT/PTR/NS/SRV（通用 `DnsRecord`） |
| SRV / TXT | 不支持 | 支持（经 `resolveAll(DnsQuestion)`） |
| EDNS0 | 不支持 | `optResourceEnabled` + `maxPayloadSize` 支持，避免截断走 TCP |
| DNS 服务器来源 | 系统配置，不可控 | `DnsServerAddressStreamProvider` 可自定义（容器/K8s） |
| IPv4/IPv6 偏好 | 系统属性 | `ResolvedAddressTypes` 精细控制 |

`DefaultNameResolver` 虽然返回 `Future`，但其底层仍是 JDK 阻塞查找，因此它**不属于真正的非阻塞 DNS**——生产环境应优先使用 `DnsNameResolver`。

---

## Practical Usage

客户端通常通过 `AddressResolverGroup` 接入解析器，而不是直接 `new` resolver。Netty 提供：

- `DnsAddressResolverGroup`：标准 DNS 解析组。
- `RoundRobinDnsAddressResolverGroup`：在解析结果上做 round-robin。
- `DefaultAddressResolverGroup`：基于 `DefaultNameResolver` 的默认组（阻塞式，需谨慎）。

在 `Bootstrap` 上通过 `resolver(AddressResolverGroup)` 设置：

```java
// 源码：resolver/src/main/java/io/netty/resolver/DefaultAddressResolverGroup.java
// Bootstrap bootstrap = ...;
// bootstrap.resolver(DefaultAddressResolverGroup.INSTANCE);
```

自定义 DNS 服务器与 TTL 的典型写法：

```java
EventLoop eventLoop = ...;
DnsNameResolver resolver = new DnsNameResolverBuilder(eventLoop)
        .nameServerProvider(new SingletonDnsServerAddressStreamProvider(        // 自定义 DNS 来源
                new InetSocketAddress("10.0.0.1", 53)))
        .ttl(60, 300)            // 钳制缓存 TTL 在 60~300 秒
        .negativeTtl(30)         // 失败结果缓存 30 秒
        .maxPayloadSize(4096)    // EDNS0
        .optResourceEnabled(true)
        .build();
```

`DnsNameResolverBuilder` 还提供 `ttl(int,int)` 与 `negativeTtl(int)` 用于缓存调优（源码：`DnsNameResolverBuilder.java:336,348`），以及 `nameServerProvider(...)` 注入自定义 provider（源码：`DnsNameResolverBuilder.java:531`）。

---

## Links

- /docs/CS/Framework/Netty/Netty.md
- /docs/CS/Framework/Netty/Bootstrap.md
- /docs/CS/Framework/Netty/EventLoop.md
- /docs/CS/Framework/Netty/ChannelHandler.md
- /docs/CS/Framework/Netty/Transport.md

## References

- DNS 协议基础与消息格式：RFC 1035 — https://www.rfc-editor.org/rfc/rfc1035
- IPv6 地址记录（AAAA）：RFC 3596 — https://www.rfc-editor.org/rfc/rfc3596
- SRV 记录（服务定位）：RFC 2782 — https://www.rfc-editor.org/rfc/rfc2782
- EDNS0 扩展机制：RFC 6891 — https://www.rfc-editor.org/rfc/rfc6891
- DNS 的 TCP 回退：RFC 7766 — https://www.rfc-editor.org/rfc/rfc7766
- Netty 官方文档（DNS resolver）：https://netty.io/wiki/name-resolution.html
