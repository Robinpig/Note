## Introduction

Quick Command


| Command                    | Function          |  |
| -------------------------- | ----------------- | - |
| ⌘⇧.(Command + Shift + .) | show hidden files |  |
| ⌘⇧4(Command + Shift + 4) | screenshots       |  |
|                            |                   |  |

vm_stat

[Software](/docs/CS/OS/mac/Tools/Software.md)




Network tools:

```shell

brew install net-tools
```

ctags

```shell
brew install ctags

/opt/homebrew/opt/ctags/bin/ctags -R
```



ccat

htop


tree

```shell
brew install tree

tree ./ -L 2
```



## Issues

MBP 长期不关机时，跨设备 Handoff 会失效（其他设备看不到复制的内容、无法接力），重启后恢复。这类连续互通功能依赖蓝牙 LE 与 AWDL 的常驻状态，长时间运行后状态机卡住，重启是最快的解法。

## Links

- [Mac](/docs/CS/OS/mac/mac.md)
- [Software](/docs/CS/OS/mac/Tools/Software.md)
- [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)
- [Development](/docs/CS/OS/mac/Development.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)
