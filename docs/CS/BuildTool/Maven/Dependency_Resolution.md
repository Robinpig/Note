## Introduction

Maven 的依赖机制本质上是一个**有向无环图上的版本选择问题**：项目声明直接依赖，传递依赖自动引入，冲突时按规则仲裁。规则本身不复杂，但**规则的默认行为往往与直觉相反**，是所有 `NoSuchMethodError` / `ClassNotFoundException` 的源头。

这一篇按"声明 → 传递 → 仲裁 → 剪枝 → 排查"的顺序把依赖机制讲透。

## Transitive Dependencies

Maven 会自动引入依赖的依赖，无需逐个声明。机制是读取每个依赖 jar 同目录下的 `.pom`，解析出它的 `<dependencies>`，递归展开。

```
项目
├── spring-web → spring-core, spring-beans
│   └── spring-jcl
└── jackson-databind → jackson-core, jackson-annotations
```

展开后项目实际拥有 7 个依赖，而非声明的 2 个。

递归没有层数上限，唯一终止条件是**检测到循环依赖**——但循环本身不是错误，只是会终止展开，不会有无限递归。

> [!Warning]
>
> 传递依赖是"方便"与"失控"的交界。依赖图会迅速膨胀，而**你无法从项目自己的 POM 看出最终 classpath 上有什么**。所以始终要显式声明你直接使用的依赖——既是文档，也是后续排查的基线。

## Dependency Mediation

当同一个制品出现在多条路径上、且版本不同时，Maven 只保留一个版本。

**默认规则：nearest definition（最近者优先）**——取依赖树中距离当前项目最近的那个版本。

```
项目
├── A 1.0 → commons-lang3 3.12    (深度 2)
└── B 1.0 → C 1.0 → commons-lang3 3.17   (深度 3)
```

结果：选 **3.12**（最近），不是 3.17，尽管 3.17 更新。

这与 Gradle 的"选最高版本"完全相反，也是两个工具迁移时最常踩的坑。

**同深度时的规则**：先声明者胜（first declaration wins）。若 A 与 B 在同一层引入不同版本，以 POM 中 `<dependencies>` 里靠前的那个为准。

> [!Note]
>
> "最近"而非"最新"的设计理由：路径最近的那个版本，是**该依赖的直接使用方明确选择并测试过的**。选最新等于用别人的兼容假设替换掉自己验证过的版本。
>
> 实践后果是：升级一个传递依赖的版本经常"升不动"——你改的是上层版本号，真正被仲裁掉的可能是另一条路径上的。要改就改**最近的那条路径**，或者用 `<dependencyManagement>` 强制。

## Dependency Scope

Scope 同时决定两件事：**是否传递**、**进入哪条 classpath**。

| scope | 编译 classpath | 测试 classpath | 运行 classpath | 是否传递 |
| :--- | :--- | :--- | :--- | :--- |
| `compile` | ✅ | ✅ | ✅ | ✅ |
| `provided` | ✅ | ✅ | ❌ | ❌ |
| `runtime` | ❌ | ✅ | ✅ | ✅ |
| `test` | ❌ | ✅ | ❌ | ❌ |
| `system` | ✅ | ✅ | ❌ | ❌ |
| `import` | 仅 `dependencyManagement` 内有效 | | | ❌ |

各 scope 的语义：

- **compile** —— 默认值。适用于所有 classpath，并向依赖方传播。
- **provided** —— 预期由 JDK 或容器提供（Servlet API、Spring Boot 的 `spring-boot-starter-tomcat`）。**不传递**：下游项目必须自己声明，否则运行期缺类。这是 `NoClassNotFoundException` 的常见来源。
- **runtime** —— 编译不需要、运行需要。最典型的是 JDBC 驱动。
- **test** —— 只在测试编译与执行时可见，不传递。JUnit、Mockito、Testcontainers 属于此类。
- **system** —— 类似 `provided`，但 **JAR 路径必须显式写在 POM 里**，且 Maven 3.x 已不再推荐（依赖从仓库解析失败时它能救急，但破坏了可重复构建）。Maven 4 起从仓库解析到的模型会**拒绝 system scope 依赖**。
- **import** —— 只能用于 `dependencyManagement` 中的 `pom` 类型依赖，作用是把被导入 POM 的 `dependencyManagement` 段落整体搬过来（BOM 的标准用法）。

### 传递矩阵

被依赖方的 scope 与传递依赖的 scope 共同决定最终 scope：

| 声明的 scope ↓ / 传递来的 scope → | compile | provided | runtime | test |
| :--- | :--- | :--- | :--- | :--- |
| compile | compile | — | runtime | — |
| provided | provided | — | provided | — |
| runtime | runtime | — | runtime | — |
| test | test | — | test | — |

`provided` 行与 `runtime` 行的规律：**provided 依赖的传递依赖一律降级为 provided**（因为容器提供的环境里不会凭空多出 runtime 依赖）。

## Dependency Management

`<dependencyManagement>` **只声明版本，不引入依赖**。它解决的是"版本统一"而非"引入"。

两种典型用法：

**用法一：多模块项目统一版本（最常见）**

```xml
<!-- 根 pom.xml -->
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-dependencies</artifactId>
      <version>3.5.0</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

子模块只需声明 `groupId:artifactId`，不写版本：

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
</dependencies>
```

**用法二：强制覆盖传递依赖的版本（仲裁的"硬手段"）**

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.18.2</version>
    </dependency>
  </dependencies>
</dependencyManagement>
```

这条不引入依赖，但会**改写整棵依赖树中该制品的最终版本**——无论它从哪条路径来、原本被仲裁成什么版本。

> [!TIP]
>
> `dependencyManagement` 只影响**传递依赖**的仲裁结果；如果一个依赖是**直接声明**的，且自己写了版本，那么 `dependencyManagement` 里的版本**不生效**。要覆盖直接依赖，必须改直接声明本身，或在直接声明里去掉 `<version>` 让它回落到 `dependencyManagement`。

### BOM

BOM（Bill of Materials）就是一个只含 `dependencyManagement` 的 `pom` 类型制品。用 `import` 引入后，被导入 POM 中**全部** `dependencyManagement` 条目被平铺进当前项目。

常见 BOM：Spring Boot（`spring-boot-dependencies`）、JUnit 5（`junit-bom`）、Jackson（`jackson-bom`）、Testcontainers（`testcontainers-bom`）。

BOM 的价值是**保证一组依赖的版本互相兼容**。逐个写版本号迟早会出现"Jackson 2.18 的 core + 2.15 的 databind"这种错配。

## Exclusions

排除是在**当前项目**上剪掉传递依赖树的某个分支：

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-web</artifactId>
  <exclusions>
    <exclusion>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-log4j12</artifactId>
    </exclusion>
  </exclusions>
</dependency>
```

注意排除的粒度：**排除的是"该路径上整个 groupId:artifactId 的子树"**。如果同一个制品还从别的路径进来，它依然会在 classpath 上。

排除的典型场景是**换掉传递引入的日志实现**（如 `slf4j-log4j12` → `logback-classic`）——但更干净的做法是声明正确的实现并排除全部旧绑定，而不是逐个排除。

## Optional Dependencies

`optional` 标记的是"**我依赖它，但它不该传染给我的下游**"。

```xml
<dependency>
  <groupId>com.example</groupId>
  <artifactId>demo-metrics-prometheus</artifactId>
  <version>1.0.0</version>
  <optional>true</optional>
</dependency>
```

项目 A 依赖 B，B 依赖 C 且 C 是 optional，则 **A 不会得到 C**。B 自己编译/运行仍可用 C。

典型用法：库的"集成适配层"——库本体不强依赖具体实现，只在引入该集成模块时把对应实现带上。

## Conflict Resolution in Practice

依赖冲突的实际表现不是报错，而是**运行时诡异错误**：

- `NoSuchMethodError` —— A 方法在旧版存在、新版删除，运行期加载了旧版；
- `NoClassDefFoundError` —— 传递依赖缺失（如 `provided` 未传递）；
- `ClassNotFoundException` —— 同上，但发生在类加载阶段；
- `IllegalAccessError` —— 版本跨越了可见性/签名变化。

### Diagnosis

```shell
# 完整依赖树，标注被省略的冲突节点
mvn dependency:tree -Dverbose

# 只看某个制品的完整路径
mvn dependency:tree -Dincludes=com.fasterxml.jackson.core:jackson-databind

# 定位 classpath 冲突（输出每个依赖的 classpath 顺序）
mvn dependency:build-classpath -Dmdep.outputFile=cp.txt

# 看最终生效的版本
mvn dependency:list -DincludeGroupIds=org.slf4j

# 分析依赖（引入/未使用的 declared/transitive）
mvn dependency:analyze
```

`dependency:tree` 的输出里，`omitted for conflict with X` 表示该节点被仲裁掉了。**看到大量 omitted 是正常的**，需要看的是最终留下的是哪个。

`dependency:analyze` 会报"Used undeclared dependencies"（用了没声明的）和"Unused declared dependencies"（声明了没用）。前者是必须修的（可能触发仲裁意外），后者是警告。

### Fixes

按优先级：

1. **在根 POM 的 `dependencyManagement` 里锁定版本** —— 最可控，影响整棵树；
2. **升级引入方** —— 让上游自己解决兼容；
3. **`exclusions` 剪枝** —— 只在确实不需要时用；
4. **`import` 引入兼容的 BOM** —— 当一组依赖需要整体对齐。

## Reproducibility

依赖版本必须可重复解析。生产构建中应禁用以下写法：

| 写法 | 问题 |
| :--- | :--- |
| `LATEST` / `RELEASE` | 指向动态最新，每次解析结果可能不同 |
| 版本区间 `[1.0,2.0)` | 解析到当时满足条件的最高版本 |
| `SNAPSHOT` | 内容可变，同一坐标两次内容不同 |

Maven 3.10.0 起 **Reproducible Builds 默认启用**：Super POM 为 `project.build.outputTimestamp` 提供了默认值，使产物 jar 内的时间戳稳定。

配合 Maven Enforcer 可以把规则强制化：

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-enforcer-plugin</artifactId>
  <version>3.6.3</version>
  <executions>
    <execution>
      <id>ban-dynamic-versions</id>
      <goals><goal>enforce</goal></goals>
      <configuration>
        <rules>
          <requireReleaseDeps>
            <message>生产构建禁止 SNAPSHOT / LATEST / RELEASE</message>
          </requireReleaseDeps>
          <requireMavenVersion>
            <version>[3.9,)</version>
          </requireMavenVersion>
        </rules>
      </configuration>
    </execution>
  </executions>
</plugin>
```

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)
- [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)

## References

1. [Maven — Introduction to Dependency Mechanism](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html)
2. [Maven — Introduction to the Dependency Mechanism (Scopes)](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html#dependency-scopes)
3. [Maven — Dependency Management](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html#dependency-management)
4. [maven-dependency-plugin](https://maven.apache.org/plugins/maven-dependency-plugin/)
5. [maven-enforcer-plugin](https://maven.apache.org/enforcer/maven-enforcer-plugin/)
