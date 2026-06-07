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

存储字面量和符号引用

Code

LineNumberTable

LocalVariableTable

1. invokevirtual：public、protected 方法（非 static、final）
2. invokeinterface：类似 invokevirtual
3. invokespecial：private 或构造器
4. invokestatic：static

invokeinterface 通过 this 对象获取 Klass
