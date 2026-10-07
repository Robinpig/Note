## Introduction

[Protocol Buffers](https://protobuf.dev/)（protobuf / protobuf）是 Google 开源的一种**语言中立、平台中立、可扩展**的结构化数据序列化机制：
先用 IDL 在 `.proto` 文件中定义消息结构与服务，再由 `protoc` 生成各语言的类型与编解码代码。
它是 [gRPC](/docs/CS/Framework/gRPC/gRPC.md) 的默认编码，也被广泛用于配置、存储与跨语言数据交换。

## Wire Format

protobuf 编码紧凑的关键有三点：

- **字段靠编号（field number）而非名字标识**。线上字节流里只有编号和值，没有字段名，因此短而快；字段名只是给人读的源码符号。
- **TLV 风格的 tag-length-value**。tag 由 `(field_number << 3) | wire_type` 组成，wire type 标明值的种类（varint、定长 64 位、length-delimited、定长 32 位等）。
- **varint 变长整数**。小整数只占 1 字节，数值越大占用越多，大多数 id/计数都很小，因此平均开销低。

```proto
syntax = "proto3";

message User {
  int64  id    = 1;           // = 1 是字段编号，线上靠它识别
  string name  = 2;
  repeated string roles = 3;  // repeated：可重复，编码为多个同 tag 字段
}
```

字段编号一旦投入使用就**不能再复用或改义**，它是二进制兼容的锚点（1~15 编码为单字节 tag，高频字段应优先占用）。

## Schema Evolution

protobuf 把前后向兼容做成默认行为，以支撑滚动升级（新老版本节点混跑）：

- **新增字段**：分配一个**新的、从未用过的编号**。老代码读到不认识的编号，按 wire type 跳过即可（前向兼容：老代码读新数据不报错）。
- **删除字段**：保留其编号为 `reserved`，防止将来有人复用旧编号导致语义错乱；新代码读旧数据时缺失字段取类型默认值。
- **默认值**：proto3 中未设置的标量字段取零值（0、空串、false），因此线上无法区分「显式设为零值」与「未设置」，需要区分时用 `optional`（带 presence）或 wrapper 类型。
- 不能安全地改字段编号、不能随意改字段的 wire type（部分数值类型间可兼容，需查兼容表）。

兼容性纪律：**字段名可改（编号不变即可），编号绝不可复用**。

## proto2 and proto3

| 维度 | proto2 | proto3 |
| --- | --- | --- |
| 字段存在性 | 默认有 has/set，标量可区分未设置 | 默认无 presence，零值即默认；可用 `optional` 恢复 |
| required | 支持（但实践证明有害，易造成严格不兼容） | 移除 required |
| 枚举 | 允许不从 0 开始 | 首项必须是 0 值 |
| 扩展 | `extensions`/`extend` | 用 `Any`、`oneof`、`map` 等 |
| 现状 | 遗留系统 | 新项目默认 |

## Services

protobuf 不仅定义消息，还能定义 RPC 服务契约，再由 gRPC 等插件生成 client/server 桩：

```proto
service UserService {
  rpc GetUser(GetUserReq) returns (User);
}
```

这与 RPC 的 [Parameter Marshalling](/docs/CS/Distributed/RPC/RPC.md) 直接对应：stub 用 protobuf 编码请求、解码响应。

## Comparison

| 维度 | protobuf | JSON | Thrift | Java 原生序列化 |
| --- | --- | --- | --- | --- |
| 编码 | 二进制、字段编号 | 文本、字段名 | 二进制 | 二进制 |
| schema | 强制 `.proto` | 无（JSON Schema 可选） | 强制 `.thrift` | 类本身 |
| 跨语言 | 强 | 强 | 强 | 仅 Java |
| 兼容演进 | 编号规则明确 | 宽松 | 支持 | 脆弱 |
| 可读性 | 需工具解码 | 直接可读 | 需工具 | 不可读 |
| 反射/动态消息 | 有 DynamicMessage/Descriptor | 天然动态 | 有 | 反射 |

与更高性能的 JIT 序列化框架（如 [Fury](/docs/CS/Distributed/RPC/Fury.md)）相比，protobuf 的优势在强契约、跨组织兼容与生态，而非极限吞吐。
更完整的编码格式取舍（语言特定格式 / 文本格式 / 二进制 schema 格式）见 [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md)。

## Links

- [Encoding](/docs/CS/Distributed/RPC/Marshalling.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)
- [RPC](/docs/CS/Distributed/RPC/RPC.md)
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md)
- [Fury](/docs/CS/Distributed/RPC/Fury.md)

## References

1. [Protocol Buffers Documentation](https://protobuf.dev/)
2. [Protocol Buffer Encoding](https://protobuf.dev/programming-guides/encoding/)
3. [Language Guide (proto3)](https://protobuf.dev/programming-guides/proto3/)
