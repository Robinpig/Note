## Introduction

"手写汇编更快"在今天是个需要证伪的命题：编译器的寄存器分配、指令选择、循环展开、向量化决策通常优于人手，而且内联汇编还会**阻断**常量传播与向量化。所以本页的重点不是"怎么写更快"，而是**先读懂编译器在做什么，再判断它错在哪**——只有确认编译器确实做错了，手写才有意义。

前置：[指令集与常用指令](/docs/CS/assembly/Instruction_Set.md) 讲指令语义，[汇编器与工具链](/docs/CS/assembly/Assembler_and_Toolchain.md) 讲怎么看输出，[分支预测](/docs/CS/CO/BranchPrediction.md) 与 [数据并行](/docs/CS/CO/simd.md) 讲相关的硬件机制。

## Reading Compiler Output

```bash
gcc -O2 -S -fverbose-asm -masm=intel foo.c
```

`-fverbose-asm` 会把源变量名作为注释写进汇编，这是从"一堆寄存器"还原成"你的代码"的关键。读的时候按这个顺序看：

1. **有没有出现意料之外的 `call`**：出现 `call memset`/`memcpy` 说明编译器识别出了惯用法；出现 `call __udivti3` 说明它没法把 128 位除法降级。
2. **循环有没有被向量化**：找 `xmm`/`ymm` 寄存器与 `paddd`/`vmovdqu` 这类指令，或者看有没有 `-ftree-vectorize` 留下的多路展开结构。
3. **有没有多余的 load/store**：同一个值在循环里反复从内存读，说明有别名（alias）问题，通常要靠 `restrict` 或重新组织代码解决，而不是靠汇编。
4. **除法是不是变成了乘法**：出现 `movabs rdx, 0x...` + `mul` + `shr` 就是编译器做了倒数替换（见下文）。

## Common Idioms

编译器生成的这些序列要在三秒内认出来：

| 惯用法 | 汇编形态 | 含义 |
|--------|---------|------|
| 清零 | `xor eax, eax` | 2 字节，无假依赖；`mov eax, 0` 更长且保留旧值依赖 |
| 判零 | `test eax, eax` + `je/jne` | 比 `cmp eax, 0` 短 |
| 取负 | `neg rax` | |
| 乘小常数 | `lea rax, [rdi + rdi*4]` | `lea` 做乘 5，一周期且不写标志位 |
| 移位乘法 | `shl rax, 3` | 乘 8 |
| 符号/零扩展 | `movsxd rax, eax` / `movzx eax, byte [...]` | C 里的整型提升 |
| 无分支选择 | `test` + `cmovne` | 分支预测失败代价通常大于一条 `cmov` |
| 布尔化 | `xor eax, eax` + `test` + `setne al` | C 里的 `bool` 赋值 |
| 取绝对值 | `mov eax, edi; neg eax; cmovs eax, edi` | |
| 求最小/最大 | `cmp` + `cmovle` | |
| 向下对齐 | `and rsp, -16` | 栈对齐 |
| 位计数 | `popcnt` / `lzcnt` / `tzcnt` | 有扩展要求，见 [指令集](/docs/CS/assembly/Instruction_Set.md) 的警告 |
| 字节序 | `bswap rax` | 网络字节序转换 |
| 取模二的幂 | `and rax, 63` | `% 64` |

**除法变乘法**是最值得认识的一个：整数除法在 x86 上是 20~40 个周期的指令，编译器会把 `x / 10` 改写成 `x * M >> s`（`M` 是编译期算出的 magic number，`movabs` 那个大常量就是它）。所以：

- 除数在编译期已知时，除法其实不慢，不需要手写优化；
- 除数在运行时才确定（变量除法）才真的慢，此时才值得考虑换算法；
- 手写汇编里写 `idiv` 替换编译器生成的乘法倒数替换，几乎总是变慢。

## Branch versus Branchless

短分支（`if` 里只有两三行）预测失败时，一次冲刷流水线在现代 x86 上是 15~20 个周期。所以编译器在能证明无副作用时会把分支改成 `cmov` 或 `setcc`（见 [分支预测](/docs/CS/CO/BranchPrediction.md)）：

```c
// 编译器倾向生成 cmov（若 x 的取值不可预测，cmov 更稳）
int m = (a > b) ? a : b;
```

但 **cmov 不是万能的**：它会无条件计算两个源操作数。如果分支的某一侧有昂贵计算、可能除零、或可能解引用空指针，改成 cmov 反而更糟。编译器在这里是保守的——它会估算两侧代价，这也正是手写汇编有时能赢的地方：你比编译器更清楚数据分布（比如"这个分支 99% 走一侧"，那就该保留分支并加 `__builtin_expect`）。

## Memory Access Patterns

指令数少不等于快，内存才是瓶颈。值得注意的几条：

- **对齐**：16 字节对齐的 SSE/AVX 传送（`movaps`/`vmovdqa`）比未对齐版本快，且未对齐的对齐要求指令（如 `movaps` 不要求对齐？——`movaps` 要求对齐，未对齐会 #GP；`movups` 不要求）会直接崩。结构体布局、缓存行（64 字节）对齐都在这里起作用。
- **局部性**：顺序访问能触发硬件预取器；跨步访问（stride）一旦超过一定间隔，预取失效，每次都要等内存。
- **假共享**：两个线程写同一缓存行的不同字节，会造成缓存行在核间反复无效化——这是汇编层面才看得见的现象（同一行 C 代码，加一个 padding 就快几倍）。
- **store-to-load forwarding stall**：刚写入内存又立刻以不同宽度/对齐读同一位置，CPU 无法直接转发，必须等写入完成。混用 8 位写与 64 位读同一地址就会触发。
- **向量化**：数据并行交给 [SIMD](/docs/CS/CO/simd.md)，编译器在 `-O3`（GCC 12+ 在 `-O2` 也启用 `-ftree-vectorize`）下会自动做；手写汇编想赢需要先确认它没做、以及为什么没做（通常是对齐或别名信息不足，`restrict` 能解决）。

## Microarchitecture Traps

- **假依赖（false dependency）**：`mov eax, 1` 形式上依赖 `rax` 的旧值（因为只写 32 位），会拖长依赖链；`xor eax, eax` 不会，因为 CPU 识别这条特殊序列。这在现代 Intel/AMD 上是真实存在的差异。
- **部分寄存器停顿**：写 `al` 再读 `eax` 会插入一次合并操作。现代微架构用寄存器重命名消除了大部分损失，但依赖链仍在。
- **混合 SSE 与 AVX**：使用 AVX（VEX 编码）指令后，若再执行非 VEX 的 SSE 指令且未用 `vzeroupper` 清零 YMM 高位，会触发一次状态切换惩罚。编译器会自己插 `vzeroupper`，手写汇编容易漏。
- **非规格化浮点数（subnormal）**：接近 0 的极小浮点数在某些 CPU 上走微码慢路径，可能慢上百倍。可以用 `mxcsr` 的 FTZ/DAZ 位关掉，但这会改变数值语义。
- **`lock` 前缀**：一次原子操作在争用下是几十到上百周期。详尽的锁实现见 [操作系统锁](/docs/CS/OS/Linux/Lock/)。

## When Hand-Written Assembly Wins

诚实的答案：场合很少，但确实存在。

- **编译器缺少对应 intrinsic 的指令序列**：特定的 MSR 访问、`swapgs`、上下文切换；
- **需要精确指令序列的场合**：密码学常数时间实现（不能让编译器插入数据相关的分支）、基准测量（不能让编译器把代码删掉）、安全缓解序列；
- **小到编译器"看不出整体"的内核**：几十个字节的专用码（如 `strlen`、定点 DSP 小核、矩阵 4×4），且能用 SIMD 手工排流水线；
- **编译器因保守而无法优化**：它能证明的信息不足（比如已知指针一定 16 字节对齐、已知数组不重叠），而你知道。这类情况优先用 `__builtin_assume_aligned`、`restrict`、`__builtin_expect` 把信息喂给编译器，比手写更好维护。

其余情况——"我觉得这样写更快"——基本都是错觉。

## Measuring, Not Guessing

性能优化的唯一标准是测量：

```bash
perf stat -e cycles,instructions,cache-misses,branch-misses ./prog
perf record -g ./prog && perf report   # 调用图（-fno-omit-frame-pointer 更准）
```

几个测量纪律：

- **不要用 `rdtsc` 直接测短代码段**：它不是序列化指令，可能被乱序执行挪动；`rdtscp` 或在其前后插入 `cpuid`/`lfence` 才能约束顺序，代价是本身有开销。
- **看 IPC 而不是墙钟时间**：`instructions/cycles` 低于 1 说明在等内存或等分支，优化方向完全不同。
- **测真实负载**：微基准容易被编译器优化掉（要么 `volatile`，要么把结果真正消费掉），也容易被缓存预热扭曲。
- **对比基线**：和 `-O2` 的纯 C 版本比，而不是和 `-O0` 比。

## Instruction Set Extensions to Watch

x86 的寄存器数量一直是瓶颈（16 个 GPR），最新的扩展正在改这件事：

- **Intel APX**（Advanced Performance Extensions）：新增 16 个通用寄存器 `r16`~`r31`（EGPR，靠 2 字节 REX2 前缀编码）、三操作数整数指令格式（NDD）、不写标志位的指令变体（NF）、`PUSH2`/`POP2` 批量保存恢复。GCC 14 支持其中一部分（EGPR、NDD、PUSH2/POP2），**GCC 15 起完整可用，开关是 `-mapxf`**；首款支持它的客户端芯片是 Diamond Rapids。APX 的意义在于它直接缓解了寄存器压力——也就是 [栈帧](/docs/CS/assembly/Stack_Frame.md) 里 spill 的成因。
- **AVX10**：把 AVX-512 收编为统一向量 ISA，按版本号枚举能力，取代过去"AVX-512 十几个子集"的碎片状态。GCC 15 起 AVX10.2 可用；同时 256 位-only 的 AVX10 配置已被架构移除。

这些扩展对"手写汇编 vs 编译器"的权衡没有影响——编译器同样能用它们，而且用得比人更系统。

## Links

- [汇编（枢纽）](/docs/CS/assembly/assembly.md)
- [指令集与常用指令](/docs/CS/assembly/Instruction_Set.md)
- [汇编器与工具链](/docs/CS/assembly/Assembler_and_Toolchain.md)
- [分支预测](/docs/CS/CO/BranchPrediction.md)
- [数据并行与加速器（SIMD）](/docs/CS/CO/simd.md)
- [性能剖析与观测](/docs/CS/CO/perf.md)

## References

1. [Agner Fog — Software Optimization Resources](https://www.agner.org/optimize/)
2. [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
3. [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html)
4. [Intel GCC 15 支持（APX / AVX10.2）](https://www.intel.com/content/www/us/en/developer/articles/technical/next-gen-performance-gcc-15.html)
5. [GCC — Optimization Options](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html)
6. [Linux perf wiki](https://perf.wiki.kernel.org/index.php/Main_Page)
