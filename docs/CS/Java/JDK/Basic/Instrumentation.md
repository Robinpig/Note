## Introduction

此类提供检测 Java 编程语言代码所需的服务。Instrumentation 是为了收集供工具使用的数据而向方法添加字节码。由于这些更改纯粹是添加性的，这些工具不会修改应用状态或行为。此类良性工具的示例包括监控代理、性能分析器、覆盖分析器和事件记录器。
有两种方法可以获得 Instrumentation 接口的实例：
当 JVM 以指示代理类的方式启动时。在这种情况下，Instrumentation 实例被传递给代理类的 premain 方法。
当 JVM 提供一种在 JVM 启动后的某个时间启动代理的机制时。在这种情况下，Instrumentation 实例被传递给代理代码的 agentmain 方法。
这些机制在包规范中有描述。
一旦代理获得 Instrumentation 实例，代理可以随时调用该实例上的方法。

基于 JVMTI redefineClasses -> redefine_single_class

## Links

## References

- [JDK](/docs/CS/Java/JDK/JDK.md)
