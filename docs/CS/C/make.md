## Introduction




```shell
apt-get install make

# verify
make -v
```

## Makefile

在Linux环境下，当我们输入make命令时，它就在当前目录查找一个名为Makefile的文件，然后，根据这个文件定义的规则，自动化地执行任意命令，包括编译命令

Makefile这个单词，顾名思义，就是指如何生成文件

Makefile由若干条规则（Rule）构成，每一条规则指出一个目标文件（Target），若干依赖文件（prerequisites），以及生成目标文件的命令


To run these examples, you'll need a terminal and "make" installed. 
For each example, put the contents in a file called Makefile, and in that directory run the command make. Let's start with the simplest of Makefiles:
```makefile
hello:
    echo "Hello, World"
```

Note: Makefiles must be indented using TABs and not spaces or make will fail.

Here is the output of running the above example:

```shell
$ make
echo "Hello, World"
Hello, World
```



## Links


## References

1. [GNU make](https://www.gnu.org/software/make/manual/make.html)