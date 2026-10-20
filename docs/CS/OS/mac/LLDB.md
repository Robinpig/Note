## Introduction

[LLDB]（https://lldb.llvm.org/index.html）is a next generation, high-performance debugger. It is built as a set of reusable components which highly leverage existing libraries in the larger LLVM Project, such as the Clang expression parser and LLVM disassembler.

LLDB is the default debugger in Xcode on macOS and supports debugging C, Objective-C and C++ on the desktop and iOS devices and simulator

For users already familiar with [GDB](/docs/CS/C/GDB.md) there is a cheat sheet listing common tasks and their LLDB equivalent in the [GDB to LLDB command map](https://lldb.llvm.org/use/map.html).









Xcode 自带的 LLDB 与命令行 `lldb` 是同一套（见 [Development](/docs/CS/OS/mac/Development.md)），区别在于前者带 IDE 集成与可视化。调试系统进程或需要内核符号时，[SIP](/docs/CS/OS/mac/Security.md) 与 KDK 是两个前置条件：前者决定能不能附加（attach）到受保护进程，后者决定能不能拿到内核符号。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Development](/docs/CS/OS/mac/Development.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)
- [GDB](/docs/CS/C/GDB.md)

## References

1. [LLDB调试器使用简介 | 南峰子的技术博客 (southpeak.github.io)](https://southpeak.github.io/2015/01/25/tool-lldb/)
