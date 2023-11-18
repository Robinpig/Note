## Introduction

A Docker container image is a lightweight, standalone, executable package of software that includes everything needed to run an application: code, runtime, system tools, system libraries and settings.

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


### Moby

Moby is an open framework created by Docker to assemble specialized container systems without reinventing the wheel. 
It provides a “lego set” of dozens of standard components and a framework for assembling them into custom platforms.

> [A new upstream project to break up Docker into independent components](https://github.com/moby/moby/pull/32691)

## Installing Docker

Install Docker Desktop:

<!-- tabs:start -->

##### **Ubuntu**

```shell
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
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


## Docker Image

##### 3.6.1 只读层

我们以Ubuntu为例，当执行`docker image inspect ubuntu:latest` 会发现容器的**rootfs**最下面的四层，对应的正是ubuntu:latest镜像的四层。它们的挂载方式都是只读的(ro+wh)，都以增量的方式分别包含了Ubuntu操作系统的一部分，四层联合起来组成了一个成品。

##### 3.6.2 可读写层

**rootfs** 最上层的操作权限为 **rw**， 在没有写入文件之前，这个目录是空的。而一旦在容器里做了写操作，你修改产生的内容就会以增量的方式出现在这个层中。如果你想删除只读层里的文件，咋办呢？这个问题上面已经讲解过了。

最上面这个可读写层就是专门用来存放修改 **rootfs** 后产生的增量，无论是增、删、改，都发生在这里。而当我们使用完了这个被修改过的容器之后，还可以使用 docker commit 和 push 指令，保存这个被修改过的可读写层，并上传到 Docker Hub上，供其他人使用。并且原先的只读层里的内容则不会有任何变化，这就是**增量 rootfs** 的好处。

##### 3.6.3 init 层

它是一个以`-init`结尾的层，夹在只读层和读写层之间。Init层是Docker项目单独生成的一个内部层，专门用来存放 /etc/hosts 等信息。

需要这样一层的原因是这些文件本来属于只读的Ubuntu镜像的一部分，但是用户往往需要在启动容器时写入一些指定的值比如 hostname，那就需要在可读写层对它们进行修改。可是，这些修改往往只对当前的容器有效，我们并不希望执行 docker commit 时，把 **init** 层的信息连同可读写层一起提交。

最后这6层被组合起来形成了一个完整的 **Ubuntu** 操作系统供容器使用。![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

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

## Links

- [Container](/docs/CS/Container/Container.md)
- [Kubernetes](/docs/CS/Container/K8s.md)

## References

1. [Moby](https://github.com/moby/moby)



