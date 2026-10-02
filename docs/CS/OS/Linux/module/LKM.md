## Introduction

**LKM（Loadable Kernel Module，可加载内核模块）** 是 Linux 在**运行时**向内核装载/卸载代码的机制，用于驱动、文件系统、网络协议、加密算法等，避免把所有功能都静态编进 vmlinux、也不必为增删功能重编译或重启内核。模块本质上是一个 **ELF 目标文件（`.ko`）**，加载时由内核完成"动态链接"，把它并入内核地址空间执行。

本笔记讲 LKM 的机制与生命周期；具体的模块开发（init/exit 函数、Makefile、`MODULE_*` 宏、版本/签名检查的代码示例）见同目录的 [module](/docs/CS/OS/Linux/module/module.md)。

需要强调一个定位差异：LKM 运行在内核态、拥有**全部内核权限**，是一种"不受沙箱限制"的扩展方式；而 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) 同样做到"不改内核源码、不重启即可扩展"，但程序要经 verifier 证明安全、能力受 helper 与 hook 约束。二者是 Linux 内核可编程性的两条路线。

## ELF Object and Dynamic Linking

`.ko` 不是完整可执行文件，而是可重定位的 ELF 目标，包含普通 ELF 段外加模块专用的 ELF section：

- `.modinfo`：模块元数据——license、author、description、`vermagic`（内核版本/编译配置串）、参数描述、别名等；
- `__versions`：所引用内核符号的 CRC 校验值，用于 **modversions** 一致性检查；
- `__param`：`module_param` 暴露的可装载参数；
- 多个 `.initcall`/`.exitcall`、per-cpu、`__ksymtab` 相关 section。

`insmod`/`finit_module` 把文件内容交给内核后，内核（`kernel/module/main.c`）大致执行：

1. 校验 ELF、读取 `.modinfo` 与 `vermagic`；
2. 分配内核内存，拷贝各 section 并做**重定位**（ELF rela 处理，把对内核/其他模块符号的引用填成真实地址）；
3. 通过 **kallsyms / 导出符号表**解析未定义符号（见下节）；
4. 处理 modversions CRC、模块签名校验；
5. 调用模块的 init 函数；失败则回滚、释放内存。

这与用户态动态链接器 `ld.so` 加载 `.so` 的思路一致，只是发生在内核态、链接器就是内核自身。

## Exported Symbols

模块只能引用内核**显式导出**的符号：

- `EXPORT_SYMBOL(sym)`：导出给所有模块（注意 GPL 与非 GPL 的差别）；
- `EXPORT_SYMBOL_GPL(sym)`：只对声明了 GPL 兼容 license 的模块可用（`MODULE_LICENSE("GPL")` 等）。

导出信息进 `__ksymtab`，运行期体现在 `/proc/kallsyms`。一个模块自己导出的符号也能被其他模块引用，由此形成模块间依赖。`modinfo <module>.ko` 的 `depends:` 字段、以及 `modules.dep`（由 depmod 生成）记录这些依赖关系。

## Lifecycle and Tools

| 工具/文件 | 作用 |
| --- | --- |
| `insmod mod.ko` | 直接按路径装载（不自动解析依赖），系统调用 `finit_module`/`init_module` |
| `rmmod mod` | 卸载（引用计数为 0 且可卸载时），`delete_module` |
| `modprobe mod` | 按模块名从 `/lib/modules/$(uname -r)` 装载并**自动加载依赖** |
| `modprobe -r mod` | 卸载并按依赖反向移除 |
| `depmod` | 扫描生成 `modules.dep`、别名、符号映射 |
| `lsmod` | 读 `/proc/modules`，列出已装载模块及引用计数 |
| `modinfo` | 查看 `.modinfo`：license、vermagic、参数、alias、depends |
| `/sys/module/<name>/` | sysfs 下每个已装载模块的参数、引用者、状态 |

模块状态：`MODULE_STATE_LIVE`（正常运行）、`MODULE_STATE_COMING`（装载中）、`MODULE_STATE_GOING`（卸载中）。引用计数通过 `try_module_get`/`module_put` 维护，卸载必须为 0。

## Auto Loading

- **启动期**：静态编入内核的驱动可通过 uevent 触发用户态 `modprobe` 按需加载（见 [udev](/docs/CS/OS/Linux/dev/udev.md)）。
- **运行期 request_modules**：内核在需要某服务（如某网络协议、某文件系统、某字符设备主号）时调用 `request_module()`，由用户态 `kmod`（`call_usermodehelper`）执行 modprobe。
- **设备别名匹配**：模块用 `MODULE_DEVICE_TABLE(usb/pci/platform, ...)` 声明它支持的设备 ID 表，用户态依据 uevent 里的 modalias 自动选中正确驱动。

## Parameters

通过 `module_param` 声明的参数可在装载时赋值，并出现在 sysfs：

```c
static int enable = 0;
module_param(enable, int, 0644);   /* /sys/module/xxx/parameters/enable */
```

`modprobe xxx enable=1` 或 `insmod xxx.ko enable=1` 传入，方便不改代码调参。

## Versioning and Signature

内核加载外部模块时做两层一致性校验（[module](/docs/CS/OS/Linux/module/module.md) 中有代码层面的说明）：

- **vermagic / modversions**：模块记录编译所用内核版本与关键配置；开启 `CONFIG_MODVERSIONS` 后，每个被引用符号带 CRC，内核变了导致函数原型变化时 CRC 不匹配即拒绝加载（典型报错 `disagrees about version of symbol`、`exec format error`）。
- **模块签名**：开启 `CONFIG_MODULE_SIG` 后内核只加载通过密钥签名的模块（enforce 模式），防止任意代码以 root 权限注入内核；Secure Boot 系统通常强制启用。

这也说明 LKM 是**高信任**扩展：能加载模块基本等同于获得内核任意执行能力。

## LKM vs Built-in vs eBPF

| 维度 | LKM（.ko） | built-in（编入内核） | [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) |
| --- | --- | --- | --- |
| 装载 | 运行时 insmod/modprobe | 随内核启动 | 运行时 bpf() 加载 |
| 权限 | 完整内核态能力 | 完整内核态能力 | 受 verifier、helper、hook 限制 |
| 安全 | 需签名/root，无沙箱 | 随镜像可信 | 加载期静态证明安全，无签名也可受限授权 |
| 典型用途 | 设备驱动、文件系统 | 核心/启动必需功能 | 观测、网络过滤、安全策略、调度 |
| 稳定性风险 | 可直接 panic 整个内核 | 同左 | 错误多被 verifier 拦截，运行时保护更强 |
| 跨版本 | vermagic/CRC 严格绑定 | 与内核同编译 | CO-RE 借助 BTF 可跨版本 |

经验法则：写驱动、需要直接操作硬件或深度介入子系统用 LKM；做可观测性、过滤、监控、轻量策略优先 eBPF。

## Links

- [module (development)](/docs/CS/OS/Linux/module/module.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)

## References

1. [Kernel Documentation: Linux Kernel Modules](https://docs.kernel.org/core-api/kernel-hacking.html)
2. [The Linux Kernel Module Programming Guide](https://sysprog21.github.io/lkmpg/)
3. [Kernel source: kernel/module/main.c](https://elixir.bootlin.com/linux/latest/source/kernel/module/main.c)
4. [Loadable Kernel Module (LWN, An introduction)](https://lwn.net/Articles/443220/)
