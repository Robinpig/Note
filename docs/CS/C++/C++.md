## Introduction


C++ blends the C language with support for object-oriented programming and for generic programming.


## Tutorial

Mac


VS Code

打开VScode，进入 `Extensions` 模块，搜索以下扩展并安装：

C/C++
C/C++ Clang Command Adapter
Code Runner


.vscode文件夹下文件配置


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

## Basic concepts


Resource Acquisition Is Initialization or RAII, is a C++ programming technique which binds the life cycle of a resource that must be acquired before use 
(allocated heap memory, thread of execution, open socket, open file, locked mutex, disk space, database connection—anything that exists in limited supply) 
to the lifetime of an object.




### Types


## Initialization


## Concurrency

[Concurrency](/docs/CS/C++/Concurrency.md)



Frameworks



- [muduo](/docs/CS/C++/muduo.md)




## Links

- [C](/docs/CS/C/C.md)
- [Java JDK](/docs/CS/Java/JDK/JDK.md)


## References

1. [C++ language](https://en.cppreference.com/w/cpp/language)
