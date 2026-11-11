## Introduction

[MyBatis](https://mybatis.org/mybatis-3/) is a first class persistence framework with support for custom SQL, stored procedures and advanced mappings.
MyBatis eliminates almost all of the JDBC code and manual setting of parameters and retrieval of results.
MyBatis can use simple XML or Annotations for configuration and map primitives, Map interfaces and Java POJOs (Plain Old Java Objects) to database records.

它定位在「JDBC 之上、ORM 之下」：**不负责把对象图映射成表结构，只负责把 SQL 与 Java 方法的入参/出参接起来**。实体类没有持久化状态、没有脏检查、没有一级缓存的实体身份（Identity Map），`SqlSession` 的一级缓存缓存的是查询结果而不是「被管理的实体」。这一点决定了 MyBatis 的心智模型更接近「SQL 模板引擎 + 结果映射器」，而不是 Hibernate 那样的对象关系映射器。

## Version Baseline

基线以 Maven Central 上的 POM 与 JAR 字节码为准（实测，2026-10-27）。仓库内所有笔记涉及版本差异时，以本节为准。

| 构件 | 基线版本 | 关键事实 |
| :--- | :--- | :--- |
| `org.mybatis:mybatis` | **3.6.0**（2026-10-23 发布） | POM 声明 `java.version=11`；`org.apache.ibatis.*` 自身 class 的字节码 major = 55（Java 11），共 486 个；shade 进来的 `org.apache.ibatis.javassist`（407 个）与 `org.apache.ibatis.ognl`（173 个）仍是 major 52 |
| `org.mybatis:mybatis`（3.5 线末版） | 3.5.19 | 全量 class major = 52（Java 8），是 3.5 线最后一个 Java 8 字节码版本 |
| `org.mybatis:mybatis-spring` | **4.1.0** | `java.version=17`，编译依赖 Spring Framework **7.0.8** |
| `org.mybatis.spring.boot:mybatis-spring-boot-starter` | **4.1.0** | 与 mybatis-spring 4.1.0 对齐 |
| `com.baomidou:mybatis-plus` | **3.5.18**（2026-10-21 发布） | `mybatis-plus-core` 编译依赖 **mybatis 3.5.19**（不是 3.6.0），见 [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md) |

> [!WARNING]
>
> **「存在 ≠ 生效」同样适用于版本**:MyBatis 官方在 3.5.x 末期的 Release Notes「Support Notice」里说明将按 **Java 8 → 11 → 17** 逐级抬升基线，并会把原定 3.6.0 的内容顺延到 3.7.0。判断某个版本到底要求哪个 JDK，**看 POM 的 `java.version` 和实际字节码 major**，不要看 Release Notes 里的计划文案 —— 3.6.0 的变更列表里同时存在「require java 11」（#3370）和「Drop java8 fallback」（#3372）两个 PR，最终落在 Java 11 而非 Release Notes 早期提到的 Java 17。

源码侧的同一基准落在 `E:/Projects/mybatis-3.6.0/pom.xml`，`pom.xml:30-32`、`:65-70`、`:85-86`：

```xml
<groupId>org.mybatis</groupId>
<artifactId>mybatis</artifactId>
<version>3.6.0</version>

<properties>
  <!-- Java Usage -->
  <java.version>11</java.version>
  <java.release.version>11</java.release.version>

  <clirr.comparisonVersion>3.4.6</clirr.comparisonVersion>

  <!-- Automatic Module Name -->
  <module.name>org.mybatis</module.name>
  <!-- ... -->
```

`java.release.version` 对应 `--release 11`，比只设 `source/target` 更严；`clirr.comparisonVersion` 是二进制兼容检查的对比版本，不能拿它推升级路径，也不构成「3.5.x 的 API 在 3.6.0 全部保留」的证据。`pom.xml:397-406` 把两个依赖改包打进同一个 JAR：

```xml
<relocations>
  <relocation>
    <pattern>ognl</pattern>
    <shadedPattern>org.apache.ibatis.ognl</shadedPattern>
  </relocation>
  <relocation>
    <pattern>javassist</pattern>
    <shadedPattern>org.apache.ibatis.javassist</shadedPattern>
  </relocation>
</relocations>
```

应用侧同时用原生 OGNL 不会撞 classpath；这两个包内部的字节码 major 仍是 52，与上表 `org.apache.ibatis.*` 自身的 55 不同。该源码树没有 `.git`，`scm` 里的 tag 只是 POM 声明，不能靠 log 追 commit；凡涉及「某个改动是哪个版本引入的」，只写 `@since` 或源码现状。`src/main/java/org/apache/ibatis/annotations/` 下带 `@since 3.6.0` 的只有 `NamedResultMap`、`NamedResultMaps`、`ResultOrdered` 三处定义，代码贴在 [Annotation Mapper](/docs/CS/Framework/MyBatis/Annotation_Mapper.md)。

## Compare with Hibernate

| 维度 | MyBatis | Hibernate |
| :--- | :--- | :--- |
| 抽象层级 | SQL 映射：SQL 由人写，框架负责参数绑定与结果映射 | ORM：对象图由人写，SQL 由框架生成 |
| 与数据库的关系 | 与具体 DB 强耦合，换库要改 SQL | 通过 Dialect 屏蔽方言差异 |
| 缓存 | 一级缓存（`SqlSession`）/ 二级缓存（`namespace`）缓存的是查询结果 | 一级缓存是持久化上下文（Identity Map），实体有身份与脏检查 |
| 关联加载 | `<association>` / `<collection>` 的嵌套查询，N+1 要自己处理 | 懒加载代理由 Session 生命周期托管 |
| 可控性 | SQL 完全可见可调优，适合报表、复杂查询 | SQL 不可见，调优靠 HQL/Criteria 与统计 |
| 迁移成本 | 无 schema 约束，接手遗留库成本低 | 需要对象模型与关系模型对齐 |

「Scalability 谁高」这类一刀切结论没有意义：**MyBatis 的可扩展性体现在插件链与自定义 `TypeHandler` / `LanguageDriver`，Hibernate 的可扩展性体现在拦截器、事件与自定义类型**。两者扩展的不是同一个东西。

## Architecture

MyBatis 的核心实现围绕 **「配置驱动 + 动态代理 + 流水线执行 + 插件扩展」** 展开：

1. **配置驱动**：启动时把 XML / 注解解析成一份 `Configuration` 对象，运行期只读。所有 `MappedStatement`、`ResultMap`、`Cache` 都挂在它上面。
2. **动态代理**：Mapper 接口没有实现类，[binding](/docs/CS/Framework/MyBatis/binding.md) 用 JDK 动态代理把方法调用翻译成 `namespace.id` 的 SQL 调用。
3. **流水线执行**：`SqlSession` → `Executor` → `StatementHandler` → (`ParameterHandler` / `ResultSetHandler`) → JDBC。
4. **插件扩展**：[Interceptor](/docs/CS/Framework/MyBatis/Interceptor.md) 在四个组件上挂责任链，分页、数据权限、SQL 改写都落在这里。

[Init](/docs/CS/Framework/MyBatis/Init.md)

### Infrastructure

<div style="text-align: center;">

```dot
strict digraph {

    xml [shape="polygon" label="XMLConfigBuilder"]
    subgraph cluster_config {
    label="Configuration"
        ms [shape="polygon" label="MappedStatement"]
    }
    xml -> ms [label="parseConfiguration"]
  
    builder [shape="polygon" label="SqlSessionFactoryBuilder"]
    factory [shape="polygon" label="SqlSessionFactory"]
    session [shape="polygon" label="SqlSession"]
    builder -> factory [label="build(Configuration)"]
    factory -> session [label="openSession"]
    executor [shape="polygon" label="Executor"]
  
    ms -> executor [label="newExecutor" ltail=executor lhead=cluster_config]
  
  
    mapper [shape="polygon" label="Mapper"]
    mapper -> session [label="getMapper/return MapperProxy" dir = both]
  
    cache [shape="polygon" label="TransactionalCacheManager"]
    {rank="same"; executor;cache;}
    executor -> cache [label="2nd Cache" dir = both]
  
    subgraph cluster_handler {
        sh [shape="polygon" label="StatementHandler"]
        rh [shape="polygon" label="ResultHandler"]
        th [shape="polygon" label="TypeHandler"]
        ph [shape="polygon" label="ParameterHandler"]
        {rank="same"; sh;th;ph;rh;}
  
    }
  
    session -> executor [label="query(MappedStatement)"]
    executor -> sh [label="newStatementHandler" ]
    executor -> rh [label="getSqlSession"]
  
    conn [shape="polygon" label="Connection"]
    sh -> conn [label="getConnection"]
    conn -> st [label="prepare"]
  
    st [shape="polygon" label="Statement"]

    re [shape="polygon" label="ResultSet"]
    map [shape="polygon" label="ResultMap"]
    {rank="same"; conn;re;}
  
    st -> re [label="executeQuery"]
    rh -> re [label="handleResultSet"]
    map -> rh [label="NestedResultMap"]
    rh -> map [label="Proxy LazyLoad"]
  
}
```

</div>

<p style="text-align: center;">
Fig.1. MyBatis Infrastructure
</p>

- [Binding](/docs/CS/Framework/MyBatis/binding.md)
- [Log](/docs/CS/Framework/MyBatis/Logging.md) provide log4j log4j2 slf4j jdklog and so on
- [Cache](/docs/CS/Framework/MyBatis/Cache.md)
- [DataSource](/docs/CS/Framework/MyBatis/DataSource.md)
- [Reflector](/docs/CS/Framework/MyBatis/Reflector.md)：类定义信息的缓存，映射属性名与 getter/setter 方法。

### Core

- [How SQL works](/docs/CS/Framework/MyBatis/Execute.md)
- [Executor](/docs/CS/Framework/MyBatis/Executor.md)
- [StatementHandler](/docs/CS/Framework/MyBatis/StatementHandler.md)
- [ResultSetHandler](/docs/CS/Framework/MyBatis/ResultSetHandler.md)
- [Interceptor](/docs/CS/Framework/MyBatis/Interceptor.md)
- [KeyGenerator](/docs/CS/Framework/MyBatis/KeyGenerator.md)
- [SqlSession](/docs/CS/Framework/MyBatis/SqlSession.md)

## Extension

[MyBatis-Spring](/docs/CS/Framework/MyBatis/MyBatis-Spring.md) : Load Mybatis-config.xml, create Configuration and SqlsessionFactory

[MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)：第三方增强工具包（baomidou 组织，与 MyBatis 官方无关）。它在**不改 MyBatis 任何源码**的前提下，用「启动期注入 MappedStatement + 运行期插件拦截」两条路子把单表 CRUD、分页、逻辑删除、多租户做成开箱即用。代价是它与 MyBatis 版本强绑定（`mybatis-plus-core` 3.5.18 编译依赖 mybatis **3.5.19**），升级 MyBatis 3.6.0 前必须确认兼容。

### Extension Points

把 Builder / Factory / Proxy / Decorator 列成一张模式对照表，解释不了「想改一个行为该往哪儿插」。`Configuration` 里真正可替换的点是数得清的：三张注册表 `typeHandlerRegistry` / `typeAliasRegistry` / `languageRegistry`，三个工厂 `objectFactory` / `objectWrapperFactory` / `reflectorFactory`，以及 `interceptorChain` 在四个工厂方法末尾的 `pluginAll` 挂载点。字段声明与四个 `pluginAll` 的代码贴在 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)。自定义 `TypeHandler` 走注册表、`@Lang` 走语言驱动注册表、插件走 `pluginAll`，三条路彼此独立；`Cache` 的 11 个装饰器是同一接口的实现矩阵，不是运行期可插拔的策略。实现矩阵与索引盲点见 [Call Graph Internals](/docs/CS/Framework/MyBatis/Call_Graph_Internals.md)。

## How to Read This Subtree

按「先定基准 → 再追配置 → 再看 SQL → 最后看符号关系」读。

源码级分册把关键代码直接贴在正文里，读单篇不需要另开源码文件；代码块取自本机 `mybatis-3.6.0`，路径与行号只作出处标注。凡涉及「哪个版本改了什么」的判断，先回 [Version Baseline](/docs/CS/Framework/MyBatis/MyBatis.md?id=version-baseline) 看基准，那里的 JAR 字节码结论与上面贴的 `pom.xml` 是同一基准的两个观察面。

配置解析有两条独立生产线，汇合点只有 `MapperBuilderAssistant.addMappedStatement`。[Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md) 追 XML 这条：`plugins` 在 `settings` 之前就注册完、`<include>` 在 `LanguageDriver` 介入前改写 DOM、四个挂起队列配四把独立锁且重试失败时静默吞掉，`StrictMap` 的短名歧义哨兵是「XML 与注解写了同一 id」报错的出处。[Annotation Mapper](/docs/CS/Framework/MyBatis/Annotation_Mapper.md) 追注解这条：`MapperAnnotationBuilder` 自己设 namespace、自己建 cache，两条线的互斥靠一个 `"namespace:"` 伪资源名；同一个方法上两个 `@Select` 在 `getAnnotationWrapper` 就抛冲突；provider 方法则在每次执行时都跑一遍。

SQL 定型再拆两页，分界是 `LanguageDriver.createSqlSource`。[Dynamic SQL](/docs/CS/Framework/MyBatis/Dynamic_SQL.md) 讲启动期建 `SqlNode` 树、运行期用 `DynamicContext` 跑树：九个 `NodeHandler` 里 `<when>` 与 `<if>` 复用同一个类，`<where>` / `<set>` 只是 `TrimSqlNode` 的两组预设参数，而只要出现过动态标签，静态内容也得走运行期 `apply`。[SqlSource and Parameters](/docs/CS/Framework/MyBatis/SqlSource_and_Parameters.md) 讲树跑完之后：`#{}` 恒换成 `?`、`ParameterExpression` 拆内联属性、`<foreach>` 的 bindings 经 `BoundSql.additionalParameters` 传到 `DefaultParameterHandler`。`${}` 与 `#{}` 的先后关系在前一页，这里不重述。

最下面一层是 [Call Graph Internals](/docs/CS/Framework/MyBatis/Call_Graph_Internals.md)，用 `.codegraph/codegraph.db` 回答单文件读不出来的问题：某个接口有几个实现者、一条语句能从哪几处被造出来、Java Mapper 接口与 XML statement 在图里到底有没有边。它同时给出这套证据的可靠性口径：1457 条 `calls` 边是索引器合成的，331 条 java-xml 边按方法名匹配，连多语言文档页里的示例代码都被合了进去，所以边计数只能指路，不能当结论。

```text
              MyBatis ─────┬─ Config Pipeline ─ Annotation Mapper
                           ├─ Dynamic SQL ─ SqlSource and Parameters
                           └─ Call Graph Internals
```

## Links

- [MyBatis 目录索引（按层导航）](/docs/CS/Framework/MyBatis/README.md)
- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [Spring Framework](/docs/CS/Framework/Spring/Spring.md)
- [Hibernate](/docs/CS/Framework/Hibernate/Hibernate.md)
- [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)

## References

1. [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
2. [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
3. [MyBatis Releases](https://github.com/mybatis/mybatis-3/releases)
4. [MyBatis Blog](http://blog.mybatis.org/)
5. [MyBatis-Spring](https://github.com/mybatis/spring)
