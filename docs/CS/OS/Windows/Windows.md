## Introduction











[CMD](/docs/CS/OS/Windows/CMD.md)





[WSL](/docs/CS/OS/Windows/WSL.md)





[Tools](/docs/CS/OS/Windows/Tools.md)



## Windows NT

Windows NT是微软于1993年推出的面向工作站、网络服务器和大型计算机的网络操作系统，也可做PC操作系统。它是一款全新从零开始开发的新操作系统，并应用了现代硬件的所有特性，“NT”所指的便是“新技术”（New Technology）

微软自己在HAL层上是定义了一个小内核，小内核之下是硬件抽象层HAL，这个HAL存在的好处是：不同的硬件平台只要提供对应的HAL就可以移植系统了。小内核之上是各种内核组件，微软称之为内核执行体，它们完成进程、内存、配置、I/O文件缓存、电源与即插即用、安全等相关的服务。
每个执行体互相独立，只对外提供相应的接口，其它执行体要通过内核模式可调用接口和其它执行体通信或者请求其完成相应的功能服务。所有的设备驱动和文件系统都由I/O管理器统一管理，驱动程序可以堆叠形成I/O驱动栈，功能请求被封装成I/O包，在栈中一层层流动处理。Windows引以为傲的图形子系统也在内核中




[ReactOS](https://reactos.org/what-is-reactos/) is an operating system.
Our own main features are:
- ReactOS is able to run Windows software
- ReactOS is able to run Windows drivers
- ReactOS looks-like Windows
- ReactOS is free and open source



## Links



- [Linux](/docs/CS/OS/Linux/Linux.md)



