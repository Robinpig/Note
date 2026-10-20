## Introduction

启动过程是把前面各篇散讲的内容串起来的一次现场演示：[内存管理](/docs/CS/OS/Windows/Memory.md) 里的 HAL 与页目录、[进程与线程](/docs/CS/OS/Windows/Process_Thread.md) 里的第一批进程、[文件系统](/docs/CS/OS/Windows/FileSystem.md) 里那个必须是 NTFS 的系统卷、以及 [安全模型](/docs/CS/OS/Windows/Security.md) 里从固件就开始的信任链，都会在几十秒内依次出现。

与 Linux 相比，Windows 的启动链有一个明显不同的性格：**它把"引导配置"做成了数据库而不是文件**。Linux 的引导参数散在 GRUB 配置、内核命令行与 initramfs 里；Windows 把这些东西统一放在 **BCD（Boot Configuration Data）**这一个 registry hive 里，由固件阶段的 Boot Manager 自己去读。

本文按时间顺序推进：从固件到 **bootmgr**，到 **winload**，到内核与 HAL 的装载，再到第一批用户态进程与 winlogon 的就绪；最后补上**安全启动**、**快速启动**与**恢复环境**这三件每天都在做事、但平时没人注意的东西。

---

## Phase 1: Firmware

加电后最先拿到控制权的是固件：

| 固件 | 特点 |
| :-- | :-- |
| 传统 BIOS | 实模式、MBR 分区表，第一扇区里的引导代码负责把控制权交出去 |
| UEFI | 有自己的文件系统（FAT）视图，直接读取 `\EFI\Microsoft\Boot\bootmgfw.efi`，支持 Secure Boot |

UEFI 的存在带来两件要紧的事：一是固件自己能读一个 FAT 格式的 EFI 系统分区，因此 **Boot Manager 是一个文件而不是一段写在扇区里的魔法代码**；二是开始了可以被度量与签名的信任链，见下文「Secure Boot」。

这一阶段的产出很朴素：**把 Boot Manager 读进内存并执行**。

---

## Phase 2: Windows Boot Manager (bootmgr)

Boot Manager 做的第一件事是**读 BCD**。BCD 是一个 registry hive 文件：

- UEFI 系统上位于 EFI 系统分区的 `\EFI\Microsoft\Boot\BCD`；
- BIOS 系统上位于 `\Boot\BCD`。

它里面记录了若干个 **boot application**（启动项）：每个可启动的 Windows 安装、Windows Recovery Environment、内存诊断工具、以及可能的 WSL/Linux 项，各自带着参数。所有 `bcdedit` 的改动本质上都是改这个 hive。

| 常用 `bcdedit` 操作 | 作用 |
| :-- | :-- |
| `bcdedit /set {default} safeboot minimal` | 下一次以安全模式启动 |
| `bcdedit /set {current} nx OptIn` | 调整 DEP 行为 |
| `bcdedit /set linearaddress57 optin` | 开启 [5 级分页](/docs/CS/OS/Windows/Memory.md) |
| `bcdedit /set {current} hypervisorlaunchtype off` | 关闭 [Hyper-V](/docs/CS/OS/Windows/Architecture.md) 的虚拟机监控程序启动 |

Boot Manager 挑选要启动的项之后，就把对应的 **boot application**（对普通的 Windows 启动而言是 `winload.efi` 或 `winload.exe`）读进内存并执行。若是双系统，它会在这时候显示那个选择操作系统菜单。

> [!WARNING]
>
> **BCD 改坏了很难修**
>
> 因为它不是纯文本配置文件，而是一个 registry hive。写错了通常看不到语法错误，只会表现为"启动不了"。修复的常规姿势是先进 Windows Recovery Environment，再 `bootrec /rebuildbcd` 或 `bcdboot`——这也是为什么安装介质一定要随身有。

---

## Phase 3: winload

`winload` 是这一段真正做重活的：

1. 加载必要的启动驱动（为了能读系统卷，磁盘小端口驱动与文件系统驱动必须就位）；
2. **读取 SYSTEM registry hive**，拿到接下去要用的一切配置：加载哪些设备驱动、以什么顺序、以及出大事故时的控制行为；
3. 把 `ntoskrnl.exe`、HAL映像、以及被标记为 boot-start 的那些驱动读进内存；
4. 准备完成后，把控制权交给内核入口。

这里有一个容易被忽视的细节：**系统卷必须是引导阶段就能读的文件系统**。第一阶段的预引导读取器与内核是绑在一起的，这也解释了为什么 Windows 上"换文件系统"远不如 Linux 那么随意。

---

## Phase 4: ntoskrnl and HAL

内核映像内部清楚地分成 Executive 与 Kernel 两部分（见 [架构篇](/docs/CS/OS/Windows/Architecture.md)），再加与之配套的 **HAL**，三者构成了"这套 Windows 能在这台机器上跑"的最小全集。这一阶段主要做：

- 初始化 Executive 的各组件（对象管理器、内存管理器、安全引用监视器等，按依赖关系分成两个阶段的早期/晚期初始化）；
- 建立中断描述符表与系统时钟，开启抢占（到这一步 [线程调度](/docs/CS/OS/Windows/Process_Thread.md) 才真正开始工作）；
- 创建第一批系统线程，包括每 CPU 的空闲线程，以及那个跑到优先级 0 的零页线程。

这一阶段的起点与终点差别极大：开始时系统还在用固件提供的服务读写磁盘，结束时 Windows 已经能自己管理内存、调度线程、响应中断——也就是"操作系统上线了"。

---

## Phase 5: The First User-Mode Processes

内核随后创建第一个用户态进程 **`smss.exe`**（Session Manager），之后的链条是：

```text
ntoskrnl
  → smss.exe        建立 Session 0，加载 registry hive，启动子系统进程
      → csrss.exe   Win32 用户态环境（每个 session 一个）
      → wininit.exe Session 0 的主人
            → services.exe   SCM：拉起所有服务，处理依赖与自动启动项
            → lsass.exe      安全子系统：认证与令牌签发（见安全篇）
            → winlogon.exe   处理 SAS、凭证 provider、创建用户会话
                  → explorer.exe   登录后，该 session 的 Shell
```

对照 Linux：

| 角色 | Windows | Linux |
| :-- | :-- | :-- |
| 第一个用户态进程 | `smss.exe`（且很快只剩一个副本） | init / systemd（PID 1，一直在） |
| 服务管理 | SCM（`services.exe`）+ 注册表里的服务数据库 | systemd + unit 文件 |
| 认证中心 | `lsass.exe` | PAM + nss + sshd 等各自实现 |
| 会话概念 | 显式存在（Session 0 / 1 / 2…） | 隐式（登录会话、TTY、cgroup） |

> [!NOTE]
>
> **`smss.exe` 的特殊性**
>
> 它是极少数会**自我终结**的系统进程：完成早期初始化之后，通常只剩一个实例继续存在。看到多个短命的 `smss.exe` 一般是不正常的（关于这类判断见 [安全模型](/docs/CS/OS/Windows/Security.md)）。

---

## Phase 6: Ready for Interactive Logon

`winlogon` 起来之后，桌面就是"等待 Ctrl+Alt+Del"的状态。这里要说清一件经常被误解的事：**登录界面不是给用户看的那么简单**——SAS（Secure Attention Sequence）的价值在于它是一条**不可被普通应用拦截的按键序列**，用于防止伪登录框拿走密码。

用户登录后，`winlogon` 用认证包校验凭证、由 `lsass` 签发令牌、用该令牌创建 `explorer.exe` 与初始进程。此刻图景上剩下的东西值得说清楚：**用户看到的那个"桌面"其实是 `explorer.exe` 的窗口**，而不是内核或系统本身的一部分。

---

## Secure Boot: The Trust Chain Below Windows

**Secure Boot** 把信任链从固件一直拉上来：

```text
固件里的平台密钥（PK）
  → 校验密钥交换密钥（KEK）
      → 校验签名数据库（db / dbx）
          → 校验 bootmgfw.efi
              → 校验 winload
                  → 校验内核与启动驱动（含 ELAM：反恶意软件早期启动）
```

每一环都必须带着被上一环认可的签名，否则整条链断掉。这条链的实用后果是：

- bootkit 与 rootkit 的落地成本从"写个驱动"变成了"要么拿到受信任签名、要么物理接触机器"；
- 启用 Secure Boot 与 [HVCI](/docs/CS/OS/Windows/Security.md) 之后，某些老驱动、老 AV 产品、以及相当一部分第三方磁盘加密软件会直接加载失败——这正是很多企业上 VBS 时被卡住的地方。

---

## Fast Startup and Recovery

### Fast Startup

Windows 8 引入的**快速启动**是一种混合关机：注销所有用户会话后，把系统会话hibernate 到磁盘，下次开机直接从 hiberfile 恢复。它的收益很实在，代价是：

- 关机期间对系统卷的修改（例如在 Linux 双系统里改 NTFS）可能与 hiberfile 里的快照冲突；
- "关机"之后硬件未必完全断电，某些设备与驱动会遇到电源状态错位——这也是某些机器上"重启一次就好"的来源。

### Windows Recovery Environment (WinRE)

WinRE 是一个独立的、极小的 Windows，跑在安装之外的一个恢复分区上。它是修复 BCD、跑 `chkdsk`、系统还原、以及"重置此电脑"的地方。它在 BCD 里也是一个启动项，因此 Boot Manager 能到达它——这是一条非常重要的自我修复路径。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows 安全模型](/docs/CS/OS/Windows/Security.md)
- [系统启动](/docs/CS/OS/BootLoader.md)

---

## References

1. [BCD System Store Settings for UEFI](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/bcd-system-store-settings-for-uefi)
2. [BCDEdit Command-Line Options](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/bcdedit-command-line-options)
3. [Secure Boot](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/oem-secure-boot)
4. [Windows Recovery Environment technical reference](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-recovery-environment--windows-re--technical-reference)
5. [Windows Server release information](https://learn.microsoft.com/en-us/windows-server/get-started/windows-server-release-info)
