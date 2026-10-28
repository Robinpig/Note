## Introduction

Quarkus 是 Red Hat 发起、现由 Commonhaus 基金会托管的 Kubernetes 原生 Java 框架，自称 "Supersonic Subatomic Java"。它与 [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md) 解决同一类问题——把一批库装配成一个可运行的服务——但路线相反：Spring Boot 把装配留在运行期（反射扫描、动态代理、启动时建 bean），Quarkus 把尽可能多的工作挪到构建期，用一个叫 **augmentation（增强）** 的构建阶段把应用"烤"成启动毫秒级、内存按实际使用量计费的产物。本页是 Quarkus 分册的枢纽：先讲它为什么存在，再给出版本支持模型，最后按"原理 → 机制 → 各子系统"的顺序引出下面的分册。

## Why Build-Time Boot

传统框架的启动时间花在三件事上：扫描 classpath 找注解、解析配置、反射装配对象——全是"启动时发现"。Quarkus 的赌注是：这些信息在构建时就已确定，没有理由每次启动重做。于是引导被切成 augmentation（构建期执行 Build Step、生成字节码）、Static Init（CDI 容器启动、录制的字节码重放）、Runtime Init（只开端口）三个阶段，元数据处理**只发生一次**，相关类在运行期 JVM 里连加载都不需要。

这套机制的完整拆解——bytecode recording、Gizmo、closed world 假设、配置阶段划分，以及它在 JVM 模式、native image、Project Leyden AOT 三种产物上分别兑现多少——见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)。

## Release and Support Model

Quarkus 社区版**月更**，同时每 6 个月选一个版本做 **LTS，支持 12 个月**；企业支持走 Red Hat build of Quarkus（RHBQ）与 IBM 渠道。截至 2026-10：

| 流 | 状态 |
| :--- | :--- |
| 3.40 LTS（2026-09-30） | 当前 LTS，社区维护至 2027-09-30；最新补丁 3.40.1.1 |
| 3.33 LTS（2026-03-25） | 维护至 2027-03-25，带 RHBQ / IBM 企业支持 |
| 3.27 LTS | 社区维护已于 2026-09-24 结束 |

3.x 线要求 JDK 17+，3.31 起完整支持 JDK 25。**Quarkus 4** 已官宣路线图（Discussion #52020）：2026-09 Beta 1、2026-10 Beta 2、2026-11 GA，之后 2027-03 出 4.x LTS。主线变更为 JPMS 模块化架构、JLink 裁剪镜像、全面对齐 Jakarta EE 11、Vert.x 5 / Netty 4.2、虚拟线程深化、HTTP/3、Jackson 3、Project Leyden AOT，最低 Java 21（Java 17 支持拟移除）。3.40 是 3.x 的收官 LTS，可作为迁往 4.0 前的稳定落点。

## Map of This Section

各分册按依赖顺序阅读：

1. [Architecture](/docs/CS/Java/Quarkus/Architecture.md) 是总纲：没有 augmentation 三阶段和 closed world 假设，后面所有"为什么这样设计"都无从谈起。
2. [Extensions](/docs/CS/Java/Quarkus/Extensions.md) 讲机制如何落到工程实体：deployment/runtime 双构件、BuildItem、ArC 构建期 CDI、平台 BOM 锁定的组件版本。它是连接原理与使用的桥。
3. 之后按使用面展开：[REST](/docs/CS/Java/Quarkus/REST.md)（Quarkus REST 与事件循环执行模型）、[Persistence](/docs/CS/Java/Quarkus/Persistence.md)（Hibernate ORM/Panache、Hibernate Reactive、Panache Next）、[NativeImage](/docs/CS/Java/Quarkus/NativeImage.md)（native 构建、PGO、Leyden AOT 与三种部署形态对比）。
4. 两个横切主题收尾：[Config](/docs/CS/Java/Quarkus/Config.md)（统一配置与构建期阶段规则）和 [DevExperience](/docs/CS/Java/Quarkus/DevExperience.md)（dev mode、Dev Services、持续测试与 JUnit 6 迁移）。

分册之间交叉引用密集：REST 的执行模型依赖 Architecture 的事件循环分析，NativeImage 的反射减免依赖 REST 的序列器改造，DevExperience 的测试栈依赖 Extensions 的打包方式——按 1→2→3→4 的顺序读，交叉链接都能落上。

## Quick Start

现代化入口（老教程里 `io.quarkus:quarkus-maven-plugin:1.4.1.Final:create` 的写法已作废）：

```shell
# CLI（推荐）
quarkus create app com.yh:quarkus --extension='rest-jackson' --maven
cd quarkus && quarkus dev

# 无 CLI：Maven 插件，版本号取当前平台版本
mvn io.quarkus.platform:quarkus-maven-plugin:3.40.1:create \
  -DprojectGroupId=com.yh \
  -DprojectArtifactId=quarkus \
  -Dextensions='rest-jackson'

# 本页沿用的历史最小示例：一个 /hello 端点 + 开 CORS
```

```java
// src/main/java/com/yh/quarkus/HelloResource.java
@Path("/hello")
public class HelloResource {
    @GET
    public String hello() {
        return "hello";
    }
}
```

```properties
# application.properties —— CORS 属于 RUN_TIME 配置，运行期即可改
quarkus.http.cors=true
```

## Links

- [Java](/docs/CS/Java/Java.md)
- [Graal](/docs/CS/Java/JDK/JVM/Graal.md)
- [Undertow](/docs/CS/Framework/Undertow/Undertow.md)
- [Netty EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [Tomcat Deployment](/docs/CS/Framework/Tomcat/Deployment.md)
- [Container](/docs/CS/Container/Container.md)

## References

- https://quarkus.io/
- https://quarkus.io/releases/
- https://quarkus.io/blog/quarkus-3-40-released/
- https://github.com/quarkusio/quarkus/discussions/52020
- https://quarkus.io/guides/writing-extensions
