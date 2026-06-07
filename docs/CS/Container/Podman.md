## Introduction

[Podman](http://podman.io/) 是一款无守护进程、开源、Linux 原生工具，旨在使用开放容器倡议（[OCI](https://www.opencontainers.org/)）[容器](https://developers.redhat.com/blog/2018/02/22/container-terminology-practical-introduction/#h.j2uq93kgxe0e)和[容器镜像](https://developers.redhat.com/blog/2018/02/22/container-terminology-practical-introduction/#h.dqlu6589ootw)，方便查找、运行、构建、共 享和部署应用程序。
Podman 提供了一个命令行界面（CLI），任何使用过 Docker [容器引擎](https://developers.redhat.com/blog/2018/02/22/container-terminology-practical-introduction/#h.6yt1ex5wfo3l)的人都很熟悉。
大多数用户只需将 Docker 别名到 Podman（别名 docker=podman）就行，没有任何问题。
与其他常见[的容器引擎](https://developers.redhat.com/blog/2018/02/22/container-terminology-practical-introduction/#h.6yt1ex5wfo3l)（Docker、CRI-O、containerd）类似，Podman 依赖于符合 OCI 标准的[容器运行时](https://developers.redhat.com/blog/2018/02/22/container-terminology-practical-introduction/#h.6yt1ex5wfo55)（runc、crun、runv 等）与操作系统接口并创建运行中的容器。
这使得Podman制造的运行容器几乎与其他常见容器引擎的容器无异。

Podman控制的容器可以由root或非特权用户运行。Podman 管理整个容器生态系统，包括 pod、容器、容器映像和容器卷，使用 [libpod](https://github.com/containers/podman) 库。Podman 专注于维护和修改 OCI 容器镜像的所有命令和功能，如拉取和标记。它允许你在生产环境中创建、运行和维护这些容器和容器镜像。

有一个 RESTFul API 来管理容器。我们还有一个远程 Podman 客户端，可以与 RESTFul服务。我们目前支持Linux、Mac和Windows平台的客户。RESTFul 服务仅为 支持Linux平台

## Installation

```shell
brew install podman

# Ubuntu 20.10 and newer
sudo apt-get update
sudo apt-get -y install podman
```

mirrors

```
# 1. 创建或编辑配置文件
sudo mkdir -p /etc/containers
sudo nano /etc/containers/registries.conf

```

配置

```
unqualified-search-registries = ["docker.io"]
[[registry]]
prefix = "docker.io"
location = "docker.mirrors.ustc.edu.cn"
```



清理缓存（可选）

```shell
podman system prune -f
```

拉取测试镜像

```shell
podman pull nginx:latest
```

若输出包含 registry.aliyuncs.com 即表示加速生效







## compose



podman-compose 基于Python

```shell
```





## Links

- [Docker](/docs/CS/Container/Docker/Docker.md)
