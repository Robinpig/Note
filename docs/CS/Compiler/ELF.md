## Introduction

ELF is the abbreviation for Executable and Linkable Format and defines the structure for binaries, libraries, and core files.
The formal specification allows the operating system to interpreter its underlying machine instructions correctly.
ELF files are typically the output of a compiler or linker and are a binary format.

 
struct

文件扩展名: 无扩展名、.axf、.bin、.elf、.o、.prx、.puff、.ko、.mod 和 .so。

魔数: 0x7F 紧跟 'E'、'L'、'F' 三个字符，即 0x7F 45 4C 46 共四个字节

<div style="text-align: center;">

![Fig.1. ELF format](img/ELF-Format.png)

</div>

<p style="text-align: center;">
Fig.1. ELF format
</p>

结构：

- ELF 首部 (ELF header) (52 or 64 byte long for 32 or 64 bit): 32 位目标会占用 52 字节，64 位目标会占用 64 字节。它定义了当前 ELF 文件使用的机器类型。
- 程序头表 (Program header table): 描述 0 个或多个 内存段 (segment) 信息。只适用于可执行文件这一类别。它的作用是描述该可执行文件应该如何被装入进程虚拟内存 (process virtual memory) 中，即如何创建进程镜像 (process image)。对于进程镜像、可执行文件、共享库来说是必须的，不过可重定位代码不必提供。
- 分段头表 (Section header table): 描述 0 个或多个段的链接以及重定位需要的数据 (section)。它描述了 ELF 文件中的各种链接应该如何加载，以及在哪个位置可以找到。表中的每一项都记录了程序各个分段的名称和大小。如果后续还需要对文件进行链接，则必须要提供分段头表，否则无法将多个不同对象文件中的同类分段合并。
- 数据 (Data): 程序头表和分段头表所具体引用的数据内容。


关于 ELF 文件的若干工具:

- readelf: 用于查看 ELF 文件的信息 (由 GNU binutils 提供)。
- elfutils: binutils 的替代品。
- elfdump: 输出 ELF 文件的 ELF 信息。
- objdump: 输出对象文件的信息。它使用二进制描述符 (Binary Descriptor) 库来组织构造 ELF 数据。
- file: 可以用于显示 ELF 文件的部分信息，比如这个可重定位文件、可执行文件或共享库所构建的目标 ISA，或是 ELF 内核转储是在什么样的 ISA 上产生的。
- nm: 可以用于显示一个对象文件包含的符号信息

## Links

- [GCC](/docs/CS/Compiler/GCC.md)
- [xv6 ELF](/docs/CS/OS/xv6/ELF.md)


## References

1. [The 101 of ELF files on Linux: Understanding and Analysis](https://linux-audit.com/elf-binaries-on-linux-understanding-and-analysis/)
