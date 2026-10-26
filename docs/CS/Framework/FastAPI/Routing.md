## Introduction

路由是 FastAPI 把"URL + HTTP 方法"映射到"处理函数"的机制。小项目把所有路由直接写在 `app` 上即可；模块变多后用 `APIRouter` 拆分，再 `include_router` 装配，避免单文件膨胀。路由本身只解决"路径怎么分、怎么归类文档"，参数的来源与校验是 [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md) 的事。

## APIRouter

`APIRouter` 把一组相关路由收在一起，自带 `prefix` 与 `tags`：

```py
from fastapi import APIRouter

router = APIRouter(prefix="/items", tags=["items"])

@router.get("/{item_id}")
async def read_item(item_id: int):
    ...

app.include_router(router)
```

- `prefix`：给该 router 下所有路径加统一前缀（如 `/items`），handler 内只写相对路径。
- `tags`：在 OpenAPI / `/docs` 里把同组接口归类，是文档可读性的关键。
- `status_code`：声明成功状态码（如创建返回 201），写在路径操作装饰器上（`@router.post(..., status_code=201)`）。
- `responses`：补充非 2xx 的响应 schema（如 `responses={404: {"model": ErrorOut}}`），让文档覆盖错误情形。

## include_router 装配

大型项目通常按业务域分多个 `routers/xxx.py`，`main.py` 只负责创建 `app`、挂载中间件与 `include_router`：

```py
from fastapi import FastAPI
from .routers import items, users

app = FastAPI()
app.include_router(items.router)
app.include_router(users.router)
```

`include_router` 也可在装配时再追加 `prefix` / `tags` / `dependencies`（例如给一整组路由统一挂鉴权依赖，见 [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)）。

## 路径参数与匹配

路径占位符 `{name}` 与 handler 同名参数绑定（如 `/items/{item_id}` → `item_id: int`），类型注解驱动自动转换与校验；非法值由 [Pydantic](/docs/CS/Framework/FastAPI/Request_and_Response.md) 返回 422。FastAPI 的路由匹配发生在 Starlette 层，支持同路径多方法、以及 `Path` 声明约束（如 `gt` / `regex`）。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)
- [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)
- [Architecture](/docs/CS/Framework/FastAPI/Architecture.md)
- [OpenAPI and SDK Generation](/docs/CS/Framework/FastAPI/OpenAPI_and_SDK.md)

## References

- [FastAPI 官方文档：Routing](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Starlette 文档：Routing](https://www.starlette.io/routing/)
