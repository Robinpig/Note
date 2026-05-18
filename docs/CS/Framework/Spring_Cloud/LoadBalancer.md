## Introduction



Loadbalancer 提供了两种内置负载均衡策略
- RandomLoadBalancer：在服务列表中随机挑选一台服务器发起调用
- RoundRobinLoadBalancer：通过内部保存的一个 position 计数器，按照次序从上到下依次调用服务


Loadbalancer 提供了一个顶层的抽象接口 ReactiveLoadBalancer，你可以通过继承这个接口，来实现自定义的负载均衡策略



创建了一个叫 CanaryRule 的负载均衡规则类，它继承自 Loadbalancer 项目的标准接口 ReactorServiceInstanceLoadBalancer
CanaryRule 借助 Http Header 中的属性和 Nacos 服务节点的 metadata 完成测试流量的负载均衡。
在这个过程里，它需要准确识别哪些请求是测试流量，并且把测试流量导向到正确的目标服务。
CanaryRule 如何识别测试流量：如果 WebClient 发出一个请求，其 Header 的 key-value 列表中包含了特定的流量 Key：traffic-version，那么这个请求就被识别为一个测试请求，只能发送到特定的金丝雀服务器上


```java
// 可以将这个负载均衡策略单独拎出来，作为一个公共组件提供服务
@Slf4j
public class CanaryRule implements ReactorServiceInstanceLoadBalancer {
private ObjectProvider<ServiceInstanceListSupplier> serviceInstanceListSup
private String serviceId;
// 定义一个轮询策略的种子
final AtomicInteger position;
// ...省略构造器代码
// 这个服务是Loadbalancer的标准接口，也是负载均衡策略选择服务器的入口方法
@Override
public Mono<Response<ServiceInstance>> choose(Request request) {
ServiceInstanceListSupplier supplier = serviceInstanceListSupplierProv
.getIfAvailable(NoopServiceInstanceListSupplier::new);
return supplier.get(request).next()
.map(serviceInstances -> processInstanceResponse(supplier, ser
}
// 省略该方法内容，本方法主要完成了对getInstanceResponse的调用
private Response<ServiceInstance> processInstanceResponse(
}
// 根据金丝雀的规则返回目标节点
Response<ServiceInstance> getInstanceResponse(List<ServiceInstance> instan
// 注册中心无可用实例 返回空
if (CollectionUtils.isEmpty(instances)) {
log.warn("No instance available {}"
, serviceId);
return new EmptyResponse();
}
// 从WebClient请求的Header中获取特定的流量打标值
// 注意：以下代码仅适用于WebClient调用，使用RestTemplate或者Feign则需要额外适配
DefaultRequestContext context = (DefaultRequestContext) request.getCon
RequestData requestData = (RequestData) context.getClientRequest();
HttpHeaders headers = requestData.getHeaders();
// 获取到header中的流量标记
String trafficVersion = headers.getFirst(TRAFFIC
_
VERSION);
// 如果没有找到打标标记，或者标记为空，则使用RoundRobin规则进行查找
if (StringUtils.isBlank(trafficVersion)) {


// 过滤掉所有金丝雀测试的节点，即Nacos Metadaba中包含流量标记的节点
// 从剩余的节点中进行RoundRobin查找
List<ServiceInstance> noneCanaryInstances = instances.stream()
.filter(e -> !e.getMetadata().containsKey(TRAFFIC
_
.collect(Collectors.toList());
return getRoundRobinInstance(noneCanaryInstances);
VERSION)

}
// 如果WelClient的Header里包含流量标记
// 循环每个Nacos服务节点，过滤出metadata值相同的instance，再使用RoundRobin查找
List<ServiceInstance> canaryInstances = instances.stream().filter(e ->
String trafficVersionInMetadata = e.getMetadata().get(TRAFFIC
VERS
_
return StringUtils.equalsIgnoreCase(trafficVersionInMetadata, traf
}).collect(Collectors.toList());
return getRoundRobinInstance(canaryInstances);
}


// 使用RoundRobin机制获取节点
private Response<ServiceInstance> getRoundRobinInstance(List<ServiceInstan
// 如果没有可用节点，则返回空
if (instances.isEmpty()) {
log.warn("No servers available for service: " + serviceId);
return new EmptyResponse();
}
// 每一次计数器都自动+1，实现轮询的效果
int pos = Math.abs(this.position.incrementAndGet());
ServiceInstance instance = instances.get(pos % instances.size());
return new DefaultResponse(instance);
}
}
```




## Links

