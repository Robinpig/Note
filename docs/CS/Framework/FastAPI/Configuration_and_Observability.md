## Introduction

FastAPI 自身没有配置系统（这点也和 Django 的 `settings.py` 不同），也没有内置采集方案——二者都要自己选。社区惯例是用 `pydantic-settings` 收敛配置，用标准库 / `structlog` / `prometheus-client` / OpenTelemetry 做可观测性。

## Configuration

用 `pydantic-settings` 把环境变量收敛成一个带类型、可校验的对象：

```py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    database_url: str
    debug: bool = False
    jwt_secret: str

settings = Settings()
```

- 字段名默认映射到同名环境变量（`APP_` 前缀 + 大写），也可用 `alias` 自定义。
- 校验在**导入时**完成：缺变量或类型不对会立刻抛错，而不是等到第一个请求才暴露。
- 生产环境用真实环境变量注入，`env_file` 只用于本地开发；密钥绝不入库、不进镜像层。
- 区分环境靠 `APP_ENV` 之类的开关，而不是在代码里 `if settings.debug` 分叉业务流程。

## Observability

```py
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}
```

- **健康检查**：`/healthz` 供编排系统探活；区分 liveness（进程活着）与 readiness（依赖就绪，如数据库可连）两个端点更稳。写进 `include_in_schema=False` 可让它不出现在 OpenAPI 文档里。
- **日志**：用标准库 `logging` 或 `structlog` 输出结构化日志；请求 ID 由中间件注入并在响应头回传（写法见 [Architecture](/docs/CS/Framework/FastAPI/Architecture.md) 的 `X-Process-Time` 中间件）。
- **指标**：`prometheus-client` 暴露 `/metrics`，注意用 `multiprocess` 模式配合多 worker 部署（否则每 worker 各自计数，聚合失真）。
- **链路追踪**：OpenTelemetry 的 `opentelemetry-instrumentation-fastapi` 可自动埋点；跨服务传播的思路与 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的 B3 头是同一类问题。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Architecture](/docs/CS/Framework/FastAPI/Architecture.md)
- [Deployment](/docs/CS/Framework/FastAPI/Deployment.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)

## References

- [pydantic-settings 文档](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [prometheus-client](https://github.com/prometheus/client_python)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
