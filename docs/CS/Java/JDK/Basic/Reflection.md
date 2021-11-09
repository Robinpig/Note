

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





## Proxy

Proxy InnvocationHandler

MethodInterceptor Enhancer



### newProxyInstance

Returns a proxy instance for the specified interfaces that dispatches method invocations to the specified invocation handler.

IllegalArgumentException will be thrown if any of the following restrictions is violated:
- All of Class objects in the given interfaces array must represent interfaces, not classes or primitive types.
- No two elements in the interfaces array may refer to identical Class objects.
- All of the interface types must be visible by name through the specified class loader. In other words, for class loader cl and every interface i, the following expression must be true:
- Class.forName(i.getName(), false, cl) == i
- All of the types referenced by all public method signatures of the specified interfaces and those inherited by their superinterfaces must be visible by name through the specified class loader.
- All non-public interfaces must be in the same package and module, defined by the specified class loader and the module of the non-public interfaces can access all of the interface types; otherwise, it would not be possible for the proxy class to implement all of the interfaces, regardless of what package it is defined in.
- For any set of member methods of the specified interfaces that have the same signature:
    - If the return type of any of the methods is a primitive type or void, then all of the methods must have that same return type.
    - Otherwise, one of the methods must have a return type that is assignable to all of the return types of the rest of the methods.
- The resulting proxy class must not exceed any limits imposed on classes by the virtual machine. For example, the VM may limit the number of interfaces that a class may implement to 65535; in that case, the size of the interfaces array must not exceed 65535.

Note that the order of the specified proxy interfaces is significant: two requests for a proxy class with the same combination of interfaces but in a different order will result in two distinct proxy classes.

```java
    @CallerSensitive
    public static Object newProxyInstance(ClassLoader loader,
                                          Class<?>[] interfaces,
                                          InvocationHandler h) {
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



## Reference

1. [JVM源码分析之不保证顺序的Class.getMethods](http://lovestblog.cn/blog/2016/11/02/class-getmethods/)