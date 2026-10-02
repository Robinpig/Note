## Introduction

Omarchy 是一个 **omakase（主厨定食）风格**的桌面 Linux 发行版，由 DHH（David Heinemeier Hansson，Ruby on Rails / 37signals 创始人）发起。它以 **Arch Linux 为底 + Hyprland 平铺式 Wayland 合成器 + Quickshell 桌面壳**为核心，开箱即带一套精心挑选、键盘驱动的完整开发桌面，让用户省去自己拼装 dotfile 的时间。

- 首发：2025 年 6 月 26 日，最初是 Arch + Hyprland 的"安装后配置"，后演进为自带安装镜像与软件仓库的完整发行版；
- 治理：早期由 Basecamp 孵化，2026 年 8 月成立非营利 **Omacom Foundation**，源码迁到该基金会的 GitHub 组织；
- 定位：不是追求"像 Windows / macOS 一样熟悉"，而是追求美观、高效、TUI 与平铺窗口重度结合的工作方式。

"omakase"与 [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) 原生 KISS/手动装配哲学恰好互补：Arch 给你最小底座自己拼，Omarchy 直接端上一套作者本人每天在用的成品配置。

## 技术栈

- **基座**：Arch Linux，滚动更新，安装时从 Arch 仓库拉取最新包；
- **合成器**：Hyprland——平铺窗口、动画、键盘优先，工作区与启动器基本绑在 `Super` 键；
- **桌面壳**：Quickshell（QML 实现）——4.0 起统一承担状态栏、启动器、通知等组件，替代此前多个独立部件；
- **文件系统 / 回滚**：Btrfs + Snapper 快照，配 Limine 引导，改动可快速回退；
- **系统工具**：大量用 shell 脚本，提供统一 CLI；主题（Tokyo Night、Catppuccin、Everforest 等）一键全局生效。

预装软件面向现代开发者：Neovim、Chromium、Obsidian、LibreOffice、Kdenlive、OBS Studio、Docker、Starship、btop，并集成 AI coding agent。3.7（2026 年 5 月）加入统一命令行界面并扩展游戏支持（Steam / Proton / Gamescope）。

## 版本

当前主线 **4.0**（2026 年 8 月发布，Quickshell 桌面壳）。包管理沿用 Arch 的 `pacman` + AUR。

## 适用场景

- 想要 Hyprland 平铺桌面、又不想花时间手动调 dotfile 的开发者；
- 偏好键盘驱动、终端重度、主题统一的工作流；
- 当作"带观点的 Arch 成品"快速体验现代 Wayland 桌面。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Omarchy 官网](https://omarchy.org/)
2. [Omarchy 手册](https://omarchy.org/manual/)
3. [Omarchy GitHub](https://github.com/omacom/omarchy)
