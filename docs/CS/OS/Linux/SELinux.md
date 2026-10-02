## Introduction

**SELinux**（Security-Enhanced Linux）是一个基于 **MAC（Mandatory Access Control，强制访问控制）** 的内核安全子系统，由美国国家安全局（NSA）发起、在 Linux 2.6 中合入主线。它在内核传统的 **DAC（Discretionary Access Control，自主访问控制）**——即用户/组/其他位（UGO 权限位）、属主、ACL——之外再加一层**由系统策略集中定义、进程自身无法绕过**的访问控制。

核心区别：

- **DAC**：资源属主可以随意修改权限，root（UID 0）几乎能为所欲为；一旦进程被攻破拿到对应权限，它能访问该用户可访问的一切。
- **MAC（SELinux）**：即使是 root，访问也要过策略这一关。每个进程和每个对象都带**安全上下文（security context / label）**，由策略决定"什么类型的进程能对什么类型的对象执行什么操作"，遵循最小权限。

SELinux 通过内核的 **LSM（Linux Security Modules）框架**挂载实现：LSM 在关键内核操作的路径上预留 hook，SELinux（以及 AppArmor、Smack 等）作为一个 LSM 模块实现这些 hook，在 DAC 检查通过后再做强制访问判定。

## Security Context

一切受控对象都有一个标签，形如四段（实际可更多段）：

```
system_u:object_r:httpd_sys_content_t:s0
  用户    角色     类型(最关键)        MLS 级别
```

- **user / role**：SELinux 用户与角色，主要用于 RBAC（基于角色的访问控制），进程侧角色决定能进入哪些域（domain）。
- **type**：最核心的字段。进程的类型又称**域（domain）**，如 `httpd_t`；文件/端口等对象的类型如 `httpd_sys_content_t`、`httpd_port_t`。
- **level / range**：可选的 MLS/MCS（多级/多类别安全），用于不同密级或用类别位隔离实例（容器常用 s0 加随机 category）。

标签来自：文件系统扩展属性（`security.selinux` xattr）、策略中的 `file_contexts` 规则、进程 exec 时的类型切换。常用查看命令：

```bash
ls -Z /var/www/html/index.html      # 文件标签
ps -eZ | grep httpd                 # 进程域
id -Z                               # 当前 shell 的上下文
ss -tlnpZ                           # 端口标签
```

## Type Enforcement

SELinux 的主体策略语言是 **TE（Type Enforcement）**：用 allow 规则描述"源类型 → 目标类型 : 类别 { 权限 }"。

```te
# 允许 httpd 进程(域 httpd_t)读取/获取/执行 httpd_sys_content_t 类型的文件
allow httpd_t httpd_sys_content_t : file { io read getattr lock open };
```

典型语义对照：

- 进程"类型" = 域（domain），exec 一个带特定入口类型（entrypoint）的程序会触发域转移（`type_transition` 或显式 `runcon`），所以一个 daemon 启动后进入受限域而非继承调用者的域。
- 文件默认继承创建目录的类型，也可用 `type_transition` 让特定域在特定目录创建的文件落特定标签。
- 判定逻辑是白名单：**没有显式 allow 即拒绝**，所有拒绝（在 enforcing 模式下）记录为 AVC。

除 TE 外，策略还包含 RBAC（角色约束域）与可选的 MLS/MCS（密级偏序、类别集合）。

## Modes

| 模式 | 行为 |
| --- | --- |
| `enforcing` | 策略生效，违反即拒绝并记录 AVC |
| `permissive` | 不拦截，只记录"本应拒绝"的 AVC，用于调试/上线前观察 |
| `disabled` | 关闭（现代发行版一般不建议直接 disabled，因涉及标签初始化） |

```bash
getenforce                      # 查看当前模式
setenforce 0                    # 运行时切 permissive（重启失效，不重打标签）
# /etc/selinux/config 中 SELINUX=enforcing|permissive|disabled 控制启动
sestatus                        # 查看状态、策略版本、挂载点
```

排错核心是 AVC 日志：

```bash
# RHEL/Fedora 默认审计日志
ausearch -m AVC -ts recent
audit2allow -a                  # 由 AVC 生成"允许规则"（慎用，应先理解）
journalctl -t setroubleshoot    # setroubleshoot 给出的人类可读建议
```

## Booleans and Policy Modules

- **SELinux boolean**：策略里预留的开关，允许在不重新编译策略的情况下切换某类行为：

```bash
getsebool -a                         # 列出全部布尔
getsebool httpd_can_network_connect
setsebool -P httpd_can_network_connect on   # -P 持久化
```

典型如 `httpd_can_network_connect`（Apache 能否主动外联）、`use_nfs_home_dirs` 等，体现"同一套策略 + 可调旋钮"。

- **可加载策略模块（policy module）**：发行版提供 `targeted`（默认，主要限制常见网络服务）、`mls` 等策略；自定义规则编译成 `.pp` 模块用 `semodule -i` 安装。`audit2allow -M` 可由拒绝日志生成模块，但生产环境应优先用布尔值或正确打标签，而不是无脑 allow。

## Labeling

标签是 SELinux 生效的前提，文件在以下情况下确定/修正标签：

```bash
restorecon -Rv /srv/www          # 按 file_contexts 递归修正标签
semanage fcontext -a -t httpd_sys_content_t '/srv/www(/.*)?'  # 新增永久规则
chcon -t httpd_sys_content_t file  # 临时改标签（relabel 后可能被覆盖）
```

新建目录、移动文件（mv 默认保留源标签）、挂载非标准路径服务目录时，最常见的故障就是标签不对——服务有权限但 SELinux 拒绝，permissive/AVC 日志能直接定位。

## LSM and Relationship to Other Isolation

SELinux 不是孤立机制，常与其他内核隔离能力组合：

- **LSM**：SELinux、AppArmor、Smack、TOMOYO 都通过 LSM 挂载；新内核支持堆叠次要 LSM（如 BPF LSM）。
- **capabilities**：把 root 的全能权限拆成 ~40 个 capability，属于 DAC/LSM 交界处的检查，SELinux 策略里也有 `capability` 类别。
- **[namespace](/docs/CS/OS/Linux/namespace.md) / [cgroup](/docs/CS/OS/Linux/cgroup.md)**：提供视图隔离与资源限额，是容器的基础；容器运行时再叠加 SELinux（MCS 随机类别）或 AppArmor/seccomp 做强制访问控制，二者互补——namespace 不是安全边界，MAC 才补强了"容器逃逸后仍受限"。
- **[eBPF LSM](/docs/CS/OS/Linux/Tools/eBPF.md)**：现代内核允许用 BPF 程序实现 LSM 策略，与 SELinux 并存。

## SELinux vs AppArmor

| 维度 | SELinux | AppArmor |
| --- | --- | --- |
| 标识对象 | 给一切打类型标签（label-based） | 基于文件路径（path-based） |
| 策略 | TE 语言，表达力强、学习曲线陡 | 配置文件式 profile，相对易读 |
| 标签存储 | 文件 xattr | 路径匹配，无需重打标签 |
| 典型发行版 | RHEL/Fedora/CentOS/Rocky/Android | Debian/Ubuntu/SUSE |
| 容器 | MCS 类别隔离常见 | profile/namespace 常见 |

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Security](/docs/CS/OS/Security.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)
- [LXC](/docs/CS/OS/Linux/LXC.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)

## References

1. [Red Hat: Using SELinux](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/html/using_selinux_to_confine_users_and_processes/index)
2. [SELinux Notebook (current)](https://github.com/SELinuxProject/selinux-notebook)
3. [Kernel Documentation: Linux Security Modules](https://docs.kernel.org/security/lsm.html)
4. [NSA SELinux History](https://www.nsa.gov/what-we-do/research/selinux/)
