## Introduction

Windows 的安全模型有一个 Linux 长期没做到的东西：**它在同一套机制里同时实现了自主访问控制（谁可以访问）和一种轻量强制访问控制（你有多可信）**。Linux 那边前者是 owner/group/other + ACL，后者要另外挂 SELinux/AppArmor；Windows 把两者都塞进了安全描述符与访问令牌里，由内核里同一个组件——**安全引用监视器（Security Reference Monitor，SRM）**——在唯一的位置做决定。

这一点决定了理解方式：别把 Windows 权限理解成"文件属性"，要理解成 **"一个拿着令牌的线程，去碰一个挂着安全描述符的对象，中途必经 SRM 的一个判断"**。这个模型统一适用于文件、注册表键、进程、线程、命名管道、共享内存、打印机、服务——因为它们在 [架构篇](/docs/CS/OS/Windows/Architecture.md) 里本来就是同一类东西：内核对象。

本文按这条链路推进：先看**五个组成部分**，再看**访问检查算法**，然后是 **UAC 与令牌分裂**这个 Windows 独有的日常现象、**强制完整性控制**、**特权与冒充**，最后是**现代 Windows 的 VBS 家族**与一张与 Linux 的对照。

---

## Five Parts of the Access Control Model

| 组成 | 是什么 |
| :-- | :-- |
| **SID**（安全标识符） | 用户、组、计算机、服务的唯一标识，形如 `S-1-5-21-<domain>-<rid>`。它替代"用户名"，因此改名、跨域迁移都不会破坏权限绑定 |
| **访问令牌（access token）** | **进程或线程的身份凭证**：包含用户的 SID、所属组的 SID、特权列表、完整性级别、以及默认 DACL |
| **安全描述符（security descriptor）** | 挂在可被保护的对象上：所有者 SID、组 SID、**DACL**（谁能做什么）、**SACL**（什么操作要审计） |
| **ACL / ACE** | DACL 是一条 ACE 列表，每条 ACE 对一个 SID 说明允许/拒绝哪些访问掩码 |
| **SRM** | 内核态唯一的执行点。任何"我能不能做这件事"的问题，最终都由它回答 |

这套结构里最容易被忽略的是 **token 属于进程或线程，而不是用户**。因此：

- 同一个用户可以同时有几十个进程，各自拿着不同令牌（一个普通、一个提升、一个替别人冒充）；
- 修改用户权限后，已经运行的进程**不会**自动获得新权限——它手里的令牌是登录那一刻签发出来的快照。

> [!NOTE]
>
> 这就是为什么"把用户加进管理员组之后必须注销再看"，以及为什么 `runas` 与 UAC 提权都要产生**新的令牌**而不是给老令牌打补丁。

---

## The Access Check

一次访问发生时，内核做的主要三步：

1. **遍历 DACL 里的 ACE**。显式 ACE 先于继承 ACE；在同一类中，若遇到匹配当前 SID 的 **deny ACE** 就直接拒绝。经典原则：**显式拒绝优先**。
2. **计算剩余许可位**。把所有命中的 allow ACE 的访问掩码累积起来；若请求的每一位都被覆盖则通过。这里还有一个常被混淆的区别：**缺少 DACL**（NULL DACL）意味着"完全开放"，而**空 DACL**（有 DACL 但零条 ACE）意味着"全部拒绝"——两者天差地别。
3. **完整性级别校验**。即便 DACL 过关，线程令牌里的 IL 与目标对象上的强制标签还需满足**强制策略**（默认禁止上行写入）。

第 3 步正是 Windows 有别于传统 Unix 权限的地方，见下文「Mandatory Integrity Control」。

---

## Token Splitting and UAC

Windows Vista 引入的 **UAC（用户账户控制）**带来了一个机制级概念：**管理员登录会签出两个令牌**。

| 令牌 | 用途 | 完整性级别 |
| :-- | :-- | :-- |
| 筛选令牌（filtered token / standard user token） | 默认给所有进程 | Medium |
| 完整令牌（elevated token） | 通过同意/凭证之后才签出 | High |

管理员日常跑的程序拿着的是**前者**：它仍然属于 Administrators 组，但这个组的 SID 被打上了"仅用于拒绝"的标记（`SE_GROUP_USE_FOR_DENY_ONLY`），因此组成员身份不再带来权限。要真正拿到管理员权限，进程必须经历一次提升——也就是"重新签一个令牌"。

这条设计回答了一个长期的安全难题：**用户想当管理员，但不想让每个下载来的程序都拥有管理员权限**。它的代价是程序员必须显式声明 "requireAdministrator" 或单独启动一次提升进程，而不能在运行时"临时提权"——因为**令牌在进程创建时确定，不能在运行的进程里升级**。

---

## Mandatory Integrity Control

**MIC（强制完整性控制）**给每个主体（进程令牌）与每个客体（安全描述符里的强制标签）都标了一个完整性级别。完整性与 ACL 是正交的两套系统，它定义了如下关系：

| 完整性级别 | SID | 值 |
| :-- | :-- | :-- |
| Untrusted | `S-1-16-0` | 0x0000 |
| Low | `S-1-16-4096` | 0x1000 |
| Medium | `S-1-16-8192` | 0x2000 |
| Medium Plus | `S-1-16-8448` | 0x2100 |
| High | `S-1-16-12288` | 0x3000 |
| System | `S-1-16-16384` | 0x4000 |
| Protected Process | `S-1-16-20480` | 0x5000 |
| Secure Process | `S-1-16-28672` | — |

RID 之间留出 0x1000 的间隔是为了将来插入新的 level（Medium Plus 就是这样挤进来的）。

> [!WARNING]
>
> **默认策略是"不能往上写"**
>
> 低 IL 的进程不能写更高 IL 的对象。这解释了一大批现象：
>
> - 浏览器渲染进程（Low IL）写不到用户目录之外的多数位置；
> - 普通 Medium IL 的进程 **无法**向另一个 High IL 的进程做 `WriteProcessMemory` 或 `CreateRemoteThread`——因此" DLL 注入管理员进程"这条路被 IL 本身挡住了，而不是被某个杀软功能挡住的；
> - 反过来，想要跨 IL 交互必须通过 IPC 明确定义的通道见 [IPC](/docs/CS/OS/Windows/IPC.md)，因为对象所有权在更高 IL 的一侧。

---

## Privileges and Impersonation

**特权（privilege）**是另一回事：它不是"能否访问某个对象"，而是"能否做某类操作"。典型例子是 `SeDebugPrivilege`（打开任意进程）、`SeBackupPrivilege`（绕过 ACL 读文件）、`SeLoadDriverPrivilege`（加载驱动）。

特权默认在令牌里处于**禁用**状态，进程需要显式启用。这也是为什么备份类工具要坚持"以管理员身份运行"并显式启用特权——只有前一半是不够的。

**冒充（impersonation）**允许一个服务端线程临时以客户端的身份执行操作，四个级别：

| 级别 | 含义 |
| :-- | :-- |
| Anonymous | 服务端不知道客户端是谁 |
| Identification | 可以查询客户端身份，但不能以它行事 |
| Impersonation | **可以**在本机以客户端身份访问资源 |
| Delegation | 可以把身份再转给远端的其它服务 |

冒充的精妙之处在于把"确认身份"与"代为行事"拆成了两个不同的权限等级——前者便宜且安全，后者会引发远端凭据流转，因此只在确实需要时才授予。

---

## Auditing: The SACL

安全描述符里的 **SACL** 决定哪些访问要写入安全事件日志。它常被忘掉，但它是 Windows 上最经济的取证来源：想回答"谁动了这个文件"，ACL 不能告诉你，SACL 可以。

审计需要两端同时打开：对象上的 SACL **和**系统级的审计策略。

---

## Modern Windows: The VBS Family

近十年的 Windows 安全升级几乎都围绕同一件事：**用虚拟化造一个连 Windows 内核自己都摸不到的地方**。这条路线统称 **VBS（Virtualization-Based Security）**，依赖 [Hyper-V](/docs/CS/OS/Windows/Architecture.md) 那套 type-1 hypervisor——**Windows 主机自己反而运行在管理层之下的 root partition 里**。

| 能力 | 做什么 |
| :-- | :-- |
| **Secure Boot / Measured Boot** | 固件阶段开始校验链式签名，阻止 bootkit；Measured Boot 把度量记入 TPM |
| **HVCI**（内存完整性） | 在独立的虚拟信任世界里校验要执行的内核代码页，未签名的驱动/内核 shellcode 直接不可执行 |
| **Credential Guard** | 把 `lsass.exe` 里最敏感的凭据材料放进隔离容器，常规意义的"读 lsass 内存"不再够用 |
| **受保护进程 / PPL** | 即使同 IL 甚至管理员也无法打开某些进程；`lsass` 的 LSA Protection 就是走 PPL |
| **AppContainer** | 面向 UWP/沙箱应用的“能力 + 容器” |

> [!NOTE]
>
> **为什么这些能力需要硬件虚拟化**
>
> 因为"内核完整性保护"朴素实现总会遇到自己的悖论：**谁来保护保护者**。若 HVCI 本身跑在内核里，攻进内核就等于关掉了它。把这一层挪到一个**内核看不见、且由 hypervisor 隔开的**执行环境里，这个悖论才被打破。代价是需要 CPU 的虚拟化扩展与 IOMMU，以及它与老驱动、老的 DMA 设备的兼容性摩擦。

---

## Comparison with Linux

| 维度 | Windows | Linux |
| :-- | :-- | :-- |
| 主体身份 | 访问令牌（进程/线程携带） | uid/gid + capabilities + LSM 标签 |
| 对象保护 | 安全描述符（DACL + SACL + 强制标签） | mode bits + POSIX ACL + xattr（扩展者由 LSM 解释） |
| 执行点 | 内核里唯一的 SRM | 分散在各处的 `inode_permission` / `security_*` hook |
| 强制访问控制 | 内建的 MIC（完整性级别） | 需要 SELinux / AppArmor / SMACK 等 LSM |
| 提权模型 | UAC：管理员默认拿筛选令牌 | sudo / setuid / capabilities |
| 审计 | SACL → 安全事件日志 | auditd / eBPF |

两边的差别不在"谁更严"，而在**严在哪里**：Linux 把"允许/拒绝"的判断权威分散给了可插拔的 LSM，换取灵活性；Windows 把它集中在 SRM 一处，换取一致性——一个统一模型能覆盖文件、注册表、管道、进程、线程、服务，代价是要加入新的安全策略时必须扩展这套模型本身。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md)
- [操作系统安全](/docs/CS/OS/Security.md)

---

## References

1. [Access Control Model](https://learn.microsoft.com/en-us/windows/win32/secauthz/access-control-model)
2. [Access Control Components](https://learn.microsoft.com/en-us/windows/win32/secauthz/access-control-components)
3. [Security Identifiers](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-identifiers)
4. [Windows Integrity Mechanism Design](https://learn.microsoft.com/en-us/previous-versions/dotnet/articles/bb625963(v=msdn.10))
5. [Securable Objects](https://learn.microsoft.com/en-us/windows/win32/secauthz/securable-objects)
