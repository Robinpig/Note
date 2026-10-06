## Introduction

`Start.md` 讲的是进程侧的事：`Bootstrap` 如何加载 `Catalina`、`Server → Service → Engine → Host` 这棵对象树如何被 `Digester` 从 `server.xml` 里读出来并逐层 `start()`。那棵树起来之后其实是空的——它能接受连接，但任何 URI 都只会命中一个 `404`。

本篇讲另一件事：**一个 war 从被扔进 `webapps/` 到能正确处理请求，中间被哪些代码经手**。这条链由四个组件接力完成，各自职责边界很清楚：

| 阶段   | 组件                                       | 回答的问题                             |
| :--- | :--------------------------------------- | :-------------------------------- |
| 发现   | `startup.HostConfig`                     | appBase / configBase 里多了什么，要不要部署   |
| 展开   | `startup.ExpandWar`                       | war 要不要解、解到哪、什么时候必须重解             |
| 装配   | `startup.ContextConfig`                   | 这个应用有哪些 servlet / filter / listener |
| 启动   | `core.StandardContext#startInternal()`   | 按什么顺序实例化，失败怎么表现                   |

链路之外还有一个入口 `startup.Tomcat`：它把上面这套东西包装成可编程 API，是「内嵌 Tomcat」的唯一正道。Spring Boot、Quarkus、Gradle 的 `tomcat-run` 插件走的都是这条路，而不是去解析 `server.xml`。

本文全部源码路径相对 `/tmp/src/tree/tomcat-catalina-11.0.26/`，即 `org/apache/catalina/...` 的简写；行号为 11.0.26 实测。

## Deployment chain overview

把一次「war 落盘」拉直看，顺序是固定的：

1. `HostConfig.check()` 在 Host 的后台处理里被调用，发现 appBase 下多了一个 `foo.war`。
2. `HostConfig.deployWAR()` 展开 war（或不展开），确定 `docBase`，用 `ContextName` 把文件名换算成 context path 与版本。
3. `Context` 被 `addChild()` 挂进 `Host`，触发 `StandardContext` 的生命周期。
4. `ContextConfig` 作为 `LifecycleListener` 接到 `CONFIGURE_START_EVENT`，把全局 web.xml、`tomcat-web.xml`、应用 web.xml、`web-fragment.xml`、注解、SCI 合并成一份 `WebXml` 并施加到 `Context` 上。
5. `StandardContext.startInternal()` 创建 `WebappLoader`（见 [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)）、实例化 filter 与 `load-on-startup` servlet，最后把 context 标为 available。
6. 请求路径上，`Mapper` 早已在第 4 步结束时拿到 URI → Context → Wrapper 的映射，此后请求才不再 404。

值得强调的是第 3、4 步的耦合方式：**部署的"配置"不是被调用出来的，而是靠生命周期事件倒过来的**。`ContextConfig` 没有任何 public 入口，它只实现 `LifecycleListener`（`startup/ContextConfig.java:288`），靠 `case Lifecycle.CONFIGURE_START_EVENT -> configureStart();`（`:300`）被 `StandardContext` 的 `start()` 流程驱动。理解了这点，就能理解为什么「程序化创建的 Context」必须显式补一个 listener 才能正常启动。

## server.xml and directory layout

部署链的全部输入都来自 `Host` 上的几个属性，它们决定了后面所有判断：

| 属性                  | 默认      | 作用与后果                                                                  |
| :------------------ | :------ | :---------------------------------------------------------------------- |
| `appBase`           | `webapps` | war 与展开目录的落地点，`HostConfig` 每轮 `list()` 它                                 |
| `configBase`        | `conf/Catalina/localhost` | 外部 `context.xml` 描述符所在地，部署优先级最高                                          |
| `deployOnStartup`   | `true`  | 进程启动时扫不扫 appBase，`core/StandardHost.java:127` 是默认值源头                       |
| `autoDeploy`        | `true`  | 运行中轮询扫描的总开关，关掉之后热部署彻底失效                                                  |
| `deployIgnore`      | 空       | 正则，命中的路径被 `filterAppPaths()` 直接剔除（`:421`）                               |
| `unpackWARs`        | `true`  | war 是否展开成目录；只读介质或镜像化部署常置 `false`                                         |
| `copyXML`           | `false` | 是否把 war 内 / configBase 的 `context.xml` 复制进 `META-INF/context.xml`        |
| `xmlValidation` / `xmlNamespaceAware` | `false` | 传给 `WebXmlParser` 的解析开关（`startup/ContextConfig.java:1311` 附近），旧资料常写反 |
| `undeployOldVersions` | 视版本     | 并行部署下回收无会话的旧版本，见 `checkUndeploy()`                                        |

目录约定里最容易踩的一点：**`WEB-INF/classes` 与 `WEB-INF/lib/*.jar` 是两条不同的扫描路径，但同一次合并里都会被扫**。`WebappServiceLoader` 明确把 `/WEB-INF/classes/` 与 `/WEB-INF/lib/` 写成两个常量，而注解扫描对二者的处理不同（前者永远扫，后者受 `metadata-complete` 与 absolute ordering 约束）。

`Digester` 在这里的角色只有一件事：把 `context.xml` / `server.xml` 里的 `<Context>` 元素变成 `StandardContext` 的属性。`ContextConfig` 通过 `context.getConfigFile()` 拿到描述符 URL 再交给 digester（`startup/ContextConfig.java:724`、`:749`）。它不负责合并 web.xml，也不负责启动顺序——细节回到 [Start](/docs/CS/Framework/Tomcat/Start.md)。

## HostConfig deployment loop

### Fixed order of deployApps

`deployApps()` 是全链的入口，代码极短但顺序不可换（`startup/HostConfig.java:401`）：

```java
    protected void deployApps() {
        // Migrate legacy Java EE apps from legacyAppBase
        migrateLegacyApps();
        File appBase = host.getAppBaseFile();
        File configBase = host.getConfigBaseFile();
        String[] filteredAppPaths = filterAppPaths(appBase.list());
        // Deploy XML descriptors from configBase
        deployDescriptors(configBase, configBase.list());
        // Deploy WARs
        deployWARs(appBase, filteredAppPaths);
        // Deploy expanded folders
        deployDirectories(appBase, filteredAppPaths);
    }
```

三个结论直接从这段代码来：

- **描述符优先于 war，war 优先于目录**。`configBase` 下的 `foo.xml` 会先建立 `Context`，随后 `deployWARs` 发现同名 war 时不会重复部署，而是把它登记成前者的 redeploy 资源。
- `migrateLegacyApps()`（`:402`）是 11 里为老 `${catalina.base}/legacyapps` 保留的搬迁钩子，正常运行时是空转；旧文档里把它描述成"部署兼容层"是不准确的。
- 同一轮里目录形态永远最后处理，所以 `foo.war` 与 `foo/` 同时存在时，**war 是真相，目录只是它的展开产物**。`deployDirectory()` 反过来会把 `foo.war` 登记为 redeploy 触发器且时间戳写死为 `0`（`:1101`），语义是"这个文件一旦出现就必须重部署"。

`Long.valueOf(0)` 这个哨兵值在文件里出现多次（`:671`、`:1101`），配合 `checkUndeploy()` 里用 `-1` 强制清空全部 redeploy 资源的"trick"，构成 `DeployedApplication` 的两套时间戳语义：**登记值 = 上次已知的 mtime，`0` = 出现即触发，`-1` = 撤销登记**。读这个类时如果不记住这三个值，`checkResources()` 看起来就像乱码。

### check and servicedSet mutual exclusion

`check()` 自身不起线程、也不做周期计数，它只负责"被调用时把该做的事做一遍"（`startup/HostConfig.java:1640`）：

```java
    protected void check() {

        if (host.getAutoDeploy()) {
            // Check for resources modification to trigger redeployment
            DeployedApplication[] apps = deployed.values().toArray(new DeployedApplication[0]);
            for (DeployedApplication app : apps) {
                if (tryAddServiced(app.name)) {
                    try {
                        checkResources(app, false);
                    } finally {
                        removeServiced(app.name);
                    }
                }
            }

            // Check for old versions of applications that can now be undeployed
            if (host.getUndeployOldVersions()) {
                checkUndeploy();
            }

            // Hotdeploy applications
            deployApps();
        }
    }
```

注意 `tryAddServiced()` 的返回值直接决定要不要处理这个应用——`servicedSet`（`:141`）是一个按 context name 的互斥集，配合 `addServiced()` 返回 `false` 表示"已经有人在处理"（`:300`、`:310`）。这个设计的目的写在字段注释里：**部署/重部署/卸载三类动作不能对同一个应用并发发生**。所有 `deployXxx()` 的 javadoc 都额外强调一句 "It is expected that the caller has successfully added the app to servicedSet before calling this method"（`:453`、`:540`、`:778`、`:1019`），也就是说这几个 protected 方法**不是线程安全的公开 API**，只能由 `check()` / `check(String)` 驱动。

`check(String name)`（`:1675`）是给 Manager APP（上传 war 后立即部署）用的同步版本：`synchronized (host)` + `host.getState().isAvailable()` 前置检查 + `checkResources(app, true)`。参数 `skipFileModificationResolutionCheck = true` 是它和后台轮询唯一的区别——上传完立刻检查时，文件系统 mtime 精度可能不足以区分"新 war"和"刚写的旧 war"，同步路径选择跳过那层保守判定。

### WAR expansion and re-expand checks

展开决策不在 `HostConfig` 里，而在 `startup/ExpandWar.expand()`（`:73`）。它用 war 自身的 mtime 和一个同名 tracker 文件比对（`:95`-`:110`）：

```java
        // Check to see of the WAR has been expanded previously
        if (docBase.exists()) {
            // A WAR was expanded. Tomcat will have set the last modified
            // time of warTracker file to the last modified time of the WAR so
            // changes to the WAR while Tomcat is stopped can be detected
            if (!warTracker.exists() || warTracker.lastModified() == warLastModified) {
                // No (detectable) changes to the WAR
                // success = true;
                return docBase.getAbsolutePath();
            }

            // WAR must have been modified. Remove expanded directory.
            log.info(sm.getString("expandWar.deleteOld", docBase));
```

这段回答了一个常见的疑问：**为什么 Tomcat 停机期间替换 war，重启后仍然会重新展开**。答案是 `warTracker`（`pathname + Constants.WarTracker`，`:86`）的 mtime 被刻意设成 war 的 mtime，所以"比较两个文件的时间"就等价于"上次展开时 war 是哪个版本"。旧的 `file##war^path` 形式的 war URL 与 `URLJarFile` 一类符号，在 11 的 `startup/`、`webresources/` 两棵树里已经 grep 不到任何痕迹——展开目录与 tracker 是唯一的版本真相。

## ContextConfig descriptor merge

`configureStart()`（`startup/ContextConfig.java:1034`）的骨架只有五步：`webConfig()`（`:1046`）→ 条件性 `applicationAnnotationsConfig()` → `validateSecurityRoles()`（`:1052`）→ `authenticatorConfig()`（`:1057`）→ `context.setConfigured(ok)`（`:1077`）。真正的复杂度全在 `webConfig()`（`:1288`）里。

它的数据流是「以应用 web.xml 为基底，按 fragment → tomcat-web.xml → 全局默认 的顺序 merge」：

```java
        Set<WebXml> defaults = new HashSet<>();
        defaults.add(getDefaultWebXmlFragment(webXmlParser));

        Set<WebXml> tomcatWebXml = new HashSet<>();
        tomcatWebXml.add(getTomcatWebXmlFragment(webXmlParser));

        WebXml webXml = createWebXml();

        // Parse context level web.xml
        InputSource contextWebXml = getContextWebXmlSource();
        if (!webXmlParser.parseWebXml(contextWebXml, webXml, false)) {
            ok = false;
        }
```

之后的九个编号步骤（`:1339` 起）：Step 1 `processJarsForWebFragments()` 收集容器与应用两侧 JAR 的 `web-fragment.xml`；Step 2 `WebXml.orderWebFragments()` 按 `<absolute-ordering>` / `metadata-complete` 排序（`:1342`）；Step 3 `processServletContainerInitializers()`；Step 4 & 5 `processClasses()` 做注解扫描（`:1351`）；Step 6 `webXml.merge(orderedFragments)`（`:1358`）；Step 7a merge `tomcat-web.xml`；Step 7b merge `defaults`；Step 8 `convertJsps()`；Step 9 `configureContext()` 把结果落到 `Context` 上。

**为什么全局 `conf/web.xml` 排在最后 merge，却仍然优先级最低？** 因为 `WebXml.merge()` 的语义是"只填坑不覆盖"：先加入者的定义胜出，后来者只有在名字未被占用时才生效。基底是应用自己的 web.xml，所以应用永远压过全局；全局默认（`DefaultServlet`、`JspServlet`、mime 映射）作为"兜底"最后补齐空白。方法开头的注释给出了这个两难的另一半解法：

```java
        /*
         * Anything and everything can override the global and host defaults. This is implemented in two parts:
         *
         * - Handle as a web fragment that gets added after everything else so everything else takes priority
         *
         * - Mark Servlets as overridable so SCI configuration can replace configuration from the defaults
         */
```

也就是说：web.xml 层面的覆盖靠 merge 顺序，SCI（注解 / `ServletContainerInitializer`）层面的覆盖靠 `overridable` 标记——否则应用就无法替换容器提供的 `JspServlet` 了。这是全站关于"默认 servlet 为什么能被覆盖"最省事的解释。

注解部分的三条规则同样写在同一个注释块里（`:1298`-`:1310`），值得单列出来，因为它们是各种"注解没生效"报告的根源：

- 无论 web.xml 声明哪个 Servlet 规范版本，都会扫注解（SRV.1.6.2）。
- `metadata-complete="true"` 时 JAR 仍要扫，但**只为了找 SCI**。
- `metadata-complete="true"` 且给了 absolute ordering 时，被排除的 JAR 连 SCI 也不扫。
- 有 SCI 带 `@HandlesTypes` 时，除被排除的 JAR 外**全部**都要扫——`ignoreAnnotations`（`:1048`）只能整体关掉这一段。

> [!WARNING]
>
> 11 已移除 SecurityManager。`ContextConfig` 里已找不到任何 `Permission` / `processContextPermissions` 相关处理（对该文件全文 grep 无命中），剩下的 `validateSecurityRoles()` 与 `authenticatorConfig()` 属于 Servlet 声明式安全，与 Java 策略文件无关。旧教程里 `<Context useHttpOnly>` 之外配 `permissions` 的做法在本版本没有对应代码。

## WebappServiceLoader

SCI 的发现走 `startup/WebappServiceLoader`（全文 239 行），类注释自称是 `java.util.ServiceLoader` 的"变体"。必须澄清：**配置文件格式与 JDK SPI 完全一致**，不是 properties 的 `key=value`：

```java
    void parseConfigFile(LinkedHashSet<String> servicesFound, URL url) throws IOException {
        ...
            String line;
            while ((line = reader.readLine()) != null) {
                int i = line.indexOf('#');
                if (i >= 0) {
                    line = line.substring(0, i);
                }
                line = line.trim();
                if (line.isEmpty()) {
                    continue;
                }
                servicesFound.add(line);
            }
        ...
    }
```

路径同样固定为 `META-INF/services/<接口全名>`（常量 `SERVICES`），一行一个实现类，`#` 之后当注释丢弃。差异全在"扫哪些 JAR、谁先谁后、要不要实例化"这三件事上：

| 维度        | `java.util.ServiceLoader`                     | `WebappServiceLoader`                                          |
| :-------- | :-------------------------------------------- | :------------------------------------------------------------- |
| 容器 / 应用次序 | 由 ClassLoader 委托顺序决定                         | **容器 SCI 先于应用 SCI**，两段用 `LinkedHashSet` 合并（应用追加在后面）           |
| 排除控制      | 无                                             | `Context` 的 `containerSciFilter` 正则，编译进构造器 `removeIf(...)`   |
| 扫描范围      | classpath 全量                                  | 若 `ServletContext` 有 `ORDERED_LIBS`，只扫其中点名的 JAR 与 `/WEB-INF/classes/` |
| 是否懒加载     | 迭代时才实例化                                       | 全部 `Class.forName(...).newInstance()` 立即实例化                     |
| 定位 entry  | `ClassLoader.getResources()`                  | 自定义 CL 时退化到 `servletContext.getResource()` + `JarFactory.getJarEntryURL()` |

为什么要自造，源码注释给了两个理由，都不是"格式不同"：其一是 `@HandlesTypes` 要求容器**内省全部**实现，懒加载模型（`ServiceLoader.stream()` 那套）拿不到类型信息；其二是 webapp 常用自定义 ClassLoader，而 `ClassLoader.findResources()` 是 `protected`，Tomcat 不想为此破坏兼容性，只能绕 `ServletContext.getResource()`。容器 SCI 排在应用 SCI 之前、但**统一用 webapp ClassLoader 加载**，这意味着应用理论上可以塞一个同名实现去顶掉容器提供的 SCI——注释里明确说这是有意为之。

## StandardContext start phases

`startInternal()`（`core/StandardContext.java:4388`）是"配置完毕"到"能接请求"之间最后一段路，顺序如下（行号为该文件绝对行号）：

| 行号     | 动作                                            | 失败语义                       |
| :----- | :-------------------------------------------- | :------------------------- |
| `:4414` | `getResources() == null` 则建 `StandardRoot`      | 必须先有，Loader 依赖它             |
| `:4430` | `getLoader() == null` 则建 `WebappLoader`        | —                          |
| `:4467` | `bindThread()` 把 CCL 切到 webapp ClassLoader      | `finally` 里 `unbindThread()` |
| `:4472` | 启动 `Loader`（此后 webapp ClassLoader 可用）           | 抛异常即 FAILED                |
| `:4478` | 把 `clearReferences*` 与 `notFoundClassResourceCacheSize` 等一组开关注入刚建好的 `WebappClassLoaderBase`；随后 `unbindThread(oldCCL); oldCCL = bindThread()`（`:4490`-`:4491`）成对调用才真正把当前线程 CCL 设为 webapp ClassLoader，源码注释直接点明了这个 trick | —    |
| `:4495` | 重置 logger（`logger = null; getLogger();`），因为其他组件可能过早取过它                        | —                          |
| `:4528` | 启动所有 `Wrapper` 之前的子容器检查 `child.getState().isAvailable()` | 任一 Wrapper 失败 → context 失败   |
| `:4535` | 启动 `Pipeline`（含 `BasicValve`），见 [Valve](/docs/CS/Framework/Tomcat/Valve.md) | —    |
| `:4541` | 取 / 建 `Manager`，集群下优先向 Cluster 要                | `StandardManager` 兜底        |
| `:4604` | 调用 `ServletContainerInitializer#onStartup()`    | 抛异常直接终止启动                 |
| `:4642` | `filterStart()` 实例化 filter 并生成 filter chain     | 返回 `false` → 启动失败           |
| `:4650` | `loadOnStartup(findChildren())` 按 `load-on-startup` 升序初始化 servlet | 返回 `false` → 启动失败 |
| `:4689` | 任何异常走 `setState(LifecycleState.FAILED)`           | context 永久不可用，见下           |

`initializers` 是 `StandardContext` 里的 `LinkedHashMap<ServletContainerInitializer, Set<Class<?>>>`（`:229`），由 `ContextConfig` 在解析阶段灌入（`:1343`），`stopInternal` 时清空（`:5022`）。**LinkedHashMap 不是随手选的**：SCI 的调用顺序必须等于发现顺序（容器先、应用后），否则像 JSP / Weld 这类互相依赖的 SCI 就会随机失败。`JasperInitializer` 正是这些 SCI 之一（注册 JSP 编译上下文与 TLD 相关逻辑），从 URL 到 `_jspService` 的完整编译链见 [Jasper](/docs/CS/Framework/Tomcat/Jasper.md)。

这里有个和 docsify 站点上常见描述不一致的语义：**`filterStart()` 或 `loadOnStartup()` 失败不会让 Tomcat 退出，只会让这个 context 变成"存在但不可用"**。表现为该应用所有请求返回 `404`（对 `Mapper` 来说它根本没 available），而其他应用照常服务，日志里只有一条 `Context [...] startup failed`。这也是 `autoDeploy` 场景下最难排查的一类问题：war 已经展开、目录存在、`Host` 里能查到这个 `Context`，但它不接流量。

## Embedded API startup.Tomcat

`startup/Tomcat.java`（1326 行）是官方编程入口，public 面很小：

```java
public Tomcat()                                   // :175
public void setBaseDir(String basedir)            // :196
public void setPort(int port)                     // :~203  默认 connector 只在 getConnector() 被调用时才创建
public Context addWebapp(String contextPath, String docBase)              // :232
public Context addWebapp(String contextPath, URL source) throws IOException // :250  先把 war 复制进 appBase
public Context addContext(String contextPath, String docBase)             // :318
public static Wrapper addServlet(Context ctx, String name, Servlet servlet) // :389
public void init(ConfigurationSource source)                              // :406
public void init(ConfigurationSource source, String[] catalinaArguments)  // :418
public void init() / start() / stop() / destroy()                         // :439 / :450 / :460 / :471
public Connector getConnector()  // :509
public Service  getService()     // :546
public Host     getHost()        // :575
public Engine   getEngine()      // :592
public Server   getServer()      // :610
public void     enableNaming()   // :987
public static void initWebappDefaults(Context ctx)  // :1038
```

最小可用示例（**这是用法示例，不是源码摘录**）：

```java
Tomcat tomcat = new Tomcat();
tomcat.setBaseDir("/tmp/tomcat-work");        // 不放这里会默认用 CWD 下的 .tomcat
tomcat.setPort(8080);
tomcat.getConnector();                       // 关键：默认 Connector 是懒创建的，不调就永远没有 HTTP 端口
tomcat.addWebapp("", new File("/abs/path/to/foo.war").getAbsolutePath());
tomcat.start();                              // 到这里才真正跑完上面那条部署链
tomcat.getServer().await();                  // 阻塞，交给 Server 的 shutdown 语义
```

`addWebapp` 的实现值得逐行读（`:720`），因为它就是本篇前四节的浓缩版：

```java
    public Context addWebapp(Host host, String contextPath, String docBase, LifecycleListener config) {

        silence(host, contextPath);

        Context ctx = createContext(host, contextPath);
        ctx.setPath(contextPath);
        ctx.setDocBase(docBase);

        if (addDefaultWebXmlToWebapp) {
            ctx.addLifecycleListener(getDefaultWebXmlListener());
        }

        ctx.setConfigFile(getWebappConfigFile(docBase, contextPath));

        ctx.addLifecycleListener(config);

        if (addDefaultWebXmlToWebapp && (config instanceof ContextConfig)) {
            // prevent it from looking ( if it finds one - it'll have dup error )
            ((ContextConfig) config).setDefaultWebXml(noDefaultWebXmlPath());
        }

        if (host == null) {
            getHost().addChild(ctx);
        } else {
            host.addChild(ctx);
        }

        return ctx;
    }
```

三个要点：

- `config` 是 `Class.forName(host.getConfigClass())` 出来的 `ContextConfig`（`:692`）——**内嵌 API 也走同一套合并逻辑，没有捷径**。
- `addDefaultWebXmlToWebapp` 为 `true` 时，默认 servlet / mime 由 `DefaultWebXmlListener`（`:1131`）在事件里注入，而不是读磁盘上的 `conf/web.xml`（内嵌场景通常根本没有 `$CATALINA_BASE`）。要关掉它调 `setAddDefaultWebXmlToWebapp(false)`。
- `getWebappConfigFile()` 会主动去找应用里的 `META-INF/context.xml` 并塞给 `setConfigFile()`，这就是"内嵌也能读 context 描述符"的全部机制。

与之相对，`addContext()` 只挂 `docBase`，配置的 `LifecycleListener` 是内部类 `FixContextListener`（`:1095`）。它的作用写在类注释里："The `start()` method in context will set 'configured' to false - and expects a listener to set it back to true"——也就是**跳过整条 web.xml / SCI 链**，只给你手动 `addServlet` 的东西。`addContext` 与 `addWebapp` 的区别不是"轻量和重量"，而是"要不要标准 Servlet 部署语义"。

### Relation to Spring Boot

`main()`（`:1267`）本身就用这套 API：解析 `--war` / `--path` / `--await` / `--no-jmx` / `--catalina`，`new Tomcat()` → `tomcat.init(null, catalinaArguments)`（`:1285`，注释写着"Create a Catalina instance and let it parse the configuration files"）→ `addWebapp()`。注意 `init(ConfigurationSource, String[])` 与无参 `init()`（`:439`，只做 `getServer().init()`）是两条不同路径：**前者读 `server.xml`，后者完全程序化装配**。

[Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md) 的嵌入式 Tomcat 属于后者：`TomcatServletWebServerFactory` 一类的工厂 `new Tomcat()`、设 baseDir 与 connector、按 `ServletContextInitializer` 列表决定用 `addContext` 还是 `addWebapp`，最后 `start()` 并自己接管 await（详见 [Spring Boot 启动](/docs/CS/Framework/Spring_Boot/Start.md)）。Spring 的类名与内部流程不在本镜像中，因此这里只作为集成点叙述，不当作源码事实。可以直接确定的对比例子是 [Jetty](/docs/CS/Framework/Jetty/Jetty.md) 的 `deploy` 模块——它把 Deployment 变成一个显式对象，而 Tomcat 是唯一还保留 war 目录扫描这条历史包袱的。

## Hot deployment and reload boundaries

`checkResources()`（`startup/HostConfig.java:1316`）是 reload 判定的唯一入口，它手里有两组资源：

- `redeployResources`：**整个应用重部署**。war 文件本身、外部 `context.xml`、`${catalina.base}/conf/Catalina/context.xml` 与 host 级 `context.xml`（由 `addGlobalRedeployResources()` 登记，永不删除）。
- `reloadResources`：**只重启 context**。来源是 `Context` 的 `<WatchedResource>`，默认覆盖 `WEB-INF/web.xml`、`WEB-INF/classes/**` 与 `WEB-INF/lib/**`（`addWatchedResources()`）。

边界很清楚：动 war 或动描述符 → 换 `docBase`、可能重新展开；动 `WEB-INF/web.xml` → 复用现有目录，走 stop/start。后者还要满足 `Context.getReloadable()` 且 `WEB-INF/classes` 里出现变化时通过 `HostConfig` 的 `reload(DeployedApplication, File, String)`（`:1434`）完成，真正的 session 迁移与旧 webapp ClassLoader 释放语义见 [Tomcat 的 Adavance](/docs/CS/Framework/Tomcat/Tomcat.md?id=adavance)，本篇不重复。

并行部署的回收是另一条路：`ContextName` 会把 `app##v2.war` 解析成同一 `path` 下的新版本，`checkUndeploy()`（`:1694` 起）按名字排序比较相邻项，若旧版本 `Manager.getActiveSessions()`（集群下用 `getActiveSessionsFull()`）为 `0`，就 `undeploy()` 并用 `-1` 哨兵清掉它的全部 redeploy 资源。**"旧版本先活着直到没人用"是并行部署的全部难点**，而它的实现只是这一段字符串排序。

把一个 war 批量同步到集群所有节点的对应物是 `FarmWarDeployer` + `WarWatcher`（watch 目录轮询 + 文件消息分片传输），它挂在 `ClusterDeployer` 契约下，见 [Cluster](/docs/CS/Framework/Tomcat/Cluster.md)。

## Pitfalls

| 现象                        | 根因与结论                                                                                     |
| :------------------------ | :--------------------------------------------------------------------------------------- |
| 生产环境 CPU 周期性抖动、日志反复重部署    | `autoDeploy="true"`。每轮 `check()` 会 `appBase.list()` 并对每个应用 stat 两组资源树；任何写入 `appBase` 的进程（备份、健康检查、日志切割）都会改 mtime。生产应显式关掉，并把 `deployOnStartup` 也设为 `false` 后用 Manager 或编排系统下发 |
| 部署后 404 但目录存在且 `Context` 在 | context 处于 FAILED / 未 configured（`ContextConfig` 的 `ok=false` → `setConfigured(false)`，`:1077`），或 filter / load-on-startup 失败（`:4642`、`:4650`）。看 `catalina.out` 里 `startup failed` 那条，不要只看 HTTP 码 |
| war 改了但重启没生效              | 展开目录的 `warTracker` mtime 恰好与 war 相同（复制保留了时间戳、或部署脚本只 `touch` 目录）。删掉展开目录 + tracker 再启动             |
| `unpackWARs="false"` 后 JSP 变慢或报找不到资源 | 不展开时全部读走 jar entry，`WebResourceRoot` 要维护 jar 缓存；同时 war 内 `META-INF/context.xml` 的 `copyXML` 路径也变了（`:867`-`:880`） |
| `webapps/` 只读、镜像化部署启动失败     | `ExpandWar.expand()` 会 `docBase.mkdir()` 并在失败时抛 `expandWar.createFailed`；只读介质必须 `unpackWARs="false"` 或用外部 `docBase` + `configBase` 描述符 |
| 应用挂到 `/` 不生效，出现两个 ROOT      | context path 为空串才是 ROOT；`addWebapp("", ...)` 与 appBase 里的 `ROOT/` 会互相覆盖。`addWebapp` 遇到同名 child / 同名 war+dir 会直接抛 `tomcat.addWebapp.conflictChild` / `conflictFile`（`:258`、`:267`） |
| war 名字带 `##` 或路径带正则特殊字符被忽略 | `##` 是并行部署的版本分隔（正常），`deployIgnore` 命中的路径会被 `filterAppPaths()` 静默跳过（只打 debug 日志，`:435` 附近）——排查时先把日志级别开到 debug |
| 端口没起来                       | 只调了 `setPort()`。默认 `Connector` 在 `getConnector()`（`:509`）里懒创建，`start()` 前必须至少碰一次；`getHost()` / `getEngine()` 同理有各自的隐式建副作用 |
| 内嵌场景 `META-INF/services` 里的 SCI 不生效 | 用了 `addContext()`（不跑部署链）或 `setAddDefaultWebXmlToWebapp(false)` 后又自己塞了 web.xml；或被 `containerSciFilter` 正则过滤掉                      |

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Start](/docs/CS/Framework/Tomcat/Start.md)
- [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)
- [Container](/docs/CS/Framework/Tomcat/Container.md)
- [Servlet](/docs/CS/Java/JDK/Servlet.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Tomcat 11 Host Configuration Reference](https://tomcat.apache.org/tomcat-11.0-doc/config/host.html)
2. [Tomcat 11 Context Configuration Reference](https://tomcat.apache.org/tomcat-11.0-doc/config/context.html)
3. [Tomcat 11 Cluster How-To](https://tomcat.apache.org/tomcat-11.0-doc/cluster-howto.html)
4. [Apache Tomcat Examples (Embed)](https://github.com/apache/tomcat/tree/11.0.x/webapps/examples/WEB-INF/classes)
