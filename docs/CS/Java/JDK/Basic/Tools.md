## Introduction

## Basic Tools

### java/javaw - Launches a Java application
[The java command starts a Java application.](/docs/CS/Java/JDK/JVM/start.md) It does this by starting a Java runtime environment, loading a specified class, and calling that class's main method.

### javac - Java programming language compiler
The javac tool reads class and interface definitions, written in the Java programming language, and compiles them into bytecode class files. It can also process annotations in Java source files and classes.


### javap - The Java Class File Disassembler
The javap command disassembles one or more class files. Its output depends on the options used. If no options are used, javap prints out the package, protected, and public fields and methods of the classes passed to it. javap prints its output to stdout.

### javab

## Java Troubleshooting, Profiling, Monitoring and Management Tools

### jcmd

jcmd process_id command optional_arguments

| Command   | --   |
| --------- | ---- |
| VM.uptime |      |

### jmc

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

jinfo command process_id

|        |                                  |
| ------ | -------------------------------- |
| -flags | Get flages of process            |
| -flag  | check or update manageable flags |



### jstack

jstack process_id  == jcmd process_id Thread.print


### jmap

### jhat



## JFR



### PerfData

## Core Tools
jol

## ASM



## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References

1. [JVM源码分析之Jstat工具原理完全解读](https://lovestblog.cn/blog/2016/07/20/jstat/)
2. [JDK Tools and Utilities](https://docs.oracle.com/javase/7/docs/technotes/tools/index.html)