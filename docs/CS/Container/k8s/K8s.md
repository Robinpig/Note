## Introduction

[Kubernetes](https://kubernetes.io/), also known as K8s, is an open-source system for automating deployment, scaling, and management of [containerized](/docs/CS/Container/Container.md) applications.

> Kubernetes来源于Google内部的[Borg](/docs/CS/Distributed/Borg.md) 和 Omega集群管理系统

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

### Build

早期K8s支持使用Bazel构建

由于使用Bazel方式构建的二进制文件维护复杂度较高 同时Go语言将编译过程的中间结果缓存下来实现类似增量编译 在K8s 1.21版本移除Bazel方式

<!-- tabs:start -->



##### **Local Env**

```shell
make all

# 单独构建某个组件
make WHAT=cmd/kubectl
```

构建函数入口
kube::golang::build_binaries

##### **Container Env**


容器环境构建

```shell
# 构建所有平台
make release

# 构建当前平台
make quick-release
```

调用到build/release.sh脚本

```go

# Set up the context directory for the kube-build image and build it.
function kube::build::build_image() {
  mkdir -p "${LOCAL_OUTPUT_BUILD_CONTEXT}"
  # Make sure the context directory owned by the right user for syncing sources to container.
  chown -R ${USER_ID}:${GROUP_ID} "${LOCAL_OUTPUT_BUILD_CONTEXT}"

  cp /etc/localtime "${LOCAL_OUTPUT_BUILD_CONTEXT}/"

  cp build/build-image/Dockerfile "${LOCAL_OUTPUT_BUILD_CONTEXT}/Dockerfile"
  cp build/build-image/rsyncd.sh "${LOCAL_OUTPUT_BUILD_CONTEXT}/"
  dd if=/dev/urandom bs=512 count=1 2>/dev/null | LC_ALL=C tr -dc 'A-Za-z0-9' | dd bs=32 count=1 2>/dev/null > "${LOCAL_OUTPUT_BUILD_CONTEXT}/rsyncd.password"
  chmod go= "${LOCAL_OUTPUT_BUILD_CONTEXT}/rsyncd.password"

  kube::build::update_dockerfile
  kube::build::set_proxy
  kube::build::docker_build "${KUBE_BUILD_IMAGE}" "${LOCAL_OUTPUT_BUILD_CONTEXT}" 'false'

  # Clean up old versions of everything
  kube::build::docker_delete_old_containers "${KUBE_BUILD_CONTAINER_NAME_BASE}" "${KUBE_BUILD_CONTAINER_NAME}"
  kube::build::docker_delete_old_containers "${KUBE_RSYNC_CONTAINER_NAME_BASE}" "${KUBE_RSYNC_CONTAINER_NAME}"
  kube::build::docker_delete_old_containers "${KUBE_DATA_CONTAINER_NAME_BASE}" "${KUBE_DATA_CONTAINER_NAME}"
  kube::build::docker_delete_old_images "${KUBE_BUILD_IMAGE_REPO}" "${KUBE_BUILD_IMAGE_TAG_BASE}" "${KUBE_BUILD_IMAGE_TAG}"

  kube::build::ensure_data_container
  kube::build::sync_to_container
}
```






<!-- tabs:end -->









## Architecture

K8s借鉴了Borg的架构设计理念 如Scheduler调度器、Pod资源对象管理等

<div style="text-align: center;">

![Fig.1. Kubernetes cluster architecture](../img/Kubernetes-Cluster-Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Kubernetes cluster architecture
</p>




K8s架构分为Control Plane 和 Worker Node两部分

Control Plane基于[etcd](/docs/CS/Framework/etcd/etcd.md) 做分布式键值存储 一个具有数据副本的最小可运行集群必须至少有3个etcd节点 生产环境建议创建5个节点
Etcd集群存储Kubernetes系统集群的状态和元数据，其中包括所有Kubernetes资源对象信息、集群节点信息等
Kubernetes将所有数据存储至Etcd集群中前缀为`/registry`的目录下

Control Plane主要包含以下组件

- [scheduler](/docs/CS/Container/k8s/scheduler.md)
- [apiServer](/docs/CS/Container/k8s/apiserver.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)

工作节点主要包含以下组件:

- [kubelet](/docs/CS/Container/k8s/kubelet.md) 是在每个节点上运行的主要 “节点代理” 用于接收、处理、上报kube-apiserver下发的任务
- [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)
- Container-Runtime 负责提供容器的基础管理服务 接收 `kubelet` 的指令



除此之外, Kubernetes官方提供了命令行工具（CLI），用户可以通过[kubectl]()以命令行交互的方式与Kubernetes API Server进行通信，通信协议使用HTTP/JSON

Kubernetes系统使用client-go作为Go语言的官方编程式交互客户端库，提供对Kubernetes API Server服务的交互访问 k8s其它组件与apiserver的通信也是基于client-go实现



 


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



K8s各组件的代码入口 `main` 结构风格非常一致







## Definition

在整个Kubernetes体系架构中，资源是Kubernetes最重要的概念，可以说Kubernetes的生态系统都围绕着资源运作。Kubernetes系统虽然有相当复杂和众多的功能，但它本质上是一个资源控制系统——注册、管理、调度资源并维护资源的状态

而对资源的操作都是基于API完成的 K8s通过`kube-apiserver` 提供RESTful风格的API 实现对资源的管理

在Kubernetes庞大而复杂的系统中，只有资源是远远不够的，Kubernetes将资源再次分组和版本化，形成Group、Version、Resource
Kubernetes系统支持多个Group，每个Group支持多个Version，每个Version支持多个Resource，其中部分资源同时会拥有自己的SubResource

在定义一个Deployment YAML文件的时候 第一行的 `apiVersion:apps/v1` 中 apps表示group, v1表示版本



每一个资源都至少有两个版本，分别是外部版本（External Version）和内部版本（Internal Version）。外部版本用于对外暴露给用户请求的接口所使用的资源对象。内部版本不对外暴露，仅在Kubernetes API Server内部使用



所有资源类型都有一个具体的表示 称为Kind 又称Object Scheme, Kind分为以下几种

- Object
- List
- Simple



```go
type GroupVersionKind struct {
	Group   string
	Version string
	Kind    string
}
```





```go
type GroupVersionResource struct {
	Group    string
	Version  string
	Resource string
}
```



Scheme defines methods for serializing and deserializing API objects, a type registry for converting group, version, and kind information to and from Go schemas, and mappings between Go schemas of different versions. A scheme is the foundation for a versioned API and versioned configuration over time.



// schemas, and mappings between Go schemas of different versions. A scheme is the foundation for a versioned API and versioned configuration over time.

// foundation for a versioned API and versioned configuration over time.



```go
type Scheme struct {
	// versionMap allows one to figure out the go type of an object with
	// the given version and name.
	gvkToType map[schema.GroupVersionKind]reflect.Type

	// typeToGroupVersion allows one to find metadata for a given go object.
	// The reflect.Type we index by should *not* be a pointer.
	typeToGVK map[reflect.Type][]schema.GroupVersionKind

	// unversionedTypes are transformed without conversion in ConvertToVersion.
	unversionedTypes map[reflect.Type]schema.GroupVersionKind

	// unversionedKinds are the names of kinds that can be created in the context of any group
	// or version
	// TODO: resolve the status of unversioned types.
	unversionedKinds map[string]reflect.Type

	// Map from version and resource to the corresponding func to convert
	// resource field labels in that version to internal version.
	fieldLabelConversionFuncs map[string]map[string]FieldLabelConversionFunc

	// defaulterFuncs is an array of interfaces to be called with an object to provide defaulting
	// the provided object must be a pointer.
	defaulterFuncs map[reflect.Type]func(interface{})

	// converter stores all registered conversion functions. It also has
	// default coverting behavior.
	converter *conversion.Converter
}
```



NewScheme creates a new Scheme. This scheme is pluggable by default.

```go
func NewScheme() *Scheme {
	s := &Scheme{
		gvkToType:                 map[schema.GroupVersionKind]reflect.Type{},
		typeToGVK:                 map[reflect.Type][]schema.GroupVersionKind{},
		unversionedTypes:          map[reflect.Type]schema.GroupVersionKind{},
		unversionedKinds:          map[string]reflect.Type{},
		fieldLabelConversionFuncs: map[string]map[string]FieldLabelConversionFunc{},
		defaulterFuncs:            map[reflect.Type]func(interface{}){},
	}
	s.converter = conversion.NewConverter(s.nameFunc)

	s.AddConversionFuncs(DefaultEmbeddedConversions()...)

	// Enable map[string][]string conversions by default
	if err := s.AddConversionFuncs(DefaultStringConversions...); err != nil {
		panic(err)
	}
	if err := s.RegisterInputDefaults(&map[string][]string{}, JSONKeyMapper, conversion.AllowDifferentFieldTypeNames|conversion.IgnoreMissingFields); err != nil {
		panic(err)
	}
	if err := s.RegisterInputDefaults(&url.Values{}, JSONKeyMapper, conversion.AllowDifferentFieldTypeNames|conversion.IgnoreMissingFields); err != nil {
		panic(err)
	}
	return s
}

```





kubernetes内部资源定义
有组：pkg\apis\<group>\
无组：pkg\apis\core\types.go
外部版本

有组：staging\src\k8s.io\api\<group>\<version>\<resource file>
无组：staging\src\k8s.io\api\core\v1

资源操作方法接口
staging\src\k8s.io\apiserver\pkg\registry\rest\rest.go
资源操作方法
staging\src\k8s.io\apiserver\pkg\registry\generic\registry\store.go
定义控制器
kubernetes\pkg\controller\






### CRI-O

CRI-O is an implementation of the Kubernetes CRI (Container Runtime Interface) to enable using OCI (Open Container Initiative) compatible runtimes.
It is a lightweight alternative to using [Docker](/docs/CS/Container/Docker.md) as the runtime for kubernetes. 
It allows Kubernetes to use any OCI-compliant runtime as the container runtime for running pods. 
Today it supports runc and Kata Containers as the container runtimes but any OCI-conformant runtime can be plugged in principle.

CRI-O supports OCI container images and can pull from any container registry. 
It is a lightweight alternative to using Docker, Moby or rkt as the runtime for Kubernetes.



### Pod

PodSpec is a description of a pod

```go
type PodSpec struct {
	Volumes []Volume
	// List of initialization containers belonging to the pod.
	InitContainers []Container
	// List of containers belonging to the pod.
	Containers []Container
	// +optional
	RestartPolicy RestartPolicy
	// Optional duration in seconds the pod needs to terminate gracefully. May be decreased in delete request.
	// Value must be non-negative integer. The value zero indicates delete immediately.
	// If this value is nil, the default grace period will be used instead.
	// The grace period is the duration in seconds after the processes running in the pod are sent
	// a termination signal and the time when the processes are forcibly halted with a kill signal.
	// Set this value longer than the expected cleanup time for your process.
	// +optional
	TerminationGracePeriodSeconds *int64
	// Optional duration in seconds relative to the StartTime that the pod may be active on a node
	// before the system actively tries to terminate the pod; value must be positive integer
	// +optional
	ActiveDeadlineSeconds *int64
	// Set DNS policy for the pod.
	// Defaults to "ClusterFirst".
	// Valid values are 'ClusterFirstWithHostNet', 'ClusterFirst', 'Default' or 'None'.
	// DNS parameters given in DNSConfig will be merged with the policy selected with DNSPolicy.
	// To have DNS options set along with hostNetwork, you have to specify DNS policy
	// explicitly to 'ClusterFirstWithHostNet'.
	// +optional
	DNSPolicy DNSPolicy
	// NodeSelector is a selector which must be true for the pod to fit on a node
	// +optional
	NodeSelector map[string]string

	// ServiceAccountName is the name of the ServiceAccount to use to run this pod
	// The pod will be allowed to use secrets referenced by the ServiceAccount
	ServiceAccountName string
	// AutomountServiceAccountToken indicates whether a service account token should be automatically mounted.
	// +optional
	AutomountServiceAccountToken *bool

	// NodeName is a request to schedule this pod onto a specific node.  If it is non-empty,
	// the scheduler simply schedules this pod onto that node, assuming that it fits resource
	// requirements.
	// +optional
	NodeName string
	// SecurityContext holds pod-level security attributes and common container settings.
	// Optional: Defaults to empty.  See type description for default values of each field.
	// +optional
	SecurityContext *PodSecurityContext
	// ImagePullSecrets is an optional list of references to secrets in the same namespace to use for pulling any of the images used by this PodSpec.
	// If specified, these secrets will be passed to individual puller implementations for them to use.  For example,
	// in the case of docker, only DockerConfig type secrets are honored.
	// +optional
	ImagePullSecrets []LocalObjectReference
	// Specifies the hostname of the Pod.
	// If not specified, the pod's hostname will be set to a system-defined value.
	// +optional
	Hostname string
	// If specified, the fully qualified Pod hostname will be "<hostname>.<subdomain>.<pod namespace>.svc.<cluster domain>".
	// If not specified, the pod will not have a domainname at all.
	// +optional
	Subdomain string
	// If specified, the pod's scheduling constraints
	// +optional
	Affinity *Affinity
	// If specified, the pod will be dispatched by specified scheduler.
	// If not specified, the pod will be dispatched by default scheduler.
	// +optional
	SchedulerName string
	// If specified, the pod's tolerations.
	// +optional
	Tolerations []Toleration
	// HostAliases is an optional list of hosts and IPs that will be injected into the pod's hosts
	// file if specified. This is only valid for non-hostNetwork pods.
	// +optional
	HostAliases []HostAlias
	// If specified, indicates the pod's priority. "SYSTEM" is a special keyword
	// which indicates the highest priority. Any other name must be defined by
	// creating a PriorityClass object with that name.
	// If not specified, the pod priority will be default or zero if there is no
	// default.
	// +optional
	PriorityClassName string
	// The priority value. Various system components use this field to find the
	// priority of the pod. When Priority Admission Controller is enabled, it
	// prevents users from setting this field. The admission controller populates
	// this field from PriorityClassName.
	// The higher the value, the higher the priority.
	// +optional
	Priority *int32
	// Specifies the DNS parameters of a pod.
	// Parameters specified here will be merged to the generated DNS
	// configuration based on DNSPolicy.
	// +optional
	DNSConfig *PodDNSConfig
}
```



### probes


启动

存活

就绪



## Network Management

## Resource Management

## Scheduling

## Storage Management


## Summary

K8s 改变了传统的应用部署发布的方式，给容器化的应用服务提供了灵活方便的容器编排、容器调度和简单的服务发现机制，但缺少了更丰富和更细粒度的服务治理能力



## Links

- [Docker](/docs/CS/Container/Docker.md)


## References

1. [Kubernetes 中文社区](https://www.kubernetes.org.cn/docs)
1. [Kubernetes源码笔记](https://wqyin.cn/gitbooks/kubeSourceCodeNote/)
1. [Kubernetes源码剖析](https://blog.tianfeiyu.com/source-code-reading-notes/)