# REST


### 数据流风格(Data Flow)

#### PF

Pipe and Filter 管道和过滤器，又名单路数据流网络

优点：
- 简单性

- 支持重用 任意过滤器可连接在一起

- 维护增强方便

- 可验证性高 分析吞吐量和死锁

- 支持并发执行
  缺点：

- 管道过长 延迟增加

- 若过滤器不能批量处理输入 则按顺序处理时不允许交互 此时无法判定所属过滤器 降低用户感知性能

 #### UPF

  Uniform Pipe and Filter 统一管道和过滤器 添加约束 所有过滤器具有相同接口
  缺点：

- 数据转换格式时 约束可能降低网络性能
复制风格 (Replication Styles)
RR
Replicated Repository 复制仓库 

改善用户感知性能，维护一致性

#### $

Cache 缓存风格，较复制仓库风格实现简单，但感知性能改善不大
分层风格(Hierarchical Styles)

#### CS

Client-Server 客户-服务器

#### LS LCS

Layered System 分层系统 Layered-Client-Server 分层-客户-服务器

分层系统仅使用于客户-服务器风格

####  CSS

Client-Stateless-Server 客户-无状态-服务器

在服务器组件上不允许有会话状态，客户每个请求都必须包含理解请求必需的全部信息，会话状态保持在客户端

优点：
- 改善可见性、可靠性、可伸缩性

缺点：
- 每次请求都必须提交重复数据，降低网络性能  

#### C$SS

  Client-Cache-Stateless-Server 客户-缓存-无状态-服务器

####   CL$SS

  Layered-Client-Cache-Stateless-Server 分层-客户-缓存-无状态-服务器

通过添加代理和/或网关组件，此范例为DNS，优缺点是LCS和C$SS的并集

#### RS

Remote Session 远程会话 CS的变体 应用状态完全保存在Server

#### RDA

Remote Data Access 远程数据访问 CS变体 状态分布在Client和Server上

### 移动代码风格(Mobile Code Styles)

#### VM

Virtual Machine 虚拟机 所有移动代码风格基础 

#### REV

Remote Evaluation 远程求值

缺乏可见性

#### COD

Code on Demand 按需代码
LCODC$SS

#### MA

Mobile Agent 移动代理 

### 点对点风格(Peer-to-Peer Styles)

#### EBI

Event-based Integration 基于事件集成 隐式调用

#### C2

#### DO

Distributed Objects 分布式对象

#### BDO

Brokered Distributed Objects 被代理的分布式对象

## 简述

表征状态转移 Representational State Transfer

面向资源，其规范为JAX-RS 约定大于配置
Web 应用程序最重要的 REST 原则是，客户端和服务器之间的交互在请求之间是无状态的。从客户端到服务器的每个请求都必须包含理解请求所必需的信息。如果服务器在请求之间的任何时间点重启，客户端不会得到通知。此外，无状态请求可以由任何可用服务器回答，这十分适合云计算之类的环境。客户端可以缓存数据以改进性能。

RESTful是满足REST原则的架构风格 

特点：客户端-服务端、可缓存、无状态、按需编码、统一接口和分层系统

### 原则

- 每一个URI代表1种资源；
- 客户端使用GET、POST、PUT、DELETE4个表示操作方式的动词对服务端资源进行操作：GET用来获取资源，POST用来新建资源（也可以用于更新资源），PUT用来更新资源，DELETE用来删除资源；
- 通过操作资源的表现形式来操作资源；
- 资源的表现形式是XML或者HTML；
- 客户端与服务端之间的交互在请求之间是无状态的，从客户端到服务端的每个请求都必须包含理解请求所必需的信息。
REST架构元素
数据元素

信息核心抽象是资源 使用资源标识符

## 表述

### 连接器

使用不同连接器类型封装访问资源和移交资源表述活动，代表组件通信抽象接口。


| 连接器 | 现代互联网实例 |
| :----: | :----: |
| 客户 | libwww、libwww-perl |
| 服务器 | libwww、Apache API、NSAPI |
| 缓存 | 浏览器缓存、Akamai缓存网络 |
| 解析器 | 绑定(DNS查找库) |
| 隧道 | SOCKS、HTTP connect之后的SSL |

客户可以使用缓存避免重复网络通信、服务端可使用缓存避免重复执行响应处理，减小交互延迟

### 组件

| 组件 | 现代互联网实例 |
| :----: | :----: |
| 来源服务器 | Apache httpd、微软IIS |
| 网关 | Squid、CGI、反向代理 |
| 代理 | CERN代理、Netscape代理、Gauntlet |
| 用户代理 | Netscape Navigator、Lynx、MOMspider |

用户代理 常见为Web浏览器
REST架构视图

- 过程视图
- 连接器视图
- 数据视图

特性

## HTTP与RPC

将HTTP与RPC区分开的并不是语法，甚至也不是使用一个流作为参数所获得
的不同的特性，尽管它帮助解释了为何现有的RPC机制对于Web而言是不可用的。

HTTP与RPC之间的重大区别的是：请求是被定向到使用一个有标准语义的通用接
口（a generic interface with standard semantics）的资源，中间组件能够采用
与提供服务的机器（the machines that originate services）几乎完全相同的方式
来解释这些语义。其结果是使得一个应用能够支持转换的分层（layers of transfor
mation）和独立于信息来源的间接层（indirection that are independent of the
information origin），这对于一个需要满足互联网规模、多个组织、无法控制的
可伸缩性需求的信息系统来说，是非常有用的。

与之相比较，RPC的机制是根据语言的API（language API）来定义的，而不是根据基于网络应用的需求来定义的。