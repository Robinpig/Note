## Introduction

JDK 自带的命令行工具

## Basic Tools

java/javaw - 启动 Java 应用程序

[java 命令启动一个 Java 应用程序](/docs/CS/Java/JDK/JVM/start.md)。它通过启动 Java 运行时环境、加载指定类并调用该类的 main 方法来实现。

javac - Java 编程语言编译器

javac 工具读取用 Java 编程语言编写的类和接口定义，并将其编译为字节码 class 文件。它也可以处理 Java 源文件和类中的注解。


javap - Java Class 文件反汇编器

javap 命令反汇编一个或多个 class 文件。其输出取决于所使用的选项。如果未使用任何选项，javap 会打印传递给它的类的包、受保护和公共字段及方法。javap 将其输出打印到 stdout。

javab

## Java Troubleshooting, Profiling, Monitoring and Management Tools

### jcmd

jcmd process_id command optional_arguments

| Command   | --   |
| --------- | ---- |
| VM.uptime |      |



### jconsole

### jvisualvm

### hsdb

```shell
java -cp .;%JAVA_HOME%/lib/sa-jdi.jar sun.jvm.hotspot.HSDB 

jhsdb hsdb --pid <pid>
```



## Monitoring Tools

### jps

### jstat

```shell
> jstat -options # openjdk15
-class
-compiler
-gc
-gccapacity
-gccause
-gcmetacapacity
-gcnew
-gcnewcapacity
-gcold
-gcoldcapacity
-gcutil
-printcompilation
```

jstat_options file


## Troubleshooting Tools


### jinfo

jinfo 命令 process_id

|        |                                  |
| ------ | -------------------------------- |
| -flags | 获取进程的标志            |
| -flag  | 检查或更新可管理的标志 |



### jstack

使用 top -H pid 查看线程

jstack process_id 等价于 jcmd process_id Thread.print


vjtop




### jmap - 内存映射工具

### jhat - 堆转储分析工具



## JFR

## JMC

### PerfData

## Core Tools
jol

## ASM



## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References

1. [JVM源码分析之Jstat工具原理完全解读](https://lovestblog.cn/blog/2016/07/20/jstat/)
2. [JDK Tools and Utilities](https://docs.oracle.com/javase/7/docs/technotes/tools/index.html)