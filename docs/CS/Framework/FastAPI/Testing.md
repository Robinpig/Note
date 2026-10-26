## Introduction

FastAPI 的 `TestClient` 来自 Starlette，同步调用即可驱动异步路由（内部自管事件循环），配合 pytest 做接口测试。核心技巧是依赖覆盖与异步驱动两种方式，前者在单测里替换 DB / 鉴权等外部依赖。

## TestClient

```py
from fastapi.testclient import TestClient
from main import app

def test_read_item():
    client = TestClient(app)
    r = client.get("/items/5?q=x")
    assert r.status_code == 200
    assert r.json()["item_id"] == 5
```

`TestClient` 同步 API 背后用 `httpx` + ASGI 传输模拟请求，所以即使路由是 `async def` 也能直接 `client.get(...)`。它还会自动跑 lifespan（启动/关闭），连接池等 `lifespan` 初始化的资源在测试里可用。

## Dependency Overrides

用 `app.dependency_overrides[get_db] = fake_get_db` 把数据库等外部依赖替换成假实现，单测不碰真实库：

```py
def fake_get_db():
    yield FakeSession()

app.dependency_overrides[get_db] = fake_get_db

def test_list():
    ...  # 此时路由里的 Depends(get_db) 拿到的是 FakeSession

# 测试结束后清理，避免泄漏到其它用例
del app.dependency_overrides[get_db]
```

覆盖按**依赖函数对象**全局匹配，必须在测试间清理（见 [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)）。

## Async Tests

需要更精细控制（如测试 lifespan 时序、流式响应）时用 `httpx.ASGITransport` 直接驱动 ASGI app，配合 `asyncio` 运行：

```py
import httpx
import pytest

@pytest.mark.asyncio
async def test_async():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/items/5")
        assert r.status_code == 200
```

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)
- [Data Layer](/docs/CS/Framework/FastAPI/Data_Layer.md)
- [Error Handling](/docs/CS/Framework/FastAPI/Error_Handling.md)
- [Background Tasks](/docs/CS/Framework/FastAPI/Background_Tasks.md)

## References

- [FastAPI 官方文档：Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Starlette 文档：TestClient](https://www.starlette.io/testclient/)
- [httpx 文档](https://www.python-httpx.org/)
