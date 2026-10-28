## Introduction

FastAPI 应用（ASGI）的部署围绕"ASGI server + 多 worker + 反代"展开。关键点：Uvicorn 多 worker 用 **spawn**；Gunicorn 侧的 `uvicorn.workers` 已弃用，改用独立包 `uvicorn-worker`；容器里通常只跑单 worker，由编排器横向扩容。交互文档在生产环境建议关闭。

## Multiple Workers

Uvicorn 自带多 worker 模式（用 **spawn** 而非 pre-fork，能在 Windows 上工作）：

```shell
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

需要进程守护与优雅重启时用 Gunicorn。**注意 worker 类的写法已变**：`uvicorn.workers` 模块自 Uvicorn 0.30.0 起**已弃用**并计划移除，官方要求改用独立包 `uvicorn-worker`：

```shell
pip install uvicorn-worker
gunicorn main:app -w 4 -k uvicorn_worker.UvicornWorker
```

类路径是 `uvicorn_worker.UvicornWorker`（下划线），不是旧的 `uvicorn.workers.UvicornWorker`。网上大量教程仍在用旧写法，它现在仍能跑但会打弃用警告。

Gunicorn 26 起还提供了**原生 ASGI worker**（`-k asgi` / `--worker-class asgi`），不再依赖 Uvicorn：

```shell
gunicorn main:app --worker-class asgi --workers 4
```

它支持 HTTP/1.1 keepalive、WebSocket 与 lifespan 协议，可用 `--asgi-loop uvloop` 换事件循环、`--asgi-lifespan` 控制 lifespan 探测；并发上限用 `--worker-connections` 而非 `--threads`（ASGI worker 下 `--threads` 无效）。

## Containerization

容器里用 `fastapi run`（等价于 `uvicorn`）监听 `0.0.0.0`，多副本交给编排器而非容器内多 worker：

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]
```

用 uv 的 `uv.lock` 保证构建可复现；`--frozen` 禁止在构建期改动锁文件。容器内通常只跑 1 个 worker，由 K8s ReplicaSet 做横向扩容——容器内多进程会让 HPA 的 CPU 指标失真，也拿不到单进程内存限额。

## Reverse Proxy

单机前置 [Nginx](/docs/CS/CN/nginx/nginx.md) 处理 TLS、静态文件和负载均衡，把 `/api` 反代到 Uvicorn（`proxy_pass http://127.0.0.1:8000`）。容器化部署时 Nginx 与 Uvicorn 分容器编排即可。

## Documentation and Debugging

启动后访问：

- `http://127.0.0.1:8000/docs` — Swagger UI，可直接发请求调试
- `http://127.0.0.1:8000/redoc` — ReDoc 文档
- `http://127.0.0.1:8000/openapi.json` — OpenAPI 3 schema，可用于生成客户端 SDK

生产环境建议关掉交互式文档（`FastAPI(docs_url=None, redoc_url=None)`），或用反向代理限制访问路径。OpenAPI 的定制与 SDK 生成见 [OpenAPI and SDK Generation](/docs/CS/Framework/FastAPI/OpenAPI_and_SDK.md)。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Architecture](/docs/CS/Framework/FastAPI/Architecture.md)
- [Configuration and Observability](/docs/CS/Framework/FastAPI/Configuration_and_Observability.md)
- [OpenAPI and SDK Generation](/docs/CS/Framework/FastAPI/OpenAPI_and_SDK.md)
- [Nginx](/docs/CS/CN/nginx/nginx.md)

## References

- [Uvicorn 部署文档](https://www.uvicorn.org/deployment/)
- [uvicorn-worker (PyPI)](https://pypi.org/project/uvicorn-worker/)
- [Gunicorn ASGI Worker](https://gunicorn.org/asgi/)
