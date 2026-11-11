## Introduction

注解路线常被写成「XML 的等价替代」，这在 3.6.0 的源码里站不住。它是另一条独立生产线：`MapperAnnotationBuilder` 自己设 namespace、自己建 cache、自己挑语言驱动，最后和 XML 一样把结果交给 `MapperBuilderAssistant.addMappedStatement`。两条线的互斥手段是 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md) 里那个 `"namespace:" + namespace` 伪资源名。本页把关键代码直接贴出来，取自本机 `mybatis-3.6.0` 源码树，路径相对 `src/main/java/org/apache/ibatis/`，省略处标 `// ...`。

## Annotation Surface

`annotations/` 下 34 个注解按用途分比按字母记快：语句类 `@Select` / `@Insert` / `@Update` / `@Delete`，Provider 类 `@SelectProvider` / `@InsertProvider` / `@UpdateProvider` / `@DeleteProvider`，结果映射类 `@Results` / `@Result` / `@ResultMap` / `@ResultType` / `@ConstructorArgs` / `@Arg` / `@AutomapConstructor` / `@One` / `@Many` / `@TypeDiscriminator` / `@Case` / `@MapKey`，主键与选项类 `@Options` / `@SelectKey` / `@Flush`，缓存类 `@CacheNamespace` / `@CacheNamespaceRef` / `@Property`，参数与标记类 `@Param` / `@Mapper`。

源码里带 `@since 3.6.0` 的只有三个注解定义，贴在这里比列版本清单直观。`NamedResultMap.java:63-75`：

```java
 * @since 3.6.0
 */
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
@Repeatable(NamedResultMaps.class)
public @interface NamedResultMap {
  String id();
```

`NamedResultMaps.java:24-34` 与 `ResultOrdered.java:24-35`：

```java
/**
 * Annotation for grouping named result maps
 *
 * @since 3.6.0
 */
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface NamedResultMaps {
  NamedResultMap[] value() default {};
}
```

```java
/**
 * Denote that a result set is known to be ordered. This is required for building results with collections in their
 * constructors.
 *
 * @since 3.6.0
 */
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface ResultOrdered {
  boolean value() default true;
}
```

一个注解上的属性是分批加进来的：`@Select.java` 自身就有 3.5.5、3.5.12 三处 `@since`，`@SelectProvider.java` 有 3.5.2、3.5.5、3.5.12 四处。按「注解什么时候出现」推能力边界会出错。`@since` 也只能证明作者标注了这个版本，源码里同时留着 `@Deprecated` 的旧重载（`ExpressionEvaluator.java:44-50`）。

## Parse Order

`MapperAnnotationBuilder.java:122-160` 一次给出整条注解生产线的顺序：

```java
public void parse() {
  String resource = type.toString();
  if (!configuration.isResourceLoaded(resource)) {
    loadXmlResource();
    configuration.addLoadedResource(resource);
    assistant.setCurrentNamespace(type.getName());
    parseCache();
    parseCacheRef();

    if (type.isAnnotationPresent(NamedResultMap.class)) {
      parseNamedResultMap(type.getAnnotation(NamedResultMap.class));
    }
    if (type.isAnnotationPresent(NamedResultMaps.class)) {
      parseNamedResultMaps();
    }

    for (Method method : type.getMethods()) {
      if (!canHaveStatement(method)) {
        continue;
      }
      if (getAnnotationWrapper(method, false, Select.class, SelectProvider.class).isPresent()
          && method.getAnnotation(ResultMap.class) == null) {
        parseResultMap(method);
      }
      try {
        parseStatement(method);
      } catch (IncompleteElementException e) {
        configuration.addIncompleteMethod(new MethodResolver(this, method));
      }
    }
  }
  configuration.parsePendingMethods(false);
}

private static boolean canHaveStatement(Method method) {
  // issue #237
  return !method.isBridge() && !method.isDefault();
}
```

`parseCache()` → `parseCacheRef()` 与 XML 的 `cache-ref` → `cache` 顺序相反；`@NamedResultMap` 在逐方法解析之前注册好；解析抛 `IncompleteElementException` 时把方法包成 `MethodResolver` 挂起。构造里那个 resource 字符串末尾是 `".java (best guess)"`，写进冲突报错时看到的就是这个猜测值。

`MapperAnnotationBuilder.java:162-180` 是两条线的接缝：

```java
private void loadXmlResource() {
  // Spring may not know the real resource name so we check a flag
  // to prevent loading again a resource twice
  // this flag is set at XMLMapperBuilder#bindMapperForNamespace
  if (!configuration.isResourceLoaded("namespace:" + type.getName())) {
    String xmlResource = type.getName().replace('.', '/') + ".xml";
    // #1347
    InputStream inputStream = type.getResourceAsStream("/" + xmlResource);
    if (inputStream == null) {
      // Search XML mapper that is not in the module but in the classpath.
      try {
        inputStream = Resources.getResourceAsStream(type.getClassLoader(), xmlResource);
      } catch (IOException e2) {
        // ignore, resource is not required
      }
    }
    if (inputStream != null) {
      XMLMapperBuilder xmlParser = new XMLMapperBuilder(inputStream, assistant.getConfiguration(), xmlResource,
          configuration.getSqlFragments(), type);
      xmlParser.parse();
    }
  }
}
```

XML 侧先解析时留下的标记让这里整体跳过，反过来注解侧先解析则按同包同名规则主动去找 XML，找到就用 `XMLMapperBuilder` 解析一遍。

bridge / default 方法被排除有两层后果：接口 default 方法由 `MapperProxy` 的 `DefaultMethodInvoker` 直接调，不产生 statement；编译期生成的 bridge 方法若不过滤，会与真实方法撞同一个 id。

## AnnotationWrapper

`statementAnnotationTypes` 是八个语句注解的 `Set`，`MapperAnnotationBuilder.java:668-692` 把它们统一成 `Optional<AnnotationWrapper>`：

```java
private Optional<AnnotationWrapper> getAnnotationWrapper(Method method, boolean errorIfNoMatch,
    Collection<Class<? extends Annotation>> targetTypes) {
  String databaseId = configuration.getDatabaseId();
  Map<String, AnnotationWrapper> statementAnnotations = targetTypes.stream()
      .flatMap(x -> Arrays.stream(method.getAnnotationsByType(x))).map(AnnotationWrapper::new)
      .collect(Collectors.toMap(AnnotationWrapper::getDatabaseId, x -> x, (existing, duplicate) -> {
        throw new BuilderException(
            String.format("Detected conflicting annotations '%s' and '%s' on '%s'.", existing.getAnnotation(),
                duplicate.getAnnotation(), method.getDeclaringClass().getName() + "." + method.getName()));
      }));
  AnnotationWrapper annotationWrapper = null;
  if (databaseId != null) {
    annotationWrapper = statementAnnotations.get(databaseId);
  }
  if (annotationWrapper == null) {
    annotationWrapper = statementAnnotations.get("");
  }
  if (errorIfNoMatch && annotationWrapper == null && !statementAnnotations.isEmpty()) {
    // Annotations exist, but there is no matching one for the specified databaseId
    throw new BuilderException(String.format(
        "Could not find a statement annotation that correspond a current database or default statement on method '%s.%s'. Current database id is [%s].",
        method.getDeclaringClass().getName(), method.getName(), databaseId));
  }
  return Optional.ofNullable(annotationWrapper);
}
```

`getAnnotationsByType` 会把 `@Repeatable` 的多个注解展开，再按 `databaseId` 收进 Map；`Collectors.toMap` 的合并函数直接抛冲突异常，所以同一个方法上写两个都不指定 databaseId 的 `@Select`，在找注解这一步就报错，早于注册 statement。取值顺序是先按当前 `configuration.getDatabaseId()`，取不到退回 `""`。`AnnotationWrapper`（`:711-715`）除 `annotation` / `databaseId` / `sqlCommandType` 外还带一个 `dirtySelect`，对应 XML 的 `affectData`。

`parseStatement` 找语句注解、`@Options`、`@ResultOrdered`、`@SelectKey` 全走这个方法（`:337`、`:341`、`:343`、`:352`），注解侧的 databaseId 语义因此和 XML 的 `databaseId` 属性一致，只是冲突检测更早。

## Provider Path

`ProviderSqlSource.java:163-205` 是「provider 方法每次执行都会跑」的直接证据，`getBoundSql` 每次都重新 `createSqlSource`：

```java
@Override
public BoundSql getBoundSql(Object parameterObject) {
  SqlSource sqlSource = createSqlSource(parameterObject);
  return sqlSource.getBoundSql(parameterObject);
}

private SqlSource createSqlSource(Object parameterObject) {
  try {
    String sql;
    if (parameterObject instanceof Map) {
      int bindParameterCount = providerMethodParameterTypes.length - (providerContext == null ? 0 : 1);
      if (bindParameterCount == 1
          && providerMethodParameterTypes[Integer.valueOf(0).equals(providerContextIndex) ? 1 : 0]
              .isAssignableFrom(parameterObject.getClass())) {
        sql = invokeProviderMethod(extractProviderMethodArguments(parameterObject));
      } else {
        Map<String, Object> params = (Map<String, Object>) parameterObject;
        sql = invokeProviderMethod(extractProviderMethodArguments(params, paramNameResolver.getNames()));
      }
    } else {
      switch (providerMethodParameterTypes.length) {
        case 0:
          sql = invokeProviderMethod();
          break;
        case 1:
          if (providerContext == null) {
            sql = invokeProviderMethod(parameterObject);
          } else {
            sql = invokeProviderMethod(providerContext);
          }
          break;
        case 2:
          sql = invokeProviderMethod(extractProviderMethodArguments(parameterObject));
          break;
        default:
          throw new BuilderException("Cannot invoke SqlProvider method '" + providerMethod
              + "' with specify parameter '" + (parameterObject == null ? null : parameterObject.getClass())
              + "' because SqlProvider method arguments for '" + mapperMethod + "' is an invalid combination.");
      }
    }
    Class<?> parameterType = parameterObject == null ? Object.class : parameterObject.getClass();
    return languageDriver.createSqlSource(configuration, sql, parameterType, paramNameResolver);
```

构造期（`:114`、`:141`、`:146-160`）只定位 provider 方法、为它建 `ParamNameResolver`、记下 `ProviderContext` 参数下标；拿到 SQL 字符串后才交给语言驱动，后续与普通注解 SQL 同路。这与 `RawSqlSource` 恰好相反，后者在构造里就把 `#{}` 全换成 `?`（见 [SqlSource and Parameters](/docs/CS/Framework/MyBatis/SqlSource_and_Parameters.md)）。带状态或做远程调用的 provider 方法会跟着每次查询跑。

## Named Result Maps

`@NamedResultMap` 标在类型上，`@Repeatable(NamedResultMaps.class)` 让单个与多个都能被 `parse()` 收下。`MapperAnnotationBuilder.java:245-269` 给出注册与校验：

```java
private void parseNamedResultMap(NamedResultMap namedResultMap) {
  validateNamedResultMap(namedResultMap);

  String resultMapId = type.getName() + '.' + namedResultMap.id();
  Class<?> returnType = namedResultMap.javaType();
  Arg[] args = namedResultMap.constructorArguments();
  Result[] results = namedResultMap.propertyMappings();
  TypeDiscriminator typeDiscriminator = namedResultMap.typeDiscriminator();
  if (AnnotationConstants.NULL_TYPE_DISCRIMINATOR.equals(typeDiscriminator.column())) {
    typeDiscriminator = null;
  }

  applyResultMap(resultMapId, returnType, args, results, typeDiscriminator);
}

private void validateNamedResultMap(NamedResultMap namedResultMap) {
  if (!AnnotationConstants.NULL_TYPE_DISCRIMINATOR.equals(namedResultMap.typeDiscriminator().column())) {
    return;
  }
  if (namedResultMap.constructorArguments().length == 0 && namedResultMap.propertyMappings().length == 0) {
    throw new BuilderException("If there is no type discriminator, then the NamedResultMap annotation "
        + "requires at least one constructor argument or property mapping");
  }
}
```

生成的 id 是 `类型全名.id`，`@ResultMap("someId")` 因此有了不依赖 XML 的来源，多个方法共用一个 `@Results` 不必再抄一遍。

## ResultOrdered

`@ResultOrdered` 在 `parseStatement` 的 `:343-344` 取出、`:392-394` 转成 `isResultOrdered`、`:407-414` 随 `addMappedStatement` 写进 `MappedStatement`。三个消费点全在 `DefaultResultSetHandler`。`DefaultResultSetHandler.java:387-392`：

```java
protected void checkResultHandler() {
  if (resultHandler != null && configuration.isSafeResultHandlerEnabled() && !mappedStatement.isResultOrdered()) {
    throw new ExecutorException(
        "Mapped Statements with nested result mappings cannot be safely used with a custom ResultHandler. "
            + "Use safeResultHandlerEnabled=false setting to bypass this check "
            + "or ensure your statement returns ordered data and set resultOrdered=true on it.");
```

`DefaultResultSetHandler.java:1177-1196` 是嵌套结果映射分支：

```java
} else if (mappedStatement.isResultOrdered()) {
  if (foundNewUniqueRow && rowValue != null) {
    nestedResultObjects.clear();
    storeObject(resultHandler, resultContext, rowValue, parentMapping, resultSet);
  }
  rowValue = getRowValue(rsw, discriminatedResultMap, rowKey, null, partialObject);
} else {
  rowValue = getRowValue(rsw, discriminatedResultMap, rowKey, null, partialObject);
  if (foundNewUniqueRow) {
    storeObject(resultHandler, resultContext, rowValue, parentMapping, resultSet);
  }
}
```

```java
if (useCollectionConstructorInjection && lastHandledCreation != null) {
  createAndStorePendingCreation(resultHandler, resultSet, resultContext, lastHandledCreation);
} else if (rowValue != null && mappedStatement.isResultOrdered()
    && shouldProcessMoreRows(resultContext, rowBounds)) {
  storeObject(resultHandler, resultContext, rowValue, parentMapping, resultSet);
  previousRowValue = null;
} else if (rowValue != null) {
  previousRowValue = rowValue;
}
```

允许框架假设结果已按嵌套 key 有序，从而清掉 `nestedResultObjects`、不保留上一行中间状态，跟排序无关。假设不成立时丢行是自己的责任。XML 侧对应 `<select resultOrdered="true">`，默认值来自 `XMLStatementBuilder.java:84`。

## Where the Two Lines Collide

XML 与注解注册同一个 id 时，`StrictMap.put` 抛异常（代码贴在 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)）。`SqlSessionTest.java:447-460` 把这个行为写成了可执行断言，报错文本里两个 `getResource()` 的来源都看得到：

```java
@Test
void shouldThrowExceptionIfTryingToAddStatementWithSameNameInAnnotation() {
  Configuration config = sqlMapper.getConfiguration();
  try {
    MappedStatement ms = new MappedStatement.Builder(config,
        "org.apache.ibatis.domain.blog.mappers.AuthorMapper.selectAuthor2", Mockito.mock(SqlSource.class),
        SqlCommandType.SELECT).resource("org/mybatis/TestMapper.xml").build();
    config.addMappedStatement(ms);
    fail("Expected exception to be thrown due to statement that already exists.");
  } catch (Exception e) {
    assertTrue(e.getMessage().contains(
        "already contains key org.apache.ibatis.domain.blog.mappers.AuthorMapper.selectAuthor2. please check org/apache/ibatis/domain/blog/mappers/AuthorMapper.java (best guess) and org/mybatis/TestMapper.xml"));
  }
}
```

`shouldThrowExceptionIfTryingToAddStatementWithSameNameInXml`（`:430-445`）结构相同，只是冲突来源换成 `BlogMapper.xml`。符号图里两条 `config.addMappedStatement` 调用就落在这两个方法上，报错来自注册中心。

`@ResultMap` 与 `@CacheNamespaceRef` 的引用可能指向还没解析的类型，这两类未决引用走 [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md) 里的挂起队列。

## Unverified

- `parseCache()` / `parseCacheRef()`（`:186`、`:208`）的字段与 `@Property` 展开规则未逐项核对；本页只确认调用顺序与它和 XML 侧相反。
- `ProviderMethodResolver.resolveMethod` 的候选方法匹配规则未展开，多候选时的选择顺序未实测。
- `validateNamedResultMap` 只核到 `MapperAnnotationBuilder.java:260-268` 的报错分支，未穷举合法/非法组合。
- `AnnotationWrapper.dirtySelect` 从注解属性到 `MappedStatement` 的赋值链未逐行追踪，只确认 `:711-715` 有该字段与 `:407-414` 的调用。

## Links

- [ResultSetHandler](/docs/CS/Framework/MyBatis/ResultSetHandler.md)
- [binding](/docs/CS/Framework/MyBatis/binding.md)
- [KeyGenerator](/docs/CS/Framework/MyBatis/KeyGenerator.md)

## References

- [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
- [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
