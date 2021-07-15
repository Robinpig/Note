## Introduction

**The \*enum\* keyword was introduced in Java 5.** It denotes a special type of class that **always extends the *java.lang.Enum* class.** 

**Comparing Enum Types Using “==”  rather than equals.**



`finalize` is final





### Serialize

```java
/**
 * prevent default deserialization
 */
private void readObject(ObjectInputStream in) throws IOException,
    ClassNotFoundException {
    throw new InvalidObjectException("can't deserialize enum");
}

private void readObjectNoData() throws ObjectStreamException {
    throw new InvalidObjectException("can't deserialize enum");
}
```



```java
// Writes given enum constant to stream. only write Enum.name
private void writeEnum(Enum<?> en,
                       ObjectStreamClass desc,
                       boolean unshared)
    throws IOException
{
    bout.writeByte(TC_ENUM);
    ObjectStreamClass sdesc = desc.getSuperDesc();
    writeClassDesc((sdesc.forClass() == Enum.class) ? desc : sdesc, false);
    handles.assign(unshared ? null : en);
    writeString(en.name(), false);
}
```



~~~java
/** ObjectInputStream
 * Reads in and returns enum constant, or null if enum type is
 * unresolvable.  Sets passHandle to enum constant's assigned handle.
 */
private Enum<?> readEnum(boolean unshared) throws IOException {
  ...
    Enum<?> en = Enum.valueOf((Class)cl, name); // use name Enum.valueOf()
 		result = en;
  ```
    return result;
}
~~~



## EnumSet and EnumMap

### EnumSet

The *EnumSet* is a specialized *Set* implementation meant to be used with *Enum* types.

It is a very efficient and compact representation of a particular *Set* of *Enum* constants when compared to a *HashSet*, owing to the internal *Bit Vector Representation* that is used. And it provides a type-safe alternative to traditional *int*-based “bit flags”, allowing us to write concise code that is more readable and maintainable.

The *EnumSet* is an abstract class that has two implementations called *RegularEnumSet* and *JumboEnumSet*, one of which is chosen depending on the number of constants in the enum at the time of instantiation.

Therefore it is always a good idea to use this set whenever we want to work with a collection of enum constants in most of the scenarios (like subsetting, adding, removing, and for bulk operations like *containsAll* and *removeAll*) and use *Enum.values()* if you just want to iterate over all possible constants.



### EnumMap

*EnumMap* is a specialized *Map* implementation meant to be used with enum constants as keys. It is an efficient and compact implementation compared to its counterpart *HashMap* and is internally represented as an array: