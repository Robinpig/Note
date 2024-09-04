## Introduction



code in `src/cmd/compile/internal/`

- Lexical Analysis
- Syntax Analysis
- generate Abstract Syntax Tree
- type check
- relationship
- inline method
- escape analysis
- closure override
- iterate method
- generate SSA
- generate machine code



compiler不允许出现未使用的变量和导入包

## Lexical Analysis

扫描文件将其token化 例如 操作符 +/- -> _IncOp, 赋值符:= -> _Define

标准库里go/scanner go/token提供了接口用于扫描源代码

## Syntax Analysis

Go语言采用了标准的自上而下的递归下降（Top-Down Recursive-Descent）算法，以简单高效的方式完成无须回溯的语法扫描，核心算法位于syntax/nodes.go及syntax/parser.go中

源文件中的每一种声明都有对应的语法，递归下降通过识别初始的标识符，例如_const，采用对应的语法进行解析
这种方式能够较快地解析并识别可能出现的语法错误。每一种声明语法在Go语言规范中都有定义



逃逸分析是Go语言中重要的优化阶段，用于标识变量内存应该被分配在栈区还是堆区。
在传统的C或C++语言中，开发者经常会犯的错误是函数返回了一个栈上的对象指针，在函数执行完成，栈被销毁后，继续访问被销毁栈上的对象指针，导致出现问题。
Go语言能够通过编译时的逃逸分析识别这种问题，自动将该变量放置到堆区，并借助Go运行时的垃圾回收机制自动释放内存。编译器会尽可能地将变量放置到栈中，
因为栈中的对象随着函数调用结束会被自动销毁，减轻运行时分配和垃圾回收的负担

在Go语言中，开发者模糊了栈区与堆区的差别，不管是字符串、数组字面量，还是通过new、make标识符创建的对象，都既可能被分配到栈中，也可能被分配到堆中
分配时，遵循以下两个原则
- 原则1：指向栈上对象的指针不能被存储到堆中
- 原则2：指向栈上对象的指针不能超过该栈对象的生命周期

Go语言通过对抽象语法树的静态数据流分析（static data-flow analysis）来实现逃逸分析，这种方式构建了带权重的有向图



## SSA
SSA生成阶段是编译器进行后续优化的保证，例如常量传播（Constant Propagation）、无效代码清除、消除冗余、强度降低（Strength Reduction）等。
大部分与SSA相关的代码位于ssa/文件夹中，但是将抽象语法树转换为SSA的逻辑位于gc/ssa.go文件中。在ssa/README.md文件中，有对SSA生成阶段比较详细的描述。
Go语言提供了强有力的工具查看SSA初始及其后续优化阶段生成的代码片段，可以通过在编译时指定GOSSAFUNC=main实现



## Links


## References

