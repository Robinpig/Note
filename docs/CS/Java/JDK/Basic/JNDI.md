## Introduction

The [Java Naming and Directory Interface™ (JNDI)](https://docs.oracle.com/en/java/javase/25/docs/api/java.naming/javax/naming/package-summary.html) is an application programming interface (API) that provides naming and directory functionality to applications written using the Java programming language. It is defined to be independent of any specific directory service implementation. Thus a variety of directories—new, emerging, and already deployed—can be accessed in a common way.

The JNDI architecture consists of an API and a [service provider interface (SPI)](/docs/CS/Java/JDK/Basic/SPI.md). Java applications use the JNDI API to access a variety of naming and directory services. The SPI enables a variety of naming and directory services to be plugged in transparently, thereby allowing the Java application using the JNDI API to access their services.

To use the JNDI, you must have the JNDI classes (module `java.naming`) and one or more service providers. The JDK ships with several built-in SPIs:

- Lightweight Directory Access Protocol (**LDAP**)
- Java Remote Method Invocation (**RMI**) Registry
- Common Object Request Broker Architecture (**CORBA**) COS name service
- **DNS** (read-only)

Other service providers can be downloaded from vendors or implemented against the SPI.

## Naming vs Directory

| 维度 | 命名服务 (Naming) | 目录服务 (Directory) |
| --- | --- | --- |
| 核心模型 | 名称 → 对象的 **绑定** | 对象 + 关联的 **属性集** |
| 能力 | `bind` / `lookup` / `rebind` / `unbind` | 在命名之上增加属性检索与 **搜索** |
| 典型用途 | 按名取 DataSource、EJB Home | 查 LDAP 条目属性、按过滤器检索 |
| 接口 | `Context` | `DirContext`（`Context` 的子接口） |

命名服务回答「这个名字对应什么对象」；目录服务在此之上回答「这个对象有哪些属性、满足什么条件」。JNDI 用同一套 `Context` 抽象统一两者。

## Architecture: API vs SPI

```text
┌─────────────────────────────┐
│   Application (your code)   │
└──────────────┬──────────────┘
               │  JNDI API (javax.naming.*)
┌──────────────▼──────────────┐
│  InitialContext / Context   │  ← 统一视图
└──────────────┬──────────────┘
               │  JNDI SPI (javax.naming.spi.*)
┌──────────────▼──────────────┐
│  NamingManager + Providers  │  ← LDAP / RMI / DNS / COS
└─────────────────────────────┘
```

应用只依赖 `javax.naming` API；具体协议由 SPI 接入。`NamingManager` 负责根据 `Context.INITIAL_CONTEXT_FACTORY` 等环境属性实例化对应 provider，使「换目录后端」对业务代码透明。

## Core API

`Context` 是所有命名操作的根接口；`InitialContext` 是默认实现入口，构造时读取环境属性决定后端：

```java
// 构造时通过环境属性选择 provider
Hashtable<String, String> env = new Hashtable<>();
env.put(Context.INITIAL_CONTEXT_FACTORY, "com.sun.jndi.ldap.LdapCtxFactory");
env.put(Context.PROVIDER_URL, "ldap://localhost:389");
Context ctx = new InitialContext(env);

// 命名操作
ctx.bind("cn=appDS", dataSource);   // 绑定名称 → 对象
Object obj = ctx.lookup("cn=appDS"); // 按名查找
ctx.rebind("cn=appDS", ds2);         // 替换绑定
ctx.unbind("cn=appDS");              // 解绑
NamingEnumeration<?> list = ctx.list(""); // 列出子上下文
```

`Context` 的关键方法：`lookup`、`bind`、`rebind`、`unbind`、`rename`、`list`、`listBindings`、`createSubcontext`、`destroySubcontext`、`close`。所有方法都抛受检异常 `NamingException`（其下有 `NameNotFoundException`、`NamingSecurityException` 等子类）。

## Directory Operations

`DirContext` 在命名之上增加属性读写与搜索：

```java
DirContext dctx = (DirContext) ctx;
// 读取属性
Attributes attrs = dctx.getAttributes("cn=user1");
Attribute mail = attrs.get("mail");

// 按过滤器搜索（LDAP 风格的 search filter）
String filter = "(&(objectClass=person)(cn=ro*))";
NamingEnumeration<SearchResult> res =
    dctx.search("ou=people", filter, new SearchControls());
```

属性以 `Attributes`/`Attribute` 抽象表示，`SearchControls` 控制搜索范围（子树/单级）、返回属性与数量上限。

## Event and SPI

`javax.naming.event` 提供 `EventContext`/`EventDirContext`，可对命名/目录对象注册 `NamespaceChangeListener`/`ObjectChangeListener`，在绑定变更或对象属性变化时收到回调——这是 JNDI 支持「热更新配置」的基础。

自定义 provider 只需实现 `ContextFactory`（经 `NamingManager` 注册）与对应 `Context`/`DirContext`，即可把任意后端（数据库、文件系统、配置中心）暴露成 JNDI 树。

## Usage: Lookup a DataSource

JNDI 最常见的企业级用途是**在容器中查找预配置的 `DataSource`**（连接池由容器管理，应用只取引用），与 [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md) 紧密耦合：

```java
Context initCtx = new InitialContext();
Context envCtx  = (Context) initCtx.lookup("java:comp/env");
DataSource ds   = (DataSource) envCtx.lookup("jdbc/AppDB");
try (Connection conn = ds.getConnection()) {
    // ...
}
```

`java:comp/env` 是 Java EE / Jakarta EE 约定的「组件环境」命名空间，DataSource 通常由应用服务器（Tomcat、WildFly）在部署描述符中声明。

## Security

JNDI 本身是中性 API，但 `lookup` 的**参数若来自不可信输入**会构成 **JNDI 注入**：当名称形如 `rmi://attacker:1099/x` 或 `ldap://attacker:389/x` 时，provider 会向远程服务发起请求；若远程返回一个 `javaCodeBase`/对象工厂指向攻击者控制的类，JVM 可能**远程加载并执行该类**（Log4Shell / CVE-2021-44228 即同源原理，只是发生在日志库的 JNDI lookup 中）。

防御要点：

- **永远不要**把用户输入拼接到 `lookup`/`search` 的命名/URL 参数中；必要时做白名单校验。
- JDK 8u191+ 起 `com.sun.jndi.ldap.object.trustURLCodebase`（及 RMI 对应项）默认改为 `false`，禁止从远程 codebases 加载类——但本地/受信 codebase 与 JNDI 参考仍可用，**不能单靠该开关兜底**。
- 在不需要远程目录后端的场景，避免引入对应 provider，缩小攻击面。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Service Provider Interface](/docs/CS/Java/JDK/Basic/SPI.md)
- [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)
- [Module System](/docs/CS/Java/JDK/Basic/module.md)

## References

1. [Java Naming and Directory Interface (JNDI) Overview](https://docs.oracle.com/en/java/javase/25/docs/api/java.naming/javax/naming/package-summary.html)
2. [JNDI Tutorial](https://docs.oracle.com/javase/jndi/tutorial/)
3. [CVE-2021-44228 — Log4Shell (JNDI lookup RCE)](https://nvd.nist.gov/vuln/detail/C14-2021-44228)
