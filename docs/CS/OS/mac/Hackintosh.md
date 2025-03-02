## Introduction



安装 [Etcher](https://etcher.balena.io/)

下载dmg镜像 带有OC的镜像为佳 通过Etcher制作安装U盘 随后将配置的EFI拷贝到U盘

### OpenCore Boot Manager


| Tool                                                                       | OS                  |
| -------------------------------------------------------------------------- | ------------------- |
| [Hackintool](https://github.com/benbaker76/Hackintool)                     | Mac                 |
| [OpenCore Configurator](https://github.com/notiflux/OpenCore-Configurator) | Mac                 |
| [ProperTree](https://github.com/corpnewt/ProperTree)                       | Mac, Linux, Windows |
| [OpenCore Auxiliary Tools](https://github.com/ic005k/OCAuxiliaryTools)     | Mac, Linux, Windows |



> [!WARNING]
> 
> AMD CPU不支持虚拟机 Docker





BIOS 设置



 | Bios选项名         | 选项     |
 | ------------------ | -------- |
 | VT-d               | Enabled  |
 | XHCI-Hand-Off      | Enabled  |
 | Above 4G Decoding  | Enabled  |
 | Fast Boot          | Disabled |
 | CSM                | Disabled |
 | Secure Boot        | Disabled |
 | Resize Bar Support | Enabled  |



kext

常见kext如下：

| Lilu.kext                                                | 几乎所有kexts的依赖，没有Lilu就无法正常使用 AppleALC、WhateverGreen、VirtualSMC等。支持10.8以上系统。 |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| VirtualSMC.kext                                          | 模拟白苹果的SMC芯片（类似于大脑中枢），支持10.6以上系统。    |
| WhatEverGreen.kext                                       | 显卡必备，99%的显卡都需要用这个驱动，不管独显核显。支持10.8以上系统。 |
| AppleALC.kext AppleALCU.kext VooDooHDA.kext      | 1.声卡驱动，大部分声卡原生支持，可以驱动麦克风。注意，AMD的CPU或主板，在大部分情况下无法正常驱动麦克风。详细的原声声卡驱动以及需要注入的layout-id情况可以看github的原文链接：[https://github.com/acidanthera/AppleALC/wiki/Supported-codecs](https://link.zhihu.com/?target=https%3A//github.com/acidanthera/AppleALC/wiki/Supported-codecs) 2.AppleALCU是ALC的精简版，非特殊不建议使用。 3.VooDooHDA是AppleALC的替代驱动，支持10.6到11.2系统。如果ALC和ALCU均无法驱动你的神仙声卡、麦克风，建议你试试这个。 |
| USBToolBox.kext                                          | 某些无法驱动USB接口的机器可以使用这个驱动。                  |
| 有线网卡驱动 主要包括 AtherosE2200Ethernet.kext IntelMausi.kext LucyRTL8125Ethernet.kext RealtekRTL8111.kext | 第一个是Atheros网卡需要的，第二个是给Intel网卡的，第三个是给Realtek 2.5Gb网卡的，需要10.15以上版本。IntelMausi.kext的详细支持列表可以参考[https://github.com/acidanthera/IntelMausi](https://link.zhihu.com/?target=https%3A//github.com/acidanthera/IntelMausi)。 |
| 无线网卡驱动 主要包括 Airportitlwm.kext              | Intel的Wi-Fi驱动，完成度极高，支持10.13以上系统。但是可以驱动的网卡型号是有限的，详见10.17节。 |
| 蓝牙驱动 主要包括 IntelBlueToothFirmware.kext        | 要和Airportitlwm.kext搭配使用。支持10.13以上系统。           |





NVRAM -> boot-args







USB定制

Windows 下使用 [USBToolBox](https://github.com/USBToolBox/tool/) 来定制 USB，最后再使用 Hackintool 简单微调修正一下



除了上述生成的 `UTBMap.kext` 文件以外，我们还需要配合 `USBToolBox.kext` 使用。

USBToolBox.kext 官方下载地址为：https://github.com/USBToolBox/kext/releases


## Links

- [MacOS](/docs/CS/OS/mac/mac.md)


## References

1. [Hackintosh.com](https://hackintosh.com/)