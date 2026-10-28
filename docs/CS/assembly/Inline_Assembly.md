## Introduction

实际工程里写的汇编，绝大多数不是独立的 `.s` 文件，而是**嵌在高级语言里的一小段**：读一个时间戳计数器、发一条特殊指令、给热点循环手写一段 SIMD。形式有三种——GCC/Clang 的扩展 `asm`、Rust 的 `asm!` 宏家族、以及 MSVC 的 intrinsic 路线。

内联汇编的危险之处在于**编译器不知道你改了什么**。它不是黑盒函数调用，而是被内联展开的一段指令流，寄存器分配、指令调度、甚至是否执行都由编译器决定。漏一个 clobber 声明，代码在 `-O0` 下正确、`-O2` 下偶发算错。调用约定见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)。

## GCC and Clang Extended Asm

扩展 asm 的完整形态：

```c
asm [volatile] [goto] ( 汇编模板
    : 输出操作数
    : 输入操作数
    : 破坏列表
    : 跳转标签        // 仅 asm goto
);
```

四段冒号，任一段可以为空但不能省掉中间的冒号。几个要点：

**操作数与编号**：`%0`、`%1` 按出现顺序编号（输出在前，输入在后）。给操作数起名字更好读：

```c
static inline uint64_t rdtsc(void) {
    uint32_t lo, hi;
    asm volatile ("rdtsc"
        : "=a" (lo), "=d" (hi)      // eax → lo, edx → hi
    );
    return ((uint64_t)hi << 32) | lo;
}
```

```c
// 命名写法，模板里用 %[name]
asm ("add %[src], %[dst]"
    : [dst] "+r" (a)
    : [src] "r" (b)
);
```

**约束字母**（常用部分）：

| 约束 | 含义 |
|------|------|
| `r` | 任意通用寄存器 |
| `m` | 内存操作数 |
| `g` | 寄存器、内存或立即数 |
| `i` / `n` | 立即数（`n` 要求已知数值常量） |
| `a`/`b`/`c`/`d`/`S`/`D` | 指定 `rax`/`rbx`/`rcx`/`rdx`/`rsi`/`rdi` |
| `q` | 任意可字节寻址的寄存器（x86 上避开 `rbp` 等） |
| `f`/`t`/`u` | x87 栈寄存器 |
| `x`/`y` | SSE / MMX 寄存器 |
| `0`/`1`… | 与第 N 个操作数用同一个位置（输入复用输出槽） |
| `+r` | 读写（in-out），区别于 `=r` 的只写 |
| `=&r` | **early clobber**：该输出在输入被消费**之前**就被写入 |

`=&` 是最容易漏、后果最难查的一个。考虑：

```c
asm ("mov %[in], %[out]\n\t"
     "add $1, %[out]"
    : [out] "=r" (result)
    : [in] "r" (input)
);
```

编译器完全可能给 `out` 和 `in` 分配**同一个寄存器**——因为没有声明冲突，它认为先读后写是安全的。如果汇编模板实际是先写后读（比如先 `mov` 常量到输出再读输入），就必须写 `=&r` 明确"这个输出会提前破坏"。

**volatile 与破坏列表**：

- `asm volatile`：告诉编译器这段有副作用，**不要**因为输出没被使用就删掉，也不要移出循环。读 `rdtsc`、写设备寄存器、做内存屏障都必须 `volatile`。注意它**不保证**指令顺序不被调度——那要靠 `memory` clobber。
- `: "memory"`：告诉编译器汇编会读写内存，编译器必须在此之前把缓存在寄存器里的值写回、之后重新加载。实现自旋锁、原子操作、或者任何与并发相关的东西，漏掉 `memory` 就是数据竞争。
- `: "cc"`：声明标志位被破坏。x86 目标上 GCC 默认假定 asm 修改了标志位，通常不用显式写。
- 未声明的寄存器破坏：如果模板里用了 `rbx` 却没列入 clobber，编译器会认为 `rbx` 保持原值——这是最经典的内联 asm bug。

```c
// 正确的完整例子：带 early clobber、volatile、memory
static inline void cpu_relax(void) {
    asm volatile ("pause" ::: "memory");
}
```

**asm goto**：让汇编跳到 C 标签（GCC 4.5+，Clang 也有支持）。内核里的 `unlikely` 分支、以及需要把条件码直接转成 C 控制流的场景用它：

```c
asm goto ("test %0, %0\n\t"
          "jz %l[zero]"
          : /* no outputs */
          : "r" (x)
          : "cc"
          : zero);
return 1;
zero:
    return 0;
```

`asm goto` 不能有输出操作数（这是限制，也是它能与跳转融合的前提）。

## Rust Inline Assembly

Rust 在 **1.59.0**（2022-02-24）稳定了 `asm!` 与 `global_asm!`，覆盖 x86、x86-64、ARM、AArch64、RISC-V；**1.88.0**（2025-06-26）稳定了 `#[unsafe(naked)]` 与 `naked_asm!`。

```rust
use std::arch::asm;

let mut x: u64 = 4;
unsafe {
    asm!(
        "mov {tmp}, {x}",
        "shl {tmp}, 1",
        "shl {x}, 2",
        "add {x}, {tmp}",
        x = inout(reg) x,
        tmp = out(reg) _,
    );
}
```

与 GCC 的对应关系：

| GCC | Rust `asm!` |
|-----|-------------|
| `"=r"(a)` | `a = out(reg) a` |
| `"+r"(a)` | `a = inout(reg) a` |
| `"r"(a)` | `a = in(reg) a` |
| `"0"(a)` | `in(reg) a` 配合 `inout` |
| `:&r` early clobber | `out(reg) a` 默认即为 early clobber（Rust 语义如此） |
| `volatile` | `options(nostack, nomem, preserves_flags)` 反过来声明"没有副作用"——Rust 默认视为有副作用 |
| `"memory"` | 默认声明破坏内存，可用 `options(nomem)` 放松 |

Rust 的 `asm!` 默认是保守的（假定破坏内存与标志），靠 `options(nomem)` / `options(preserves_flags)` 显式放松，这跟 GCC 的"默认乐观、靠声明收紧"方向相反——从 C 迁过来的人容易搞反。

**`global_asm!`** 用于写在模块顶层的裸汇编（`.section`、`.globl` 都要自己写）；**`naked_asm!`** 配合 `#[unsafe(naked)]` 定义**裸函数**：整个函数体就是手写指令，编译器不加 prologue/epilogue：

```rust
#[unsafe(naked)]
pub unsafe extern "sysv64" fn wrapping_add(a: u64, b: u64) -> u64 {
    // SAFETY: 遵守 System-V ABI，参数在 rdi/rsi，返回值在 rax
    core::arch::naked_asm!("lea rax, [rdi + rsi]", "ret");
}
```

相比 `global_asm!`，裸函数的好处是：自动发出各目标文件格式需要的伪指令、参与 Rust 的名字修饰（不会符号冲突）、可以用常量泛型。

> [!WARNING]
> 一个实测到的坑：**`--emit=metadata` 不校验汇编串**，也就是说 `cargo check` 发现不了内联汇编的语法错误——往 `global_asm!` 里塞一句彻底非法的汇编，`cargo check` 干净通过，只有真正产出目标文件（`--emit=obj`，即 `cargo build`）才报 `unexpected token in argument list`。另外裸函数体内不允许用 `asm!`，编译器会报 `E0787` 并建议改用 `naked_asm!`。

## MSVC and Intrinsics

MSVC 在 x64 下**不支持内联汇编**（`__asm` 只在 32 位可用）。Windows 上的做法有三条：

1. 用编译器 intrinsic（`<intrin.h>`），覆盖绝大多数需求（`__rdtsc`、`_mm_*` 系列、`_Interlocked*`）；
2. 单独的 `.asm` 文件用 `ml64.exe` 汇编后一起链接；
3. 用 Clang-cl，它支持 GCC 风格的内联 asm。

intrinsic 与内联 asm 的取舍很明确：**能用 intrinsic 就用 intrinsic**。编译器知道 intrinsic 的语义（能调度、能分配寄存器、能常量折叠），而内联 asm 对它是不透明的黑盒，会阻断优化。

## When Not to Use Inline Assembly

内联汇编的合理场景其实很窄：

- 编译器没有对应 intrinsic 的指令（`rdtscp`、`swapgs`、特定的 MSR 访问）；
- 需要精确指令序列且不希望被调度打散（基准测试、安全边界）；
- 极小的热点内核，且已确认编译器生成的代码明显更差；
- 启动代码、上下文切换这类 C 无法表达的场合（那通常直接写成 `.S` 文件而不是内联）。

不该用的场景：为了"更快"而手写——现代编译器在寄存器分配、指令选择、循环展开上的决策通常优于手写，而且内联 asm 会**阻断**常量传播与向量化。正确顺序是：先写自然的 C，看生成的汇编，确认编译器确实做错了，再考虑 intrinsic，最后才是内联 asm。判断方法见 [惯用法与优化](/docs/CS/assembly/Optimization_and_Idioms.md)。

## Common Bugs

1. **漏 clobber**：模板用了没声明的寄存器 → 该寄存器的值被静默破坏。
2. **缺 `volatile`**：输出未使用 → 整段被删掉；或者在循环里被外提，语义变成"只执行一次"。
3. **缺 `"memory"`**：并发代码里表现为偶发读到旧值。
4. **缺 early clobber**：输出与输入被分配同一寄存器。
5. **用 `r` 约束却要求特定寄存器**：需要 `rdx:rax` 这种隐式操作数的指令（`mul`/`div`）必须用 `a`/`d` 显式约束，不能指望编译器碰巧选对。
6. **在内联 asm 里改栈指针**：编译器会假定 `rsp` 不变，除非你非常清楚自己在做什么（并且声明了 `nostack` 之类）。
7. **跨语言的 ABI 假设**：内联 asm 里调用 C 函数必须自己遵守调用约定，还要考虑内联 asm 不保证生成栈帧。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)
- [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)
- [惯用法与优化](/docs/CS/assembly/Optimization_and_Idioms.md)
- [Rust 宏（naked_asm 与内联汇编实测）](/docs/CS/Rust/Macros.md)

## References

1. [GCC — Using Assembly Language with C](https://gcc.gnu.org/onlinedocs/gcc/Using-Assembly-Language-with-C.html)
2. [GCC — Extended Asm（含约束与 clobber 完整说明）](https://gcc.gnu.org/onlinedocs/gcc/Extended-Asm.html)
3. [Rust Reference — Inline Assembly](https://doc.rust-lang.org/reference/inline-assembly.html)
4. [Announcing Rust 1.59.0（asm! 稳定）](https://blog.rust-lang.org/2022/02/24/Rust-1.59.0)
5. [Stabilizing naked functions（Rust 1.88.0）](https://blog.rust-lang.org/2025/07/03/stabilizing-naked-functions)
6. [Microsoft — Inline assembler (x86 only)](https://learn.microsoft.com/en-us/cpp/assembler/inline/inline-assembler)
