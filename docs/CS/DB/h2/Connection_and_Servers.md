## Introduction

这一页管的是「连接怎么建立、进程间怎么共享同一个库、怎么把 H2 暴露成服务、以及暴露时什么会咬人」。锚定 H2 2.5.252；文档与源码不一致处两边都写并以源码为准。

## Connection Modes and URLs

三种连接模式与三个正交维度的关系见 [H2](/docs/CS/DB/h2/H2.md) 的 Three Orthogonal Dimensions 一节，这里只补实现细节与真实默认值。

- **Embedded**：同 JVM 内直接打开，最快；**一个库同一时刻只能被一个虚拟机（且一个 class loader）持有**，第二个进程会被 `.lock.db` 挡住。I/O 由执行 SQL 的应用线程完成，所以应用的线程模型会直接变成数据库的 I/O 行为。
- **Server**：一个进程当 server，其它进程（可跨机器）连入；加密链路用 `ssl://`（JSSE，自定义 keystore 走 `javax.net.ssl.keyStore` 系列属性）。
- **Auto-Mixed（`AUTO_SERVER=TRUE`）**：首个连接以 embedded 打开并在内部起一个 daemon 线程的 TCP server，后来的进程自动转 client/server。**它明确拒绝这几种配置**：只读库、内存库、`FILE_LOCK=NO`、`FILE_LOCK=FS`、`DB_CLOSE_ON_EXIT=FALSE`（`Database.java:275-282`）——最后一条常被忽略，因为它和「嵌入式 + 连接池」的推荐组合冲突。内嵌起的这个 server 是带 `-tcpAllowOthers` 的，靠 `.lock.db` 里的 key 限定只能访问那一个库，**不能写成「只监听本机」**。

真实存在的 URL 开关（几个常被引用但其实不存在的：`ACCESS_MODE_LOG`、`SHARED`、`DELAY_DB_OPEN`、`AUTO_SERVER_RECONNECT` 均**不存在**）：

| 片段 | 真实语义 |
| :--- | :--- |
| `jdbc:h2:mem:` / `jdbc:h2:mem:db1` | 私有内存库 / 具名内存库（不具名的两个连接 = 两个不同的库） |
| `;IFEXISTS=TRUE` | 库不存在就报错，避免打错路径顺手建空库 |
| `;DB_CLOSE_ON_EXIT=FALSE` | 阻止 VM 退出时关库（默认值随库类型变，见下） |
| `;DB_CLOSE_DELAY=60` | -1 永不自动关（其它负数报错）、0 默认、≥1 为秒；需 admin 且**会持久化**；但**正常退出或 `System.exit` 时即使设了 delay 也会立刻关闭** |
| `;INIT=RUNSCRIPT FROM '~/create.sql'` | 每次连接执行 SQL，多条用 `\;` 分隔 |
| `;ACCESS_MODE_DATA=r` | 以只读打开（唯一存在的访问模式参数，默认 `rw`） |
| `;CIPHER=AES` | 文件加密；同时改变口令的解析方式（见下文加密段） |
| `;FILE_LOCK={FILE|SOCKET|FS|NO}` | 锁协议，**默认是 `FS`** |
| `;IGNORE_UNKNOWN_SETTINGS=TRUE` | 未知参数不报错（否则抛 Unsupported） |
| `;PAGE_SIZE=8192` | 仅建库时有效；加密库必须是 4096 的倍数 |
| `;MODE=MySQL;DATABASE_TO_LOWER=TRUE` | 兼容模式与其配套开关（后者不会自动随模式开启） |

`DB_CLOSE_ON_EXIT` 的默认值是「持久库 true / 内存库 false」，且持久库总会注册 shutdown hook；设成 FALSE 时 hook 仍然会做一次 `checkpoint()`（`Database.java:280,386,1174-1181`、`OnExitDatabaseCloser.java:41`）。

## File Locking: 默认值与文档不符

**文档 `features.html#Database File Locking` 说默认方法是 `FILE`，源码里默认是 `FS`**（`Database.java:246-248`），只有 `AUTO_SERVER` 才强制回落到 `FILE`。三种协议的真实行为：

- `FILE`：watchdog 线程每 **1000 ms**（`LOCK_SLEEP`）复查锁文件；陈旧判定粒度 2000 ms，抢占最多再等 80×25 ms（`FileLock.java:44-46, 279-301, 477-495`）。
- `SOCKET`：开一个 server socket，不轮询；只应在文件仅由同一台机器访问时使用。
- `FS`：`FileChannel.lock` 原生锁（默认）。

`.lock.db` 的内容也不只是文档说的「IP 和端口」：它含 `method`（file|socket）、`id`（时间戳 hex + 16 随机字节 hex，即 AUTO_SERVER 的 key），AUTO_SERVER 下另写 `server`=ip:port 与 `hostName`（`Database.java:694-698`）。当锁文件里带 `server` 时，第二个进程会**先做一次 TCP 探测**，活着就抛 `DATABASE_ALREADY_OPEN_1` 并把 `server`/`id` 塞进 SQL 字段回传给客户端（`FileLock.java:214-249`）。容器、NFS、跨机器共享目录里的「库明明没人用却打不开」，基本都出在这套判定的时间粒度与网络可见性上。

## Servers

三个 server 的默认端口（常量**不在** `server/Service.java`，那只是接口）：TCP `9092`（`engine/Constants.java:223`）、Web Console `8082`（`:189`）、PG `5435`（`server/pg/PgServer.java:43`）。

命令行参数全集见 `tools/Server.java` 的 `verifyArgs`/`runTool`（168-248、306-340）：`-web -webAllowOthers -webExternalNames -webDaemon -webVirtualThreads -webPort -webSSL -webAdminPassword -browser -tcp -tcpAllowOthers -tcpDaemon -tcpVirtualThreads -tcpPort -tcpSSL -tcpPassword -tcpShutdown -tcpShutdownForce -pg -pgAllowOthers -pgDaemon -pgPort -properties -baseDir -ifExists -ifNotExists -trace -key <from> <to> -tool`。几个要点：

- **不带参数启动 = tcp + pg + web + browser 四件事一起做**（`:341-347`）。
- **默认端口被占用时会回落到随机端口**（`TcpServer.java:241-249`）——脚本化运维必须显式 `-tcpPort`。
- `-pgPassword` **不存在**；`-ftp*` 只在 `verifyArgs` 里放行、`runTool` 会报不支持（遗留死代码）；`-webAdminPassword` **被显式拒绝从命令行传入**（`:190-196`），只能经配置文件或程序化调用，值是十六进制哈希。
- 停服：`-tcpShutdown "tcp://localhost:9092" [-tcpPassword x] [-tcpShutdownForce]`。`force=false` 的语义是拒绝新连接、等最后一个连接关闭才停，**且此后无法再用 `force=true`**；`tools/Shutdown` 类不存在。TCP server 内部还有一个管理用库 `mem:tcp:server<port>`。

**建库权限的默认方向**：服务端 `ifExists` 默认是 **true**（`TcpServer.java:66`、`PgServer.java:83`、`WebServer.java:179`），也就是**2.5 起远程默认不能建库**；`-ifNotExists` 打开后「访问即建库」，风险是与 `INIT` / `CREATE ALIAS` 组合可直接执行代码。旧资料常把这个方向写反。

Console 的配置文件真实名是 **`~/.h2.server.properties`**（`Constants.java:391/396`），键为 `webPort/webSSL/webAllowOthers/webExternalNames/webAdminPassword/commandHistory`，再加数字键 `0..n-1` 存 `name|driver|url|user`（**不含口令**）；`-properties null` 可禁用。所谓 `WEB_ALLOW_OTHERS` / `WEB_PASSWORD` / `WEB_USER_NAME` 这些大写键名**不存在**。

## Security

- **授权**：只有 `GRANT {SELECT|INSERT|UPDATE|DELETE|ALL} [PRIVILEGES] ON {SCHEMA s | [TABLE] t} TO PUBLIC|user|role`、`GRANT ALTER ANY SCHEMA TO u`（= schema admin）、以及角色授予；REVOKE 对称；**没有列级/细粒度授权**。注意 `GRANT`/`REVOKE`、`SET DB_CLOSE_DELAY` 这类语句**会提交当前事务**。
- **任意类加载**：官方在 advanced.html 的 "Restricting Class Loading and Usage" 一节说得很直白——默认对 admin **毫无限制**，举例就是 `CREATE ALIAS SET_PROPERTY FOR "java.lang.System.setProperty"`。真实的限制机制是 JVM 系统属性 **`h2.allowedClasses`**（逗号分隔类名，支持 `*` 前缀，默认全允许），覆盖事件监听器、触发器、UDF、聚合以及 Console 里注册的 JDBC 驱动。
- **注入防护**：`SET ALLOW_LITERALS NONE|NUMBERS|ALL`（默认 ALL，仅管理员可改，且会持久化、也可写在 URL 上），配合 `CREATE CONSTANT` 与 `ZERO()`。`DISABLE_ORACLE_SYNTAX_SUPPORT` 不存在。
- **爆破延时**：`h2.delayWrongPasswordMin` / `Max` 默认 250 / 4000 ms（翻倍递增），且**用户名错与口令错返回同一异常**。
- 绑定地址统一由 `-Dh2.bindAddress` 控制（含所有 TLS socket）。

## Encryption

三层要分清（第三层细节见 [MVStore](/docs/CS/DB/h2/MVStore.md)）：

1. `CIPHER` 可选 `AES`（**仅实现 AES-128**）/ `XTEA`（32 轮）/ `FOG`（伪加密，只用于让文本编辑器看不出内容）——`CipherFactory.java:69-78` 只认这三个。
2. 但 `.mv.db` 主文件的加密**与 CIPHER 名无关**，永远是 PBKDF2(SHA-256, 10 轮) 派生的 AES-128-XTS；`CIPHER` 真正决定的是 LOB/临时文件与脚本文件的 `SecureFileStore`（那里迭代 1024 轮）。
3. **两段式口令只在 URL 含 `CIPHER` 时生效**：按**第一个空格**切成「文件口令 + 用户口令」，没有空格就报 `WRONG_PASSWORD_FORMAT`，文件口令不能含空格，两者都区分大小写；写法是在 URL 的 `PASSWORD=` 或 `getConnection` 参数里给，**不是交互式输入**。`PASSWORD_HASH=TRUE` 表示给的是十六进制哈希。

AES 让操作慢约 2.5 倍。事后加解密/换密用 `ChangeFileEncryption`，参数只有 `-dir -db -cipher -encrypt -decrypt -quiet`（**改密要先解密**，文档没写这层）。定位要说清：这只防「文件被离线拿走」，不防有写权限的人。

## Read-Only, Packaging and Backup

- 文件设为只读 → 库即只读，只允许 `SELECT` 与 `CALL`；判断走 `Connection.isReadOnly()` 或 `CALL READONLY()`；也可用 `ACCESS_MODE_DATA=r` 在文件可写时强开只读。
- 打包形态是 **`jdbc:h2:zip:~/data.zip!/test`**（格式 `zip:<zip>!/<db>`）；**源码里没有 `jar:` 前缀的处理**，旧说法要改。打包前应 `SHUTDOWN DEFRAG`，且此时只能用 **Backup 工具**（`-dir -db -file -quiet`）——文档明确说这种场景不能用 `BACKUP TO`。
- `BACKUP TO 'backup.zip'` 拷文件与日志，不锁对象但保证事务一致，需要 admin 权限。
- 移动或改名库文件是安全的：库名与路径不写进数据库，关闭后按同前缀改名/换目录即可跨 OS 搬迁。

## PG Protocol and ODBC: 官方逐条列出的限制

PG Server 的兼容性在文档里挂在 advanced.html 的 "ODBC Driver" 一节内（**不是独立小节**），限制值得全抄：

1. 只实现 PG 协议的**子集**，SQL、catalog 与文本编码仍可能不兼容，官方措辞是 "Problems are fixed as they are found"。
2. **PG 协议下语句无法取消**。
3. 不提供 index meta。
4. PgSQL ODBC 驱动强制要求口令 → **连不上没有口令的 H2 库**。
5. 安全：不支持 challenge-response / 口令加密（**口令在链路上可被嗅探**），**不支持 SSL**，官方直接写「安全重要的场景不要用」。
6. **第一个打开某库的连接必须是管理员**，后续连接才不必。

另外 `-key TEST "~/data/test;cipher=aes"` 这类映射只能有一条、库名需 ≥3 字符，并建议打开 ODBC 侧的 server-side prepare。

## Pitfalls

1. 默认 `FILE_LOCK` 是 **FS**，`AUTO_SERVER` 才强制 FILE——照文档写 FILE 会得出错误的排障结论。
2. `-ifNotExists` 是「打开即建库」开关，**默认已禁止远程建库**。
3. `DB_CLOSE_DELAY=-1` 挡不住 JVM 正常退出时被关闭；`DB_CLOSE_ON_EXIT=FALSE` 仍会 checkpoint。
4. 两段口令只在 URL 带 `CIPHER` 时才拆分，否则整串当用户口令。
5. 端口被占会用随机端口，运维脚本必须显式指定。
6. PG 协议端点没有 SSL，不能当安全通道用。
7. `GRANT`/`REVOKE` 与若干 `SET` 会提交事务，放在事务中间会改变回滚边界。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [MVStore](/docs/CS/DB/h2/MVStore.md)
- [Transactions and Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)
- [Tools and Operations](/docs/CS/DB/h2/Tools_and_Operations.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Compatibility Modes](/docs/CS/DB/h2/Compatibility_Modes.md)

## References

1. [H2 Database Engine - Features](https://h2database.com/html/features.html)
2. [H2 Database Engine - Advanced Features](https://h2database.com/html/advanced.html)
3. [H2 Database Engine - Security](https://h2database.com/html/security.html)
4. [H2 source at tag 2.5.252: org/h2/tools/Server.java](https://github.com/h2database/h2/blob/2.5.252/src/main/h2/org/h2/tools/Server.java)
