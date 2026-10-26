## Introduction

OpenAPI schema 是 FastAPI 的**契约产物**，不只是文档副产品——前后端、客户端 SDK、网关配置都从它派生。FastAPI 在启动时就根据路由签名自动生成 schema，并可在应用层定制元信息与分组。

## Customization

```py
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Item Service",
    version="1.0.0",
    openapi_tags=[{"name": "items", "description": "商品相关接口"}],
)
```

- **`openapi_tags`**：给 `tags` 配描述，在 Swagger UI 里显示为分组说明。
- **`openapi_extra`**：给单个路径操作塞厂商扩展字段（如 `x-internal: true`）。
- **统一错误响应**：用 `app.openapi_schema` 覆写生成的 schema，或在每个路由上用 `responses=` 声明常见错误码（见 [Routing](/docs/CS/Framework/FastAPI/Routing.md) 与 [Error Handling](/docs/CS/Framework/FastAPI/Error_Handling.md)）。

## SDK Generation

拿到 `/openapi.json` 后可生成客户端 SDK：

- `openapi-python-client`（基于 datamodel-code-generator）生成同步 Python 客户端；
- `openapi-generator` 生成 Java / TS / Go 等多语言客户端；
- `schemathesis` 拿 schema 做属性测试（property-based testing），自动生成边界用例。

契约一旦对外发布就该纳入版本管理：schema 变更等于接口变更，需评审与版本号同步。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Routing](/docs/CS/Framework/FastAPI/Routing.md)
- [Error Handling](/docs/CS/Framework/FastAPI/Error_Handling.md)
- [Deployment](/docs/CS/Framework/FastAPI/Deployment.md)
- [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)

## References

- [FastAPI 官方文档：Metadata and Docs URLs](https://fastapi.tiangolo.com/tutorial/metadata/)
- [openapi-generator](https://openapi-generator.tech/)
- [openapi-python-client](https://github.com/openapi-generator/openapi-python-client)
- [schemathesis](https://schemathesis.readthedocs.io/)
