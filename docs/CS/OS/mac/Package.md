## Introduction

macOS 的软件分发和 Linux 的包管理器生态完全不是一回事。Linux 上"安装"是把文件写进 `/usr` 树、由包管理器记账；macOS 上"安装"多数时候是**把一个目录拖进 `/Applications`**。没有集中的包数据库，卸载靠用户自己删，残留靠用户自己找。

这套体系有三层需要分清：**物理形态**（`.app` / `.pkg` / `.dmg`）、**信任机制**（代码签名 + 公证）、**分发渠道**（App Store / 独立分发 / Homebrew）。搞混它们最常见的后果是"装了但打不开"或"删了但没删干净"。

## Bundle Structure

`.app` 不是可执行文件，是**目录**（bundle）。Finder 把它显示成单个图标，右键"显示包内容"才能进去：

```
MyApp.app/
└── Contents/
    ├── Info.plist            # bundle 标识、版本、主类、权限声明
    ├── MacOS/MyApp           # 真正的 Mach-O 可执行文件
    ├── Resources/            # 图标、nib、本地化资源
    ├── Frameworks/           # 自带的 dylib / framework
    └── XPCServices/          # 权限隔离子进程（见 Service Management）
```

这个结构带来的两个直接后果：

- 命令行里要跑它，路径必须写到 `Contents/MacOS/<名字>`，或者用 `open -a MyApp`；
- 拷贝 bundle 必须保留结构与扩展属性（`cp -R`，别用 `cp -r` 丢资源分支），否则签名或资源会坏。

## Distribution Formats

| 形态 | 本质 | 典型安装方式 | 适用场景 |
| :--- | :--- | :--- | :--- |
| `.app` | 目录 bundle | 拖到 `/Applications` | 绝大多数应用 |
| `.pkg` | 安装包（xar 归档 + 安装脚本） | 双击走安装器，可写系统目录 | 需要 root、装 LaunchDaemon、装 kext |
| `.dmg` | 磁盘映像 | 挂载后把里面的 `.app` 拖出去 | `.app` 的分发载体，带签名与压缩 |
| `.zip` | 压缩归档 | 解压 | 小工具；不保留部分扩展属性 |

`.dmg` 本身不是安装格式，它是**容器**：把 `.app` 放进去，附一份使用说明背景图，压缩并签名后分发。用户挂载 dmg、拖 app、推出 dmg，全程没有"安装器"参与。

`.pkg` 才是有安装逻辑的那个：它可以包含 pre/post install 脚本、可以指定目标卷、可以往 `/Library` 写东西。因为能执行任意脚本，它也是 Gatekeeper 重点检查的对象。

## Code Signing and Notarization

签名决定"这个 app 是谁的、有没有被改过"；公证决定"Apple 有没有扫过它"。两者是独立的，前者本地可做，后者必须联网提交给 Apple。

```shell
# 查看签名
codesign -dv --verbose=4 /Applications/MyApp.app

# 严格校验（会真的检查资源与 sealed 资源）
codesign -vv --deep --strict /Applications/MyApp.app

# 让 Gatekeeper 评估能不能启动
spctl -a -vv /Applications/MyApp.app
```

签名的内部结构是 Mach-O 里嵌入的 CodeDirectory（各页哈希）+ CMS 签名 blob + entitlements（权限声明）。刚才那条 `codesign -dv` 输出的 `flags=0x2000(library-validation)` 就是其中一项：启用库校验后，注入外部 dylib 会直接被拒。

公证流程（Xcode 13 起推荐 `notarytool`，旧的 `altool` 已废弃）：

```shell
xcrun notarytool submit MyApp.zip --keychain-profile "AC_PASSWORD" --wait
xcrun stapler staple MyApp.app        # 把票据钉到 app 上，离线也能验证
```

不公证的后果不是"装不上"，而是首次启动时 Gatekeeper 拦截，需要用户去"系统设置 → 隐私与安全性"手动允许（详见 [Security](/docs/CS/OS/mac/Security.md)）。

## App Store vs Direct Distribution

| 渠道 | 沙箱要求 | 公证 | 更新机制 | 分成 |
| :--- | :--- | :--- | :--- | :--- |
| Mac App Store | 必须开启 App Sandbox | Apple 审核时完成 | App Store 统一更新 | Apple 抽成 |
| 独立分发 | 无强制 | 开发者自行提交 | 应用内更新（Sparkle 等） | 无 |
| Homebrew | 不适用（命令行） | 不适用 | `brew upgrade` | 无 |

沙箱（App Sandbox）是 App Store 的硬门槛：它把 app 限制在自己的容器里，访问用户文件、网络、硬件都要 entitlement 声明。独立分发的应用不受此限，这也是很多开发工具不上架 App Store 的原因——它们需要的能力沙箱给不了。

## Homebrew

Homebrew 是 macOS 上事实标准的命令行包管理器，把"Formula（Ruby 描述的构建脚本）+ prefix 目录 + 版本化 Cellar"这套模型搬到了 macOS 上（安装与多架构共存的细节见 [Software](/docs/CS/OS/mac/Tools/Software.md)）。

它与前述体系的关系是：**Homebrew 装的不是 bundle，而是 Unix 风格的树**。Apple Silicon 上装在 `/opt/homebrew`（Apple 定这个路径就是为了不和 Intel 的 `/usr/local` 打架），Intel 上是 `/usr/local`。这也解释了为什么 Apple Silicon 上跑某些脚本会找不到 `/usr/local/bin` 里的东西。

## Uninstalling

没有集中的包数据库，意味着卸载是"手工活"。拖到废纸篓只删了 `/Applications/MyApp.app`，残留通常在这几处：

```shell
~/Library/Application Support/<App>/
~/Library/Preferences/<bundle-id>.plist
~/Library/Caches/<bundle-id>/
~/Library/LaunchAgents/<bundle-id>.plist
/Library/LaunchDaemons/<bundle-id>.plist
```

如果当初是用 `.pkg` 装的，可以先用 `pkgutil` 反查它到底装了什么：

```shell
pkgutil --pkgs                          # 列出已登记的 pkg（本机 133 个）
pkgutil --files <package-id>            # 该 pkg 装了哪些文件
pkgutil --forget <package-id>           # 从登记库里移除（不删文件）
```

`pkgutil --files` 给出完整清单，按清单删才是干净的卸载；删完再 `--forget` 清掉登记记录。

## Commands

| 命令 | 用途 |
| :--- | :--- |
| `pkgutil --pkgs` / `--files` / `--forget` | 查询与清理 pkg 安装记录 |
| `codesign -dv` / `-vv` | 查看 / 校验签名 |
| `spctl -a -vv` | 让 Gatekeeper 评估 |
| `xcrun notarytool submit` / `stapler staple` | 提交公证、钉票据 |
| `lipo -archs <binary>` | 查看可执行文件的架构（系统二进制是 `x86_64 arm64e`） |
| `open -a <App>` | 从命令行启动 app |
| `installer -pkg <pkg> -target /` | 命令行安装 pkg（自动化场景） |

## Links

- [MacOS](/docs/CS/OS/mac/mac.md)
- [Security](/docs/CS/OS/mac/Security.md)
- [Service Management](/docs/CS/OS/mac/Service_Management.md)
- [Development](/docs/CS/OS/mac/Development.md)
- [Mac Tools](/docs/CS/OS/mac/Tools/Tools.md)
- [Software](/docs/CS/OS/mac/Tools/Software.md)

## References

1. [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
2. [Code Signing Guide](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Introduction/Introduction.html)
3. [Bundle Programming Guide](https://developer.apple.com/library/archive/documentation/CoreFoundation/Conceptual/CFBundles/Introduction/Introduction.html)
4. [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
5. [Distributing your app for beta testing and releases](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)
