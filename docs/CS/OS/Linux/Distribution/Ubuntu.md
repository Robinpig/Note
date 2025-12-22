## Introduction

> [Ubuntu Releases](https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/)



##### **Docker**

可以先`passwd root`重置密码

Docker环境下缺失很多工具

```shell
# 先update
apt-get update

apt-get install -y sudo gcc gdb file strace

```

Linux5.x 在 Intel NUC10 的核显支持不友好 Ubuntu18.04 点击进入安装界面黑屏不显示 更改为Ubuntu22.04 安装成功



[Ubuntu 更换 macOS Big Sur 主题](https://www.cnblogs.com/Undefined443/p/18133703)



中文输入法

```shell
sudo apt install -y fcitx5 \
fcitx5-chinese-addons \
fcitx5-frontend-gtk4 fcitx5-frontend-gtk3 fcitx5-frontend-gtk2 \
fcitx5-frontend-qt5

im-config
```








## Software

```shell
sudo apt search <software>
```

```shell
sudo dpkg -i xx.deb
```



##### Clash for Windows

安装[clash for windows](https://github.com/MGod-monkey/clash-for-all-backup/releases/download/v0.20.39/Clash.for.Windows-0.20.39-x64-linux.tar.gz)

```shell
mv clash /opt/clash
```





启动报错：

FATAL:setuid_sandbox_host.cc(158)] The SUID sandbox helper binary was found, but is not configured correctly. Rather than run without  sandboxing I'm aborting now. You need to make sure that  /home/user/Desktop/aep/source/build/linux-unpacked/chrome-sandbox is  owned by root and has mode 4755.

使用以下命令解决：

```shell
sudo chown root chrome-sandbox && sudo chmod 4755 chrome-sandbox
```

##### Clash Verge

[V2RaySE](https://v2rayse.com/)

下载deb文件安装



##### Guake


```shell
sudo add-apt-repository ppa:linuxuprising/guake
sudo apt-get update

sudo apt install guake
```



ubuntu的unattended-upgrade进程总是会造成一些不好的体验，

1.手动安装软件包时经常发现dpkg的锁被该进程占用，且不知道要占用多久；

2.明明在software updater里禁止了更新，但还是老弹出提醒更新。

禁用方法1：

```shell
sudo systemctl disable unattended-upgrades
```

禁用方法2：

找到启动文件/etc/apt/apt.conf.d/50unattended-upgrades ，把里面的相关内容注释掉。

把Unattended-Upgrade::Allowed-Origins里列出的origins都注释掉应该就可以了。











## Links


- [Linux](/docs/CS/OS/Linux/Linux.md)