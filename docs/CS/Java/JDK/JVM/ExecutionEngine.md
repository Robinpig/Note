## Introduction

Once the bytecode has been loaded into the main memory, and details are available in the runtime data area, the next step is to run the program. 
The Execution Engine handles this by executing the code present in each class.

However, before executing the program, the bytecode needs to be converted into machine language instructions.
The JVM can use an interpreter or a JIT compiler for the execution engine.

Interpreter

The interpreter reads and executes the bytecode instructions line by line. Due to the line by line execution, the interpreter is comparatively slower.
Another disadvantage of the interpreter is that when a method is called multiple times, every time a new interpretation is required.


JIT Compiler

The JIT Compiler overcomes the disadvantage of the interpreter. 
The Execution Engine first uses the interpreter to execute the byte code, but when it finds some repeated code, it uses the JIT compiler.

The JIT compiler then compiles the entire bytecode and changes it to native machine code.
This native machine code is used directly for repeated method calls, which improves the performance of the system.

The JIT Compiler has the following components:

- Intermediate Code Generator - generates intermediate code
- Code Optimizer - optimizes the intermediate code for better performance
- Target Code Generator - converts intermediate code to native machine code
- Profiler - finds the hotspots (code that is executed repeatedly)

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
