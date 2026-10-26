## Introduction

ELF（Executable and Linkable Format）定义了可执行文件、目标文件与核心转储的二进制布局，操作系统据此把磁盘上的字节正确解释成机器指令与数据。xv6 的用户程序（包括首个进程 `initcode`、shell `sh`）都是 ELF，内核在 `exec()` 里解析它、把程序段搬进新建的地址空间，再跳到入口开始执行。

更通用的 ELF 规范与工具见 [Compiler/ELF](/docs/CS/Compiler/ELF.md)；本笔记聚焦 xv6 里 ELF 的**头部结构**与**装载过程**。`exec` 本身是系统调用，入口分发见 [Syscall](/docs/CS/OS/xv6/Syscall.md)，装载时用到的 inode 读与地址空间分配分别见 [file](/docs/CS/OS/xv6/file.md) 与 [memory](/docs/CS/OS/xv6/memory.md)。

> 字段宽度：x86 版 ELF 头用 32 位字段，RISC-V 版用 64 位。下面给 RISC-V 版（`uint64`），x86 对应项为 32 位 `uint`。

## ELF 头部

文件头（ELF header）描述整体属性与程序头表位置：

```c
// elf.h（RISC-V，64 位字段）
#define ELF_MAGIC 0x464C457FU  // “\x7FELF” 小端

struct elfhdr {
  uint magic;        // 必须等于 ELF_MAGIC
  uchar elf[12];     // 类别/数据编码/版本等
  ushort type;
  ushort machine;
  uint version;
  uint64 entry;      // 程序入口虚拟地址
  uint64 phoff;      // 程序头表文件偏移
  uint64 shoff;      // 节头表文件偏移
  uint flags;
  ushort ehsize;
  ushort phentsize;
  ushort phnum;      // 程序头数量
  ushort shentsize;
  ushort shnum;
  ushort shstrndx;
};
```

## 程序头（段描述）

每个程序头描述一个"段"在文件中的位置和应被载入内存的位置/大小：

```c
// elf.h
struct proghdr {
  uint type;         // PT_LOAD 表示需要装载
  uint flags;
  uint64 off;        // 段在文件中的偏移
  uint64 vaddr;      // 段应载入的虚拟地址
  uint64 paddr;
  uint64 filesz;     // 文件中字节数
  uint64 memsz;      // 内存中字节数（≥ filesz，多出部分清零，如 .bss）
  uint64 align;
};
```

`bootmain` 读内核 ELF 时用的是同一套结构；用户态 `exec` 装载逻辑与 [Boot](/docs/CS/OS/xv6/Boot.md) 里的内核加载同构，只是目标地址空间换成进程的私有页表。

## exec 装载流程

`exec(path, argv)` 把一个程序映像替换进**当前进程**（不新建进程），大致分五步：

1. **找到 inode**：`namei(path)` 解析路径拿到文件 inode（见 [file](/docs/CS/OS/xv6/file.md)）。
2. **校验 ELF 头**：用 `readi` 读 `sizeof(elfhdr)` 字节，确认 `magic == ELF_MAGIC`。
3. **建页表并装载段**：为进程新建页表，遍历 `phnum` 个程序头，对 `type == PT_LOAD` 的段调用 `uvmalloc` 分配虚拟内存、再用 `loadseg` 把文件内容拷进对应虚拟地址（`filesz` 之后、`memsz` 之前的内存填 0）。
4. **布置用户栈与 argv**：分配一页栈，把 `argv` 字符串与指针数组压栈，并设置 `argc`，使 `sp` 指向栈顶、符合 C 运行时约定。
5. **切换地址空间并设 trapframe**：把新页表挂到进程、释放旧页表，然后把 `trapframe->epc` 设为 `elf.entry`、把 `trapframe->sp` 设为栈顶，返回用户态时即从新程序入口开始执行。

```c
// exec.c（RISC-V，节选）
int
exec(char *path, char **argv)
{
  // ... namei(path) 取得 ip，ilock(ip) ...
  struct elfhdr elf;
  if(readi(ip, 0, (uint64)&elf, 0, sizeof(elf)) != sizeof(elf))
    goto bad;
  if(elf.magic != ELF_MAGIC)
    goto bad;

  // Load program into memory.
  for(i=0, off=elf.phoff; i<elf.phnum; i++, off+=sizeof(ph)){
    if(readi(ip, 0, (uint64)&ph, off, sizeof(ph)) != sizeof(ph))
      goto bad;
    if(ph.type != ELF_PROG_LOAD)
      continue;
    if(ph.memsz < ph.filesz)
      goto bad;
    if((sz1 = uvmalloc(pagetable, sz, ph.vaddr + ph.memsz)) == 0)
      goto bad;
    sz = sz1;
    if(loadseg(pagetable, ph.vaddr, ip, ph.off, ph.filesz) < 0)
      goto bad;
  }

  // ... 分配用户栈、拷贝 argv、设置 sp ...
  // 切换：oldpagetable = p->pagetable; p->pagetable = pagetable;
  //       p->sz = sz; p->trapframe->epc = elf.entry; p->trapframe->sp = sp;
  return 0;

bad:
  // 释放已分配页表，返回 -1
  return -1;
}
```

关键点：`exec` **不返回到原程序**——成功时 `trapframe` 已被改写，用户态恢复后直接跑新程序；失败时回滚并返回 `-1`。`argv` 的布置让用户程序 `main(argc, argv)` 能像普通 C 程序那样拿到参数。

## x86 与 RISC-V 差异

| 维度 | x86 | RISC-V |
| --- | --- | --- |
| 字段位宽 | `uint`（32 位） | `uint64`（64 位） |
| 页表类型 | `pde_t *`（二级页表） | `pagetable_t`（SV39 三级） |
| 地址分配 | `uvmalloc(pgdir, ...)` | `uvmalloc(pagetable, ...)` |

装载的**逻辑完全相同**——校验头、按程序头搬段、建栈、改 `trapframe`——只是页表结构与地址宽度不同（见 [memory](/docs/CS/OS/xv6/memory.md)）。

## Links

- [xv6](/docs/CS/OS/xv6/xv6.md)
- [xv6 启动流程](/docs/CS/OS/xv6/Boot.md)
- [xv6 系统调用](/docs/CS/OS/xv6/Syscall.md)
- [xv6 文件系统](/docs/CS/OS/xv6/file.md)
- [xv6 内存管理](/docs/CS/OS/xv6/memory.md)
- [ELF 通用格式](/docs/CS/Compiler/ELF.md)

## References

1. [xv6 a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.828/2018/xv6/book-rev11.pdf)
2. [ELF Specification (gabi)](https://refspecs.linuxbase.org/elf/elf.pdf)
