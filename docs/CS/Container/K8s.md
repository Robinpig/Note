## Introduction

[Kubernetes](https://kubernetes.io/), also known as K8s, is an open-source system for automating deployment, scaling, and management of [containerized](/docs/CS/Container/Container.md) applications.

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




<div style="text-align: center;">

![Fig.1. Kubernetes cluster architecture](img/Kubernetes-Cluster-Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Kubernetes cluster architecture
</p>

Master

Kubernetes runs your workload by placing containers into Pods to run on Nodes. 
A node may be a virtual or physical machine, depending on the cluster.
Each node is managed by the control plane and contains the services necessary to run Pods.

Typically you have several nodes in a cluster; in a learning or resource-limited environment, you might have only one node.

The components on a node include the kubelet, a container runtime, and the kube-proxy.





Pod gang scheduling

base on infra container




Kubernetes supports container runtimes such as containerd, CRI-O, and any other implementation of the Kubernetes CRI (Container Runtime Interface).

## CRI-O

CRI-O is an implementation of the Kubernetes CRI (Container Runtime Interface) to enable using OCI (Open Container Initiative) compatible runtimes.
It is a lightweight alternative to using [Docker](/docs/CS/Container/Docker.md) as the runtime for kubernetes. 
It allows Kubernetes to use any OCI-compliant runtime as the container runtime for running pods. 
Today it supports runc and Kata Containers as the container runtimes but any OCI-conformant runtime can be plugged in principle.

CRI-O supports OCI container images and can pull from any container registry. 
It is a lightweight alternative to using Docker, Moby or rkt as the runtime for Kubernetes.



### Pod



## Network Management

## Resource Management

## Scheduling

## Storage Management




## Links


## References

1. [Kubernetes 中文社区](https://www.kubernetes.org.cn/docs)