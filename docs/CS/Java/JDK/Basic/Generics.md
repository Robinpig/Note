## Introduction

Generics means parameterized types. 
The idea is to allow type (Integer, String, … etc, and user-defined types) to be a parameter to methods, classes, and interfaces. Using Generics, it is possible to create classes that work with different data types.

An entity such as class, interface, or method that operates on a parameterized type is called generic entity.

Why Generics?

Object is the superclass of all other classes and Object reference can refer to any type object. These features lack type safety. Generics adds that type safety feature. We will discuss that type safety feature in later examples.

Generics in Java is similar to templates in C++. For example, classes like HashSet, ArrayList, HashMap, etc use generics very well. There are some fundamental differences between the two approaches to generic types.

How to implement generics?
- Code specialization
- Code sharing

`C++ and C# use Code specialization while Java use Code sharing`

Type Erasure

generics not exist in JVM,only have List.class not List<Integer>.class

## Type Expression

Usually Parameters : 

- E - Element  use in Collection 

- T - Type

- K - Key in Map

- V - Value in Map

- ? - Type not sure



