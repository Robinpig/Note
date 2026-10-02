## Introduction

Java 标准的 `java.net.URL` 和各种 URL 前缀处理器不足以统一访问底层资源：没有标准方式访问类路径资源或相对于 `ServletContext` 的资源，注册新的 URL 前缀处理器又很复杂，且 `URL` 缺少 `exists()` 这类实用能力。

Spring 的 `Resource` 接口就是为抽象"对底层资源的访问"而设计的更强大的接口。它在 Spring 内部被广泛使用，也可以脱离 Spring 其余部分当作通用工具类使用。

## Resource

`Resource` 继承自 `InputStreamSource`：

```java
public interface InputStreamSource {
    InputStream getInputStream() throws IOException;
}

public interface Resource extends InputStreamSource {
    boolean exists();
    boolean isOpen();
    URL getURL() throws IOException;
    File getFile() throws IOException;
    Resource createRelative(String relativePath) throws IOException;
    String getFilename();
    String getDescription();
}
```

关键方法语义：

- `getInputStream()`：定位并打开资源，**每次调用都应返回新的流**，调用方负责关闭。
- `exists()`：资源是否存在。
- `isOpen()`：是否持有已打开的输入流。为 `true` 时流只能读一次、读完即关，以防泄漏；除 `InputStreamResource` 外常用实现都返回 `false`。
- `getDescription()`：资源描述，出错信息里使用，通常是全限定文件名或真实 URL。

Resource 抽象不取代底层访问能力，而是包装它（例如 `UrlResource` 内部就是包了一个 `URL`）。

## Built-in Implementations

| 实现 | 资源来源 | 备注 |
|---|---|---|
| `UrlResource` | `java.net.URL` | 支持 `file:`、`http:`、`ftp:` 等标准前缀 |
| `ClassPathResource` | 类路径 | 用线程上下文 ClassLoader、指定 ClassLoader 或 Class 加载；jar 内资源不支持 `getFile()`，但支持 URL/流访问 |
| `FileSystemResource` | `java.io.File` / `java.nio.file.Path` | 同时支持 File 和 URL 形式 |
| `ServletContextResource` | Web 应用根目录相对路径 | 仅在 webapp 解包且资源位于文件系统时支持 `getFile()` |
| `InputStreamResource` | 给定的 `InputStream` | 已打开资源的描述符，`isOpen()` 返回 true；找不到合适实现时才用 |
| `ByteArrayResource` | 给定字节数组 | 为字节数组创建 `ByteArrayInputStream`，优先于单用 InputStreamResource |

## ResourceLoader

`ResourceLoader` 用来加载 Resource，所有 ApplicationContext 都实现了它：

```java
public interface ResourceLoader {
    Resource getResource(String location);
}
```

**不带前缀时，返回的 Resource 类型取决于具体的 ApplicationContext**：

```java
// ClassPathXmlApplicationContext -> ClassPathResource
// FileSystemXmlApplicationContext -> FileSystemResource
// WebApplicationContext -> ServletContextResource
Resource template = ctx.getResource("some/resource/path/myTemplate.txt");
```

带显式前缀则强制使用对应实现，与上下文类型无关：

```java
ctx.getResource("classpath:some/resource/path/myTemplate.txt");   // ClassPathResource
ctx.getResource("file:///data/config.xml");                       // UrlResource (file:)
ctx.getResource("http://myhost/logo.png");                        // UrlResource (http:)
```

| 前缀 | 示例 | 含义 |
|---|---|---|
| `classpath:` | `classpath:com/myapp/config.xml` | 从类路径加载 |
| `file:` | `file:///data/config.xml` | 从文件系统以 URL 加载 |
| `http:` | `http://myserver/logo.png` | 以 URL 加载 |
| （无前缀） | `/data/config.xml` | 取决于底层 ApplicationContext |

## ResourceLoaderAware

bean 实现 `ResourceLoaderAware` 接口后，容器会把自身（ApplicationContext 即 ResourceLoader）注入进来：

```java
public interface ResourceLoaderAware {
    void setResourceLoader(ResourceLoader resourceLoader);
}
```

但通常更推荐直接 `@Autowired` 注入 `ResourceLoader`（成员字段、构造参数、方法参数均可），让代码只耦合资源加载接口，而不是整个 ApplicationContext。

## 资源依赖与路径通配符

- **静态资源路径**：直接让 bean 暴露一个 `Resource` 属性，由 Spring 自动注入即可，无需动用 ResourceLoader。
- **路径运行时才确定**（如按用户角色选择模板）：bean 自己持有 `ResourceLoader` 动态加载。
- **构造 ApplicationContext**：`new ClassPathXmlApplicationContext("conf/appContext.xml")` 的路径字符串同样按上述前缀规则解析；不带前缀时由上下文类型决定。
- **Ant 风格通配符**：`classpath*:config/**/*.xml` 可以跨多个 jar 匹配同名 classpath 资源（普通 `classpath:` 只命中类路径上的第一个）。

> FileSystemResource 注意：在 FileSystemXmlApplicationContext 中，相对路径是相对于工作目录解析的；要稳定定位，优先使用 `classpath:` 或绝对 `file:` 路径。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [IoC](/docs/CS/Framework/Spring/IoC.md)

## References

- [Spring Framework Reference - Resources](https://docs.spring.io/spring-framework/reference/core/resources.html)
