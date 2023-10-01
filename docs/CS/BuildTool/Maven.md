## Introduction

## Dependency Manager

依赖传递

依赖优先

- 短路径优先
- 先声明优先

可选依赖不会传递

Dependency Scope

- compiler(default)
- provider
- runtime
- test
- system

## use

### clean

pre-clean
clean
清理上一次构建生成的文件
post-clean

### default：构建项目

validate

compile
编译项目的主源码
src/mainj/java下的Java文件→主classpath目录
test-compile
编译项目的测试代码
test
使用单元测试框架运行测试
测试代码不会打包或部署
package
编译好的代码，打包成可发布的格式
jar、war
install
将包安装到本地仓库
deploy
最终的包复制到远程仓库

### site：建立项目站点

## Mirrors

add mirror into `<mirrors></mirrors>` of `~/.m2/settings.xml`

```xml
<mirror>
    <id>aliyunmaven</id>
    <mirrorOf>*</mirrorOf>
    <name>阿里云公共仓库</name>
    <url>https://maven.aliyun.com/repository/public</url>
</mirror>
```

other proxy repos into `<repositories></repositories>` of `~/.m2/settings.xml`:

```xml
<repository>
    <id>spring</id>
    <url>https://maven.aliyun.com/repository/spring</url>
    <releases>
        <enabled>true</enabled>
    </releases>
    <snapshots>
        <enabled>true</enabled>
    </snapshots>
</repository>
```


## Test

debug test

```shell
mvn test -Dmaven.surefire.debug
```

## Plugins

## Links

- [Build Tools](/docs/CS/BuildTool/BuildTools.md)
- [Gradle](/docs/CS/BuildTool/Gradle.md)

## References

1. [Calendar Versioning](https://calver.org/)
2. [Aliyun Maven Mirror](https://developer.aliyun.com/mirror/maven)
