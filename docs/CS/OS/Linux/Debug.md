



### install vmware



### install ubuntu

download & install ubuntu (disk space prefer **100GB**)

```
http://mirrors.aliyun.com/ubuntu-releases/14.04/ubuntu-14.04.6-desktop-amd64.iso
```





```shell
# set root password
sudo passwd 

su root

apt-get update

# install
apt-get install vim tmux openssh-server git -y

# start ssh
ps -e | grep ssh
sudo /etc/init.d/ssh start

# set PermitRootLogin yes
vim /etc/ssh/sshd_config

sudo /etc/init.d/ssh restart
```



### compile kernel

```shell
# download kernel
cd /root
wget https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.0.1.tar.xz
xz -d linux-5.0.1.tar.xz
tar -xvf linux-5.0.1.tar
cd linux-5.0.1

apt install build-essential flex bison libssl-dev libelf-dev libncurses-dev -y

# set menuconfig
make menuconfig

# make sure below settings are inculded
Kernel hacking  --->
     Compile-time checks and compiler options  ---> 
         [*] Compile the kernel with debug info
         [*]     Provide GDB scripts for kernel debugging


Processor type and features  --->
    [*] Randomize the address of the kernel image (KASLR) 

# make
make

mkdir rootfs
```



### install vscode

**Here are install vscode in Ubuntu. If you want to use vscode in MacOS only, just need to install plugins.**

code version is code_1.58.2-1626302803_amd64.deb

because of the Ubuntu version '14.04.6', the code will run fail

f you run `code --verbose` you will see real problem



```shell

apt-get install dpkg

wget https://mirrors.wikimedia.org/ubuntu/ubuntu/pool/main/g/gcc-10/libstdc%2B%2B6_10.3.0-1ubuntu1~20.04_amd64.deb

# extract a directory 'usr'
dpkg-deb -R libstdc++6_10.3.0-1ubuntu1~20.04_amd64.deb .


# libstdc++.so.6  libstdc++.so.6.0.28 in usr/lib/x86_64-linux-gnu
cp -P usr/lib/x86_64-linux-gnu/* /usr/share/code/

```



#### install plugins

1. c/cpp for ssh
2. remote ssh

#### set configurations

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "kernel-debug",
            "type": "cppdbg",
            "request": "launch",
            "miDebuggerServerAddress": "127.0.0.1:1234",
            "program": "${workspaceFolder}/vmlinux",
            "args": [],
            "stopAtEntry": false,
            "cwd": "${workspaceFolder}",
            "environment": [],
            "externalConsole": false,
            "logging": {
                "engineLogging": false
            },
            "MIMode": "gdb",
        }
    ]
}
```



### install gdb

```shell
cd /root
gdb -v | grep gdb
apt remove gdb -y
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt install software-properties-common
sudo apt-get update
sudo apt-get install gcc-snapshot -y
gcc --version
sudo apt install gcc-9 g++-9 -y
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 90 --slave /usr/bin/g++ g++ /usr/bin/g++-9
gcc --version
wget https://mirror.bjtu.edu.cn/gnu/gdb/gdb-8.3.tar.xz
tar -xvf gdb-8.3.tar.xz
cd gdb-8.3
# 修改 gdb/remote.c 代码。
vim gdb/remote.c


```

file change

```c
  /* Further sanity checks, with knowledge of the architecture.  */
    // if (buf_len > 2 * rsa->sizeof_g_packet)
    //   error (_("Remote 'g' packet reply is too long (expected %ld bytes, got %d "
    //      "bytes): %s"),
    //    rsa->sizeof_g_packet, buf_len / 2,
    //    rs->buf.data ());
  if (buf_len > 2 * rsa->sizeof_g_packet) {
    rsa->sizeof_g_packet = buf_len;
    for (i = 0; i < gdbarch_num_regs (gdbarch); i++){
            if (rsa->regs[i].pnum == -1)
                continue;
            if (rsa->regs[i].offset >= rsa->sizeof_g_packet)
                rsa->regs[i].in_g_packet = 0;
            else
                rsa->regs[i].in_g_packet = 1;
        }
    }
```



compile gdb

```shell
./configure
make -j8
cp gdb/gdb /usr/bin/
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 0 --slave /usr/bin/g++ g++ /usr/bin/g++-9
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-4.8 100
```



### debug



#### qemu

```shell
# in linuxnet/lab3 directory
make rootfs
```



#### gdb

```shell
# start qemu in linuxnet/lab3 directory
qemu-system-x86_64 -kernel ../../arch/x86/boot/bzImage -initrd ../rootfs.img -append nokaslr -S -s

cd /root/linux-5.0.1
gdb ./vmlinux

# break
b tcp_v4_connect
b inet_csk_accept

c

```



#### vscode

Set breakpoionts in files then Run -> StartDebugging



### debug linuxnet

```shell
cd /root/linux-5.0.1
git clone https://github.com/mengning/linuxnet.git

cd linuxnet/lab2

vim Makefile
# cp test_reply.c ../../../menu/test.c
# cp syswrapper.h ../../../menu

make

cd ../../../menu
make rootfs
cd ../linux-5.0.1/linuxnet/lab3

# change to qemu-system-x86_64 -kernel ../../arch/x86/boot/bzImage -initrd ../rootfs.img
vim Makefile
```



input in qemu

```shell
replyhi
hello
```





#### debug menu

```shell

cd /root
git clone https://github.com/mengning/menu.git
cd menu

# qemu-system-x86_64 -kernel ../linux-5.0.1/arch/x86/boot/bzImage -initrd ../rootfs.img
vim Makefile


# install qemu
apt install qemu libc6-dev-i386

```



### debug poll

```shell

cd /root/linux-5.0.1

git clone https://github.com/wenfh2020/kernel_test.git

cd kernel_test/test_epoll_tcp_server

make


qemu-system-x86_64 -kernel ../../arch/x86/boot/bzImage -initrd ../rootfs.img -append nokaslr -S -s
# input 's' in qemu to start test server
s
# input 'c' in qemu to start test client
c
```



## Reference

1. [gdb 调试 Linux 内核网络源码](https://wenfh2020.com/2021/05/19/gdb-kernel-networking/)
2. [libxkbcommon.so.0: no version information available after installing VSCode update](https://stackoverflow.com/questions/66058683/libxkbcommon-so-0-no-version-information-available-after-installing-vscode-upda)