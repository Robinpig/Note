

## Buffer


实质是一个数组进行封装
从channel读写数据到buffer

directBuffer

mapped memory




position<=limit<=capacity

flip将limit置为之前的position


clear为重置各项为初始值

## Channel

SelectableChannel
FileChannel


## Selector
轮询注册的channel状态
SelectorProvider sychronized 单例
依据不同JDK生成不同的Selector实现类
调用OS的接口创建FD

## Reference
1. [Java NIO Tutorial](http://tutorials.jenkov.com/java-nio/index.html)