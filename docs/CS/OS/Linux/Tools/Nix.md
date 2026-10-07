## Introduction

Nix 是一个**函数式、声明式、可复现**的包管理器。它把"软件包如何构建"建模为纯函数：输入（源码、依赖、构建脚本、编译器版本）相同，输出（构建产物）必然相同。与 `apt`/`dnf`/`pacman` 等命令式包管理器（现场修改全局 `/usr`）不同，Nix 把一切装进内容寻址的 `/nix/store`。

核心特性：

- **内容寻址 store**：`/nix/store/<hash>-<name>-<version>`，哈希由所有依赖与构建参数算出，哈希相同即内容相同；
- **依赖隔离**：每个包的依赖各自独立存放，升级库不会破坏依赖旧版的程序，从根上消除"DLL 地狱"；
- **可复现构建**：同一份描述在任何机器、任何时间构建结果一致；
- **事务式**：安装 / 升级先写新路径再切换符号链接（用户 profile / 系统 `current-system`），失败可整体回退。

## Basic Concepts

```shell
ls /nix/store/                 # 每个条目形如 <hash>-<name>-<version>
# 9a3...-coreutils-9.5         —— 哈希相同 = 内容相同，可被多环境共享
```

- **derivation（衍生）**：Nix 构建的基本单元，描述"从哪些输入产出哪个输出"，是一个 `.drv` 文件；
- **store path**：构建产物在 `/nix/store` 下的实际路径，被其内容的哈希前缀唯一标识；
- **profile**：一组 store path 的符号链接集合（用户环境 `~/.nix-profile`、系统 `/run/current-system`），切换即"换环境"。

## Common Commands

```shell
nix-env -iA nixpkgs.vim       # 装包到用户 profile（类传统，但不作为真理来源）
nix-shell -p python3          # 临时进入含 python3 的 shell（不影响系统）
nix build nixpkgs#hello       # 纯构建，结果软链到 ./result
nix run nixpkgs#htop          # 临时运行，不持久安装
nix develop                   # 进入含 devShell 的开发环境（替代 venv / asdf）
nix-collect-garbage           # 回收不再被任何 profile 引用的 store 路径
```

## Flakes (Modern Practice)

用 `flake.nix` 声明输入源与版本锁（`flake.lock`），让构建在任意机器可复现：

```nix
# flake.nix（节选）
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
  outputs = { self, nixpkgs }: {
    packages.x86_64-linux.hello = nixpkgs.legacyPackages.x86_64-linux.hello;
  };
}
```

```shell
nix build .#hello             # 基于 flake 构建
nix develop .                # 可复现开发环境
```

## home-manager

把 shell、编辑器、dotfiles 等**用户级配置**也写成 Nix 表达式，与系统配置同源、可版本化：

```nix
# home.nix（节选）
{ pkgs, ... }: {
  home.packages = [ pkgs.git pkgs.neovim ];
  programs.zsh.enable = true;
}
```

## Runtime Platform

Nix 不绑定 NixOS——可在任意 Linux 发行版（Ubuntu / Fedora / Rocky 等）乃至 macOS 上安装，用于可复现的开发环境、CI 依赖与构建缓存；真正的"整系统声明式"则由 [NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md) 在它之上实现。与 [容器](/docs/CS/Container/Container.md) 互补：Nix 可导出确定性镜像，但粒度在"包 / 配置"层而非"整机快照"层。

## Links

- [NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Nix 手册](https://nixos.org/manual/nix/stable/)
2. [NixOS 官网](https://nixos.org/)
