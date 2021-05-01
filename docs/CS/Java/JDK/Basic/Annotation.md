# Annotation



![Annotation](https://github.com/Robinpig/Note/blob/master/images/JDK/Annotation.png)

*The common interface extended by all annotation types. Note that an interface that manually extends this one does not define an annotation type. Also note that this interface does not itself define an annotation type. More information about annotation types can be found in section 9.6 of The Java Language Specification. The reflect.AnnotatedElement interface discusses compatibility concerns when evolving an annotation type from being non-repeatable to being repeatable.*





## AnnotatedElement

`java.lang.reflect.AnnotatedElement`

*Represents an annotated element of the program currently running in this VM. T**his interface allows annotations to be read reflectively**. **All annotations returned by methods in this interface are immutable and serializable**. The arrays returned by methods of this interface may be modified by callers without affecting the arrays returned to other callers.*

*The **getAnnotationsByType(Class)** and **getDeclaredAnnotationsByType(Class)** methods support multiple annotations of the same type on an element. If the argument to either method is a repeatable annotation type (JLS 9.6), then the method will "look through" a container annotation (JLS 9.7), if present, and return any annotations inside the container. Container annotations may be generated at compile-time to wrap multiple annotations of the argument type.*



*The terms directly present, indirectly present, present, and associated are used throughout this interface to describe precisely which annotations are returned by methods:*

1. *An annotation A is directly present on an element E if E has a RuntimeVisibleAnnotations or RuntimeVisibleParameterAnnotations or RuntimeVisibleTypeAnnotations attribute, and the attribute contains A.*
2. *An annotation A is indirectly present on an element E if E has a RuntimeVisibleAnnotations or RuntimeVisibleParameterAnnotations or RuntimeVisibleTypeAnnotations attribute, and A 's type is repeatable, and the attribute contains exactly one annotation whose value element contains A and whose type is the containing annotation type of A 's type.*
3. *An annotation A is present on an element E if either:*
   1. *A is directly present on E; or*
   2. *No annotation of A 's type is directly present on E, and E is a class, and A 's type is inheritable, and A is present on the superclass of E.*
4. *An annotation A is associated with an element E if either:*
   1. *A is directly or indirectly present on E; or*
   2. *No annotation of A 's type is directly or indirectly present on E, and E is a class, and A's type is inheritable, and A is associated with the superclass of E.*