## introduction

[Termux](https://termux.dev/en/) is an Android terminal emulator and [Linux](/docs/CS/OS/Linux/Linux.md) environment app that works directly with no rooting or setup required.
A minimal base system is installed automatically - additional packages are available using the APT package manager.



Access to shared storage
```
termux-setup-storage
```


Change Repo:

```shell
termux-change-repo
```

```shell
apt get update

apt get upgrade

apt get install nodejs
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



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Termux Wiki](https://wiki.termux.com/wiki/Main_Page)
