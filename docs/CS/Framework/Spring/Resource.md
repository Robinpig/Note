## Introduction

Java 标准的 `java.net.URL` 和各种 URL 前缀处理器不足以统一访问底层资源：没有标准方式访问类路径资源或相对于 `ServletContext` 的资源，注册新的 URL 前缀处理器又很复杂，且 `URL` 缺少 `exists()` 这类实用能力。

Spring 的 `Resource` 接口就是为抽象"对底层资源的访问"而设计的更强大的接口。它在 Spring 内部被广泛使用（配置文件加载、SQL 脚本、`spring.factories` 与 `.imports` 清单读取、静态资源服务等），也可以脱离 Spring 其余部分当作通用工具类使用。

## Resource 接口

`Resource` 继承自 `InputStreamSource`，位于 `org.springframework.core.io`：

```java
public interface InputStreamSource {
    InputStream getInputStream() throws IOException;
}
```

除 `getInputStream()` 外，接口上的方法可分为三组——**存在性与可读性的判断**、**句柄转换**、**内容读取**：

| 方法 | 语义 | 版本 |
|---|---|---|
| `exists()` | 是否以物理形式存在（明确的存在性检查） | 1.0 |
| `isReadable()` | 是否能通过 `getInputStream()` 读到非空内容 | 5.1 |
| `isOpen()` | 是否持有已打开流；为 `true` 时只能读一次，读完即关 | 1.0 |
| `isFile()` | 是否为文件系统中的文件（为 `true` 时 `getFile()` 通常能成功） | 5.0 |
| `getURL()` / `getURI()` | 转成 `URL` / `URI` 句柄 | 1.0 / 2.5 |
| `getFile()` | 转成 `File` 句柄，**仅支持默认文件系统** | 1.0 |
| `getFilePath()` | 转成 NIO `Path` 句柄，**支持非默认文件系统** | **7.0** |
| `readableChannel()` | 返回 `ReadableByteChannel`，每次调用都应是新通道 | 5.0 |
| `contentLength()` / `lastModified()` | 内容长度 / 最后修改时间 | 1.0 |
| `getContentAsByteArray()` | 一次性读成字节数组 | 6.0.5 |
| `getContentAsString(Charset)` | 一次性读成字符串 | 6.0.5 |
| `consumeContent(IOConsumer<InputStream>)` | 按内容逐个回调消费 | **7.1** |
| `createRelative(String)` | 创建相对资源 | 1.0 |
| `getFilename()` / `getDescription()` | 文件名 / 描述（通常用于错误输出与 `toString()`） | 1.0 |

`Resource` 抽象不取代底层访问能力，而是包装它（例如 `UrlResource` 内部就是包了一个 `URL`）。

### 三个子接口

- `WritableResource`：可写资源，增加 `getOutputStream()` / `isWritable()` / `getWritableChannel()`。
- `ContextResource`：从"上下文"加载的资源（如 `ServletContext`、classpath 相对路径），多一个 `getPathWithinContext()`。
- `HttpResource`：HTTP 可达资源，暴露响应头信息。

### 7.x 的两点变化

> [!WARNING]
> **两个容易踩的版本点**：
>
> - `PathResource` 自 **7.0 起弃用**（计划移除），统一用 `FileSystemResource`——后者同时接受 `File` 与 `Path`，且已覆盖前者的全部能力。
> - `consumeContent()` 是 **7.1** 新增的，专为"多内容"资源设计：`getResource("classpath*:...")` 返回的句柄在 7.1 中可以对应**多个物理文件**，此时 `getInputStream()` 返回**合并后的拼接流**，而 `consumeContent()` 会**每个文件回调一次**。若你的代码把 `classpath*:` 结果当单一文件解析（XML、JSON），7.1 起要显式确认合并语义是否符合预期。

## Built-in Implementations

| 实现 | 资源来源 | 备注 |
|---|---|---|
| `UrlResource` | `java.net.URL` | 支持 `file:`、`http:`、`ftp:` 等标准前缀 |
| `FileUrlResource` | `file:` URL | `UrlResource` 子类，同时实现 `WritableResource` |
| `FileSystemResource` | `File` / `Path` | **7.x 首选的文件系统实现**，可写 |
| `PathResource` | `Path` | **7.0 起弃用**，迁移到 `FileSystemResource` |
| `ClassPathResource` | 类路径 | 用线程上下文 ClassLoader、指定 ClassLoader 或 Class 加载 |
| `ModuleResource` | JPMS 模块 | 通过 `Module.getResourceAsStream()` 访问模块内资源 |
| `ServletContextResource` | Web 应用根目录相对路径 | 仅在 webapp 解包且资源位于文件系统时支持 `getFile()` |
| `InputStreamResource` | 给定的 `InputStream` | 已打开资源的描述符，`isOpen()` 返回 true；找不到合适实现时才用 |
| `ByteArrayResource` | 给定字节数组 | 为字节数组创建 `ByteArrayInputStream`，优先于单用 `InputStreamResource` |
| `DescriptiveResource` | 无 | 只有描述、不可读，用于异常消息中占位 |
| `VfsResource` | JBoss VFS | 应用服务器内部使用，应用代码一般不需要 |

## 读取资源的四种姿势

```java
// 1) 经典流方式：调用方负责关闭，每次返回新流
try (InputStream in = resource.getInputStream()) {
    ...
}

// 2) 一次性读成字符串/字节数组（6.0.5+，内部会帮你关流）
String yaml = resource.getContentAsString(StandardCharsets.UTF_8);

// 3) NIO 通道（5.0+），配合 transferTo 做大文件拷贝
try (ReadableByteChannel ch = resource.readableChannel()) {
    ...
}

// 4) 7.1+ 多内容回调：classpath*: 命中几个文件就回调几次
resource.consumeContent(in -> parse(in));
```

选择依据很简单：**小配置/模板用 2，大文件用 1 或 3，跨 jar 批量扫描用 4**。

## ResourceLoader

`ResourceLoader` 用来加载 Resource，**所有 ApplicationContext 都实现了它**：

```java
public interface ResourceLoader {
    String CLASSPATH_URL_PREFIX = "classpath:";
    Resource getResource(String location);
}
```

**不带前缀时，返回的 Resource 类型取决于具体的 ApplicationContext**（`DefaultResourceLoader` 默认按 classpath 解析）：

```java
// ClassPathXmlApplicationContext -> ClassPathResource
// FileSystemXmlApplicationContext -> FileSystemResource
// WebApplicationContext -> ServletContextResource
Resource template = ctx.getResource("some/resource/path/myTemplate.txt");
```

带显式前缀则强制使用对应实现，与上下文类型无关：

```java
ctx.getResource("classpath:some/resource/path/myTemplate.txt");   // ClassPathResource
ctx.getResource("file:///data/config.xml");                       // FileUrlResource
ctx.getResource("http://myhost/logo.png");                        // UrlResource (http:)
```

| 前缀 | 示例 | 含义 |
|---|---|---|
| `classpath:` | `classpath:com/myapp/config.xml` | 从类路径加载（只命中第一个匹配） |
| `classpath*:` | `classpath*:config/**/*.xml` | 跨所有 classpath 条目匹配（含多个 jar） |
| `file:` | `file:///data/config.xml` | 从文件系统以 URL 加载 |
| `http:` / `https:` | `http://myserver/logo.png` | 以 URL 加载 |
| （无前缀） | `/data/config.xml` | 取决于底层 ApplicationContext |

`ResourceLoader` 的两个常用实现变体：

- `FileSystemResourceLoader`：把**不带前缀的路径**解析为文件系统资源（覆盖 `DefaultResourceLoader` 的 classpath 默认策略）。
- `ClassRelativeResourceLoader`：把**不带前缀的路径**解析为相对某个 `Class` 所在包的位置。

此外 `ProtocolResolver` 是自定义协议的扩展点（`DefaultResourceLoader#addProtocolResolver`），可让 `getResource("myproto:xxx")` 返回自定义 `Resource`；Boot 的嵌套 jar 支持正是基于这类扩展来做 `jar:file:` 解析的。

## ResourcePatternResolver 与通配符

`ResourcePatternResolver` 扩展 `ResourceLoader`，支持一次返回多个资源：

```java
public interface ResourcePatternResolver extends ResourceLoader {
    String CLASSPATH_ALL_URL_PREFIX = "classpath*:";
    Resource[] getResources(String locationPattern) throws IOException;
}
```

唯一内置实现是 `PathMatchingResourcePatternResolver`（内部用 `PathPattern`/Ant 匹配，与 MVC 的 `PathPattern` 同源）。

```java
Resource[] xmls = resolver.getResources("classpath*:META-INF/spring/*.xml");
```

`classpath:` 与 `classpath*:` 的区别是读源码时最容易混淆的一处：

- `classpath:`：**只取第一个**匹配到的资源，按 classpath 顺序命中即返回。
- `classpath*:`：**遍历**所有 classpath 条目（目录 + 所有 jar），收集全部匹配。典型用途是加载散落在多个 jar 中的同名文件（如各模块自己的 `.imports` 清单、`META-INF/spring.factories`（见 [Spring Boot 自动配置 SPI](/docs/CS/Framework/Spring/SPI.md)）、MyBatis 的 `*Mapper.xml`）。

> [!WARNING]
> **通配符的两个硬性限制**：
>
> 1. **`classpath*:` 与 Ant 通配符连用时，模式前必须至少有一段根目录**。官方明确说明 `classpath*:*.xml` 这类"根下直接通配"不可靠——它可能只从文件系统目录取到结果而不会扫描 jar 根。写成 `classpath*:conf/*.xml` 或 `classpath*:META-INF/**/*.xml` 才是安全的。
> 2. **`classpath*:**/*.class` 性能很差**：需要遍历所有 jar 的全部条目，启动期做一次尚可，请求路径上绝不能这么扫。Spring 自己的组件扫描反而用的是编译期索引（`@ComponentScan` 的候选组件索引）而非通配扫描。

## 注入资源

大多数场景不需要自己调 `ResourceLoader`——直接把 `Resource` 声明为属性，由 `ResourceEditor` 把字符串位置转换成资源对象：

```java
@Component
public class ReportRenderer {

    @Value("classpath:templates/report.ftl")   // 字符串 -> ClassPathResource
    private Resource template;

    @Value("classpath*:META-INF/rules/*.yaml") // 也支持数组
    private Resource[] rules;
}
```

`ResourceLoaderAware` 是另一种方式，容器会把自身（ApplicationContext 即 ResourceLoader）注入进来：

```java
public interface ResourceLoaderAware {
    void setResourceLoader(ResourceLoader resourceLoader);
}
```

但通常更推荐直接 `@Autowired` 注入 `ResourceLoader`（成员字段、构造参数、方法参数均可），让代码只耦合资源加载接口，而不是整个 ApplicationContext。

**判据**：路径写死在配置里 → 用 `@Value` 注入；路径运行时才确定（如按用户角色、租户选择模板）→ 注入 `ResourceLoader` 动态加载。

## 写资源与 Web 场景

写入需要 `WritableResource`，常用实现是 `FileSystemResource` 与 `FileUrlResource`：

```java
FileSystemResource out = new FileSystemResource(Path.of("/var/tmp/report.csv"));
try (OutputStream os = out.getOutputStream()) {
    os.write(bytes);
}
```

Web 侧有两个高频用法：

- **静态资源服务**：Spring MVC 的 `ResourceHttpRequestHandler` 把 `Resource` 直接映射为 HTTP 响应，支持缓存头、Gzip/Brotli 编码协商。配置入口是 `spring.web.resources.*`，详见 [Spring MVC](/docs/CS/Framework/Spring/MVC.md)。
- **断点续传 / 视频分片**：把 `HttpRange` 解析成 `ResourceRegion` 列表返回，一次响应只传文件的一段。这是 `Resource` 抽象在 HTTP 层最实际的收益——同一份代码对 classpath、文件系统、远程 URL 资源都成立。

## 常见陷阱

| 陷阱 | 现象 | 处理 |
|---|---|---|
| **fat jar 里 `getFile()` 失败** | 本地 IDE 正常，打成 Spring Boot 可执行 jar 后抛 `FileNotFoundException` | 嵌套 jar 中的条目不是文件系统文件。改用 `getInputStream()` / `getContentAsString()`；确实需要路径时必须解压到临时目录 |
| **误用 `PathResource`** | 7.0 起编译告警 | 换成 `FileSystemResource` |
| **非默认文件系统** | `getFile()` 抛 `UnsupportedOperationException` | 改用 7.0 新增的 `getFilePath()` |
| **相对路径漂移** | `FileSystemResource("conf/app.xml")` 解析结果随工作目录变化 | 显式写 `classpath:` 或绝对 `file:` 路径；或显式用 `FileSystemResourceLoader` 并配合绝对路径 |
| **`getInputStream()` 只能读一次** | `InputStreamResource` 第二次读为空 | 需要重复读就换成 `ByteArrayResource` 或重新加载资源 |
| **`classpath*:` 扫不到 jar** | 模式写成 `classpath*:*.xml` | 模式前补一段根目录 |
| **native image 下资源缺失** | 源码里能读到，编译成 GraalVM 原生镜像后 `exists()` 为 false | 原生镜像只包含构建期登记的资源，需通过运行时提示（Runtime Hints）登记，见 [AOT](/docs/CS/Framework/Spring/AOT.md) |

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [IoC](/docs/CS/Framework/Spring/IoC.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

## References

- [Spring Framework Reference - Resources](https://docs.spring.io/spring-framework/reference/core/resources.html)
- [Spring Framework 7.1 Javadoc - org.springframework.core.io](https://docs.spring.io/spring-framework/docs/7.1.x/javadoc-api/org/springframework/core/io/package-summary.html)
- [Spring Framework 7.0 Release Notes](https://github.com/spring-projects/spring-framework/wiki/Spring-Framework-7.0-Release-Notes)
