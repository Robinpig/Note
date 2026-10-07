## Introduction

预处理器在**编译之前**对源码做纯文本变换：它不懂 C 语义，只认以 `#` 开头的行。正因为处在文本层，宏既能写出优雅的抽象，也最容易埋下「看着对、实际错」的坑。

## Directives

- `#define` / `#undef`：定义 / 取消对象宏或函数宏。
- `#include`：贴入头文件（见 [编译与链接](/docs/CS/C/Compilation.md) 的头文件守卫）。
- 条件编译：`#if` / `#ifdef` / `#ifndef` / `#elif` / `#else` / `#endif`，配合 `#define DEBUG` 开关调试代码。
- `#error`：不满足条件直接让编译失败（常用于特性检查）。
- `#line` / `#pragma`：前者改 `__LINE__`，后者给编译器发实现相关指示；`_Pragma` 是 `#pragma` 的「运算符形式」，可写在宏里。

## Object-like Macros vs Function-like Macros

```c
#define BUFFER_SIZE 4096                // 对象宏：纯文本替换
#define MAX(a, b) ((a) > (b) ? (a) : (b))   // 函数宏
```

函数宏的每个参数都要**用括号包住**，且整个展开也要包括号——否则运算符优先级会咬人：

```c
#define SQR(x) x * x
SQR(1 + 2)        // 展开成 1 + 2 * 1 + 2 = 5，而非 9
#define SQR(x) ((x) * (x))     // 正确写法
```

含多条语句的宏要用 `do { ... } while (0)` 包成复合语句，才能安全地用在 `if` 后不带 `{}` 的分支里。

## Stringification and Concatenation: `#` and `##`

- `#`：把参数变成字符串字面量。
- `##`：把左右两边拼接成新记号（token paste）。

```c
#define STR(x)  #x
STR(hello)              // "hello"

#define CONCAT(a, b) a##b
CONCAT(foo, bar)        // foobar
```

## Variadic Macros

函数宏可以接受可变参数（`...`），用 `__VA_ARGS__` 引用：

```c
#define LOG(fmt, ...) printf(fmt, __VA_ARGS__)
```

GNU 扩展允许 `__VA_ARGS__` 前加 `##` 来吃掉多余的逗号（`LOG("hi")` 不报错）。**C23 标准化了 `__VA_OPT__`**，只在确实有可变参数时才展开，取代这种技巧（见 [C 标准演进](/docs/CS/C/Standard.md)）。

## Header Guards and `#pragma once`

防止同一头文件被重复包含：

```c
#ifndef MY_H
#define MY_H
/* ... */
#endif
```

`#pragma once` 效果等价、写法更短，主流编译器都支持但**不在标准里**。两者选一即可，不要混用。

## Predefined Macros

这些由编译器 / 标准自动提供，常用于可移植与日志：

- `__FILE__` / `__LINE__`：当前文件 / 行号（断言、日志常用）。
- `__func__`：当前函数名（C99，是隐式声明的 `static const char[]`，不是宏但行为类似）。
- `__DATE__` / `__TIME__`：编译日期 / 时间。
- `__STDC__` / `__STDC_VERSION__`：是否遵循标准、标准版本号（如 `201112L` 表示 C11）。
- 编译器私有宏：如 `__GNUC__`、`_MSC_VER`。

## Macro Pitfalls

- **带副作用的参数**：`MAX(i++, j++)` 里 `i` / `j` 可能被求值多次——用 `MAX` 时绝不要传带 `++` 的参数。
- **作用域与类型**：宏没有类型，容易和同名函数冲突；现代 C 里多数场景应优先用 `static inline` 函数或 `enum` 常量替代宏。
- **运算符优先级**：忘了给参数和整体加括号是最常见的 bug 源（见上文 `SQR`）。

## X-Macros (Advanced)

用一个「列表宏」集中描述一组数据，再用宏生成枚举、字符串表、switch 分支，避免多处手写不同步：

```c
#define COLOR_LIST(X) \
    X(RED)  X(GREEN)  X(BLUE)

#define X_ENUM(name) COLOR_##name,
enum { COLOR_LIST(X_ENUM) COLOR_COUNT };

#define X_STR(name)  case COLOR_##name: return #name;
const char* color_name(int c) {
    switch (c) { COLOR_LIST(X_STR) }
    return "?";
}
```

这套手法在大型 C 项目（包括 Linux 内核）里很常见，适合「一组相关常量要在多处以不同形式出现」的场景。

## Links

- [C](/docs/CS/C/C.md)
- [编译与链接](/docs/CS/C/Compilation.md)
- [C 标准演进](/docs/CS/C/Standard.md)

## References

1. [cppreference：预处理器](https://en.cppreference.com/w/c/preprocessor)
2. [GCC 预处理器官方手册](https://gcc.gnu.org/onlinedocs/cpp/)
