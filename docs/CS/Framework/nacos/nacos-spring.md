## Introduction



Nacos 无缝支持 Spring 全栈  Nacos-spring-boot 项目和 Nacos-spring 项目是为 Spring 用户提供的项目， 本质是提升 Java用户的编程体验和效率  

@NacosValue 这个注解是通过 NacosValueAnnotationBeanPostProcessor 类来处理的。  

每次 Nacos-client 端收到相应的 dataId 变更之后， 都会触发 NacosConfigReceivedEvent  

计算出新的 evaluatedValue 之后， 通过 setFiled 进行更新  

Nacos 的 @NacosPropertySource 注解可以从 Nacos 服务端拉取相应的配置。 @NacosPropertySource 注解主要是由 NacosPropertySourcePostProcessor 类来处理， 该类实现了BeanFactoryPostProcessor， 作为⼀个钩子类， 会在所有 spring bean definition生成后、 实例化之前调用。  

他的使命是进行注解的扫描， 扫描由 spring 所有的 bean， 查看其类上是否有 @NacosPropertySource 注解， 如果有的话，则生成  

在 receiveConfigInfo 的回调逻辑中， 当有配置变更的时候， 会重新生成 NacosPropertySource， 并且替换掉 environment 中过时的 NacosPropertySource， 完成这个步骤之后， 就可以通过 environment.getProperty() 动态的获取到配置值了  


## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)