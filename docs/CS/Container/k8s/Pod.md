

Pod出现CrashLoopBackOff状态，就想到大概率是Pod内服务自身的原因

使用kubectl describe命令查看

从Event日志可以看出，是calico的健康检查没通过导致的重启，出错原因也比较明显：net/http: request canceled while waiting for connection (Client.Timeout exceeded while awaiting headers)，这个错误的含义是建立连接超时[1]，并且手动在控制台执行健康检查命令，发现确实响应慢（正常环境是毫秒级别）

考虑到错误原因是建立连接超时，并且业务量比较大，先观察一下TCP连接的状态情况

对TCP的SYN_RECV