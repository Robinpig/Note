# Computer Systems A Programmer's Perspective Third Edition

## 计算机系统漫游

### 信息是位+上下文

Text File < Binary File



### GCC编译过程

- **预处理阶段**	.c文件通过预处理器（cpp）插入#include<>的内容生成.i文本文件
- **编译阶段**	通过编译器（ccl）编译成汇编程序.s文本文件
- **汇编阶段** 	汇编器（as）将其翻译成机器语言指令，打包成*可重定位目标程序*(relocatable object program)保存在.o的二进制文件
- **链接阶段**	链接器（ld）将被调用的函数所在的.o文件合并到主线，生成可执行文件



### 了解编译系统益处

- 优化程序性能

- 理解链接时出现的错误

- 避免安全漏洞



### 处理器读解释指令

命令行第一个单词不为内置命令时，则假定为可执行文件名

**系统硬件组成**

- 总线
- I/O设备
- 主存
- 处理器	核心是大小为一个字的程序寄存器（PC），指向主存中某条机器指令
  - 寄存器文件（register file）由一些单个字长的寄存器组成
  - 算术/逻辑单元（ALU）计算新的数据和地址值

**直接存储器存取**（DMA）技术可以让数据不通过处理器直接从磁盘到达主存

**操作系统**

- 基本功能
  - 防止硬件被失控的应用程序滥用
  - 向应用程序提供简单一致的机制来控制复杂而不相一致的硬件设备
- 抽象概念
  - **文件**	对I/O设备的抽象
  - **虚拟内存**	对主存和磁盘I/O设备的抽象
  - **进程**	对处理器、主存和I/O设备的抽象
    
    - 操作系统在进程间进行上下文切换
  - **虚拟机**	对操作系统、处理器、主存和I/O设备抽象
  - 处理器抽象出**指令集架构**
- 从特殊系统的角度看，网络就是一种I/O设备



**Amdahl定律**：要想显著加速整个系统，必须提升全系统中相当大部分的速度

执行时间：
$$
T_{new}=(1-\alpha)T_{old}+(\alpha T_{old})/k=T_{old}[(1-\alpha)+\alpha /k]
$$
加速比：
$$
S=T_{old}/T_{new}=\frac{1}{(1-\alpha)+\alpha /k}
$$

### 并发和并行

L1高速缓存分成数据和指令两个部分，L2属于单核，L3为所有核共享

- 线程级并发	超线程，又称同时多线程，允许一个CPU执行多个控制流
- 指令级并发	一个时钟周期一条指令或更快
- 单指令、多数据并行	例如SIMD指令，并行对float做加法







## 第一部分	程序结构和执行

### 信息的表示和处理

最小可寻址单位为byte，为8bit，内存被作为一个字节数组（virtual memory），每个字节具有唯一数字标识（address）

每个计算机拥有一个字长（word size）w，为指针数据的标称大小（nominal size），亦是虚拟地址空间最大大小为2^w字节，32位字长机器最大支持4GB

区别32还是64位程序在于编译过程

- 小端法（little endian）	最低有效字节在最前面
- 大端法（big endian）	最高有效字节在最前面



**反汇编器**是一种确定可执行程序文件所表示的指令序列的工具



- 逻辑右移 左端补0 >>
- 算术右移 左端补最高有效位的值 >>>



整数乘法使用加法和移位能提升性能





### 程序的机器级表示

汇编代码与机器指令级相关



- 程序计数器
- 整数寄存器 存储64位的值，地址或整数数据
- 条件码寄存器 保存最近执行算术或逻辑指令状态信息，用来实现if和while语句
- 向量寄存器 存放一个或多个整数或浮点数值

操作系统负责管理虚拟内存空间，将虚拟地址翻译成物理地址



x86-64的CPU包含一组16个存储64位值的**通用目的存储器**，以%r开头，存储整数数据和指针

- %rax 返回值
- %rsp 栈指针 指明运行时栈结束位置



x86-64限制传送指令（mov）的两个操作数不能指向内存位置，将一个值从一个内存位置复制到另一个位置需要先加载到寄存器，再从寄存器写入目标位置。

| 指令   | 位数         |
| ------ | ------------ |
| movb   | 1byte        |
| movw   | 2bytes       |
| movl   | 4bytes       |
| movq   | 8bytes       |
| movbsq | 绝对的8bytes |

通常局部变量保存在寄存器中以加快访问速度



### 处理器体系结构

### 优化程序性能

### 存储器层次结构

### 链接

### 异常控制流

## 虚拟内存

## 系统级I/O

## 网络编程

## 并发编程