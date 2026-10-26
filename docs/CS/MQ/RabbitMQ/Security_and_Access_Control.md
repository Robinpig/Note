## Introduction

RabbitMQ 的安全模型只有两层，但这两层的边界经常被搞混，混了就等于没做权限控制。

- **认证（Authentication, authn）** = 你是谁。凭密码、JWT、X.509 证书证明身份，回答完这题连接才建立。
- **授权（Authorisation, authz）** = 你能做什么。决定这个已认证的身份可以碰哪些 vhost、哪些 exchange、哪些队列。

官方文档原话是 "Authentication and authorisation are often confused or used interchangeably. That's wrong and in RabbitMQ, the two are separated."

本文基于 **RabbitMQ 4.4.0**（2026-10-20 发布，社区支持至 2027-07-31）。上一系列 4.3.x 最新补丁 4.3.6（2026-09-16，社区支持至 2027-01-31）。4.3.0 起元数据存储从 Mnesia 换成 Khepri（Raft），最低 Erlang/OTP 27；4.4.0 完整支持 Erlang/OTP 28 与 29。

文中所有配置键与命令均已对照 4.4.0 的 `rabbitmq-server` 源码核实（`deps/rabbit/priv/schema/rabbit.schema`、`deps/rabbit/src/rabbit_access_control.erl`、`deps/rabbitmq_cli/lib/rabbitmq/cli/ctl/commands/`），不是凭记忆写的。

先说三个最容易在生产上踩的坑，展开在后面：

1. **改完权限不代表立刻生效** —— 授权检查结果会被缓存，官方文档说是 "per-connection or per-channel basis"，最坏情况下要等客户端重连才生效。"我已经 revoke 了权限，为什么这个连接还在发消息？"——答案就是缓存。
2. **`guest` 不是一个普通的默认用户** —— 它默认全权限 `.*`，但被 `loopback_users` 限制为只能从 localhost 连接。这两件事必须同时理解，否则要么以为它很安全（其实全权限），要么以为它很危险（其实远程连不上）。
3. **4.4.0 有两个 breaking change 直接打在认证链路上** —— OIDC discovery 校验变严、密码哈希 HTTP 端点换协议。升级前不处理，升级后直接起不来。

## Two Layers: Authentication and Authorisation

本篇讲的是 broker 侧「谁能连、能操作什么」。协议层的入口差异（0-9-1 与 1.0 的授权检查点不同）见[协议面](/docs/CS/MQ/RabbitMQ/Protocol.md)，vhost 与 Khepri 元数据的关系见[集群与元数据](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)。


两者在配置上是**可分离**的，同一个槽位可以认证用 A 后端、授权用 B 后端：

```ini
# 内部数据库认证，IP 段授权
auth_backends.1.authn = internal
auth_backends.1.authz = rabbit_auth_backend_ip_range

# LDAP 认证，内部数据库授权
auth_backends.1.authn = ldap
auth_backends.1.authz = internal
```

后端链上**第一个返回肯定结果的后端即为最终结论**，后续不再问：

```ini
auth_backends.1 = ldap
auth_backends.2 = internal
```

含义是：LDAP 里找到用户就用 LDAP 校验密码；LDAP 里没有这个用户，退回内部数据库再试一次。

`.authn` / `.authz` 后缀是可选的。写 `auth_backends.1 = internal` 等于同时指定该槽位既做 authn 又做 authz。

第三方插件**必须写完整的 Erlang 模块名，不能写插件名**——这是官方特意加的提醒，因为模块名前缀是 `rabbit_` 而插件名通常是 `rabbitmq_`：

```ini
# 错：这是插件名，不是模块名
auth_backends.1 = rabbitmq_auth_backend_ip_range

# 对
auth_backends.1 = rabbit_auth_backend_ip_range
```

内置别名（对照 4.4.0 schema 的 `rabbit.auth_backends` translation 逐个确认）：

| 别名 | 实际模块 |
| --- | --- |
| `internal` | `rabbit_auth_backend_internal` |
| `internal_loopback` | `rabbit_auth_backend_internal_loopback` |
| `ldap` | `rabbit_auth_backend_ldap` |
| `http` | `rabbit_auth_backend_http` |
| `oauth` / `oauth2` | `rabbit_auth_backend_oauth2` |
| `cache` | `rabbit_auth_backend_cache` |
| `amqp` | `rabbit_auth_backend_amqp` |
| `dummy` | `rabbit_auth_backend_dummy` |

> [!WARNING]
> 后端模块对应的插件没启用时，RabbitMQ 会在启动时**直接中止**（abort boot），不是静默降级。日志里会明确列出哪些后端因为插件不可用被丢弃。

## Authentication Mechanisms

`auth_mechanisms` 是一个**有序列表，顺序即客户端偏好顺序**（AMQP §5.3.3.1 明确要求服务端按偏好降序排列）：

```ini
auth_mechanisms.1 = PLAIN
auth_mechanisms.2 = AMQPLAIN
auth_mechanisms.3 = ANONYMOUS
```

4.4.0 的默认值就是上面这三项（`deps/rabbit/Makefile` 里的 `{auth_mechanisms, ['PLAIN', 'AMQPLAIN', 'ANONYMOUS']}`）。

| 机制 | 来源 | 说明 |
| --- | --- | --- |
| `PLAIN` | 内置 | 明文传密码，**必须配 TLS**，否则等同裸奔 |
| `AMQPLAIN` | 内置 | PLAIN 的变体 |
| `ANONYMOUS` | 内置 | 无凭据，**生产环境必须移除** |
| `RABBIT-CR-DEMO` | 内置 | 演示用 |
| `EXTERNAL` | 插件 | 来自 `rabbitmq_auth_mechanism_ssl`，用客户端证书做外部认证 |

移除 ANONYMOUS：

```ini
auth_mechanisms.1 = PLAIN
auth_mechanisms.2 = AMQPLAIN
```

> [!TIP]
> ANONYMOUS 危险在于它配合默认的 `anonymous_login_user` / `anonymous_login_pass`（两者默认都是 `guest`）会把匿名客户端直接变成 guest 用户。schema 里对这个配置键的注释写得很直接：*"For production environments, set this value to 'none'."*

## Virtual Host as Isolation Boundary

vhost 是 RabbitMQ 的**第一层访问控制边界**，也是逻辑上最硬的隔离单位。

连接建立时，服务端先检查用户能否访问目标 vhost，**没有任何权限就直接拒绝连接**：

```ini
[error] <0.1594.0> Error on AMQP connection <0.1594.0> (127.0.0.1:63793 -> 127.0.0.1:5672, user: 'user2', state: opening):

access to vhost '/' refused for user 'user2'
```

关键点，也是新手最常误解的一点：

- **同名队列/exchange 在不同 vhost 是完全不同的对象**。`/prod` 下的 `orders` 和 `/test` 下的 `orders` 是两个队列，两份数据，两套权限，互不可见。
- 新建的用户**默认没有任何权限**，所以"加完用户连不上"是预期行为——必须先 `set_permissions`。
- 同一 vhost 内的资源权限（configure/write/read）才决定你能不能声明、写入、读取具体的 exchange/queue。

所以 vhost 的划分应该是**按信任边界**，不是按业务模块。同一个团队的同一个服务，如果生产环境和测试环境应该互相看不见，就分成两个 vhost；如果两个团队共用一个服务且需要互相调用，混在一个 vhost 里靠资源正则区分——但这意味着一个团队的宽权限正则可能会误伤另一个团队的资源。**vhost 隔离比正则隔离可靠得多**，这是我在事故复盘里见过最多次的教训。

## Permission Model: configure / write / read

每个用户在每个 vhost 上有三条**正则表达式**权限：

| 权限 | 覆盖的操作 |
| --- | --- |
| `configure` | 创建、删除资源，或改变资源行为（声明 exchange/queue、绑定、设置参数） |
| `write` | 向资源注入消息（发布） |
| `read` | 从资源获取消息（消费） |

授权命令的参数顺序是 **configure、write、read**：

```bash
rabbitmqctl set_permissions --vhost "custom-vhost" "username" ".*" ".*" ".*"
```

> [!WARNING]
> 这个顺序不是 `configure/read/write`。写错了不会报错，只会静默地给错权限——表现为"应用明明配了 read 却消费不了"或"本该不能写却能写"。**权限写错方向的危害是双向的**，前者表现为功能不可用（好排查），后者表现为越权（难排查）。

查询：

```bash
rabbitmqctl list_permissions --vhost /
```

### Deny Notation

拒绝所有操作的写法是 `^$`（匹配空字符串，等价于匹配不到任何资源）：

```ini
configure = ^$
```

空字符串 `''` 是 `^$` 的**同义词**，限制效果完全一样。

### Built-in Resource Prefixes

- 内置的 AMQP 0-9-1 资源名以 `amq.` 为前缀
- 服务端生成的资源名以 `amq.gen` 为前缀（源码 `rabbit_amqqueue.erl` 里的 `<<"amq.gen">>`、`rabbit_amqp_session.erl` 里的 `rabbit_guid:binary(..., "amq.gen")`）

典型场景：只允许访问自动生成的队列和默认 exchange，其他一概拒绝：

```ini
^(amq\.gen.*|amq\.default)$
```

注意 `amq.default` 那个特例：**AMQP 0-9-1 的 default exchange 空名称在权限检查时被映射成 `amq.default`**（源码 `rabbit_access_control.erl` 里 `check_resource_access` 对 `kind = exchange, name = <<"">>` 的特殊分支）。所以要访问默认 exchange，权限正则里得写 `amq.default` 或能匹配它的模式。

### Combined Semantics of Permission Checks

单个操作常常需要**多条权限同时成立**，这是最容易漏配的地方。

**`queue.bind` 需要目标队列的 write + 源 exchange 的 read。** 源码 `rabbit_channel.erl` 的 `handle_method(#'queue.bind'{...})` 顺序是先 `check_write_permitted(DestinationName, ...)`（队列），再 `check_read_permitted(ExchangeName, ...)`（exchange）。

要允许用户把 `queueA` 绑到 `exchangeB`：

- write 正则要匹配 `queueA`
- read 正则要匹配 `exchangeB`

**发布到 topic exchange 时，topic 权限检查在普通资源权限之后。** 源码顺序是先 `check_write_permitted(ExchangeName, ...)`，之后才 `check_write_permitted_on_topics(...)`。**第一层拒绝就不会执行第二层**，这也意味着：如果普通 write 权限配错了，你永远不会看到 topic 权限报的错，会误以为是 topic 规则写错了。

## Permission Caching and Revocation

> [!WARNING]
> 这是本篇最需要记住的一条：**RabbitMQ 可能在 per-connection 或 per-channel 层面缓存授权检查结果，因此权限变更可能要等用户重连才完全生效。**

源码层面能看到的缓存粒度：

- **缓存是 channel 级的**：`rabbit_channel.erl` 用 Erlang process dictionary 缓存 `permission_cache` 和 `topic_permission_cache` 两个列表，每个最多缓存 **12** 条（`?MAX_PERMISSION_CACHE_SIZE`）。
- 缓存 key 是 `{Resource, Context, Permission}` 三元组，Context 变了才算新条目。
- **缓存只在三种情况下被清空**（`clear_permission_cache/0`）：
  1. 收到 `{update_user_state, User}` 消息——即客户端主动 `connection.update_secret` 换凭据时；
  2. channel 进入 hibernate 状态时；
  3. 定时 `tick` 到达时，**但仅当 `permission_cache_can_expire` 为真**。这个标志来自 `rabbit_access_control:permission_cache_can_expire/1`，它判断授权后端是否支持凭据过期——**内部后端 `rabbit_auth_backend_internal:expiry_timestamp/1` 永远返回 `never`，所以用内部后端时定时清缓存这条路是不走的**。

> [!WARNING]
> 最后这条是"权限改完不生效"的根因所在：**用默认的内部后端时，channel 的权限缓存没有自动过期机制**，一条 channel 只要不重建，它缓存过的授权结论就一直有效。定时 tick 的清理路径对内部后端是死路（`channel_tick_interval` 默认 60000 毫秒，但那个分支进不去）。
>
> 这也解释了官方那句 "changes to user permissions may only take effect when the user reconnects" —— 对内部后端而言，"reconnect"基本等价于"重建 channel"。

`clear_permissions` 的行为要特别注意：

```bash
rabbitmqctl clear_permissions --vhost "custom-vhost" "username"
```

**清除权限不会影响当前已打开的连接。** 官方原话是 "It is also possible to clear user permissions but that will not affect any currently open connections." 后续客户端操作最终会被拒绝，但具体延迟取决于授权后端（授权操作缓存的存在）。

**后果是什么**：安全上出问题时，"先 revoke 再观察"这个直觉动作在 RabbitMQ 上是不成立的——已经建立的连接还能继续读写一段时间。真正的即时撤销手段是关连接。

删除用户则会**立即关闭该用户的所有连接**：

```bash
rabbitmqctl delete_user 'username'
```

源码路径：`rabbit_auth_backend_internal:delete_user/2` 发出 `user_deleted` 事件 → `rabbit_connection_tracking` 捕获 → `shutdown_tracked_items(list_of_user(Username), ...)`，日志会打印 "Closing all connections for user '~ts' because the user is being deleted"。

> [!TIP]
> 排查"权限明明改了却不生效"的标准动作：先 `rabbitmqctl list_permissions --vhost <vhost>` 确认配置层面改对了，再让客户端**重连**。重连还不行，才是权限本身配错了。这个顺序能省掉大量无效排查。

## Passive Declaration

`passive=true` 的声明用于**探测资源是否存在**，不修改资源：

```ini
exchange.declare (passive=true)
queue.declare (passive=true)
```

**自 4.3.1 起，被动声明要求用户在目标资源上至少拥有 configure、write、read 三者之一**，任一满足即可。对比非被动声明只要求 `configure`（因为它会真的（重新）声明资源）。

源码确认了这个"任一权限"语义的存在与引入时间：`check_any_resource_access_permitted/3` 在 4.3.0 的 `rabbit_channel.erl` 里**不存在**（grep 命中 0 次），在 4.3.1 出现（命中 3 次），4.3.6 与 4.4.0 一致。

源码注释写得很清楚：

```erlang
%% Used by passive declare operations.
%%
%% For security reviews:
%% unlike regular declarations, passive declares require *any* permission on the
%% target resource (e.g. a queue) by design.
%% See rabbitmq/rabbitmq-server#16085 for context.
```

而且实现上刻意把 `configure` 放在**最后**尝试：

```erlang
%% 'configure' is intentionally tried last so that the error reported
%% in the negative/refusal case matches that of a regular declare.
Perms = [read, write, configure],
```

> [!TIP]
> 这个语义变化有实际影响，但**方向和直觉相反**：以前（4.3.0 及更早）被动声明要求的是 **`configure`** 权限——源码 `rabbit_channel.erl` 里那一分支调用的是 `check_configure_permitted(QueueName, User, AuthzContext)`。4.3.1 起改成"三者任一"，所以**门槛变低了**：一个只有 `read` 权限的账号，以前做被动声明会被拒，之后就能做了。
>
> 反过来说，**如果你有一个只需要"检查队列是否存在"的只读监控账号，它在 4.3.1 之前反而做不了这件事**（除非你给它 `configure`——那等于给了它创建和删除队列的能力）。升级后这类账号可以只给 `read` 就做存在性探测，这是个权限收敛的好机会。

## Topic Permissions

Topic 权限是**第二层授权**，面向以 topic 为结构组织的协议 —— 主要是 **MQTT** 和 **STOMP**。

### Check Ordering

发布到 topic exchange 会经过**两层**检查：

1. 普通资源权限（`basic.publish` 权限）
2. topic 权限（routing key 匹配）

**第一层拒绝则第二层根本不执行。** 源码印证：`rabbit_channel.erl` 的 `handle_method(#'basic.publish'{...})` 先做 `check_write_permitted(ExchangeName, ...)`，之后才在消息构造完成后做 `check_write_permitted_on_topics(...)`。

### AMQP 0-9-1 Consumers

在 AMQP 0-9-1 里，消费者是从队列消费的，所以**标准资源权限生效**，不走 topic 权限。

但有一条例外容易漏：**把 topic exchange 绑定到队列或 exchange 时，binding 使用的 routing key 也会被 topic 权限检查。** 源码 `handle_method(#'queue.bind'{...})` 在 `check_read_permitted(ExchangeName, ...)` 之后，额外调用 `check_read_permitted_on_topic(Exchange, User, RoutingKey, AuthzContext)`。

也就是说：一个 AMQP 0-9-1 用户虽然消费时不走 topic 权限，但**他创建的那条 binding 的 routing key 会被 topic 权限管**。

### Default Allow

使用默认授权后端时，**没有定义任何 topic 权限 = 全部放行**。官方原话：

> When default authorisation backend is used, publishing to a topic exchange or consuming from a topic is always authorised if no topic permissions are defined (which is the case on a fresh RabbitMQ installation).

所以 topic 授权是**可选的、需要主动开启**的功能。不配 = 不生效，不是"默认拒绝"。

### Variable Expansion

topic 权限正则支持变量展开，变量用 **`{name}` 花括号语法**（源码 `rabbit_auth_backend_internal.erl` 的 `expand_topic_permission/2`，`Opening = <<"{">>, Closing = <<"}">>`）：

| 变量 | 含义 |
| --- | --- |
| `{username}` | 连接用户名 |
| `{vhost}` | vhost 名 |
| `{client_id}` | 客户端 ID，**仅 MQTT 适用** |

`client_id` 只在 MQTT 下有效——源码 `rabbitmq_mqtt/src/rabbit_mqtt_processor.erl` 里构造 `AuthzCtx = #{<<"client_id">> => ClientId}`，而 AMQP 0-9-1 与 STOMP 走 `amqp_params_direct` 的 `variable_map`，不含 `client_id`。

展开示例：权限模式 `^{username}-.*`，用户 `tonyg` 连接后实际匹配 `^tonyg-.*`。

展开时变量值会经 `rabbit_re:escape/1` 转义，所以用户名里的正则元字符不会变成注入点。

> [!NOTE]
> 展开只发生在**内部默认授权后端**（`rabbit_auth_backend_internal`）里。换成自定义后端就没有这个行为。

### Custom Backend

自定义授权后端要支持 topic 授权，必须实现 `rabbit_auth_backend` behaviour 的 `check_topic_access/4` 回调。4.4.0 的 `rabbit_authz_backend.erl` 定义的回调：

```erlang
-callback check_topic_access(rabbit_types:auth_user(),
    rabbit_types:r(atom()),
    rabbit_types:permission_atom(),
    rabbit_types:topic_access_context()) ->
    boolean() | {false, Reason :: string()} | {'error', any()}.
```

同 behaviour 里还有 `user_login_authorization/2`、`check_vhost_access/3`、`check_resource_access/4`、`update_state/2`、`expiry_timestamp/1`，其中只有 `update_state/2` 是 `-optional_callbacks`。

## User Management

### Commands

```bash
# 添加用户（交互式，密码从 stdin 读，不进 shell 历史）
rabbitmqctl add_user "username"

# 直接传密码
rabbitmqctl add_user 'username' '2a55f70a841f18b97c3a7db939b7adc9e34a0f1b'

# 用预生成的哈希加用户
rabbitmqctl add_user --pre-hashed-password 'username' '{value produced by "rabbitmqctl hash_password"}'

# 改密码
rabbitmqctl change_password 'username' 'new-password'

# 列用户
rabbitmqctl list_users

# 删用户（会关闭该用户所有连接）
rabbitmqctl delete_user 'username'

# 生成哈希
rabbitmqctl hash_password "my-secret-password"
```

4.4.0 CLI 的准确 usage 签名（从 `deps/rabbitmq_cli/lib/rabbitmq/cli/ctl/commands/` 逐个核对）：

| 命令 | usage 字符串 |
| --- | --- |
| `add_user` | `add_user <username> [<password>] [<password_hash> --pre-hashed-password]` |
| `change_password` | `change_password <username> <password>` |
| `list_users` | `list_users [--no-table-headers]` |
| `delete_user` | `delete_user <username>` |
| `hash_password` | `hash_password <cleartext_password> [--hashing-algorithm <algorithm>]` |
| `set_permissions` | `set_permissions [--vhost <vhost>] <username> <conf> <write> <read>` |
| `clear_permissions` | `clear_permissions [--vhost <vhost>] <username>` |
| `list_permissions` | `list_permissions [--vhost <vhost>] [--no-table-headers]` |
| `set_user_tags` | `set_user_tags <username> <tag> [...]` |
| `close_all_user_connections` | `close_all_user_connections <username> <explanation>` |
| `authenticate_user` | `authenticate_user <username> <password>` |

几个细节：

- `hash_password` 的 `--hashing-algorithm` 支持 `sha256` / `sha512` / `md5` / `pbkdf2_sha256`，**默认走 `rabbit_password.hash/1`**（即服务器当前配置的算法）。
- `close_all_user_connections` 需要**两个**位置参数，第二个是给客户端看的关闭原因，会被记入日志并返回给客户端。别漏。
- `add_user` 支持**空密码**（源码注释："blank passwords are currently allowed, they make sense e.g. when a user only authenticates using X.509 certificates"）。此时该用户不能用密码登录。凭据强度要求交给 `rabbit_credential_validation` 校验器，不靠 CLI。
- `authenticate_user` 成功退出码 0，失败非 0。适合拿来做健康检查。

### Shell Escaping Pitfall

**在命令行传密码时，shell 会解释一批字符：`!`、`?`、`&`、`^`、`"`、`'`、`*`、`~` 等。** 转义不当的后果不是报错，而是 **CLI 收到一个和预期不同的密码值**——于是"明明设了这个密码却登不上"。

规避方式：

- 用交互式 `add_user "username"`，密码走 stdin，不经过 shell 解析。
- 用 `--pre-hashed-password` 传哈希，避开明文。
- 通过 HTTP API（不经 shell）创建用户时不存在这个限制，但换成编程语言时又会有各自的转义规则。

官方推荐的密码形态：**40 到 100 字符的字母数字串，符号只留极少量**（例如 `:`、`=`）。既避开转义坑，也避开很多客户端/配置文件的字符集限制。

> [!TIP]
> 顺带一个坑：`rabbitmq.conf` 里 **`#` 是注释符**，所以生成的凭据里不能包含 `#`，否则 `#` 之后的内容会被当注释吃掉。

### The guest User

`guest` 需要同时理解三件事，缺一条就会判断错：

**一、它默认存在，且默认拥有全权限。** 首次启动时（数据库未初始化/被重置/被删除）RabbitMQ 会创建 vhost `/`、用户 `guest`、密码 `guest`，并授予对 `/` 的全权限 `.*`（configure/write/read 三个正则都是 `.*`）。

**二、它默认只能从 loopback 连接。** `loopback_users` 的默认值是 `[<<"guest">>]`，4.4.0 源码 `deps/rabbit/Makefile` 里写死为这一条。检查逻辑在 `rabbit_access_control.erl` 的 `check_user_loopback/2`：连接源地址是 loopback 就放行，否则看用户名是否在 `loopback_users` 列表里。**这个限制对所有协议生效**，不只是 AMQP。

远程连 guest 的日志：

```ini
[error] <0.918.0> PLAIN login refused: user 'guest' can only connect via localhost
```

**三、导入 definitions 启动则不创建默认用户。** 源码 `rabbit.erl` 的 `maybe_insert_default_data/0` 明确判断：

```erlang
NoDefsToImport = not rabbit_definitions:has_configured_definitions_to_load(),
case rabbit_db:needs_default_data() andalso NoDefsToImport of
```

即"有 definitions 要加载"就不播种默认 vhost 和默认用户。官方文档同口径：*"If a blank node imports definitions on boot, this default user will not be created."*

### Disabling the loopback Restriction

```ini
# DANGER ZONE!

# allowing remote connections for default user is highly discouraged

# as it dramatically decreases the security of the cluster. Delete the default user

# instead and create a new one with generated secure credentials, or use JWT tokens,

# or x.509 certificates for clients to authenticate themselves

loopback_users = none
```

`loopback_users = none` 会**清空整个 loopback 限制列表**，不只是放开 guest。这不是"给 guest 开个例外"，是"取消所有 loopback 限制"。

官方对此的态度没有任何余地："Allowing remote connections for the default user with well known default credentials is very strongly recommended against: doing so will dramatically reduce the security of the cluster."

**正确做法是删掉 guest，建一个凭据是随机生成的新用户**，或者改用 JWT / X.509 客户端证书。

## Tags and Management Access

用户除了资源权限，还有 **tags**。目前**只有 management UI / HTTP API 的访问由 tag 控制**。

```bash
rabbitmqctl set_user_tags 'username' 'administrator'
```

**新用户默认没有任何 tag。** 这是个安全默认值——建完用户忘了设 tag，它连管理界面都进不去。

> [!NOTE]
> 但注意区分两种"默认用户"：**用 `add_user` 新建的用户**没有 tag；而**首次启动播种的那个 `default_user`（默认就是 `guest`）** 是带 `administrator` tag 的——4.4.0 的 `deps/rabbit/Makefile` 里写死了 `{default_user_tags, [administrator]}`，schema 里也有 `default_user_tags.<tag>` 这个键可覆盖。
>
> 也就是说，**默认配置下 `guest` 同时拥有 `/` vhost 的全资源权限和管理界面的 administrator 权限**，只是被 `loopback_users` 挡在 localhost 之外。一旦有人为了图方便设了 `loopback_users = none`，等于把一个完整的管理员账号暴露到了网络上。

| Tag | 能力 |
| --- | --- |
| 无 | "No access to the management plugin" |
| `management` | 消息协议能做的都能做；此外能列出可登录的 vhost、查看这些 vhost 里的队列/exchange/binding、关闭自己的 channel/connection、查看自己所有 vhost 的全局统计 |
| `policymaker` | `management` 全部 + 管理可登录 vhost 的 policy 与 parameter |
| `monitoring` | `management` 全部 + 列出所有 vhost（含消息协议访问不到的）、查看其他用户的连接与 channel、查看节点级数据（内存、集群状态）、查看真正全局的跨 vhost 统计 |
| `administrator` | `policymaker` + `monitoring` 全部 + 创建删除 vhost、管理用户、管理权限、关闭其他用户的连接 |

官方提示：由于能力是嵌套的（administrator ⊃ policymaker ⊃ monitoring ⊃ management），**一个用户通常最多只需要一个 tag**。

> [!IMPORTANT]
> **Tag 和资源权限不可互相替代。** 官方原话：
>
> > Normal RabbitMQ permissions to resources still apply to monitors and administrators; just because a user is a monitor or administrator does not grant them full access to exchanges, queues and bindings through the management plugin or other means.
>
> 配套的还有一句：
>
> > All users can only list objects within the virtual hosts they have any permissions for.
>
> 也就是说：一个带 `administrator` tag 的账号，如果对某 vhost 没有资源权限，它在管理界面里**看不到那个 vhost 里的队列和 exchange**。反过来，一个没有任何 tag 但有全资源权限的账号，能收发消息却打不开管理界面。这两套正交，排查时别混。

## Default User and Default Vhost

`default_user` / `default_pass` **只在空白节点首次启动时生效**：

```ini
# default is "guest", and its access is limited to localhost only.

default_user = a-user

# default is "guest"

default_pass = 768a852ed69ce916fa7faa278c962de3e4275e5f
```

关键约束：**这两个值必须在首次启动前就写好**。数据库一旦初始化，改配置不会重新播种，也不会删除已存在的用户。

凭据支持加密配置值（参见 RabbitMQ 的 Configuration Value Encryption）。

### default_permissions Family

除了 `default_users.<user>.*`，4.4.0 的 schema 里还有一组**独立的** `default_permissions.*` 键，用来设定默认用户在默认 vhost 上的三条权限正则：

```ini
default_permissions.configure = .*
default_permissions.write = .*
default_permissions.read = .*
```

它和 `default_users.<user>.*` 是**两套机制，不要混**：

| | `default_permissions.*` | `default_users.<user>.*` |
| --- | --- | --- |
| 作用对象 | `default_user` 这一个用户 | 你指定的任意用户名 |
| 生效时机 | 空白节点首次启动播种默认用户时 | **每次新建 vhost** 时 |
| 权限维度 | configure / write / read 三条 | configure / write / read 三条 |
| 额外能力 | 无 | 可配 `tags`、`vhost_pattern` |

> [!WARNING]
> **官方文档把这两族键拆在两个不同的页面上，很容易只看到一半**：
>
> - `default_permissions.*` 只出现在**配置参考页** `/docs/configure`（原文："Permissions to assign to the default user when creating it."，默认值三者都是 `.*`）；
> - `default_users.<user>.*` 只出现在 **access-control 页** `/docs/access-control`。
>
> 两边都不完整，所以单看任一页都会漏。
>
> 顺带一个从源码看出来的**顺序陷阱**：`rabbit.schema` 的 translation 把三个值组装成 `[Configure, Read, Write]`，而 `rabbit.erl` 的解构写的是 `{ok, [DefaultConfigurePerm, DefaultWritePerm, DefaultReadPerm]}`——**第 2、3 位是反的**。默认值三者都是 `.*` 所以看不出来，但只要你把 read 和 write 设成不同的正则，**实际生效的 read 和 write 就是对调的**。这个不一致在 4.3.6、4.4.0 以及上游 main 分支都存在（三个版本我都逐一比对过）。如果你依赖 `default_permissions` 做差异化授权，**先在小环境验证实际生效值**，别假设配置即所得。

### default_users Family

`default_users.<user>.*` 用于**在新建 vhost 时自动给指定用户配权限和 tag**：

```ini
# Grants user 'monitoring' access to all virtual hosts

# with certain permissions

default_users.monitoring.vhost_pattern = .*

default_users.monitoring.tags = monitoring

default_users.monitoring.configure = ^$

default_users.monitoring.read = .*

default_users.monitoring.write = ^$
```

含义拆开看：

- `vhost_pattern = .*` —— 新建 vhost 名匹配 `.*` 时应用下面这套
- `tags = monitoring` —— 给该用户打 `monitoring` tag
- `configure = ^$` —— 不能创建/删除/改资源
- `read = .*` —— 能读所有资源
- `write = ^$` —— 不能写

这就是一个典型的只读监控服务账号：能看所有队列指标，但完全不能碰业务数据。

官方明确限定用途：*"This feature should only be used to grant virtual host access to service accounts (such as monitoring and automation tools)."*

> [!NOTE]
> **注意这五个键在官方 access-control 文档里只列了五个：`vhost_pattern` / `tags` / `configure` / `read` / `write`。但 4.4.0 的 schema 里还有第六个 `default_users.$name.password`，源码也确实消费它**（`rabbit_db_vhost_defaults.erl` 的 `list_users/1` 里 `proplists:get_value(<<"password">>, Ss, undefined)`，非 undefined 时塞进 `#{password => ...}`）。文档没写，schema 有。这是文档落后于实现的一例——用它给新建 vhost 里的服务账号设初始密码是可行的，但属于未文档化行为，升级时留意。

> [!WARNING]
> `default_users` **不是**普通业务用户的权限管理手段。它只在**新建 vhost** 的那一刻生效一次，不会同步已有 vhost，也不会在用户被删后自动清理。把它当"权限模板"用可以，当"权限来源"用会出事。

## Credential Rotation

### Normal Rotation

三步，顺序不能乱：

```bash
# 1. 改密码
rabbitmqctl change_password 'username' 'new-generated-password'

# 2. 关掉该用户的现有连接
rabbitmqctl close_all_user_connections 'username' 'password rotated'

# 3. 让应用能拿到新凭据并重连（例如重启应用）
```

**第 2 步是很多人漏掉的。** 只改密码不关连接的话，旧连接会一直活着——而因为授权检查有缓存，你甚至不能靠"等权限失效"来解决问题。必须显式关。

### Suspected Credential Leak

怀疑凭据泄漏时，官方给的完整流程是五步：

1. 评估用户权限，导出完整集群 definitions
2. 删除用户（**撤销访问并关闭使用该凭据的所有现有连接**）
3. 用新生成的密码重新添加用户
4. 重新授予该用户此前拥有的所有 virtual host 权限
5. 确保应用能发现新凭据并重新连接

导出 definitions：

```bash
rabbitmqctl export_definitions /path/to/definitions.file.json
```

导出内容**包含密码哈希和哈希算法信息**，属于敏感信息，要当 secret 管理。

用 LDAP 等外部后端时，用户账户由 RabbitMQ 外部系统管理，轮换流程在外部执行。

> [!TIP]
> 第 4 步"重新授予此前拥有的所有权限"是最容易出错的一步——重建用户后它对**所有 vhost 都是零权限**，如果只补了常用的那一个，跨 vhost 的调用会在重启后集体失败，而且表现为"连接被拒"而不是"权限不足"，容易误判成认证问题。**先从导出的 definitions 里把 permissions 段捞出来当 checklist**，比凭记忆补要可靠得多。

## Definitions and Boot-time Import

在启动时导入 definitions 是推荐的预配置方式。

```ini
# Does not require management plugin to be enabled.

definitions.import_backend = local_filesystem

definitions.local.path = /path/to/definitions/defs.json
```

从 URL 导入（需 HTTPS）：

```ini
definitions.import_backend = https

definitions.https.url = https://your-endpoint.example.com/rabbitmq.definitions.json

# client-side TLS options for definition import

definitions.tls.versions.1 = tlsv1.2
```

避免重复导入：

```ini
definitions.skip_if_unchanged = true
```

几个必须知道的语义：

- **导入发生在插件激活之后**，所以插件相关的 definitions（如动态 Shovel、自定义 exchange 类型）也能在启动时导入。
- **导入的文件不会覆盖 broker 里已有的东西。**
- **空白节点导入 definitions 时，不会创建默认 vhost 和默认用户。** 官方建议生产环境用唯一凭据的新用户；测试环境可以在 definitions 文件里手动写一个等价的默认用户。
- 集群里**每个节点都会导入**，导致重复劳动。文件小无所谓，文件大时推荐在集群组建完成后再导入。

definitions 文件里用户段的实际结构（官方给的示例）：

```javascript
    "users": [

        {

            "name": "guest",

            "password_hash": "9/1i+jKFRpbTRV1PtRnzFFYibT3cEpP92JeZ8YKGtflf4e/u",

            "tags": ["administrator"]

        }

    ],

    "permissions":[

        {

            "user":"guest",

            "vhost":"/",

            "configure":".*",

            "read":".*",

            "write":".*"}

    ],
```

注意 `password_hash` 用的是 `password_hash_2` 那种带盐的格式，且导出的哈希值不应外泄。

## HTTP API for Users and Permissions

管理插件提供的 HTTP API（`/api` 前缀）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/users` | 列出**内部数据存储中**的用户（用 LDAP 时不含 LDAP 用户） |
| `GET` | `/api/users/{user}` | 单个用户信息 |
| `PUT` | `/api/users/{user}` | 创建/更新用户，需要 `password` 或 `password_hash` 之一 |
| `DELETE` | `/api/users/{user}` | 删除用户 |
| `GET` | `/api/users/without-permissions` | 列出无任何权限、可安全删除的用户 |
| `POST` | `/api/users/bulk-delete` | body `{"users": ["user1","user2"]}` |
| `GET` | `/api/user-limits` / `/api/user-limits/{user}` | 查询连接/信道限制 |
| `PUT` | `/api/user-limits/{user}/{name}` | body `{"value": 100}`，name 如 `max-connections` / `max-channels` |
| `PUT` | `/api/permissions/{vhost}/{user}` | body `{"configure":".*","write":".*","read":".*"}`，**三个键都必须给** |
| `GET` | `/api/permissions` | 集群全部权限 |
| `DELETE` | `/api/permissions/{vhost}/{user}` | 撤销权限 |
| `PUT` | `/api/topic-permissions/{vhost}/{user}` | body `{"exchange":"amq.topic","write":"^a","read":".*","configure":".*"}`，**四个键都必填** |
| `GET` | `/api/topic-permissions` | 集群全部 topic 权限 |
| `DELETE` | `/api/topic-permissions/{vhost}/{user}` | 撤销 topic 权限 |

`PUT /api/users/{user}` 的 body 示例：

```json
{"password":"secret","tags":"administrator"}
```

或用哈希：

```json
{"password_hash":"2lmoth8l4H0DViLaK9Fxi6l9ds8=", "tags":["administrator"]}
```

两个都不给的话，该用户无法用密码登录（但可以走客户端证书等机制）。把 `password_hash` 设成空字符串 `""` 则明确禁止密码登录。

`tags` 官方说明是 "The `tags` key takes a comma-separated list of tags."，但示例里也用了数组形式 `["administrator"]`，两种都见过。

## Breaking Changes in 4.4.0

这两个改动直接打在认证链路上，**升级前不处理，升级后起不来或者登不上**。

### Stricter OpenID Connect Discovery Validation

4.4.0 起，OIDC discovery 响应按 **OpenID Connect Discovery 1.0 §4.3** 规范校验。官方 release note 原话：

> OpenID Connect discovery responses are now validated more strictly. A deployment whose identity provider serves non-HTTPS (`http://`) endpoints, or whose `issuer` claim does not match the discovery endpoint used to retrieve it, will fail discovery validation after the upgrade.

两种情况会导致升级后 discovery 校验失败：

1. IdP 提供的端点不是 HTTPS
2. `issuer` claim 与用于获取 discovery 文档的 endpoint 不匹配

**已知受害者：Cloud Foundry UAA**。官方明确说明：

> This is known to affect Cloud Foundry UAA, whose issuer is its token endpoint URL rather than a prefix of its discovery endpoint.

UAA 的 issuer 是它的 token endpoint URL，而不是 discovery endpoint 的前缀——这在 OIDC 规范下不合规，但 UAA 是既有实现。

**升级前**对不合规 IdP 设置：

```ini
auth_oauth2.discovery.verify_issuer = false
auth_oauth2.discovery.verify_https_endpoints = false
```

两个键在 4.4.0 的 `rabbitmq_auth_backend_oauth2.schema` 里都存在，**默认都是 `true`**，schema 原文注释：

```erlang
%% Require the jwks_uri, token_endpoint, authorization_endpoint and
%% end_session_endpoint of a discovered OpenID configuration to use the https
%% scheme. Set to false only when your identity provider's discovery document
%% uses http, for example in a development or test environment.
%%
%% {verify_https_endpoints, true},
```

```erlang
%% Verify that the issuer discovered in an OpenID configuration document is
%% present, uses the https scheme, and matches the discovery endpoint used to
%% retrieve it, per OpenID Connect Discovery 1.0, Section 4.3. Set to false
%% only when your identity provider's issuer does not follow this
%% convention.
%%
%% {verify_issuer, true},
```

4.4.0 还支持按 provider 粒度覆盖：`auth_oauth2.oauth_providers.$name.discovery.verify_issuer` 与 `auth_oauth2.oauth_providers.$name.discovery.verify_https_endpoints`。

> [!NOTE]
> **这两个键目前还没有出现在官方 OAuth 2 文档页上**——我把 4.4 的 `/docs/oauth2` 和 `/docs/next/oauth2` 都抓下来全文搜过，`verify_issuer` 和 `verify_https_endpoints` 两个字符串的出现次数都是 **0**。它们的权威来源目前只有 4.4.0 的 `rabbitmq_auth_backend_oauth2.schema` 原文注释（上面已完整引用）和 4.4.0 release note。所以别指望在文档页上搜到这两个键，要搜就搜 schema。

> [!IMPORTANT]
> **这两个键是 4.4.0 新增的，4.3.x 的 schema 里没有。** 我逐个版本比对过 `rabbitmq_auth_backend_oauth2.schema`：`verify_issuer` 和 `verify_https_endpoints` 在 4.3.6 里出现次数是 **0**，在 4.4.0 里才是 4（两个键各两处：全局 + per-provider）。
>
> 所以**不要试图"先在 4.3.x 上把开关设成 false 再升级"**——4.3.x 的 schema 里没有这两个键，把它们写进 4.3.x 的 `rabbitmq.conf` 属于配置了 schema 不认识的键，风险是节点起不来而不是"提前关掉校验"。**正确顺序是：先升到 4.4.0，如果 discovery 校验失败，再把开关加上并重启。**

### hash_password Endpoint Replaced

**`GET /api/auth/hash_password/{password}` 被 `POST /api/auth/hash_password` 取代。** 官方 release note：

> `GET /api/auth/hash_password/{password}` was replaced with another endpoint, `POST /api/auth/hash_password`. The new endpoint consumes a POST body with JSON document with one key `{"password": "..."}`

新端点：

```http
POST /api/auth/hash_password
Content-Type: application/json

{"password": "my-secret-password"}
```

4.4.0 源码 `deps/rabbitmq_management/src/rabbit_mgmt_wm_hash_password.erl` 确认了实现细节：

```erlang
allowed_methods(ReqData, Context) ->
    {[<<"GET">>, <<"POST">>, <<"OPTIONS">>], ReqData, Context}.
```

```erlang
%% Passing the password as a URL path segment risked leaking it via
%% access logs, proxies, and browser or shell history. GET now only
%% points callers at the POST replacement.
to_json(ReqData, Context) ->
    rabbit_mgmt_util:not_found(
      <<"Passing the password in the URL is no longer supported. "
        "Use POST /auth/hash_password with a JSON body "
        "{\"password\": \"...\"} instead.">>,
      ReqData, Context).
```

注意几个点：

- **GET 路径没有被直接删掉，而是保留为"拒绝并给出指引"**：`to_json` 返回 not_found，消息里明确告诉调用方改用 POST。所以旧的 GET 调用**不会静默失效**，而是收到一条说明性错误——这点对排查很友好。
- 改动动机是**避免密码泄漏到 access log / 代理 / 浏览器或 shell 历史**。GET 把密码放在 URL 路径里，这些地方都会记录 URL。
- POST 的 body 里 `password` 键**必须存在**——`rabbit_mgmt_util:with_decode([password], ...)` 对缺失的键返回 `{error, [{key_missing, password}]}`，最终是 400；若 `password` 存在但不是字符串，则报 `<<"password must be a string">>`。
- 该端点要求 **administrator 权限**（`rabbit_mgmt_util:is_authorized_admin/2`）。

4.3.6 的同一文件还是老样子——`allowed_methods` 只有 `GET` 和 `OPTIONS`，直接从 URL 路径取密码：

```erlang
allowed_methods(ReqData, Context) ->
    {[<<"GET">>, <<"OPTIONS">>], ReqData, Context}.
```

> [!WARNING]
> **如果你有自动化脚本在调 `GET /api/auth/hash_password/{password}`（比如密码轮换脚本、配置生成器），升级后这一段会挂。** 这是 HTTP API 客户端需要主动适配的破坏性变更，属于 4.4.0 升级 checklist 上必须排查的一项。改法就一行：换成 POST + JSON body。

## Security Baseline Checklist

上线/整改前逐条过：

- [ ] **删除 `guest` 用户**：`rabbitmqctl delete_user 'guest'`。至少也要改密码 + 保持 loopback 限制。**不要**用 `loopback_users = none` 来图省事。
- [ ] **生产用强随机密码**：40–100 字符字母数字 + 少量符号（`:` `=` 即可），避开 shell 元字符和 `#`。
- [ ] **启用 TLS**：`PLAIN` 机制在明文链路上等于把密码广播出去。
- [ ] **移除 `ANONYMOUS`**：从 `auth_mechanisms` 里去掉，并确认 `anonymous_login_user` / `anonymous_login_pass` 不指向 `guest`。
- [ ] **最小权限正则**：默认 `.*` 是最懒的写法。用 `^$` 明确拒绝不需要的维度，只对确实需要的资源开 `.*`。
- [ ] **权限改完验证**：用 `rabbitmqctl list_permissions --vhost <vhost>` 核对，并让客户端重连——权限缓存不会自己失效。
- [ ] **vhost 按信任边界划分**，而不是按业务模块。
- [ ] **监控账号用 `default_users.<user>.*` 模板 + `monitoring` tag + `^$` 权限**，别给它 `.*`。
- [ ] **定期导出 definitions 备份**（`rabbitmqctl export_definitions`），把 permissions 段当轮换时的 checklist。
- [ ] **审计**：4.4.0 的事件系统会发出 `user.created` / `user.deleted` / `user.password.changed` / `user.password.cleared` / `user.tags.set` / `permission.created` / `permission.deleted` 等事件（`rabbit_event_consumer.erl` 中的 `key/1` 映射），可以接到日志或审计管道。
- [ ] **升级 4.4.0 前**：处理 OIDC discovery 校验开关 + 改掉 `GET /api/auth/hash_password` 调用。

## Notes on Limits

官方 access-control 与 management 文档**都没有给出**以下限制的具体数值：

- 单个 vhost 最多能配多少条权限记录
- 单个用户最多能关联多少个 vhost
- 权限正则表达式的最大长度
- 用户总数上限

本文因此**不编造**这些数字。若确实需要评估规模，请以压测和官方 issue tracker 为准，不要拿"限制是 N"当设计依据。

源码层面能观察到的、确定的实现细节（可作为容量规划的参考下限，但**不是官方承诺的上限**）：

- channel 级的权限缓存每个 channel 各 12 条（`permission_cache` 与 `topic_permission_cache` 各 12 条）。
- `set_permissions` / `clear_permissions` 都是**单 vhost 单用户粒度**的操作，批量处理需要脚本循环。

## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [AMQP 0-9-1 协议结构与工作流（Spring AMQP 侧）](/docs/CS/Framework/Spring/AMQP.md)
- [安全（通用）](/docs/CS/Security/Security.md)

## References

- https://www.rabbitmq.com/docs/access-control
- https://www.rabbitmq.com/docs/configure
- https://www.rabbitmq.com/docs/definitions
- https://www.rabbitmq.com/docs/management
- https://www.rabbitmq.com/docs/http-api-reference
- https://www.rabbitmq.com/docs/oauth2
- https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.4.0
