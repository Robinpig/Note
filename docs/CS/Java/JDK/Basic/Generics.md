## Introduction

Generics means parameterized types. 

The idea is to allow type (Integer, String, … etc, and user-defined types) to be a parameter to methods, classes, and interfaces. Using Generics, it is possible to create classes that work with different data types.

An entity such as class, interface, or method that operates on a parameterized type is called generic entity.

Object is the superclass of all other classes and Object reference can refer to any type object. These features lack type safety. Generics adds that type safety feature. We will discuss that type safety feature in later examples.

Generics in Java is similar to templates in C++. For example, classes like HashSet, ArrayList, HashMap, etc use generics very well. There are some fundamental differences between the two approaches to generic types.

How to implement generics?
- Code specialization
- Code sharing

`C++ and C# use Code specialization while Java use Code sharing.`



> “In layman,s term, generics force type safety in java language.”
>
> “Generics add stability to your code by making more of your bugs detectable at compile time.”



In the heart of generics is “[**type safety**](https://en.wikipedia.org/wiki/Type_safety)“. What exactly is type safety? It’s just a guarantee by compiler that if correct Types are used in correct places then there should not be any `ClassCastException` in runtime. A usecase can be list of `Integer` i.e. `List<Integer>`. If you declare a list in java like `List<Integer>`, then java guarantees that it will detect and report you any attempt to insert any non-integer type into above list.

Another important term in java generics is “[**type erasure**](https://en.wikipedia.org/wiki/Type_erasure)“. It essentially means that all the extra information added using generics into source code will be removed from bytecode generated from it. Inside bytecode, it will be old java syntax which you will get if you don’t use generics at all. This necessarily helps in generating and executing code written prior to java 5 when generics were not added in language.

generics not exist in JVM,only have List.class not List<Integer>.class

## Type Expression

Usually Parameters : 

- E - Element  use in Collection 

- T - Type

- K - Key in Map

- V - Value in Map

- ? - Type not sure



