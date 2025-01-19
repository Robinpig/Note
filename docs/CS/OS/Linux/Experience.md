## Overview

遇到的一些错误



Install

>  [Installation Guide](https://installati.one/)



<table>
  <thead>
    <tr>
      <th>报错</th>
      <th>解决方式</th>
      <th>原因</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>apt安装deb包时 _apt用户无法访问文件问题</td>
      <td>将deb文件移动到/tmp目录下进行安装</td>
      <td></td>
    </tr>
  </tbody>
</table>



Ubuntu24.04安装向日葵报错 缺少libgconf-2-4包

浏览器搜索Ubuntu官方软件库

> https://packages.ubuntu.com/search?keywords=libgconf-2-4



修改 `/etc/apt/sources.list.d/ubuntu.sources` 添加

```properties
Types: deb
URIs: http://th.archive.ubuntu.com/ubuntu/
Suites: jammy
Components: main universe
```



更新源

```shell
sudo apt-get update
sudo apt install libgconf-2-4
```









## 密码与权限



##### Reset Password

1. `shift` when starting to Advanced options for ubuntu
2. `e` at second recover mode 
3. Use `quiet splash rw init=/bin/bash` replace `ro recovery nomodeset *`
4. `passwd ["username"]` change password


## 命令相关

##### path修改出问题了

无法使用/usr/share/bin下的命令

用whereis查询vim

```shell
/usr/bin/whereis vim
```



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)

