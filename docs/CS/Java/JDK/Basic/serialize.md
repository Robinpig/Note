## Introduction

Java 原生序列化（Java Object Serialization）把实现了 `java.io.Serializable` 标记接口的对象编码成字节流，
使其可以写入文件、走网络传输，之后再通过反序列化重建为一个与原对象状态相同的新对象。序列化只保存对象的状态（字段），不保存类的字节码。

```java
public class User implements Serializable {
    // 显式声明版本号：类演进后反序列化旧数据时按它做兼容性校验
    @java.io.Serial
    private static final long serialVersionUID = 1L;

    private String name;
    private transient int passwordHash; // transient 字段不参与序列化
}
```

## Mechanism

- `ObjectOutputStream.writeObject()` 沿引用图递归写入：从该对象出发可达的所有对象都必须可序列化，
  否则抛 `NotSerializableException`。
- `ObjectInputStream.readObject()` 重建对象。它是一个「魔法构造器」：**不调用任何构造函数**，
  直接依据流中的字段还原状态，因此反序列化得到的对象可能破坏类的不变量（invariant）。
- `serialVersionUID` 用于版本校验。不显式声明时由编译器根据类结构哈希生成，类一旦增删字段/方法，
  自动算出的 UID 就会变化，旧数据流反序列化即抛 `InvalidClassException`；显式声明后可以在字段兼容的前提下平滑演进。
- `transient` 与 `static` 字段不被序列化（静态字段属于类而非对象状态）。

### Custom Serialization

- 类中定义 `writeObject`/`readObject`（签名固定、由反射调用），可以在默认序列化前后追加逻辑，例如加密、校验、重建 `transient` 派生字段。
- `writeReplace()`/`readResolve()` 允许序列化时替换对象。单例模式正依赖 `readResolve()` 返回唯一实例，
  否则反序列化会「复制」出一个新单例，破坏唯一性（详见 References 中单例与序列化的分析）。
- `Externalizable` 把读写完全交给程序员，需要实现 `writeExternal`/`readExternal`，且反序列化时会先调用无参构造器。

## Security

原生序列化的核心安全问题在于：反序列化的是一个**带类型的对象图**，`readObject` 会实例化流中声明的任意类并执行其 `readObject`/字段类型逻辑。

- 攻击者构造恶意 gadget chain（classpath 上可被链式触发的库类），在反序列化过程中达成任意命令执行，
  经典如 Apache Commons Collections 反序列化 RCE（CVE-2015-7501）。
- 数据不透明、不可跨语言、体积大，且会扩大攻击面。业界长期建议避免对**不可信来源**的数据做 Java 原生反序列化。
- 防御：JEP 290（JDK 9 起内置）提供序列化过滤（ObjectInputFilter 白/黑名单与深度、引用数、字节数限制）；
  JDK 17 起可通过 JDK 属性对整个 Security Manager 范围配置全局过滤。更彻底的方案是换用结构化格式。

## Alternatives

| 方案 | 格式 | 跨语言 | 说明 |
| --- | --- | --- | --- |
| Java Serialization | 二进制（Java 对象流） | 否 | 内置于 JDK，仅建议可信数据/历史系统 |
| JSON（Jackson/Gson） | 文本 | 是 | 最通用，只序列化属性，无任意类实例化风险 |
| Protobuf | 二进制 | 是 | 强 schema、向后/向前兼容，适合高性能 RPC |
| Hessian/Kryo | 二进制 | Hessian 跨语言 | Kryo 仅限 Java 生态，比原生更快更小，仍需注意可信边界 |

选型原则：对外或不可信边界一律使用 JSON/Protobuf 这类数据格式；JDK 原生序列化只在遗留 RMI、JMX 等可信内网场景中维持使用。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md) — 序列化沿对象引用图遍历
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) — readObject/writeObject 由反射驱动

## References

1. [Java Object Serialization Specification](https://docs.oracle.com/en/java/javase/17/docs/specs/serialization/)
2. [JEP 290: Filter Incoming Serialization Data](https://openjdk.org/jeps/290)
3. [单例与序列化的那些事儿](https://www.hollischuang.com/archives/1144)
