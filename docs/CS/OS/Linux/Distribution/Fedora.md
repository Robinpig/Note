## Introduction

Fedora 是 Red Hat 赞助、社区主导的**上游发行版**：新内核、新工具链（GCC/systemd/ Wayland 等）总是先在 Fedora 落地验证，成熟后再进入 RHEL。约每 6 个月一个版本，每个版本维护约 13 个月。

理解它在 Red Hat 系里的位置：**Fedora（试验田）→ RHEL（企业稳定版）→ Rocky/Alma/CentOS Stream（免费生态）**。想第一时间用上最新内核特性（如 EEVDF、sched_ext、io_uring 演进，见 [调度器](/docs/CS/OS/Linux/proc/sche.md)、[io_uring](/docs/CS/OS/Linux/IO/io_uring.md)），Fedora 和 [Arch](/docs/CS/OS/Linux/Distribution/Arch.md) 是最方便的两个选择。

包管理用 `dnf`（yum 的现代替代）：

```shell
dnf search <pkg>          # 搜索
dnf install <pkg>         # 安装
dnf upgrade               # 全系统升级
rpm -ivh x.rpm            # 本地 rpm（不解决依赖）
```

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)
- [Rocky Linux](/docs/CS/OS/Linux/Distribution/Rocky.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
