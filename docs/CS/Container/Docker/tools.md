## Introduction

拿到一个已经跑起来的容器或一个现成的镜像，最常见的需求是"反推"出它是怎么启动的、Dockerfile 长什么样。容器往往是 compose、k8s 或前任同事留下的，没有启动命令时，靠 `docker inspect` 逐字段拼太慢，下面这些工具就是干这个的。

按作用对象分两类：**从容器反推启动命令**（runlike）、**从镜像反推 Dockerfile**（whaler / dfimage / dedockify）。另有若干镜像分析与审计工具。

## runlike：还原 docker run

[runlike](https://github.com/lavie/runlike) 用于从**运行中的容器**反推出它的 `docker run` 命令。容器往往不是手工起的，而是 compose、k8s 或前任同事留下的，没有启动命令时，runlike 可以还原出端口、挂载、环境变量、restart 策略等完整启动参数。

```shell
# 用完即弃的别名方式，无需安装
alias runlike="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  assaflavie/runlike"

# 或 pip 安装
pip install runlike
```

```shell
# 输出可直接复制执行的 docker run 命令
runlike <container_name_or_id>

# -p 将参数拆成多行，可读性更好
runlike -p <container_name_or_id>

# 只输出命令而不执行
runlike --no-name <container>
```

本质上 runlike 就是把 `docker inspect` 的输出（HostConfig、Config、NetworkSettings 等）解析后拼装回 CLI 参数，因此它只能还原 Docker 记录下来的信息，无法还原构建时的意图——比如 `ENTRYPOINT` 里那些镜像自带的默认值会混进来，build args 更是不可能知道。

## 从镜像还原 Dockerfile

### Whaler

[Whaler](https://github.com/P3GLEG/Whaler) 是一个 Go 程序，用于从**镜像**中还原 Dockerfile 及各层信息。镜像的每一层 metadata 里本来就带有 `created_by`（对应构建时执行的指令），Whaler 把这些元数据逆序解析，重建出 Dockerfile。它还会顺带：

- 搜索各层中潜在的密钥/敏感文件（审计利器）
- 提取 `ADD`/`COPY` 指令加入的文件
- 展示端口、运行用户、环境变量等信息

```shell
# 最简单的方式：以镜像方式运行，会自动 pull 目标镜像
alias whaler="docker run -t --rm -v /var/run/docker.sock:/var/run/docker.sock:ro \
  pegleg/whaler"

whaler -sV=1.36 nginx:latest

# -x 将各层导出到当前目录，-v 打印全部细节
whaler -x -v nginx:latest

# 源码编译
go get -u github.com/P3GLEG/Whaler && cd $GOPATH/src/github.com/P3GLEG/Whaler && go build .
```

输出示例（还原出的 Dockerfile + 层信息）：

```plain
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y nginx
COPY ./index.html /var/www/html/
ENV NGINX_PORT=80
EXPOSE 80
```

### Dedockify

配套的还有 [Dedockify](https://github.com/mrhavens/Dedockify)，思路相同、更轻量：

```shell
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  mrhavens/dedockify <image_id>
```

### dfimage

[dfimage](https://github.com/stephensek/rancher-tools/tree/master/dfimage) 也是同类工具，从镜像元数据反推 Dockerfile：

```shell
alias dfimage="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  alpine/dfimage"
dfimage -sV=1.36 <image>
```

注意还原出的 Dockerfile 是**近似等价**的：`MAINTAINER`/`LABEL` 可能丢失，构建期用到的 build args、build context 里的临时文件无法恢复。它适合审计、学习和排查"这个镜像里到底装了什么"，而不是官方构建脚本。

## 逐层分析镜像

| 工具 | 干什么 | 一句话场景 |
| :-- | :-- | :-- |
| `docker history --no-trunc` | 看每层的完整指令 | 不装任何工具的"穷人版 whaler"，先看它往往就够了 |
| [dive](https://github.com/wagoodman/dive) | 交互式逐层浏览文件系统差异 | 分析镜像体积、找可精简的层、看有没有误拷大文件 |
| [docker scout](https://docs.docker.com/scout/) | CVE 扫描 + 修复建议 | CI 里的安全门禁 |
| [trivy](https://github.com/aquasecurity/trivy) | 镜像/文件系统/依赖漏洞扫描 | 覆盖面最广的开源扫描器 |
| [grype](https://github.com/anchore/grype) | 漏洞扫描 | 常与 syft 生成 SBOM 配套 |
| [syft](https://github.com/anchore/syft) | 生成 SBOM（CycloneDX/SPDX） | 供应链清单 |
| [cosign](https://github.com/sigstore/cosign) | 镜像签名与验签 | Docker Content Trust 的现代替代 |
| [hadolint](https://github.com/hadolint/hadolint) | Dockerfile 静态检查 | 把最佳实践变成 lint 规则 |
| [docker-slim](https://github.com/slimtoolkit/slim) | 自动裁剪镜像 | 只保留运行时真正用到的文件 |

```shell
dive nginx:1.27-alpine
docker scout cves --only-severity critical,high app:v1
syft app:v1 -o spdx-json > sbom.json
hadolint Dockerfile
```

## 运行时侧的工具

| 工具 | 干什么 |
| :-- | :-- |
| [ctop](https://github.com/bcicen/ctop) | 终端里看容器指标，比 `docker stats` 好看 |
| [lazydocker](https://github.com/jesseduffield/lazydocker) | 终端 UI 管理容器/镜像/日志/卷 |
| [cadvisor](https://github.com/google/cadvisor) | 容器指标导出，Prometheus 生态的采集端 |
| [sysdig](https://github.com/draios/sysdig) / [falco](https://github.com/falcojs/falco) | 系统调用级内省与运行时安全检测 |
| [nerdctl](https://github.com/containerd/nerdctl) | 直接操作 [containerd](/docs/CS/Container/k8s/containerd.md) 的 Docker 兼容 CLI |
| [skopeo](https://github.com/containers/skopeo) | 不拉镜像就 inspect / 在 registry 之间搬运 |

## 对比表

| 工具 | 作用对象 | 输出 | 典型场景 |
| ---- | -------- | ---- | -------- |
| runlike | 运行中的容器 | `docker run` 命令 | 容器迁移、重建 compose 配置 |
| Whaler / Dedockify / dfimage | 镜像 | Dockerfile + 层信息 | 镜像审计、学习他人构建方式 |
| `docker history --no-trunc` | 镜像 | 层指令列表 | 快速粗查，不想拉工具时 |
| dive | 镜像 | 交互式逐层浏览文件系统 | 分析镜像体积、寻找可精简层 |
| trivy / grype / scout | 镜像 | CVE 清单 | 安全门禁 |

## Security Notes

这类工具都以 `docker.sock` 挂载运行，等价于给容器 root 级权限访问 Docker daemon，只应在可信环境使用——风险与原理见 [Docker 安全](/docs/CS/Container/Docker/security.md)。反推出来的配置里可能包含敏感的环境变量和密钥，注意脱敏；审计第三方镜像时，建议在隔离的构建机上跑，不要在承载生产的宿主上跑。

## Links

- [Docker 镜像](/docs/CS/Container/Docker/image.md)
- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)

## References

1. [runlike](https://github.com/lavie/runlike)
2. [Whaler](https://github.com/P3GLEG/Whaler)
3. [Dedockify](https://github.com/mrhavens/Dedockify)
4. [dive](https://github.com/wagoodman/dive)
5. [Docker Scout](https://docs.docker.com/scout/)
