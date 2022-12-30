## Introduction

**The `enum` keyword was introduced in Java 5.** It denotes a special type of class that **always extends the *java.lang.Enum* class.**
**Java enum**, also called Java *enumeration type*, is a type whose **fields consist of a fixed set of constants**.
The very purpose of enum is to **enforce compile time type safety**.

When you create an enum, an associated class is produced for you by the compiler.
This class is automatically inherited from java.lang.Enum, which provides certain capabilities:

The ordinal() method produces an int indicating the declaration order of each enum instance, starting from zero.
You can always safely compare enum instances using ==, and equals() and hashCode() are automatically created for you.
The Enum class is Comparable, so there’s a compareTo() method, and it is also Serializable.

If you call getDeclaringClass() on an enum instance, you’ll find out the enclosing enum class.
The name() method produces the name exactly as it is declared, and this is what you get with toString(), as well.
valueOf() is a static member of Enum, and produces the enum instance that corresponds to the String name you pass to it, or throws an exception if there’s no match.

Although enums appear to be a new data type, the keyword only produces some compiler behavior while generating a class for the enum, so in many ways you can treat an enum as if it were any other class.
In fact, enums are classes and have their own methods.

An especially nice feature is the way that enums can be used inside switch statements.
Since a switch is intended to select from a limited set of possibilities, it’s an ideal match for an enum. Notice how enum names can produce a much clearer expression of intent.
In general you can use an enum as if it were another way to create a data type, then just put the results to work.

**Comparing Enum Types Using “==”  rather than equals.**

**Use enums instead of int constants**.

`finalize` is final

### Serialization

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

## Constant-Specific Methods

### Chain of Responsibility with enums

In the Chain of Responsibility design pattern, you create a number of different ways to solve a problem and chain them together.
When a request occurs, it is passed along the chain until one of the solutions can handle the request.

You can easily implement a simple Chain of Responsibility with constant-specific methods.
Consider a model of a post office, which tries to deal with each piece of mail in the most general way possible, but must keep trying until it ends up treating the mail as a dead letter.
Each attempt can be thought of as a Strategy (another design pattern), and the entire list together is a Chain of Responsibility.

We start by describing a piece of mail.
All the different characteristics of interest can be expressed using enums.
Because Mail objects are randomly generated, the easiest way to reduce the probability of (for example) a piece of mail being given a YES for GeneralDelivery is to create more non-YES instances, so the enum definitions look a little funny at first.

### State Machines with enums

Enumerated types can be ideal for creating state machines.
A state machine can be in a finite number of specific states.
The machine normally moves from one state to the next based on an input, but there are also transient states; the machine moves out of these as soon as their task is performed.

There are certain allowable inputs for each state, and different inputs change the state of the machine to different new states.
Because enums restrict the set of possible cases, they are useful for enumerating the different states and inputs.
Each state also typically has some kind of associated output.

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
