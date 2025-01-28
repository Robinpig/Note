## Introduction







创建资源对象的流程可分为：实例化Factory接口、通过Builder和Visitor将资源对象描述文件（deployment.yaml）文本格式转换成资源对象。将资源对象以HTTP请求的方式发送给kube-apiserver，并得到响应结果。最终根据Visitor匿名函数集的errors判断是否成功创建了资源对象





## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)

