## Introduction

一旦字节码加载到主内存中，并且在运行时数据区中可获得详细信息，下一步就是运行程序。
Execution Engine 通过执行每个类中的代码来处理。

然而，在执行程序之前，需要将字节码转换为机器语言指令。
JVM 可以使用解释器或 JIT 编译器作为执行引擎。

解释器（Interpreter）

解释器逐行读取并执行字节码指令。由于逐行执行，解释器相对较慢。
解释器的另一个缺点是，当一个方法被多次调用时，每次都需要重新解释。

JIT 编译器

JIT 编译器克服了解释器的缺点。
Execution Engine 首先使用解释器执行字节码，但当发现重复代码时，它会使用 JIT 编译器。

JIT 编译器随后编译整个字节码并将其转换为本地机器码。
这种本地机器码直接用于重复的方法调用，从而提高了系统性能。

JIT 编译器包含以下组件：

- Intermediate Code Generator - 生成中间代码
- Code Optimizer - 优化中间代码以获得更好的性能
- Target Code Generator - 将中间代码转换为本地机器码
- Profiler - 发现热点（重复执行的代码）

```
-Xint only interceptor
-Xcomp use interceptor only if compiler not execute some codes
-Xmixed default
```

On Stack Replacement

- Invocation Counter -- for call method
- Back Edge Counter -- for code in loop

```
CompileThreshold                          = 10000
BackEdgeThreshold                         = 100000
OnStackReplacePercentage                  = 140
```

count will decr by time

```
UseCounterDecay                           = true
```

compile hot code async

```
BackgroundCompilation                     = true
```

calc InterpreterBackwardBranchLimit beacuse of Hotspot may not use BackEdgeThreshold

```cpp
// invocationCounter.cpp

void InvocationCounter::reinitialize(bool delay_overflow) {
  // define states
  guarantee((int)number_of_states <= (int)state_limit, "adjust number_of_state_bits");
  def(wait_for_nothing, 0, do_nothing);
  if (delay_overflow) {
    def(wait_for_compile, 0, do_decay);
  } else {
    def(wait_for_compile, 0, dummy_invocation_counter_overflow);
  }

  InterpreterInvocationLimit = CompileThreshold << number_of_noncount_bits;
  InterpreterProfileLimit = ((CompileThreshold * InterpreterProfilePercentage) / 100)<< number_of_noncount_bits;

  // When methodData is collected, the backward branch limit is compared against a
  // methodData counter, rather than an InvocationCounter.  In the former case, we
  // don't need the shift by number_of_noncount_bits, but we do need to adjust
  // the factor by which we scale the threshold.
  if (ProfileInterpreter) {
    InterpreterBackwardBranchLimit = (int)((int64_t)CompileThreshold * (OnStackReplacePercentage - InterpreterProfilePercentage) / 100);
  } else {
    InterpreterBackwardBranchLimit = (int)(((int64_t)CompileThreshold * OnStackReplacePercentage / 100) << number_of_noncount_bits);
  }

  assert(0 <= InterpreterBackwardBranchLimit,
         "OSR threshold should be non-negative");
  assert(0 <= InterpreterProfileLimit &&
         InterpreterProfileLimit <= InterpreterInvocationLimit,
         "profile threshold should be less than the compilation threshold "
         "and non-negative");
}
```

Interceptor

Code

Code Cache

CodeCacheExpansionSize                    = 65536
CodeCacheMinimumFreeSpace                 = 512000
InitialCodeCacheSize                      = 2555904
PrintCodeCache                            = false
PrintCodeCacheOnCompilation               = false
ReservedCodeCacheSize                     = 251658240
UseCodeCacheFlushing                      = true

## JIT

1. c1
2. opto(c2)

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
