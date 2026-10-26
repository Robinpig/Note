## Introduction

FastAPI **不自带 ORM**——这是与 [Django](/docs/CS/Framework/Django.md) 最实质的分工差异：Django 内置 ORM + 迁移 + admin，FastAPI 只提供 HTTP 层，数据访问要自己选型。社区主流组合是 **SQLAlchemy 2.0 + Alembic**。这里有两套独立类型需要分清：ORM 模型面向数据库（`Mapped[...]` 注解），Pydantic 模型面向 API 契约（`BaseModel`），二者通过 `response_model` + `from_attributes` 显式转换，不要直接把 ORM 对象返回（会连带暴露内部字段）。

版本基线：SQLAlchemy 稳定线 **2.0.54**（2.1 仍为 rc，且 2.1 起最低需 Python 3.11）；Alembic **1.20.0**（自 1.20.0 起要求 SQLAlchemy >= 2.0，1.4 支持已移除）。

## Async Session

用 `async_sessionmaker` 建会话工厂，把会话生命周期绑到请求上（配合 [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md) 的 yield 依赖）：

```py
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine(
    "postgresql+asyncpg://user:pwd@localhost/app",
    pool_pre_ping=True,      # 取连接前探活，避免拿到被数据库端断开的连接
    pool_size=5,
    max_overflow=10,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

`get_session` 就是 yield 依赖——请求进入时开连接、响应发出后归还连接池。驱动选型上：PostgreSQL 用 `postgresql+asyncpg`（或 psycopg 3 的 `postgresql+psycopg`），MySQL 用 `mysql+aiomysql`。

连接池的容量、超时与连接失效检测需按数据库侧的连接上限与 [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md) 的行为来配，不要照抄默认值。

## Declarative Model and Query

```py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column()
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped["User"] = relationship(back_populates="items")
```

SQLAlchemy 2.0 的查询风格是「构造 select 语句再执行」，不再是 1.4 的 `session.query()`：

```py
from sqlalchemy import select

@app.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)):
    stmt = select(Item).where(Item.price > 0).limit(50)
    rows = (await session.execute(stmt)).scalars().all()
    return rows
```

把 ORM 对象转成 Pydantic 响应模型：Pydantic v2 用 `model_config = ConfigDict(from_attributes=True)`（旧 `orm_mode=True` 已弃用），返回时由 `response_model` 按字段抽取。详见 [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)。

## Migrations with Alembic

Alembic 管 schema 版本，与 Django 的 `makemigrations` / `migrate` 职责对应，但工具链完全独立：

```shell
alembic init migrations                # 生成迁移环境
alembic revision --autogenerate -m "add items"   # 比对模型与库，自动生成迁移脚本
alembic upgrade head                   # 应用到数据库
```

`--autogenerate` 只做差异比对，**不能捕获全部变更**：重命名列（会被判成删+增）、数据回填、复杂约束都要手写迁移脚本。迁移脚本进版本库、可评审、可回滚，和 Django 迁移的定位一致。

## Links

- [FastAPI](/docs/CS/Framework/FastAPI.md)
- [Dependency Injection](/docs/CS/Framework/FastAPI/Dependency_Injection.md)
- [Request and Response](/docs/CS/Framework/FastAPI/Request_and_Response.md)
- [Django](/docs/CS/Framework/Django.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)

## References

- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [Alembic 文档](https://alembic.sqlalchemy.org/)
