## Introduction

A Docker container image is a lightweight, standalone, executable package of software that includes everything needed to run an application: code, runtime, system tools, system libraries and settings.

> 2013年3月15日 PyCon Solomon Hykes的演讲 [The future of Linux Containers](https://www.youtube.com/watch?v=wW9CAH9nSLs)

**Container images** become containers at runtime and in the case of **Docker containers** – images become containers when they run on Docker Engine.<br/> 
Available for both Linux and Windows-based applications, containerized software will always run the same, regardless of the infrastructure.
Containers isolate software from its environment and ensure that it works uniformly despite differences for instance between development and staging.

Docker runs Linux software on most systems. 
Docker for Mac and Docker for Windows integrate with common virtual machine (VM) technology to create portability with Windows and macOS. 
But Docker can run native Windows applications on modern Windows server machines.

Docker containers that run on Docker Engine:

* **Standard:** Docker created the industry standard for containers, so they could be portable anywhere
* **Lightweight:** Containers share the machine’s OS system kernel and therefore do not require an OS per application, driving higher server efficiencies and reducing server and licensing costs
* **Secure:** Applications are safer in containers and Docker provides the strongest default isolation capabilities in the industry

> 目前使用Docker基本上有两个选择： **Docker Desktop** 和 **Docker Engine**
>
> - Docker Desktop是专门针对个人使用而设计的，支持Mac和Windows快速安装，具有直观的图形界面，还集成了许多周边工具，方便易用
> - Docker Engine则和Docker Desktop正好相反，完全免费，但只能在Linux上运行，只能使用命令行操作


### Moby

Moby is an open framework created by Docker to assemble specialized container systems without reinventing the wheel. 
It provides a “lego set” of dozens of standard components and a framework for assembling them into custom platforms.

> [A new upstream project to break up Docker into independent components](https://github.com/moby/moby/pull/32691)

## Installing Docker

Install Docker Desktop:

> IDEA和VS Code的Docker插件非常实用


<!-- tabs:start -->




##### **Ubuntu**

```shell
sudo apt install -y docker.io

```

##### **Fedora**

```shell
# Uninstall old versions
sudo dnf remove docker \
                  docker-client \
                  docker-client-latest \
                  docker-common \
                  docker-latest \
                  docker-latest-logrotate \
                  docker-logrotate \
                  docker-selinux \
                  docker-engine-selinux \
                  docker-engine

sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo

sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl start docker
```

##### **Mac**

ARM mac 最好使用ARM 版本 Homebrew来安装 Docker


```shell
brew install --cask docker
brew install docker

#rm files if has installed docker
brew uninstall  docker
brew uninstall  --cask docker
rm -rf /usr/local/bin/docker
rm -rf /usr/local/etc/bash_completion.d/docker
rm -rf /usr/local/share/zsh/site-functions/_docker
rm -rf /usr/local/share/fish/vendor_completions.d/docker.fish
```

<!-- tabs:end -->



第一个 `service docker start` 是启动Docker的后台服务，第二个 `usermod -aG` 是把当前的用户加入Docker的用户组。这是因为操作Docker必须要有root权限，而直接使用root用户不够安全， 加入Docker用户组是一个比较好的选择，这也是Docker官方推荐的做法

```plain
sudo service docker start         #启动docker服务
# 重新登录后生效
sudo usermod -aG docker ${USER}   #当前用户加入docker组
```

After installed done, open Docker Desktop and set registry-mirrors:

```json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://registry.docker-cn.com",
    "http://hub-mirror.c.163.com",
    "https://mirror.ccs.tencentyun.com"
  ]
}
```


Docker开启监听2375端口

<!-- tabs:start -->

##### **Mac**

```shell
docker run -it -d --name=socat \
  -p 2375:2375 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  alpine/socat \
  TCP4-LISTEN:2375,fork,reuseaddr UNIX-CONNECT:/var/run/docker.sock
```

##### **Windows**

Windows较为复杂 `netstat -ano | findstr :2375` 发现没有进程
[Port 2375 not listening](https://github.com/docker/for-win/issues/3546)
```
netsh interface ipv4 show excludedportrange protocol=tcp
```



停止winnat服务
```shell
net stop winnat
dism.exe /Online /Disable-Feature:Microsoft-Hyper-V
```


```shell
netsh int ipv4 add excludedportrange protocol=tcp startport=2375 numberofports=1
```

reset后重启
```shell
netsh int ip reset
```

<!-- tabs:end -->


Docker builds containers using 10 major system features.
The specific features are as follows:
- PID namespace— Process identifiers and capabilities
- UTS namespace— Host and domain name
- MNT namespace— Filesystem access and structure
- IPC namespace— Process communication over shared memory
- NET namespace— Network access and structure
- USR namespace— User names and identifiers
- chroot syscall—Controls the location of the filesystem root
- cgroups— Resource protection
- CAP drop— Operating system feature restrictions
- Security modules— Mandatory access controls
         

## Under Hood



Docker 底层技术主要包括 Namespaces，Cgroups 和 rootfs。

Namespace 的作用是访问隔离，Linux Namespaces 机制提供 种资源隔离方案。每个 Namespace 下的资源，对于其他 Namespace 下的资源都是不可见的。

Cgroup 主要用来资源控制，CPU\MEM\宽带等。提供的 种可以限制、记录、隔离进程组所使用的物理资源机制，实现进程资源控制。

rootfs 的作用是文件系统隔离









## Architecture


Docker uses a client-server architecture.
The Docker client talks to the Docker daemon, which does the heavy lifting of building, running, and distributing your Docker containers.
The Docker client and daemon can run on the same system, or you can connect a Docker client to a remote Docker daemon.
The Docker client and daemon communicate using a REST API, over UNIX sockets or a network interface.
Another Docker client is Docker Compose, that lets you work with applications consisting of a set of containers.


<div style="text-align: center;">

![Fig.1. Docker architecture](img/Docker-Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Docker architecture
</p>

- Docker client
- Docker daemon
- Registry
- Graph
- Driver
- libcontainer
- Container





By default all files created inside a container are stored on a writable container layer. 
This means that:

- The data doesn't persist when that container no longer exists, and it can be difficult to get the data out of the container if another process needs it.
- A container's writable layer is tightly coupled to the host machine where the container is running. You can't easily move the data somewhere else.
- Writing into a container's writable layer requires a storage driver to manage the filesystem. The storage driver provides a union filesystem, using the Linux kernel.
  This extra abstraction reduces performance as compared to using data volumes, which write directly to the host filesystem.

Docker has two options for containers to store files on the host machine, so that the files are persisted even after the container stops: volumes, and bind mounts.<br/>
Docker also supports containers storing files in-memory on the host machine. Such files are not persisted.


No matter which type of mount you choose to use, the data looks the same from within the container. 
It is exposed as either a directory or an individual file in the container's filesystem.

An easy way to visualize the difference among volumes, bind mounts, and `tmpfs` mounts is to think about where the data lives on the Docker host.

- Volumes are stored in a part of the host filesystem which is managed by Docker (/var/lib/docker/volumes/ on Linux).
  Non-Docker processes should not modify this part of the filesystem. Volumes are the best way to persist data in Docker.
- Bind mounts may be stored anywhere on the host system. They may even be important system files or directories. 
  Non-Docker processes on the Docker host or a Docker container can modify them at any time.
- `tmpfs` mounts are stored in the host system's memory only, and are never written to the host system's filesystem.




## Docker Images



Docker 可以将 个基础系统锐像可以披多个锐像共用。这里可以代入调用和级存的概念。保证每个容器体积小，速度快，性能忧

采用了分层设计，启动容器后，镜像永远是只读属性。只不过在最上层加 层读写层（容器层），如果要对底层镜像的文件进行更改，读写层会复制 份镜像中的只读层进行写操作，这就是 Copy On Write

```shell
docker images

# 需要先修改为规范的镜像
docker tag name:version username/name:version

docker push username/name:version
```













## Dockerfile

A Docker Dockerfile contains a set of instructions for how to build a Docker image. 
The Docker build command executes the Dockerfile and builds a Docker image from it.

A Docker image typically consists of:

- A base Docker image on top of which to build your own Docker image.
- A set of tools and applications to be installed in the Docker image.
- A set of files to be copied into the Docker image (e.g configuration files).
- Possibly a network (TCP / UDP) port (or more) to be opened for traffic in the firewall. 
- etc.


A Dockerfile consists of a set of instructions. 
Each instruction consists of a command followed by arguments to that command, similar to command line executables.

A Docker image consists of layers. Each layer adds something to the final Docker image. Each layer is actually a separate Docker image.
The Dockerfile FROM command specifies the base image of your Docker images.


The CMD command specifies the command line command to execute when a Docker container is started up which is based on the Docker image built from this Dockerfile.

The Dockerfile COPY command copies one or more files from the Docker host (the computer building the Docker image from the Dockerfile) into the Docker image. 
The COPY command can copy both a file or a directory from the Docker host to the Docker image.

The Dockerfile ADD instruction works in the same way as the COPY instruction with a few minor differences:

- The ADD instruction can copy and extract TAR files from the Docker host to the Docker image.
- The ADD instruction can download files via HTTP and copy them into the Docker image.

The Dockerfile ENV command can set an environment variable inside the Docker image.


The Dockerfile RUN command can execute command line executables within the Docker image.

The Dockerfile EXPOSE instruction opens up network ports in the Docker container to the outside world.


The Dockerfile HEALTHCHECK instruction can execute a health check command line command at regular intervals, 
to monitor the health of the application running inside the Docker container.


## Docker Network

Libnetwork

drivers:
- bridge
- host
- null
- remote
- overlay




## Docker Volume



Issues

low Buffered IO isolation level

Sometimes Docker daemon accident

container killed because of OOM

Disable OOM_kill cause Host server down


## Docker Compose


[Docker Compose](https://docs.docker.com/compose/)将所管理的容器分为三层， 分别是工程（project），服务（service）以及容器（containner）
docker-compose并没有解决负载均衡的问题。因此需要借助其他工具实现服务发现及负载均衡


每个目录下有且仅有一个docker-compose.yml文件用于描述Docker配置





## Links

- [Container](/docs/CS/Container/Container.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [Moby](https://github.com/moby/moby)



