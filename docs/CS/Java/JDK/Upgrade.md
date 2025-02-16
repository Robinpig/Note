## Introduction

JDK升级
当前项目JDK版本
二方包JDK版本需要单独维护 使用maven-source-plugin 维护原有打包版本

spring boot 从 2.7 开始引入了新的自动装配方式 ： META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
在 2.7.x同时支持这种方式和原来的spring.factories方式，如果两个文件同时存在也不会重复装配， 3.x 开始废弃了spring.factories ，没有 META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports文件的 starter 都不会自动装配，也就是说我们使用的大部分 starter 可能都会失效


依赖修改
javax下的包迁移到jakarta下


本地编译运行

修改Docker文件
workdir设置为log目录 提高工作效率 增加常用命令的别名








## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)