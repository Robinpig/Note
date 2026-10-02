## Introduction

这篇笔记整理"**一个可执行文件是怎么被运行起来的**"这一链路上最常用的排查命令：从识别文件类型、查看 ELF 结构，到 shell 如何通过 `execve` 装载。内核侧 execve 的处理见 [进程知识地图](/docs/CS/OS/Linux/proc/README.md)，这里是用户态观察入口。

## 识别文件：file 与 xxd

`file` 通过魔数（magic number）判断类型，而不是扩展名；`xxd` 做十六进制 dump，直接看文件头字节：

```shell
$ file /bin/cat
/bin/cat: ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked,
interpreter /lib64/ld-linux-x86-64.so.2, BuildID[sha1]=..., for GNU/Linux 3.2.0, stripped

$ xxd /bin/cat | less
00000000: 7f45 4c46 0201 0100 0000 0000 0000 0000  .ELF............
```

开头四个字节 `7f 45 4c 46`（`\x7fELF`）就是 ELF 魔数：第 5 字节 01 表示 32 位、02 表示 64 位；第 6 字节 01 小端、02 大端。

## 查看 ELF：readelf / objdump / ldd

- `readelf -h`：ELF 头——入口地址 `Entry point address`、目标架构、程序头/节头表位置；
- `readelf -l`：program header（段视图，装载器用），可以看到 `INTERP` 段指定的动态链接器 `/lib64/ld-linux-x86-64.so.2`；
- `readelf -S`：section header（节视图，链接器用）：`.text` 代码、`.data` 已初始化全局变量、`.bss` 未初始化（不占文件空间）、`.rodata` 只读数据、`.got/.plt` 动态链接跳转；
- `readelf -d`：动态段，记录依赖的共享库（NEEDED）和 RPATH/RUNPATH；
- `readelf -r/-s`：重定位项、符号表（stripped 后 `.symtab` 被移除，但 `.dynsym` 保留）。

```shell
$ readelf -h /bin/cat | grep -E 'Class|Entry|Type'
  Class:                             ELF64
  Type:                              DYN (PIE)
  Entry point address:               0x5f60
$ ldd /bin/cat          # 解析运行时实际加载的 .so 与搜索路径
        libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6
        /lib64/ld-linux-x86-64.so.2
$ objdump -d /bin/cat | less   # 反汇编
```

排障高频场景：启动报 `No such file or directory` 但文件明明存在——往往是 INTERP 指定的动态链接器路径不对（如 32/64 位不匹配）；`version 'GLIBC_2.xx' not found` 用 `readelf -d` + `objdump -T` 查符号版本。

## shell 到进程：execve

shell 执行外部命令时 fork 出子进程，子进程调用 `execve` 用新程序替换自身映像（PID 不变）：

```c
int execve(const char *pathname, char *const argv[], char *const envp[]);
```

内核侧链路（linux/fs/exec.c）：`execve` → 读取 ELF 头识别格式（`linux_binfmt`，还支持脚本 `#!`）→ 清空旧地址空间 → 按 program header 映射 PT_LOAD 段（mmap）→ 设置栈（argc/argv/envp/auxv）→ 把入口点改为 ELF 头里的 `e_entry`（动态链接程序先跳到 ld.so，由它完成 GOT/PLT 重定位后再跳进 main）。

常用观察手段：

```shell
$ strace -f -e trace=execve,openat ./a.out   # 看装载期打开的文件与解释器
$ LD_DEBUG=libs ./a.out                     # 动态链接器打印库搜索全过程
$ ltrace ./a.out                            # 库函数调用
```

注意内建命令（cd/export/read）由 shell 直接执行，不会 fork+execve——这也是 `cd` 必须内建的原因（子进程改工作目录影响不了父 shell）。

## 其他常用二进制工具

| 命令 | 用途 |
|------|------|
| nm | 列符号表（查 undefined symbol） |
| strings | 提取可打印字符串（找内嵌路径/版本） |
| strip | 去符号表减小体积（调试信息分离时） |
| addr2line | 地址 → 源码行（配合 -g） |
| patchelf | 修改 interpreter、RPATH（部署兼容） |
| hexdump/od | 另两种十六进制查看器 |

## Links

- [Linux Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [进程知识地图](/docs/CS/OS/Linux/proc/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [man 5 elf - Linux manual page](https://man7.org/linux/man-pages/man5/elf.5.html)
2. [man 2 execve](https://man7.org/linux/man-pages/man2/execve.2.html)
