## Introduction







入口函数是位于`cmd/kube-scheduler/scheduler.go`中的main()方法,调用的是app.NewSchedulerCommand()方法





kube-scheduler 目前包含两部分调度算法 predicates 和 priorities，首先执行 predicates 算法过滤部分 node 然后执行 priorities 算法为所有 node 打分，最后从所有 node 中选出分数最高的最为最佳的 node






## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
