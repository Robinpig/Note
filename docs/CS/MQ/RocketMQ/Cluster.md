## Introduction

Slave 同步 Broker的消息主要是 HAClient 这个类

masterAddress 保存 master的信息

Master的 masterAddress 为 null

processReadEvent 是普通NIO程序处理接收数据的地方

读取消息 调用 dispatchReadRequest 处理数据


reportSlaveMaxOffsetPlus
如果 CommitLog的最大位移比上次同步的大，则发送回 master 并更新 currentReportedOffset


Master 的 AcceptSocketService 负责接收 slave的连接

ReadSocketService 负责处理 slave上传进度等其它消息


GroupSocketService



## Links



