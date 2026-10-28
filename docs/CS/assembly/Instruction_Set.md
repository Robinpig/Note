## Introduction

x86-64 的指令集是几十年向后兼容叠出来的：8086 的 16 位指令、IA-32 的扩展、MMX/SSE/AVX 的向量、64 位模式的 REX 前缀，全都还在。所以"指令集"不是一个整齐的清单，而是一堆功能组，每组里既有常用核心也有历史遗留。

本页按功能分组讲常用指令与 x86 的硬约束。语法差异见 [语法与伪指令](/docs/CS/assembly/Syntax_and_Directives.md)，操作数能放哪见 [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)，向量指令的体系性介绍见 [数据并行与加速器](/docs/CS/CO/simd.md)。

## Data Movement

```asm
mov   rax, rbx            ; 寄存器 → 寄存器
mov   rax, [rbx]          ; 内存 → 寄存器
mov   [rbx], rax          ; 寄存器 → 内存
mov   qword [rbx], 1      ; 立即数 → 内存（NASM 必须写宽度）
```

**`mov` 不能内存到内存。** 想复制内存必须借一个寄存器，这是 x86 最重要的编码约束（源自 ModRM 只允许一个内存操作数）。`memcpy` 在汇编里因此是"load 一批 → store 一批"的循环。

宽度不匹配的传送要靠 `movzx`（零扩展）与 `movsx`/`movsxd`（符号扩展）：

```asm
movzx eax, byte [rbx]     ; unsigned char → int，高 24 位清零
movsx eax, byte [rbx]     ; signed char → int，符号位扩展到高 24 位
movsxd rax, dword [rbx]   ; int → long，32 位符号扩展到 64 位
```

`lea` 也归在这一组——它算地址但不访存，因此是最灵活的算术指令（见 [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)）。

交换与条件传送：

```asm
xchg  rax, rbx            ; 交换；带内存操作数时隐含 lock 语义（原子但慢）
cmove rax, rbx            ; ZF=1 时 rax = rbx，不跳转、不预测失败
setne al                  ; ZF=0 时 al = 1，否则 al = 0
```

`cmovcc` 与 `setcc` 是**消除分支**的主要手段：短分支预测失败的代价通常远大于一条 `cmov`。但 `cmov` 会无条件计算两个源操作数，源里有副作用或可能陷入（比如除法、空指针解引用）时不能用。

## Arithmetic and Flags

```asm
add   rax, rbx            ; rax += rbx，写 CF/ZF/SF/OF/PF/AF
sub   rax, rbx
adc   rax, rbx            ; 带进位加（大整数运算）
sbb   rax, rbx            ; 带借位减
neg   rax
cmp   rax, rbx            ; 只写标志位，不写目标（就是 sub 但不保存结果）
test  rax, rax            ; 按位与，只写标志位；判零/判符号的惯用法
```

`cmp` 与 `test` 是"比较但不保存"，后面必然跟一条读标志位的指令（`jcc`/`setcc`/`cmovcc`）。

**标志位**（`rflags` 的低位）：

| 标志 | 含义 | 典型用途 |
|------|------|---------|
| `ZF` | 结果为零 | `je`/`jne`；`test rax,rax` 后判零 |
| `CF` | 无符号溢出/借位 | `ja`/`jb`；多精度加法进位 |
| `SF` | 结果为负（最高位） | `js`/`jns` |
| `OF` | 有符号溢出 | `jo`/`jno` |
| `PF` | 低 8 位含偶数个 1 | 历史遗留（浮点比较），几乎不用 |
| `AF` | 低 4 位进位 | BCD 运算，历史遗留 |
| `DF` | 方向标志 | 串指令 `movs`/`stos` 的增减方向 |

**有符号与无符号的条件跳转不是同一批指令**——`cmp` 不区分符号，区分符号的是后面的 `jcc`：无符号用 `ja`（above）/`jb`（below），有符号用 `jg`（greater）/`jl`（less）。写反了在边界情况下才暴露，是经典 bug。

乘法与除法有隐式操作数，这是 x86 的 CISC 遗风：

```asm
mul   rcx                 ; rdx:rax = rax * rcx（无符号，128 位结果）
imul  rcx                 ; 单操作数：同 mul，有符号
imul  rax, rcx            ; 双操作数：rax = rax * rcx（只留 64 位）
imul  rax, rcx, 3         ; 三操作数：rax = rcx * 3（最常用，无隐式操作数）
cqo                       ; rax 符号扩展到 rdx:rax（idiv 前必做）
idiv  rcx                 ; rax = rdx:rax / rcx，rdx = 余数
```

要点：除法前**必须**把 `rdx` 设成 `rax` 的符号扩展（`cqo`），否则结果是错的（不是报错）；无符号除法用 `xor rdx, rdx` 先清零。三操作数 `imul` 是最常用的形式，因为它没有隐式寄存器、结果也只有 64 位。

## Logic and Bit Manipulation

```asm
and   rax, rbx            ; 屏蔽位；and rax, -16 是最快的 16 字节向下对齐
or    rax, rbx
xor   rax, rax            ; 清零惯用法（2 字节，且不产生对旧值的假依赖）
not   rax
shl   rax, 4              ; 逻辑左移（等价乘 2^4）
shr   rax, 4              ; 逻辑右移（补 0，用于无符号）
sar   rax, 4              ; 算术右移（补符号位，用于有符号除法）
rol   rax, 8              ; 循环左移
bt    rax, 3              ; 测试第 3 位 → CF
bts   rax, 3              ; 测试并置位
btr   rax, 3              ; 测试并清除
popcnt rax, rbx           ; 统计置位数（POPCNT 扩展）
tzcnt rax, rbx            ; 尾零个数
lzcnt rax, rbx            ; 前导零个数
```

`xor reg, reg` 优于 `mov reg, 0`：编码更短，且现代 CPU 在寄存器重命名阶段就识别它、不消耗执行端口。

> [!WARNING]
> `lzcnt`/`tzcnt` 的编码是 `F3` 前缀加 `bsr`/`bsf` 的操作码。在**不支持**这些扩展的老 CPU 上，`F3` 前缀被忽略，指令退化成 `bsr`/`bsf`——`bsf` 对输入 0 结果未定义，`bsr` 与 `lzcnt` 结果也不同。用之前要查 CPUID 的 ABM/LZCNT 位，编译器需要 `-mlzcnt` 或对应的 `-march`。

## Control Flow

```asm
jmp   label               ; 无条件跳转
je    label               ; ZF=1
jne / jz / jnz / jg / jge / jl / jle / ja / jae / jb / jbe / js / jns / jo / jno
call  func                ; 压入返回地址并跳转
ret                       ; 弹出返回地址并跳转
```

`call`/`ret` 是函数抽象在硬件上的落点，也是 [栈帧](/docs/CS/assembly/Stack_Frame.md) 存在的原因。还有几条特殊指令：

- **`loop`**：`dec rcx` + `jnz`。它是 8086 的遗产，现代 CPU 上比手写 `dec`+`jnz` 慢，实际代码中不该出现。
- **`pause`**：给自旋锁用的提示，告诉 CPU 正在自旋，避免退出时的内存序误判惩罚；也用于 RDTSC 序列化。
- **`ud2`**：故意触发非法指令异常，编译器用它在 `__builtin_unreachable()` 之后做断言。
- **`endbr64`**：CET 的分支目标标记，函数入口必须是它，否则走函数指针调用会被终结。
- **`hlt`**：停机，仅在 Ring 0 可用。

## Stack Operations

```asm
push  rax                 ; rsp -= 8; [rsp] = rax
pop   rax                 ; rax = [rsp]; rsp += 8
push  qword [rbx]         ; 可以直接压内存
leave                     ; rsp = rbp; pop rbp（epilogue 惯用法）
```

`push`/`pop` 自带 `rsp` 更新，天然嵌套成对——这是栈能表达"函数调用层级"的根本原因。`enter` 指令（对应高级语言的块入口）因为慢，现代代码一律用 `push rbp; mov rbp, rsp; sub rsp, N` 手写。

## Atomic and System Instructions

| 指令 | 作用 | 说明 |
|------|------|------|
| `lock add [mem], 1` | 原子加 | `lock` 前缀锁总线/缓存行 |
| `xchg [mem], reg` | 原子交换 | 带内存操作数时隐含 `lock`，无需前缀 |
| `cmpxchg [mem], reg` | CAS | 隐含用 `rax` 作期望值，ZF 表示是否成功 |
| `xadd [mem], reg` | 原子交换并加 | fetch-and-add |
| `mfence`/`lfence`/`sfence` | 内存屏障 | 与 [缓存一致性](/docs/CS/CO/coherence.md) 相关 |
| `rdtsc`/`rdtscp` | 读时间戳计数器 | 基准测试常用，但可能被乱序，需配合序列化指令 |
| `cpuid` | 查询 CPU 特性 | 判断扩展是否可用的唯一途径 |
| `syscall` | 系统调用 | 详见 [系统调用](/docs/CS/assembly/System_Calls.md) |
| `int 3` | 断点软中断 | 调试器下断点靠它 |
| `swapgs` | 切换 GS 基址 | 内核入口专用（Ring 0） |

`lock` 前缀的开销是数量级的：一次原子自增在争用下可能是几十上百个周期，而普通 `add` 不到一个周期。这是并发数据结构里"先无锁化、再原子化"的原因。

## Encoding Constraints Worth Knowing

- **1 字节的 `inc`/`dec` 在 64 位模式下不存在**：这 16 个操作码（`0x40`~`0x4F`）在 x86-64 里被征用作 REX 前缀，所以 64 位代码里的 `inc rax` 是 2 字节编码。
- **立即数宽度有限**：`mov rax, imm64` 可以带 64 位立即数（`movabs`），但 `add rax, imm` 的立即数最多 32 位（符号扩展）。要让 `rax` 等于任意 64 位常量，用 `movabs rax, 0x...`。
- **位移只能是 32 位**：内存操作数的 displacement 字段是 32 位有符号，无法一次表达更大的偏移。
- **指令长度**：x86 指令最短 1 字节，最长 15 字节，超过会 `#UD`。前缀叠加很容易逼近上限。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [寄存器与寻址方式](/docs/CS/assembly/Registers_and_Addressing.md)
- [栈帧与函数调用](/docs/CS/assembly/Stack_Frame.md)
- [惯用法与优化](/docs/CS/assembly/Optimization_and_Idioms.md)
- [数据并行与加速器（向量 ISA）](/docs/CS/CO/simd.md)
- [流水线](/docs/CS/CO/pipeline.md)

## References

1. [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
2. [AMD64 Architecture Programmer's Manual](https://www.amd.com/en/search/site-search.html?k=AMD64%20Architecture%20Programmer%27s%20Manual)
3. [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html)
4. [x86-64 psABI 1.0 PDF](https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf)
5. [Felix Cloutier — x86 and amd64 instruction reference](https://www.felixcloutier.com/x86/)
