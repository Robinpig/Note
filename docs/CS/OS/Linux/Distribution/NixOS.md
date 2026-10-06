## Introduction

NixOS 是基于 [Nix](/docs/CS/OS/Linux/Tools/Nix.md) 函数式包管理器的 Linux 发行版，最大特点是**整系统声明式配置 + 可复现构建**。它把 Nix 的"包可复现"能力上升到"整个操作系统可复现"：不仅软件包，连服务、用户、内核参数、网络配置都写进同一份声明式描述。

与传统的 FHS 发行版（全局共享 `/usr`、`/lib`）不同，NixOS 的软件来自 `/nix/store`，系统状态由 `/etc/nixos/configuration.nix` 这一份文件推导出来。

核心思想：

- **声明式系统**：系统该长什么样写在一个文件里，执行 `nixos-rebuild switch` 让它"变成"那个状态；
- **可复现**：相同配置在任何机器、任何时间构建出相同的系统；
- **原子升级与回滚**：每次 `nixos-rebuild` 生成一个新"代际（generation）"，出问题时整体回退。

## 系统配置与代际

（Nix 包管理器本身的 store、flakes、home-manager 等概念见 [Nix](/docs/CS/OS/Linux/Tools/Nix.md)。）

```shell
# 编辑声明式配置后应用
nixos-rebuild switch             # 立即切换到新配置（生成新代际）
nixos-rebuild boot               # 下次启动生效
nixos-rebuild test               # 临时测试，回滚计时器到点自动还原
nixos-rebuild switch --rollback  # 回退到上一可用代际
```

- 配置入口 `/etc/nixos/configuration.nix`：声明要装哪些包、开哪些服务、设哪些选项；
- 模块化：大量 `services.*` / `programs.*` / `boot.*` 选项开箱即用，社区模块可扩展；
- 代际：每次切换写入一个生成项，`/run/current-system` 指向当前代际，启动菜单可选旧代际整体回退。

## 发布节奏

两个 channel：**stable**（每半年一个版本，代号取自花卉）与 **unstable**（跟随 master，滚动更新）。

支持期**只有 7 个月**（比滚动发行版的"无固定周期"更严格）：

| 版本 | 代号 | 发布 | 支持至 |
| :-- | :-- | :-- | :-- |
| NixOS 25.11 | Xantusia | 2025-11 | 2026-06-30（已 EOL） |
| **NixOS 26.05** | **Yarara** | **2026-05-30** | **2026-12-31** |

**NixOS 的支持期是全发行版里最短的**（7 个月），因为它靠"可复现构建 + 声明式升级"而非长期维护某一代来保证可靠性 —— 需要长期支持得自己做版本锁定或用 NixOps/colmq 之类的工具。

### 26.05 的两个要点

- **initrd 默认基于 systemd** —— 旧脚本实现已废弃，计划 26.11 移除。这意味着 initrd 生成路径变了，自定义 initrd 的做法要跟着改。
- **弃用 x86-darwin** —— 26.05 是最后一个支持版本，26.11 起不再构建。（Nixpkgs 本身仍可单独用于其他 Linux 与 macOS，这与 NixOS 发行版是两件事。）

## 适用场景

- 需要可复现、可版本化基础设施的服务器 / 集群；
- 开发环境：用 [Nix](/docs/CS/OS/Linux/Tools/Nix.md) 的 `nix-shell` / `flake.nix` 一键还原项目依赖，新人免配环境；
- 与 [容器](/docs/CS/Container/Container.md) 互补：Nix 可导出确定性镜像，但粒度在"包 / 配置"层而非"整机快照"层。

## 排障速查

```shell
# 当前代际
nixos-version
readlink /run/current-system
nix-env -q --installed             # 当前环境的包
nix-store -q --references /run/current-system

# 代际管理
nixos-rebuild list-generations
nixos-rebuild list-profiles
nix profile list                  # profile 世代
# 回滚：启动时选旧代际，或
sudo nixos-rebuild switch --rollback

# 通道
nix-channel --list
sudo nix-channel --set nixos-25.11 nixpkgs

# 搜索包
nix-env -qa -n chromium           # 按名
nix search nixpkgs ripgrep        # 查 nixpkgs
nix search nixpkgs '^firefox$' --regex

# GC（NixOS 的磁盘杀手）
nix-collect-garbage -d            # 删不可达路径
nix-store --gc --print-dead      # 先看会删什么
# 关键：不要删 /nix/var/nix/profiles 之外的 system
```

## 与其它子系统的接缝

- Nix 的 store 与 flakes 见 [Nix](/docs/CS/OS/Linux/Tools/Nix.md)；
- NixOS 的 systemd 服务管理与 cgroup 委派见 [systemd](/docs/CS/OS/Linux/Tools/systemd.md) 与 [cgroup 委派实践](/docs/CS/OS/Linux/cgroup/delegation.md)；
- 声明式配置思想与 [btrfs 快照](/docs/CS/OS/Linux/fs/btrfs.md) 的"可回退"是同一类问题的两种解法。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Nix（包管理器）](/docs/CS/OS/Linux/Tools/Nix.md)
- [Arch（理念相反的独立系）](/docs/CS/OS/Linux/Distribution/Arch.md)
- [systemd](/docs/CS/OS/Linux/Tools/systemd.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [NixOS 官网](https://nixos.org/)
2. [NixOS 26.05 release announcement](https://nixos.org/blog/announcements/2026/nixos-2605)
3. [Nix 手册 — Package management](https://nix.dev/manual/nix/stable/package-management)
4. [NixOS Wiki — Release channels](https://nixos.wiki/wiki/NixOS/Release)
