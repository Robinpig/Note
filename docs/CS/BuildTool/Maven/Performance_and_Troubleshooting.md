## Introduction

Maven 的性能问题高度集中：**每次构建都要冷启一个 JVM 并重新解析一遍依赖树**。多模块项目里，这部分固定开销会淹没真正的编译时间。

这一篇讲怎么把这块开销压下来（`mvnd`、并行、缓存），以及一份按症状索引的排障表。

## Where the Time Goes

一次 `mvn clean install` 的时间分布大致是：

| 阶段 | 占比（多模块项目） | 说明 |
| :--- | :--- | :--- |
| JVM 启动 + Maven 核心加载 | 显著 | 每次都重来 |
| 依赖解析 | 显著 | 冷缓存时要下载 |
| 插件下载 + 类加载 | 显著 | 插件 classloader 每次重建 |
| 实际编译 | 取决于项目 | |
| 测试 | 取决于项目 | |

前三项是**与代码改动无关的固定开销**。改一行代码也照付——这是 Maven 相比 Gradle 最被诟病的地方。

## Maven Daemon (mvnd)

`mvnd` 是 Maven 官方团队的解决方案：**常驻后台进程 + 轻量客户端**。

| 维度 | `mvn` | `mvnd` |
| :--- | :--- | :--- |
| 进程模型 | 每次构建新起 JVM | 后台 daemon 常驻，客户端只发请求 |
| 客户端 | JVM 启动 | **GraalVM native executable**，启动极快 |
| JIT | 每次重新预热 | daemon 内保留已编译代码 |
| 插件类加载 | 每次重建 classloader | 复用 |
| 内存 | 一次性 | daemon 常驻（可配上限） |
| 命令 | `mvn ...` | `mvnd ...`（参数完全一致） |
| 安装 | 独立安装 Maven | **自带 Maven**，无需另装 |

```shell
mvnd clean install
```

**版本**：`mvnd` 1.0.3 是当前 GA；`2.x` 为预览线。

配置在 `$MAVEN_MVND_HOME/conf/mvnd.properties`：

```properties
maven.settings=/path/to/settings.xml
mvnd.jvmArgs=-Xmx2g
```

> [!Note]
>
> **daemon 是"空闲后自动退出"的**——一段时间无请求就关闭以省内存，下次命令再启动。所以"第一次比 mvn 还慢"是正常的，第二次开始才体现优势。多模块项目收益最明显。
>
> 另一个现实限制：daemon 会持有**上一次构建的内存状态**。怀疑构建被污染时，用 `mvnd --stop` 杀掉 daemon 再重试。

## Maven Wrapper

`mvnw`（`mvnw.cmd` + `.mvn/wrapper/`）让项目**自带 Maven 版本**：

```shell
./mvnw clean install
```

它解决的是"团队/CI 的 Maven 版本不一致"这个经典问题。`./mvnw -v` 会自动下载项目指定的 Maven 版本到 `~/.m2/wrapper/dists/`。

Maven 官方还提供 **Maven Wrapper** 的独立项目（`mvn wrapper:wrapper`），支持指定 Maven 版本与 JDK 版本：

```properties
# .mvn/wrapper/maven-wrapper.properties
distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.10.0/apache-maven-3.10.0-bin.zip
```

**CI 上强烈建议用 wrapper**——它把构建工具版本变成仓库里的一份可评审配置，而不是每个人机器上的隐含状态。

## Parallel Builds

```shell
mvn -T 4C clean package      # 4 × 核数 线程
mvn -T 2C clean package
mvn -T 1 clean package
```

`-T 1C` 表示每个 CPU 核一个线程。

并行的前提是**模块间无依赖耦合**；有依赖的模块仍严格按拓扑序。

风险与对策：

| 风险 | 表现 | 对策 |
| :--- | :--- | :--- |
| 插件线程不安全 | 结果随机错乱 | 升级插件；避免共享状态 |
| 日志交错 | 难读 | 用 `-l` 分离日志 |
| 共享文件写入 | 互相覆盖 | 检查插件是否写固定路径 |

Maven 3.10.0 修复了 `ProjectIndex` 的线程安全问题（#12832）。

## Caching the Local Repository

CI 上最大的提速点是**缓存 `~/.m2/repository`**。注意几个坑：

1. **缓存 key 要包含 POM 内容** —— 否则改了依赖版本，CI 还在用旧的；
2. **SNAPSHOT 不能永久缓存** —— 缓存了就不会更新，需要定期失效或用 `-U`；
3. **缓存体积** —— 完整仓库轻易几百 MB 到几 GB；
4. **并发写同一缓存目录会损坏** —— CI 并行 job 需要各自独立的缓存副本，或用只读缓存 + 单独写层。

## Offline Mode

```shell
mvn -o clean package
```

离线模式完全不访问网络，只用本地仓库。依赖齐全时能省掉网络往返，但**不会拉取 SNAPSHOT 的新版本**。

在"依赖已预热 + 网络受限"的 CI 环境有用。

## Troubleshooting by Symptom

### 依赖冲突类

| 症状 | 根因 | 处理 |
| :--- | :--- | :--- |
| `NoSuchMethodError` | 依赖版本被仲裁成不兼容的旧版 | `mvn dependency:tree -Dverbose` 看清仲裁；在 `dependencyManagement` 锁版本 |
| `NoClassDefFoundError` | 传递依赖缺失，多为 `provided` 未传递 | 显式声明该依赖 |
| `ClassNotFoundException` | 同上，或 SNAPSHOT 时间戳导致的文件名不匹配 | 见下 |
| `IllegalAccessError` | 版本跨越了可见性/签名变化 | 升级或对齐版本 |
| `LinkageError` | 同包不同版本的两份类 | 排除重复依赖 |

### 构建失败类

| 症状 | 根因 | 处理 |
| :--- | :--- | :--- |
| `Could not resolve dependencies` | 仓库地址错 / 凭据缺失 / 制品不存在 | `mvn -X` 看具体 URL 与 HTTP 状态；检查 `settings.xml` 的 `<server>` id 是否匹配 |
| `Plugin ... or one of its dependencies could not be resolved` | 插件仓库未配镜像 | 配 `<pluginRepositories>`；插件与依赖是两条独立通道 |
| `The parent element cannot be found` | `relativePath` 指向不存在，或 parent 在仓库里没发布 | 检查 `relativePath`；`mvn help:effective-pom` |
| `Unrecognised tag: 'X'` (POM) | XML 拼写错误 / 标签位置错 | 校验 XML；Maven 4 的 `mvnval` 可只校验不构建 |
| `Duplicated tag: 'dependency'` | 重复声明 | **Maven 3.10.0 起这是致命错误**（原先只是 WARNING） |
| 编码乱码 | 源码编码与编译器编码不一致 | 显式设 `project.build.sourceEncoding`（3.10 起默认 UTF-8） |
| `StackOverflowError` | 循环依赖或 POM 自引用 | 检查 parent/模块引用环 |

### 性能类

| 症状 | 处理 |
| :--- | :--- |
| 每次构建都要等很久才"开始" | 用 `mvnd` |
| 依赖解析慢 | 配镜像；缓存 `~/.m2` |
| 只有一个模块慢 | 该模块的插件在下载或测试慢；`-X` 看耗时 |
| 测试阶段慢 | Surefire 的 fork 次数、JUnit 引擎扫描 |

### 版本与发布类

| 症状 | 处理 |
| :--- | :--- |
| CI 拿到旧 SNAPSHOT | 默认 `daily` 策略；用 `-U` |
| `mvn deploy` 报 "repository element was not specified" | `distributionManagement` 缺 `snapshotRepository` |
| Central 发布 403 / 404 | 还在用 OSSRH 的 URL/token；OSSRH 已于 2025-06-30 关停 |
| GPG 签名卡住 | CI 缺 `--pinentry-mode loopback` |
| 本地能跑、远端不能跑 | 本地 `install` 覆盖了本地仓库里的同版本；清 `~/.m2` 重试 |

### Debugging Commands

```shell
mvn -X clean install            # 完整调试输出
mvn -e clean install            # 打印异常栈
mvn -U clean install            # 强制检查更新
mvn -o clean install            # 离线
mvn help:effective-pom          # 看合并后的 POM
mvn help:effective-settings     # 看合并后的 settings
mvn help:active-profiles        # 看激活的 profile
mvn dependency:tree -Dverbose   # 依赖树与冲突
mvn dependency:analyze          # 依赖使用分析
mvn -T 4C clean package         # 并行
```

## Classpath Ordering Change

Maven 3.10.0 把依赖 classpath 的顺序从 **pre-order（深度优先）** 改为 **level-order（广度优先）**，与 Maven 4 和 Resolver 2.x 的默认行为对齐。

需要旧行为时：

```shell
mvn -Daether.system.dependencyVisitor=preOrder clean package
```

这在依赖了"同一路径下多个同名资源"的旧项目里会体现出来——`ClassNotFoundException` 或资源加载顺序变化。

## Toolchains

当项目要用与运行 Maven 不同的 JDK 编译时：

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-toolchains-plugin</artifactId>
  <version>3.2.0</version>
  <executions>
    <execution>
      <goals><goal>toolchain</goal></goals>
    </execution>
  </executions>
</plugin>
```

```xml
<!-- ~/.m2/toolchains.xml -->
<toolchains>
  <toolchain>
    <type>jdk</type>
    <provides>
      <version>17</version>
      <vendor>openjdk</vendor>
    </provides>
    <configuration>
      <jdkHome>/usr/lib/jvm/java-17-openjdk</jdkHome>
    </configuration>
  </toolchain>
</toolchains>
```

> [!Note]
>
> **Maven 3.10.0 起，插件请求的 toolchain 如果配置错误会让构建直接失败**，而不是静默回退到运行 Maven 的 JDK。这个变化修掉了一个隐蔽的"编译出来的东西和我以为的不一样"的问题，但升级时可能暴露出原本被掩盖的错误配置。

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)

## References

1. [Maven Daemon (mvnd)](https://maven.apache.org/guides/getting-started/maven-daemon.html)
2. [Maven — Maven Wrapper](https://maven.apache.org/wrapper/)
3. [Maven — Introduction to the Lifecycle (Parallel Builds)](https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html)
4. [maven-toolchains-plugin](https://maven.apache.org/plugins/maven-toolchains-plugin/)
5. [maven-dependency-plugin](https://maven.apache.org/plugins/maven-dependency-plugin/)
