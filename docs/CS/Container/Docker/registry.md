## Introduction

registry 是存储与分发容器镜像的服务。公共默认是 **Docker Hub**，私有可自托管。`docker pull` / `push` 走的是 **OCI Distribution Spec**（原 Docker Registry HTTP API V2）——它定义了镜像如何按内容寻址、如何被拉取与推送。

本篇聚焦"registry 本身"：协议模型、pull/push 流程、私有部署（registry:2 / Distribution）、鉴权、垃圾回收、镜像加速器，以及和生产级方案（Harbor）的关系。镜像内部结构见 [Docker 镜像](/docs/CS/Container/Docker/image.md)，供应链签名见 [Docker 安全](/docs/CS/Container/Docker/security.md)。

## 协议与资源模型

Distribution Spec 围绕三类资源：

- **blob**：层（layer）与 config 的二进制内容，按 `sha256:` 摘要做**内容寻址**，天然去重（同层只存一份）。
- **manifest**：描述一个镜像——指向 config blob + 若干 layer blob 的摘要；有两种形态：
  - `image manifest`（schema 2）：单架构镜像。
  - `manifest list` / `image index`：多架构索引，列出多个单架构 manifest（见 [buildx](/docs/CS/Container/Docker/buildx.md) 的多平台构建）。
- **tag**：指向 manifest 的**可变**指针；`digest`（`sha256:...`）才是**不可变**引用。生产部署应钉 digest 而非 tag。

鉴权采用 **Bearer Token** 流程：客户端请求受保护资源时，registry 返回 `WWW-Authenticate: Bearer realm=...service=...scope=...`，客户端去 `realm` 换 token 再带回去；匿名公开镜像则无需 token。简单私有场景也可用 HTTP basic auth（htpasswd）。

## 拉取与推送流程

**pull**（`docker pull registry.example.com/lib/app:1.4`）：

```
GET /v2/<name>/manifests/1.4            → 拿到 manifest（含 config + layers 摘要）
GET /v2/<name>/blobs/<config-digest>    → config（镜像配置、环境变量、入口）
GET /v2/<name>/blobs/<layer-digest>     → 逐层下载（按摘要去重、可并行）
```

**push** 反向：先 `POST` / `PUT` 各 blob（支持整体或分块 chunked 上传），最后 `PUT` manifest。失败重试靠摘要幂等。

相关命令：

```bash
docker login registry.example.com
docker pull  registry.example.com/lib/app:1.4
docker push registry.example.com/lib/app:1.4
docker logout
docker manifest inspect registry.example.com/lib/app:1.4   # 看多平台 manifest list
```

## 私有 registry（registry:2 / Distribution）

官方镜像 `registry:2` 背后是 **Distribution** 项目（已捐给 CNCF，Apache-2.0），也是 Docker Hub、GHCR 等的参考实现。新版还有 `registry:3` 线（Distribution 3.1.x）。

最小可运行：

```bash
docker run -d -p 5000:5000 --name registry \
  -v registry-data:/var/lib/registry \
  registry:2
docker tag myapp localhost:5000/myapp:1.4
docker push localhost:5000/myapp:1.4
curl -s localhost:5000/v2/_catalog        # 列仓库
curl -s localhost:5000/v2/myapp/tags/list  # 列 tag
```

**配置**（`config.yml` 或环境变量）：

- 持久化：挂卷到 `/var/lib/registry`，否则容器删了镜像全没。
- 鉴权：生产必须加。`htpasswd` basic auth 最简单——`REGISTRY_AUTH=htpasswd` + `REGISTRY_AUTH_HTPASSWD_PATH` + `REGISTRY_AUTH_HTPASSWD_REALM`；更正式用 token auth 服务或把 registry 放在带 TLS 的反向代理后。
- **非 localhost 默认要求 HTTPS**：否则 Docker 拒绝，除非在 `daemon.json` 加 `insecure-registries`（不推荐生产）。

**删除与垃圾回收**：删除 tag 只是摘指针，**底层 blob 仍占盘**，需单独 GC：

```bash
# 先允许删除
export REGISTRY_STORAGE_DELETE_ENABLED=true
# 触发 GC（停止写入期间跑，回收无引用的 blob）
docker exec registry bin/registry garbage-collect /etc/docker/registry/config.yml
```

## pull-through 缓存 / 镜像加速器

公共 registry（尤其 Docker Hub）对匿名/低频账号有 **pull rate limit**，CI 多任务同 IP 很容易 `toomanyrequests`。解法是在 `daemon.json` 指一个 **mirror**（pull-through cache）：

```json
{
  "registry-mirrors": ["https://mirror.internal.example.com"]
}
```

镜像首次被请求时由 mirror 去上游拉、缓存、回源；之后同层全部本地命中，既绕开限流又提速。`registry:2` 自身也能配成 mirror 模式；Harbor、Artifactory 或云厂商镜像也都行。另一半解是**给 CI  pull 加上登录凭据**，因为登录账号的限额比匿名高。

## Harbor 与生产级方案

裸 `registry:2` 只是个存储引擎，**没有 RBAC、UI、扫描、签名、复制**。生产要这些就上 **Harbor**（VMware 开源，底层也用 Distribution）：

- 项目级 RBAC 与审计；
- 镜像漏洞扫描；
- 复制（replication）与 pull-through 代理；
- 与 [安全](/docs/CS/Container/Docker/security.md) 的签名（cosign / Notary）打通做供应链准入。

跨 registry 搬运镜像用 **skopeo / crane**（不依赖 Docker daemon，直接走 Distribution API）。

## 供应链衔接

- 部署时**钉 digest**（`image@sha256:...`）而非 tag，避免"同名不同内容"。
- 配合签名与扫描：推送后做 `cosign sign` / 扫描，准入时校验（详见 [安全](/docs/CS/Container/Docker/security.md)）。
- 镜像仓库是供应链信任链的一环：私有化 + 访问控制 + 签名校验，才能把"任意人都可拉任意镜像"的风险关上。

## 排障

| 现象 | 原因 / 处理 |
| :-- | :-- |
| `toomanyrequests: rate limit` | Docker Hub 限流 → 配 `registry-mirrors` + 登录 CI 账号 |
| `x509: certificate signed by unknown authority` | registry 自签证书未被 daemon 信任 → 加 CA 或用 `insecure-registries`（仅测试） |
| `http: server gave HTTP response to HTTPS client` | 没开 TLS 又没声明 insecure → 同上 |
| 删了 tag 磁盘没变小 | 删的是指针，blob 还在 → 跑 `garbage-collect` |
| 多平台镜像只看到单架构 | 用 `docker manifest inspect` 确认 index 是否含目标架构 |

## Links

- [Docker 镜像](/docs/CS/Container/Docker/image.md)
- [Docker 安全](/docs/CS/Container/Docker/security.md)
- [Docker 构建 buildx](/docs/CS/Container/Docker/buildx.md)
- [Docker 存储](/docs/CS/Container/Docker/storage.md)

## References

1. [OCI Distribution Specification](https://github.com/opencontainers/distribution-spec)
2. [Deploy a registry (registry:2)](https://docs.docker.com/registry/deploying/)
3. [Registry garbage collection](https://docs.docker.com/registry/garbage-collection/)
4. [Docker Hub rate limits](https://docs.docker.com/docker-hub/rate-limits/)
