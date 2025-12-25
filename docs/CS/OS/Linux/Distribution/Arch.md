## Introduction

Arch Linux 是少数几个原生的 Linux 发行版之一，它并不基于任何现有的发行版或操作系统
Arch 为用户提供了一种纯粹的 Linux 体验。默认安装时，仅包含一个最小化的基础系统——用户需要根据自己的需求，手动配置并添加所需的内容



## Installation



启动进入 LiveUSB 系统后，先确认验证引导模式是否为 UEFI。

```sh
ls /sys/firmware/efi/efivars
```

如果显示有目录且无错误，则系统是以 UEFI 模式引导的，**本指南也只针对 UEFI 模式安装的**



镜像源

编辑 `/etc/pacman.d/mirrorlist` 文件，并将 `Server = https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch` 放置**最上方**即可

更新软件包缓存：



```
pacman -Syyu
```





更新系统时间



```shell
timedatectl set-ntp true
```





安装必要软件



```sh
pacstrap /mnt base linux linux-firmware lvm2
```





生成 fstab 文件：

```sh
genfstab -U /mnt >> /mnt/etc/fstab
```





Change root 到新安装的系统：

```sh
arch-chroot /mnt
```





时区

```sh
ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
```

Root 密码

passwd



网络管理

```sh
sudo pacman -S networkmanager
sudo systemctl enable NetworkManager
```





GRUB

```shell
sudo pacman -S grub efibootmgr
```





```shell
useradd -G -m robin

passwd robin
```





为了让用户可以获取管理员权限，我们需要修改 sudo 的配置。



```
vim visudo
```

去掉 `%wheel ALL=(ALL:ALL) ALL` 前面的 `#` 以取消注释，让 `wheel` 用户组获得管理员权限











## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [安装 Arch Linux 系统](https://razonyang.com/zh-hans/archlinux-guide/installation/)