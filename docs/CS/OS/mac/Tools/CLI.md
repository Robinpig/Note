## Introduction

macOS 自带的命令行来自 FreeBSD 与 NetBSD 的用户态，不是 GNU coreutils。这一句话解释了绝大多数"我在 Linux 上这么写没问题"的困惑：同名命令、不同实现、参数分歧，而且**分歧往往不是报错，而是给出另一个正确结果**——`sed -i` 那类直接报错的反而是好情况。

判断一个命令当前用的是哪一版，先看它在哪：

```shell
$ which -a sed
/usr/bin/sed                      # BSD，系统自带
/opt/homebrew/opt/gnu-sed/bin/sed # GNU，Homebrew 装的
```

> [!NOTE]
>
> 本文所有行为均在 **macOS 15.3.1 / Darwin 24.3.0（Apple M1 Pro）** 上实测。命令一律用绝对路径调用，因为本机 PATH 里混入了第三方 shim（toybox），`which sed` 可能先命中非系统版本——这本身也是"同名命令不同实现"的一个现实例子。

## BSD and GNU Divergence

下表是实际会踩到的分歧，左列是 Linux 习惯写法，右列是 macOS 上的等效写法：

| 场景 | GNU 写法（Linux） | BSD 写法（macOS） | 说明 |
| :--- | :--- | :--- | :--- |
| 原地替换 | `sed -i 's/a/b/' f` | `sed -i '' 's/a/b/' f` | BSD 的 `-i` **必须**带后缀参数，`''` 表示不备份 |
| 相对日期 | `date -d '1 day ago'` | `date -v-1d` | `-v` 是 BSD 独有，GNU 的 `-d` 不存在 |
| 文件属性 | `stat -c '%s %n' f` | `stat -f '%z %N' f` | `-c`/`-f` 格式串互不通用 |
| 正则引擎 | `grep -P 'a.c'` | 不支持 | BSD grep 无 PCRE，报 `invalid option -- P` |
| 符号链接 | `readlink -f f` | `readlink -f f` | 本机 15.3.1 实测支持，但历史版本没有 `-f`，跨版本脚本别依赖 |
| 删除分隔符 | `xargs -d '\n'` | 不支持 `-d` | 用 `xargs -0` 配合 `find -print0` |
| 文本工具 | `awk`（gawk） | `awk`（one true awk） | 本机 `/usr/bin/awk` 报 `awk version 20200816`，是 Kernighan 的 awk |

最容易误判的是 `sed -i`。GNU 下 `-i` 的参数可选，BSD 下它是必填的"备份文件后缀"。当你写 `sed -i 's/a/b/' f` 时，BSD 把 `s/a/b/` 当成后缀、把 `f` 当成 sed 脚本，于是报出一个看起来毫不相干的错：

```shell
$ /usr/bin/sed -i 's/hello/world/' t.txt
sed: 1: "t.txt": undefined label 't.txt'
```

`undefined label` 是 sed 在抱怨脚本里的 `t` 命令（跳转标签）没有定义——它把 `t.txt` 当脚本解析了。看到这个报错就说明 `-i` 缺了后缀参数。

`awk` 的分歧更隐蔽：macOS 自带的是 one true awk（`awk version 20200816`），不支持 gawk 的 `gensub()`、`asort()`、`PROCINFO` 等扩展。写了 gawk 特性的脚本在 macOS 上会静默产出空结果而不是报错。

## Missing GNU Tools

一批 Linux 上的常用命令在 macOS 上根本不存在，不是参数不同而是命令本身缺失：

| 缺失 | 作用 | macOS 替代 |
| :--- | :--- | :--- |
| `timeout` | 限时运行 | `perl -e 'alarm shift; exec @ARGV'`，或装 coreutils |
| `free` | 内存概览 | `vm_stat`、`memory_pressure`、`top` |
| `vmstat` | 系统统计 | `vm_stat`、`iostat`、`sar` 需另装 |
| `watch` | 周期执行 | `while :; do ...; sleep 1; done` |
| `nproc` | CPU 数 | `sysctl -n hw.ncpu` |
| `strace` | 系统调用跟踪 | `dtruss`（见 [dtruss](/docs/CS/OS/mac/Tools/dtruss.md)） |
| `realpath` | 规范化路径 | `readlink -f`（较新版本可用） |

反过来的方向也值得记住：macOS 在现代版本里补了 GNU 风格的校验和命令，`/sbin/sha256sum` 与 `/sbin/md5sum` 都存在（本机实测），不必一律改用 `shasum`。

> [!WARNING]
>
> `/usr/bin/iotop` 虽然存在，但它**是一个 DTrace 包装脚本**（`iotop - display top disk I/O events by process. Written using DTrace`）。SIP 开启时它和其他 DTrace 工具一起失效，报 `DTrace requires additional privileges`。`/usr/bin` 下这批脚本（`iotop`、`iosnoop`、`opensnoop`、`execsnoop`、`rwsnoop`、`errinfo`、`dtruss`）全是同一套机制，详见 [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)。

## macOS Native Commands

另一半是别处没有的命令。它们大多桥接了 macOS 的框架层（Spotlight、launchd、configd、ColorSync、Quartz），是"用命令行操作 GUI 系统"的入口：

| 命令 | 作用 | 典型用法 |
| :--- | :--- | :--- |
| `pbcopy` / `pbpaste` | 读写系统剪贴板 | `cat f \| pbcopy`、`pbpaste > f` |
| `open` | 用默认程序打开 | `open .`（Finder）、`open -a Safari url`、`open -e f`（TextEdit） |
| `mdfind` | 查 Spotlight 索引 | `mdfind "kMDItemKind == 'Folder'"`、`mdfind -onlyin ~/Docs kw` |
| `mdls` | 读文件元数据 | `mdls -name kMDItemWhereFroms f`（看下载来源） |
| `defaults` | 读写 plist 偏好 | `defaults read com.apple.finder`、`defaults write ... -bool true` |
| `scutil` | 查系统配置数据库 | `scutil --dns`、`scutil --get HostName` |
| `networksetup` | 网络配置 | `networksetup -listallnetworkservices` |
| `diskutil` | 磁盘与 APFS | `diskutil apfs list`、`diskutil verifyVolume /` |
| `pkgutil` | 安装包收据 | `pkgutil --pkgs`、`pkgutil --files <pkg>` |
| `caffeinate` | 阻止睡眠 | `caffeinate -d`（防显示器睡眠）、`caffeinate -i`（防系统空闲睡眠） |
| `pmset` | 电源与睡眠策略 | `pmset -g custom`、`pmset -g assertions`（看谁在阻止睡眠） |
| `say` / `textutil` | 语音合成 / 文本格式转换 | `say -v Tingting "文本"`、`textutil -convert html f.docx` |
| `qlmanage` | Quick Look 缩略图 | `qlmanage -t -s 512 f` |
| `sips` | 图像处理 | `sips -Z 1024 img.jpg`（等比缩放） |
| `screencapture` | 截图 | `screencapture -x shot.png` |
| `system_profiler` | 硬件与软件清单 | `system_profiler SPHardwareDataType` |
| `ditto` | 复制（保留 HFS 元数据与资源分支） | `ditto src dst`，打包时优于 `cp` |
| `hdiutil` | 磁盘映像 | `hdiutil create/attach/verify` |
| `xattr` | 扩展属性 | `xattr -d com.apple.quarantine app`（解除隔离标记） |

`xattr -d com.apple.quarantine` 值得单独记住：从网上下载的 app 被 Gatekeeper 拦下时，系统实际是给文件打了 quarantine 扩展属性，删掉它就能绕过那次拦截——但绕过前先确认文件来源可信，见 [Security](/docs/CS/OS/mac/Security.md)。

## Mach-O Binary Tools

查看与修改 Mach-O 二进制的工具也自成一组，在其他 Unix 上没有对应物：

| 命令 | 作用 |
| :--- | :--- |
| `otool` | 查看 Mach-O 结构：`otool -L app`（动态库依赖）、`otool -tv`（反汇编）、`otool -hv`（头部） |
| `install_name_tool` | 改写 dylib 的路径（`@rpath`、`@loader_path`） |
| `codesign` | 签名与验证：`codesign -dv --verbose=4 app`、`codesign -d --entitlements - app` |
| `spctl` | Gatekeeper 评估：`spctl --status`、`spctl -a -vv app` |
| `security` | 钥匙串与证书：`security find-certificate`、`security list-keychains` |
| `lipo` | 通用二进制：`lipo -archs app`、`lipo -thin arm64 app -o app_arm64` |
| `dwarfdump` | 读 DWARF 调试信息 |

`otool -L` 与 Linux 的 `ldd` 地位相当，但 Mach-O 用的是 `@rpath` 这类安装路径而不是 `LD_LIBRARY_PATH`，改依赖要靠 `install_name_tool` 而不是环境变量——这是 macOS 上动态库问题的常见误判点。

## Shell Built-in Pitfalls

`echo` 的行为在 `/bin/sh`（此处是 bash 3.2 的 POSIX 模式）与 zsh 下不同，`-n`/`-e` 的解释方式不一致；需要可移植输出时用 `printf`。`script` 录制、`nohup` 与 `&` 的组合在 macOS 上与 Linux 一致，但 `ulimit -n` 的默认值较小（256，远低于 Linux 常见的 1024），高并发服务要显式调大：

```shell
launchctl limit maxfiles      # 本机实测：maxfiles  256  unlimited
sudo launchctl limit maxfiles 65536 200000   # 改系统级上限
```

本机 `/bin/sh` 实测是 `GNU bash, version 3.2.57(1)-release (arm64-apple-darwin24)`——因为 GPLv3 的授权问题 Apple 从未升级自带 bash，需要 bash 4/5 特性只能从 Homebrew 装。

## Links

- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [DTrace](/docs/CS/OS/mac/Tools/DTrace.md)
- [Homebrew](/docs/CS/OS/mac/Tools/Homebrew.md)
- [Terminal](/docs/CS/OS/mac/Tools/Terminal.md)
- [Virtual Memory](/docs/CS/OS/mac/Virtual_Memory.md)
- [Security](/docs/CS/OS/mac/Security.md)

## References

1. [BSD General Commands Manual — Apple](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/)
2. [GNU Coreutils Manual](https://www.gnu.org/software/coreutils/manual/coreutils.html)
