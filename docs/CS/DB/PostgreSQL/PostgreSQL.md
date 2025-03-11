## Introduction






子事务


存储引擎只有redolog 没有undo log 子事务实现是通过分配一个新的事务id
子事务还可以继续创建子事务 构成一个树状结构

jDBC驱动配置了autosave需要同时配置cleanup savepoints 否则会引起性能问题



## Build



```dockerfile
FROM centos:7

RUN mv /etc/yum.repos.d/CentOS-Base.repo /etc/yum.repos.d/CentOS-Base.repo_bak

RUN curl -o /etc/yum.repos.d/CentOS-Base.repo https://mirrors.aliyun.com/repo/Centos-7.repo

RUN yum clean all
RUN rm -rf  /var/cache/yum/

RUN yum makecache;
RUN yum update -y

RUN yum install -y wget gcc gdb bison flex perl readline-devel zlib-devel perl-Test-Harness make systemd-devel libicu-devel


RUN useradd -m postgres
RUN mkdir /home/postgres/data
RUN mkdir /home/postgres/init
RUN chown -R postgres:postgres /home/postgres


RUN mkdir /pg && cd /pg

RUN wget https://ftp.postgresql.org/pub/source/v17.4/postgresql-17.4.tar.gz

RUN tar -xf postgresql-17.4.tar.gz

RUN cd postgresql-17.4 && ./configure --enable-debug \
  --datadir=/home/postgres/init \
  --with-pgport=5432 \
  --prefix=/usr/local/pgsql \
  --with-systemd \
  --with-segsize=16 \
  --with-blocksize=8 \
  --with-wal-blocksize=8

RUN make -j8

RUN make install

RUN su  postgres

RUN /usr/local/pgsql/bin/initdb -D /home/postgres/data
```

创建systemd配置文件`/etc/systemd/system/postgresql.service`

```
[Unit]
Description=PostgreSQL database server
Documentation=man:postgres(1)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=postgres
ExecStart=/usr/local/pgsql/bin/postgres -D /home/postgres/data
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target

```
开机启动
```shell
systemctl enable postgresql --now
```




## Engine


OrioleDB





## Links


## References

1. [PGlite - Postgres in WASM](https://github.com/electric-sql/pglite)
1. [从源码编译安装PostgreSQL 16.x](https://blog.frognew.com/2023/11/install-postgresql-16-from-source-code.html)
