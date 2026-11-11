## Introduction

一次 `SqlSessionFactoryBuilder.build()` 里发生的是两段解析：先把全局配置变成一份 `Configuration`，再把每个 mapper 资源变成挂在它上面的 `MappedStatement` / `ResultMap` / `Cache`。[Init](/docs/CS/Framework/MyBatis/Init.md) 已经贴过 `build()` 与 `BaseBuilder` 的代码，这一页只讲顺序。下面每个结论都配了对应的源码片段，取自本机 `mybatis-3.6.0` 源码树，路径相对 `src/main/java/org/apache/ibatis/`，代码块上方标了行号；片段只删掉 import 与部分注释，省略处标 `// ...`。

## Parse Order

`XMLConfigBuilder.java:105-135`：

```java
public Configuration parse() {
  if (parsed) {
    throw new BuilderException("Each XMLConfigBuilder can only be used once.");
  }
  parsed = true;
  parseConfiguration(parser.evalNode("/configuration"));
  return configuration;
}

private void parseConfiguration(XNode root) {
  try {
    // issue #117 read properties first
    propertiesElement(root.evalNode("properties"));
    Properties settings = settingsAsProperties(root.evalNode("settings"));
    loadCustomVfsImpl(settings);
    loadCustomLogImpl(settings);
    typeAliasesElement(root.evalNode("typeAliases"));
    pluginsElement(root.evalNode("plugins"));
    objectFactoryElement(root.evalNode("objectFactory"));
    objectWrapperFactoryElement(root.evalNode("objectWrapperFactory"));
    reflectorFactoryElement(root.evalNode("reflectorFactory"));
    settingsElement(settings);
    // read it after objectFactory and objectWrapperFactory issue #631
    environmentsElement(root.evalNode("environments"));
    databaseIdProviderElement(root.evalNode("databaseIdProvider"));
    typeHandlersElement(root.evalNode("typeHandlers"));
    mappersElement(root.evalNode("mappers"));
  } catch (Exception e) {
    throw new BuilderException("Error parsing SQL Mapper Configuration. Cause: " + e, e);
  }
}
```

12 步里几个位置是 issue 修出来的：`properties` 必须第一，后面所有 `${...}` 都依赖它；VFS 与日志实现要在扫包之前定下来；`settings` 在第 2 步就读成 `Properties`，但直到第 10 步才用 `MetaClass` 写进 `Configuration`，所以读得早、生效得晚；`environments` 的注释点名 `objectFactory` 与 `objectWrapperFactory` 必须先就位；`typeHandlers` 排在 `settings` 之后，让自定义处理器能读到全局默认值。

`plugins` 在第 6 步，早于 `environments` 与 `mappers`。`pluginsElement` 走的是 `InterceptorChain.addInterceptor`（`InterceptorChain.java:35-37`），这一步只是把实例放进 `List<Interceptor>`：

```java
public class InterceptorChain {

  private final List<Interceptor> interceptors = new ArrayList<>();

  public Object pluginAll(Object target) {
    for (Interceptor interceptor : interceptors) {
      target = interceptor.plugin(target);
    }
    return target;
  }

  public void addInterceptor(Interceptor interceptor) {
    interceptors.add(interceptor);
  }
}
```

真正让代理生效的是 `Configuration` 里四个工厂方法末尾的 `pluginAll`。`Configuration.java:710-729`：

```java
public ParameterHandler newParameterHandler(MappedStatement mappedStatement, Object parameterObject,
    BoundSql boundSql) {
  ParameterHandler parameterHandler = mappedStatement.getLang().createParameterHandler(mappedStatement,
      parameterObject, boundSql);
  return (ParameterHandler) interceptorChain.pluginAll(parameterHandler);
}

public ResultSetHandler newResultSetHandler(Executor executor, MappedStatement mappedStatement, RowBounds rowBounds,
    ParameterHandler parameterHandler, ResultHandler resultHandler, BoundSql boundSql) {
  ResultSetHandler resultSetHandler = new DefaultResultSetHandler(executor, mappedStatement, parameterHandler,
      resultHandler, boundSql, rowBounds);
  return (ResultSetHandler) interceptorChain.pluginAll(resultSetHandler);
}

public StatementHandler newStatementHandler(Executor executor, MappedStatement mappedStatement,
    Object parameterObject, RowBounds rowBounds, ResultHandler resultHandler, BoundSql boundSql) {
  StatementHandler statementHandler = new RoutingStatementHandler(executor, mappedStatement, parameterObject,
      rowBounds, resultHandler, boundSql);
  return (StatementHandler) interceptorChain.pluginAll(statementHandler);
}
```

`Configuration.java:735-749` 的 `newExecutor` 同形：先按 `ExecutorType` 造 `BatchExecutor` / `ReuseExecutor` / `SimpleExecutor`，`cacheEnabled` 为真时再包一层 `CachingExecutor`，最后才 `pluginAll(executor)`。这就是插件能拦到后续所有组件创建的原因，见 [Interceptor](/docs/CS/Framework/MyBatis/Interceptor.md)。

## Configuration Registries

`Configuration.java:152-164` 里可替换的点是数得清的：三张注册表、两个工厂、`interceptorChain`，以及若干 `StrictMap`。

```java
protected final MapperRegistry mapperRegistry = new MapperRegistry(this);
protected final InterceptorChain interceptorChain = new InterceptorChain();
protected final TypeHandlerRegistry typeHandlerRegistry = new TypeHandlerRegistry(this);
protected final TypeAliasRegistry typeAliasRegistry = new TypeAliasRegistry();
protected final LanguageDriverRegistry languageRegistry = new LanguageDriverRegistry();

protected final Map<String, MappedStatement> mappedStatements = new StrictMap<MappedStatement>(
    "Mapped Statements collection")
        .conflictMessageProducer((savedValue, targetValue) -> ". please check " + savedValue.getResource() + " and "
            + targetValue.getResource());
protected final Map<String, Cache> caches = new StrictMap<>("Caches collection");
protected final Map<String, ResultMap> resultMaps = new StrictMap<>("Result Maps collection");
protected final Map<String, ParameterMap> parameterMaps = new StrictMap<>("Parameter Maps collection");
```

`StrictMap` 是「同一 id 被 XML 和注解各写一遍」报错的出处。`Configuration.java:1154-1192`：

```java
@Override
@SuppressWarnings("unchecked")
public V put(String key, V value) {
  if (containsKey(key)) {
    throw new IllegalArgumentException(name + " already contains key " + key
        + (conflictMessageProducer == null ? "" : conflictMessageProducer.apply(super.get(key), value)));
  }
  if (key.contains(".")) {
    final String shortKey = getShortName(key);
    if (super.get(shortKey) == null) {
      super.put(shortKey, value);
    } else {
      super.put(shortKey, (V) AMBIGUITY_INSTANCE);
    }
  }
  return super.put(key, value);
}

@Override
public boolean containsKey(Object key) {
  if (key == null) {
    return false;
  }
  return super.get(key) != null;
}

@Override
public V get(Object key) {
  V value = super.get(key);
  if (value == null) {
    throw new IllegalArgumentException(name + " does not contain value for " + key);
  }
  if (AMBIGUITY_INSTANCE == value) {
    throw new IllegalArgumentException(key + " is ambiguous in " + name
        + " (try using the full name including the namespace, or rename one of the entries)");
  }
  return value;
}
```

全名重复直接抛异常，`mappedStatements` 还挂了 `conflictMessageProducer`，把两个冲突来源的 `getResource()` 拼进报错，所以错误信息里能直接看到是哪两个文件撞了。全名不冲突时，key 含 `.` 就再存一份短名；短名第二次出现写入 `AMBIGUITY_INSTANCE` 哨兵，`get` 取到它抛的是「含糊的短名」。`selectOne("getUser")` 在多个 namespace 下报错就来自这里。`containsKey` 被重写成 `super.get(key) != null`，因此 null 值不算存在。

`Configuration.java:190-202` 的构造函数预置了一批别名，这些不需要在 XML 里声明：

```java
public Configuration() {
  typeAliasRegistry.registerAlias("JDBC", JdbcTransactionFactory.class);
  typeAliasRegistry.registerAlias("MANAGED", ManagedTransactionFactory.class);

  typeAliasRegistry.registerAlias("JNDI", JndiDataSourceFactory.class);
  typeAliasRegistry.registerAlias("POOLED", PooledDataSourceFactory.class);
  typeAliasRegistry.registerAlias("UNPOOLED", UnpooledDataSourceFactory.class);

  typeAliasRegistry.registerAlias("PERPETUAL", PerpetualCache.class);
  typeAliasRegistry.registerAlias("FIFO", FifoCache.class);
  typeAliasRegistry.registerAlias("LRU", LruCache.class);
  typeAliasRegistry.registerAlias("SOFT", SoftCache.class);
  typeAliasRegistry.registerAlias("WEAK", WeakCache.class);
```

## Mapper Parse Order

`XMLMapperBuilder.java:103-134` 一次给出守卫、元素顺序与末尾三次挂起重试：

```java
public void parse() {
  if (!configuration.isResourceLoaded(resource)) {
    configurationElement(parser.evalNode("/mapper"));
    configuration.addLoadedResource(resource);
    bindMapperForNamespace();
  }
  configuration.parsePendingResultMaps(false);
  configuration.parsePendingCacheRefs(false);
  configuration.parsePendingStatements(false);
}

private void configurationElement(XNode context) {
  try {
    String namespace = context.getStringAttribute("namespace");
    if (namespace == null || namespace.isEmpty()) {
      throw new BuilderException("Mapper's namespace cannot be empty");
    }
    builderAssistant.setCurrentNamespace(namespace);
    cacheRefElement(context.evalNode("cache-ref"));
    cacheElement(context.evalNode("cache"));
    parameterMapElement(context.evalNodes("/mapper/parameterMap"));
    resultMapElements(context.evalNodes("/mapper/resultMap"));
    sqlElement(context.evalNodes("/mapper/sql"));
    buildStatementFromContext(context.evalNodes("select|insert|update|delete"));
  } catch (Exception e) {
    throw new BuilderException("Error parsing Mapper XML. The XML location is '" + resource + "'. Cause: " + e, e);
  }
}
```

`cache-ref` 排在 `cache` 之前有实际原因：前者只记录「这个 namespace 借用哪个 namespace 的缓存」，被引用方可能还没出现，因此最容易落进挂起队列。`buildStatementFromContext` 还会按 `configuration.getDatabaseId()` 把语句解析跑两遍，先带 databaseId 再不带，同一 id 因此能有多份按数据库区分的语句。

`XMLMapperBuilder.java:401-418` 里那个 `"namespace:"` 前缀，是 XML 与注解两条生产线互斥的全部机关：

```java
private void bindMapperForNamespace() {
  String namespace = builderAssistant.getCurrentNamespace();
  if (namespace != null) {
    Class<?> boundType = null;
    try {
      boundType = Resources.classForName(namespace);
    } catch (ClassNotFoundException e) {
      // ignore, bound type is not required
    }
    if (boundType != null && !configuration.hasMapper(boundType)) {
      // Spring may not know the real resource name so we set a flag
      // to prevent loading again this resource from the mapper interface
      // look at MapperAnnotationBuilder#loadXmlResource
      configuration.addLoadedResource("namespace:" + namespace);
      configuration.addMapper(boundType);
    }
  }
}
```

namespace 能当类名加载时，先写这个伪资源名再注册 Mapper；注解侧的 `loadXmlResource()` 见到它就跳过同名 XML（代码贴在 [Annotation Mapper](/docs/CS/Framework/MyBatis/Annotation_Mapper.md)）。注释把动因写明了：Spring 未必知道真实资源名。

## Include Before Parsing

`<include>` 在语句级、`LanguageDriver` 介入之前就把 DOM 改掉了。`XMLStatementBuilder.java:82-88` 的顺序是先定默认值、再 `applyIncludes`：

```java
boolean isSelect = sqlCommandType == SqlCommandType.SELECT;
boolean flushCache = context.getBooleanAttribute("flushCache", !isSelect);
boolean useCache = context.getBooleanAttribute("useCache", isSelect);
boolean resultOrdered = context.getBooleanAttribute("resultOrdered", false);

// Include Fragments before parsing
XMLIncludeTransformer includeParser = new XMLIncludeTransformer(configuration, builderAssistant);
includeParser.applyIncludes(context.getNode());
```

到 `XMLStatementBuilder.java:118` 的注释已经写成 `pre: <selectKey> and <include> were parsed and removed`。`XMLIncludeTransformer.java:61-100` 说明这是递归改 DOM，不是字符串替换：

```java
private void applyIncludes(Node source, final Properties variablesContext, boolean included) {
  if ("include".equals(source.getNodeName())) {
    Node toInclude = findSqlFragment(getStringAttribute(source, "refid"), variablesContext);
    Properties toIncludeContext = getVariablesContext(source, variablesContext);
    applyIncludes(toInclude, toIncludeContext, true);
    if (toInclude.getOwnerDocument() != source.getOwnerDocument()) {
      toInclude = source.getOwnerDocument().importNode(toInclude, true);
    }
    source.getParentNode().replaceChild(toInclude, source);
    while (toInclude.hasChildNodes()) {
      toInclude.getParentNode().insertBefore(toInclude.getFirstChild(), toInclude);
    }
    toInclude.getParentNode().removeChild(toInclude);
  } else if (source.getNodeType() == Node.ELEMENT_NODE) {
    if (included && !variablesContext.isEmpty()) {
      NamedNodeMap attributes = source.getAttributes();
      for (int i = 0; i < attributes.getLength(); i++) {
        Node attr = attributes.item(i);
        attr.setNodeValue(PropertyParser.parse(attr.getNodeValue(), variablesContext));
      }
    }
    NodeList children = source.getChildNodes();
    for (int i = 0; i < children.getLength(); i++) {
      applyIncludes(children.item(i), variablesContext, included);
    }
  } else if (included && (source.getNodeType() == Node.TEXT_NODE || source.getNodeType() == Node.CDATA_SECTION_NODE)
      && !variablesContext.isEmpty()) {
    source.setNodeValue(PropertyParser.parse(source.getNodeValue(), variablesContext));
  }
}

private Node findSqlFragment(String refid, Properties variables) {
  refid = PropertyParser.parse(refid, variables);
  refid = builderAssistant.applyCurrentNamespace(refid, true);
  try {
    XNode nodeToInclude = configuration.getSqlFragments().get(refid);
    return nodeToInclude.getNode().cloneNode(true);
  } catch (IllegalArgumentException e) {
    throw new IncompleteElementException("Could not find SQL statement to include with refid '" + refid + "'", e);
  }
}
```

`included` 这个布尔只在片段内部为真，所以 `${}` 替换只作用于被 include 进来的属性值与文本节点，外层语句的 `${}` 留给 `XMLLanguageDriver` 的 `PropertyParser.parse`（见 [SqlSource and Parameters](/docs/CS/Framework/MyBatis/SqlSource_and_Parameters.md)）。`refid` 自己也过一遍 `PropertyParser.parse`，`${prefix}Columns` 这类动态 refid 因此合法。

DTD 是离线解析的，`XMLMapperEntityResolver.java:35-41, 56-66`：

```java
private static final String IBATIS_CONFIG_SYSTEM = "ibatis-3-config.dtd";
private static final String IBATIS_MAPPER_SYSTEM = "ibatis-3-mapper.dtd";
private static final String MYBATIS_CONFIG_SYSTEM = "mybatis-3-config.dtd";
private static final String MYBATIS_MAPPER_SYSTEM = "mybatis-3-mapper.dtd";

private static final String MYBATIS_CONFIG_DTD = "org/apache/ibatis/builder/xml/mybatis-3-config.dtd";
private static final String MYBATIS_MAPPER_DTD = "org/apache/ibatis/builder/xml/mybatis-3-mapper.dtd";

@Override
public InputSource resolveEntity(String publicId, String systemId) throws SAXException {
  try {
    if (systemId != null) {
      String lowerCaseSystemId = systemId.toLowerCase(Locale.ENGLISH);
      if (lowerCaseSystemId.contains(MYBATIS_CONFIG_SYSTEM) || lowerCaseSystemId.contains(IBATIS_CONFIG_SYSTEM)) {
        return getInputSource(MYBATIS_CONFIG_DTD, publicId, systemId);
      }
      if (lowerCaseSystemId.contains(MYBATIS_MAPPER_SYSTEM) || lowerCaseSystemId.contains(IBATIS_MAPPER_SYSTEM)) {
        return getInputSource(MYBATIS_MAPPER_DTD, publicId, systemId);
      }
    }
    return null;
  } catch (Exception e) {
    throw new SAXException(e.toString());
  }
}
```

四组 system id 收敛到 classpath 下两个本地 DTD，按包含关系匹配，断网环境下 mapper XML 照样能解析。

## Statement Assembly

`parseStatementNode()` 把一条 `<select>` 拆成约二十个属性。`XMLStatementBuilder.java:90-110` 是「XML 没写 `parameterType` 时从 Mapper 接口反推」的实现：

```java
String parameterType = context.getStringAttribute("parameterType");
Class<?> parameterTypeClass = resolveClass(parameterType);
ParamNameResolver paramNameResolver = null;
if (parameterTypeClass == null && mapperClass != null) {
  List<Method> mapperMethods = Arrays.stream(mapperClass.getMethods())
      .filter(m -> m.getName().equals(id) && !m.isDefault() && !m.isBridge()).collect(Collectors.toList());
  if (mapperMethods.size() == 1) {
    paramNameResolver = new ParamNameResolver(configuration, mapperMethods.get(0), mapperClass);
    if (paramNameResolver.isUseParamMap()) {
      parameterTypeClass = ParamMap.class;
    } else {
      String[] paramNames = paramNameResolver.getNames();
      if (paramNames.length == 1) {
        Type paramType = paramNameResolver.getType(paramNames[0]);
        if (paramType instanceof Class) {
          parameterTypeClass = (Class<?>) paramType;
        }
      }
    }
  }
}
```

反推有前提：方法名与 id 同名、非 bridge、非 default，并且唯一。重载同名方法会让 `mapperMethods.size() == 1` 不成立，整段跳过。`XMLStatementBuilder.java:112-130` 接着选语言驱动、处理 `<selectKey>`、决定 `KeyGenerator`，然后才把 DOM 交给 `LanguageDriver`：

```java
String lang = context.getStringAttribute("lang");
LanguageDriver langDriver = getLanguageDriver(lang);

// Parse selectKey after includes and remove them.
processSelectKeyNodes(id, parameterTypeClass, langDriver);

// Parse the SQL (pre: <selectKey> and <include> were parsed and removed)
KeyGenerator keyGenerator;
String keyStatementId = id + SelectKeyGenerator.SELECT_KEY_SUFFIX;
keyStatementId = builderAssistant.applyCurrentNamespace(keyStatementId, true);
if (configuration.hasKeyGenerator(keyStatementId)) {
  keyGenerator = configuration.getKeyGenerator(keyStatementId);
} else {
  keyGenerator = context.getBooleanAttribute("useGeneratedKeys",
      configuration.isUseGeneratedKeys() && SqlCommandType.INSERT.equals(sqlCommandType))
          ? Jdbc3KeyGenerator.INSTANCE : NoKeyGenerator.INSTANCE;
}

SqlSource sqlSource = langDriver.createSqlSource(configuration, context, parameterTypeClass, paramNameResolver);
```

`resultType` 与 `resultMap` 都没写时同样反查接口返回类型，`XMLStatementBuilder.java:136-141`：

```java
String resultType = context.getStringAttribute("resultType");
Class<?> resultTypeClass = resolveClass(resultType);
String resultMap = context.getStringAttribute("resultMap");
if (resultTypeClass == null && resultMap == null) {
  resultTypeClass = MapperAnnotationBuilder.getMethodReturnType(builderAssistant.getCurrentNamespace(), id);
}
```

`getMethodReturnType` 找不到对应接口时静默返回 `null`（`MapperAnnotationBuilder.java:694-709`）。最后 `XMLStatementBuilder.java:150-154` 把 `affectData` 读成 `dirtySelect`，连同 `paramNameResolver` 一起交给注册中心：

```java
boolean dirtySelect = context.getBooleanAttribute("affectData", Boolean.FALSE);

builderAssistant.addMappedStatement(id, sqlSource, statementType, sqlCommandType, fetchSize, timeout, parameterMap,
    parameterTypeClass, resultMap, resultTypeClass, resultSetTypeEnum, flushCache, useCache, resultOrdered,
    keyGenerator, keyProperty, keyColumn, databaseId, langDriver, resultSets, dirtySelect, paramNameResolver);
```

## Pending Queues

解析中途遇到「引用还没出现」时，MyBatis 把构建器挂起来而不是立即报错。`Configuration.java:169-177` 给出四个集合与四把独立的锁：

```java
protected final Collection<XMLStatementBuilder> incompleteStatements = new LinkedList<>();
protected final Collection<CacheRefResolver> incompleteCacheRefs = new LinkedList<>();
protected final Collection<ResultMapResolver> incompleteResultMaps = new LinkedList<>();
protected final Collection<MethodResolver> incompleteMethods = new LinkedList<>();

private final ReentrantLock incompleteResultMapsLock = new ReentrantLock();
private final ReentrantLock incompleteCacheRefsLock = new ReentrantLock();
private final ReentrantLock incompleteStatementsLock = new ReentrantLock();
private final ReentrantLock incompleteMethodsLock = new ReentrantLock();
```

| 集合 | 元素 | 谁在末尾重试 |
| :--- | :--- | :--- |
| `incompleteResultMaps` | `ResultMapResolver` | `XMLMapperBuilder.parse()` |
| `incompleteCacheRefs` | `CacheRefResolver` | `XMLMapperBuilder.parse()` |
| `incompleteStatements` | `XMLStatementBuilder` | `XMLMapperBuilder.parse()` |
| `incompleteMethods` | `MethodResolver` | `MapperAnnotationBuilder.parse()` |

`Configuration.java:973-1016` 把重试语义写得很清楚：

```java
protected void buildAllStatements() {
  parsePendingResultMaps(true);
  parsePendingCacheRefs(true);
  parsePendingStatements(true);
  parsePendingMethods(true);
}

public void parsePendingMethods(boolean reportUnresolved) {
  if (incompleteMethods.isEmpty()) {
    return;
  }
  incompleteMethodsLock.lock();
  try {
    incompleteMethods.removeIf(x -> {
      x.resolve();
      return true;
    });
  } catch (IncompleteElementException e) {
    if (reportUnresolved) {
      throw e;
    }
  } finally {
    incompleteMethodsLock.unlock();
  }
}

public void parsePendingStatements(boolean reportUnresolved) {
  if (incompleteStatements.isEmpty()) {
    return;
  }
  incompleteStatementsLock.lock();
  try {
    incompleteStatements.removeIf(x -> {
      x.parseStatementNode();
      return true;
    });
  } catch (IncompleteElementException e) {
    if (reportUnresolved) {
      throw e;
    }
  } finally {
    incompleteStatementsLock.unlock();
  }
}
```

`XMLMapperBuilder.parse()` 末尾三次调用都传 `false`，解析阶段的未决引用被静默容忍；`buildAllStatements()` 传 `true` 才是强制检查。`removeIf` 的回调恒返回 `true`，列表每次清空，重试失败的元素不会留到下一轮，前面已经 resolve 过的方法也不会回滚。`MethodResolver` 本身只有 36 行，唯一的方法是 `resolve() { annotationBuilder.parseStatement(method); }`，作用是把单个方法的解析包成可延迟调用的对象，见 [Annotation Mapper](/docs/CS/Framework/MyBatis/Annotation_Mapper.md)。

## Unverified

- `settingsElement` 用 `MetaClass` 逐个设值的完整字段表、以及 `Settings` 与 `Configuration` 的字段对应关系未逐项核对；本页只确认调用位置 `XMLConfigBuilder.java:126` 与 `:261`。
- `databaseIdMatchesCurrent` 的具体匹配规则（`XMLStatementBuilder.java:75`）未展开，多 databaseId 语句的优先级未做实测。
- `XMLMapperBuilder` 的 `resultMapElements` / `sqlElement` 内部对 `extend`、`<include>` 嵌套片段的处理只核到方法位置（`:210`、`:318-325`），未逐分支验证。
- `buildAllStatements()` 的所有触发点没有普查，`Configuration.java:973-977` 只代表查到的那一处汇总调用。

## Links

- [MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)
- [KeyGenerator](/docs/CS/Framework/MyBatis/KeyGenerator.md)
- [Cache](/docs/CS/Framework/MyBatis/Cache.md)

## References

- [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
- [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
