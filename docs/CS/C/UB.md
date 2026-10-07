## Introduction

C 标准描述的是一台「抽象机」的行为，而**未定义行为（Undefined Behavior, UB）**指标准**不施加任何要求**的情况。一旦程序触发 UB，编译器可以做任何事：看似正常运行、崩溃、或更隐蔽地——在优化后把整段代码「合理」地删掉或重排。写出正确 C 的关键，就是知道哪些操作是 UB。

## Why UB Exists

UB 不是缺陷，而是**刻意为之**：它把「标准不保证」的区域留给编译器做优化。例如「有符号整数不会溢出」让编译器假设循环边界、做向量化；「没有数据竞争」让它能重排内存访问。代价是：一旦你的程序真的越了界，之前基于假设做出的优化会反噬你。

## Common UB List

### Null / Wild / Dangling Pointer Dereference

解引用 `NULL`、未初始化指针、或已 `free` 的指针（悬垂）。后者最隐蔽：内存还没被复用，程序可能「正常」跑很久才崩。相关分配器细节见 [malloc](/docs/CS/C/malloc.md) / [glibc](/docs/CS/C/glibc.md)。

### Signed Integer Overflow

**有符号**整数溢出是 UB；**无符号**整数溢出则良定义（按模回绕）。这正是为什么计数器、下标、哈希里倾向用 `unsigned`。

```c
int a = INT_MAX;
int b = a + 1;     // UB！不要依赖「变成负数」
unsigned u = UINT_MAX;
unsigned v = u + 1; // 良定义：回绕成 0
```

### Strict Aliasing Rule (strict aliasing)

通过**不兼容类型**的指针访问同一段内存是 UB——编译器据此假设「不同类型的指针不会指向同一数据」，从而大胆缓存 / 重排。例外：`char` / `unsigned char` 可以别名任何类型；`union` 做类型双关是合规的（见 [结构体](/docs/CS/C/Struct.md)）。

```c
float f = 3.14f;
int   i = *(int*)&f;   // UB：用 int* 读 float 对象
// 合规写法：
int   j; memcpy(&j, &f, sizeof j);
```

GCC/Clang 默认开 `-fstrict-aliasing`，`-O2` 下极易踩中。

### Evaluation Order and Sequence Points

同一表达式里对同一对象做多次未排序的修改，结果是 UB：

```c
int i = 0;
int x = i++ + i++;   // UB：两次副作用未排序
```

C11 起用语精确化为 * sequenced-before / unsequenced / indeterminately sequenced*；函数实参的求值顺序是 *indeterminately sequenced*（彼此不交错，但先后不确定），所以 `f(i++, i++)` 也别指望顺序。

### Other Common UB

- 数组越界访问（含「差一个」的 off-by-one）。
- 使用未初始化的自动变量（值是不确定的）。
- 数据竞争：两个线程无同步地访问同一对象且至少一个在写（见 [并发与原子](/docs/CS/C/Concurrency.md)）。
- 除以零、移位负位数或超出类型宽、对空指针做指针算术。

## Defensive Measures

- 开 `-Wall -Wextra`，很多笔误 / 可疑写法会被警告。
- 接 **UBSan**：`-fsanitize=undefined`，运行期直接报出 UB 发生点（配合 ASan 抓内存类 UB）。
- 需要回绕语义时显式用 `unsigned`；需要类型双关时用 `memcpy` 或 `union`，别用强制转换。
- 并发访问一律加同步（mutex / 原子），不要赌「单核上看着没事」。

## Links

- [C](/docs/CS/C/C.md)
- [结构体](/docs/CS/C/Struct.md)
- [类型系统](/docs/CS/C/Types.md)
- [malloc](/docs/CS/C/malloc.md)
- [并发与原子](/docs/CS/C/Concurrency.md)

## References

1. [cppreference：未定义行为 / 抽象机](https://en.cppreference.com/w/c/language/behavior)
2. [A Guide to Undefined Behavior（John Regehr）](https://blog.regehr.org/archives/213)
