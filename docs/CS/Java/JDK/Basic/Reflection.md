

## Introduction

Instances of the class Class represent classes and interfaces in a running Java application. An enum is a kind of class and an annotation is a kind of interface. Every array also belongs to a class that is reflected as a Class object that is shared by all arrays with the same element type and number of dimensions. The primitive Java types (boolean, byte, char, short, int, long, float, and double), and the keyword void are also represented as Class objects.
Class has no public constructor. Instead Class objects are constructed automatically by the Java Virtual Machine as classes are loaded and by calls to the defineClass method in the class loader.

- Class
- Constructor
- Field
- Method



Get Class Object

1. ClassName.class
2. Class.forName()
3. Instance.getClass()
4. ClassLoader.loadClass()



1. `getName()` Returns the name of the entity (class, interface, array class, primitive type, or void) represented by this Class object, as a String.
2. `getSimpleName()` Returns the simple name of the underlying class as given in the source code. Returns an empty string if the underlying class is anonymous.
3. `getCanonicalName()` Returns the canonical name of the underlying class as defined by the Java Language Specification. Returns null if the underlying class does not have a canonical name (i.e., if it is a local or anonymous class or an array whose component type does not have a canonical name).


| Class           | getName             | getSimpleName | getCanonicalName    |
| --------------- | ------------------- | ------------- | ------------------- |
| int.class       | int                 | int           | int                 |
| int[].class     | [I                  | int[]         | int[]               |
| int[][].class   | [[I                 | int[][]       | int[][]             |
| String.class    | java.lang.String    | String        | java.lang.String    |
| String[].class  | [Ljava.lang.String; | String[]      | java.lang.String[]  |
| ArrayList.class | java.util.ArrayList | ArrayList     | java.util.ArrayList |



Todo benchmark



### Method

java.lang.Class.getMethods don't keep the order of methods

because they are sorted by memory not name for improve performance


MethodAccessor

MethodAccessor 是一个接口，它有两个已有的具体实现：一
个通过本地方法NativeMethodAccessorImpl来实现反射调用，另一个则使用了委派模式DelegatingMethodAccessorImpl
每个 Method 实例的第一次反射调用都会生成一个委派实现，它所委派的具体实现便是一
个本地实现。
本地实现非常容易理解。当进入了 Java 虚拟机内部之后，我们便拥有了
Method 实例所指向方法的具体地址。这时候，反射调用无非就是将传入的参数准备好，
然后调用进入目标方法
 

-Dsun.reflect.inflationThreshold=15


当某个反射调用的调用次数在 15 之下时，
采用本地实现；当达到 15 时，便开始动态生成字节码，并将委派实现的委派对象切换至动
态实现，这个过程我们称之为 Inflation。

反射调用的 Inflation 机制是可以通过参数（-Dsun.reflect.noInflation=true）来关闭的


```java
// java -verbose:class Test
public class Test {
  public static void target(int i) {
    new Exception("#" + i).printStackTrace();
  }
  public static void main(String[] args) throws Exception {
    Class<?> klass = Class.forName("Test");
    Method method = klass.getMethod("target", int.class);
    for (int i = 0; i < 20; i++) {
      method.invoke(null, i);
    }
  }
}
```


## Proxy

A dynamic proxy class is a class that implements a list of interfaces specified at runtime such that a method invocation through one of 
the interfaces on an instance of the class will be encoded and dispatched to another object through a uniform interface. 
Thus, a dynamic proxy class can be used to create a type-safe proxy object for a list of interfaces without requiring pre-generation of the proxy class, such as with compile-time tools.
Method invocations on an instance of a dynamic proxy class are dispatched to a single method in the instance's invocation handler,
and they are encoded with a java.lang.reflect.Method object identifying the method that was invoked and an array of type Object containing the arguments.


Processes a method invocation on a proxy instance and returns the result. This method will be invoked on an invocation handler when a method is invoked on a proxy instance that it is associated with.
```java
public interface InvocationHandler { 
    Object invoke(Object proxy, Method method, Object[] args) throws Throwable;
}
```

MethodInterceptor Enhancer



### newProxyInstance

Returns a proxy instance for the specified interfaces that dispatches method invocations to the specified invocation handler.


Note that the order of the specified proxy interfaces is significant: 
two requests for a proxy class with the same combination of interfaces but in a different order will result in two distinct proxy classes.

```java
class Proxy {
  @CallerSensitive
  public static Object newProxyInstance(ClassLoader loader, Class<?>[] interfaces, InvocationHandler h) {
    Objects.requireNonNull(h);

    final Class<?> caller = System.getSecurityManager() == null ? null : Reflection.getCallerClass();

    /** Look up or generate the designated proxy class and its constructor. */
    Constructor<?> cons = getProxyConstructor(caller, loader, interfaces);

    return newProxyInstance(caller, cons, h);
  }

  private static Object newProxyInstance(Class<?> caller, // null if no SecurityManager
                                         Constructor<?> cons,
                                         InvocationHandler h) {
    /** Invoke its constructor with the designated invocation handler. */
    try {
      if (caller != null) {
        checkNewProxyPermission(caller, cons.getDeclaringClass());
      }

      return cons.newInstance(new Object[]{h});
    } catch (IllegalAccessException | InstantiationException e) {
      throw new InternalError(e.toString(), e);
    } catch (InvocationTargetException e) {
            ...
    }
  }
}
```


Uses the constructor represented by this Constructor object to create and initialize a new instance of the constructor's declaring class, with the specified initialization parameters. Individual parameters are automatically unwrapped to match primitive formal parameters, and both primitive and reference parameters are subject to method invocation conversions as necessary.

If the number of formal parameters required by the underlying constructor is 0, the supplied initargs array may be of length 0 or null.

If the constructor's declaring class is an inner class in a non-static context, the first argument to the constructor needs to be the enclosing instance; see section 15.9.3 of The Java Language Specification.

If the required access and argument checks succeed and the instantiation will proceed, the constructor's declaring class is initialized if it has not already been initialized.

If the constructor completes normally, returns the newly created and initialized instance.


```java
@CallerSensitive
@ForceInline // to ensure Reflection.getCallerClass optimization
public T newInstance(Object ... initargs)
    throws InstantiationException, IllegalAccessException,
           IllegalArgumentException, InvocationTargetException
{
    Class<?> caller = override ? null : Reflection.getCallerClass();
    return newInstanceWithCaller(initargs, !override, caller);
}
```




```java

 /* package-private */
T newInstanceWithCaller(Object[] args, boolean checkAccess, Class<?> caller)
  throws InstantiationException, IllegalAccessException,
InvocationTargetException
{
  if (checkAccess)
    checkAccess(caller, clazz, clazz, modifiers);

  if ((clazz.getModifiers() & Modifier.ENUM) != 0)
    throw new IllegalArgumentException("Cannot reflectively create enum objects");

  ConstructorAccessor ca = constructorAccessor;   // read volatile
  if (ca == null) {
    ca = acquireConstructorAccessor();
  }
  @SuppressWarnings("unchecked")
  T inst = (T) ca.newInstance(args);
  return inst;
}
```

Uses Unsafe.allocateObject() to instantiate classes; only used for bootstrapping.

```java
class BootstrapConstructorAccessorImpl extends ConstructorAccessorImpl {
    private final Constructor<?> constructor;

    BootstrapConstructorAccessorImpl(Constructor<?> c) {
        this.constructor = c;
    }

    public Object newInstance(Object[] args)
        throws IllegalArgumentException, InvocationTargetException
    {
        try {
            return UnsafeFieldAccessorImpl.unsafe.
                allocateInstance(constructor.getDeclaringClass());
        } catch (InstantiationException e) {
            throw new InvocationTargetException(e);
        }
    }
}
```

Threshold
```
# default 15
-Dsun.reflect.inflationThreshold=

-Dsun.reflect.noInflation=true
```

NativeMethodAccessorImpl
DelegatingMethodAccessorImpl

```shell
java -verbose:class Main.class
```
gather than threshold, only use DelegatingMethodAccessor, GeneratedMethodAccessor1, 



### saveProxyFiles

set property
> System.getProperties().put("sun.misc.ProxyGenerator.saveGeneratedFiles", "true");

saveFies
```java
public class ProxyGenerator {
  /** debugging flag for saving generated class files */
  private final static boolean saveGeneratedFiles =
          java.security.AccessController.doPrivileged(
                  new GetBooleanAction(
                          "sun.misc.ProxyGenerator.saveGeneratedFiles")).booleanValue();



  /**
   * Generate a proxy class given a name and a list of proxy interfaces.
   */
  public static byte[] generateProxyClass(final String name,
                                          Class<?>[] interfaces,
                                          int accessFlags)
  {
    ProxyGenerator gen = new ProxyGenerator(name, interfaces, accessFlags);
    final byte[] classFile = gen.generateClassFile();

    if (saveGeneratedFiles) {
      java.security.AccessController.doPrivileged(
              new java.security.PrivilegedAction<Void>() {
                public Void run() {
                  try {
                    int i = name.lastIndexOf('.');
                    Path path;
                    if (i > 0) {
                      Path dir = Paths.get(name.substring(0, i).replace('.', File.separatorChar));
                      Files.createDirectories(dir);
                      path = dir.resolve(name.substring(i+1, name.length()) + ".class");
                    } else {
                      path = Paths.get(name + ".class");
                    }
                    Files.write(path, classFile);
                    return null;
                  } catch (IOException e) {
                    throw new InternalError(
                            "I/O exception saving generated file: " + e);
                  }
                }
              });
    }

    return classFile;
  }
}
```


## Tuning

方法的反射调用会带来不少性能开销，原因主要有三个：变长参数方法导致的 Object 数组，基本类型的自动装箱、拆箱，还有最重要的方法内联



## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References

1. [JVM源码分析之不保证顺序的Class.getMethods](http://lovestblog.cn/blog/2016/11/02/class-getmethods/)