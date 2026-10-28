## Introduction

Memcached 支持**三种协议**，共用同一个 TCP 端口——服务端通过首包的特征自动识别：

1. **文本协议（Text Protocol）**：最通用，命令以 `\r\n` 分隔，行式输入，适合 `telnet` 调试和脚本快速接入。
2. **二进制协议（Binary Protocol）**：字段化固定格式，省掉分隔符解析，适合极低延迟的高并发客户端。
3. **Meta 协议（Meta Text Protocol，1.6.0+）**：在文本协议之上扩展，用 `mc.mget` / `mc.set` 等带 `E` 标志位的命令支持 CAS value 和客户端自定义版本戳。

客户端库通常同时支持文本和二进制，让用户按需切换。Meta 协议是较新的增量，只有较新的客户端才会实现。

### Auto-Detection

服务端识别顺序：

1. 如果首包以二进制协议的 magic byte（请求是 `0x80`，响应是 `0x81`）开头 → 走二进制。
2. 如果首包以 `mc.` 开头 → 走 Meta 文本协议。
3. 否则 → 走标准文本协议。

### Error Responses

三种协议的错误响应码/文本：

| 文本协议 | 二进制 status | 含义 |
| :-- | :-- | :-- |
| `ERROR` | 0x01 | 客户端发送了不存在的命令 |
| `CLIENT_ERROR <msg>` | 0x03 | 客户端输入格式错误（key 过长、参数缺失等） |
| `SERVER_ERROR <msg>` | 0x04 | 服务端内部错误 |
| — | 0x02 | key 不存在 |
| — | 0x05 | value 过大（超过 `-I` 限制） |
| — | 0x06 | 内存不足（默认不触发，因为会先淘汰） |
| — | 0x07 | CAS 不匹配 |

## Text Protocol

### Request Format

命令行以 `\r\n` 结尾。存储命令需要额外的一行数据：

```
<command> <key> [flags] [exptime] <bytes> [noreply]\r\n
<data>\r\n
```

非存储命令没有 data 行：

```
<command> [args...]\r\n
```

### Key Constraints

- 最大 250 字节（`MAX_KEY_LENGTH 250`）。
- 不能包含空格、换行或控制字符（除了可以包含 `\0`，服务端做 C 字符串截断）。
- 大小写敏感（直接 `memcmp`）。

### Value Constraints

- 默认最大 1 MB（`-I` 参数可调）。
- Opaque——服务端完全不解析其内容。

## Binary Protocol

### Header Format

每个请求和响应都以固定 24 字节的 header 开头：

```
Byte  0       : magic (0x80 request / 0x81 response)
Byte  1       : opcode (命令码)
Byte  2-3     : key length (big-endian)
Byte  4       : extras length
Byte  5       : data type (通常 0x00)
Byte  6-7     : status (响应时用)
Byte  8-11    : total body length (big-endian)
Byte  12-15   : opaque (原样回传，客户端匹配请求用)
Byte  16-23   : CAS (8 字节，条件更新用)
```

body = extras（命令特定扩展字段）+ key + value。

### Opcode Map

| Opcode | 命令 |
| :-- | :-- |
| 0x00 | GET |
| 0x01 | SET |
| 0x02 | ADD |
| 0x03 | REPLACE |
| 0x04 | DELETE |
| 0x05 | INCREMENT |
| 0x06 | DECREMENT |
| 0x07 | QUIT |
| 0x08 | FLUSH |
| 0x09 | GETQ（quiet，批量获取不逐个回） |
| 0x0A | NOOP |
| 0x0B | VERSION |
| 0x0C | GETK |
| 0x0D | GETKQ |
| 0x0E | APPEND |
| 0x0F | PREPEND |
| 0x10 | STAT |
| 0x11 | SETQ / ADDQ / REPLACEQ |
| 0x12 | DELETEQ |
| 0x13 | INCREMENTQ / DECREMENTQ |
| 0x14 | QUITQ |
| 0x15 | FLUSHQ |
| 0x19 | APPENDQ / PREPENDQ |
| 0x20 | TOUCH |
| 0x21 | GAT |

Q 结尾的命令（quiet variants）是优化：一次性发多个，不需要每个都等响应——只在出错时才回。这是 Memcached 高并发批处理的关键。

## Meta Text Protocol（1.6.0+）

Meta 协议是对文本协议的扩展，前缀统一为 `mc.`。它的核心新增能力：

1. **`mc.mget` / `mc.set`**：批量操作，一个请求多个 key。
2. **`E` flag**：客户端可以在写入时自带版本戳（CAS value），服务端只在服务端当前 CAS value ≤ 客户端提供的值时才写入——这实现了客户端驱动的乐观并发控制。
3. **`cas` flag**：请求响应中自带 CAS value，客户端下次条件更新时可以带上。
4. **`ttl` flag**：请求中直接带 TTL 秒数，而不是用旧的 `exptime` 字段。
5. **`noreply` flag**：静默模式，批量操作时进一步压减响应。

### Example

```
mc.mget a b c\r\n
E a=1 b=3 c=5\r\n    # 每个 key 自带 CAS value，客户端用它来做条件更新
```

写入时：

```
mc.set foo flags=0 exptime=3600 cas=7\r\n
<data>\r\n
```

### When to Use

Meta 协议适合需要**在客户端做跨 key 一致性控制**的场景（比如多阶段流水线处理、分布式乐观锁），或者 Meta Proxy 下 Lua 脚本需要精确控制缓存行为的场景。纯缓存命中场景用文本协议或二进制协议就够了。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Commands](/docs/CS/DB/Memcached/Commands.md)
- [Proxy](/docs/CS/DB/Memcached/Proxy.md)

## References

1. [Memcached GitHub — doc/protocol.txt](https://github.com/memcached/memcached/blob/master/doc/protocol.txt) — 文本协议规范
2. [Memcached GitHub — doc/protocol-binary.xml](https://github.com/memcached/memcached/blob/master/doc/protocol-binary.xml) — 二进制协议规范
3. [Memcached Documentation — Meta Text Protocol](http://docs.memcached.org/protocols/meta/) — Meta 协议文档
