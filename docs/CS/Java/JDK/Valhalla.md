## Introduction

[Project Valhalla](https://openjdk.java.net/projects/valhalla/) plans to augment the Java object model with value objects and user-defined primitives, combining the abstractions of object-oriented programming with the performance characteristics of simple primitives.
These features will be complemented with changes to Java’s generics to preserve performance gains through generic APIs.


## Hidden Classes

Creates a hidden class or interface from bytes, returning a Lookup on the newly created class or interface.

Ordinarily, a class or interface C is created by a class loader, which either defines C directly or delegates to another class loader. A class loader defines C directly by invoking ClassLoader::defineClass, which causes the Java Virtual Machine to derive C from a purported representation in class file format. In situations where use of a class loader is undesirable, a class or interface C can be created by this method instead. This method is capable of defining C, and thereby creating it, without invoking ClassLoader::defineClass. Instead, this method defines C as if by arranging for the Java Virtual Machine to derive a nonarray class or interface C from a purported representation in class file format using the following rules:

- The lookup modes for this Lookup must include full privilege access. This level of access is needed to create C in the module of the lookup class of this Lookup.
- The purported representation in bytes must be a ClassFile structure of a supported major and minor version. The major and minor version may differ from the class file version of the lookup class of this Lookup.
- The value of this_class must be a valid index in the constant_pool table, and the entry at that index must be a valid CONSTANT_Class_info structure. Let N be the binary name encoded in internal form that is specified by this structure. N must denote a class or interface in the same package as the lookup class.
- Let CN be the string N + "." + <suffix>, where <suffix> is an unqualified name.
  Let newBytes be the ClassFile structure given by bytes with an additional entry in the constant_pool table, indicating a CONSTANT_Utf8_info structure for CN, and where the CONSTANT_Class_info structure indicated by this_class refers to the new CONSTANT_Utf8_info structure.
  Let L be the defining class loader of the lookup class of this Lookup.
  C is derived with name CN, class loader L, and purported representation newBytes as if by the rules of JVMS , with the following adjustments:
    - The constant indicated by this_class is permitted to specify a name that includes a single "." character, even though this is not a valid binary class or interface name in internal form.
    - The Java Virtual Machine marks L as the defining class loader of C, but no class loader is recorded as an initiating class loader of C.
    - C is considered to have the same runtime package, module and protection domain as the lookup class of this Lookup.
    - Let GN be the binary name obtained by taking N (a binary name encoded in internal form) and replacing ASCII forward slashes with ASCII periods. For the instance of Class representing C:
        - Class.getName() returns the string GN + "/" + <suffix>, even though this is not a valid binary class or interface name.
        - Class.descriptorString() returns the string "L" + N + "." + <suffix> + ";", even though this is not a valid type descriptor name.
        - Class.describeConstable() returns an empty optional as C cannot be described in nominal form.

```java
public Lookup defineHiddenClass(byte[] bytes, boolean initialize, ClassOption... options)
                throws IllegalAccessException
   {
		...
    return makeHiddenClassDefiner(bytes.clone(), Set.of(options), false).defineClassAsLookup(initialize);
}

Lookup defineClassAsLookup(boolean initialize) {
    Class<?> c = defineClass(initialize, null);
    return new Lookup(c, null, FULL_POWER_MODES);
}
```




## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)