## Introduction

Apple Silicon 的 Mac 没有 BIOS，也没有传统 PC 意义上的 UEFI。它的启动过程和 iPhone、iPad 是同一套：**每一级固件验证下一级的签名，验证失败就进恢复系统**。这条链上除了内核，连"安全策略"本身也要被验证——这是 Apple Silicon 启动与 Intel Mac 最本质的区别。

Intel Mac 上是 EFI 固件找 `boot.efi`，`boot.efi` 加载 kernel；Apple Silicon 上是 Boot ROM → LLB → iBoot → kernelcache → launchd。中间多出来的 LLB 与 iBoot 两级，以及贯穿其中的 LocalPolicy，构成了它的信任链。

## The Chain

| 阶段 | 由谁加载 | 它负责验证 / 加载什么 |
| :--- | :--- | :--- |
| Boot ROM | 芯片内固化 | 硬件信任根，验证并启动 LLB |
| LLB（Low-Level Bootloader） | Boot ROM | SoC 内核固件（存储、显示、系统管理、Thunderbolt 控制器），加载 LocalPolicy，按策略验证 iBoot |
| iBoot | LLB | macOS 配对固件（Secure Neural Engine、Always On Processor 等），BootKC、AuxKC、system trust cache、SSV 根哈希 |
| XNU kernelcache | iBoot | 内核接管，挂载已验证的系统卷 |
| launchd | 内核 | PID 1，拉起用户态（见 [Service Management](/docs/CS/OS/mac/Service_Management.md)） |

关键点是**验证不止覆盖代码**：iBoot 会检查系统卷（SSV）的根哈希，确认内核即将挂载的文件系统完整性没问题——也就是说"磁盘上的系统"和"即将运行的系统"是被同一条链串起来的。

## LocalPolicy

LocalPolicy 是 Apple Silicon 引入的一个概念：**每个系统安装有一份安全策略文件，由本机的 Secure Enclave 用其私钥签名**（不是 Apple 中央服务器签的）。它记录用户为该安装选择了什么启动与运行时安全策略。

设计上有两个防降级的细节：

- **绑定硬件**：签名密钥只存在于这台机器的 Secure Enclave 里，因此一份 LocalPolicy 拿不到别的机器上用。
- **防重放**：LLB 会从 Secure Enclave 挂载的 Secure Storage Component 取 anti-replay 值，与 LocalPolicy 里的比对。目的是防止"把安全策略调低 → 用完再贴回旧的低安全性策略"。

结果是这套机制既防**操作系统版本回滚**，也防**安全策略降级**——后者是很多带 Secure Boot 的系统没覆盖到的。

## Security Modes

LocalPolicy 里最核心的字段是安全档位，共三档：

| 档位 | 含义 | 什么时候需要 |
| :--- | :--- | :--- |
| Full Security | 行为与 iOS / iPadOS 一致，只允许启动安装时已知的最新版本 | **默认档** |
| Reduced Security | 信任系统自带的"全局"签名，允许跑较旧的 macOS；**这也是支持第三方 kext 的必要档位** | 装第三方内核扩展 |
| Permissive Security | 在 Reduced 基础上，接受由本机 Secure Enclave 签名的部分启动对象 | 自己编译、签名并启动自定义 XNU 内核 |

```shell
bputil -d        # 查看当前启动策略（需要 root）
```

更改档位要进恢复模式（启动安全性工具），因为改的是 LocalPolicy：需要卷属主认证 + Secure Enclave 重新签名，所以**不能脚本化远程改**，这也是企业 MDM 要专门支持的原因。

> [!NOTE]
>
> Full Security 下 LLB 校验的是 iBoot 的**个性化签名**（personalized signature，与 Apple 签名服务器相关），Reduced / Permissive 下校验的是**全局签名**。降级到 Reduced 意味着放弃"只跑最新系统"这条保证。

## Kernel Collections

Apple Silicon 上内核与 kext 不再单独加载，而是打包成**内核集合**（Kernel Collection）：

| 集合 | 内容 | 谁签名 |
| :--- | :--- | :--- |
| BootKC（Boot Kernel Collection） | XNU 内核 + 启动必需的 kext | Apple |
| AuxKC（Auxiliary Kernel Collection） | 第三方 kext | 本机 Secure Enclave，哈希存入 LocalPolicy |

iBoot 会去找 AuxKC，验证它的签名与 LocalPolicy 里存的哈希一致，然后把它与 BootKC 一起放进内存，并用 SCIP（System Coprocessor Integrity Protection）把这段内存锁住。找不到 AuxKC 就照常启动，只是没有那些第三方 kext。

本机上能看到发布形态的内核与按机型的变体：

```shell
$ ls /System/Library/Kernels/
kernel    kernel.release.t6000    kernel.release.t6020    kernel.release.t8103    ...
```

真正被加载的预链接 cache 则在 Preboot 卷上，路径里带随系统版本变化的哈希（见 [File System](/docs/CS/OS/mac/File_System.md)）。

## Intel and T2

过渡期的 Intel Mac 分两种：

- **带 T2 芯片**：T2 Boot ROM → T2 bridgeOS → UEFI 固件 → `boot.efi` → kernel。T2 承担 Secure Boot 的验证职责。
- **不带 T2**：没有 Secure Boot，启动链不做验证，固件级攻击面存在。

Intel Mac 的安全启动档位只有三档中的两档（Full Security / Medium Security / No Security），用恢复模式里的启动安全性工具管理，没有 LocalPolicy 这一层。

## Boot Modes and Recovery

| 操作 | 结果 |
| :--- | :--- |
| 长按电源键直到出现启动选项 | 进入选择器，可选系统卷或 `Options`（恢复） |
| `Options` | 启动 recoveryOS（Apple Silicon 上是 1TR，One True Recovery） |
| 关机后长按电源键（配合特定键序） | 进入 DFU 模式，供另一台 Mac 用 Apple Configurator 恢复固件 |

Apple Silicon 的恢复系统叫 **1TR**，因为它要求卷属主认证才能改安全策略或重灌系统——这与 Intel 时代"进恢复就能改"不同，是防物理接触攻击的一环。

## boot-args

内核启动参数通过 NVRAM 传入，是调试内核问题时最常用的开关：

```shell
nvram boot-args          # 查看当前设置
sudo nvram boot-args="debug=0x14e keepsyms=1"
sudo nvram -d boot-args  # 清除
```

常见取值：`debug=0x14e` 让内核 panic 时等待调试器附加而不是直接重启；`keepsyms=1` 保留符号；`swd_panic=1` 让睡眠唤醒失败时产生崩溃日志而不是静默重启。SIP 开启时这些参数的设置本身也受限。

同一套 `boot-args` 在 [Hackintosh](/docs/CS/OS/mac/Hackintosh.md) 里也有，但那边是写在 OpenCore 的 `config.plist` 的 `NVRAM → Add` 里，不是用 `nvram` 命令。

## Power States

睡眠相关的配置归 `pmset` 管，与启动链共享同一份持久化状态：

```shell
$ pmset -g custom
Battery Power:
 hibernatemode          3
 hibernatefile          /var/vm/sleepimage
 standby                1
 powernap               1
 displaysleep           2
 sleep                  1
```

macOS 的 `hibernatemode` 与 Linux 的 S3/S4 不是一一对应的：`3` 是默认的混合模式（睡眠时保持内存供电，同时写一份镜像到磁盘兜底），`25` 才是纯休眠。排查"睡了之后立刻唤醒"这类问题，`pmset -g log` 与 `log show --last 3m | grep "Wake reason"` 是首选，详见 [Hackintosh](/docs/CS/OS/mac/Hackintosh.md) 的睡眠排错段。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [File System](/docs/CS/OS/mac/File_System.md)
- [Apple Silicon](/docs/CS/OS/mac/Apple_Silicon.md)
- [Hackintosh](/docs/CS/OS/mac/Hackintosh.md)

## References

1. [Boot process for a Mac with Apple silicon](https://support.apple.com/guide/security/boot-process-secac71d5623/web)
2. [Startup Security Utility for a Mac with Apple silicon](https://support.apple.com/guide/security/startup-security-utility-sec2f6b3c1c8/web)
3. [Apple Platform Security Guide](https://help.apple.com/pdf/security/en_AU/apple-platform-security-guide-x.pdf)
4. [Kernel debugging with boot-args](https://developer.apple.com/library/archive/technotes/tn2118/_index.html)
