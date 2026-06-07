## Introduction

[Java 命名和目录接口（JNDI）](https://docs.oracle.com/javase/jndi/tutorial/getStarted/overview/index.html)是一个应用程序编程接口（API），为使用 Java 编程语言编写的应用程序提供命名和目录功能。它被定义为独立于任何特定的目录服务实现。因此，可以以通用的方式访问各种目录——新的、新兴的和已部署的。

JNDI 架构由一个 API 和一个[服务提供者接口（SPI）](/docs//CS/Java/JDK/Basic/SPI.md)组成。Java 应用程序使用 JNDI API 来访问各种命名和目录服务。SPI 使各种命名和目录服务能够透明地插入，从而允许使用 JNDI API 的 Java 应用程序访问它们的服务。参见下图。

要使用 JNDI，你必须拥有 JNDI 类和一个或多个服务提供者。Java 2 SDK v1.3 为以下命名/目录服务包含了三个服务提供者：

- Lightweight Directory Access Protocol (LDAP)
- Common Object Request Broker Architecture (CORBA) Common Object Services (COS) name service
- Java Remote Method Invocation (RMI) Registry

其他服务提供者可以从 JNDI 网站下载或从其他供应商处获得。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
