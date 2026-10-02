## Introduction

[Jackson](https://github.com/FasterXML/jackson) 是事实上的 Java JSON 标准库（"JSON for Java"），Spring Boot 的 Web/MVC 默认用它完成 `@RequestBody`/`@ResponseBody` 的序列化与反序列化。它有三套模型：**Streaming API**（`JsonParser`/`JsonGenerator`，流式令牌，最快最底层）、**Tree Model**（`JsonNode` 类似 DOM，适合结构不定的报文）、**Databind**（`ObjectMapper` + POJO 绑定，日常 99% 使用的 API）。

## ObjectMapper 基本用法

```java
ObjectMapper mapper = new ObjectMapper();
String json = mapper.writeValueAsString(user);     // POJO → JSON
User u = mapper.readValue(json, User.class);       // JSON → POJO
JsonNode node = mapper.readTree(json);             // 树模型
String name = node.path("profile").path("name").asText("default");
```

ObjectMapper 线程安全（配置完成后），正确做法是整个应用复用一个单例；每次 new 一个既浪费又会丢失全局配置。

## 常用注解

| 注解 | 作用 |
|------|------|
| `@JsonProperty("x")` | 指定 JSON 字段名（含构造参数名绑定） |
| `@JsonIgnore` / `@JsonIgnoreProperties` | 忽略字段（序列化/反序列化双向） |
| `@JsonInclude(NON_NULL)` | null 字段不输出（全局可配） |
| `@JsonFormat(pattern=...)` | 日期格式、时区 |
| `@JsonCreator` + `@JsonProperty` | 不可变对象用构造器/工厂反序列化 |
| `@JsonAlias` | 反序列化时接受历史字段名 |
| `@JsonTypeInfo` / `@JsonSubTypes` | 多态类型信息（带 `@class` 判别字段） |
| `@JsonView` | 同一对象按视图输出不同字段集 |

## 高频踩坑

1. **日期与时间**：`java.util.Date` 默认输出时间戳；JSR-310 的 LocalDateTime 必须注册 `JavaTimeModule`（jackson-datatype-jsr310）并通常关闭 `WRITE_DATES_AS_TIMESTAMPS`，否则报 InvalidDefinitionException。
2. **未知字段默认失败**：对接外部系统时对方加字段会导致反序列化报错，生产常配 `FAIL_ON_UNKNOWN_PROPERTIES=false`。
3. **泛型擦除**：反序列化 `List<User>` 要用 `mapper.getTypeFactory().constructCollectionType(...)` 或 `new TypeReference<List<User>>(){}` 保留类型。
4. **循环引用**：双向关联导致无限递归，用 `@JsonManagedReference/@JsonBackReference` 或 `@JsonIdentityInfo`。
5. **反射与可见性**：Lombok 没生成 setter/无参构造时绑定失败；record/不可变对象走 `@JsonCreator`。
6. **大数字精度**：前端 number 装不下 Long 雪花 ID，通常序列化为 String（`@JsonSerialize(using=ToStringSerializer.class)`）。

## 模块生态

Jackson core 只支持标准 JSON，能力通过模块扩展：JSR-310（时间）、jdk8（Optional）、parameter-names（编译加 -parameters 免注解）、Afterburner/BlackBird（字节码加速）；同一套 Databind API 还能通过 dataformat 模块处理 YAML、CBOR、Protobuf、CSV、XML——这也是 [Retrofit](/docs/CS/Java/Retrofit.md) 等框架选择它作为 Converter 的原因。

## 与 Gson 的对比

- **[Gson](/docs/CS/Java/Gson.md)**：API 更简单、默认配置更宽容（不 fail on unknown）、反射友好；Android/小项目常见。
- **Jackson**：性能与吞吐更高（流式 + 字节码加速）、注解与模块生态最全、流式 API 可处理超大 JSON（逐 token 不全量驻留）；Spring 生态默认。
- 数据量小、只做简单转换时两者差异可忽略；高吞吐服务端、需要精细控制序列化行为时选 Jackson。Java 原生序列化的安全问题见 [serialize](/docs/CS/Java/JDK/Basic/serialize.md)，JSON 不受反序列化 RCE 链影响但仍要校验输入。

## Links

- [Gson](/docs/CS/Java/Gson.md)
- [Retrofit](/docs/CS/Java/Retrofit.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Protobuf](/docs/CS/Distributed/RPC/ProtoBuf.md)

## References

1. [Jackson Wiki（GitHub）](https://github.com/FasterXML/jackson-docs)
2. [Baeldung - Jackson 系列教程](https://www.baeldung.com/jackson)
