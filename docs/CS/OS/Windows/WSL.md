## 简介

适用于 Linux 的 Windows 子系统（WSL）让开发者可以直接在 Windows 上安装 Linux 发行版（如 Ubuntu、OpenSUSE、Kali、Debian、Arch Linux 等），并使用 Linux 应用程序、工具和 Bash 命令行工具，无需传统虚拟机或双系统设置的额外开销。

安装

```shell
wsl --install
```

打开 Windows PowerShell

修改完配置后使用如下命令 shutdown 后重启加载配置
```shell
wsl --shutdown
```

避免高 CPU/内存占用

使用 **.wslconfig** 为 WSL 上运行的所有已安装的发行版配置**全局设置**。

```
# Settings apply across all Linux distros running on WSL 2
[wsl2]

# Limits VM memory to use no more than 4 GB, this can be set as whole numbers using GB or MB
memory=4GB 

# Sets the VM to use two virtual processors
processors=2

# Specify a custom Linux kernel to use with your installed distros. The default kernel used can be found at https://github.com/microsoft/WSL2-Linux-Kernel
# kernel=C:\\temp\\myCustomKernel

# Sets additional kernel parameters, in this case enabling older Linux base images such as Centos 6
kernelCommandLine = vsyscall=emulate

# Sets amount of swap storage space to 8GB, default is 25% of available RAM
# swap=8GB

# Sets swapfile path location, default is %USERPROFILE%\AppData\Local\Temp\swap.vhdx
# swapfile=C:\\temp\\wsl-swap.vhdx

# Disable page reporting so WSL retains all allocated memory claimed from Windows and releases none back when free
pageReporting=false

# Turn on default connection to bind WSL 2 localhost to Windows localhost. Setting is ignored when networkingMode=mirrored
localhostforwarding=true

# Disables nested virtualization
nestedVirtualization=false

# Turns on output console showing contents of dmesg when opening a WSL 2 distro for debugging
debugConsole=true

# Enable experimental features
[experimental]
sparseVhd=true
```

查看 memory
```shell
cat /proc/meminfo
```

WSL 查看 Windows 本地磁盘 C

```shell
cd /mnt/c
```

Windows 访问 WSL 目录 在目录下执行 `explorer.exe`

## 链接

- [Windows](/docs/CS/OS/Windows/Windows.md)

## 参考

1. [示例 .wslconfig 文件](https://learn.microsoft.com/zh-cn/windows/wsl/wsl-config)
2. [Windows 10 中配置 WSL2 与 Ubuntu（进阶）](https://rich1e.github.io/workspace/Windows10%E4%B8%AD%E9%85%8D%E7%BD%AEWSL2%E4%B8%8EUbuntu%EF%BC%88%E8%BF%9B%E9%98%B6%EF%BC%89.html)
