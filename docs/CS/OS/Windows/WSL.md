## Introduction

he Windows Subsystem for Linux (WSL) lets developers install a Linux  distribution (such as Ubuntu, OpenSUSE, Kali, Debian, Arch Linux, etc)  and use Linux applications, utilities, and Bash command-line tools  directly on Windows, unmodified, without the overhead of a traditional  virtual machine or dualboot setup.



Install

```shell
wsl --install
```





Open Windows PowerShell

```shell
wsl --shutdown
```



Avoid high CPU/memory used.

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



## References

1. [示例 .wslconfig 文件](https://learn.microsoft.com/zh-cn/windows/wsl/wsl-config)

