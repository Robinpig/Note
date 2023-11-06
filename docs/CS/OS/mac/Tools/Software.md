## Introduction

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

## Monitor Tools

- iStat Menu
- Better MenuBar(Apple Store)
- [SMCAMDProcessor](https://github.com/trulyspinach/SMCAMDProcessor)

Disk

- Disk Space Analyzer PRO

## Markdown

- Typora
- Marked 2
- [Glow](https://github.com/charmbracelet/glow) is a terminal based markdown reader designed from the ground up to bring out the beauty—and power—of the CLI.

PDF Reader

- PDF Reader Pro
- PDF Expert

## Others

- Magnet
- [MonitorControl](https://github.com/MonitorControl/MonitorControl)
- Dynamic Wallpaper
- OneSwitch
- V2rayU

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
