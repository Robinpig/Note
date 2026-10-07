## Introduction

[Fury](https://fury.apache.org/) 是 Apache 基金会下的一款多语言（Java/Python/Go/JavaScript/Rust/C++ 等）高性能序列化框架，
定位是比 JSON、[Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)、[Thrift](/docs/CS/Distributed/RPC/Thrift.md)
更快的对象序列化，同时保持对 Java 对象图（共享引用、循环引用、多态）的完整表达能力。它既可以用作 RPC 的编解码层，也可以用于数据缓存、跨语言数据交换。

## 设计

Fury 性能的关键来自两点：JIT 化的序列化器与元数据共享。

### JIT 序列化器

- 不要在热路径上用反射逐字段读写。Fury 在运行时为每个类**动态生成并编译**专用的 serializer（Java 侧用 Janino/ASM 字节码，其它语言走等价的 codegen），
  把字段偏移、布局在编译期摊平，序列化/反序列化接近手写代码的速度。
- 支持 `register(Class)` 预注册类并分配稳定的 class id，链路中只传 id，不传类名字符串。

### MetaShare（元数据共享）

在一条持久连接 / 一个会话内，同一类被反复序列化时，其结构元数据（字段名、类型、布局）只在**第一次**发送，后续报文只传一个元数据版本号，
接收方按号查回本地缓存的元数据。这就是「元数据共享模式」——把 Class 的元数据统一存放在会话上下文，而不是每条消息重复携带。

- 短消息、对象字段名长时，节省尤为明显（字段名往往比数据还占空间）；
- 对同一连接上反复交换同类对象的 RPC 场景，体积与 CPU 都显著下降。

### 引用与多态（Reference & Polymorphism）

- 默认支持**共享引用与循环引用**：通过引用表（ref id）去重，对象图序列化后仍是同一对象，不会像很多框架那样把共享引用复制成两份。
- 支持多态：无需 IDL 即可序列化接口/抽象类的实际运行时类型，这对 Java 领域对象（含继承、泛型集合）很友好，也是 Protobuf 这类严格 schema 格式的弱项。

## 对比

| 维度 | Fury | Protobuf | Java 原生序列化 | JSON |
| --- | --- | --- | --- | --- |
| IDL/schema | 可选（也可直接序列化 POJO） | 必须 `.proto` | 无需 | 无需 |
| 跨语言 | 多语言 | 多语言（最广） | 仅 Java | 全语言 |
| 元数据开销 | 会话内共享，首条后近乎为零 | 字段编号，无字段名 | 类描述冗长 | 每条都带字段名 |
| 共享/循环引用 | 支持 | 不支持（无对象图语义） | 支持 | 不支持 |
| 多态 | 原生支持 | 需 `oneof`/Any 模拟 | 支持 | 弱 |
| 演进兼容 | 兼容（需注意注册/字段策略） | 前后向兼容语义明确 | 脆弱 | 宽松 |
| 可读性 | 二进制 | 二进制 | 二进制 | 文本可读 |

总体取向：**追求极致性能、对象图复杂、以 Java/多语言 RPC 与缓存为主**时 Fury 合适；
而需要严格 schema 契约、跨组织接口、长期存档时，[ProtoBuf](/docs/CS/Distributed/RPC/ProtoBuf.md) 的兼容性纪律更稳妥。
Fury 属于二进制编码范畴，与 [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) 中讨论的各类编码格式是同一问题空间。

## Links

- [RPC](/docs/CS/Distributed/RPC/RPC.md)
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md)
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md)
- [Java 原生序列化](/docs/CS/Java/JDK/Basic/serialize.md)

## References

1. [Apache Fury](https://fury.apache.org/)
2. [Apache Fury (GitHub)](https://github.com/apache/fury)
