## Introduction

Homebrew 是 macOS 上事实上的第三方包管理器，但它不是系统的一部分——`brew` 装的东西与系统自带的 `/usr/bin` 完全隔离，靠 `PATH` 顺序决定谁优先。这个隔离既是它的优点（不会污染系统、SIP 下也能装），也是"命令行为不对"的第二大来源：你可能同时装了 BSD 版和 GNU 版的同一个命令，而调用哪一份取决于 `PATH` 里谁在前面。

```shell
$ which -a sed
/usr/bin/sed                                 # BSD，系统自带
/opt/homebrew/opt/gnu-sed/libexec/gnubin/sed # GNU，Homebrew 装的
```

## Prefix and Architecture

**Apple Silicon 与 Intel 的前缀不同**，这是最容易踩的一处：

| | Apple Silicon（arm64） | Intel / Rosetta 2（x86_64） |
| :--- | :--- | :--- |
| 安装前缀 | `/opt/homebrew` | `/usr/local` |
| brew 路径 | `/opt/homebrew/bin/brew` | `/usr/local/bin/brew` |
| Cellar | `/opt/homebrew/Cellar` | `/usr/local/Cellar` |

选择依据是**当前 shell 的架构**，不是机器架构：在 Apple Silicon 上跑 `arch -x86_64 zsh` 后再安装，就会装到 `/usr/local` 且是 x86_64 的二进制。

> [!NOTE]
>
> 本机（macOS 15.3.1，M1 Pro）实测**两版并存**，正好是个现实例子：
>
> ```shell
> $ /usr/local/bin/brew --version    && /usr/local/bin/brew config | grep -E 'CPU|Rosetta'
> Homebrew 7.0.4
> CPU: octa-core 64-bit westmere
> Rosetta 2: true                    # 这一版整个跑在转译层下
>
> $ /opt/homebrew/bin/brew --version && /opt/homebrew/bin/brew config | grep -E 'CPU|Rosetta'
> Homebrew 6.0.6
> CPU: octa-core 64-bit arm_firestorm_icestorm
> Rosetta 2: false                   # 原生 arm64
> ```
>
> 注意两版版本号不一致（7.0.4 与 6.0.6）——它们是各自独立升级的，互不感知。

## Multiple Versions

两版共存时靠别名区分（写入 `~/.zshrc`）：

```shell
alias abrew='/opt/homebrew/bin/brew'                    # ARM
alias ibrew='arch -x86_64 /usr/local/bin/brew'          # Intel
```

`arch -x86_64` 前缀的作用是强制以 x86_64 启动，Rosetta 2 会自动介入。判断某条命令当前跑在哪个架构下：

```shell
arch                        # 显示当前架构
sysctl sysctl.proc_translated    # 1 表示当前进程正在被 Rosetta 转译
```

> [!WARNING]
>
> **不要在同一前缀下混装两种架构的 bottle。** 判断依据是 `brew config` 里的 `CPU` 与 `Rosetta 2` 两行：只要 `Rosetta 2: true`，这个 brew 装出来的就全是 x86_64 二进制。给本机装软件一律用 `/opt/homebrew` 那一版；只有确实需要 x86 依赖（比如某个闭源软件只提供 x86 dylib）时才动用 `ibrew`。

## Core Concepts

| 概念 | 含义 |
| :--- | :--- |
| **formula** | 命令行软件的构建脚本（Ruby DSL），装到 Cellar 后软链到 prefix 的 `bin`/`lib` |
| **bottle** | 预编译好的二进制包，命中则跳过本地编译。不匹配当前平台时会回退到源码编译，耗时显著变长 |
| **cask** | GUI 应用与大型二进制（`.app`、字体、驱动），本质是下载并放到 `/Applications` |
| **tap** | 第三方 formula 仓库，`brew tap <user>/<repo>` 后即可安装其 formula |

同一个 formula 出现在多个 tap 里会报 `Formulae found in multiple taps`，此时需要 `brew untap` 掉其中一个才能继续。

常用操作：

```shell
brew install <formula>            # 装命令行软件
brew install --cask <cask>        # 装 GUI 应用
brew uninstall <formula>
brew upgrade                      # 升级全部
brew list --formula / --cask      # 分别列出
brew info <formula>               # 看依赖、安装路径、bottle 是否命中
brew deps --tree <formula>        # 依赖树
brew outdated                     # 可升级清单
brew cleanup                      # 清理旧版本与下载缓存
```

## Services

`brew services` 是 launchd 的一层封装，与 [Service Management](/docs/CS/OS/mac/Service_Management.md) 里讲的那套是一回事：

```shell
brew services list                       # 看所有受管服务与状态
brew services start nginx                # 注册并启动
brew services restart nginx
brew services stop nginx
```

它生成的 plist 放在 `/opt/homebrew/opt/<formula>/*.plist` 或 `~/Library/LaunchAgents`，本质上是 `launchctl bootstrap` 的包装。因此排查"服务起不来"时，绕开 `brew services` 直接用 `launchctl print gui/$UID/<label>` 看真实原因通常更快。

## GNU Tools via Homebrew

需要 GNU 行为时不要覆盖系统命令，而是按需引入：

```shell
brew install coreutils          # 提供 gstat、gdate 等 g 前缀命令
```

coreutils 默认**不会**把 `sed`/`date` 装成同名命令，而是以 `g` 前缀提供，避免覆盖系统工具。若确实想让 GNU 版优先，需要手动把 gnubin 加进 PATH：

```shell
# ~/.zshrc
export PATH="/opt/homebrew/opt/coreutils/libexec/gnubin:$PATH"
```

> [!WARNING]
>
> 把 gnubin 放到 PATH 最前面会让脚本里所有 `sed`/`date` 变成 GNU 行为，**包括你以为在调 BSD 的那些**。一旦这么做，跨机器共享的脚本就可能在别人机器上失效。更稳的做法是只在需要的脚本里显式写 `gsed`/`gdate`。

## Mirrors

国内网络下常配镜像加速（见 [Software](/docs/CS/OS/mac/Tools/Software.md) 里的安装脚本）。核心是三个环境变量：

```shell
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"
export HOMEBREW_API_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api"
export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/brew.git"
export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/homebrew-core.git"
```

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [CLI](/docs/CS/OS/mac/Tools/CLI.md)
- [Software](/docs/CS/OS/mac/Tools/Software.md)
- [Package](/docs/CS/OS/mac/Package.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)

## References

1. [Homebrew Documentation](https://docs.brew.sh/)
2. [Homebrew Formula Cookbook](https://docs.brew.sh/Formula-Cookbook)
