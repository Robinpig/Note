## Introduction



like [dtruss in Mac](/docs/CS/OS/mac/Tools/dtruss.md)


```shell
sudo apt-get install strace
```

strace提供了多种参数来定制跟踪的行为：

> -c：统计每一系统调用的执行时间、次数和出错次数。
> -T：显示每个系统调用所耗费的时间。
> -e trace=set：只跟踪指定的系统调用集，如-e trace=open,close。
> -f：跟踪由fork()产生的子进程。
> -o <file>：将输出重定向到文件。
> -p <pid>：跟踪指定的进程ID。

注意事项与提示

- 使用strace时可能会对系统性能产生一定影响，特别是在生产环境中。
  在生产环境的高流量Apache或Nginx服务器中，要诊断一个性能问题，使用strace来跟踪一个长时间运行的进程。由于strace需要捕获所有的系统调用和信号，这个过程可能会占用大量的CPU资源，从而影响到服务器的性能。在这种情况下，可能会发现服务器的响应时间变慢，处理请求的速度下降。
- 某些程序可能包含检测strace的机制，可能会改变行为或退出。
- 使用-o参数将输出重定向到文件是一个好的习惯，这样可以避免输出过多导致屏幕滚动过快。

## Links



## References
1. [strace(1) — Linux manual page](http://man7.org/linux/man-pages/man1/strace.1.html)