## Introduction

[Kubernetes](https://kubernetes.io/), also known as K8s, is an open-source system for automating deployment, scaling, and management of [containerized](/docs/CS/Container/Container.md) applications.

> Kubernetes来源于Google内部的Borg 和 Omega集群管理系统

Kubernetes has the following characteristics:

- It is made of a manager and a set of nodes
- It has a scheduler to place containers in a cluster
- It has an API server and a persistence layer with etcd
- It has a controller to reconcile states
- It is deployed on VMs or bare-metal machines, in public clouds, or on-premise
- It is written in Go

Kubernetes is a mature and feature-rich solution for managing containerized applications. It is not the only container orchestrator, and there are four others:

- Docker Swarm
- Apache Mesos
- Nomad from HashiCorp
- Rancher

At a high level, there is nothing different between Kubernetes and other clustering systems. 
A central manager exposes an API, a scheduler places the workloads on a set of nodes, and the state of the cluster is stored in a persistent layer.
In Kubernetes, however, the persistence layer is implemented with etcd instead of Zookeeper for Mesos.

## Installing K8s



```shell
swapoff -a

# Add vm.swappiness = 0
sudo vim /etc/sysctl.d/k8s.conf
sudo sysctl -p /etc/sysctl.d/k8s.conf
```

[Install Tools](https://kubernetes.io/docs/tasks/tools/)

Windows上WSL和虚拟机不适用 在`minikube start`报错 不支持双重虚拟化

安装minikube 依赖Docker 需要确认镜像是否可以下载

```shell
minikube status
```

### Installing kubeadm, kubelet and kubectl

You will install these packages on all of your machines:

- kubeadm: the command to bootstrap the cluster.
- kubelet: the component that runs on all of the machines in your cluster and does things like starting pods and containers.
- kubectl: the command line util to talk to your cluster.

<!-- tabs:start -->

##### **CentOS**

```shell
# Set SELinux in permissive mode (effectively disabling it)
sudo setenforce 0
sudo sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config

# This overwrites any existing configuration in /etc/yum.repos.d/kubernetes.repo
cat <<EOF > /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://mirrors.aliyun.com/kubernetes/yum/repos/kubernetes-el7-x86_64/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://mirrors.aliyun.com/kubernetes/yum/doc/yum-key.gpg https://mirrors.aliyun.com/kubernetes/yum/doc/rpm-package-key.gpg
exclude=kube*
EOF

# Only for CentOS7
cat <<EOF >  /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
EOF
sysctl --system

sudo yum install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
sudo systemctl enable --now kubelet
```

##### **Ubuntu**

```shell
sudo apt-get update
# apt-transport-https may be a dummy package; if so, you can skip that package
sudo apt-get install -y apt-transport-https ca-certificates curl gpg

curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# This overwrites any existing configuration in /etc/apt/sources.list.d/kubernetes.list
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```



##### **Mac**

Mac下通常使用Docker Desktop的k8s

遇到Kubernetes一直在starting的情况

> [`Docker Desktop for Mac` 开启并使用 `Kubernetes`](https://github.com/maguowei/k8s-docker-desktop-for-mac?tab=readme-ov-file#docker-desktop-for-mac-%E5%BC%80%E5%90%AF%E5%B9%B6%E4%BD%BF%E7%94%A8-kubernetes)





<!-- tabs:end -->

Build

```shell
make all

# 单独构建某个组件
make WHAT=cmd/kubectl
```

构建函数入口
kube::golang::build_binaries

### Installing a container runtime


容器环境构建

```shell
make quick-release
```

调用到build/release.sh脚本

<!-- tabs:start -->

Ubuntu


```

```


<!-- tabs:end -->
## Architecture

K8s借鉴了Borg的架构设计理念 如Scheduler调度器、Pod资源对象管理等

K8s架构分为Control Plane 和 Worker Node两部分
Control Plane基于etcd做分布式键值存储 Control Plane主要包含以下组件
- [scheduler](/docs/CS/Container/k8s/scheduler.md)
- [apiServer](/docs/CS/Container/k8s/apiserver.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)

工作节点主要包含以下组件:
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)
- Container-Runtime

<div style="text-align: center;">

![Fig.1. Kubernetes cluster architecture](../img/Kubernetes-Cluster-Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Kubernetes cluster architecture
</p>


kubectl是官方命令行工具 与kube-apiserver进行交互 通信协议默认HTTP/JSON


kubelet 是在每个节点上运行的主要 “节点代理” 用于接收、处理、上报kube-apiserver下发的任务
kubelet的3种标准化接口分别用于CRI、CNI和CSI

在Kubernetes中 service是分布式集群架构的核心
一个Service有以下特征
- 唯一指定名称
- 一个虚拟IP地址和端口号
- 能够提供某种远程服务能力
- 能将客户端对服务访问请求转发到一组容器应用中

在Service中每个服务进程都有独立的Endpoint

每个进程都将被包装到相应的Pod中 成为Pod中的一个容器 为了建立Pod和Service的关系 每个Pod都被打上了一个Label 然后给相应的Service定义Label Selector

Pod运行在称为Node的环境(可以是物理机器 或者是虚拟机) 每个Node可以有多个Pod 每个Pod里都有Pause的容器


在集群管理上 机器被划分为Master和其它Node Master运行着一些进程 kube-apiserver kube-controller-manager


Deployment


Master

Kubernetes runs your workload by placing containers into Pods to run on Nodes. 
A node may be a virtual or physical machine, depending on the cluster.
Each node is managed by the control plane and contains the services necessary to run Pods.

Typically you have several nodes in a cluster; in a learning or resource-limited environment, you might have only one node.

The components on a node include the kubelet, a container runtime, and the kube-proxy.





Pod gang scheduling

base on infra container




Kubernetes supports container runtimes such as containerd, CRI-O, and any other implementation of the Kubernetes CRI (Container Runtime Interface).


apiserver模块在Kubernetes中扮演了非常重要的角色。它是Kubernetes集群中所有API的主要接口，负责处理和转发集群内部和外部的API请求。


### project layout

根据 Standard Go Project Layout 方案 来看一下Kubernetes Project Layout 的设计


| 目录         | 说明       |
|------------|----------|
| cmd        | 可执行文件入口  |
| pkg        | 核心库代码    |
| vendor     |          |
| api        |          |
| build      |          |
| test       |          |
| docs       |          |
| hack       |          |
| third_party |          |
| plugin     |          |
| staging    | 核心库暂存目录 该目录下的核心包多以软连接的方式链接到 vendor/k8s.io 目录 |
| translations |          |
| CHANGELOG  |          |




## CRI-O

CRI-O is an implementation of the Kubernetes CRI (Container Runtime Interface) to enable using OCI (Open Container Initiative) compatible runtimes.
It is a lightweight alternative to using [Docker](/docs/CS/Container/Docker.md) as the runtime for kubernetes. 
It allows Kubernetes to use any OCI-compliant runtime as the container runtime for running pods. 
Today it supports runc and Kata Containers as the container runtimes but any OCI-conformant runtime can be plugged in principle.

CRI-O supports OCI container images and can pull from any container registry. 
It is a lightweight alternative to using Docker, Moby or rkt as the runtime for Kubernetes.



### Pod



### probes


启动

存活

就绪



## Network Management

## Resource Management

## Scheduling

## Storage Management



## Links

- [Docker](/docs/CS/Container/Docker.md)


## References

1. [Kubernetes 中文社区](https://www.kubernetes.org.cn/docs)
1. [Kubernetes源码笔记](https://wqyin.cn/gitbooks/kubeSourceCodeNote/)
1. [Kubernetes源码剖析](https://blog.tianfeiyu.com/source-code-reading-notes/)