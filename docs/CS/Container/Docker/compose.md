## Introduction

[Docker Compose](https://docs.docker.com/compose/) 用一份 YAML 描述"一组容器怎么起"，解决的是**单机多容器**的编排问题：把 `docker run` 那一长串参数沉淀成文件，一条命令拉起整栈。

Compose 把所管理的容器分为三层：**工程（project）→ 服务（service）→ 容器（container）**。project 是默认以目录名命名的一组资源；service 是"一类容器"的声明（镜像、环境变量、网络）；container 是实际跑起来的实例（一个 service 可以 `scale` 出多个）。

```plain
project: myapp/
  ├── service: web      → container: myapp-web-1
  ├── service: api      → container: myapp-api-1, myapp-api-2（scale=2）
  └── service: db       → container: myapp-db-1
```

> [!NOTE]
> 命令是 `docker compose`（空格，Go 写的 CLI 插件，v2 / v5 线，最新 5.6.0 于 2026-10-02），不是老的 `docker-compose`（连字符，Python 写的 v1，2023 年 6 月后停止支持）。v1 已 EOL，脚本里见到连字符形式就该改。

每个目录下有且仅有一个 `docker-compose.yml` 文件用于描述 Docker 配置（配合可选的 override 文件）。

## 一份最小可用配置

```yaml
services:
  web:
    image: nginx:1.27-alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      api:
        condition: service_healthy
    networks:
      - frontend

  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    environment:
      - DATABASE_URL=postgres://app:secret@db:5432/app
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 15s
    restart: unless-stopped
    networks:
      - frontend
      - backend

  db:
    image: postgres:17
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: secret
    networks:
      - backend

volumes:
  pgdata:

networks:
  frontend:
  backend:
```

几个默认值值得记住：Compose 会为每个 project 建一个默认网络，service 之间**用 service 名互相 DNS 解析**（所以上面的 `db:5432` 能通）；volume 与 network 名会带 project 前缀。

## 关键字段与陷阱

### depends_on 不等于"准备好"

`depends_on` 只保证**启动顺序**，不保证依赖服务已经可用。想等就绪必须配合 `condition`：

- `service_started`（默认）：容器起来了就算
- `service_healthy`：等对方的 `healthcheck` 变 healthy（所以依赖方必须定义 healthcheck；健康检查机制见 [容器生命周期](/docs/CS/Container/Docker/lifecycle.md)）
- `service_completed_successfully`：等对方正常退出（一次性任务，如数据库迁移）

更彻底的方案是在应用里做重试，Compose 层面做不到完美等待。

### restart 策略

| 值 | 行为 |
| :-- | :-- |
| `no` | 不自动重启（默认） |
| `always` | 总是重启，daemon 启动时也会拉起 |
| `unless-stopped` | 总是重启，但手动 stop 过的不再拉起 |
| `on-failure[:N]` | 非 0 退出码才重启，可限次数 |

注意 Compose 的 restart 是**容器级**策略，跟 [K8s](/docs/CS/Container/k8s/K8s.md) 的 Pod 重启语义不同（重启策略、信号与优雅终止的完整机制见 [容器生命周期](/docs/CS/Container/Docker/lifecycle.md)）。

### deploy 字段单机上不生效

`deploy.replicas`、`deploy.resources.limits` 这些只在 **Swarm** 或 Compose 的某些集成下有意义。单机 `docker compose up` 想限资源，用 `mem_limit` / `cpus`，或干脆交给 [Docker 性能](/docs/CS/Container/Docker/performance.md) 里那套 `docker run` 参数。

### 环境变量与 .env

- `environment`：直接写进容器
- `env_file`：从文件读取，适合把配置与编排分离
- 同级目录下的 `.env` 文件用于**变量替换**（`${TAG:-latest}`），不是自动注入容器

```yaml
services:
  api:
    image: "myapp/api:${TAG:-latest}"
    env_file:
      - ./api.env
```

### 覆盖与 profile

- `docker-compose.override.yml` 会被自动合并，通常用来放开发期配置（挂源码、开调试端口）
- `-f` 可显式指定多个文件，后面的覆盖前面的
- `profiles:` 让某些 service 默认不启动（如 debug 工具），用 `--profile debug` 启用

```shell
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 常用命令

```shell
docker compose up -d              # 后台拉起全栈（缺失的镜像先 build/pull）
docker compose up -d --build      # 强制重建镜像
docker compose ps                 # 看本 project 的容器
docker compose logs -f api        # 跟某个服务的日志
docker compose logs -f --tail=100
docker compose exec api sh        # 进容器
docker compose down               # 停并删容器、网络（默认保留 volume）
docker compose down -v            # 连 volume 一起删（数据会没）
docker compose config             # 打印合并后的最终配置，排错首选
docker compose top                # 各容器进程
docker compose restart api        # 重启单个服务
docker compose pull && docker compose up -d   # 更新镜像后重启
```

`docker compose config` 是排查"变量没生效 / 缩进不对 / 覆盖没合并"的第一工具，它输出的就是 Compose 真正理解的配置。

### 一次性与服务内命令

```shell
docker compose run --rm api sh            # 一次性命令，跑完即删（默认忽略 ports）
docker compose run --rm -e DEBUG=1 api pytest
docker compose wait api                   # 等某服务 healthy/running 再继续（脚本用）
docker compose cp api:/var/log/app.log ./local.log   # 拷文件进出容器
```

`pull_policy`（服务级）控制 `up` 时是否拉新镜像：`always` / `missing` / `never` / `build`。

## 与 Dockerfile 的关系

| 维度 | Dockerfile | Compose |
| :-- | :-- | :-- |
| 描述对象 | 一个镜像怎么构建 | 一组容器怎么运行 |
| 主要指令 | `FROM`/`RUN`/`COPY` | `services`/`networks`/`volumes` |
| 产物 | 镜像 | 运行中的容器栈 |

`build:` 字段把两者接起来：构建上下文、Dockerfile 路径、build args、target 阶段都能在这里指定，见 [Dockerfile](/docs/CS/Container/Docker/Dockerfile.md)。

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
      target: production      # 多阶段构建里选最终阶段
      args:
        - VERSION=1.2.3
    image: myapp/api:1.2.3    # 同时指定时，构建出的镜像打这个 tag
```

## 进阶字段与开发闭环

### networks 进阶

默认网络之外，可声明自定义网络的细节：

```yaml
networks:
  backend:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: br-backend
    ipam:
      config:
        - subnet: 172.28.0.0/16
services:
  api:
    networks:
      backend:
        aliases: [api-svc]         # 同网络内额外 DNS 名
        ipv4_address: 172.28.0.10  # 固定 IP（调试用）
  db:
    networks:
      - backend
```

外部已存在的网络用 `external: true`（不创建、只接入）：

```yaml
networks:
  existing_net:
    external: true
```

容器名解析仍是 service 名；`aliases` 给同网络内额外别名。

### volumes 进阶

volume 也能 `external`（接入已有卷）或指定 driver：

```yaml
volumes:
  pgdata:
    external: true                 # 不创建，接入同名已有卷
  ceph:
    driver: rexray
    driver_opts:
      size: "10Gi"
```

### secrets 与 configs

避免把密钥写进 `environment` 明文或 bake 进镜像，改为文件挂载（默认只读、0400，挂到 `/run/secrets/`）：

```yaml
services:
  api:
    secrets: [db_password, api_key]
    environment:
      DB_PASSWORD_FILE: /run/secrets/db_password   # 官方镜像认 *_FILE
secrets:
  db_password:
    file: ./secrets/db_password.txt
  api_key:
    file: ./secrets/api_key.txt
configs:
  nginx_conf:
    file: ./nginx/nginx.conf
```

PostgreSQL / MySQL 等官方镜像原生支持 `POSTGRES_PASSWORD_FILE` 这类 `_FILE` 变量从 secret 读。

### extends 与 include

**extends** 继承另一 service 的配置（同文件或跨文件），做 DRY：

```yaml
# common.yaml
services:
  base-web:
    init: true
    restart: unless-stopped
# compose.yaml
services:
  api:
    extends: { file: common.yaml, service: base-web }
    image: myapi:2.1.0
```

限制：不能 extends 用 `depends_on` / `volumes_from` / `links` 的 service；顶层 `networks` / `volumes` 不继承。

**include** 把多个 compose 文件合并成一个 stack（Compose Spec v5.0.0 稳定；用 OCI include 需 v2.40.2+ 以修 CVE-2025-62725 路径穿越）：

```yaml
include:
  - infra/db.yaml
  - oci://docker.io/org/stack:latest
```

`include` 比多 `-f` 更干净，适合「基础设施栈与应用栈分文件维护」。

### GPU / devices

单机用 GPU 走 `deploy.resources.reservations.devices`（2026 Spec 正式稳定，需 NVIDIA Container Toolkit）：

```yaml
services:
  ml:
    image: pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

注意：`deploy.resources.limits` 单机不生效（见关键字段），但 `reservations.devices` 在 Compose 下生效。

### develop / watch（开发热重载）

`develop.watch`（Compose 2.22.0+）把「改代码 → 重建 / 同步」自动化（inner loop）：

```yaml
services:
  web:
    build: .
    develop:
      watch:
        - action: sync        # 同步文件，不重建
          path: ./src
          target: /app/src
        - action: rebuild      # 改了依赖则重建镜像
          path: ./package.json
```

`action` 取值：`sync`（拷文件）、`rebuild`（重建镜像并重创容器）、`sync+restart`、`sync+exec`（同步后容器内跑命令，2.32+）、`restart`（2.32+）。`initial_sync` 在 `watch` 启动时先全量同步。开发期用 `docker compose watch` 启动。

### lifecycle hooks（pre_start / post_start / pre_stop）

Compose 5.3+ 支持生命周期钩子：`pre_start` 在 service 容器启动前跑一次性 init 容器（如数据库迁移），非零退出即中断启动；`post_start` / `pre_stop` 在已运行容器内执行命令。

```yaml
services:
  api:
    depends_on:
      db: { condition: service_healthy }
    pre_start:
      - command: ["./manage.py", "migrate"]
```

### x- 扩展字段与 YAML anchors

顶层 `x-` 开头的 key 被 Compose 忽略，配合 YAML anchors（`&` / `*`）做重复配置去重：

```yaml
x-logging: &logging
  driver: json-file
  options: { max-size: "10m", max-file: "3" }
services:
  api:
    <<: *logging
```

### 安全基线：read_only + tmpfs

把容器根文件系统挂只读、仅给少量 tmpfs 可写，缩小被入侵后的落脚点：

```yaml
services:
  app:
    read_only: true
    tmpfs:
      - /tmp
      - /run
```

> 这些进阶字段与 [Docker 安全](/docs/CS/Container/Docker/security.md) 的 capabilities / 非 root / seccomp 是同一套纵深防线的不同层。

## 能力边界

Compose 的定位是**单机开发/小型部署**，明确不解决的问题：

- **负载均衡**：`scale` 出多个容器后，Compose 不做流量分发，需要外部 LB 或 Swarm/K8s
- **服务发现与健康自愈**：只提供 DNS 名，没有"实例挂了自动补一个"的能力
- **跨主机**：[Swarm](/docs/CS/Container/Docker/swarm.md) 模式下可以用，但生态主流已转向 K8s
- **滚动更新、回滚、自动扩缩**：都归 [Kubernetes](/docs/CS/Container/k8s/K8s.md)

换句话说：Compose 适合"我在自己机器上把这套东西跑起来"，一旦进入多机、需要自愈和弹性，就该上 K8s。

## Links

- [Docker CLI](/docs/CS/Container/Docker/cli.md)
- [Docker 网络](/docs/CS/Container/Docker/net.md)
- [Docker 存储](/docs/CS/Container/Docker/storage.md)
- [Docker](/docs/CS/Container/Docker/Docker.md)
- [BuildKit](/docs/CS/Container/Docker/buildkit.md)

## References

1. [Docker Compose documentation](https://docs.docker.com/compose/)
2. [Compose file reference](https://docs.docker.com/reference/compose-file/)
3. [Compose releases](https://github.com/docker/compose/releases)
