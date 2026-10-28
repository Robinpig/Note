## Introduction

FastAPI 的"类型即契约"集中体现在请求与响应处理上：函数参数的类型注解决定它从请求的哪个位置取、怎么校验；返回值的结构由 `response_model` 约束与过滤。这一层完全由 [Pydantic v2](https://docs.pydantic.dev/) 驱动，校验失败返回 **422** 而非 400。

## Pydantic Request Body

用 Pydantic `BaseModel` 声明请求体，FastAPI 自动完成 JSON 解析、类型校验（失败返回 422）和 OpenAPI schema 生成：

```py
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool | None = None

@app.post("/items")
async def create_item(item: Item):
    # item.name / item.price 已完成类型转换与校验，可直接使用
    return {"item_name": item.name, "price_with_tax": item.price * 1.13}
```

Pydantic v2 推荐用 `Annotated` + `Field` 承载约束元数据，这也是 FastAPI 契约的承载点（见 [Typing](/docs/CS/Python/Typing.md)）：

```py
from annotated_types import Gt
from typing import Annotated
from pydantic import BaseModel, Field

class Item(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: Annotated[float, Gt(0)]
```

`Annotated[...]` 之所以成立，正因为 `__metadata__` 在运行时读得到——FastAPI 与 pydantic 都靠它在运行时取约束。

## Parameter Sources

| 来源 | 声明方式 | 示例 |
| :--- | :--- | :--- |
| 路径参数 | 路径占位符 + 同名函数参数 | `/items/{item_id}` → `item_id: int` |
| 查询参数 | 普通函数参数（有默认值即可选） | `q: str \| None = None` |
| 请求体 | Pydantic Model 参数 | `item: Item` |
| Header | `Header()` | `user_agent: str = Header()` |
| Cookie | `Cookie()` | `session_id: str \| None = Cookie()` |
| 表单/文件 | `Form()` / `UploadFile` | `file: UploadFile` |

查询参数的"必需 vs 可选"由默认值决定：无默认值即必需；有默认值即可选。需要显式约束（如 `min_length`、正则）或把查询参数声明为 `Query(...)` 时，用 `Query` / `Path` / `Header` / `Cookie` 等 `Param` 子类包裹。

> [!WARNING]
>
> 类型注解与"是否必需"是两套语义：单注解 `q: str` 会被当成**必需查询参数**（无默认值），而不是可选。要可选必须给默认值 `q: str | None = None`。这是新手最常见的 422 来源。

## Response Model

通过 `response_model` 声明输出结构，可做字段过滤（如隐藏内部字段）和文档生成：

```py
class UserOut(BaseModel):
    username: str
    email: str

@app.get("/users/me", response_model=UserOut)
async def read_me():
    ...
```

注意点：

- `response_model` 默认**只输出模型中声明的字段**，多出来的内部字段被丢弃（等价于过滤），这是它和直接 `return` dict 的核心差异。
- Pydantic v2 下，从 ORM 对象转换到响应模型常用 `model_config = ConfigDict(from_attributes=True)`（旧写法 `orm_mode=True` 已弃用），或在 `response_model` 对应的模型上设该配置后用 `UserOut.model_validate(orm_obj)`。
- `response_model_exclude_unset=True` 可让"未显式赋值的字段"不出现在响应里，适合 PATCH 风格的局部更新。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Routing](/docs/CS/Framework/FastAPI/Routing.md)
- [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)
- [Architecture](/docs/CS/Framework/FastAPI/Architecture.md)
- [Typing](/docs/CS/Python/Typing.md)
- [Error Handling](/docs/CS/Framework/FastAPI/Error_Handling.md)

## References

- [Pydantic 文档](https://docs.pydantic.dev/)
- [FastAPI 官方文档：Body / Fields](https://fastapi.tiangolo.com/tutorial/body/)
- [FastAPI 官方文档：Query Parameters](https://fastapi.tiangolo.com/tutorial/query-params/)
