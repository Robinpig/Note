## Introduction



kubeadm的源代码，直接就在kubernetes/cmd/kubeadm目录下，是Kubernetes项目的一部分。其中，app/phases文件夹下的代码


编写了一个给kubeadm用的YAML文件（名叫：kubeadm.yaml）：

```yaml
apiVersion: kubeadm.k8s.io/v1alpha1
kind: MasterConfiguration
controllerManagerExtraArgs:
horizontal-pod-autoscaler-use-rest-clients: "true"
horizontal-pod-autoscaler-sync-period: "10s"
node-monitor-grace-period: "10s"
apiServerExtraArgs:
runtime-config: "api/all=true"
kubernetesVersion: "stable-1.11"
```


```shell
kubeadm init --config kubeadm.yaml
```
就可以完成Kubernetes Master的部署

部署完成后，kubeadm会生成一行指令：

```
kubeadm join 10.168.0.2:6443 --token 00bwbx.uvnaa2ewjflwu1ry --discovery-token-ca-cert-hash sha256:00eb62a2a6020f94132e3fe1ab721349bbcd3e9b94da9654cfe15f2985ebd711
```
这个kubeadm join命令，就是用来给这个Master节点添加更多工作节点（Worker）的命令。我们在后面部署Worker节点的时候马上会用到它，所以找一个地方把这条命令记录下来。

此外，kubeadm还会提示我们第一次使用Kubernetes集群所需要的配置命令：

mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

而需要这些配置命令的原因是：Kubernetes集群默认需要加密方式访问。所以，这几条命令，就是将刚刚部署生成的Kubernetes集群的安全配置文件，保存到当前用户的.kube目录下，kubectl默认会使用这个目录下的授权信息访问Kubernetes集群。

如果不这么做的话，我们每次都需要通过export KUBECONFIG环境变量告诉kubectl这个安全配置文件的位置

可以使用kubectl get命令来查看当前唯一一个节点的状态

在调试Kubernetes集群时，最重要的手段就是用kubectl describe来查看这个节点（Node）对象的详细信息、状态和事件（Event）

通过kubectl describe指令的输出，我们可以看到NodeNotReady的原因在于，我们尚未部署任何网络插件


在Kubernetes项目“一切皆容器”的设计理念指导下，部署网络插件非常简单，只需要执行一句kubectl apply指令，以Weave为例：

$ kubectl apply -f https://git.io/weave-kube-1.6



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
