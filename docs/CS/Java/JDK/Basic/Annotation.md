## Introduction

An annotation is a special form of syntactic metadata that can be added to Java source code.
Classes, methods, variables, parameters and packages may be annotated.
**Annotations have no direct effect on the operation of the code they annotate** — they are consumed by the compiler, by build-time tools, or reflectively at runtime.

Annotations have a number of uses, among them:

- Information for the compiler — detect errors or suppress warnings.
- Compile-time and deployment-time processing — tools process annotation information to generate code, XML files, and so forth.
- Runtime processing — some annotations are available to be examined at runtime.

Java defines a set of built-in annotations, and a set of meta-annotations used to annotate other annotation types.

## Built-in Annotations

Applied to code:

- `@Override` — asks the compiler to verify the method overrides a supertype method; a compile error if no match is found.
- `@Deprecated` — marks the element obsolete; produces a warning on use (and a `forRemoval` flag since JDK 9 for imminent removal).
- `@SuppressWarnings` — instructs the compiler to suppress the named compile-time warnings (e.g. `"unchecked"`, `"deprecation"`).
- `@SafeVarargs` — asserts the method/constructor does not perform unsafe operations on its varargs (suppresses the `unchecked` warning for heap pollution).
- `@FunctionalInterface` — marks an interface as a functional interface (exactly one abstract method); a compile error if the contract is violated.
- `@Native` — marks a `public static final` primitive constant as being referenced from native code (JDK 8).

## Meta-annotations

Meta-annotations annotate other annotation type declarations.

### Target

Indicates the contexts in which an annotation type is applicable (JLS 9.6.4.1), denoted by `java.lang.annotation.ElementType`:

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Target {
    ElementType[] value();
}
```

The constants split into **declaration contexts** (`TYPE`, `FIELD`, `METHOD`, `PARAMETER`, `CONSTRUCTOR`, `LOCAL_VARIABLE`, `ANNOTATION_TYPE`, `PACKAGE`, `TYPE_PARAMETER`, `MODULE`, `RECORD_COMPONENT`) and **type contexts** (`TYPE_USE`).
`TYPE_USE` (JDK 8) covers all 15 type contexts in JLS 4.11 plus type and type-parameter declarations — it is what lets a checker annotate `List<@NonNull String>`.

```java
public enum ElementType {
    TYPE, FIELD, METHOD, PARAMETER, CONSTRUCTOR,
    LOCAL_VARIABLE, ANNOTATION_TYPE, PACKAGE,
    TYPE_PARAMETER,      // declaration of a type parameter
    TYPE_USE,            // use of a type
    MODULE,              // (JDK 9)
    RECORD_COMPONENT;    // (JDK 16)
}
```

### Retention

Indicates how long annotations are retained. If absent, the policy defaults to `RetentionPolicy.CLASS`.

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Retention {
    RetentionPolicy value();
}
```

```java
public enum RetentionPolicy {
    SOURCE,  // discarded by the compiler
    CLASS,   // recorded in the class file, not retained by the VM (default)
    RUNTIME  // recorded in the class file, retained by the VM, readable via reflection
}
```

### Documented

If `@Documented` is present on annotation type `A`, then any `@A` on an element is part of that element's public contract and shown by tools like `javadoc`.

### Inherited

If `@Inherited` is present, a class query for the annotation walks up the superclass chain.
It has effect **only for class declarations** — annotations on interfaces are never inherited through interface implementation.

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Inherited {}
```

### Repeatable

JEP 120 (JDK 8) allows the same annotation type to be applied multiple times to one element.
The base type is marked with `@Repeatable`, pointing at a **container annotation** whose `value()` is an array of the base type.

```java
@Repeatable(Authorities.class)
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface Authority {
    String role();
}

@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface Authorities {
    Authority[] value();
}

// usage
@Authority(role = "Admin")
@Authority(role = "Manager")
public void doSomething() { /* ... */ }
```

The compiler desugars the repeated form into a single `@Authorities({...})`. At runtime, `getAnnotation(Authority.class)` "looks through" the container (JLS 9.7), so reflection sees the individual `@Authority` instances.

### Native

`@Native` (JDK 8) marks a `public static final` primitive constant as being referenced from native code, so tools can generate the proper native header (`javac -h`).

## Type Annotations

JEP 104 (JDK 8) made annotations applicable **anywhere a type is used**, not just on declarations.
Combined with a pluggable type system (e.g. the Checker Framework), this enables improved type checking:

```java
List<@NonNull String> names = new ArrayList<>();
@NonNull String lookup(@Nullable Key k) { /* ... */ }
void process(@Readonly MyObject o) { /* ... */ }
```

The compiler records these in `RuntimeVisibleTypeAnnotations` attributes; `AnnotatedElement` exposes them via `getAnnotation` / `getAnnotationsByType` on the corresponding type-use location.

## Annotation Processing

At compile time, an annotation processor (`javax.annotation.processing.AbstractProcessor`) can generate source or resource files for annotations it supports.
Processors run in **rounds**: the compiler parses sources, invokes each processor's `process(Set<? extends TypeElement>, RoundEnvironment)`, and if any processor produces new files, a new round begins with the augmented source set until no new files are generated.

```java
@SupportedAnnotationTypes("com.example.MyAnno")
@SupportedSourceVersion(SourceVersion.RELEASE_25)
public class MyProcessor extends AbstractProcessor {
    @Override
    public boolean process(Set<? extends TypeElement> annotations,
                           RoundEnvironment roundEnv) {
        for (Element e : roundEnv.getElementsAnnotatedWith(MyAnno.class)) {
            // emit a new source/class/resource via Filer
            try (Writer w = processingEnv.getFiler()
                    .createSourceFile("com.example.Generated").openWriter()) {
                w.write("package com.example; public class Generated {}");
            } catch (IOException ex) { /* ... */ }
        }
        return false; // false = don't claim the annotations, others may process
    }
}
```

`Filer` writes generated files, `Messager` reports diagnostics, and `Elements`/`Types` provide the compile-time model.

## Reading at Runtime

Annotations retained at `RUNTIME` are read reflectively through `java.lang.reflect.AnnotatedElement`:

```java
Class<?> clazz = SomeBean.class;
if (clazz.isAnnotationPresent(Service.class)) {
    Service svc = clazz.getAnnotation(Service.class);
    String name = svc.value();
}
// repeatable: getAnnotationsByType "looks through" the container
Authority[] auths = method.getAnnotationsByType(Authority.class);
```

All annotations returned are immutable and serializable; the arrays returned may be modified by the caller without affecting other callers.

## Implementations

See [Dubbo SPI](/docs/CS/Framework/Dubbo/SPI.md) for a framework-level annotation-driven extension mechanism.

## Links

- [Java basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Generics](/docs/CS/Java/JDK/Basic/Generics.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)

## References

1. [JLS 9.6 (Annotation Types)](https://docs.oracle.com/javase/specs/jls/se25/html/jls-9.html#jls-9.6)
2. [JEP 120: Repeating Annotations](https://openjdk.org/jeps/120)
3. [JEP 104: Annotations on Java Types](https://openjdk.org/jeps/104)
4. [The Java Tutorials — Annotations](https://docs.oracle.com/javase/tutorial/java/annotations/)
