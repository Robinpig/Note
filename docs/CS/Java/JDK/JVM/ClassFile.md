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

1. invokevirtual：public, protected methods without static, final
2. invokeinterface：like invokevirtual
3. invokespecial：只用于调用私有方法，构造方法。跟多态机制无关。
4. invokestatic：只用于调用静态方法。与多态机制无关。

invokeinterface get a this object to get Klass
