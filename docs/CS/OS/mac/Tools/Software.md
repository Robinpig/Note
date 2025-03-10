## Introduction



查看服务进程

```shell
launchctl list | grep <service>
```

停止/启动进程

```shell
launchctl stop/start <service>
```





## Install Tools

## Homebrew

<!-- tabs:start -->

###### **Traditional**

Install tutorial:

> https://mirrors.tuna.tsinghua.edu.cn/help/homebrew/

Homebrew-bottles mirror:

```shell
echo 'export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"' >> ~/.zprofile
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"
```

###### **Quick Script**

Otherwise:

```shell
/bin/zsh -c "$(curl -fsSL https://gitee.com/cunkai/HomebrewCN/raw/master/Homebrew.sh)"
```


##### **Uninstall**

```shell
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)"
```

<!-- tabs:end -->



tap

当tap了多个版本, riscv/riscv和riscv-software-src/riscv时会报错

>  homebrew Formulae found in multiple taps:

此时需要untap任意一个之后方可



### 多版本

参考:

> https://idayer.com/homebrew-x86-arm/



x86和ARM版本

|              | x86                                                          | ARM                                                          |
| ------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 命令路径     | /usr/local/bin/brew                                          | /opt/homebrew/bin/brew                                       |
| 安装脚本     | arch -x86_64 /bin/bash -c "$(curl -fsSL https://gitee.com/ineo6/homebrew-install/raw/master/install.sh)" | /bin/bash -c "$(curl -fsSL https://gitee.com/ineo6/homebrew-install/raw/master/install.sh)" |
| 安装软件路径 | /usr/local/Cellar                                            |                                                              |
|              |                                                              |                                                              |

共存方案 



执行如下命令进入

```shell
arch -x86_64 zsh
```

使用别名来调用不同的brew

别名脚本

```shell
cat << 'EOF' >> ~/.zshrc
alias abrew='arch -arm64 /opt/homebrew/bin/brew'
alias ibrew='arch -x86_64 /usr/local/bin/brew'
EOF

# 生效
source ~/.zshrc
```



安装的软件路径

### ohmyzsh

```shell
git clone https://mirrors.tuna.tsinghua.edu.cn/git/ohmyzsh.git
cd ohmyzsh/tools
REMOTE=https://mirrors.tuna.tsinghua.edu.cn/git/ohmyzsh.git sh install.sh
```

### autojump

1. make sure [Homebrew](/docs/CS/OS/mac/Tools/Software.md?id=Homebrew) already installed
2. vim .zshrc
   1. Add autojump after `plugins=`, for example plugins=(git autojump)
   2. Add a new row below `[[ -s $(brew --prefix)/etc/profile.d/autojump.sh ]] && . $(brew --prefix)/etc/profile.d/autojump.sh`
   3. `wq`

通过 `j -a <dir>` 添加快速路径

`j -s` 查看统计

## iTerm2

下载

为 iTerm2 配置 Solarize 主题

## 主题美化


主题美化 设置 `.zshrc` 

```
ZSH_THEME="agnoster"
```

推荐补全

```shell
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
```
在 `.zshrc` 中插件 增加zsh-autosuggestions
```
plugins=([plugins...] zsh-autosuggestions)
```

语法高亮

```shell
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting
```

在 `.zshrc` 中插件**最后面** 增加zsh-autosuggestions

```
plugins=( [plugins...] zsh-syntax-highlighting)
```

文件路径太长，只显示当前文件夹名

打开主题配置文件，比如我的是 `agnoster.zsh-theme` ：

```shell
vim ~/.oh-my-zsh/themes/agnoster.zsh-theme
```

将文件里的 `%~` 修改成 `%1d`

```shell
# Dir: current working directory
prompt_dir() {
  # prompt_segment blue $CURRENT_FG '%~'   # Original code
  prompt_segment blue $CURRENT_FG '%1d'    # Modified code
}
```





## Monitor Tools

- iStat Menu
- Better MenuBar(Apple Store)
- [SMCAMDProcessor](https://github.com/trulyspinach/SMCAMDProcessor) 适用AMD CPU

## Markdown

- Typora
- Marked 2
- [Glow](https://github.com/charmbracelet/glow) is a terminal based markdown reader designed from the ground up to bring out the beauty—and power—of the CLI.

## Read



PDF Reader

- PDF Reader Pro
- PDF Expert

Epub

- Apple Books
- Calibre



## Disk



分析

- CleanMyMac
- Disk Graph
- Disk Space Analyzer PRO

## Others

- Magnet
- [MonitorControl](https://github.com/MonitorControl/MonitorControl)
- Dynamic Wallpaper
- OneSwitch
- ~~V2rayU~~
- ClashX
- [keka](https://www.keka.io/zh-cn/) 压缩文件管理器

## Developer

- Navicat Premium
- [MySQL](https://dev.mysql.com/downloads/mysql/)
- [Postman](https://www.postman.com/downloads/?utm_source=postman-home)
- Charles
- Dash

### Visual Studio Code

For example: https://vscode.cdn.azure.cn/stable/3866c3553be8b268c8a7f8c0482c0c0177aa8bfa/VSCode-darwin-arm64.zip

Replace https://az764295.vo.msecnd.net by https://vscode.cdn.azure.cn.

The mirror url:

https://vscode.cdn.azure.cn/stable/3866c3553be8b268c8a7f8c0482c0c0177aa8bfa/VSCode-darwin-arm64.zip

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
