## Introduction

Memcached 的命令集极度收敛——文本协议只有约 12 条命令，这是它能保持高性能和低复杂度的核心设计决策。命令分为四类：**存储、检索、变更、管理**。

所有命令对 key 和 value 的大小有统一约束：key ≤ 250 字节、value ≤ 1 MB（`-I` 参数可调）、总请求（命令 + key + flags + exptime + bytes + value）≤ 最大单次请求大小。

## Storage Commands

所有存储命令的响应都是单行：

| 响应 | 含义 |
| :-- | :-- |
| `STORED\r\n` | 成功 |
| `NOT_STORED\r\n` | 拒绝（ADD 时已存在 / REPLACE 时不存在 / CAS 时版本不匹配） |
| `EXISTS\r\n` | CAS 时发现服务端 CAS value 跟提供的不一致 |
| `NOT_FOUND\r\n` | CAS 时 key 不存在 |

### SET

```
set <key> <flags> <exptime> <bytes> [noreply]\r\n
<value>\r\n
```

无条件写入。key 存在则覆盖（释放旧 chunk、填充新 chunk），不存在则新建。

| 参数 | 含义 |
| :-- | :-- |
| `key` | 缓存键，≤ 250 字节 |
| `flags` | 客户端自定义标志位，原样回传，服务端不做任何解析 |
| `exptime` | 过期时间：0 = 永不过期；< 30 天 = 剩余秒数（相对 TTL）；≥ 30 天 = Unix 时间戳（绝对过期） |
| `bytes` | value 的字节数 |
| `noreply` | 静默模式，不回 `STORED`/`NOT_STORED` |

### ADD

```
add <key> <flags> <exptime> <bytes> [noreply]\r\n
<value>\r\n
```

**仅当 key 不存在时写入**。如果 key 已存在 → `NOT_STORED`。

### REPLACE

```
replace <key> <flags> <exptime> <bytes> [noreply]\r\n
<value>\r\n
```

**仅当 key 存在时覆盖**。如果 key 不存在 → `NOT_STORED`。

### APPEND / PREPEND

```
append <key> <bytes> [noreply]\r\n
<data>\r\n

prepend <key> <bytes> [noreply]\r\n
<data>\r\n
```

在已有 value 的**末尾**（append）或**开头**（prepend）拼接一段新数据。如果 key 不存在 → `NOT_STORED`。flags 和 exptime 保留原值不变。

拼接后新 value 的总长度**不能超过 `-I` 限制**（默认 1 MB）。

### CAS（Compare-And-Swap）

```
cas <key> <flags> <exptime> <bytes> <cas_unique> [noreply]\r\n
<value>\r\n
```

条件写入。`cas_unique` 来自之前 `gets` 命令返回的 CAS value。只在服务端当前 CAS value 与 `cas_unique` 相等时才写入：

| 情况 | 响应 |
| :-- | :-- |
| CAS 匹配，写入成功 | `STORED` |
| CAS 不匹配，key 仍存在 | `EXISTS` |
| key 不存在 | `NOT_FOUND` |

CAS 是 Memcached 提供的唯一的**并发写入保护**机制。多客户端同时更新同一个 key 时，只有拿到正确 CAS value 的那个能写成功，其他的拿到 `EXISTS` 需要重新 GET 再 CAS。

## Retrieval Commands

### GET / GETS

```
get <key> [key2 ...]\r\n
gets <key> [key2 ...]\r\n
```

- `get`：返回 value（不带 CAS value）。
- `gets`：返回 value **和** CAS value（用于后续 CAS 命令）。

支持**批量**——一次命令传多个 key，按 key 在命令中的顺序返回。不存在的 key 不返回任何行（静默跳过）。

响应格式（每个命中的 key 两行）：

```
VALUE <key> <flags> <bytes> [<cas_unique>]\r\n
<value>\r\n
```

所有 key 处理完后，以 `END\r\n` 结束。

### GAT / GATS（Touch-And-Get）

```
gat <exptime> <key> [key2 ...]\r\n
gats <exptime> <key> [key2 ...]\r\n
```

等价于先 `get/gats` 再 `touch`：在返回 value 的同时**重置过期时间**。适合「滑动窗口」场景——只要某个 key 被持续访问就不过期。

## Mutation Commands

### INCR / DECR

```
incr <key> <delta> [noreply]\r\n
decr <key> <delta> [noreply]\r\n
```

对已有数值型 value 做原子增减。

- value 必须是可解析的整数（Memcached 存的是字符串，但要求内容全是数字）。
- key 不存在 → `NOT_FOUND`。
- 结果不会低于 0（`decr` 到 0 就停，不会变负数）。
- 返回增减后的数值。

这是 Memcached 为数不多有运算语义的命令——因为它作用在不透明的字节串上，只在 value 是整数时有效。

## Management Commands

### DELETE

```
delete <key> [<time>] [noreply]\r\n
```

从内存中直接删除 item。`time` 参数（可选，≥ 0）是秒数：删除后 key 在 `time` 秒内不能被重新 `add`/`set`（称为 deferred delete）。

响应：`DELETED` / `NOT_FOUND`。

### TOUCH

```
touch <key> <exptime> [noreply]\r\n
```

仅重置过期时间，不返回 value。key 不存在 → `NOT_FOUND`。

### FLUSH_ALL

```
flush_all [<time>] [noreply]\r\n
```

**立即失效**所有 item（或 `time` 秒后延迟失效）。失效不是物理删除——所有 item 还在内存里，但 `get` 返回 MISS，直到被 LRU 淘汰或被新值覆盖。

响应：`OK`（或 `noreply` 静默）。

### STATS

```
stats\r\n
stats <arg>\r\n
```

返回服务端统计信息，以 `END\r\n` 结束。常用子参数：

| 参数 | 含义 |
| :-- | :-- |
| `stats` | 通用统计（uptime、get/set/eviction 次数、内存总量等） |
| `stats slabs` | 各 slabclass 的 chunk 大小、使用量、分配量 |
| `stats items` | 各 slabclass 的 LRU 统计（HOT/WARM/COLD/TEMP 的数量和年龄） |
| `stats sizes` | 按 size 范围的 item 数量分布 |
| `stats settings` | 服务端启动参数 |
| `lru` | LRU 运行时调优（mode / tune / temp_ttl） |

### QUIT

```
quit\r\n
```

优雅关闭连接。二进制协议有 `QUITQ` 静默变体。

### VERSION

```
version\r\n
```

返回版本字符串，如 `VERSION 1.6.45\r\n`。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Protocol](/docs/CS/DB/Memcached/Protocol.md)
- [Configuration](/docs/CS/DB/Memcached/Configuration.md)

## References

1. [Memcached GitHub — doc/protocol.txt](https://github.com/memcached/memcached/blob/master/doc/protocol.txt) — 命令与协议的权威文档
