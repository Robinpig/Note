## Introduction

Containerization is the packaging of software code with just the operating system (OS) libraries and dependencies required to 
run the code to create a single lightweight executable—called a container—that runs consistently on any infrastructure.
More portable and resource-efficient than virtual machines (VMs), containers have become the de facto compute units of modern cloud-native applications.

Containerization allows developers to create and deploy applications faster and more securely. 
With traditional methods, code is developed in a specific computing environment which, when transferred to a new location, often results in bugs and errors. 
For example, when a developer transfers code from a desktop computer to a VM or from a Linux to a Windows operating system. 
Containerization eliminates this problem by bundling the application code together with the related configuration files, libraries, and dependencies required for it to run. 
This single package of software or “container” is abstracted away from the host operating system, and hence, 
it stands alone and becomes portable—able to run across any platform or cloud, free of issues.

Container via Virtual Machine:

- **Container**<br/>
  Containers are an abstraction at the app layer that packages code and dependencies together. 
  Multiple containers can run on the same machine and share the OS kernel with other containers, each running as isolated processes in user space. 
  Containers take up less space than VMs (container images are typically tens of MBs in size), can handle more applications and require fewer VMs and Operating systems.
- **Virtual Machine**<br/>
  Virtual machines (VMs) are an abstraction of physical hardware turning one server into many servers.
  The hypervisor allows multiple VMs to run on a single machine.
  Each VM includes a full copy of an operating system, the application, necessary binaries and libraries – taking up tens of GBs. VMs can also be slow to boot.



The concept of containerization and process isolation is actually decades old, but the emergence in 2013 of the open source [Docker Engine](/docs/CS/Container/Docker.md)—an industry standard for containers 
with simple developer tools and a universal packaging approach—accelerated the adoption of this technology.


The rapid growth in interest and usage of container-based solutions has led to the need for standards around container technology and the approach to packaging software code. 
The Open Container Initiative (OCI), established in June 2015 by Docker and other industry leaders, is promoting common, minimal, open standards and specifications around container technology. 

Today, Docker is one of the most well-known and highly used container engine technologies, but it is not the only option available. 
The ecosystem is standardizing on containerd and other alternatives like CoreOS rkt, Mesos Containerizer, LXC Linux Containers, OpenVZ, and crio-d. Features and defaults may differ,
but adopting and leveraging OCI specifications as these evolve will ensure that solutions are vendor-neutral, certified to run on multiple operating systems and usable in multiple environments.


## Links

