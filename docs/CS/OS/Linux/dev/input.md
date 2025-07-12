## Introduction

input子系统有两大类使用场景。
第一类是协助我们完成设备驱动(device), 适用于鼠标、键盘、电源按键和传感器等设备

第二类协助我们定义操作(handler)来处理input事件， 设备报告给系统数据信息、报告一系列数据的结尾标志等都属于input事件


input子系统有两个核心数据结构，input_dev和input_handler。顾名思义，input_clev对应驱动的设备端，input_handler对应的是操作(handler)




## Links

- [Linux dev](/docs/CS/OS/Linux/dev/device.md)


