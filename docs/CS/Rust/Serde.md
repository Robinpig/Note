## Introduction

serde 是 Rust 生态里最接近"标准库之一"的 crate：`serde` 定义 `Serialize` / `Deserialize` 两个 trait，`#[derive]` 由 [Proc_Macro](/docs/CS/Rust/Proc_Macro.md) 生成实现，而每种格式（JSON、bincode、TOML、MessagePack……）是各自独立的 crate。这个三分法是它成功的关键：**trait 归语言层、生成归编译期、格式归生态**，于是"换格式"通常只改一行 `Cargo.toml` 和两个函数名。

本篇讲三件事：数据模型（`Serializer` / `Deserializer` 这对 trait 到底抽象了什么）、derive 的属性体系、以及零拷贝反序列化这个 serde 最独有的能力。版本事实：写作时 **serde 1.0.229（2026-07-18 发布）**，MSRV 核心 1.56、derive 1.71（2026-02 提升），`serde_json` 1.0.154（2026-10-11）；仓库已拆出 `serde_core`（1.0.229 同步发布）并把 `serde_derive` 的依赖升到 syn 3。

## The Data Model

serde 的核心抽象只有两个 trait，方向相反：

```rust
trait Serialize {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error>;
}
trait Deserialize<'de>: Sized {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error>;
}
```

`Serialize` 侧，你的类型把自己"描述"成一系列原语调用（`serialize_u32`、`serialize_str`、`serialize_seq`、`serialize_map`、`serialize_struct`……）；`Deserialize` 侧，格式反过来调用你的类型的 `Visitor`（`visit_u32`、`visit_str`、`visit_seq`、`visit_map`……）。**两个 trait 都不认识 JSON**——它们只认识一个中立的数据模型：32 个左右的原语 + 四种复合结构（seq / tuple / map / struct）。

这个中介层带来三个直接后果：

1. **N×M 变成 N+M**：`类型数 × 格式数` 的组合里，类型实现一次 `Serialize`、格式实现一次 `Deserializer`，全部互通。
2. **错误类型由格式定**：`serde_json::Error` 带行列号，`bincode::Error` 不带——因为 JSON 有文本位置，二进制没有。
3. **自描述能力可裁剪**：JSON 需要知道字段名（`serialize_struct` 带名字），二进制格式通常忽略它——同一份 derive 代码在两种格式下编出不同的字节流。

### Self-Describing vs Non-Self-Describing

判断一个格式"要不要知道你的类型"的术语：

| 类型 | 格式 | 含义 |
| :--- | :--- | :--- |
| 自描述 | JSON / TOML / YAML / MessagePack | 字节里带字段名与结构，缺字段能发现、多字段能忽略 |
| 非自描述 | bincode / postcard / rkyv 的旧版 | 字节就是字段的顺序快照，**schema 必须两侧一致**，改结构即不兼容 |

选型第一问：**这个数据会不会离开你的进程**。跨进程/跨版本/跨语言，选自描述；同进程内、同版本、性能敏感，选非自描述。

## The Derive Attributes

derive 生成的代码把"字段名怎么映射、哪个字段可选、缺失怎么办"全部参数化，常用属性：

| 属性 | 位置 | 作用 |
| :--- | :--- | :--- |
| `#[serde(rename = "...")]` | 字段 / 变体 | 改字节里的名字（ snake_case → camelCase 一类） |
| `#[serde(rename_all = "...")]` | 容器 | 批量改（`"camelCase"` / `"SCREAMING_SNAKE_CASE"`） |
| `#[serde(default)]` | 字段 | 反序列化缺失时用 `Default::default()` |
| `#[serde(skip)]` | 字段 | 完全不参与（序列化跳过、反序列化用 default） |
| `#[serde(alias = "...")]` | 字段 | 反序列化时接受另一个名字 |
| `#[serde(deny_unknown_fields)]` | 容器 | 出现未知字段报错（防 typo，但**破坏前向兼容**） |
| `#[serde(flatten)]` | 字段 | 把内层结构的字段拍平到外层 map |
| `#[serde(tag = "type")]` | enum | 内部标签表示（`{"type": "A", ...}`） |
| `#[serde(untagged)]` | enum | 无标签，按顺序尝试匹配（错误信息差） |
| `#[serde(with = "...")]` | 字段 | 换一套序列化函数（如 `chrono` 时间） |
| `#[serde(borrow)]` | 字段 | 反序列化时借用输入（`Cow<'a, str>` / `&'a str`） |

三条经验：

1. **`deny_unknown_fields` 与前向兼容互斥**：加上它，对端新增字段你的反序列化就炸。API 边界默认不加，内部配置可以加。
2. **`default` + `Option` 是两回事**：`Option<T>` 字段缺失时 serde 默认填 `None`，不需要显式 `default`；显式写 `default` 反而把"字段不存在"和"字段是 null"混为一谈。
3. **枚举的三种表示**（外部标签 `{"A": ...}`、内部标签 `{"type": "A"}`、无标签）改一个就换 wire format，跨语言对接时先和对方确认——这是 serde 最常见的"能编过但对面读不了"来源。

## Zero-Copy Deserialization

serde 最有独占性的能力：**反序列化时直接借用输入缓冲，不分配**。`&str` 与 `String` 字段的取舍是同一份数据的两种命运：

```rust
#[derive(Deserialize)]
struct Borrowed<'a> {
    name: &'a str,                    // 零分配：直接指向输入
    tags: Vec<Cow<'a, str>>,          // 输入里未转义的借用，转义的才分配
}

#[derive(Deserialize)]
struct Owned {
    name: String,                     // 每个字段一次分配 + 拷贝
}
```

机制：`Deserialize<'de>` 的生命周期参数贯穿整条 visitor 链，`&'a str` 字段在 `visit_str` 时拿到的是**输入缓冲的切片**（serde_json 的 `from_str` 输入本身就是 `&str`，切片即零拷贝）。`#[serde(borrow)]` 在类型推断不明显处显式开启它。

适用与边界：

| 场景 | 用借用 | 原因 |
| :--- | :--- | :--- |
| 读一次就丢的大 JSON | `Owned` | 借用型数据活不过输入缓冲，后续处理反而受限 |
| 输入缓冲自己管理生命周期的解析 | `Borrowed` | 一次解析零分配 |
| 需要转义处理的字符串（`\n` 一类） | `Cow` | serde 自动退化成 `Owned` |

零拷贝的上限是**格式**：JSON 的字符串可能含转义，所以只有 `from_str`（不是 `from_reader` 流式）路径能稳定借用；二进制格式（bincode / postcard）天然零拷贝但要 `borrow` 标注。

## Formats: The Ecosystem

格式选择是 serde 选型的主战场，按维度分：

| 格式 | crate | 自描述 | 零拷贝 | 体积 | 速度量级 | 典型场景 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| JSON | `serde_json` | 是 | 部分 | 大 | 基准 | API、配置、日志 |
| TOML | `toml` | 是 | 否 | 大 | 慢 | 配置文件（`Cargo.toml` 同门） |
| YAML | `serde_yaml`（已归档，见下） | 是 | 否 | 大 | 很慢 | 配置文件、K8s |
| MessagePack | `rmp-serde` | 是 | 否 | 中 | 快 | 跨语言 RPC |
| CBOR | `ciborium` | 是 | 否 | 中 | 快 | IoT、受限设备 |
| bincode | `bincode` | **否** | 是 | 最小 | 最快 | 同版本进程间、缓存 |
| postcard | `postcard` | **否** | 是 | 最小 | 最快 | **no_std / 嵌入式** |
| rkyv | `rkyv` | 否 | **极致** | 最小 | 零反序列化 | 大冷数据 mmap |
| `flexbuffers` | `flexbuffers` | 是 | 否 | 中 | 快 | schemaless 二进制 |

三个需要单独点名的现状：

1. **`serde_yaml` 已归档**（2024 年起 deprecated，官方推荐 `serde_yaml_ng` 或 `serde_norway` 一类 fork）——新项目别再把 `serde-yaml` 加进依赖，这是少数"惯用法会踩归档坑"的地方。
2. **`bincode` 维护慢但生态绑定深**：它的格式细节（varint 编码、`Option` 的 niche 利用）没有正式规范，跨语言实现几乎不存在——它就是"Rust ↔ Rust 同版本"的格式。
3. **`rkyv` 是另一种范式**：它不做"反序列化"，而是把序列化结果直接 mmap 后按原布局访问（零拷贝到极致），代价是访问要走 `Archived` 类型、字段布局随编译器变化——适合"写一次读多次"的冷数据，不适合 API。

## Patterns and Anti-Patterns

**1. 用 `#[serde(tag = "type", content = "data")]` 做多态消息。** 内部标签 + 内容分离的 adjacently tagged 表示是跨语言对接里最稳的枚举形态；`untagged` 省字节但错误信息会退化成"没有一个变体匹配"，排错痛苦。

**2. `deserialize_with` 优先于新建类型。** 时间、十进制 money、十六进制 ID——先用模块级 `with` 函数处理，别急着上 newtype；等校验逻辑（而不只是格式逻辑）出现再 newtype + `TryFrom`（[Type_Conversion](/docs/CS/Rust/Type_Conversion.md)）。

**3. 错误类型对齐调用方的 `?` 链。** `serde_json::Error` 实现了 `std::error::Error`，但要把格式错误转成你的领域错误，实现 `From<serde_json::Error> for MyError`（[Error_Handling](/docs/CS/Rust/Error_Handling.md) 的转换链），而不是在每个调用点 `map_err`。

**4. 别 derive 到过程宏看不见的类型上。** serde 与其它 derive 的叠加（`#[derive(Serialize)]` + 手写 `Deserialize`）完全合法，但顺序敏感：derive 生成的代码引用你的手写实现时，trait bound 要自己加（[Proc_Macro](/docs/CS/Rust/Proc_Macro.md) 的机械 bound 问题）。

**5. no_std 可用。** serde 核心（`serde` + `serde_derive`）是 `#![no_std]` 的——`core::fmt` 就够；`alloc` 让 `Vec` / `String` 字段可用。嵌入式选 postcard + serde 是标准组合（[No_Std](/docs/CS/Rust/No_Std.md)）。

## Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | `deny_unknown_fields` 用在 API 边界 | 对端加字段后反序列化炸 | 默认不加；内部配置才加 |
| 2 | 枚举换了 tag 形态 | 对面读不了 / 你读不了对面 | 对接前确认 wire format，用 adjacently tagged |
| 3 | 非自描述格式改了字段顺序 | 同版本也解错 | bincode/postcard 类改结构 = 破坏性变更，走版本号 |
| 4 | `Option` + `default` 同用 | "缺字段"与 "null" 混淆 | 二选一，想区分就 newtype |
| 5 | 借用字段活过输入缓冲 | 生命周期编译错误 | 输入缓冲与解析结果同生命周期，或改 `Owned` |
| 6 | 新项目用 `serde_yaml` | 依赖已归档 | `serde_yaml_ng` 等 fork |
| 7 | 忘了 `derive` feature | `#[derive(Serialize)]` 找不到 | `features = ["derive"]` |
| 8 | `flatten` + `deny_unknown_fields` 同用 | 编译错误或行为意外 | flatten 拍平后字段归属不定，别叠加 |

## Links

- [Proc_Macro](/docs/CS/Rust/Proc_Macro.md)
- [Type_Conversion](/docs/CS/Rust/Type_Conversion.md)
- [Error_Handling](/docs/CS/Rust/Error_Handling.md)
- [No_Std](/docs/CS/Rust/No_Std.md)
- [集合类型](/docs/CS/Rust/Collections.md)
- [生态选型](/docs/CS/Rust/Ecosystem.md)

## References

1. [serde — Official site](https://serde.rs/)
2. [`serde::Serialize`](https://docs.rs/serde/latest/serde/trait.Serialize.html)
3. [`serde::Deserialize`](https://docs.rs/serde/latest/serde/trait.Deserialize.html)
4. [serde — Container attributes](https://serde.rs/container-attrs.html)
5. [serde — Field attributes](https://serde.rs/field-attrs.html)
6. [serde-rs/serde releases](https://github.com/serde-rs/serde/releases)
