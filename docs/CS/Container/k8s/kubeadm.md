## Introduction



kubeadm的源代码，直接就在kubernetes/cmd/kubeadm目录下，是Kubernetes项目的一部分。其中，app/phases文件夹下的代码


当你执行kubeadm init指令后，kubeadm首先要做的，是一系列的检查工作，以确定这台机器可以用来部署Kubernetes。这一步检查，我们称为“Preflight Checks”

在通过了Preflight Checks之后，kubeadm要为你做的，是生成Kubernetes对外提供服务所需的各种证书和对应的目录。

Kubernetes对外提供服务时，除非专门开启“不安全模式”，否则都要通过HTTPS才能访问kube-apiserver。这就需要为Kubernetes集群配置好证书文件。

kubeadm为Kubernetes项目生成的证书文件都放在Master节点的/etc/kubernetes/pki目录下。在这个目录下，最主要的证书文件是ca.crt和对应的私钥ca.key。

此外，用户使用kubectl获取容器日志等streaming操作时，需要通过kube-apiserver向kubelet发起请求，这个连接也必须是安全的。kubeadm为这一步生成的是apiserver-kubelet-client.crt文件，对应的私钥是apiserver-kubelet-client.key。

除此之外，Kubernetes集群中还有Aggregate APIServer等特性，也需要用到专门的证书

证书生成后，kubeadm接下来会为其他组件生成访问kube-apiserver所需的配置文件。这些文件的路径是：/etc/kubernetes/xxx.conf

这些文件里面记录的是，当前这个Master节点的服务器地址、监听端口、证书目录等信息。这样，对应的客户端（比如scheduler，kubelet等），可以直接加载相应的文件，使用里面的信息与kube-apiserver建立安全连接。

接下来，kubeadm会为Master组件生成Pod配置文件

Kubernetes有三个Master组件kube-apiserver、kube-controller-manager、kube-scheduler，而它们都会被使用Pod的方式部署起来。


在这一步完成后，kubeadm还会再生成一个Etcd的Pod YAML文件，用来通过同样的Static Pod的方式启动Etcd

Master容器启动后，kubeadm会通过检查localhost:6443/healthz这个Master组件的健康检查URL，等待Master组件完全运行起来。

然后，kubeadm就会为集群生成一个bootstrap token。在后面，只要持有这个token，任何一个安装了kubelet和kubadm的节点，都可以通过kubeadm join加入到这个集群当中。

这个token的值和使用方法，会在kubeadm init结束后被打印出来。

在token生成之后，kubeadm会将ca.crt等Master节点的重要信息，通过ConfigMap的方式保存在Etcd当中，供后续部署Node节点使用。这个ConfigMap的名字是cluster-info。

kubeadm init的最后一步，就是安装默认插件。Kubernetes默认kube-proxy和DNS这两个插件是必须安装的。它们分别用来提供整个集群的服务发现和DNS功能。其实，这两个插件也只是两个容器镜像而已，所以kubeadm只要用Kubernetes客户端创建两个Pod就可以了



## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
