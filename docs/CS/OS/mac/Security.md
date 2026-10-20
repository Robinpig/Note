## Introduction

macOS 的安全不是一道门，是**一串串联的闸口**，每一层拦的东西都不一样：固件只认 Apple 签过的启动链，系统卷只读且带哈希封印，SIP 限制 root 与进程注入，Gatekeeper 与公证决定一个下载来的 app 能不能第一次启动，XProtect 在运行时比对恶意软件特征，TCC 把摄像头、桌面、文稿这类敏感资源从"文件权限"里拿出来单独授权，FileVault 与 Secure Enclave 负责静态加密。

理解这套模型的实用价值在于**定位报错**：macOS 拒绝一个操作时，给出的提示往往只说"操作不被允许"，不说被哪一层拦了。按从下到上的顺序逐层排除，比猜快得多。

## Sealed System Volume

macOS 11 起系统盘上的"Macintosh HD"**不再是读写卷**，而是被哈希树封印的只读卷，运行时挂载的是它的 APFS 快照。本机证据：

```shell
$ mount | grep ' / '
/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)

$ diskutil apfs list
+-> Volume disk3s1
    APFS Volume Disk (Role):   disk3s1 (System)
    Sealed:                    Yes
    Snapshot Disk:             disk3s1s1
    Snapshot Mount Point:      /
```

注意挂载点是 `disk3s1s1`（**快照**）而不是 `disk3s1`（卷）本身。这带来一个反直觉的现象：root 也无法直接往 `/System`、`/usr`、`/bin` 写文件，哪怕先 `mount -uw /` 也不行——因为封印校验在 APFS 层。要改系统内容，正确路径是快照、修改、再重新封印（Apple 的系统更新就是这么做的）。

顺带一提，**系统应用也不一定住在系统卷上**。Apple 从 macOS 13 起用 cryptex（cryptographically sealed extension）把部分系统组件从系统卷拆出来，放到 Preboot 卷上独立更新：

```shell
$ ls /System/Volumes/Preboot/Cryptexes/
App   Incoming   OS

$ codesign -dv /Applications/Safari.app 2>&1 | head -2
Executable=/System/Volumes/Preboot/Cryptexes/App/System/Applications/Safari.app/Contents/MacOS/Safari
Identifier=com.apple.Safari
```

Safari 的可执行文件实际在 `Cryptexes/App/` 下——这就是为什么 Safari 能在不重装系统的情况下单独拿到更新。

## System Integrity Protection

SIP 是"权限之外"的那一层：**它限制 root 能做什么**。即便你拿到 root shell，SIP 保护的路径仍然不可写，受保护进程仍然不能被注入代码或调试。

```shell
$ csrutil status
System Integrity Protection status: enabled.
```

被 SIP 约束的能力主要包括：修改受保护路径（`/System`、`/usr`、`/bin`、`/sbin`、`/var`、Apple 预装 app）、加载未签名 kext、以及 `task_for_pid()`——Mach 层那个"拿到另一个 task 端口就能读写其内存"的能力（见 [Darwin](/docs/CS/OS/mac/Darwin.md)）。

这一条直接解释了两件日常会撞到的事：LLDB 附加到系统进程会失败，[dtruss](/docs/CS/OS/mac/Tools/dtruss.md) 这类基于 DTrace 的工具默认不可用。两者都要先关 SIP：关机 → 长按电源键进恢复模式 → 终端里 `csrutil disable` → 重启。

> [!WARNING]
>
> 关 SIP 是**整机降级**，不是给某个工具开白名单。Apple 提供的 `csrutil enable --without <flag>` 可以只放开单项（如 `--without debug`），代价远小于全关。

## Gatekeeper and Notarization

Gatekeeper 管的是"这个 app 能不能第一次启动"。它的输入是三样东西：代码签名、公证票据（notarization ticket）、以及文件上的隔离属性 `com.apple.quarantine`（从网络上下载的文件会被打上）。

```shell
$ spctl --status
assessments enabled          # 默认；本机被手动关掉时显示 assessments disabled

$ codesign -dv /Applications/Safari.app 2>&1 | head -5
Identifier=com.apple.Safari
Format=app bundle with Mach-O universal (x86_64 arm64e)
CodeDirectory v=20400 size=617 flags=0x2000(library-validation) hashes=9+7 location=embedded
Platform identifier=16
```

几个细节值得留意：`Format=app bundle with Mach-O universal (x86_64 arm64e)` 说明系统二进制是 fat binary 且 Apple Silicon 侧用的是 **arm64e**（带指针认证），不是普通的 arm64；`flags=0x2000(library-validation)` 表示启用库校验，注入别人的 dylib 会直接被拒。

公证是 Apple 的在线扫描服务：开发者上传二进制，Apple 扫描后签发票据，用户在离线状态下也能验证。未公证的软件第一次打开时，系统弹窗会引导用户去"系统设置 → 隐私与安全性"里手动允许；也可以从右键菜单"打开"绕过（`xattr -d com.apple.quarantine` 是命令行等价做法，但会一并丢掉隔离标记带来的其它提示）。

## XProtect and Malware Removal

XProtect 是 macOS 内建的**签名型**反恶意软件：不分后台常驻扫描，而是在 app 首次启动、签名变更、以及定期任务时比对特征。它的规则与本体是 Apple 通过系统更新单独推送的，位置在：

```shell
$ ls /Library/Apple/System/Library/CoreServices/
XProtect.app
XProtect.bundle
CoreTypes.bundle
```

`XProtect.bundle` 里放的是 Yara 规则与已知恶意软件签名，`XProtect.app` 是执行引擎。早期版本另有 MRT.app（Malware Removal Tool）负责自动修复，新版已并入 XProtect 体系。

## TCC

TCC（Transparency, Consent, and Control）是 macOS 上最容易和 Unix 权限混淆的一层。**文件权限在这里不是充分条件**：一个进程就算有 root、能 `open()` 某个文件，访问受 TCC 保护的资源仍然会被拒，必须由用户在弹窗中授权，而且授权记录在数据库里，不写在文件系统权限位上。

受控的资源大致分几类：位置服务、相机、麦克风、桌面 / 文稿 / 下载文件夹、完全磁盘访问（Full Disk Access）、屏幕录制、输入监控、以及跨应用自动化（Apple Events）。

```shell
tccutil reset All          # 重置全部 TCC 授权（会清空所有历史授权决定）
```

数据库本体受 SIP 保护（`/Library/Application Support/com.apple.TCC/` 下），即使 root 也列不出来——这正是"为什么改完权限还是打不开"的高频原因。

## FileVault and Encryption at Rest

FileVault 是卷级加密，基于 XTS-AES-128（Apple Silicon 上由 Secure Enclave 协同管理密钥层级）。开启后**连 swap 也是加密的**：

```shell
$ fdesetup status
FileVault is On.

$ sysctl -n vm.swapusage
vm.swapusage: total = 15360.00M  used = 14333.94M  free = 1026.06M  (encrypted)
```

末尾那个 `(encrypted)` 是 macOS 相对 Linux 的一个明确优势：Linux 上 swap 加密需要额外配置（dm-crypt / zswap 加密），macOS 默认就是。

## Address Space Layout Randomization

ASLR 从 Mac OS X 10.5 起引入：每次执行时，程序在内存中的起始地址、堆、栈、库的加载地址都会随机化，让攻击者无法预先算出目标地址。

```c
// test.c
#include <stdlib.h>
#include <stdio.h>

int main()
{
    int a = 0;
    printf("The address in the stack is:\t0x%x\n", &a);
    return 0;
}
```

```shell
clang test.c -o test
./test
```

每次运行时 `a` 的逻辑地址都不同，表现为"一个随机基址 + 固定偏移"。逻辑地址不再固定，意味着汇编层面不能直接引用绝对地址，编译器需要生成位置无关代码（Position Independent Code, PIC）；由 PIC 编译链接出的可执行文件称为位置无关可执行文件（PIE）。

## Layers at a Glance

| 机制 | 拦的是什么 | 怎么查状态 | 关掉的代价 |
| :--- | :--- | :--- | :--- |
| Secure Boot | 非 Apple 签名的启动链 | 恢复模式里的启动安全性工具 | 整机信任根失效 |
| Sealed System Volume | 对系统卷的写入 | `diskutil apfs list` 看 `Sealed` | 需要重新封印才能再保护 |
| SIP | root 对系统路径与进程的改动 | `csrutil status` | 可被任意 kext / 注入改写系统 |
| Gatekeeper | 未签名 / 未公证 app 的首次启动 | `spctl --status` | 任意下载物可直接运行 |
| XProtect | 已知恶意软件 | 更新记录 | 少一层特征拦截 |
| TCC | 对敏感资源与目录的访问 | 系统设置 → 隐私与安全性 | 任意 app 可读桌面 / 开摄像头 |
| FileVault | 磁盘被物理读取 | `fdesetup status` | 静态数据可离线读出 |

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [File System](/docs/CS/OS/mac/File_System.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [Package](/docs/CS/OS/mac/Package.md)
- [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)

## References

1. [Apple Platform Security](https://support.apple.com/guide/security/welcome/web)
2. [About System Integrity Protection on Mac](https://support.apple.com/en-us/102149)
3. [Using Gatekeeper and notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
4. [Protecting against malware in macOS](https://support.apple.com/guide/security/protecting-against-malware-sec469d47bd8/web)
5. [Signed system volume security](https://support.apple.com/guide/security/signed-system-volume-security-sec698a30bf4/web)
