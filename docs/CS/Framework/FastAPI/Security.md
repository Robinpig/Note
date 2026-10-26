## Introduction

FastAPI 把鉴权拆成「提取凭证」与「校验逻辑」两层：`fastapi.security` 负责从请求里按标准方式取出 token / api key，真正的校验仍由 [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md) 包裹的函数完成。框架**不内置鉴权后端**——JWT 的签发与验签要自己接 `PyJWT` / `python-jose`。

这与 [Django](/docs/CS/Framework/Django.md) 相反：Django 自带 session + auth 中间件和 User 模型，开箱即用；FastAPI 更裸，靠 `Depends` 把任意鉴权逻辑组合进路由，灵活但要自己搭。

## Extractors

```py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer()

async def require_token(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> str:
    # 这里只演示提取；真实场景应校验签名 / 查库 / 查 Redis
    if creds.credentials == "invalid":
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials

@app.get("/secure")
async def secure(token: str = Depends(require_token)):
    return {"token": token}
```

可用的提取器：

- `HTTPBearer`：从 `Authorization: Bearer <token>` 取。
- `APIKeyHeader` / `APIKeyQuery`：API key（Header 或查询参数）。
- `OAuth2PasswordBearer`（配合 `tokenUrl` 自动生成 OAuth2 密码流文档）、`OAuth2AuthorizationCodeBearer`：OAuth2 流。

这些提取器会顺带把凭证信息接进 OpenAPI 文档（在 `/docs` 里出现"Authorize"按钮），但**不**做任何校验。

## JWT

JWT 的签发与验签需自己接 `PyJWT` / `python-jose`——FastAPI 只管「取出凭证并接到 OpenAPI 文档」，不内置鉴权后端。`require_token` 里应做：解析 JWT → 校验签名与过期 → 查黑名单/权限。把"取 token"和"验 token"都做成 `Depends`，就能在任意路由上组合复用。

## Comparison with Django

| 维度 | FastAPI | Django |
| :--- | :--- | :--- |
| 鉴权后端 | 无（靠 `Depends` + `fastapi.security` 自己搭） | 内置 session + auth 中间件 + User 模型 |
| 凭证提取 | `HTTPBearer` / `APIKey*` / `OAuth2*` 接文档 | 中间件统一处理 |
| 实时/长连接 | 原生 WebSocket（Starlette） | 需另引 Channels |
| ORM | 自选（SQLAlchemy 2.0 + Alembic） | 内置 ORM + 迁移 + admin |

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)
- [Async and WebSockets](/docs/CS/Framework/FastAPI/Async_and_WebSockets.md)
- [Error Handling](/docs/CS/Framework/FastAPI/Error_Handling.md)
- [Django](/docs/CS/Framework/Django.md)

## References

- [FastAPI 官方文档：Security](https://fastapi.tiangolo.com/tutorial/security/)
- [PyJWT 文档](https://pyjwt.readthedocs.io/)
