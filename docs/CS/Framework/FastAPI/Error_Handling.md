## Introduction

FastAPI 的错误表达分两条路径：业务/HTTP 语义错误用 `HTTPException` 主动抛出，参数与请求体校验失败由 Pydantic 自动返回 422。二者状态码与响应形态不同，需要统一错误 envelope 时再用自定义异常处理器改写。

## HTTPException

路径操作里用 `HTTPException` 中断请求并返回标准 JSON `{"detail": ...}`：

```py
from fastapi import HTTPException

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    if item_id < 0:
        raise HTTPException(status_code=404, detail="Item not found")
```

- 请求体/参数校验失败由 Pydantic 自动返回 **422**（不是 400），body 是字段级错误。
- 404 / 400 / 401 等才是 `HTTPException` 的常规语义码。

> [!NOTE]
>
> 422 vs 400 是 FastAPI 的刻意设计：422 Unprocessable Entity 表示"语法正确但语义/校验不通过"，专用于请求体验证失败；`HTTPException(status_code=400)` 是开发者主动抛的业务错误。混用会让客户端难以区分"输入格式错"与"业务拒绝"。

## Custom Exception Handler

自定义异常处理器可改写错误响应形态、统一错误 envelope：

```py
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "msg": exc.detail},
    )
```

注意 `response_model` 只约束正常返回，异常走处理器，不会套用 `response_model`——统一 envelope 必须在处理器里自己保证结构。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)
- [Security](/docs/CS/Framework/FastAPI/Security.md)
- [Testing](/docs/CS/Framework/FastAPI/Testing.md)
- [OpenAPI and SDK Generation](/docs/CS/Framework/FastAPI/OpenAPI_and_SDK.md)

## References

- [FastAPI 官方文档：Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
