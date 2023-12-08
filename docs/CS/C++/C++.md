## Introduction


C++ blends the C language with support for object-oriented programming and for generic programming.


## Basic concepts


Resource Acquisition Is Initialization or RAII, is a C++ programming technique which binds the life cycle of a resource that must be acquired before use 
(allocated heap memory, thread of execution, open socket, open file, locked mutex, disk space, database connection—anything that exists in limited supply) 
to the lifetime of an object.




## Types

### 基本的内置类型

C++ 为程序员提供了种类丰富的内置数据类型和用户自定义的数据类型。下表列出了七种基本的 C++ 数据类型：

| 类型     | 关键字  |
| -------- | ------- |
| 布尔型   | bool    |
| 字符型   | char    |
| 整型     | int     |
| 浮点型   | float   |
| 双浮点型 | double  |
| 无类型   | void    |
| 宽字符型 | wchar_t |

### typedef 声明

您可以使用 **typedef** 为一个已有的类型取一个新的名字。下面是使用 typedef 定义一个新类型的语法：

```c++
typedef type newname; 
```

例如，下面的语句会告诉编译器，feet 是 int 的另一个名称：

```c++
typedef int feet;
```

现在，下面的声明是完全合法的，它创建了一个整型变量 distance：

```c++
feet distance;
```

### 枚举类型

创建枚举，需要使用关键字 **enum**。枚举类型的一般形式为：

```c++
enum 枚举名{ 
     标识符[=整型常数], 
     标识符[=整型常数], 
... 
    标识符[=整型常数]
} 枚举变量;
    
```

默认 变量值为第一个，值为0。


### Constant

 常量是固定值，在程序执行期间不会改变。这些固定的值，又叫做**字面量**。 

使用 **const** 前缀声明指定类型的常量，如下所示：

```c++
const type variable = value;
```

### 修饰符类型

C++ 允许在 **char、int 和 double** 数据类型前放置修饰符。修饰符用于改变基本类型的含义，所以它更能满足各种情境的需求。

下面列出了数据类型修饰符：

- signed
- unsigned
- long
- short

修饰符 **signed、unsigned、long 和 short** 可应用于整型，**signed** 和 **unsigned** 可应用于字符型，**long** 可应用于双精度型。

修饰符 **signed** 和 **unsigned** 也可以作为 **long** 或 **short** 修饰符的前缀。例如：**unsigned long int**。

C++ 允许使用速记符号来声明**无符号短整数**或**无符号长整数**。您可以不写 int，只写单词 **unsigned、short** 或 **unsigned、long**，int 是隐含的。例如，下面的两个语句都声明了无符号整型变量。

### 类型限定符

类型限定符提供了变量的额外信息。

| 限定符   | 含义                                                         |
| -------- | ------------------------------------------------------------ |
| const    | **const** 类型的对象在程序执行期间不能被修改改变。           |
| volatile | 修饰符 **volatile** 告诉编译器不需要优化volatile声明的变量，让程序可以直接从内存中读取变量。对于一般的变量编译器会对变量进行优化，将内存中的变量值放在寄存器中以加快读写效率。 |
| restrict | 由 **restrict** 修饰的指针是唯一一种访问它所指向的对象的方式。只有 C99 增加了新的类型限定符 restrict。 |



## Concurrency

[Concurrency](/docs/CS/C++/Concurrency.md)


## Links

- [C](/docs/CS/C/C.md)
- [Java JDK](/docs/CS/Java/JDK/JDK.md)


## References
