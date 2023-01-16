## Introduction

- magic
- minor_version & major_version
- constant_pool_count & constant_pool
- access_flags
- this_class & super_class
- interfaces_count & interfaces
- fields_count & fields
- methods_count & methods
- attributes_count & attributes

### access flags

### Constant Pool

storage Literal and Symbolic References

Code

LineNumberTable

LocalVariableTable

1. invokevirtual：咱们平时写代码调用方法，最常用的就是这个指令。这个指令用于调用public、protected修饰，且不被static、final修饰的方法。跟多态机制有关。
2. invokeinterface：跟invokevirtual差不多。区别是多态调用时，如果父类引用是对象，就用invokevirtual。如果父类引用是接口，就用这个。
3. invokespecial：只用于调用私有方法，构造方法。跟多态机制无关。
4. invokestatic：只用于调用静态方法。与多态机制无关。

invokeinterface get a this object to get Klass
