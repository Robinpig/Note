## Introduction

ELF is the abbreviation for Executable and Linkable Format and defines the structure for binaries, libraries, and core files. 
The formal specification allows the operating system to interpreter its underlying machine instructions correctly. 
ELF files are typically the output of a compiler or linker and are a binary format.


## x86

```c
#define ELF_MAGIC 0x464C457FU  // “\x7FELF” in little endian

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
