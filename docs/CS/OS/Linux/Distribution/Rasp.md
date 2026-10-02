## Introduction

Raspberry Pi OS（旧名 Raspbian）是树莓派基金会的官方系统，**基于 [Debian](/docs/CS/OS/Linux/Distribution/Debian.md) 针对树莓派硬件（ARM）定制**：预装桌面、编程环境与树莓派配置工具 `raspi-config`，内核与固件由官方仓库单独维护。

从 https://www.raspberrypi.com/software/ 下载官方烧录镜像工具 Raspberry Pi Imager，选择系统镜像与目标 SD 卡写入即可；烧录前可在设置里预配 SSH、Wi-Fi 与用户名，免接显示器完成 headless 初始化。

包管理与其他 Debian 系一致（`apt`），区别在于 `raspi-config` 与 `/boot/firmware/config.txt` 这套硬件配置入口。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [Debian](/docs/CS/OS/Linux/Distribution/Debian.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
