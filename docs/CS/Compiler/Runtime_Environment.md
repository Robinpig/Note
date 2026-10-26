# Runtime Environment

## Introduction

编译器不只是翻译指令，它还要为运行期搭建整套契约：变量存在哪、过程怎么调用与返回、名字在运行时如何解析、程序如何与操作系统交互。
这些决策大部分在**代码生成期**定型，运行期只是忠实地执行编译器选定的方案。

本页按龙书的组织方式展开：存储组织 → 过程调用 → 栈帧细节 → 作用域的非局部访问 → 与 [memory](/docs/CS/memory/memory.md) 的堆管理衔接。

## Storage Organization

从编译器视角，目标程序独占自己的逻辑地址空间：

| 区域 | 内容 | 分配时机 |
| :--- | :--- | :--- |
| 代码区 | 目标代码 | 编译/加载期 |
| 静态数据区 | 全局量、常量、字符串字面量 | 编译期定址 |
| 栈 | 活动记录、局部量 | 过程入口/出口动态伸缩 |
| 堆 | 动态分配对象 | 运行时分配器管理 |

操作系统把逻辑地址映射到物理地址；对编译器而言，"每个值有逻辑地址"是它唯一的假设。
静态区的地址可在编译期算出绝对位置；栈上对象的地址依赖运行时的帧指针；堆上对象只有分配后才知道位置。

## Procedure Calls and Activation Records

过程调用是运行期最频繁的控制转移，编译器为每次调用生成**活动记录**（activation record，即栈帧）：

```
┌─────────────────────┐  ← 高地址
│   返回地址/帧信息     │
│   参数与返回值位置     │
│   被调用者保存寄存器   │
│   局部变量与临时量     │
│   已计算的定值         │
└─────────────────────┘  ← sp
```

调用序列（call sequence）由编译器按 ABI 展开：

1. **调用者**：实参入栈或入寄存器 → 保存调用者保存寄存器 → `call`；
2. **被调用者**：压返回地址 → 保存帧指针 → 建新帧 → 保存被调用者保存寄存器 → 执行 → 恢复 → 返回；
3. **调用者**：取返回值 → 清理实参 → 继续。

调用约定的具体形态（寄存器参数上限、栈对齐、哪些寄存器 volatile）见 [Calling_Conventions](/docs/CS/assembly/Calling_Convention.md)，编译器必须与目标平台 ABI 逐字节对齐。

## Stack Frame Details

帧指针（frame pointer）链让调试与栈回溯成为可能：每个帧保存调用者的帧指针，逆链而上可重建整个调用栈——`perf`、`gdb` 的 backtrace 正是读这条链。
`-fomit-frame-pointer` 省掉一个寄存器，但破坏 unwinding，调试与采样剖析场景必须关闭。

### Parameter Passing

| 模式 | 语义 | 使用者 |
| :--- | :--- | :--- |
| 值传递 | 实参拷贝 | C、Java 基本类型 |
| 引用传递 | 形参绑定实参地址 | C++ `&`、Pascal `var` |
| 结果传递 | 返回值拷回实参 | 少数语言 |
| 名传递 | 每次出现都重新求值 | Algol 60 |

### Nested Scopes and Non-local Access

词法作用域的嵌套带来非局部访问问题：内层过程引用外层过程的局部量。
两种经典方案：

- **静态链**（static link）：每个帧指向词法外层帧，访问外层量沿链走 n 步；
- **display**：维护一个数组，第 i 项指向当前词法第 i 层的帧，访问 O(1)，进/出层维护数组。

Pascal 用前者，效率换简洁；现代语言大多回避深层嵌套，C++ lambda 捕获的正是外层栈帧（或堆上闭包环境）。

### Closures and Continuations

函数作为一等公民时，"代码 + 环境"必须打包：闭包在堆上分配环境记录，函数退出后环境仍存活。
尾调用优化（tail-call optimization）是运行期契约的另一面：尾位置调用复用当前帧， Scheme 靠它实现无界循环，C/C++ 编译器按需开启。

## Heap and Garbage Collection

编译器只负责生成"申请内存"的调用，真正管理堆的是分配器与运行时：

- **显式管理**：C/C++ 的 `malloc`/`free`，编译器保证 ABI 匹配，生命周期由程序员维护；
- **自动管理**：GC 语言（Java、Go）由运行时回收，编译器侧配合的是逃逸分析与写屏障插入；
- **分代假说**：多数对象朝生夕死 → 新生代小、老年代大，minor GC 极快。

堆分配器与 GC 的完整机制见 [GC](/docs/CS/memory/GC.md) 与 [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)。

## Links

- [Compiler](/docs/CS/Compiler/Compiler.md)
- [Code Generation](/docs/CS/Compiler/Code_Generation.md)
- [Calling_Conventions](/docs/CS/assembly/Calling_Convention.md)
- [GC](/docs/CS/memory/GC.md)
- [glibc](/docs/CS/C/glibc.md)

## References

1. [System V Application Binary Interface — x86-64](https://gitlab.com/x86-psABIs/x86-64-ABI)
2. [Itanium C++ ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi.html)
