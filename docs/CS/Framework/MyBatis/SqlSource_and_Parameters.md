## Introduction

`SqlSource` 是启动期产物，`BoundSql` 是运行期产物，这条分界决定了 `#{id}` 到底什么时候变成 `?`。[Dynamic SQL](/docs/CS/Framework/MyBatis/Dynamic_SQL.md) 讲 `SqlNode` 树怎么建，本页讲树跑完之后 SQL 文本、参数映射与 JDBC 占位符怎么对齐。代码块取自本机 `mybatis-3.6.0` 源码树，路径相对 `src/main/java/org/apache/ibatis/`，省略处标 `// ...`。

## LanguageDriver Registry

`LanguageDriverRegistry.java:24-69` 只有一张 Map 和一个默认类：

```java
public class LanguageDriverRegistry {

  private final Map<Class<? extends LanguageDriver>, LanguageDriver> languageDriverMap = new HashMap<>();
  private Class<? extends LanguageDriver> defaultDriverClass;

  public void register(Class<? extends LanguageDriver> cls) {
    if (cls == null) {
      throw new IllegalArgumentException("null is not a valid Language Driver");
    }
    languageDriverMap.computeIfAbsent(cls, k -> {
      try {
        return k.getDeclaredConstructor().newInstance();
      } catch (Exception ex) {
        throw new ScriptingException("Failed to load language driver for " + cls.getName(), ex);
      }
    });
  }

  public void register(LanguageDriver instance) {
    if (instance == null) {
      throw new IllegalArgumentException("null is not a valid Language Driver");
    }
    Class<? extends LanguageDriver> cls = instance.getClass();
    if (!languageDriverMap.containsKey(cls)) {
      languageDriverMap.put(cls, instance);
    }
  }

  public LanguageDriver getDriver(Class<? extends LanguageDriver> cls) {
    return languageDriverMap.get(cls);
  }

  public LanguageDriver getDefaultDriver() {
    return getDriver(getDefaultDriverClass());
  }

  public void setDefaultDriverClass(Class<? extends LanguageDriver> defaultDriverClass) {
    register(defaultDriverClass);
    this.defaultDriverClass = defaultDriverClass;
  }
}
```

`register(Class)` 用 `computeIfAbsent` 反射调无参构造，自定义语言驱动必须能无参实例化；`register(instance)` 只在 key 不存在时放入，先注册的实例不会被后注册的同名实例覆盖。`getDriver` 查不到就返回 `null`，回退默认是 `getDefaultDriver()` 的事。`setDefaultDriverClass` 先 `register` 再赋值，默认驱动因此一定在表里，`Configuration.setDefaultScriptingLanguage`（`:665`）与 XML 的 `lang` 属性都走这个入口。

## XMLLanguageDriver

`XMLLanguageDriver.java:43-75` 两组重载形状不同，还留了一处不对称：

```java
@Override
public SqlSource createSqlSource(Configuration configuration, XNode script, Class<?> parameterType) {
  return createSqlSource(configuration, script, parameterType, null);
}

@Override
public SqlSource createSqlSource(Configuration configuration, XNode script, Class<?> parameterType,
    ParamNameResolver paramNameResolver) {
  XMLScriptBuilder builder = new XMLScriptBuilder(configuration, script, parameterType, paramNameResolver);
  return builder.parseScriptNode();
}

@Override
public SqlSource createSqlSource(Configuration configuration, String script, Class<?> parameterType) {
  return createSqlSource(configuration, script, parameterType, null);
}

@Override
public SqlSource createSqlSource(Configuration configuration, String script, Class<?> parameterType,
    ParamNameResolver paramNameResolver) {
  // issue #3
  if (script.startsWith("<script>")) {
    XPathParser parser = new XPathParser(script, false, configuration.getVariables(), new XMLMapperEntityResolver());
    return createSqlSource(configuration, parser.evalNode("/script"), parameterType);
  }
  // issue #127
  script = PropertyParser.parse(script, configuration.getVariables());
  TextSqlNode textSqlNode = new TextSqlNode(script);
  if (textSqlNode.isDynamic()) {
    return new DynamicSqlSource(configuration, textSqlNode);
  } else {
    return new RawSqlSource(configuration, script, parameterType, paramNameResolver);
  }
}
```

XNode 路径把 `paramNameResolver` 交给 `XMLScriptBuilder`，由它决定 `DynamicSqlSource` / `RawSqlSource`；String 路径先处理 `${}` 与 `<script>`，含 `${}` 走动态，否则走 `RawSqlSource`。`<script>` 分支调的是三参数 `createSqlSource(..., parameterType)`，四参数重载持有的 resolver 在「注解 + `<script>`」组合里会丢掉，代价是 `#{}` 的泛型类型推断退化，SQL 本身照常执行。`createParameterHandler`（`:38-41`）固定返回 `new DefaultParameterHandler(mappedStatement, parameterObject, boundSql)`。

`RawLanguageDriver`（`:33-52`）继承 `XMLLanguageDriver`，两个 `createSqlSource` 都在父类产出后调 `checkIsNotDynamic(source)`，拿到 `DynamicSqlSource` 就抛错。标了 `@Lang(RawLanguageDriver.class)` 的语句因此不能含 `${}` 或任何动态标签。

## SqlSource Family

四种实现什么时候定型，看代码最省事。`DynamicSqlSource.java:43-52` 每次调用都重跑树：

```java
@Override
public BoundSql getBoundSql(Object parameterObject) {
  DynamicContext context = new DynamicContext(configuration, parameterObject, null, paramNameResolver, true);
  rootSqlNode.apply(context);
  String sql = context.getSql();
  SqlSource sqlSource = SqlSourceBuilder.buildSqlSource(configuration, sql, context.getParameterMappings());
  BoundSql boundSql = sqlSource.getBoundSql(parameterObject);
  context.getBindings().forEach(boundSql::setAdditionalParameter);
  return boundSql;
}
```

第 `50` 行容易被跳过：整份 bindings（含 `<bind>` 变量、`<foreach>` 的 `item` / `index`）灌进 `BoundSql.additionalParameters`。`ParameterMappingTokenHandler` 里 `metaParameters.hasGetter(...)` 和 `DefaultParameterHandler` 里 `boundSql.hasAdditionalParameter(propertyName)` 就是靠这份数据取到值的，少了它，`<foreach>` 里的 `#{item.xxx}` 连类型都推不出来。

`RawSqlSource.java:49-74` 在构造里就把树跑完、把 `#{}` 换成 `?`：

```java
public RawSqlSource(Configuration configuration, SqlNode rootSqlNode, Class<?> parameterType,
    ParamNameResolver paramNameResolver) {
  DynamicContext context = new DynamicContext(configuration, parameterType, paramNameResolver);
  rootSqlNode.apply(context);
  String sql = context.getSql();
  sqlSource = SqlSourceBuilder.buildSqlSource(configuration, sql, context.getParameterMappings());
}

public RawSqlSource(Configuration configuration, String sql, Class<?> parameterType,
    ParamNameResolver paramNameResolver) {
  Class<?> clazz = parameterType == null ? Object.class : parameterType;
  List<ParameterMapping> parameterMappings = new ArrayList<>();
  ParameterMappingTokenHandler tokenHandler = new ParameterMappingTokenHandler(parameterMappings, configuration,
      clazz, new HashMap<>(), paramNameResolver);
  GenericTokenParser parser = new GenericTokenParser("#{", "}", tokenHandler);
  sqlSource = SqlSourceBuilder.buildSqlSource(configuration, parser.parse(sql), parameterMappings);
}

@Override
public BoundSql getBoundSql(Object parameterObject) {
  return sqlSource.getBoundSql(parameterObject);
}
```

`StaticSqlSource.java:44-47` 已经定型，`new BoundSql(...)` 直接返回，不解析任何 token：

```java
@Override
public BoundSql getBoundSql(Object parameterObject) {
  return new BoundSql(configuration, sql, parameterMappings, parameterObject);
}
```

`ProviderSqlSource` 也是每次调用重算，先调 provider 方法拿字符串再交给语言驱动，代码贴在 [Annotation Mapper](/docs/CS/Framework/MyBatis/Annotation_Mapper.md)。

`SqlSourceBuilder.java:27-42` 在 3.6.0 里只剩静态方法，空白折叠发生在 SQL 定型这一步：

```java
public class SqlSourceBuilder {

  private SqlSourceBuilder() {
    super();
  }

  public static SqlSource buildSqlSource(Configuration configuration, String sql,
      List<ParameterMapping> parameterMappings) {
    return new StaticSqlSource(configuration,
        configuration.isShrinkWhitespacesInSql() ? SqlSourceBuilder.removeExtraWhitespaces(sql) : sql,
        parameterMappings);
  }

  public static String removeExtraWhitespaces(final String original) {
    return original.replaceAll("\\s+", " ").trim();
  }
}
```

`replaceAll("\\s+", " ")` 会影响日志里看到的 SQL，也会影响字符串字面量里的连续空白，它不是渲染层的美化。本机没有 3.5.x 源码树可比，因此这里只写 3.6.0 的形态。

## From `#{}` to `?`

一次占位符解析要过四个类，关键两跳贴在下面。`ParameterMappingTokenHandler.java:77-95` 的 `handleToken` 恒返回 `"?"`：

```java
@Override
public String handleToken(String content) {
  genericType = null;
  typeHandler = null;
  parameterMappings.add(buildParameterMapping(content));
  return "?";
}

private ParameterMapping buildParameterMapping(String content) {
  Map<String, String> propertiesMap = parseParameterMapping(content);

  final String property = propertiesMap.remove("property");
  final JdbcType jdbcType = resolveJdbcType(propertiesMap.remove("jdbcType"));
  final String typeHandlerAlias = propertiesMap.remove("typeHandler");

  ParameterMapping.Builder builder = new ParameterMapping.Builder(configuration, property, (Class<?>) null);
  PropertyTokenizer propertyTokenizer = new PropertyTokenizer(property);
  builder.jdbcType(jdbcType);
  final Class<?> javaType = figureOutJavaType(propertiesMap, property, propertyTokenizer, jdbcType);
```

占位符的个数就是 `parameterMappings` 的长度，与 `#{}` 里写了多少属性无关。`parseParameterMapping` 交给 `ParameterExpression`，它自带的语法说明是 `inline-parameter = (propertyName | expression) oldJdbcType attributes`：`(expr)` 形式走 `expression()`，普通属性走 `property()`，`,` 后是 `jdbcType=...` 等选项，`:` 后是旧式 jdbcType。

`ParameterMappingTokenHandler.java:140-180` 是 javaType 的优先级：

```java
private Class<?> figureOutJavaType(Map<String, String> propertiesMap, String property,
    PropertyTokenizer propertyTokenizer, JdbcType jdbcType) {
  Class<?> javaType = resolveClass(propertiesMap.remove("javaType"));
  if (javaType != null) {
    return javaType;
  }
  if (metaParameters.hasGetter(propertyTokenizer.getName())) { // issue #448 get type from additional params
    return metaParameters.getGetterType(property);
  }
  typeHandler = resolveTypeHandler(parameterType, jdbcType, (Class<? extends TypeHandler<?>>) null);
  if (typeHandler != null) {
    return parameterType;
  }
  if (JdbcType.CURSOR.equals(jdbcType)) {
    return ResultSet.class;
  }
  if (paramNameResolver != null && ParamMap.class.equals(parameterType)) {
    Type actualParamType = paramNameResolver.getType(property);
    if (actualParamType instanceof Type) {
      MetaClass metaClass = MetaClass.forClass(actualParamType, configuration.getReflectorFactory());
      String multiParamsPropertyName;
      if (propertyTokenizer.hasNext()) {
        multiParamsPropertyName = propertyTokenizer.getChildren();
        if (metaClass.hasGetter(multiParamsPropertyName)) {
          Entry<Type, Class<?>> getterType = metaClass.getGenericGetterType(multiParamsPropertyName);
          genericType = getterType.getKey();
          return getterType.getValue();
        }
      } else {
        genericType = actualParamType;
      }
    }
    return Object.class;
  }
  if (Map.class.isAssignableFrom(parameterType)) {
    return Object.class;
  }
  MetaClass metaClass = MetaClass.forClass(parameterType, configuration.getReflectorFactory());
  // ... 泛型 getter 类型分支
```

显式 `javaType` → `metaParameters` 的 getter 类型 → 参数类自身有没有注册的 `TypeHandler` → `JdbcType.CURSOR` 特判成 `ResultSet.class` → `ParamNameResolver` 分支（仅当 `parameterType == ParamMap.class`）→ `Map` 兜底成 `Object.class` → `MetaClass` 的泛型 getter 类型。`ParamNameResolver` 全程只补类型信息，不生成 SQL 文本；运行期 `DefaultParameterHandler` 还会再取它一次做同一件事。

触发这一跳的 parser 在 [Dynamic SQL](/docs/CS/Framework/MyBatis/Dynamic_SQL.md) 贴过：`DynamicContext` 用 `new GenericTokenParser("#{", "}", tokenHandler)`，`parseParam(sql)` 调 `tokenParser.parse(sql)`。

## BoundSql

`mapping/BoundSql.java:35-75` 只有五个字段，`additionalParameters` 与 `metaParameters` 是同一份数据的两种视图：

```java
public class BoundSql {

  private final String sql;
  private final List<ParameterMapping> parameterMappings;
  private final Object parameterObject;
  private final Map<String, Object> additionalParameters;
  private final MetaObject metaParameters;

  public BoundSql(Configuration configuration, String sql, List<ParameterMapping> parameterMappings,
      Object parameterObject) {
    this.sql = sql;
    this.parameterMappings = parameterMappings;
    this.parameterObject = parameterObject;
    this.additionalParameters = new HashMap<>();
    this.metaParameters = configuration.newMetaObject(additionalParameters);
  }

  public String getSql() {
    return sql;
  }

  public boolean hasAdditionalParameter(String name) {
    String paramName = new PropertyTokenizer(name).getName();
    return additionalParameters.containsKey(paramName);
  }

  public void setAdditionalParameter(String name, Object value) {
    metaParameters.setValue(name, value);
  }

  public Object getAdditionalParameter(String name) {
    return metaParameters.getValue(name);
  }
  // ...
}
```

没有缓存、没有可变 SQL，`getSql()` 返回的就是已经带 `?` 的字符串。

## DefaultParameterHandler

`scripting/defaults/DefaultParameterHandler.java:91-119` 按 `parameterMappings` 逐个绑定，取值优先级写得清楚：

```java
public void setParameters(PreparedStatement ps) {
  ErrorContext.instance().activity("setting parameters").object(mappedStatement.getParameterMap().getId());
  List<ParameterMapping> parameterMappings = boundSql.getParameterMappings();
  if (parameterMappings != null) {
    ParamNameResolver paramNameResolver = mappedStatement.getParamNameResolver();
    for (int i = 0; i < parameterMappings.size(); i++) {
      ParameterMapping parameterMapping = parameterMappings.get(i);
      if (parameterMapping.getMode() != ParameterMode.OUT) {
        Object value;
        String propertyName = parameterMapping.getProperty();
        JdbcType jdbcType = parameterMapping.getJdbcType();
        JdbcType actualJdbcType = jdbcType == null ? getParamJdbcType(ps, i + 1) : jdbcType;
        Type propertyGenericType = null;
        TypeHandler typeHandler = parameterMapping.getTypeHandler();
        if (parameterMapping.hasValue()) {
          value = parameterMapping.getValue();
        } else if (boundSql.hasAdditionalParameter(propertyName)) { // issue #448 ask first for additional params
          value = boundSql.getAdditionalParameter(propertyName);
        } else if (parameterObject == null) {
          value = null;
        } else {
          Class<? extends Object> parameterClass = parameterObject.getClass();
          TypeHandler paramTypeHandler = typeHandlerRegistry.getTypeHandler(parameterClass, actualJdbcType);
          if (paramTypeHandler != null) {
            value = parameterObject;
            typeHandler = paramTypeHandler;
          } else {
            paramMetaObject = getParamMetaObject();
            value = paramMetaObject.getValue(propertyName);
            // ... 按 ParamNameResolver / MetaClass 补泛型类型
```

构建期塞进来的字面值 → `<bind>` / `<foreach>` 留下的变量 → `null` 参数 → 参数类本身有注册的 `TypeHandler` 时整个对象当值并换用该 handler → 否则 `paramMetaObject.getValue(propertyName)`，再按 `ParamNameResolver` / `MetaClass` 补泛型类型（`:120-151`）。`ParameterMode.OUT` 的映射在 `:98` 被跳过，那是存储过程参数，不走这条输入路径。

`DefaultParameterHandler.java:153-174` 是收尾：

```java
if (value == null) {
  if (jdbcType == null) {
    jdbcType = configuration.getJdbcTypeForNull();
  }
  if (typeHandler == null) {
    typeHandler = ObjectTypeHandler.INSTANCE;
  }
} else if (typeHandler == null) {
  if (propertyGenericType == null) {
    propertyGenericType = value.getClass();
  }
  typeHandler = typeHandlerRegistry.getTypeHandler(propertyGenericType, actualJdbcType, null);
}
if (typeHandler == null) {
  typeHandler = typeHandlerRegistry.getTypeHandler(actualJdbcType);
}
if (typeHandler == null) {
  throw new TypeException("Could not find type handler for Java type '" + propertyGenericType.getTypeName()
      + "' nor JDBC type '" + actualJdbcType + "'");
}
try {
  typeHandler.setParameter(ps, i + 1, value, jdbcType);
  // ...
}
```

`value == null` 时 `jdbcType` 取 `configuration.getJdbcTypeForNull()`，`typeHandler` 兜底 `ObjectTypeHandler.INSTANCE`；全部分支都找不到 handler 时抛 `TypeException`。

`${}` 的替换归 [Dynamic SQL](/docs/CS/Framework/MyBatis/Dynamic_SQL.md)；两者的差别就一句话：`#{}` 在这里变成 `?` 并由 `TypeHandler` 赋值，`${}` 在 SQL 定型前被换成字符串，没有 `ParameterMapping`，也没有类型处理。

## Unverified

- `<script>` 分支丢失 `paramNameResolver`（`XMLLanguageDriver.java:66`）的实际影响只按代码路径推断，没有跑用例验证哪些 `#{}` 写法会退化。
- `ParameterExpression` 的 `numericScale` / `resultMap` / `expression` 等选项未逐个核对解析结果，只核到语法注释与 `buildParameterMapping` 的分支位置。
- `DefaultParameterHandler` 的 `metaClassCache`（`:125`）命中策略与并发行为未展开。
- `RawLanguageDriver.checkIsNotDynamic` 的报错文本与触发条件只核到方法位置 `:50`，未逐个用例验证。

## Links

- [Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)
- [StatementHandler](/docs/CS/Framework/MyBatis/StatementHandler.md)
- [Reflector](/docs/CS/Framework/MyBatis/Reflector.md)

## References

- [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
- [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
