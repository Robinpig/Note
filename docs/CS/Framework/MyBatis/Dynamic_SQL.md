## Introduction

动态 SQL 的边界在 `LanguageDriver.createSqlSource` 这一行：往前是 DOM 解析（启动期，[Config Pipeline](/docs/CS/Framework/MyBatis/Config_Pipeline.md)），往后是每次调用重新拼 SQL（运行期，[SqlSource and Parameters](/docs/CS/Framework/MyBatis/SqlSource_and_Parameters.md)）。`XMLScriptBuilder` 做的是前者，把 `<if>` / `<foreach>` / `<where>` 变成一棵 `SqlNode` 树，树在启动时建好就不再变；`DynamicContext` 做的是后者，每次 `getBoundSql` 用新的入参跑一遍这棵树。分不清这两次解析，就容易把 `#{}` 当成运行期才解析的东西。本页代码块取自本机 `mybatis-3.6.0` 源码树，路径相对 `src/main/java/org/apache/ibatis/`，省略处标 `// ...`。

## Node Handler Map

`XMLScriptBuilder.java:63-84` 给出注册表与「动态/静态」的分叉：

```java
private void initNodeHandlerMap() {
  nodeHandlerMap.put("trim", new TrimHandler());
  nodeHandlerMap.put("where", new WhereHandler());
  nodeHandlerMap.put("set", new SetHandler());
  nodeHandlerMap.put("foreach", new ForEachHandler());
  nodeHandlerMap.put("if", new IfHandler());
  nodeHandlerMap.put("choose", new ChooseHandler());
  nodeHandlerMap.put("when", new IfHandler());
  nodeHandlerMap.put("otherwise", new OtherwiseHandler());
  nodeHandlerMap.put("bind", new BindHandler());
}

public SqlSource parseScriptNode() {
  MixedSqlNode rootSqlNode = parseDynamicTags(context);
  SqlSource sqlSource;
  if (isDynamic) {
    sqlSource = new DynamicSqlSource(configuration, rootSqlNode);
  } else {
    sqlSource = new RawSqlSource(configuration, rootSqlNode, parameterType, paramNameResolver);
  }
  return sqlSource;
}
```

九个 key、八个 handler 实例，`when` 与 `if` 共用 `IfHandler`。`XMLScriptBuilder.java:86-115` 是逐子节点的判定：

```java
protected MixedSqlNode parseDynamicTags(XNode node) {
  List<SqlNode> contents = new ArrayList<>();
  NodeList children = node.getNode().getChildNodes();
  for (int i = 0; i < children.getLength(); i++) {
    XNode child = node.newXNode(children.item(i));
    if (child.getNode().getNodeType() == Node.CDATA_SECTION_NODE || child.getNode().getNodeType() == Node.TEXT_NODE) {
      String data = child.getStringBody("");
      if (data.trim().isEmpty()) {
        contents.add(emptyNodeCache.computeIfAbsent(data, EmptySqlNode::new));
        continue;
      }
      TextSqlNode textSqlNode = new TextSqlNode(data);
      if (textSqlNode.isDynamic()) {
        contents.add(textSqlNode);
        isDynamic = true;
      } else {
        contents.add(new StaticTextSqlNode(data));
      }
    } else if (child.getNode().getNodeType() == Node.ELEMENT_NODE) { // issue #628
      String nodeName = child.getNode().getNodeName();
      NodeHandler handler = nodeHandlerMap.get(nodeName);
      if (handler == null) {
        throw new BuilderException("Unknown element <" + nodeName + "> in SQL statement.");
      }
      handler.handleNode(child, contents);
      isDynamic = true;
    }
  }
  return new MixedSqlNode(contents);
}
```

元素节点命中 handler 后无条件置 `isDynamic = true`。只要 SQL 里出现过任何一个动态标签，哪怕 `<where>` 里的条件全是静态文本，也会造 `DynamicSqlSource`；静态内容因此也要走一遍运行期 `apply`，只是树的分支恒定。空文本用 `emptyNodeCache` 缓存一个 `EmptySqlNode`，避免为缩进空白反复造对象。

`ChooseHandler` 不把 `<when>` 交给外层递归，而是自己分派。`XMLScriptBuilder.java:240-252`：

```java
private void handleWhenOtherwiseNodes(XNode chooseSqlNode, List<SqlNode> ifSqlNodes,
    List<SqlNode> defaultSqlNodes) {
  List<XNode> children = chooseSqlNode.getChildren();
  for (XNode child : children) {
    String nodeName = child.getNode().getNodeName();
    NodeHandler handler = nodeHandlerMap.get(nodeName);
    if (handler instanceof IfHandler) {
      handler.handleNode(child, ifSqlNodes);
    } else if (handler instanceof OtherwiseHandler) {
      handler.handleNode(child, defaultSqlNodes);
    } else {
      throw new BuilderException("Unknown element <" + nodeName + "> in SQL statement.");
    }
  }
}
```

`otherwise` 在 `ChooseHandler` 之外单独注册，是为了让它出现在 `<choose>` 内部时也能被 handler 表找到。

## SqlNode Matrix

符号图里 `SqlNode` 的直接实现者有九个，但 `WhereSqlNode` 与 `SetSqlNode` 靠继承间接拿到接口。`WhereSqlNode.java:26-33`：

```java
public class WhereSqlNode extends TrimSqlNode {

  private static final List<String> prefixList = Arrays.asList("AND ", "OR ", "AND\n", "OR\n", "AND\r", "OR\r", "AND\t",
      "OR\t");

  public WhereSqlNode(Configuration configuration, SqlNode contents) {
    super(configuration, contents, "WHERE", prefixList, null, null);
  }
}
```

`SetSqlNode.java:25-31`：

```java
public class SetSqlNode extends TrimSqlNode {

  private static final List<String> COMMA = List.of(",");

  public SetSqlNode(Configuration configuration, SqlNode contents) {
    super(configuration, contents, "SET", COMMA, null, COMMA);
  }
}
```

`TrimSqlNode.java:28` 才是 `public class TrimSqlNode implements SqlNode`。两个子类传的只是预设参数，共用的裁剪逻辑全在 `TrimSqlNode.FilteredDynamicContext`（`:74`）的 `applyPrefix` / `applySuffix`。`<bind>` 走 `BindHandler`（`:121-133`）产出 `VarDeclSqlNode`，`apply` 时把表达式值 `context.bind(name, value)`，后续 `<if test="...">` 与 `#{}` 都能看见。

`implements` 视图里查不到这两个子类，这是 [Call Graph Internals](/docs/CS/Framework/MyBatis/Call_Graph_Internals.md) 里索引盲点的一个具体例子。

## DynamicContext

`DynamicContext.java:38-79` 是 OGNL 表达式能直接写 `_parameter` / `_databaseId` 的原因，也说明 `#{}` 的 token parser 与 `${}` 的分开：

```java
public class DynamicContext {

  public static final String PARAMETER_OBJECT_KEY = "_parameter";
  public static final String DATABASE_ID_KEY = "_databaseId";

  static {
    OgnlRuntime.setPropertyAccessor(ContextMap.class, new ContextAccessor());
  }

  protected final ContextMap bindings;

  public DynamicContext(Configuration configuration, Object parameterObject, Class<?> parameterType,
      ParamNameResolver paramNameResolver, boolean paramExists) {
    if (parameterObject == null || parameterObject instanceof Map) {
      bindings = new ContextMap(null, false);
    } else {
      MetaObject metaObject = configuration.newMetaObject(parameterObject);
      boolean existsTypeHandler = configuration.getTypeHandlerRegistry().hasTypeHandler(parameterObject.getClass());
      bindings = new ContextMap(metaObject, existsTypeHandler);
    }
    bindings.put(PARAMETER_OBJECT_KEY, parameterObject);
    bindings.put(DATABASE_ID_KEY, configuration.getDatabaseId());
    this.configuration = configuration;
    this.parameterObject = parameterObject;
    this.paramExists = paramExists;
    this.parameterType = parameterType;
    this.paramNameResolver = paramNameResolver;
  }
```

静态块把 OGNL 的属性读写转接到 `ContextMap`，这是 MyBatis 自己的适配。`DynamicContext.java:131-157` 的 `ContextMap.get` 决定一个属性从哪儿取值：

```java
static class ContextMap extends HashMap<String, Object> {
  private final MetaObject parameterMetaObject;
  private final boolean fallbackParameterObject;

  @Override
  public Object get(Object key) {
    String strKey = (String) key;
    if (super.containsKey(strKey)) {
      return super.get(strKey);
    }
    if (parameterMetaObject == null) {
      return null;
    }
    if (fallbackParameterObject && !parameterMetaObject.hasGetter(strKey)) {
      return parameterMetaObject.getOriginalObject();
    }
    // issue #61 do not modify the context when reading
    return parameterMetaObject.getValue(strKey);
  }
}
```

先查自身 key，再查 `parameterMetaObject`；简单类型参数没有 getter，就退回原始对象，读操作不许往 context 里写。`DynamicContext.java:97-113` 是 `#{}` 的入口：

```java
private void initTokenParser(List<ParameterMapping> parameterMappings) {
  if (tokenParser == null) {
    tokenHandler = new ParameterMappingTokenHandler(parameterMappings != null ? parameterMappings : new ArrayList<>(),
        configuration, parameterObject, parameterType, bindings, paramNameResolver, paramExists);
    tokenParser = new GenericTokenParser("#{", "}", tokenHandler);
  }
}

public List<ParameterMapping> getParameterMappings() {
  initTokenParser(null);
  return tokenHandler.getParameterMappings();
}

protected String parseParam(String sql) {
  initTokenParser(getParameterMappings());
  return tokenParser.parse(sql);
}
```

`getParameterMappings()` 与 `parseParam()` 共用同一个懒初始化的 parser，参数映射的构建因此和 `${}` 替换不在同一个 token parser 里。

## OGNL Layer

`OgnlCache.java:34-58` 是全局静态缓存，表达式树按字符串缓存，每次取值都注入自定义成员访问与类解析：

```java
public final class OgnlCache {

  private static final OgnlMemberAccess MEMBER_ACCESS = new OgnlMemberAccess();
  private static final OgnlClassResolver CLASS_RESOLVER = new OgnlClassResolver();
  private static final Map<String, Object> expressionCache = new ConcurrentHashMap<>();

  public static Object getValue(String expression, Object root) {
    try {
      OgnlContext context = Ognl.createDefaultContext(root, MEMBER_ACCESS, CLASS_RESOLVER, null);
      return Ognl.getValue(parseExpression(expression), context, root);
    } catch (OgnlException e) {
      throw new BuilderException("Error evaluating expression '" + expression + "'. Cause: " + e, e);
    }
  }

  private static Object parseExpression(String expression) throws OgnlException {
    Object node = expressionCache.get(expression);
    if (node == null) {
      node = Ognl.parseExpression(expression);
      expressionCache.put(expression, node);
    }
    return node;
  }

}
```

`ExpressionEvaluator.java:29-56` 只提供两个能力，`evaluateBoolean` 给 `<if>` / `<when>`，`evaluateIterable` 给 `<foreach>`：

```java
public class ExpressionEvaluator {

  public static final ExpressionEvaluator INSTANCE = new ExpressionEvaluator();

  public boolean evaluateBoolean(String expression, Object parameterObject) {
    Object value = OgnlCache.getValue(expression, parameterObject);
    if (value instanceof Boolean) {
      return (Boolean) value;
    }
    if (value instanceof Number) {
      return new BigDecimal(String.valueOf(value)).compareTo(BigDecimal.ZERO) != 0;
    }
    return value != null;
  }

  @Deprecated
  public Iterable<?> evaluateIterable(String expression, Object parameterObject) {
    return evaluateIterable(expression, parameterObject, false);
  }

  /** @since 3.5.9 */
  public Iterable<?> evaluateIterable(String expression, Object parameterObject, boolean nullable) {
    Object value = OgnlCache.getValue(expression, parameterObject);
    if (value == null) {
      if (nullable) {
        return null;
      }
      throw new BuilderException("The expression '" + expression + "' evaluated to a null value.");
    }
    // ... Iterable 与数组两种形态的转换
  }
}
```

三参数重载多出来的 `nullable` 就是 `<foreach nullable="...">` 的来源。别照搬 pom 里那条测试用的 `--add-opens` 去推断运行期反射行为，具体放宽了哪些限制在 `OgnlMemberAccess` / `OgnlClassResolver` 两个文件里。

## ForEach

`ForEachSqlNode.java:68-115` 的循环体把分隔符、绑定作用域都写在一起：

```java
public boolean apply(DynamicContext context) {
  Map<String, Object> bindings = context.getBindings();
  final Iterable<?> iterable = evaluator.evaluateIterable(collectionExpression, bindings,
      Optional.ofNullable(nullable).orElseGet(configuration::isNullableOnForEach));
  if (iterable == null || !iterable.iterator().hasNext()) {
    return true;
  }
  boolean first = true;
  applyOpen(context);
  int i = 0;
  for (Object o : iterable) {
    DynamicContext scopedContext;
    if (first || separator == null) {
      scopedContext = new PrefixedContext(context, "");
    } else {
      scopedContext = new PrefixedContext(context, separator);
    }
    // Issue #709
    if (o instanceof Map.Entry) {
      Map.Entry<Object, Object> mapEntry = (Map.Entry<Object, Object>) o;
      applyIndex(scopedContext, mapEntry.getKey());
      applyItem(scopedContext, mapEntry.getValue());
    } else {
      applyIndex(scopedContext, i);
      applyItem(scopedContext, o);
    }
    contents.apply(scopedContext);
    if (first) {
      first = !((PrefixedContext) scopedContext).isPrefixApplied();
    }
    i++;
  }
  applyClose(context);
  return true;
}

private void applyIndex(DynamicContext context, Object o) {
  if (index != null) {
    context.bind(index, o);
  }
}

private void applyItem(DynamicContext context, Object o) {
  if (item != null) {
    context.bind(item, o);
  }
}
```

标签上的 `nullable` 优先，没写就取全局 `nullableOnForEach`；空集合直接返回 `true`，不会产出 `open` / `close`。`first` 只在 `isPrefixApplied()` 为真时推进，分隔符因此只出现在真正产出 SQL 的轮次之间。`Map.Entry` 时 `index` 绑 key、`item` 绑 value，否则绑自增计数与元素。绑定发生在 `scopedContext` 上，`PrefixedContext`（`:129`、`:140`）把 `putAll(delegate.getBindings())` 与写操作分离，循环结束不会污染外层 `bindings`。

## Token Order

`TextSqlNode.java:32-69` 把 `${}` 判定与 `${}` → `#{}` 的顺序写得很紧凑：

```java
public boolean isDynamic() {
  DynamicCheckerTokenParser checker = new DynamicCheckerTokenParser();
  GenericTokenParser parser = createParser(checker);
  parser.parse(text);
  return checker.isDynamic();
}

@Override
public boolean apply(DynamicContext context) {
  GenericTokenParser parser = createParser(new BindingTokenParser(context));
  context.appendSql(context.parseParam(parser.parse(text)));
  return true;
}

private GenericTokenParser createParser(TokenHandler handler) {
  return new GenericTokenParser("${", "}", handler);
}

private static class BindingTokenParser implements TokenHandler {
  private final DynamicContext context;

  @Override
  public String handleToken(String content) {
    Object parameter = context.getBindings().get("_parameter");
    if (parameter == null) {
      context.getBindings().put("value", null);
    } else if (SimpleTypeRegistry.isSimpleType(parameter.getClass())) {
      context.getBindings().put("value", parameter);
    }
    Object value = OgnlCache.getValue(content, context.getBindings());
    // issue #274 return "" instead of "null"
    return value == null ? "" : String.valueOf(value);
  }
}
```

`apply` 里 `parser.parse(text)` 先替换 `${}`，结果再交给 `context.parseParam` 处理 `#{}`。这个顺序有两层后果：`${}` 替换进来的文本若含 `#{...}`，同样会被 `ParameterMappingTokenHandler` 登记成 `ParameterMapping` 并换成 `?`；`BindingTokenParser` 对简单类型额外塞一个 `value` 键，值为 null 时返回空串而不是 `"null"`。

`isDynamic()` 与 `apply` 走同一个 `createParser`，只换 handler，判定与执行因此不会用两套不同的 token 规则。

## Unverified

- `OgnlMemberAccess` / `OgnlClassResolver` 的具体权限策略、与 Java 11 模块反射的关系未逐行核对；本页只确认 `OgnlCache.java:36-37` 注入了这两个自定义实现。
- `TrimSqlNode.FilteredDynamicContext` 的 `applyPrefix` / `applySuffix` 大小写与空格处理未逐分支实测，只确认两个子类传入的参数。
- `<choose>` 里 `<when>` / `<otherwise>` 并列多个时的分派结果未做用例验证，只核到 `XMLScriptBuilder.java:240-252` 的分派代码。
- `emptyNodeCache` 的 key 是原始文本而非 trim 后的值（`:94`），缓存命中率与文本形态的关系未量化。

## Links

- [StatementHandler](/docs/CS/Framework/MyBatis/StatementHandler.md)
- [binding](/docs/CS/Framework/MyBatis/binding.md)
- [Execute](/docs/CS/Framework/MyBatis/Execute.md)

## References

- [MyBatis 3 Documentation](https://mybatis.org/mybatis-3/)
- [MyBatis Source (GitHub)](https://github.com/mybatis/mybatis-3)
