## Introduction

C 没有原生字符串类型：字符串就是「以 `\0` 结尾的 `char` 数组」。而数组名在多数表达式里会**退化**成指向首元素的指针——这两点是大量 C 新手（和 bug）的来源。

## 数组与指针：不是一回事

- 数组是「连续 N 个同类型对象」；指针是「一个地址」。
- 数组在表达式中（除 `sizeof` / `_Alignof` / `&` / `_Atomic` 的操作数外）**退化**为指向首元素的指针。
- 作为函数参数时，`void f(char s[])` 等价于 `void f(char *s)`——数组**不会**按值传入，退化成指针，所以 `sizeof(s)` 在参数里得到指针大小：
  ```c
  char buf[16];
  sizeof(buf);                  // 16
  void f(char s[16]) { sizeof(s); }  // 得到指针大小，不是 16！
  ```

## 字符串

- `"hello"` 是 `char[6]`（含结尾 `\0`）。
- `char str[] = "hi";` 可修改；`char *p = "hi";` 指向**只读**字面量，写它是 [UB](/docs/CS/C/UB.md)（段错误）。
- 字符串长度不含 `\0`：`strlen("hello") == 5`。

## `<string.h>` 要点

- `strlen`：不含 `\0`。
- `strcpy` / `strncpy`：后者**不保证**补 `\0`（目标不够长时不补），需要手动处理。
- `strcat`：拼接，注意目标容量。
- `strcmp`：按字典序返回负 / 零 / 正（不是布尔真值）。
- `memcpy` / `memmove`：**重叠**内存必须用 `memmove`。
- `memset`：按字节填（清 0 可用，但清结构体的指针字段只是位 0，不是 NULL）。
- `strdup` / `strndup`：分配副本（POSIX，C23 纳入标准）。

## 缓冲区溢出

`strcpy` 不检查目标边界，是最经典的 CVE 来源。防御：

- 用 `strncpy` + 手动补 `\0`，或优先 `snprintf`：
  ```c
  snprintf(buf, sizeof buf, "%s", src);   // 绝不越界，且补 \0
  ```
- C11 可选 **Annex K** 边界检查接口（`strcpy_s` 等）很多平台未实现，别依赖。
- 网络 / 文件读入一律用「长度 + 边界检查」回路，别信输入以 `\0` 结尾。

## 多维数组

行主序（row-major）：`int a[2][3]` 在内存里是 `a[0][0..2]` 接 `a[1][0..2]`。退化时 `a` 退化成 `int(*)[3]`（指向「含 3 个 int 的行」），而**不是** `int**`——这是二维数组传参最常见的误区。

## Links

- [C](/docs/CS/C/C.md)
- [结构体](/docs/CS/C/Struct.md)
- [未定义行为](/docs/CS/C/UB.md)
- [类型系统](/docs/CS/C/Types.md)

## References

1. [cppreference：字符串与字节](https://en.cppreference.com/w/c/string/byte)
2. [cppreference：数组](https://en.cppreference.com/w/c/language/array)
