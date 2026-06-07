## Introduction

## JUnit5

**JUnit 5 = JUnit Platform + JUnit Jupiter + JUnit Vintage**

JUnit Platform 作为在 JVM 上启动测试框架的基础。
它还定义了用于开发测试框架的 TestEngine API，该框架运行在平台上。
此外，平台提供了 Console Launcher 用于从命令行启动平台，以及 JUnit Platform Suite Engine 用于使用平台上的一个或多个测试引擎运行自定义测试套件。
流行的 IDE（如 IntelliJ IDEA、Eclipse、NetBeans 和 Visual Studio Code）和构建工具（如 Gradle、Maven 和 Ant）也为 JUnit Platform 提供了一流支持。

JUnit Jupiter 是在 JUnit 5 中编写测试和扩展的编程模型和扩展模型的组合。
Jupiter 子项目提供了一个 TestEngine 用于在平台上运行基于 Jupiter 的测试。

JUnit Vintage 提供了一个 TestEngine 用于在平台上运行基于 JUnit 3 和 JUnit 4 的测试。
它要求 class path 或 module path 中存在 JUnit 4.12 或更高版本。

## Test Lifecycle

## Links

- [Test](/docs/CS/SE/Test.md)
