# Dubbo

[Apache Dubbo](http://dubbo.apache.org/) is a high-performance, java based open source RPC framework.

## Design

![Dubbo Framework](https://github.com/Robinpig/Note/raw/master/images/Dubbo/Dubbo-framework.png)



## SPI

use Adapter

Wrapper class

JavaAssist

## Transport
AbstractServer.doOpen()->create a Netty or Mina Server.

Request Event connected by NettyServer -> AllChannelHandler -> Executor Service 
-> Dubbo Protocol invoke() -> received

- received
- handleRequest

-> reply()

RegistryProtocol

- create Registry
- do Register

Dispatcher
AllDispstcher

ThreadPool Model

GenericFilter

