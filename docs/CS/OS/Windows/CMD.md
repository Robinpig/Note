## Introduction

Windows 的命令行世界有一个别的系统没有的负担：**你要同时理解三到四层东西在发生什么**。

- `cmd.exe` 是从 DOS 时代继承下来的壳，语法与行为为了兼容历史可以非常反直觉（它的批处理语言几乎是一门独立的、带着转义陷阱的小语种）；
- **PowerShell** 是微软在 2006 年给出的替代：它的管道里流的是**对象**而不是文本，因为 Windows 的管理 API 本来就返回结构化数据；
- **Windows Terminal** 是一个终端宿主，负责把 conhost、PowerShell、WSL、Azure Cloud Shell 等放到同一个带标签页的窗口里，它不是壳本身。

本文按这条线索推进：先给 CMD 批处理的常用片段与它的几个坑，再给 powershell 的日常用法与 CMD/bash 的一张对照表，最后说清"到底该开哪个"。

---

## CMD and Batch: Practical Snippets

### Batch Snippets

把每个子目录里的文件挪到当前目录、删空目录、再顺手删掉 html：

```bat
for /d %a in (*) do move "%a\*" . && rd /s /q "%a" && del *.html
```

把若干种音频文件归拢到一个目录：

```bat
mkdir mp3 && move *.mp3  mp3 & move *.m4a mp3
```

串起来一次做完：

```bat
(for /d %a in (*) do move "%a\*" . && rd /s /q "%a" && del *.html) & mkdir mp3 && move *.mp3  mp3 & move *.m4a mp3
```

重命名（之后按提示给出原名与新名）：

```bat
ren
```

> [!WARNING]
>
> **`%` 在命令行与批处理文件里写法不同**
>
> 上面的 `%a` 是**交互命令行**里的写法；把它写进 `.bat` 文件时必须写成 `%%a`。这是批处理最常见的"我明明在命令行试过了"陷阱。
>
> 第二个陷阱是**延迟扩展**：在 `for` 或 `if` 的括号体内修改并立即读取同一个变量时，需要用 `setlocal enabledelayedexpansion` 并用 `!var!` 而非 `%var%` 取值——因为 `%var%` 在整块被解析时就已经被展开了。

### Three CMD-ex Notes

| 现象 | 原因 |
| :-- | :-- |
| 命令不认含空格路径 | 必须加引号，且 `cd` 换盘符要加 `/d` |
| `echo %ERRORLEVEL%` 在 CPU/IDE/分批/gulp 里值不对 | `if errorlevel 1` 是"≥1"而非"=1"；且要在下一次调用前读 |
| 重定向后中文乱码 | 控制台代码页与文件编码不一致（PowerShell 下一般省心） |

---

## PowerShell: Objects, Not Text

PowerShell 与 Unix shell 的根本区别：**管道里是 .NET 对象**。因此不需要用 `awk '{print $3}'` 之类的位置切割，你可以直接 `Get-Process | Sort-Object CPU -Descending | Select-Object -First 5`。

### Cmdlet Naming Convention

cmdlet 一律是 **动词-名词** 形式，动词与名词都取自受控词表，因此可发现性极好：

| 常用动词 | 含义 |
| :-- | :-- |
| `Get-` | 取出 |
| `Set-` | 设定 |
| `New-` / `Remove-` | 创建 / 删除 |
| `Start-` / `Stop-` / `Restart-` | 启动 / 停止 / 重启 |
| `Where-` / `Select-` / `Sort-` / `Group-` | 过滤 / 投影 / 排序 / 分组 |
| `Invoke-` / `Test-` | 执行 / 检测 |

### Installing and Checking Version

从 Microsoft Store 安装 PowerShell 7 之后，可以设置它为默认配置文件：

1. 打开终端（Terminal），点标题栏下拉箭头 → 设置；
2. 选择"启动 → 默认配置文件"，在下拉菜单中选择 PowerShell；
3. 可选但推荐：Win + I → 隐私和安全性 → 开发者选项（较新版本的 Win11 在"系统 → 对于开发人员"）→ 把"终端"设为 Windows 终端；
4. 设置完成后，Win + X 选"终端"、或在资源管理器右键"在终端中打开"，默认就是 PowerShell 7。

验证当前版本：

```powershell
$PSVersionTable
```

看输出结果里的 `PSVersion`：

- 显示 **7.x.x** 说明已是新的 PowerShell（跨平台，命令 `pwsh`）；
- 显示 **5.1.x** 说明打开的还是随系统自带的 Windows PowerShell（`powershell.exe`），请检查上一步的路径与默认配置文件是否选错。

> [!NOTE]
>
> **Windows PowerShell 5.1 vs PowerShell 7 是两个东西**
>
> 5.1 基于 .NET Framework，只随 Windows 更新，功能基本冻结；7.x 基于 .NET、跨平台、开源、持续演进。两者可以并存，情形与 Linux 上同时装着 Python 2 与 Python 3 类似——**写新脚本一律面向 7.x**，并把只能在 Windows PowerShell 里用的专有 cmdlet 单独标出来。

### One-line对照表

| 意图 | CMD | PowerShell | bash |
| :-- | :-- | :-- | :-- |
| 列目录 | `dir` | `Get-ChildItem`（别名 `ls`、`dir`） | `ls` |
| 找文件 | `dir /s <name>` | `Get-ChildItem -Recurse -Filter <name>` | `find . -name` |
| 看进程 | `tasklist` | `Get-Process`（别名 `ps`） | `ps aux` |
| 杀进程 | `taskkill /PID <pid> /F` | `Stop-Process -Id <pid> -Force` | `kill -9` |
| 文件内容 | `type <file>` | `Get-Content`（别名 `cat`） | `cat` |
| 找字符串 | `findstr <s> <file>` | `Select-String` | `grep` |
| 服务 | `sc query` | `Get-Service` | `systemctl` |
| 环境变量 | `set NAME=v` | `$env:NAME = "v"` | `export NAME=v` |
| 上一条的退出码 | `%ERRORLEVEL%` | `$LASTEXITCODE` | `$?` |

### Two PowerShell Practices

- **执行策略（Execution Policy）**不是安全边界，它防的是"手滑”，而不是攻击者。写脚本遇权限在企业环境或本机想 restrict 太大时，用 `Get-ExecutionPolicy -List` 看清作用域，再决定 `-Scope CurrentUser` 的调整。
- **`$PROFILE`** 是用户级的配置文件路径，可以在里面放别名与函数。想要"每次打开都有 Linux 那套手感"就在 `$PROFILE` 里做，而不是去改全局。

---

## Which Shell Should I Use?

| 场景 | 建议 |
| :-- | :-- |
| 跑别人给的 `.bat` | 用 `cmd.exe`，不要试图在 PowerShell 里重写它 |
| 日常管理与自动化 | PowerShell 7 |
| 写跨平台脚本 | PowerShell 7（也要装 Linux 上的 pwsh），或 Python |
| 需要 GNU 工具链与 bash 语义 | [WSL](/docs/CS/OS/Windows/WSL.md) 或 MSYS2（见 [Tools](/docs/CS/OS/Windows/Tools.md)） |
| 只是一个好用的终端界面 | Windows Terminal 作为宿主，里面放 Powershell/WSL/CMD 三个 profile |

---

## Links

- [WSL](/docs/CS/OS/Windows/WSL.md)
- [Windows 工具链](/docs/CS/OS/Windows/Tools.md)
- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows](/docs/CS/OS/Windows/Windows.md)
- [命令与 ELF](/docs/CS/OS/command.md)
- [Shell 与终端](/docs/CS/OS/Linux/Tools/README.md)

---

## References

1. [What is PowerShell?](https://learn.microsoft.com/en-us/powershell/scripting/overview)
2. [PowerShell 7 installation](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-windows)
3. [Windows Terminal overview](https://learn.microsoft.com/en-us/windows/terminal/)
4. [Windows Commands reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/windows-commands)
