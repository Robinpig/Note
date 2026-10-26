## Introduction

macOS 从 **10.15 Catalina** 起把默认 shell 从 bash 换成了 zsh。官方说法是授权原因（bash 4 起是 GPLv3，Apple 分发 GPLv3 软件有附加义务），直接结果是系统自带的 bash 永远停在 3.2：

```shell
$ /bin/bash --version
GNU bash, version 3.2.57(1)-release (arm64-apple-darwin24)

$ echo $SHELL
/bin/zsh
$ /bin/zsh --version
zsh 5.9 (arm64-apple-darwin24.0)
```

需要 bash 4/5 特性（关联数组、新 `mapfile` 等）只能从 [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md) 另装一份，不要试图替换 `/bin/bash`——它在 SIP 保护下，而且系统脚本依赖它。

## Startup Files and path_helper

zsh 的启动文件加载顺序是固定的：

| 文件 | 何时加载 | 典型用途 |
| :--- | :--- | :--- |
| `/etc/zshenv`、`~/.zshenv` | **总是**，包括非交互脚本 | 只放必须的环境变量 |
| `/etc/zprofile`、`~/.zprofile` | 登录 shell | `PATH` 之类一次性设置 |
| `/etc/zshrc`、`~/.zshrc` | 交互 shell | 别名、提示符、插件 |
| `/etc/zlogin`、`~/.zlogin` | 登录 shell 的最后 | 启动消息 |

macOS 特有的坑在 `path_helper`。`/etc/profile`（以及 zsh 对应的 profile）会执行：

```shell
if [ -x /usr/libexec/path_helper ]; then
	eval `/usr/libexec/path_helper -s`
fi
```

它读取 `/etc/paths` 与 `/etc/paths.d/*`，**把里面的系统路径前置到 PATH 最前面**，同时去掉重复项。后果是：你在 `.zshrc` 里 `export PATH="/my/tool:$PATH"` 加的路径，可能被挤到系统路径后面，于是 `/usr/bin` 里的 BSD 版命令反而优先。本机实测 `path_helper` 的输出开头是：

```
/usr/local/bin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:...
```

注意 `/System/Cryptexes/App/usr/bin`——这是 macOS 的 Cryptex 机制（系统组件可以独立于系统卷更新），见 [File System](/docs/CS/OS/mac/File_System.md)。

> [!WARNING]
>
> `~/.zshenv` 会被**每一个** zsh 进程读取，包括 shell 脚本与工具内部启动的子 shell。把 `echo`、`PATH` 追加或耗时逻辑写在里面，会让所有脚本变慢并在输出里插入多余内容。`PATH` 的追加应放在 `~/.zprofile`（登录 shell 只跑一次），别名与插件放 `~/.zshrc`。

## GUI Apps Do Not Inherit Shell PATH

这是 macOS 上最常被误判为"软件坏了"的问题：从 Dock 或 Finder 启动的 GUI 应用，**继承的不是你 shell 的 PATH**，而是 launchd 的 PATH。所以命令行里能跑的命令，在 VS Code 的集成终端、IDE 的外部工具、或某个 GUI 程序的子进程里可能找不到。

`launchctl` 那侧的 PATH 与 shell 里的是两套：

```shell
launchctl getenv PATH      # 看 launchd 域里的 PATH
launchctl setenv PATH "$PATH"    # 临时同步（重启后失效）
```

真正持久的做法是把 PATH 写进 `/etc/paths.d/`（新增一个文件，每行一个路径），让 `path_helper` 在每次启动时带上它。改完需要重新登录才生效。

## Terminal Emulators

| 终端 | 特点 |
| :--- | :--- |
| **Terminal.app** | 系统自带，够用但功能有限（无分屏、主题弱） |
| **iTerm2** | 老牌第三方，分屏、触发词、图片内联、强配置能力 |
| **Warp** | Rust 写，把命令输出做成可交互区块，带 AI 补全（部分功能需登录） |
| **Kitty / Alacritty** | GPU 渲染，配置靠纯文本文件，适合键盘流 |
| **Hyper** | 基于 Electron，插件生态丰富，启动与内存开销较大 |

本机实测装了 iTerm.app 与 Hyper.app。选择上真正的分水岭是**渲染方式**：Terminal.app 与 iTerm2 走原生渲染，Kitty/Alacritty 走 GPU，Hyper 走 Electron——长输出滚动与高刷屏场景下的差异很明显。

## oh-my-zsh

oh-my-zsh 是 zsh 的配置框架，本身不提供功能，靠插件补齐（本机实测 `~/.oh-my-zsh` 已安装）：

```shell
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

常用插件与它们的加载位置有讲究——**语法高亮必须放最后**，否则它会包裹后续插件的补全逻辑：

```shell
plugins=(git zsh-autosuggestions zsh-syntax-highlighting)
```

| 插件 | 作用 |
| :--- | :--- |
| `git` | 大量 git 别名与提示符分支显示 |
| `zsh-autosuggestions` | 基于历史命令的灰色提示，按 → 补全 |
| `zsh-syntax-highlighting` | 命令语法着色，写错能立刻看出来 |
| `autojump` / `z` | 目录跳转，`j <片段>` 直达 |

主题相关的提示符定制通常在 `~/.oh-my-zsh/themes/<name>.zsh-theme` 里，例如 agnoster 主题的 `prompt_dir()` 用 `%~` 显示完整路径，改成 `%1d` 就只显示当前目录名——路径很深时这一改能省掉大半行宽。

## tmux

tmux 不是系统自带的，需要 `brew install tmux`。它在 macOS 上的主要注意点是**剪贴板**：tmux 自己的 buffer 与系统剪贴板不通，跨窗格复制要走 `pbcopy`：

```shell
# ~/.tmux.conf，让复制直接进系统剪贴板
bind -T copy-mode-vi y send-keys -X copy-pipe-and-cancel "pbcopy"
```

另一个 macOS 特有问题是**会话里的 GUI 程序**：tmux 会话不隶属于 GUI 域，会话里启动的进程无法正常调用 `open` 或访问剪贴板服务，这类操作要放到 tmux 之外执行。

## Login Shell and Terminal Startup

Terminal.app 与 iTerm2 默认把每个新窗口开成**登录 shell**（会读 `.zprofile`），而其他一些终端默认是非登录 shell（只读 `.zshrc`）。这解释了同一个配置在 iTerm2 里生效、在 VS Code 集成终端里不生效的原因——检查位置是终端偏好设置里的 "Shells open with: login shell"。

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md)
- [Software](/docs/CS/OS/mac/Tools/Software.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)
- [File System](/docs/CS/OS/mac/File_System.md)

## References

1. [zsh 手册](https://zsh.sourceforge.io/Doc/Release/index.html)
2. [Use zsh as the default shell on your Mac](https://support.apple.com/en-us/102360)
