## Introduction

C 标准库（libc；本库以 glibc 为实现）按头文件分模块。分配器那一块已在 [glibc](/docs/CS/C/glibc.md) / [malloc](/docs/CS/C/malloc.md) 专门展开，这里给总览并挑几块讲清。

## 头文件分族

- `<stdio.h>`：文件与格式化 IO（`FILE`、printf/scanf/fopen）。
- `<stdlib.h>`：通用（`exit`/`atexit`、`qsort`/`bsearch`、`getenv`、`strtol`/`atoi`、`rand`/`srand`、`system`）。
- `<string.h>`：内存与字符串（见 [数组与字符串](/docs/CS/C/Array_String.md)）。
- `<ctype.h>`：字符分类（`isdigit` 等，参数须为 `unsigned char` 或 `EOF`，否则 UB）。
- `<math.h>` / `<time.h>`：数学 / 时间。
- `<errno.h>` / `<stdarg.h>` / `<setjmp.h>` / `<signal.h>` / `<locale.h>`：见下。

## 格式化 IO

`printf` 族：`%d %u %x %p %s %c %f`，C23 新增 `%b`/`%B` 打印二进制（见 [C 标准演进](/docs/CS/C/Standard.md)）。`scanf` 用 `%` 读入，注意取地址 `&`。**防溢出用 `snprintf`** 而非 `sprintf`。

## 错误处理：errno

很多库函数在出错时设置**线程局部的** `errno`（`<errno.h>`）：

```c
#include <errno.h>
FILE *f = fopen("x", "r");
if (!f) {
    if (errno == ENOENT) { /* 文件不存在 */ }
    perror("fopen");                 // 打印 "fopen: <描述>"
    const char *m = strerror(errno);
}
```

注意：只有函数文档写明「失败时设 errno」才可靠；成功路径**不保证**把 errno 清零，不要先看 errno 再判断成功。

## 非局部跳转：setjmp / longjmp

`<setjmp.h>` 提供跨栈帧的「类似异常」跳转：

```c
#include <setjmp.h>
jmp_buf env;
if (setjmp(env) == 0) {
    deep_call();          // 正常执行
} else {
    /* 从 longjmp 回来的错误恢复 */
}
/* 深处： */
longjmp(env, 1);          // 跳回 setjmp，返回非 0
```

风险：跳过的中间栈帧**不会**执行清理（不会释放锁 / 内存 / 关闭资源），比 C++ 异常更危险；现代代码多用返回值 / 错误码交给上层处理。用途多见于错误恢复、协程式控制流。

## 可变参数：`<stdarg.h>`

`printf` 之所以能接任意个参数，靠 `<stdarg.h>`：

```c
#include <stdarg.h>
int sum(int n, ...) {
    va_list ap; va_start(ap, n);
    int s = 0;
    for (int i = 0; i < n; i++) s += va_arg(ap, int);
    va_end(ap);
    return s;
}
```

实现依赖调用约定；参数类型完全靠程序员保证（传错类型是 UB）。C23 用 `__VA_OPT__` 让宏侧可变参数更干净（见 [预处理与宏](/docs/CS/C/Preprocessor.md)）。

## 数值转换

- `atoi`：**不报溢出 / 错误**，别用于不可信输入。
- `strtol` / `strtoul` / `strtod`：好——返回 `errno` 与「停止解析的位置」，可区分「0」和「解析失败」。
- `rand` / `srand`：弱随机数，加密场景用 `/dev/urandom` 或平台 CSPRNG。

## Links

- [C](/docs/CS/C/C.md)
- [glibc](/docs/CS/C/glibc.md)
- [malloc](/docs/CS/C/malloc.md)
- [数组与字符串](/docs/CS/C/Array_String.md)
- [预处理与宏](/docs/CS/C/Preprocessor.md)

## References

1. [cppreference：C 标准库](https://en.cppreference.com/w/c)
2. [The GNU C Library 手册](https://www.gnu.org/software/libc/manual/)
