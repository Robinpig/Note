## Introduction



go 源代码首先要通过 go build 编译为可执行文件，在 linux 平台上为 ELF 格式的可执行文件，编译阶段会经过编译器、汇编器、链接器三个过程最终生成可执行文件。

1. 编译器：.go 源码通过 go 编译器生成为 .s 的 plan9 汇编代码，Go 编译器入口是 compile/internal/gc/main.go 文件的 main 函数；
2. 汇编器：通过 go 汇编器将编译器生成的 .s 汇编语言转换为机器代码，并写出最终的目标程序 .o 文件，src/cmd/internal/obj 包实现了go汇编器；
3. 链接器：汇编器生成的一个个 *.o 目标文件通过链接处理得到最终的可执行程序，src/cmd/link/internal/ld 包实现了链接器；



两个重要的环境变量分别是 GOPATH 和 GOBIN。

- GOPATH：代表 Go 语言项目的工作目录，在 Go Module 模式之前非常重要，现在基本上用来存放使用 go get 命令获取的项目。
- GOBIN：代表 Go 编译生成的程序的安装目录，比如通过 go install 命令，会把生成的 Go 程序安装到 GOBIN 目录下，以供你在终端使用。

export GOPATH=/Users/flysnow/go export GOBIN=$GOPATH/bin

Go 语言开发工具包的另一强大功能就是可以跨平台编译

Go 语言通过两个环境变量来控制跨平台编译，它们分别是 GOOS 和 GOARCH 。

- GOOS：代表要编译的目标操作系统，常见的有 Linux、Windows、Darwin 等。
- GOARCH：代表要编译的目标处理器架构，常见的有 386、AMD64、ARM64 等。

可以通过 `go tool dist list` 查看支持的 GOOS、GOARCH 可选值

通过组合不同的 GOOS 和 GOARCH，就可以编译出不同的可执行程序

```shell
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build
```

可以通过 `-x` 和 `--work` 查看编译的详细过程



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





执行go build 命令时候，带上 `-n` 选项可以观察编译流程所执行所有的命令
从上面命令输出的内容可以看到：
1. Go编译器首先会创建一个任务输出临时目录（mkdir -p $WORK/b001/）。b001是root task的工作目录，每次构建都是由一系列task完成，它们构成 action graph
2. 接着将依赖的包: /usr/lib/go/pkg/linux_amd64/runtime.a 写入到 `importcfg` 中
3. 接着会使用compile命令，并指定importcfg文件，将主程序empty_string.go编译成_pkg.a文件（/usr/lib/go/pkg/tool/linux_amd64/compile -o $WORK/b001/pkg.a -trimpath “$WORK/b001=>” -p main -complete -buildid aJhlsTb17ElgWQeF76b5/aJhlsTb17ElgWQeF76b5 -goversion go1.14.13 -D _/home/vagrant/dive-into-go -importcfg $WORK/b001/importcfg -pack ./empty_string.go）。
4. 程序依赖的包都写到importcfg.link这个文件中，Go编译器连接阶段中链接器会使用该文件，找到所有依赖的包文件，将其连接到程序中（/usr/lib/go/pkg/tool/linux_amd64/link -o $WORK/b001/exe/a.out -importcfg $WORK/b001/importcfg.link -buildmode=exe -buildid=FoylCipvV-SPkhyi2PJs/aJhlsTb17ElgWQeF76b5/aJhlsTb17ElgWQeF76b5/FoylCipvV-SPkhyi2PJs -extld=gcc $WORK/b001/pkg.a /usr/lib/go/pkg/tool/linux_amd64/buildid -w $WORK/b001/exe/a.out # internal）。
5. 将编译成功的二进制文件移动到输出目录中（mv $WORK/b001/exe/a.out empty_string）。


为了详细查看go build整个详细过程，我们可以使用go build -work -a -p 1 -x empty_string.go命令来观察整个过程，它比go build -n提供了更详细的信息:
- -work选项指示编译器编译完成后保留编译临时工作目录
- -a选项强制编译所有包。我们使用go build -n时候，只看到main包编译过程，这是因为其他包已经编译过了，不会再编译。我们可以使用这个选项强制编译所有包。
- -p选项用来指定编译过程中线程数，这里指定为1，是为观察编译的顺序性
- -x选项可以指定编译参数


b001目录用于main包编译 是任务图的root节点

自举，英文名称是Bootstrapping。自举指的是用要编译的程序的编程语言来编写其编译器
Go语言最开始是使用C语言实现的编译器，go1.4是最后一个C语言实现的编译器版本。
自go1.5开始，Go实现了自举功能，go1.5的gc是由go语言实现的，它是由go1.4版本的C语言实现编译器编译出来的，详细内容可以参见Go 自举的设计文档： Go 1.3+ Compiler Overhaul。

除了 Go 语言实现的 gc 外，Go 官方还维护了一个基于 gcc 实现的 Go 编译器 gccgo。与 gc 相比，gccgo 编译代码较慢，但支持更强大的优化，因此由 gccgo 构建的 CPU 密集型(CPU-bound)程序通常会运行得更快。
此外 gccgo 比 gc 支持更多的操作系统，如果交叉编译gc不支持的操作系统，可以考虑使用gccgo




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


## AST

在Go语言源文件中的任何一种import、type、const、func声明都是一个根节点，在根节点下包含当前声明的子节点。
如下decls函数将源文件中的所有声明语句转换为节点（Node）数组。核心逻辑位于gc/noder.go中
每个节点都包含了当前节点属性的Op字段，定义在gc/syntax.go中，以O开头。与词法解析阶段中的token相同的是，Op字段也是一个整数。不同的是，每个Op字段都包含了语义信息



闭包变量捕获的核心逻辑位于gc/closure.go的capturevars函数中 


函数内联指将较小的函数直接组合进调用者的函数。这是现代编译器优化的一种核心技术。函数内联的优势在于，可以减少函数调用带来的开销。
对于Go语言来说，函数调用的成本在于参数与返回值栈复制、较小的栈寄存器开销以及函数序言部分的检查栈扩容（Go语言中的栈是可以动态扩容的）
同时，函数内联是其他编译器优化（例如无效代码消除）的基础。我们可以通过一段简单的程序衡量函数内联带来的效率提升[3]
，如下所示，使用bench对max函数调用进行测试。当我们在函数的注释前方加上//go：noinline时，代表当前函数是禁止进行函数内联优化的。取消该注释后，max函数将会对其进行内联优化

Go语言编译器会计算函数内联花费的成本，只有执行相对简单的函数时才会内联。函数内联的核心逻辑位于gc/inl.go中。当函数内部有for、range、go、select等语句时，该函数不会被内联，当函数执行过于复杂（例如太多的语句或者函数为递归函数）时，也不会执行内

如果希望程序中所有的函数都不执行内联操作，那么可以添加编译器选项-l 
在调试时，可以获取当前函数是否可以内联，以及不可以内联的原因 

## escape

逃逸分析是Go语言中重要的优化阶段，用于标识变量内存应该被分配在栈区还是堆区。
在传统的C或C++语言中，开发者经常会犯的错误是函数返回了一个栈上的对象指针，在函数执行完成，栈被销毁后，继续访问被销毁栈上的对象指针，导致出现问题。
Go语言能够通过编译时的逃逸分析识别这种问题，自动将该变量放置到堆区，并借助Go运行时的垃圾回收机制自动释放内存。
编译器会尽可能地将变量放置到栈中，因为栈中的对象随着函数调用结束会被自动销毁，减轻运行时分配和垃圾回收的负担。
在Go语言中，开发者模糊了栈区与堆区的差别，不管是字符串、数组字面量，还是通过new、make标识符创建的对象，都既可能被分配到栈中，也可能被分配到堆中。
分配时，遵循以下两个原则：
- 原则1：指向栈上对象的指针不能被存储到堆中
- 原则2：指向栈上对象的指针不能超过该栈对象的生命周期

Go语言通过对抽象语法树的静态数据流分析（static data-flow analysis）来实现逃逸分析，这种方式构建了带权重的有向图。 



在前面的阶段，编译器完成了闭包变量的捕获用于决定是通过指针引用还是值引用的方式传递外部变量。
在完成逃逸分析后，下一个优化的阶段为闭包重写，其核心逻辑位于gc/closure.go中。
闭包重写分为闭包定义后被立即调用和闭包定义后不被立即调用两种情况。在闭包被立即调用的情况下，闭包只能被调用一次，这时可以将闭包转换为普通函数的调用形式。
如果闭包定义后不被立即调用，而是后续调用，那么同一个闭包可能被调用多次，这时需要创建闭包对象。
如果变量是按值引用的，并且该变量占用的存储空间小于2×sizeof（int），那么通过在函数体内创建局部变量的形式来产生该变量。
如果变量通过指针或值引用，但是占用存储空间较大，那么捕获的变量（var）转换成指针类型的&var。这两种方式都需要在函数序言阶段将变量初始化为捕获变量的值


闭包重写后，需要遍历函数，其逻辑在gc/walk.go文件的walk函数中。
在该阶段会识别出声明但是并未被使用的变量，遍历函数中的声明和表达式，将某些代表操作的节点转换为运行时的具体函数执行。
例如，获取map中的值会被转换为运行时mapaccess2_fast64函数（详见第8章）。



在执行walk函数遍历之前，编译器还需要对某些表达式和语句进行重新排序，例如将x/=y替换为x=x/y。
根据需要引入临时变量，以确保形式简单，例如x=m[k]或m[k]=x，而k可以寻址。



## SSA

SSA生成阶段是编译器进行后续优化的保证，例如常量传播（Constant Propagation）、无效代码清除、消除冗余、强度降低（Strength Reduction）等。
大部分与SSA相关的代码位于ssa/文件夹中，但是将抽象语法树转换为SSA的逻辑位于gc/ssa.go文件中。在ssa/README.md文件中，有对SSA生成阶段比较详细的描述。
Go语言提供了强有力的工具查看SSA初始及其后续优化阶段生成的代码片段，可以通过在编译时指定GOSSAFUNC=main实现


`go build -gcflags -S main.go` 查看 Plan9 汇编代码





## Links


## References

