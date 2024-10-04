## Introduction

ubuntu容器内配置ssh
```shell
apt-get install openssh-server
```

容器先做好ssh端口映射 如
```shell
docker run -it -p 9527:22 ubuntu
```

```shell
vim /etc/ssh/sshd_config

# set
PermitRootLogin yes
UsePAM no
```

restart
```shell
service ssh restart
```




## Links


