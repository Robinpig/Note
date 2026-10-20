## Introduction

launchd 是 macOS 的 PID 1，也是它唯一的 init 系统。它不只是"启动服务"，而是把 Unix 上散落在多个组件里的活全部收拢到一个进程：系统引导、常驻服务（daemon）、登录会话服务（agent）、按需启动（XPC 与 socket activation）、以及定时任务——`init`、`inetd`、`cron`、`at`、`xinetd` 在 macOS 上的角色都由它扮演。

这带来两个与 Linux 直觉的落差。第一，**进程不是"被某个父进程启动"，而是"被某个域里的 launchd 启动"**，父进程退了它还在。第二，**配置是声明式的 plist**，不是可执行脚本：你描述"什么条件下启动、失败后怎么办"，launchd 负责维持这个状态。

## Domains

服务属于**域**（domain），域决定它的可见范围与生命周期归属。这是理解 launchd 的第一件事——同一个 plist 放进不同域，行为完全不同。

| 域 | 目标描述符 | 含义 | 何时存在 |
| :--- | :--- | :--- | :--- |
| system | `system` | 系统级，root 身份的 launchd | 开机即有，关机才结束 |
| user | `user/<uid>` | 用户的非 GUI 会话 | ssh 登录等场景 |
| gui | `gui/<uid>` | 用户的图形登录会话 | 用户登录后 |
| login | `login/<asid>` | 单个登录会话 | 会话期间 |
| session | `session/<asid>` | 会话内作用域 | 会话期间 |

```shell
$ launchctl print system
system = {
        type = system
        handle = 0
        active count = 902
        service count = 422
        active service count = 144
        ...
}

$ launchctl print gui/$UID
gui/501 = {
        type = login
        handle = 100018
        active count = 441
        service count = 440
        active service count = 194
```

注意 `service count` 与 `active service count` 的差别：绝大多数服务是**按需**的，注册了但没在跑。这是 launchd 与 sysvinit 类系统最本质的区别。

## Service Types

| 类型 | 运行身份 | 何时启动 | 典型用途 |
| :--- | :--- | :--- | :--- |
| LaunchDaemon | root（或指定 UserName） | 开机，无用户会话 | Web 服务、系统监控、更新器 |
| LaunchAgent | 登录用户 | 用户登录后 | 菜单栏 App、同步客户端 |
| XPC Service | 宿主进程身份 | 被 `NSXPCConnection` 连接时按需启动 | app 内部的权限隔离子进程 |
| Login Item | 用户 | 登录后由登录项启动 | 用户级自启动 app |

XPC Service 值得单独说：它是 app bundle 内 `Contents/XPCServices/*.xpc` 的子进程，**由 launchd 托管但只对宿主可见**，崩溃不影响宿主，常用来把"需要权限但不需要信任的代码"（网络解析、图像处理）隔离到独立沙箱里。

## plist Locations

plist 放哪决定它属于哪个域。四个标准位置加上用户目录：

```shell
/System/Library/LaunchDaemons     # Apple 的系统 daemon（SIP 保护）
/System/Library/LaunchAgents      # Apple 的系统 agent
/Library/LaunchDaemons            # 第三方 daemon，root 身份
/Library/LaunchAgents             # 第三方 agent，所有登录用户
~/Library/LaunchAgents            # 当前用户自己的 agent
```

## Modern launchctl

`launchctl` 的命令模型在 macOS 10.11 前后换过一次：早年是 `load` / `unload` / `start` / `stop` 这套**操作文件**的动词，后来改成**操作域与服务目标**的子命令。老教程里的命令现在要么失效，要么直接给警告：

```shell
$ launchctl load /Library/LaunchDaemons/com.example.daemon.plist
Warning: Expecting a LaunchAgents path since the command was ran as user. Got LaunchDaemons instead.
`launchctl bootstrap` is a recommended alternative.
```

新旧对照：

| 旧写法 | 现在该用 | 说明 |
| :--- | :--- | :--- |
| `launchctl load <plist>` | `launchctl bootstrap <domain> <plist>` | 把服务注册进域 |
| `launchctl unload <plist>` | `launchctl bootout <domain>/<service>` | 注销并终止 |
| `launchctl start <label>` | `launchctl kickstart <domain>/<service>` | 立即启动（哪怕按需） |
| `launchctl stop <label>` | `launchctl kill SIGTERM <domain>/<service>` | 终止但不注销 |
| `launchctl list` | `launchctl print <domain>` | 查看域内服务与状态 |
| — | `launchctl enable` / `disable` | 覆盖 plist 的 Disabled 键，持久化生效 |

服务目标描述符的完整形式是 `<domain>/<service-label>`：

```shell
launchctl bootstrap system /Library/LaunchDaemons/com.example.daemon.plist
launchctl kickstart -k system/com.example.daemon      # -k 表示已运行时先杀掉再起
launchctl bootout gui/$UID/com.example.agent
launchctl print gui/$UID/com.example.agent
launchctl blame system/com.apple.cfprefsd.xpc.daemon  # 为什么它现在在跑
```

> [!NOTE]
>
> `launchctl kickstart` 里的 `-k`（kill 后重启）是最常用的组合：改完 plist 后要让它生效，正确顺序是 `bootout` → `bootstrap` → `kickstart -k`，而不是只重启进程——因为重启进程不会重读 plist。

## Scheduling

launchd 用 plist 键替代 cron：

| 键 | 含义 |
| :--- | :--- |
| `RunAtLoad` | 注册时立即启动一次 |
| `KeepAlive` | 退出后自动重启（`true` 或按条件字典） |
| `StartInterval` | 每隔 N 秒启动一次 |
| `StartCalendarInterval` | 按日历时间触发（等价于 cron 的 `分 时 日 月 周`） |
| `WatchPaths` | 监听路径变化触发 |
| `ThrottleInterval` | 失败重启的最小间隔，防崩溃风暴 |

`cron` 在 macOS 上仍然可用（`/usr/sbin/cron` 由 launchd 拉起），但 Apple 已把它标记为遗留方案，新东西应该用 `StartCalendarInterval`。

## Debugging

排查一个服务"为什么没起来"或"为什么一直重启"，按这个顺序：

```shell
launchctl print gui/$UID/com.example.agent    # 状态、上次退出码、pid
launchctl blame system/com.example.daemon      # 它被谁、因什么原因拉起
log show --predicate 'process == "launchd"' --last 10m
```

几个高频坑：

- **退出码非 0 会被节流**：launchd 不会无限重启崩溃的服务，`ThrottleInterval` 默认 10 秒，表现为"第一次能用，之后就静默了"。去日志里看 `Service exited with abnormal code` 与节流提示。
- **launchd 的工作目录与 PATH 都很干净**：plist 里没写 `WorkingDirectory` 就是 `/`，`PATH` 也不继承 shell 的。脚本里引用 `brew` 装的绝对路径（`/opt/homebrew/bin/...`）比依赖 PATH 可靠。
- **StandardOutPath / StandardErrorPath 默认是丢弃**：调试期一定要显式指向文件，否则看不到任何输出。
- **权限**：daemon 的 plist 与它启动的可执行文件必须归 root 且非 group/other 可写，否则 launchd 拒绝加载。

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Darwin](/docs/CS/OS/mac/Darwin.md)
- [Boot](/docs/CS/OS/mac/Boot.md)
- [Package](/docs/CS/OS/mac/Package.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)

## References

1. [launchd.info](http://www.launchd.info/)
2. [Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
3. [launchd.plist man page](https://www.unix.com/man-page/osx/5/launchd.plist/)
4. [XPC — Apple Developer Documentation](https://developer.apple.com/documentation/xpc)
