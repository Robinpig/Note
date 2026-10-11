## Introduction

JDK 自带一套命令行工具，覆盖编译、打包、依赖分析、运行时诊断、性能记录等全生命周期。`$JAVA_HOME/bin` 下的工具分两类：**标准工具**（随版本稳定，如 `javac`/`jar`/`jlink`）与**诊断/排障工具**（多位于 `jdk.jcmd`/`jdk.jfr` 等模块，JDK 9 模块化后部分需显式包含）。下面按用途归类，标注高频选项与典型命令。

## Compile and Package

**javac** — Java 编译器，把 `.java` 编译成 `.class`。关键选项：`-d <dir>` 输出目录、`-cp`/`-classpath` 类路径、`-source`/`-target` 源/目标版本、`-Xlint:all` 开启全部告警、`--release <N>` 指定目标规范（推荐替代 `-source`/`-target` 组合，避免 bootstrap classpath 错配）。

**javap** — 类文件反汇编器，查看方法签名、字节码、常量池。`javap -p -c MyClass` 打印 private 成员与 Code 属性字节码；`-v` 输出完整 verbose（常量池、行号、StackMapTable）。排查「方法签名/泛型擦除/注解保留期」时最常用。

**jar** — 打包/解包 jar。`jar cvf app.jar -C classes/ .` 打包；`jar xf` 解包；`jar i` 生成索引。`--create`/`--update`/`--describe-module`（模块化 jar 描述）是 JDK 9 后新增的长选项形式。

**jmod** — 操作 `.jmod` 格式（JDK 9+ 模块化后的中间产物，含原生库/头文件/配置，比 jar 更适合作为运行时构件）。`jmod create`/`list`/`describe`。

**jlink** — 把一组模块链接成**自定义运行时镜像**（`runtime image`），只含所需模块，显著缩小体积。典型：`jlink --add-modules java.base,java.sql --output myruntime`。配合升级章节的模块化裁剪使用。

**jpackage** — JDK 14+ 把应用（含自定义运行时）打成原生安装包（dmg/exe/rpm/deb），把 JVM 与应用一起分发。

## Dependency and Compatibility

**jdeps** — 依赖与模块分析。`jdeps app.jar` 列出包级依赖；`jdeps --jdk-internals app.jar` 标出对 JDK 内部 API（`sun.*`/`jdk.internal.*`）的非法引用，给出应改用的标准替代；`--module-path` 分析模块化依赖图。升级 JDK 时定位「强封装会爆」的耦合点。

**jdeprscan** — 扫描对「已标记 deprecated-for-removal」API 的使用。`jdeprscan app.jar` 给出具体类/方法，是升级前的静态风险清单（见 [Upgrade](/docs/CS/Java/JDK/Upgrade.md)）。

## Diagnose and Monitor

**jps** — 列出本机 JVM 进程（PID + 主类/参数），`-v` 显示启动参数，`-l` 显示全限定主类。诊断第一步定位 PID。

**jstat** — 监控 JVM 内部统计（GC、类加载、JIT）。`-options` 列出可用数据视图：

```shell
> jstat -options # openjdk
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

`jstat -gcutil <pid> 1000` 每秒打印各分区使用率与 GC 时间占比，是最常用的「无侵入看 GC 健康度」命令。

**jinfo** — 查看 / 动态修改可管理 JVM flag。`jinfo <pid>` 打印全部；`-flags` 看全部 flag；`-flag <name>` 查单个；`-flag [+/-]<name>` 在支持范围内更新可管理 flag（注意只有 `manageable` 级别的 flag 能运行时改）。

| 子命令 | 含义 |
| --- | --- |
| `-flags` | 打印进程全部 VM flag |
| `-flag <name>` | 查看单个 flag 值 |
| `-flag [+/-]<name>` | 检查或更新 manageable flag |
| `-sysprops` | 打印系统属性 |

**jstack** — 线程栈转储，`jstack <pid>` 等价于 `jcmd <pid> Thread.print`。死锁/高 CPU/线程堆积时抓栈定位。配 `top -H <pid>` 找到热点 OS 线程 LWP，再在栈里对 nid 定位 Java 线程。

**jmap** — 堆与对象统计。`jmap -histo <pid>` 按类统计实例数/占用字节（快速看内存大户）；`jmap -dump:live,format=b,file=heap.hprof <pid>` 抓堆转储供 MAT/VisualVM 分析。`-clstats` 看类加载器统计。

**jcmd** — **瑞士军刀**，一个进程统一入口，派发到各诊断命令。`jcmd` 不加参数列出可用命令；`<pid> help` 看该进程支持的子命令：

| 子命令 | 作用 |
| --- | --- |
| `VM.uptime` | JVM 运行时长 |
| `Thread.print` | 线程栈（同 `jstack`） |
| `GC.heap_dump <file>` | 抓堆转储 |
| `GC.run` | 建议 JVM 做一次 full GC |
| `VM.system_properties` | 系统属性 |
| `VM.native_memory` | Native 内存汇总（需 `-XX:NativeMemoryTracking=summary`） |
| `JFR.start` / `JFR.dump` / `JFR.stop` | 启停/转储飞行记录 |

**jhsdb / hsdb** — Serviceability Agent 的 HotSpot Debugger，深入看对象、栈帧、元空间等底层结构。`jhsdb hsdb --pid <pid>` 进入 GUI；或 `java -cp $JAVA_HOME/lib/sa-jdi.jar sun.jvm.hotspot.HSDB`。

## Record and Analyze

**JFR（Java Flight Recorder）** — 低开销（生产可常开）的事件记录。用 `jcmd <pid> JFR.start name=rec duration=60s filename=rec.jfr` 采集，离线用 **JMC（Java Mission Control）** 分析 CPU、锁、GC、I/O、分配热点。`-XX:+FlightRecorder` 显式开启（JDK 11+ 已解除商业限制，默认可用）。

**PerfData** — JVM 暴露在 `/tmp/hsperfdata_<user>/` 的性能计数器，`jstat` 即读它；进程僵死时该文件残留会导致 `jps` 误报，需手动清理。

## Interactive

**jshell** — JDK 9+ 的 REPL，快速验证语法/API/片段，无需写完整类与 `main`。`/help`、`/vars`、`/edit` 等指令；适合核对某个 JDK API 的行为。

**jol（Java Object Layout）** — 第三方（OpenJDK CodeTools）而非 JDK 自带，用于查看对象在堆中的真实内存布局（对象头、字段对齐填充、引用压缩），分析对象大小与内存占用时极有用。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Upgrade](/docs/CS/Java/JDK/Upgrade.md) — 升级前用 jdeprscan/jdeps 做静态核对
- [module](/docs/CS/Java/JDK/Basic/module.md) — jlink 自定义运行时依赖模块图

## References

1. [JDK Tools and Utilities (Oracle Docs)](https://docs.oracle.com/en/java/javase/21/docs/specs/man/)
2. [jstat - Monitoring Tools and Commands](https://docs.oracle.com/en/java/javase/21/docs/specs/man/jstat.html)
3. [Java Object Layout (jol)](https://github.com/openjdk/jol)
