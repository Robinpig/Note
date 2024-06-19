## Introduction

Maven, a Yiddish word meaning accumulator of knowledge, began as an attempt to simplify the build processes in the Jakarta Turbine project.
Maven's primary goal is to allow a developer to comprehend the complete state of a development effort in the shortest period of time.
In order to attain this goal, Maven deals with several areas of concern:

- Making the build process easy
- Providing a uniform build system
- Providing quality project information
- Encouraging better development practices


## Dependency Mechanism

### Transitive Dependencies

Maven avoids the need to discover and specify the libraries that your own dependencies require by including transitive dependencies automatically.
This feature is facilitated by reading the project files of your dependencies from the remote repositories specified.
There is no limit to the number of levels that dependencies can be gathered from.
A problem arises only if a cyclic dependency is discovered.

With transitive dependencies, the graph of included libraries can quickly grow quite large.
For this reason, there are additional features that limit which dependencies are included:

- **Dependency mediation** - this determines what version of an artifact will be chosen when multiple versions are encountered as dependencies. Maven picks the "*nearest definition*".
  That is, it uses the version of the closest dependency to your project in the tree of dependencies.
  **Note that if two dependency versions are at the same depth in the dependency tree, the first declaration wins.**
- **Dependency management** - this allows project authors to directly specify the versions of artifacts to be used when they are encountered in transitive dependencies or in dependencies where no version has been specified.
- **Dependency scope** - this allows you to only include dependencies appropriate for the current stage of the build. This is described in more detail below.
- **Excluded dependencies** - If project X depends on project Y, and project Y depends on project Z, the owner of project X can explicitly exclude project Z as a dependency, using the "exclusion" element.
- **Optional dependencies** - If project Y depends on project Z, the owner of project Y can mark project Z as an optional dependency, using the "optional" element.

Although transitive dependencies can implicitly include desired dependencies, it is a good practice to explicitly specify the dependencies your source code uses directly.
This best practice proves its value especially when the dependencies of your project change their dependencies.
Another reason to directly specify dependencies is that it provides better documentation for your project: one can learn more information by just reading the POM file in your project, or by executing mvn dependency:tree.

### Dependency Scope

Dependency scope is used to limit the transitivity of a dependency and to determine when a dependency is included in a classpath.

There are 6 scopes:

- **compile**
  This is the default scope, used if none is specified. Compile dependencies are available in all classpaths of a project.
  Furthermore, those dependencies are propagated to dependent projects.
- **provided**
  This is much like , but indicates you expect the JDK or a container to provide the dependency at runtime.
  For example, when building a web application for the Java Enterprise Edition, you would set the dependency on the Servlet API and related Java EE APIs to scope because the web container provides those classes.
  A dependency with this scope is added to the classpath used for compilation and test, but not the runtime classpath. It is not transitive.`compile``provided`
- **runtime**
  This scope indicates that the dependency is not required for compilation, but is for execution.
  Maven includes a dependency with this scope in the runtime and test classpaths, but not the compile classpath.
- **test**
  This scope indicates that the dependency is not required for normal use of the application, and is only available for the test compilation and execution phases.
  This scope is not transitive. Typically this scope is used for test libraries such as JUnit and Mockito.
  It is also used for non-test libraries such as Apache Commons IO if those libraries are used in unit tests (src/test/java) but not in the model code (src/main/java).
- **system**
  This scope is similar to except that you have to provide the JAR which contains it explicitly.
  The artifact is always available and is not looked up in a repository.`provided`
- **import**
  This scope is only supported on a dependency of type in the section.
  It indicates the dependency is to be replaced with the effective list of dependencies in the specified POM's section.
  Since they are replaced, dependencies with a scope of do not actually participate in limiting the transitivity of a dependency.`pom``<dependencyManagement>``<dependencyManagement>``import`

Each of the scopes (except for ) affects transitive dependencies in different ways, as is demonstrated in the table below.
If a dependency is set to the scope in the left column, a transitive dependency of that dependency with the scope across the top row results
in a dependency in the main project with the scope listed at the intersection.
If no scope is listed, it means the dependency is omitted.`import`


| -        | compile    | provided | runtime  | test |
| -------- | ---------- | -------- | -------- | ---- |
| compile  | compile(*) | -        | runtime  | -    |
| provided | provided   | -        | provided | -    |
| runtime  | runtime    | -        | runtime  | -    |
| test     | test       | -        | test     | -    |

> [!Note]
>
> It is intended that this should be runtime scope instead, so that all compile dependencies must be explicitly listed.
> However, if a library you depend on extends a class from another library, both must be available at compile time. For this reason,
> compile time dependencies remain as compile scope even when they are transitive.

## Lifecycle

## Clean Lifecycle


| Phase        | Description                                                   |
| ------------ | ------------------------------------------------------------- |
| `pre-clean`  | execute processes needed prior to the actual project cleaning |
| `clean`      | remove all files generated by the previous build              |
| `post-clean` | execute processes needed to finalize the project cleaning     |

## Default Lifecycle




| Phase                     | Description                                                                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `validate`                | validate the project is correct and all necessary information is available.                                                                             |
| `initialize`              | initialize build state, e.g. set properties or create directories.                                                                                      |
| `generate-sources`        | generate any source code for inclusion in compilation.                                                                                                  |
| `process-sources`         | process the source code, for example to filter any values.                                                                                              |
| `generate-resources`      | generate resources for inclusion in the package.                                                                                                        |
| `process-resources`       | copy and process the resources into the destination directory, ready for packaging.                                                                     |
| `compile`                 | compile the source code of the project.                                                                                                                 |
| `process-classes`         | post-process the generated files from compilation, for example to do bytecode enhancement on Java classes.                                              |
| `generate-test-sources`   | generate any test source code for inclusion in compilation.                                                                                             |
| `process-test-sources`    | process the test source code, for example to filter any values.                                                                                         |
| `generate-test-resources` | create resources for testing.                                                                                                                           |
| `process-test-resources`  | copy and process the resources into the test destination directory.                                                                                     |
| `test-compile`            | compile the test source code into the test destination directory                                                                                        |
| `process-test-classes`    | post-process the generated files from test compilation, for example to do bytecode enhancement on Java classes.                                         |
| `test`                    | run tests using a suitable unit testing framework. These tests should not require the code be packaged or deployed.                                     |
| `prepare-package`         | perform any operations necessary to prepare a package before the actual packaging. This often results in an unpacked, processed version of the package. |
| `package`                 | take the compiled code and package it in its distributable format, such as a JAR.                                                                       |
| `pre-integration-test`    | perform actions required before integration tests are executed. This may involve things such as setting up the required environment.                    |
| `integration-test`        | process and deploy the package if necessary into an environment where integration tests can be run.                                                     |
| `post-integration-test`   | perform actions required after integration tests have been executed. This may including cleaning up the environment.                                    |
| `verify`                  | run any checks to verify the package is valid and meets quality criteria.                                                                               |
| `install`                 | install the package into the local repository, for use as a dependency in other projects locally.                                                       |
| `deploy`                  | done in an integration or release environment, copies the final package to the remote repository for sharing with other developers and projects.        |

## Site Lifecycle


| Phase         | Description                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------- |
| `pre-site`    | execute processes needed prior to the actual project site generation                         |
| `site`        | generate the project's site documentation                                                    |
| `post-site`   | execute processes needed to finalize the site generation, and to prepare for site deployment |
| `site-deploy` | deploy the generated site documentation to the specified web server                          |

## use

### clean

pre-clean
clean
清理上一次构建生成的文件
post-clean

### default

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

## Tuning

### 依赖冲突

检查依赖
```
mvn -Dverbose dependency:tree
```

omitted for conflict with xx

依赖冲突会常导致发生NoClassDefFoundError、NoSuchMethodException、IllegalAccessError等错误

## Links

- [Build Tools](/docs/CS/BuildTool/BuildTools.md)
- [Gradle](/docs/CS/BuildTool/Gradle.md)

## References

1. [Calendar Versioning](https://calver.org/)
2. [Aliyun Maven Mirror](https://developer.aliyun.com/mirror/maven)
