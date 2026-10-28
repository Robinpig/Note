## Introduction

Quarkus 支持三种部署形态：**JVM 模式**（普通可执行 jar）、**native image**（GraalVM/Mandrel 静态编译）、以及 3.32 起的 **Leyden AOT**（JVM 模式 + AOT 缓存）。三者是同一套 augmentation 产物的不同消费者——Static Init 阶段装配好的对象图，在 native 模式下直接序列化进二进制，在 JVM 模式下由录制的字节码现场重放。总览见 [Quarkus](/docs/CS/Java/Quarkus.md)，构建期机制见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)。

## Native Image with Mandrel

native image 用 [GraalVM](https://www.graalvm.org/) 的 Substrate VM 提前编译；Red Hat 维护的下游发行版叫 **Mandrel**（GraalVM CE 的 native-image 专用裁剪版），Quarkus 文档与容器镜像默认走 Mandrel。3.31 起完整支持 JDK 25 的 native 构建。

```shell
# 本机 native 构建（需已装 Mandrel/GraalVM）
./mvnw package -Dnative

# 容器内构建（无需本机工具链）
./mvnw package -Dnative -Dquarkus.native.container-build
```

构建产物直接可执行，无 JVM，启动毫秒级、RSS 按实际用量计。代价是：

- **构建期复杂度**：反射、动态代理、资源、JNI 都要显式注册，这是最大的工程成本；
- **构建时长**：分钟级，且随应用规模增长；
- **吞吐折让**：无 JIT 的峰值吞吐通常低于 HotSpot，短生命周期请求密集场景最划算；
- **可移植性**：二进制与目标平台绑定。

Quarkus 缓解这些代价的手段与 augmentation 同源：配置在构建期固定，Substrate 就能判定未调用的方法并消除；3.37 的 **reflection-free Jackson serializers**（构建期生成序列化器，去掉最大的一类反射注册）和 3.35 的 **JAR tree-shaking**（JVM 产物裁掉未用类）都直接减少需要注册的东西。

## Build Optimizations for Native

| 版本 | 特性 | 作用 |
| :--- | :--- | :--- |
| 3.35 | **PGO for native** | 用一次剖析运行的数据引导 native 镜像优化布局，提升吞吐 |
| 3.35 | **Semeru AOT** | 支持 IBM Semeru 的共享 AOT 缓存类，多个 JVM 实例共享已编译代码 |
| 3.35 | JAR tree-shaking | JVM 模式产物体积瘦身 |
| 3.37 | reflection-free Jackson | 砍掉 Jackson 反射注册 |
| 3.32 | Project Leyden AOT | 不走 native 也能砍启动时间 |

## Project Leyden AOT: The Middle Path

训练运行录制类加载、链接与方法剖析，生成 AOT cache，后续运行跳过冷启动重复劳动，**要求 JDK 25**。3.40.1 上最小 REST 应用启动 370 ms → 80 ms，9000 类的大型 CRUD 应用 3 s → 900 ms（官方 3.32 博文数字）。与 native 相比收益小、镜像略大（多一个 cache 文件），但**不改代码、不换工具链、保留 JIT 峰值吞吐**，是多数团队性价比最高的一档。

## Deployment Modes Compared

| 维度 | JVM 模式 | Leyden AOT | Native image |
| :--- | :--- | :--- | :--- |
| 启动 | 百毫秒级 | 数十毫秒级 | 毫秒级 |
| 峰值吞吐 | 最高（完整 JIT） | 高 | 中 |
| RSS | 框架类常驻但已裁过 | 同 JVM 模式 | 最低 |
| 构建时长 | 短 | 短 + 一次训练运行 | 长（分钟级） |
| 反射等注册 | 不需要 | 不需要 | 需要 |
| 运行环境 | JRE | JDK 25 | 无（裸二进制） |
| 镜像体积 | 大 | 大 + cache 文件 | 小 |

## Testing Native and Integration

- `@QuarkusTest`：dev/test 模式跑 JVM，快速反馈；
- `@QuarkusIntegrationTest`：对**打好的包**（含 native 产物）做黑盒验证，`./mvnw verify -Dnative` 时自动以 native 二进制运行；
- Quarkus 3.31 起测试栈随 JUnit 6 升级，工件改名 `quarkus-junit5` → `quarkus-junit`，细节见 [DevExperience](/docs/CS/Java/Quarkus/DevExperience.md)。

## Links

- [Architecture](/docs/CS/Java/Quarkus/Architecture.md)
- [DevExperience](/docs/CS/Java/Quarkus/DevExperience.md)
- [Graal](/docs/CS/Java/JDK/JVM/Graal.md)
- [Container](/docs/CS/Container/Container.md)
- [Tools](/docs/CS/Java/Tools/Tools.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)

## References

- https://quarkus.io/guides/building-native-image
- https://quarkus.io/blog/quarkus-3-32-released/
- https://quarkus.io/blog/quarkus-3-35-released/
- https://quarkus.io/blog/quarkus-3-40-released/
