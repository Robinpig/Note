## Introduction

ELF 是 Executable and Linkable Format（可执行与可链接格式）的缩写，定义了二进制文件、库和核心文件的结构。
正式规范允许操作系统正确解释其底层的机器指令。
ELF 文件通常是编译器或链接器的输出，是一种二进制格式。

## x86

```c
#define ELF_MAGIC 0x464C457FU  // "\x7FELF" in little endian

// File header
struct elfhdr {
  uint magic;  // must equal ELF_MAGIC
  uchar elf[12];
  ushort type;
  ushort machine;
  uint version;
  uint entry;
  uint phoff;
  uint shoff;
  uint flags;
  ushort ehsize;
  ushort phentsize;
  ushort phnum;
  ushort shentsize;
  ushort shnum;
  ushort shstrndx;
};
```

```c
// Program section header
struct proghdr {
  uint type;
  uint off;
  uint vaddr;
  uint paddr;
  uint filesz;
  uint memsz;
  uint flags;
  uint align;
};
```

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [ELF](/docs/CS/Compiler/ELF.md)

## References
