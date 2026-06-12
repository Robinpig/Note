## Introduction

An annotation, in the Java computer programming language, is a special form of syntactic metadata that can be added to Java source code.
Classes, methods, variables, parameters and packages may be annotated.
**Annotations have no direct effect on the operation of the code they annotate.**

Annotations have a number of uses, among them:

- Information for the compiler — Annotations can be used by the compiler to detect errors or suppress warnings.
- Compile-time and deployment-time processing — Software tools can process annotation information to generate code, XML files, and so forth.
- Runtime processing — Some annotations are available to be examined at runtime.

It is possible to create meta-annotations out of the existing ones in Java, which makes this concept more sophisticated.
Java defines a set of annotations that are built into the language.

Annotations applied to java code:

- @Override – Checks that the function is an override. Causes a compile warning if the function is not found in one of the parent classes.
- @Deprecated – Marks the function as obsolete. Causes a compile warning if the function is used.
- @SuppressWarnings – Instructs the compiler to suppress the compile time warnings specified in the annotation parameters.


Repeating Annotations provide the ability to apply the same annotation type more than once to the same declaration or type use.
Type Annotations provide the ability to apply an annotation anywhere a type is used, not just on a declaration. Used with a pluggable type system, this feature enables improved type checking of your code.

Annotations applied to other annotations:

- @Retention – Specifies how the marked annotation is stored—Whether in code only, compiled into the class, or available at runtime through reflection.
- @Documented – Marks another annotation for inclusion in the documentation.
- @Target – Marks another annotation to restrict what kind of java elements the annotation may be applied to.
- @Inherited – Marks another annotation to be inherited to subclasses of **annotated class** (by default annotations are not inherited to subclasses).

### Annotation Hierarchy

![Annotation](../img/Annotation.png)

The common interface extended by all annotation types. Note that an interface that manually extends this one does not define an annotation type.
Also note that this interface does not itself define an annotation type.
The `reflect.AnnotatedElement` interface discusses compatibility concerns when evolving an annotation type from being non-repeatable to being repeatable.

```java
public interface Annotation {

   boolean equals(Object obj);

   int hashCode();

   String toString();

   Class<? extends Annotation> annotationType();
}
```

## Meta-annotation

### Target

Indicates the contexts in which an annotation type is applicable. 
The declaration contexts and type contexts in which an annotation type may be applicable are specified in JLS 9.6.4.1, and denoted in source code by enum constants of `java.lang.annotation.ElementType`.

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Target {
    /**
     * Returns an array of the kinds of elements an annotation type
     * can be applied to.
     * @return an array of the kinds of elements an annotation type
     * can be applied to
     */
    ElementType[] value();
}
```

#### ElementType

The constants of this enumerated type provide a simple classification of the syntactic locations where annotations may appear in a Java program.
These constants are used in java.lang.annotation.Target meta-annotations to specify where it is legal to write annotations of a given type.
The syntactic locations where annotations may appear are split into declaration contexts , where annotations apply to declarations, and type contexts , where annotations apply to types used in declarations and expressions.
The constants ANNOTATION_TYPE , CONSTRUCTOR , FIELD , LOCAL_VARIABLE , METHOD , PACKAGE , PARAMETER , TYPE , and TYPE_PARAMETER correspond to the declaration contexts in JLS 9.6.4.1.
For example, an annotation whose type is meta-annotated with @Target(ElementType.FIELD) may only be written as a modifier for a field declaration.

The constant `TYPE_USE` corresponds to the 15 type contexts in JLS 4.11, as well as to two declaration contexts: type declarations (including annotation type declarations) and type parameter declarations.
For example, an annotation whose type is meta-annotated with @Target(ElementType.TYPE_USE) may be written on the type of a field (or within the type of the field, if it is a nested, parameterized, or array type),
and may also appear as a modifier for, say, a class declaration.
The `TYPE_USE` constant includes type declarations and type parameter declarations as a convenience for designers of type checkers which give semantics to annotation types.
For example, if the annotation type NonNull is meta-annotated with @Target(ElementType.TYPE_USE), then @NonNull class C {...} could be treated by a type checker as indicating that all variables of class C are non-null,
while still allowing variables of other classes to be non-null or not non-null based on whether @NonNull appears at the variable's declaration.

```java
public enum ElementType {
    /** Class, interface (including annotation type), or enum declaration */
    TYPE,

    /** Field declaration (includes enum constants) */
    FIELD,

    /** Method declaration */
    METHOD,

    /** Formal parameter declaration */
    PARAMETER,

    /** Constructor declaration */
    CONSTRUCTOR,

    /** Local variable declaration */
    LOCAL_VARIABLE,

    /** Annotation type declaration */
    ANNOTATION_TYPE,

    /** Package declaration */
    PACKAGE,

    // Type parameter declaration
    TYPE_PARAMETER,

    // Use of a type
    TYPE_USE
}

```

### Retention

Indicates how long annotations with the annotated type are to be retained. 
If no Retention annotation is present on an annotation type declaration, the retention policy defaults to RetentionPolicy.CLASS.

A Retention meta-annotation has effect only if the meta-annotated type is used directly for annotation. 
It has no effect if the meta-annotated type is used as a member type in another annotation type.

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Retention {
    /**
     * Returns the retention policy.
     * @return the retention policy
     */
    RetentionPolicy value();
}
```

SOURCE CLASS extends AbstractProccessor override process

Annotation retention policy. The constants of this enumerated type describe the various policies for retaining annotations. They are used in conjunction with the Retention meta-annotation type to specify how long annotations are to be retained.

```java
public enum RetentionPolicy {

   SOURCE,
   CLASS,
   RUNTIME
}
```

#### AnnotatedElement

`java.lang.reflect.AnnotatedElement`

Represents an annotated element of the program currently running in this VM. This interface allows annotations to be read reflectively.
All annotations returned by methods in this interface are immutable and serializable.
The arrays returned by methods of this interface may be modified by callers without affecting the arrays returned to other callers.

The *getAnnotationsByType(Class)* and *getDeclaredAnnotationsByType(Class)* methods support multiple annotations of the same type on an element.
If the argument to either method is a repeatable annotation type (JLS 9.6), then the method will "look through" a container annotation (JLS 9.7), if present, and return any annotations inside the container.
Container annotations may be generated at compile-time to wrap multiple annotations of the argument type.*

*The terms directly present, indirectly present, present, and associated are used throughout this interface to describe precisely which annotations are returned by methods:

1. An annotation A is directly present on an element E if E has a RuntimeVisibleAnnotations or RuntimeVisibleParameterAnnotations or RuntimeVisibleTypeAnnotations attribute, and the attribute contains A.
2. An annotation A is indirectly present on an element E if E has a RuntimeVisibleAnnotations or RuntimeVisibleParameterAnnotations or RuntimeVisibleTypeAnnotations attribute,
   and A 's type is repeatable, and the attribute contains exactly one annotation whose value element contains A and whose type is the containing annotation type of A 's type.
3. An annotation A is present on an element E if either:
   1. A is directly present on E; or
   2. No annotation of A 's type is directly present on E, and E is a class, and A 's type is inheritable, and A is present on the superclass of E.
4. An annotation A is associated with an element E if either:
   1. A is directly or indirectly present on E; or
   2. No annotation of A 's type is directly or indirectly present on E, and E is a class, and A's type is inheritable, and A is associated with the superclass of E.

### Documented

If the annotation @Documented is present on the declaration of an annotation type A, then any @A annotation on an element is considered part of the element's public contract. 
In more detail, when an annotation type A is annotated with Documented, the presence and value of annotations of type A are a part of the public contract of the elements A annotates. 
Conversely, if an annotation type B is not annotated with Documented, the presence and value of B annotations are not part of the public contract of the elements B annotates. 
Concretely, if an annotation type is annotated with Documented, by default a tool like javadoc will display annotations of that type in its output while annotations of annotation types without Documented will not be displayed.

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Documented {
}
```

### Inherited

Indicates that an annotation type is automatically inherited. 
If an Inherited meta-annotation is present on an annotation type declaration, and the user queries the annotation type on a class declaration, 
and the class declaration has no annotation for this type, then the class's superclass will automatically be queried for the annotation type. 
This process will be repeated until an annotation for this type is found, or the top of the class hierarchy (Object) is reached. 
If no superclass has an annotation for this type, then the query will indicate that the class in question has no such annotation.

> [!NOTE]
>
> Note that this meta-annotation type has no effect if the annotated type is used to annotate anything other than a class. 
> Note also that this meta-annotation only causes annotations to be inherited from superclasses; annotations on implemented interfaces have no effect.


> AnnotatedElementUtil#findMergedAnnotation could help us. 


```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.ANNOTATION_TYPE)
public @interface Inherited {
}
```

## Implementations

See [Dubbo SPI](/docs/CS/Framework/Dubbo/SPI.md)

```java
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target({ElementType.TYPE})
public @interface SPI {

    /**
     * default extension name
     */
    String value() default "";

}
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
