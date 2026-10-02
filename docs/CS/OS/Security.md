## Introduction

操作系统安全的目标是在**共享内核**之上让多个主体（用户、进程、容器）安全地复用同一台机器：控制谁能访问什么、隔离互不信任的执行环境、并在出问题时限制破坏范围。它不是单一机制，而是从硬件特权级到访问控制、从身份认证到隔离沙箱的一整套分层防御。

本笔记梳理操作系统安全的主干概念与 Linux 的对应机制；某一机制的细节见各专题，如强制访问控制的 [SELinux](/docs/CS/OS/Linux/SELinux.md)。

## Privilege Rings and Kernel/User

最底层的隔离由硬件提供：

- **特权级（x86 ring 0/3，ARM EL3/EL1/EL0）**：内核运行在最高特权态，可执行特权指令、直接访问设备与全部物理内存；用户进程运行在非特权态，必须通过**系统调用**经受控入口请求内核服务。
- **系统调用门**：用户态到内核态的唯一合法入口，内核在此做参数校验与权限检查，是安全边界所在。
- **[中断与异常](/docs/CS/OS/Linux/Interrupt.md)** 也会进入内核态，其入口同样受控。

## Authentication, Authorization, Accounting

经典的 **AAA / 3A** 模型：

- **认证（Authentication）**：你是谁——密码、密钥、多因素；对应 UID、PAM、SSH key。
- **授权（Authorization）**：你能做什么——权限位、ACL、capability、MAC 策略。
- **审计（Accounting/Audit）**：做过什么——`auditd`、日志、SELinux AVC。

身份在 Linux 上体现为 UID/GID（真实/有效/saved/fs uid），`root` 即 UID 0。

## DAC and MAC

访问控制的两大范式：

| 范式 | 决定者 | 特点 | Linux 实现 |
| --- | --- | --- | --- |
| **DAC**（自主访问控制） | 资源属主 | 属主可随意授权限；root 基本不受限 | UGO 权限位、属主/属组、POSIX ACL |
| **MAC**（强制访问控制） | 系统全局策略 | 主体不能改变、连 root 也要服从，默认拒绝 | [SELinux](/docs/CS/OS/Linux/SELinux.md)、AppArmor、Smack（经 LSM） |

DAC 的问题是粒度粗且"属主全权、root 全能"：一个被攻破的 root 进程能控制整台机器。MAC 通过给一切打标签、由集中策略判定来实施最小权限。

## Capabilities

为拆解 root 的全能权限，Linux 把传统上仅 UID 0 拥有的特权分成约 40 个 **capability**（`CAP_NET_ADMIN`、`CAP_SYS_ADMIN`、`CAP_DAC_OVERRIDE`、`CAP_KILL`……）：

- 进程的 capability 集合分 permitted/effective/inheritable/bounding/ambient；
- 文件也可带 capability（setcap），让非 root 程序只在执行某项特权操作时获得相应能力；
- 容器通过**丢弃大部分 capability**（Docker 默认只保留一小集）显著收窄攻击面。

## Linux Security Modules

**LSM** 是内核提供的安全框架，在内核对象的关键操作（打开文件、建立连接、task 操作等）上预留 hook，具体安全模块实现这些 hook，在 DAC 检查之后再做强制判定。SELinux、AppArmor、Smack、TOMOYO 都是 LSM 模块；较新的内核还支持 [BPF LSM](/docs/CS/OS/Linux/Tools/eBPF.md) 用 eBPF 写策略，并允许堆叠次要模块。

## Isolation and Containers

让不可信负载彼此隔离的机制（容器的构建块）：

- **[namespace](/docs/CS/OS/Linux/namespace.md)**：隔离视图——mnt、pid、net、ipc、uts、user、cgroup namespace，让进程"看到"受限的系统；
- **[cgroup](/docs/CS/OS/Linux/cgroup.md)**：限制/统计资源——CPU、内存、IO、设备；
- **MAC（SELinux/AppArmor）**：即使逃逸出 namespace 仍受强制策略约束（namespace 本身不是强安全边界）；
- **seccomp**：过滤进程可调用的系统调用集合，缩小内核攻击面；
- **chroot / pivot_root**：文件系统根隔离的基础；
- 虚拟化（VM）则借助 VMM/硬件虚拟化（VT-x/AMD-V）提供更强的 guest/kernel 隔离。

纵深防御通常是这些机制叠加：namespace + cgroup + seccomp + capability drop + MAC。

## Other Mechanisms

- **进程凭据与提权**：setuid/setgid 位、saved-ID、`sudo`；setuid 程序历来是提权高发区。
- **内核模块信任**：加载 [LKM](/docs/CS/OS/Linux/module/LKM.md) 等同获得内核任意执行能力，故有模块签名与 Secure Boot；eBPF 则提供受 verifier 约束的更安全扩展。
- **栈/内存安全**：地址空间布局随机化（ASLR）、栈保护（stack canary）、不可执行栈（NX）、FORTIFY_SOURCE、KASLR/SMEP/SMAP 等内核侧缓解。
- **加密与完整性**：传输/静态数据加密、文件完整性（IMA）、dm-verity、Secure Boot 信任链。
- **并发安全本身**：正确的同步原语（见内核[同步机制](/docs/CS/OS/Linux/Lock/README.md)）也是避免竞态型安全漏洞（TOCTOU 等）的基础。

## Threat Model

安全设计的前提是威胁模型：信任边界画在哪（用户↔内核、容器↔宿主、VM↔hypervisor）、攻击者已具备什么能力、要保护什么资产（机密性 C / 完整性 I / 可用性 A）。没有"绝对安全"，只有在既定威胁模型下用最小权限、隔离与纵深防御把风险降到可接受水平。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)
- [LXC](/docs/CS/OS/Linux/LXC.md)
- [LKM](/docs/CS/OS/Linux/module/LKM.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [Kernel Locking](/docs/CS/OS/Linux/Lock/README.md)

## References

1. [Kernel Documentation: Linux Security Modules](https://docs.kernel.org/security/lsm.html)
2. [Kernel Documentation: capabilities(7)](https://man7.org/linux/man-pages/man7/capabilities.7.html)
3. [NIST: Controlled Access Protection / MAC vs DAC](https://csrc.nist.gov/)
4. [Linux Kernel Security Documentation](https://docs.kernel.org/security/security.html)
