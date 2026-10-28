## Introduction

多模块（multi-module / multimodule）是 Maven 最有价值也最容易失控的能力。它的价值在于**一次 reactor 构建内完成"改代码 → 编译 → 测试 → 打包 → 装入本地仓库"的闭环**，让下游模块立刻能用上上游模块的**最新改动**——这是单模块项目链式构建很难做到的。

它的失控点在于：aggregator（聚合）与 parent（继承）被混为一谈、reactor 排序规则不透明、`-am` / `-pl` 参数语义记不清。这一篇把这两件事讲清。

## Two Independent Roles

一个 `pom` packaging 的项目可以同时扮演两个**互相独立**的角色：

| 角色 | 做什么 | 配置在哪 |
| :--- | :--- | :--- |
| **Aggregator** | 把多个模块收进一次构建 | `<modules>` |
| **Parent** | 提供属性、依赖管理、插件管理、构建配置 | `<parent>` |

**两者不必在同一个项目上**。三种常见布局：

```
方案 A：一个项目身兼两职（最常见）
root/            ← aggregator + parent
├── module-a/
├── module-b/

方案 B：分离（聚合与继承解耦）
build-root/     ← aggregator only
├── parent/     ← parent only
│   ├── module-a/
│   └── module-b/

方案 C：纯 parent（不聚合任何模块）
library-parent/ ← 只提供配置，被外部项目引用
```

方案 A 是绝大多数项目的做法。

> [!Note]
>
> `<modules>` 的路径是**相对于 aggregator 的 POM 文件所在目录**，不是相对于执行命令的目录。所以在根目录执行 `mvn -f path/to/pom.xml` 时，`modules` 仍按 POM 位置解析。

## Declaring Modules

```xml
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo-parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>

  <modules>
    <module>common</module>
    <module>service</module>
    <module>app</module>
  </modules>
</project>
```

> [!Tip]
>
> **Maven 4 支持自动发现子模块**：父项目使用 `pom` packaging、既无显式 `<subprojects>`（或已弃用的 `<modules>`）也无 `<modules>`，且直接子目录含 `pom.xml` 时，Maven 会自动把它们纳入构建。Maven 3 下没有这个能力，仍须显式声明。

## Parent Inheritance

子模块通过 `<parent>` 继承：

```xml
<parent>
  <groupId>com.example</groupId>
  <artifactId>demo-parent</artifactId>
  <version>1.0.0</version>
  <!-- 可选：默认 ../pom.xml -->
  <relativePath>../pom.xml</relativePath>
</parent>
```

继承来的东西：

- **properties** —— 变量；
- **dependencyManagement** —— 版本管理；
- **dependencies** —— **依赖本身也会被继承**（容易踩坑）；
- **build/pluginManagement** —— 插件配置与版本；
- **build/resources**、**build/testResources** —— 目录约定；
- **repositories / pluginRepositories** —— 仓库声明；
- **distributionManagement** —— 发布目标。

### The relativePath Trap

`<relativePath>` 默认是 `../pom.xml`。Maven 先在本地文件系统上按它找 parent，**找不到才去仓库解析**。

两种典型故障：

1. **parent 在仓库里但本地路径不对** —— Maven 会去仓库下载 parent POM。结果是：你以为改的是本地 parent，實際生效的是仓库里那份旧版本。排查方法：`mvn help:effective-pom` 看继承结果；
2. **`<relativePath/>` 显式置空** —— 强制只从仓库解析，不看本地路径。用于"parent 只作为发布出去的 BOM"。

> [!Note]
>
> Maven 3.10.0 起，**parent 的 `relativePath` 会做校验**（此前任何 Maven 3.x 版本都不校验）。指向一个不存在或不是有效 POM 的路径会直接让构建失败。

### 继承 dependencies 的陷阱

parent 的 `<dependencies>` 会被**所有**子模块继承，包括 test scope 的。这意味着父 POM 里为了某个子模块加的测试依赖，会出现在所有子模块的 classpath 上。

规范做法：父 POM 只放 `dependencyManagement`（声明版本），让子模块按需在 `<dependencies>` 中引入。

## The Reactor

Maven 一次构建涉及的所有项目构成 **reactor**（反应堆）。核心是**构建顺序**——它由两套信息共同决定：

**规则 1：模块依赖关系。** 若 A 依赖 B，B 必须先构建。依赖关系来自 reactor 内的 `<dependency>`（包括 test scope）。

**规则 2：声明顺序。** 无依赖关系的模块，按在 `<modules>` 中的**声明顺序**构建。

综合结果就是 **topological sort（拓扑排序）**。举例：

```xml
<modules>
  <module>common</module>     <!-- 无内部依赖 -->
  <module>service</module>    <!-- 依赖 common -->
  <module>app</module>        <!-- 依赖 common、service -->
</modules>
```

构建顺序：`common → service → app`。

若声明顺序反了（`app` 在 `service` 前），Maven **仍会**正确排序为 `common → service → app`——依赖关系优先级高于声明顺序。声明顺序只在**彼此无依赖**的模块之间起作用。

```shell
mvn clean install        # 查看 Reactor Build Order 输出
```

### Reactor Resolution

reactor 内的依赖如何解析？规则是：**如果依赖的模块在本次构建的 reactor 里，就用 reactor 里那个模块当前构建出的产物**（`target/classes` 或刚打好的 jar），**不去仓库找**。

这正是多模块的价值所在——改完 `common` 立刻 `mvn install`，`service` 用的就是新代码，不需要先 `deploy` 到 Nexus。

> [!Warning]
>
> 但 reactor 解析**只对"同一次构建内"的模块生效**。如果只构建单个模块（`mvn -pl service`）而 `common` 不在 reactor 里，Maven 就会去仓库找 `common`——拿到的是**旧版本**。这是"我明明改了 common，为什么 service 里还是旧行为"的头号原因。
>
> 解决办法是 `-am`（also-make），见下文。

## Selecting Modules

`-pl` / `--projects` 和 `-am` / `-also-make` 是多模块构建的标配组合。

```shell
# 只构建 service（依赖的 common 从仓库取旧版本）
mvn -pl service clean install

# 构建 service 及其 reactor 内依赖的模块
mvn -pl service -am clean install

# 构建 service 及其依赖它的下游模块
mvn -pl service -amd clean install

# 排除某些模块
mvn -pl '!legacy-module' clean install

# 按目录路径选择
mvn -pl docs/CS/Framework -am clean package
```

| 参数 | 含义 |
| :--- | :--- |
| `-pl` | 选择要构建的项目（多个用逗号分隔，支持 `!` 排除） |
| `-am` | 同时构建**所选项目的依赖**（also make） |
| `-amd` | 同时构建**依赖所选项目的项目**（also make dependents） |
| `-rf` | 从 reactor 中的某个项目开始（resume from） |
| `-fae` | fail at end：失败后继续构建不依赖它的模块 |
| `-fn` | fail never：全部继续 |

`-am` 解决的是"上游改了，下游要用新版本"；`-amd` 解决的是"上游接口变了，下游要一起验证"。

> [!Tip]
>
> **改了公共模块后验证下游**，用 `-amd` 而不是全量构建——省时间且能精准暴露破坏性变更。

## CI-Friendly Versions

多模块 + CI 的经典矛盾：版本号写在 POM 里，每次发布都要改一堆文件。Maven 的解法是 **CI-friendly 版本**（`${revision}` / `${changelist}` / `${sha1}`）。

```xml
<version>${revision}</version>
```

```xml
<properties>
  <revision>1.0.0-SNAPSHOT</revision>
  <changelist>-SNAPSHOT</changelist>
</properties>
```

命令行传入实际版本：

```shell
mvn clean install -Drevision=1.2.0 -Dchangelist=
```

> [!Note]
>
> **`${revision}` 只能用在 `<version>` 和 `<parent><version>` 上**——这是 Maven 3.5 引入 CI-friendly 时的刻意限制（否则无法在解析前确定版本）。其它地方（依赖版本、插件版本）用 `${revision}` 会报 "not a valid version"。
>
> **Maven 4 把 CI-friendly 变量做成了完整内置支持**，不再需要 flatten-maven-plugin 来把变量"压平"到发布的 POM 里——见 [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)。

配套插件：

- **flatten-maven-plugin** —— Maven 3 下把 `${revision}` 替换成实际值后生成发布的 POM（Maven 4 内置了等价能力）；
- **build-helper-maven-plugin** 的 `parse-version` goal —— 从 POM 里读回版本。

## Parallel Builds

Maven 3 支持并行构建：

```shell
mvn -T 4C clean package      # 4 × CPU 核数 个线程
mvn -T 1 clean package       # 单线程
mvn -T 2C clean package      # 2 × 核数
```

**并行的前提是模块间无依赖耦合**——有依赖关系的模块仍严格按拓扑序，只是可以并行跑那些互不依赖的。

风险点：

- **插件线程不安全** —— 写插件时若把状态放在字段里，并行下会互相污染；
- **输出交错** —— 老插件的日志会混在一起；
- **共享静态资源** —— 如同目录写同一份文件。

Maven 3.10.0 修复了 `ProjectIndex` 在并行构建下的线程安全问题。

## Resuming Failed Builds

Maven 4 新增 `--resume` / `-r`：从上次失败的子项目继续，而不是从头重建。

Maven 3 的等价手法是 `-rf`（`--resume-from`），但它需要手动指定模块名：

```shell
mvn clean install -rf :service
```

`-rf` 在 Maven 3 里就可用，但需要人知道从哪继续；Maven 4 的 `--resume` 会自动记录失败点。

## Best Practices

1. **父 POM 只放 `dependencyManagement` + `pluginManagement`**，不放具体 `dependencies`；
2. **所有插件版本显式锁定**（父 POM 的 `pluginManagement` 里统一锁）；
3. **聚合项目与 parent 分离**（当两者职责开始发散时）；
4. **改了公共模块，用 `-am` 验证下游**；
5. **CI 上用 `${revision}` + flatten**，不要手改版本号；
6. **不要在 reactor 里放业务无关的模块**——大 reactor 会拖慢每次构建。

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)

## References

1. [Maven — Introduction to Multi-Module Projects](https://maven.apache.org/guides/mini/guide-multimodule.html)
2. [Maven — Guide to Multi-Module Builds](https://maven.apache.org/guides/mini/guide-multimodule.html)
3. [Maven — Reactor Guide](https://maven.apache.org/guides/mini/guide-multimodule.html#advanced-multi-module-approaches)
4. [Maven — CI Friendly Versions](https://maven.apache.org/guides/mini/guide-ci-friendly.html)
5. [Maven — Running Maven in Parallel](https://maven.apache.org/guides/mini/guide-multimodule.html#running-maven-in-parallel)
