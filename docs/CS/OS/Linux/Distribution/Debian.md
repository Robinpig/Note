## Introduction

Debian 由社区驱动，1993 年发起，坚持自由软件原则与"稳定压倒一切"的发布哲学。它是整个 Debian 系的**母发行版** —— [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)、[Kali](/docs/CS/OS/Linux/Distribution/Kali.md)、[Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md) 都从它派生，共享 `apt`/`dpkg` 生态。

版本事实（2026-10 核实）：

| 项 | 值 |
| :-- | :-- |
| 当前 stable | **Debian 13 "trixie"**（13.7，2026-09-12） |
| 内核 | **6.12 LTS** 系列 |
| 官方架构 | amd64 / arm64 / armel / armhf / ppc64el / **riscv64**（trixie 首次官方支持）/ s390x |
| testing | forky（预计成为 Debian 14） |
| unstable | sid |

## Three-branch Model

| 分支 | 别名 | 定位 |
| :-- | :-- | :-- |
| stable | 玩具总动员角色命名（bookworm、trixie…） | 生产可用。**3 年 full support + 2 年 LTS = 共 5 年** |
| testing | 下一版 stable 的孵化场（当前 forky） | 软件较新，自动化测试通过即入 |
| unstable | sid | 开发者滚动提交入口，**不保证可用** |

Ubuntu 每次从 Debian unstable/testing 冻结快照再加工，Kali 则基于 testing 滚动 —— 理解这三条线就看懂了整个 Debian 系的"血缘"。

### The Truth About the Support Cycle

"Debian 支持 5 年"常被简化成一句话，实际是**两段不同范围**的支持：

- **full support（3 年）**：全部包由 Debian 安全团队维护，覆盖所有架构；
- **LTS（再 2 年）**：**只有仍有活跃 sponsor 的包**被维护，架构范围也收窄。

所以"某个包在 LTS 期间是否还更新"要查 [Debian LTS tracker](https://wiki.debian.org/LTS)，不能假设全覆盖。超出 5 年后有商业 ELTS（Freexian 提供，非官方）可延到 10 年。

**LTS 交接有过一次特例**：Debian 12 bookworm 的 3 年 full support 在 2026-07 结束后，**2026-07-12 起移交给 LTS 团队**。Debian 11 bullseye 已在 2026-08-31 EOL。

## riscv64 Officially Supported for the First Time

trixie 最大的架构变化：**riscv64 首次成为官方架构**，共 7 个。

同时 **i386 不再是常规架构** —— 没有官方内核与安装器，只能作为 amd64 上的 32 位 userland 使用。**trixie 也是 armel 的最后一个版本**。

这三条合在一起说明 Debian 正在收缩老架构支持：内核与工具链的构建成本高，维护收益低。

## Package Management

```shell
apt search <keyword>          # 搜索
apt install <pkg>             # 安装（自动解决依赖）
apt remove <pkg>              # 卸载，保留配置
apt purge <pkg>               # 卸载并删配置
apt update && apt upgrade     # 刷新索引并升级
apt full-upgrade              # 会删除冲突包，生产升级更彻底
dpkg -i x.deb                 # 安装本地 deb（不解决依赖）
dpkg -l | grep <pkg>          # 查询已安装
apt-cache policy <pkg>        # 看候选版本与来源优先级
```

> `apt upgrade` **不会删除**已安装的包，`apt full-upgrade` 会 —— 需要跨发行版升级时用后者。

### Image Structure

`deb.debian.org` 上按 `dists/` 与 `pool/` 组织：

```
dists/trixie/main/binary-amd64/Packages     # 索引
dists/trixie/main/binary-amd64/Release     # 签名与校验和
pool/main/<首字母>/<源包>/<文件>.deb        # 实际包文件
```

`apt update` 拉的是索引（`Packages` / `Release`），包本体在 `pool/`。**手动做本地源时要按这个结构组织**，否则 `apt` 找不到（现代系统用 deb822 格式写在 `/etc/apt/sources.list.d/*.sources`）。

## Kernel and Security Hardening

trixie 的内核加固**随架构走**：

- **amd64**：CET（控制流增强）
- **arm64**：PAC / BTI（指针认证与分支目标标识）
- **riscv64**：首次支持，随架构做适配

内核走 **6.12 LTS**（长支持分支）而非上游最新 —— 这是"稳定优先"哲学的直接体现：选 LTS 以避免内核 regression 打到生产。代价是新内核特性要等 LTS 回合才可用。

配置取向与另两个系形成对照：Debian 相对保守、模块打包为 `linux-image-*`；RHEL 系是"内核 ABI 冻结 + 大量 out-of-tree backport"；Fedora 则是"启用一切新上游特性"。

## Interfaces with Other Subsystems

- 内核版本决定可用特性：EEVDF（6.6+）、MGLRU（6.1+）、sched_ext（6.12+）在 6.12 上都可用，见 [sche](/docs/CS/OS/Linux/proc/sche.md)。
- 架构列表影响 [namespace 与 idmapping](/docs/CS/OS/Linux/namespace.md) 的可用性。
- 派生发行版的内核策略差异见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)。

## Troubleshooting Quick Reference

```shell
# 版本与来源
cat /etc/debian_version
lsb_release -a                        # 发行版信息
dpkg --print-architecture             # dpkg 架构（可能与 kernel arch 不同）
uname -r                              # 内核版本

# 包状态
apt-cache policy <pkg>                # 候选版本与来源
apt-mark showhold                     # 被 hold 的包（升级不动时查）
dpkg -l | grep '^ii' | wc -l         # 已安装包数
apt-get check                         # 依赖完整性

# 源与镜像
cat /etc/apt/sources.list
ls /etc/apt/sources.list.d/           # deb822 格式（.sources）

# 架构相关
dpkg --print-foreign-architectures     # 启用的外部架构（armhf 等）
apt-cache showsrc <pkg> | grep -i arch # 源包支持的架构
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)
- [Kali](/docs/CS/OS/Linux/Distribution/Kali.md)
- [Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Debian 官网](https://www.debian.org/)
2. [Updated Debian 13: 13.7 released](https://debian.org/News/2026/20260912)
3. [DebianTrixie — Debian Wiki](https://wiki.debian.org/DebianTrixie)
4. [Debian LTS](https://wiki.debian.org/LTS)
