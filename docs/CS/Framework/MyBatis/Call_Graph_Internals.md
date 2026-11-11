## Introduction

前面几篇逐文件读源码，回答「函数在哪、做什么」；这一页读 `E:/Projects/mybatis-3.6.0/.codegraph/codegraph.db`，回答单文件读不出来的问题：某个接口有几个实现者、一条语句能从哪几处被造出来、Java Mapper 接口与 XML statement 在图里到底有没有边。本页的数字都给了可复现的 SQL，源码摘抄的省略处标 `// ...`，涉及的源码片段直接贴在下面，与 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md) 等分册取自同一份源码树。

符号图能看到扇入扇出，但图本身不是事实。这个索引器会主动合成边、会按名字把 Java 与 XML 连起来，也会把多语言文档页里的示例代码当成 mapper 声明。本页把 `nodes` / `implements` / `unresolved_refs` 当候选证据，`calls` 边只用来定位；写进正文的结论一律回源码核过。

## Index Shape

`.codegraph/codegraph.db` 是 SQLite。先看清表结构，后面的统计才不会读错列：

```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
    qualified_name TEXT NOT NULL, file_path TEXT NOT NULL, language TEXT NOT NULL,
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
    docstring TEXT, signature TEXT, visibility TEXT, /* ... */
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL,
    metadata TEXT, -- JSON object
    line INTEGER, col INTEGER, provenance TEXT DEFAULT NULL
);
CREATE TABLE unresolved_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node_id TEXT NOT NULL, reference_name TEXT NOT NULL,
    reference_kind TEXT NOT NULL, line INTEGER NOT NULL, col INTEGER NOT NULL,
    file_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE project_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);
```

索引版本与状态可以直接查出来：

```sql
SELECT key, value FROM project_metadata ORDER BY key;
-- indexed_at_commit            ''
-- indexed_dirty_paths          ''
-- index_files_accounted        1853
-- index_files_discovered       1853
-- index_state                  complete
-- indexed_with_extraction_version  27
-- indexed_with_version         1.6.2
```

`indexed_at_commit` 是空串，源码树也没有 `.git`，索引无法绑定到某个 commit。规模：

| 项 | 值 | 复现方式 |
| :--- | :--- | :--- |
| 索引文件 | 1853（java 1396 / xml 441 / yaml 9 / properties 7） | `SELECT language, count(*) FROM files GROUP BY language` |
| 节点 | 25667（main 7288 / test 18313 / 其它 66） | `SELECT count(*) FROM nodes`，按 `file_path LIKE 'src/main/%'` 分组 |
| 边 | 52333：`contains` 23830、`calls` 14343、`references` 6248、`instantiates` 3613、`imports` 3305、`decorates` 622、`extends` 248、`implements` 124 | `SELECT kind, count(*) FROM edges GROUP BY kind` |
| 未解析引用 | 32054，全部 `status='failed'` | `SELECT status, count(*) FROM unresolved_refs GROUP BY status` |

覆盖边界先说清楚，否则计数会被误用：441 个 xml 里 410 个在 `src/test/resources/` 下（其中 408 个在 `org/apache/ibatis/` 子树），`src/site/` 下另有 27 个 xdoc 文档页与站点元数据，其余是少量根目录 XML；`src/main/resources` 的两个 DTD 不在文件表里。测试节点占全部节点的七成，任何按全库统计的扇入数字，先默认是测试代码贡献的。

## Resolution Semantics

`calls` 边的 `metadata.resolvedBy` 分布：`instance-method` 9809、`exact-match` 2014、无标记 1457、`import` 735、`qualified-name` 328。查法：

```sql
SELECT json_extract(metadata, '$.resolvedBy') AS by, count(*)
FROM edges WHERE kind = 'calls' GROUP BY by ORDER BY 2 DESC;
```

那 1457 条无标记的恰好等于索引器合成边的总数：`synthesizedBy=interface-impl` 1126 条 + `synthesizedBy=mybatis-java-xml` 331 条。前者给接口方法按实现类补伪调用边，metadata 长这样：

```json
{
  "kind": "calls",
  "source": "org.apache.ibatis.mapping::SqlSource::getBoundSql",
  "target": "org.apache.ibatis.builder::StaticSqlSource::getBoundSql",
  "metadata": {
    "synthesizedBy": "interface-impl",
    "via": "getBoundSql",
    "registeredAt": "src/main/java/org/apache/ibatis/builder/StaticSqlSource.java:44"
  }
}
```

`registeredAt` 指的是实现类的方法声明位置，源码里并不存在这行调用。把「无 resolvedBy」读成「解析失败的边」正好读反了，它们是索引器主动造的。

带 `confidence` 标记的边共 26367 条：`0.9` 17628、`0.7` 4116、`0.95` 3412、`0.4` 553、`0.85` 362、`0.65` 185、`0.8` 109、`0.5` 2。最低那 553 条几乎全是测试代码里的 `instantiates`，典型是 `ParameterExpressionTest.simpleProperty` → `ParameterExpression`，标记 `resolvedBy=exact-match, refName=ParameterExpression`，类名与实例构造被当成弱证据。

`implements` 共 124 条，其中 source 落在 `src/main/` 的 80 条。Java 项目的实现关系大量走 `extends`（248 条，main 53 条），单看 implements 会少算一半。

## Interface Implementation Matrix

主源码侧 `implements` 边按目标接口聚合，几组最有信息量：

| 接口 | 直接实现者数 | 成员 |
| :--- | :--- | :--- |
| `Cache` | 11 | `PerpetualCache` 与 10 个装饰器（`LruCache` / `FifoCache` / `SoftCache` / `WeakCache` / `ScheduledCache` / `SerializedCache` / `LoggingCache` / `SynchronizedCache` / `BlockingCache` / `TransactionalCache`） |
| `Log` | 10 | slf4j 三种、log4j2 三种、log4j / jdk14 / stdout / no-logging |
| `SqlNode` | 9 | 八个独立类 + `XMLScriptBuilder.java:267` 的 `EmptySqlNode` |
| `NodeHandler` | 8 | `XMLScriptBuilder.java:121-225` 的内部类，与 `:63-73` 的注册表一一对应 |
| `SqlSource` | 4 | `StaticSqlSource` / `RawSqlSource` / `DynamicSqlSource` / `ProviderSqlSource` |
| `TokenHandler` | 4 | `ParameterMappingTokenHandler` / `VariableTokenHandler` / `BindingTokenParser` / `DynamicCheckerTokenParser` |
| `KeyGenerator` | 3 | `Jdbc3KeyGenerator` / `NoKeyGenerator` / `SelectKeyGenerator` |
| `Executor` | 2 | `BaseExecutor` / `CachingExecutor` |
| `StatementHandler` | 2 | `BaseStatementHandler` / `RoutingStatementHandler` |
| `SqlSession` | 2 | `DefaultSqlSession` / `SqlSessionManager` |
| `Interceptor` | 0 | 主源码里没有实现类，插件由使用方提供 |

`Executor` 只数到 2 是错的读法：`SimpleExecutor` / `ReuseExecutor` / `BatchExecutor` 三个是 `extends BaseExecutor` 的 `extends` 边（`SimpleExecutor.java:36` 等），`ResultLoaderMap.java:280` 里还有个内部类 `ClosedExecutor` 同样继承它。[Executor](/docs/CS/Framework/MyBatis/Executor.md) 里那张继承图对应的就是 `extends` 边。

## Blind Spots

索引器只为显式 `implements` 声明建边，靠继承拿到的接口不算。三行类声明说明了全部问题：

```java
// scripting/xmltags/WhereSqlNode.java:26
public class WhereSqlNode extends TrimSqlNode {

// scripting/xmltags/TrimSqlNode.java:28
public class TrimSqlNode implements SqlNode {

// type/BaseTypeHandler.java:37
public abstract class BaseTypeHandler<T> implements TypeHandler<T> {
```

`WhereSqlNode` / `SetSqlNode` 只有 `extends` 边，`SqlNode` 的实现者清单里查不到它们（构造参数见 [Dynamic SQL](/docs/CS/Framework/MyBatis/Dynamic_SQL.md)）。`BaseTypeHandler` 虽写了 `implements TypeHandler<T>`，主源码的 `implements` 边里却没有以 `TypeHandler` 为目标的记录；几十个具体 handler 又都继承它，于是 `TypeHandler` 家族在 implements 视图里几乎隐形，只在 `calls` 边里以 `TypeHandler.getResult`（283 条）出现。泛型接口签名是这个盲点的高发区。编译期接口断言、匿名内部类、lambda 同样不产生 implements 边；`ResolverUtil.java:87` / `:118` 的 `IsA` / `AnnotatedWith` 能连上 `Test` 接口，算是少数例外。

结论：接口实现矩阵能指出「存在一组同构类型」，数量必须回源码数。这和 [Higress 的符号图分册](/docs/CS/Framework/Higress/Call_Graph_Internals.md) 里嵌入式实现不建边的口径是同一类问题，只是 Java 这里的形态是继承。

## Java-XML Bridge

这个索引器专门为 MyBatis 合了一类边：`synthesizedBy=mybatis-java-xml` 共 331 条，全是 `calls`。metadata 形如：

```json
{
  "source": "org.apache.ibatis.submitted.rounding::Mapper::getUser2",
  "target": "src/site/es/xdoc/configuration.xml",
  "metadata": {
    "synthesizedBy": "mybatis-java-xml",
    "via": "Mapper.getUser2",
    "registeredAt": "src/site/es/xdoc/configuration.xml:1595"
  }
}
```

| 落点 | 条数 | 说明 |
| :--- | :--- | :--- |
| `src/test/resources/org/apache/...` 的真实 mapper XML | 323 | 测试用的 statement 声明 |
| `src/site/{es,ja,ko,zh_CN}/xdoc/configuration.xml` | 8 | 文档站四种语言的示例代码块被当成 mapper 声明 |

xml 文件里被提为 `method` 的节点 648 个：632 个来自测试 mapper XML，16 个来自那四份文档页（每份 `getUser` / `insert` / `getUser2` / `insert2` 四个）。于是 `src/test/java/org/apache/ibatis/submitted/rounding/Mapper.java:24` 的 `getUser2` 会同时「调用」四个语言版本的示例节点。

真正要记住的是运行期怎么对上的。`MapperBuilderAssistant.java:90-109` 与 `:213`：

```java
public String applyCurrentNamespace(String base, boolean isReference) {
  if (base == null) {
    return null;
  }
  if (isReference) {
    // is it qualified with any namespace yet?
    if (base.contains(".")) {
      return base;
    }
  } else {
    // is it qualified with this namespace yet?
    if (base.startsWith(currentNamespace + ".")) {
      return base;
    }
    if (base.contains(".")) {
      throw new BuilderException("Dots are not allowed in element names, please remove it from " + base);
    }
  }
  return currentNamespace + "." + base;
}
```

```java
id = applyCurrentNamespace(id, false);

MappedStatement.Builder statementBuilder = new MappedStatement.Builder(configuration, id, sqlSource, sqlCommandType)
    .resource(resource).fetchSize(fetchSize).timeout(timeout).statementType(statementType)
    .keyGenerator(keyGenerator).keyProperty(keyProperty).keyColumn(keyColumn).databaseId(databaseId).lang(lang)
    .resultOrdered(resultOrdered).resultSets(resultSets)
    // ...
```

Mapper 接口方法与 XML statement 靠 `namespace.id` 字符串对上，没有编译期引用。索引器只能按方法名合出候选边，不同 namespace 下的同名 id 会串线，文档里贴的代码也会被合进去。要确认「这个方法对应哪条 SQL」，只能回 `MappedStatement` 的 id 与 `Configuration.mappedStatements` 的 `StrictMap`（代码贴在 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)）。

## Call Sites from unresolved_refs

32054 条 `unresolved_refs` 全部是 `failed`，但它记录的不只是调用：

```sql
SELECT reference_name, count(*) AS n FROM unresolved_refs
GROUP BY reference_name ORDER BY n DESC LIMIT 6;
-- assertEquals 1966 | Test 1910 | Override 1592 | Integer 1004 | List 891 | Object 841
```

注解、泛型、类型字面量一律算未解析引用。另有 `new SqlSessionFactoryBuilder().build` 261 条、`sqlSessionFactory.getConfiguration().getEnvironment().getDataSource` 196 条，是 `submitted` 测试类的模板化写法。

用它统计调用点的正确姿势是先按 `reference_name` 精确过滤，再拿 `file_path` + `line` 回源码核一遍。例如查 `assistant.addMappedStatement` 的 `calls` 边，主源码侧落在四处：`XMLStatementBuilder.java:152`（正常语句）、`:201`（`<selectKey>`）、`MapperAnnotationBuilder.java:407`（注解语句）、`:627`（`@SelectKey`）。另外 `MapperBuilderAssistant.java:282`、`:292` 两条是重载之间的自调用，被标成 `exact-match` / `confidence=0.7`；测试里还有一批 `config.addMappedStatement` 直接构造 `MappedStatement`，属于测试夹具。

## Fan-in Illusion

按 `calls` 目标聚合的头部符号：

| 符号 | 扇入 |
| :--- | :--- |
| `SqlSessionFactory::openSession` | 890 |
| `SqlSession::getMapper` | 772 |
| `SqlSessionFactory::getConfiguration` | 320 |
| `TypeHandler::getResult` | 283 |
| `Resources::getResourceAsReader` | 248 |
| `BaseDataTest::runScript` | 218 |
| `TypeHandlerRegistry::getTypeHandler` | 191 |

一眼看去像「框架最热的六个入口」，实际是 1002 个测试类反复 `openSession` / `getMapper` 的结果：`BaseDataTest.runScript` 218 次对应各 `submitted` 场景启动灌库，`getResult` 283 次里有一大批是 `TypeHandler` 单测直接调实现类。扇入数字用来定位热门接口有用，用来判断运行期热路径会错得离谱。

插件链那侧的情况反过来：`Configuration.java:710` / `:717` / `:724` / `:748` 是 `interceptorChain.pluginAll(...)` 的四个调用点（代码贴在 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)），符号图能把它们指出来，但主源码里 `Interceptor` 的实现者数为 0，插件全在使用方代码里。想知道某个插件拦了什么，只能读它的 `@Intercepts` 签名（[Interceptor](/docs/CS/Framework/MyBatis/Interceptor.md)）。

## Unverified

- `calls` / `implements` 边的误连比例未做抽样量化，本页只举出可复核的实例（合成边、文档站示例、泛型接口缺失），不要把任何边计数直接当源码事实引用。
- `indexed_at_commit` 为空，且源码树没有 `.git`；换机器或换 CodeGraph 版本后，本页所有计数需重跑。
- `src/site/` 下 xdoc 页面被判为 mapper 声明的具体规则未查索引器实现，只从 `registeredAt` 与节点名字反推。
- `decorates` 622 条、`references` 6248 条的语义未逐类核对，本页只用 `calls` / `implements` / `extends` / `unresolved_refs` 四类。

## Links

- [MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)
- [Init](/docs/CS/Framework/MyBatis/Init.md)
- [Reflector](/docs/CS/Framework/MyBatis/Reflector.md)

## References

- [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
- [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
