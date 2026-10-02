## Introduction

Debian 是由社区驱动的老牌发行版（1993 年发起），坚持自由软件原则与"稳定压倒一切"的发布哲学。[Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)、[Kali](/docs/CS/OS/Linux/Distribution/Kali.md)、[Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md) 等大量发行版都直接从 Debian 派生，共享 `apt`/`dpkg` 生态。

## 三分支模型

| 分支 | 别名 | 定位 |
| :-- | :-- | :-- |
| stable | 以玩具总动员角色命名（bookworm、trixie…） | 生产可用，约 2 年一大版，只收安全修复 |
| testing | 下一版 stable 的孵化场 | 软件较新，偶有滞后（安全补丁经 unstable 转入） |
| unstable | sid | 开发者滚动提交入口，不保证可用 |

Ubuntu 每次从 Debian unstable/testing 冻结快照再加工，Kali 则基于 testing 滚动——理解这三条线就看懂了整个 Debian 系的"血缘"。

## 包管理

```shell
apt search <keyword>          # 搜索
apt install <pkg>             # 安装（自动解决依赖）
apt remove / purge <pkg>      # 卸载 / 连配置一起删
apt update && apt upgrade     # 刷新索引并升级
dpkg -i x.deb                 # 安装本地 deb（不解决依赖）
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
