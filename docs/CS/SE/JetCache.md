## Introduction

JetCache 是一个由阿里巴巴开源的、面向 Java/Spring 生态的轻量级缓存抽象框架。它不替代 Redis 或本地缓存组件，而是站在业务应用层，提供一套统一、易用、生产级的缓存开发与管理方案。



```yml
# application.yml
jetcache:
  statIntervalMinutes: 15
  areaInCacheName: false
  local:
    default:
      type: caffeine
      keyConvertor: fastjson2
  remote:
    default:
      type: redis.lettuce
      keyConvertor: fastjson2
      valueEncoder: java
      valueDecoder: java
      uri: redis://127.0.0.1:6379/
```























## Links
- []