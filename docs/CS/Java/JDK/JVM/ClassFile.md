## Introduction


Class file format：

- magic number
- minor_version & major_version
- constant_pool_count & constant_pool
- access_flags
- this_class & super_class
- interfaces_count & interfaces
- fields_count & fields
- methods_count & methods
- attributes_count & attributes



使用[jclasslib bytecode editor](https://github.com/ingokegel/jclasslib)查看class文件

### access flags

### Constant Pool

storage Literal and Symbolic References

Code

LineNumberTable

LocalVariableTable

1. invokevirtual：public, protected methods without static, final
2. invokeinterface：like invokevirtual
3. invokespecial：private or constructor
4. invokestatic：static

invokeinterface get a this object to get Klass
