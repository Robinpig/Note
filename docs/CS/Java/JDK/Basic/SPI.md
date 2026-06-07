## Introduction

Java 6 引入了一项特性，用于发现和加载匹配给定接口的实现：**服务提供者接口（SPI）**。

一个*可扩展的*应用程序是指可以在不修改原始代码库的情况下进行扩展的应用程序。
你可以使用新的插件或模块来增强其功能。开发者、软件供应商和客户可以通过在应用程序类路径或特定于应用程序的扩展目录中添加新的 Java 归档（JAR）文件来添加新的功能或 API。

SPI 的本质是将接口实现类的全限定名配置在文件中，并由服务加载器读取配置文件，加载实现类。这样可以在运行时，动态为接口替换实现类。
正因此特性，我们可以很容易的通过 SPI 机制为我们的程序提供拓展功能。
SPI的核心原理可以总结为：基于接口的编程 + 策略模式 + 配置文件 + 反射机制

以下是理解可扩展应用程序的重要术语和定义：

- Service
  一组编程接口和类，提供对某些特定应用程序功能或特性的访问。
  服务可以定义功能的接口以及检索实现的方式。
  在文字处理器的示例中，字典服务可以定义检索词典和单词定义的方式，但它不实现底层功能集。
  相反，它依赖*服务提供者*来实现该功能。
- Service provider interface (SPI)
  服务定义的一组公共接口和抽象类。SPI 定义了应用程序可用的类和方法。
- Service Provider
  实现 SPI。具有可扩展服务的应用程序使你、供应商和客户能够在不修改原始应用程序的情况下添加服务提供者。

## ServiceLoader

`java.util.ServiceLoader` 类帮助你查找、加载和使用服务提供者。
它在你的应用程序类路径或运行时环境的扩展目录中搜索服务提供者。
它加载它们并使你的应用程序能够使用提供者的 API。

### 约定

使用 ServiceLoader 约定如下：

1. 在 JAR 包的 `META-INF/services/` 目录中创建一个以服务接口全限定名命名的文件。
2. 该文件包含实现类的全限定名，每一行一个。
3. 使用 ServiceLoader.load() 方法加载实现。

```java
ServiceLoader<MyService> loader = ServiceLoader.load(MyService.class);
for (MyService service : loader) {
    service.doSomething();
}
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
