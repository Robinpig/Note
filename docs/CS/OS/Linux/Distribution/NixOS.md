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

两个 channel：**stable**（如 24.05、25.05，每半年一个版本，代号取自花卉）与 **unstable**（跟随 master，滚动更新）。

## 适用场景

- 需要可复现、可版本化基础设施的服务器 / 集群；
- 开发环境：用 [Nix](/docs/CS/OS/Linux/Tools/Nix.md) 的 `nix-shell` / `flake.nix` 一键还原项目依赖，新人免配环境；
- 与 [容器](/docs/CS/Container/Container.md) 互补：Nix 可导出确定性镜像，但粒度在"包 / 配置"层而非"整机快照"层。

与 [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) 同属"独立系"，但理念相反：Arch 追求"你亲手拼出系统、滚动最新"，NixOS 追求"声明系统、构建可复现"——一个重过程，一个重结果。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [NixOS 官网](https://nixos.org/)
