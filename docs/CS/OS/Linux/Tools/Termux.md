## 简介

[Termux](https://termux.dev/en/) 是一个 Android 终端模拟器和 [Linux](/docs/CS/OS/Linux/Linux.md) 环境应用，可直接使用，无需 root 或额外设置。
自动安装最小基础系统——额外的包可通过 APT 包管理器获取。



Access to shared storage
```
termux-setup-storage
```


Change Repo:

```shell
termux-change-repo
```

Network tools:

```shell
apt install net-tools

apt install dnsutils
apt install nmap

pkg install traceroute
pkg install whois
pkg install netcat-openbsd

pkg install root-repo
pkg install tcpdump
```

> 安装curl会出现libcurl.so



```shell
pkg install wget zsh -y
sh -c "$(wget -O- https://raw.githubusercontent.com/robbyrussell/oh-my-zsh/master/tools/install.sh)"
```



```shell
pkg install autojump
```



```shell
apt get update
apt get upgrade

apt get install nodejs
```



安装 proot 和 proot-distro

```bash
pkg install proot proot-distro
```

使用proot模拟linux文件系统：

```bash
termux-chroot
```

查看一下可用的发行版有哪些：

```bash
proot-distro list
```

安装 Ubuntu：

```shell
proot-distro install ubuntu
```

进入发行版环境

```bash
proot-distro login ubuntu
```




## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Termux Wiki](https://wiki.termux.com/wiki/Main_Page)
1. [一篇文章上手Termux](https://toad114514.github.io/2024/08/20/termux-all/)
1. [termux从入门到入土](https://linux.do/t/topic/270578)
