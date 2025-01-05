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



> [trzsz-ssh ( tssh )](https://github.com/trzsz/trzsz-ssh/tree/main) is an ssh client designed as a drop-in replacement for the openssh client.





## Links


