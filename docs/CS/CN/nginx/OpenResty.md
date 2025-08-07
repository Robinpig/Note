## Introduction

OpenResty 是一个兼具开发效率和性能的服务端开发平台，虽然它基于 NGINX 实现，但其适用范围，早已远远超出反向代理和负载均衡。
它的核心是基于 NGINX 的一个 C 模块（lua-nginx-module），该模块将 LuaJIT 嵌入到 NGINX 服务器中，并对外提供一套完整的 Lua API，透明地支持非阻塞 I/O，提供了轻量级线程、定时器等高级抽象。同时，围绕这个模块，OpenResty 构建了一套完备的测试框架、调试技术以及由 Lua 实现的周边功能库。
你可以用 Lua 语言来进行字符串和数值运算、查询数据库、发送 HTTP 请求、执行定时任务、调用外部命令等，还可以用 FFI 的方式调用外部 C 函数。这基本上可以满足服务端开发需要的所有功能。

OpenResty的三大特性
- 详尽的文档和测试用例
- 同步非阻塞
- 动态

和其他的开源软件一样，OpenResty 的安装有多种方法，比如使用操作系统的包管理器、源码编译或者 docker 镜像
推荐你优先使用 yum、apt-get、brew 这类包管理系统，来安装 OpenResty。这里我们使用 Mac 系统来做示例

```shell
brew install openresty/brew/openresty
```


使用 OpenResty 源码安装，不仅仅步骤繁琐，需要自行解决 PCRE、OpenSSL 等外部依赖，而且还需要手工对 OpenSSL 打上对应版本的补丁。不然就会在处理 SSL session 时，带来功能上的缺失，比如像ngx.sleep这类会导致 yield 的 Lua API 就没法使用

一个简单的OpenResty程序至少需要三步才能完成：
- 创建工作目录；
- 修改 NGINX 的配置文件，把 Lua 代码嵌入其中；
- 启动 OpenResty 服务。

mkdir helloworld cd helloworld mkdir logs/ conf/


nginx.conf 嵌入代码

```conf
events {
    worker_connections 1024;
}

http {
    server {
        listen 8080;
        location / {
            content_by_lua '
                ngx.say("hello, world")
            ';
        }
    }
}
```

启动服务

openresty -p `pwd` -c conf/nginx.conf








## Links

- [nginx](/docs/CS/CN/nginx/nginx.md)
