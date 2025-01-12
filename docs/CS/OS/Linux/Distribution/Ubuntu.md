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
sudo apt install fcitx5 \
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
sudo apt install <software>
```





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





## Links


- [Linux](/docs/CS/OS/Linux/Linux.md)