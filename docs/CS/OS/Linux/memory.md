









Limits 

1. OS `/proc/sys/fs/file-max`
2. Process fs.nr_open
3. User process in `/etc/security/limits.conf`

```shell
> cat /proc/sys/fs/file-max 
174837

# vi /etc/sysctl.conf 
> sysctl -a |grep nr_open
fs.nr_open = 1048576

# hard limit <= fs.nr_open
> cat /etc/security/limits.conf
root soft nofile 65535
root hard nofile 65535
```





```shell
> sysctl -a |grep rmem
net.core.rmem_default = 212992
net.core.rmem_max = 212992
net.ipv4.tcp_rmem = 4096        87380   6291456
net.ipv4.udp_rmem_min = 4096
```





```shell
> sysctl -a |grep wmem
net.core.wmem_default = 212992
net.core.wmem_max = 212992
net.ipv4.tcp_wmem = 4096        16384   4194304
net.ipv4.udp_wmem_min = 4096
vm.lowmem_reserve_ratio = 256   256     32      0       0
```



```shell
> sysctl -a |grep range
net.ipv4.ip_local_port_range = 32768    60999
```



Check memory

```shell
cat /proc/meminfo 

slabtop
```



check network

```shell
ss 
```





tcp 内存使用slab分配

dmidecode 查看CPU 内存信息
每个CPU和它直接相连的内存条组成Node

numactl --hardware
查看Node情况
Node划分为Zone

```shell
cat /proc/zoneinfo #查看zone信息
```

Zone包含Page 一般为4KB


```shell
cat /proc/slabinfo
slabtop
```

slab_def.h

mm/slab.h



空establish 连接占用3.3KB左右



strace



```shell
# 
> watch 'netstat -s |grep LISTEN'

# 
> watch 'netstat -s |grep overflowed'
```



```shell
> cat  /proc/sys/net/ipv4/tcp_max_syn_backlog 
1024
```



```shell

> cat /proc/sys/net/core/somaxconn 
128
```



```shell
ss -nlt
```



