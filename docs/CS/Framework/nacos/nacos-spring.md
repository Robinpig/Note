# Nacos Spring Integration

## Introduction

`nacos-spring` 是 Nacos 官方提供的**纯 Spring 框架接入项目**（`com.alibaba.nacos:nacos-spring-context`），用一组 `@Nacos*` 注解把 Spring 的属性注入与 Nacos 配置中心打通，核心增量是**自动刷新**。

> 版本基线：Nacos server 锚定 3.2.4（commit 2c587c0）。`nacos-spring-context` / `nacos-config-spring-boot-starter` 属独立仓库，不在 Nacos server 源码树内；本篇机制以官方文档为准，未对处理类做源码级核验。

反直觉点：

- **它和 Spring Cloud Alibaba 是两个不同项目**：`nacos-spring` 用 `@NacosValue` / `@NacosPropertySource`，SCA 用 Spring 原生 `@Value` / `@ConfigurationProperties` + `@RefreshScope` + `spring.config.import`。
- 注解里的 `autoRefreshed=true` 才是刷新的开关；只写 `@NacosValue("${key}")` 不会自动更新。
- **SCA 2025.1.x 已移除 bootstrap.yml**，但那不影响 `nacos-spring` 的用法——别把两套接入的配置方式混着抄。

## Annotation Mapping

官方文档给出的对应关系（`nacos-spring-context` 对 Spring 原生注解的增强）：

| Spring | Nacos Spring | 增强点 |
| :-- | :-- | :-- |
| `@Value` | `@NacosValue` | 自动刷新 |
| `@ConfigurationProperties` | `@NacosConfigurationProperties` | 自动刷新 + `@NacosProperty` / `@NacosIgnore` |
| `@PropertySource` | `@NacosPropertySource` | 自动刷新 + 优先级控制 |
| `@PropertySources` | `@NacosPropertySources` | 多配置源 |

启用方式与最小配置：

```java
@Configuration
@EnableNacosConfig(globalProperties = @NacosProperties(serverAddr = "127.0.0.1:8848"))
@NacosPropertySource(dataId = "example", autoRefreshed = true)
public class NacosConfiguration {
}

@Controller
public class ConfigController {
    @NacosValue(value = "${useLocalCache:false}", autoRefreshed = true)
    private boolean useLocalCache;
}
```

服务发现侧对应 `@EnableNacosDiscovery` 与 `@NacosInjected`（注入 `NamingService`）。

## How Refresh Works

两个处理类分别负责「注入值刷新」与「配置源装载」：

- `@NacosValue` 由 `NacosValueAnnotationBeanPostProcessor` 处理。客户端收到 dataId 变更后会触发 **`NacosConfigReceivedEvent`**（官方事件表明确它发生在 `Listener.receiveConfigInfo()` 之后），处理器据此重算 `evaluatedValue`，再通过反射 `setField` 更新字段。
- `@NacosPropertySource` 由 `NacosPropertySourcePostProcessor` 处理，它实现 `BeanFactoryPostProcessor`——作为钩子在**所有 bean definition 生成后、实例化之前**扫描类上的注解并生成配置源。`receiveConfigInfo` 回调里会重新生成 `NacosPropertySource`、替换 `Environment` 中过时的那个，之后 `environment.getProperty()` 就能拿到新值。

> [!NOTE]
> 上述两个处理类名来自 `nacos-spring-project`（独立仓库），本次未能在 Nacos 3.2.4 server 源码树内核验，因此只作为机制说明；可核验的事件名与注解语义取自 Nacos 官方 Spring 集成文档。

## Events

`nacos-spring` 的事件都继承 Spring `ApplicationEvent`，由标准 Spring Event / Listener 机制驱动：

| 事件 | 触发时机 |
| :-- | :-- |
| `NacosConfigReceivedEvent` | `Listener.receiveConfigInfo()` 之后 |
| `NacosConfigPublishedEvent` | `ConfigService.publishConfig()` 之后 |
| `NacosConfigRemovedEvent` | `removeConfig()` 之后 |
| `NacosConfigTimeoutEvent` | `getConfig()` 超时 |
| `NacosConfigListenerRegisteredEvent` | `addListener()` / `removeListener()` 之后 |

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Client SDK](/docs/CS/Framework/nacos/client.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## References

- <https://nacos.io/docs/latest/ecology/use-nacos-with-spring/>
- <https://nacos.io/docs/latest/ecology/use-nacos-with-spring-boot3/>
