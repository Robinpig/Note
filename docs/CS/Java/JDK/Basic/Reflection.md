## Introduction

Instances of the class `Class` represent classes and interfaces in a running Java application. An enum is a kind of class and an annotation is a kind of interface. Every array also belongs to a Class object shared by all arrays with the same element type and number of dimensions. The primitive Java types and the keyword `void` are also represented as `Class` objects. `Class` has no public constructor — Class objects are constructed automatically by the JVM as classes are loaded.

**四种获取 Class 对象的方式：**

1. `ClassName.class`（编译期已知）
2. `Class.forName("...")`（运行时按名加载，触发初始化）
3. `instance.getClass()`
4. `ClassLoader.loadClass("...")`（仅加载，不初始化）

| 表达式 | getName | getSimpleName | getCanonicalName |
| -------- | -------- | -------- | -------- |
| `int.class` | int | int | int |
| `int[].class` | [I | int[] | int[] |
| `String.class` | java.lang.String | String | java.lang.String |
| `ArrayList.class` | java.util.ArrayList | ArrayList | java.util.ArrayList |

> 注意：`Class.getMethods()` **不保证方法顺序**——它们按内存布局而非字母序排序以提升性能，不要依赖返回顺序。

## Reflection API

### Class

`Class` 是反射的入口，除获取名称（见上表）外，还提供 `getFields`/`getDeclaredFields`、`getMethods`/`getDeclaredMethods`、`getConstructors`/`getDeclaredConstructors`、`getAnnotations` 等。带 `Declared` 的方法只列出当前类显式声明的成员，不含继承；不带 `Declared` 的包含公开继承成员。

### Field and Constructor

`Field` / `Constructor` 通过 `get`/`set`、`newInstance` 读写成员或创建实例。访问非 public 成员前需 `setAccessible(true)` 关闭访问检查（见下节）。

> ⚠️ 反射**禁止创建 enum 实例**：`Constructor.newInstance` 内部检查 `Modifier.ENUM` 并抛 `IllegalArgumentException("Cannot reflectively create enum objects")`——这是 enum 单例安全性的最后一道防线（`Unsafe.allocateInstance` 可绕过，见 [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md?id=allocateinstance)）。

`Constructor.newInstance` 在引导期借 `Unsafe.allocateInstance` 实现（仅 `BootstrapConstructorAccessorImpl`）：

```java
class BootstrapConstructorAccessorImpl extends ConstructorAccessorImpl {
    public Object newInstance(Object[] args) throws ... {
        try {
            return UnsafeFieldAccessorImpl.unsafe.allocateInstance(constructor.getDeclaringClass());
        } catch (InstantiationException e) { throw new InvocationTargetException(e); }
    }
}
```

### Method

`Method.invoke` 的底层由 `MethodAccessor` 实现。每个 `Method` 的首次反射调用会生成一个委派实现（`DelegatingMethodAccessorImpl`），其委派对象最初是一个本地实现（`NativeMethodAccessorImpl`）；当调用次数达到 **15 次阈值**时，JVM 动态生成字节码（`GeneratedMethodAccessorN`）并切换委派目标，这一过程称为 **Inflation**：

```java
// -Dsun.reflect.inflationThreshold=15   // 默认 15
// -Dsun.reflect.noInflation=true        // 关闭 Inflation，始终用本地实现
```

```java
public class Test {
  public static void target(int i) { new Exception("#" + i).printStackTrace(); }
  public static void main(String[] args) throws Exception {
    Method method = Class.forName("Test").getMethod("target", int.class);
    for (int i = 0; i < 20; i++) method.invoke(null, i);  // 第 15 次起转动态实现
  }
}
```

本地实现慢（需跨 JNI 边界、参数打包成 Object 数组），动态生成字节码后可直接调用目标方法、避免装箱与数组分配，性能接近直接调用。

## setAccessible and Strong Encapsulation

`setAccessible(true)` 用于绕过 private/protected 访问检查，是 ORM、序列化、测试框架的基石。但 **JPMS 强封装（JEP 403，JDK 17 硬默认）改变了它的边界**：

- 若目标类所在的**包未被模块 `opens` 给调用方模块**，即使 `setAccessible(true)` 也会抛 `InaccessibleObjectException`。
- 平台模块（如 `java.base`）的多数内部包默认不开放，需启动参数 `--add-opens <module>/<pkg>=<caller>` 才能反射（见 [module](/docs/CS/Java/JDK/Basic/module.md)）。

> 这与 Security Manager 无关：Security Manager 已在 JDK 24（JEP 486）被移除，强封装由模块系统本身强制。

## MethodHandle vs Reflection

`java.lang.invoke.MethodHandle`（JSR 292，JDK 7 引入、JDK 8 完善）是更现代、更底层的"可调用引用"抽象：

- **签名严格**：`invokeExact` 要求调用时的静态类型与方法句柄类型完全匹配，否则抛 `WrongMethodTypeException`；`invoke` 允许松散适配。
- **性能更好**：无变长 Object 数组、无强制装箱，JIT 可直接内联目标，避免了反射 `Method.invoke` 的三类开销（见 [Tuning](#tuning)）。
- **与 Lambda 同源**：Lambda 表达式经 `invokedynamic` 引导方法生成调用点，内部正是用 `MethodHandle` + ASM 动态生成匿名类（见 [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md?id=class--lambda-generation)）。

反射适合"按名发现 API"（如框架扫描字段/方法），`MethodHandle` 适合"已知签名的高频调用"。两者都能被 JIT 优化，但 MethodHandle 的路径更短。

## Proxy

A dynamic proxy class implements a list of interfaces specified at runtime; a method invocation through one of the interfaces is encoded and dispatched to an `InvocationHandler`. `Proxy` 无需预生成代理类即可为一组接口创建类型安全的代理对象。

```java
public interface InvocationHandler {
    Object invoke(Object proxy, Method method, Object[] args) throws Throwable;
}
```

`Proxy.newProxyInstance` 查找或生成代理类，再经其构造器实例化：

```java
public static Object newProxyInstance(ClassLoader loader, Class<?>[] interfaces, InvocationHandler h) {
    Objects.requireNonNull(h);
    final Class<?> caller = System.getSecurityManager() == null ? null : Reflection.getCallerClass();
    Constructor<?> cons = getProxyConstructor(caller, loader, interfaces);  // 查找/生成代理类
    return newProxyInstance(caller, cons, h);
}
```

生成的类可经 `System.getProperties().put("sun.misc.ProxyGenerator.saveGeneratedFiles", "true")` 落盘查看（`ProxyGenerator.generateProxyClass`）。

### Limitations

- **只能代理接口**，不能代理类——生成的代理类继承自 `Proxy` 并实现指定接口，Java 单继承决定了无法同时继承目标类。
- 代理类自身位于 `com.sun.proxy` 包（历史为 `sun.misc` 包），在 JPMS 下受模块边界约束，且生成过程同样受 `setAccessible` 的强封装限制。
- 每次 `newProxyInstance` 都生成（或缓存）一个新类，接口顺序不同会得到**不同的代理类**。

## AnnotatedElement and Generic Reflection

`AnnotatedElement`（`Class`/`Method`/`Field` 均实现）提供 `getAnnotations`/`getDeclaredAnnotations`/`getAnnotation`，是注解处理（如 Spring 的 `@Autowired`、JUnit 的 `@Test`）的基础。

泛型类型在运行时被擦除，但通过反射仍可获取**声明处**的泛型信息：

- `Type[] getTypeParameters()`：类的类型变量（如 `class Box<T>` 的 `T`）。
- `Type getGenericReturnType()` / `getGenericParameterTypes()`：方法签名中的泛型类型。
- `ParameterizedType.getActualTypeArguments()`：如从 `List<String>` 提取 `String`。

这些信息来自 class 文件中的 `Signature` 属性，而非运行时对象，因此只能还原"源码声明"层面的泛型，无法还原具体实例的实参类型。

## Tuning

方法的反射调用会带来开销，主要来自三点：

1. **变长参数方法导致的 Object 数组分配**：`invoke` 把基本类型装箱、参数打包成 `Object[]`。
2. **基本类型的自动装箱/拆箱**：`int` → `Integer` 等。
3. **方法内联受阻**：反射调用经 `MethodAccessor` 间接跳转，JIT 难以内联目标方法（动态生成字节码后有所缓解）。

在高性能场景，应优先用 `MethodHandle` 或直接代码路径替代反射。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [module](/docs/CS/Java/JDK/Basic/module.md)

## References

1. [JVM源码分析之不保证顺序的Class.getMethods](http://lovestblog.cn/blog/2016/11/02/class-getmethods/)
2. [JEP 403: Strongly Encapsulate JDK Internals](https://openjdk.org/jeps/403)
3. [JSR 292: Supporting Dynamically Typed Languages on the JVM](https://jcp.org/en/jsr/detail?id=292)
