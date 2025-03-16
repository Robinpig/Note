## Introduction





```shell
wget https://github.com/chenshuo/muduo/archive/refs/tags/v2.0.2.tar.gz
tar zxf v2.0.2.tar.gz
```



build.sh

```shell
#!/bin/sh

cd `dirname $0`
work_path=`pwd`
cd $work_path

BUILD_TYPE=debug ./build.sh install -j4

[ $? -ne 0 ] && echo "build failed" && exit 1
cd ../build/debug-install-cpp11/lib/
cp libmuduo_base.a libmuduo_net.a /usr/local/lib64
[ $? -ne 0 ] && echo "copy failed!" && exit 1
cd -
echo "done!"
```


build
```shell
cd muduo-2.0.2
chmod +x build.sh

build.sh
```






## Links

- [C++](/docs/CS/C++/C++.md)