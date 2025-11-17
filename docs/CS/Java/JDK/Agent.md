## Introduction

JavaAgent就是JAVA代理，JDK 1.5 引入，位于java.lang.instrument包下。实现机制是在JVM启动前或启动后进行修改方法字节码。类似于AOP，但是完全无侵入性

在 JVM 启动的时候，可以通过 -javaagent:/path/to/agent.jar 的⽅式来加载 Java Agent。在
Java Agent 中，实现 ClassFileTransformer 接⼝，并调⽤Instrumentation.addTransformer
将 Transformer 添加到系统中


接下来加载类的时候，或者通过 retransformClasses 触发类重新加载的时候，Transformer 就
可以修改类的字节码，⽐如去除掉某⼀段代码，在原来的⽅法前后执⾏额外逻辑等等

> Byte Buddy is a code generation and manipulation library for creating and modifying Java classes during the runtime of a Java application and without the help of a compiler. 
> 