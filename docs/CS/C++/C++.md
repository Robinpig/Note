## Introduction

C++ 在 C 之上叠加了面向对象、泛型与 RAII，核心理念是**零成本抽象（zero-overhead abstraction）**：你不为没用到的抽象付费，用到的抽象与手写代码等价。代价是语言表面积巨大、编译慢、错误信息冗长。

## 知识体系

本目录按「对象模型 → 资源管理 → 泛型 → 内存 → 标准库 → 并发 → 工程」逐层展开：

- **对象模型与类型**：[对象模型](/docs/CS/C++/ObjectModel.md)讲内存布局、vtable 与虚分发，是理解多态与 [RTTI](/docs/CS/C++/RTTI.md) 的地基；[初始化](/docs/CS/C++/Init.md)梳理最易错的值 / 列表 / 拷贝初始化与「最令人头疼的解析」。
- **资源管理（RAII）**：[智能指针](/docs/CS/C++/SmartPtr.md)（unique / shared / weak）把 `new` / `delete` 封装进生命周期；[移动语义](/docs/CS/C++/Move.md)（右值引用、完美转发、Rule of Five）让资源转移零拷贝。
- **泛型**：[模板](/docs/CS/C++/Templates.md)（SFINAE、可变参数、C++20 Concepts、CRTP）是 STL 与元编程的基石。
- **内存**：[内存与 new/delete](/docs/CS/C++/Memory.md)讲分配 / 构造两步骤、placement new 与 `std::pmr` 分配器模型；[未定义行为](/docs/CS/C++/UB.md)汇总越界、溢出、数据竞争等标准不保证的雷区。
- **标准库**：[STL](/docs/CS/C++/STL.md)（容器 / 迭代器 / 算法 / `string_view` / `span`）是日常最高频的一半。
- **并发**：[Concurrency](/docs/CS/C++/Concurrency.md)覆盖 `std::thread`、future / promise、latch / barrier、原子与六种内存序。
- **标准演进**：[C++ 标准演进](/docs/CS/C++/Standard.md)（C++11 → 20 → 23 → 26）对照各版本特性与 `-std=` / ABI 稳定性。
- **工程框架**：[muduo](/docs/CS/C++/muduo.md)是现代 C++ 网络编程（one loop per thread）的代表库。

## 几个值得记住的点

- `std::sort` 是**内省排序**（introsort）：快排为主、递归过深转堆排、小子区间用插入排序——见 [STL](/docs/CS/C++/STL.md)。
- **RAII** 是 C++ 资源管理的万能钥匙：任何「获取即构造、释放即析构」的资源（锁、文件、连接）都应包进对象，详见 [智能指针](/docs/CS/C++/SmartPtr.md)。
- 与 [C](/docs/CS/C/C.md) 共享底层（同用堆、同踩 UB），但多了构造 / 析构、类型安全与模板元编程。

## 工具链

C++ 与 C 共用构建与调试基建：CMake / make 见 [C 的 make](/docs/CS/C/make.md) 与 [CMake](/docs/CS/C/CMake.md)，调试器见 [GDB](/docs/CS/C/GDB.md)。

## 与相邻语言的对照

- 和 [Go](/docs/CS/Go/Go.md) 比：Go 用 GC 与 goroutine 换开发效率，C++ 用显式控制换性能与抽象。
- 和 [Rust](/docs/CS/Rust/Rust.md) 比：Rust 把所有权 / 借用检查移到编译期，C++ 把所有权交给程序员（靠智能指针自律）。
- 和 [Java](/docs/CS/Java/Java.md) 比：Java 的对象总是在堆、靠 JVM GC，C++ 对象可在栈也可在堆、析构确定性释放。

## 快速开始（VS Code 环境）

Mac 下用 VS Code 写 C++ 的常用配置。

打开 VScode，进入 `Extensions` 模块，搜索以下扩展并安装：

- C/C++
- C/C++ Clang Command Adapter
- Code Runner

`.vscode` 文件夹下文件配置：

<!-- tabs:start -->

###### **c_cpp_properties.json**

```json
{
  "configurations": [
    {
      "name": "Mac",
      "includePath": [
        "${workspaceFolder}/**"
      ],
      "defines": [],
      "macFrameworkPath": [
        "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks"
      ],
      "compilerPath": "/usr/bin/clang++",
      "cStandard": "c17",
      "cppStandard": "c++17",
      "intelliSenseMode": "macos-clang-x64"
    }
  ],
  "version": 4
}
```

###### **task.json**

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "type": "cppbuild",
      "label": "C/C++: clang++ 生成活动文件",
      "command": "/usr/bin/clang++",
      "args": [
        "-fcolor-diagnostics",
        "-fansi-escape-codes",
        "-g",
        "${file}",
        "-o",
        "${fileDirname}/${fileBasenameNoExtension}"
      ],
      "options": {
        "cwd": "${fileDirname}"
      },
      "problemMatcher": [
        "$gcc"
      ],
      "group": {
        "kind": "build",
        "isDefault": true
      },
      "detail": "编译器: /usr/bin/clang++"
    }
  ]
}
```

###### **launch.json**

```json
{
  "configurations": [
    {
      "name": "C/C++: clang++ 生成和调试活动文件",
      "type": "cppdbg",
      "request": "launch",
      "program": "${fileDirname}/${fileBasenameNoExtension}",
      "args": [],
      "stopAtEntry": false,
      "cwd": "${workspaceFolder}",
      "environment": [],
      "externalConsole": true,
      "MIMode": "lldb",
      "preLaunchTask": "C/C++: clang++ 生成活动文件"
    }
  ],
  "version": "2.0.0"
}
```

<!-- tabs:end -->

## Links

- [C](/docs/CS/C/C.md)
- [编程语言横向对比](/docs/CS/Languages.md)
- [Java JDK](/docs/CS/Java/JDK/JDK.md)
- [Go](/docs/CS/Go/Go.md)
- [Rust](/docs/CS/Rust/Rust.md)

## References

1. [cppreference](https://en.cppreference.com/w/cpp)
1. [ISO C++](https://isocpp.org/)
