## Introduction


RTTI(Run Time Type Identification)即通过运行时类型识别，程序能够使用基类的指针或引用来检查着这些指针或引用所指的对象的实际派生类型

和很多其他语言一样，C++是一种静态类型语言。其数据类型是在编译期就确定的，不能在运行时更改
然而由于面向对象程序设计中多态性的要求，C++中的指针或引用(Reference)本身的类型，可能与它实际代表(指向或引用)的类型并不一致
有时我们需要将一个多态指针转换为其实际指向对象的类型，就需要知道运行时的类型信息，这就产生了运行时类型识别的要求
和 Java 相比，C++ 要想获得运行时类型信息，只能通过 RTTI 机制，并且 C++ 最终生成的代码是直接与机器相关的

RTTI 依赖的 `std::type_info` 由编译器嵌入对象的 vtable（见 [对象模型](/docs/CS/C++/ObjectModel.md)），因此只有多态类才有可用 RTTI。

> Java 中任何一个类都可以通过 [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) 来获取类的基本信息（接口、父类、方法、属性、Annotation等），
> 而且 Java 中还提供了一个关键字 `instanceof`，可以在运行时判断一个类是不是另一个类的子类或者是该类的对象，Java 生成字节码文件中含有类的信息

dynamic_cast






## Links

- [C++](/docs/CS/C++/C++.md)
- [对象模型](/docs/CS/C++/ObjectModel.md)
