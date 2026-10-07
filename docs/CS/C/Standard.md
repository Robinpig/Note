## Introduction

C 标准由 ISO/IEC JTC1/SC22/WG14（WG14）维护，文档号 ISO/IEC 9899。了解演进不在于考古，而在于：**某特性是否可用，取决于你指定的 `-std` 和编译器版本**。本文按时间线梳理各版引入的关键能力。

## 演进时间线

| 版本 | 发布 | 名字 / `__STDC_VERSION__` | 关键新增 |
| :-- | :-- | :-- | :-- |
| C89 / C90 | 1989 / 1990 | ANSI C / ISO/IEC 9899:1990 | 首个标准（K&R 之后）：函数原型、标准库 |
| C95 | 1995 | AMD1 | 宽字符 / 多字节支持 |
| C99 | 1999 | 199901L | `//` 注释、单行声明混合、长整型 `long long`、变长数组 VLA、复合字面量、指定初始化器、`restrict`、`inline`、`_Bool`、`<stdint.h>`、`<stdbool.h>` |
| C11 | 2011 | 201112L | `_Generic`（泛型）、`_Atomic` + `<stdatomic.h>`、`<threads.h>`（可选）、`_Alignof`/`_Alignas`、匿名结构体/联合体、`_Static_assert`、边界检查接口 Annex K（可选）、移除 `gets` |
| C17 / C18 | 2018 | 201710L | 仅缺陷修复与技术勘误，**无新特性**（「C18」来自 ISO 出版年） |
| C23 | 2024 | 202311L | 大量更新（见下） |

## C23 重点（ISO/IEC 9899:2024，2024-10-31 发布）

- **关键字化**：`bool` / `true` / `false` / `static_assert` / `thread_local` / `nullptr`（及 `nullptr_t`）从宏升级为关键字（旧 `<stdbool.h>` / `<threads.h>` 宏仍可用作兼容拼写）；`typeof` 运算符标准化；`auto` 改作类型推导；新增 `constexpr`。
- **新类型**：`_BitInt(N)` 位精确整数、`_Decimal32/64/128` 十进制浮点、`char8_t`（UTF-8 字符类型，与 C++17 对齐）。
- **属性语法 `[[]]`**：`[[deprecated]]` `[[fallthrough]]` `[[maybe_unused]]` `[[nodiscard]]` `[[noreturn]]`（C++ 风格）；`_Noreturn` 被弃用。
- **预处理**：`#elifdef` / `#elifndef` / `#warning` / `#embed`（二进制资源内嵌）、`__has_include` / `__has_c_attribute`、`__VA_OPT__`（替代 GNU 的 `, ## __VA_ARGS__`，见 [预处理与宏](/docs/CS/C/Preprocessor.md)）。
- **新库**：`<stdbit.h>`（位工具 `stdc_count_ones` 等）、`<stdckdint.h>`（checked 整数算术）；`memset_explicit`（安全擦除敏感数据）、`memccpy`、`strdup` / `strndup`、`memalignment`、`timegm`；`printf` 的 `%b`/`%B` 二进制格式；`0b`/`0B` 二进制整数字面量；字面量数字分隔符 `'`。
- **移除 / 弃用**：三字符序列（trigraphs）、K&R 旧式函数定义（无原型）、非二补码的有符号整数表示。

## 编译器与 `-std`

实际可用特性要看编译器支持度（GCC 15 起默认 C23、Clang/MSVC 渐进支持）。用 `-std` 选标准：

```shell
gcc -std=c11 main.c     # 广泛兼容
gcc -std=c17 main.c
gcc -std=c23 main.c     # 或旧称 -std=c2x
```

用 `__STDC_VERSION__` 在代码里探测特性（配合 [预处理与宏](/docs/CS/C/Preprocessor.md) 的 `__has_include`）：

```c
#if __STDC_VERSION__ >= 201112L
/* 可用 _Atomic / _Generic 等 C11 特性 */
#endif
```

## 实践建议

- 既有 / 跨平台项目：默认 `-std=c11` 或 `c17`，兼容性最好。
- 新项目：可考虑 `c23`，但先确认工具链（尤其嵌入式 / 老旧编译器）支持。
- 需要某特性前先查 `__STDC_VERSION__`，不要假设「反正新编译器都有」。

## Links

- [C](/docs/CS/C/C.md)
- [预处理与宏](/docs/CS/C/Preprocessor.md)
- [类型系统](/docs/CS/C/Types.md)
- [并发与原子](/docs/CS/C/Concurrency.md)

## References

1. [WG14（C 标准委员会）](https://www.open-std.org/jtc1/sc22/wg14/)
2. [cppreference：C23](https://en.cppreference.com/w/c/23)
