## Introduction

依赖注入（DI）是 FastAPI 做横切逻辑的核心机制：用 `Depends` 声明"某个参数需要先跑一段逻辑再注入"，特别适合鉴权、数据库会话、分页参数等可复用的前置步骤。依赖本身可以再依赖别的依赖（嵌套），也可以在测试期整体替换。它与 [Security](/docs/CS/Framework/FastAPI/Security.md) 的凭证提取天然配合。

## Basic Depends

```py
from fastapi import Depends, HTTPException

async def get_token_header(x_token: str = Header()):
    if x_token != "secret":
        raise HTTPException(status_code=400, detail="X-Token header invalid")

@app.get("/admin/", dependencies=[Depends(get_token_header)])
async def admin():
    return {"msg": "authorized"}
```

`Depends(get_token_header)` 表示：进入路由前先调用 `get_token_header`，其返回值注入到对应参数。用 `dependencies=[...]`（装饰器参数）时依赖的返回值不注入、只做"前置校验/副作用"，常用于整组路由挂鉴权。

## Sub-dependencies and Reuse

依赖函数可以再声明自己的 `Depends`，形成依赖树；同一依赖在同一请求里**默认只执行一次**并缓存结果（可用 `Depends(..., use_cache=False)` 关闭）。数据库会话是最典型用例：请求开始时建 session、请求结束自动关闭（yield 依赖）。

```py
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session   # yield 之前的代码在请求前跑，之后的在响应后跑

@app.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)):
    ...
```

yield 依赖的"收尾"逻辑（关闭连接）由 FastAPI 在响应发出后驱动，即使路由抛异常也会执行——这是管理连接池生命周期的标准写法（具体会话工厂见 [Data Layer](/docs/CS/Framework/FastAPI/Data_Layer.md)）。

## Testing Overrides

测试时用 `app.dependency_overrides` 把外部依赖（DB、鉴权、第三方）替换成假实现，单测不碰真实库：

```py
def fake_get_session():
    ...

app.dependency_overrides[get_session] = fake_get_session
# 测试结束后记得 del app.dependency_overrides[get_session]
```

覆盖是**全局、按依赖函数对象**匹配的，必须在测试间清理，否则会泄漏到其它用例。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Security](/docs/CS/Framework/FastAPI/Security.md)
- [Data Layer](/docs/CS/Framework/FastAPI/Data_Layer.md)
- [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)
- [Testing](/docs/CS/Framework/FastAPI/Testing.md)

## References

- [FastAPI 官方文档：Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
